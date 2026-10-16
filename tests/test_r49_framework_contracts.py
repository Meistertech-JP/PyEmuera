"""Independent Framework measurements, separate from historical local models."""
import gzip
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pyemuera.collation_portable import PortableNLSBackend
import pyemuera.sort1824 as sort_module
from test_core import Harness

FIXTURE = Path(__file__).parent / 'fixtures/r49'


def load(name):
    pins = {
        'burned49101551': '73b60ca6b8ad9c0a14761fa9e5efa241ec688817b6aa4f68f55b0e675a6d4a9e',
        'prefix_alignment': '4d6b753a4c511480931862550e2e86f9e4d1476f3f7bf7424974f574dee18672',
        'burned49101550': '76a5b248d07c8d4e20725a08cfdba8c112dbf1b23bd755fa19357ffedbb94fa1',
        'both_separators': '9a951917394362290baeafab17c8e82a49b2116e1262f84eaeda1deda2280ec8',

        'burned49101549': '0bd649647dad66ae901da841a0015aa5c0bbcc9c43daf97bfd9fda904fac6b9b',
        'alignment': '5d8f88e46975970b7f54074686f7dffa8f15ede80e48caaf97cf0d05e5eda9ca',

        'contract': '16e9b9911dd45784872042680a02513af801d48d975dcdf1b3209c7cb2d1d6bd',
        'development': 'b8b03ae80bc1e97924d0515811f0800b4cb951202216270cbe55950f76d1aa72',
        'r48_official': 'aaca63f56b0369a344ea79802388c49a8b329a5f662808fe86ab9674e9b0c598',
    }
    raw = (FIXTURE / (name + '.json.gz')).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == pins[name]
    return json.loads(gzip.decompress(raw))


def values(oracle):
    return [bytes.fromhex(h).decode('utf-16-le', 'surrogatepass') for h in oracle['inputs_utf16le_hex']]


class FrameworkContractsR49(unittest.TestCase):
    def check_pairs(self, name, group=None):
        oracle = load(name)['oracle']
        strings = values(oracle)
        backend = PortableNLSBackend()
        rows = [row for row in oracle['pairs'] if group is None or row['group'] == group]
        for row in rows:
            self.assertEqual(row['CompareTo_sign'], row['CompareInfo_None_sign'])
            if 'NLS_sign' in row:
                self.assertEqual(row['CompareTo_sign'], row['NLS_sign'])
            self.assertEqual(backend.compare(strings[row['left']], strings[row['right']]), row['CompareTo_sign'], row)
        return len(rows)

    def test_original_random_10000_against_framework_direct_comparison(self):
        self.assertEqual(self.check_pairs('contract', 'old_random_10000'), 10000)

    def test_original_boundary_292_against_framework_direct_comparison(self):
        self.assertEqual(self.check_pairs('contract', 'boundary292'), 292)

    def test_all_5177_original_inputs_have_raw_framework_sortkeys(self):
        import r43_source_collation_model as model
        oracle = load('contract')['oracle']
        available = dict(zip(oracle['inputs_utf16le_hex'], oracle['sort_keys_hex']))
        original = model.review_inputs()
        self.assertEqual(len(original), 5177)
        for text in original:
            raw = bytes.fromhex(available[text.encode('utf-16-le', 'surrogatepass').hex()])
            self.assertIs(type(raw), bytes)
            self.assertTrue(raw.endswith(b'\0'))

    def test_jamo_only_primary_bytes_match_measured_framework(self):
        oracle = load('contract')['oracle']
        backend = PortableNLSBackend()
        count = 0
        for text, native in zip(values(oracle), oracle['sort_keys_hex'], strict=True):
            if text and all(ord(char) in backend._jamo for char in text):
                # Full key serialization is intentionally a portable format.
                # This assertion compares the measured primary stream only.
                self.assertEqual(backend.sort_key(text).split(b'\1')[0], bytes.fromhex(native).split(b'\1')[0])
                count += 1
        self.assertEqual(count, 1860)

    def test_r48_all_4400_known_framework_pairs(self):
        self.assertEqual(self.check_pairs('r48_official'), 4400)

    def test_unequal_separator_prefix_development_grid(self):
        count = self.check_pairs('development', 'prefix-grid')
        self.assertEqual(count, 19600)

    def test_shared_leading_all_1280_native_pairs(self):
        self.assertEqual(self.check_pairs('development', 'shared-leading'), 1280)

    def test_burned_first_r49_holdout_all_4400_pairs(self):
        self.assertEqual(self.check_pairs('burned49101549'), 4400)

    def test_alignment_22532_native_development_pairs(self):
        self.assertEqual(self.check_pairs('alignment'), 22532)

    def test_burned_second_r49_holdout_all_4400_pairs(self):
        self.assertEqual(self.check_pairs('burned49101550'), 4400)

    def test_both_separator_development_58932_native_pairs(self):
        self.assertEqual(self.check_pairs('both_separators'), 58932)

    def test_superseded_third_r49_population_all_4400_pairs(self):
        self.assertEqual(self.check_pairs('burned49101551'), 4400)

    def test_modern_leading_prefix_alignment_18432_native_pairs(self):
        oracle = load('prefix_alignment')['oracle']
        strings = values(oracle)
        backend = PortableNLSBackend()
        count = 0
        for row in oracle['pairs']:
            left, right = strings[row['left']], strings[row['right']]
            first = next((ord(c) for c in left if ord(c) in backend._jamo), None)
            if first is not None and 0x1100 <= first <= 0x1112:
                self.assertEqual(backend.compare(left, right), row['CompareTo_sign'])
                count += 1
        self.assertEqual(count, 18432)

    def test_short_trailing_counterexamples_and_reverse(self):
        backend = PortableNLSBackend()
        for left, right, expected in [('\u11b5', '\x01\u11b0', -1), ('\u11b7\u11b7', '\x01\u11bd', 1)]:
            self.assertEqual(backend.compare(left, right), expected)
            self.assertEqual(backend.compare(right, left), -expected)

    def test_filler_is_a_cluster_member_during_alignment(self):
        self.assertEqual(PortableNLSBackend().compare('\u115f\u1160\u11c2', '\u00ad\x01\u115f\u1160\u11bf\u115f\u1160\u11b9;4'), -1)

    def test_compatibility_forms_keep_measured_vowel_trailing_path(self):
        backend = PortableNLSBackend()
        oracle = load('development')['oracle']
        strings = values(oracle)
        checked = 0
        for row in oracle['pairs']:
            left, right = strings[row['left']], strings[row['right']]
            if any(0x3131 <= ord(char) <= 0x318e for char in left + right):
                self.assertEqual(backend.compare(left, right), row['CompareTo_sign'])
                checked += 1
        self.assertGreater(checked, 0)

    def test_r48_all_48_sort_orders_and_complete_call_traces(self):
        self.check_sort_traces('r48_official')
        self.check_sort_traces('burned49101549')
        self.check_sort_traces('burned49101550')
        self.check_sort_traces('burned49101551')

    def check_sort_traces(self, name):
        data = load(name)
        strings = values(data['oracle'])
        backend = PortableNLSBackend()
        original = sort_module._intro_sort
        self.assertEqual(len(data['arrays']), 48)
        for plan, expected in zip(data['arrays'], data['oracle']['sorts'], strict=True):
            calls = []
            active = False

            def entry(items, compare, low, high, depth):
                nonlocal active
                if active:
                    return original(items, compare, low, high, depth)

                def logged(left, right):
                    sign = compare(left, right)
                    calls.append({'call_index': len(calls), 'left_original_row': left[1],
                                  'right_original_row': right[1], 'comparison_sign': sign})
                    return sign
                active = True
                try:
                    return original(items, logged, low, high, depth)
                finally:
                    active = False

            with self.subTest(case=plan['name']), patch.object(sort_module, '_intro_sort', entry), patch('pyemuera.collation1824.compare_strings', backend.compare):
                self.assertIsNone(expected['exception'])
                self.assertEqual(sort_module.framework_list_order([strings[i] for i in plan['inputs']], string=True), expected['order'])
                self.assertEqual(calls, expected['calls'])


class ArrayStateR49(Harness):
    def test_r48_48_arrays_related_rows_result_and_rng(self):
        self.check_array_states('r48_official')
        self.check_array_states('burned49101549')
        self.check_array_states('burned49101550')
        self.check_array_states('burned49101551')

    def check_array_states(self, name):
        data = load(name)
        strings = values(data['oracle'])
        backend = PortableNLSBackend()
        for plan, expected in zip(data['arrays'], data['oracle']['sorts'], strict=True):
            size = len(plan['inputs'])
            vm = self.make(headers=f'#DIMS KEYS,{size}\n#DIM ROWS,{size},2')
            keys = [strings[i] for i in plan['inputs']]
            for i, text in enumerate(keys):
                vm.set(f'KEYS:{i}', text)
                vm.set(f'ROWS:{i}:0', i)
                vm.set(f'ROWS:{i}:1', 1000 + i)
            vm.set('RESULT', 917)
            rng = vm.rng.getstate()
            with patch('pyemuera.collation1824.compare_strings', backend.compare):
                self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 1)
            self.assertEqual(vm.get('RESULT'), 917)
            self.assertEqual(vm.rng.getstate(), rng)
            self.assertEqual([vm.get(f'KEYS:{i}') for i in range(size)], [keys[i] for i in expected['order']])
            self.assertEqual([vm.get(f'ROWS:{i}:0') for i in range(size)], expected['order'])
            self.assertEqual([vm.get(f'ROWS:{i}:1') for i in range(size)], [1000 + i for i in expected['order']])
