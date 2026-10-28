"""Direct Framework comparisons and input-derived state, separate from sort keys."""
import gzip
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pyemuera.collation_portable import PortableNLSBackend, _utf16_units
from pyemuera.collation_direct_jamo import DirectJamoComparison, direct_jamo_sign


class DirectJamoState(unittest.TestCase):
    def setUp(self):
        self.backend = PortableNLSBackend()

    def test_all_36864_fixed_framework_directions(self):
        path = Path(__file__).parent / 'fixtures/r49/prefix_alignment.json.gz'
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '4d6b753a4c511480931862550e2e86f9e4d1476f3f7bf7424974f574dee18672')
        oracle = json.loads(gzip.decompress(raw))['oracle']
        values = [bytes.fromhex(h).decode('utf-16le') for h in oracle['inputs_utf16le_hex']]
        self.assertEqual(len(oracle['pairs']), 36864)
        for i, row in enumerate(oracle['pairs']):
            self.assertEqual(row['CompareTo_sign'], row['CompareInfo_None_sign'])
            self.assertEqual(row['CompareTo_sign'], row['NLS_sign'])
            left, right = values[row['left']], values[row['right']]
            self.assertEqual(self.backend.compare(left, right), row['CompareTo_sign'], i)
            # The new loop itself resolves every direction, without a fallback.
            self.assertEqual(direct_jamo_sign(self.backend, left, right, _utf16_units), row['CompareTo_sign'], i)

    def test_independent_native_ending_controls(self):
        left = '\u1113\0\u1162'
        for a, b, expected in (
            (left, '\x01\u1113\u11ae\u11b5', -1),
            (left, '\x01\u1113\u11ae', 1),
            (left, '\x01\u1113\u11ae\0', 1),
            ('\u1113\0', '\x01\u1113\u11ae\u11b5', -1),
            (left, '\x01\u1113\u11ae\u1162', -1),
            ('\x01\u1113\u11ae\u11b5', left, 1),
        ):
            with self.subTest(left=a, right=b):
                self.assertEqual(self.backend.compare(a, b), expected)

    def test_cached_mapper_sample_categories_survive_one_sided_skip(self):
        model = DirectJamoComparison(self.backend)
        result = model.compare(_utf16_units('\u1113\0\u1162'),
                               _utf16_units('\x01\u1113\u11ae\u11b5'), trace=True)
        self.assertEqual(result, -1)
        samples = [event['samples'] for event in model.events if event.get('kind') == 'samples']
        self.assertEqual(samples, [
            [0x020804ac, 0x02020603],
            [0x0202c6f9, 0x020804ac],
            [0, 0x04b004b0],
            [0x02a504ed, 0x0202ec97],
        ])
        maps = [(e['side'], e['start'], e['consumed']) for e in model.events if e.get('kind') == 'map']
        self.assertEqual(maps, [('left', 0, 1), ('right', 1, 2), ('right', 3, 1), ('left', 2, 1)])

    def test_jamo_common_prefix_restarts_original_buffers(self):
        model = DirectJamoComparison(self.backend)
        model.compare(_utf16_units('a\u1113\0\u1162'),
                      _utf16_units('a\u1113\u11ae\u11b5'), trace=True)
        self.assertEqual(model.events[0]['cursor'], [0, 0])

    def test_non_jamo_common_prefix_keeps_skip(self):
        model = DirectJamoComparison(self.backend)
        model.compare(_utf16_units('a\u1113\0\u1162'),
                      _utf16_units('a\x01\u1113\u11ae\u11b5'), trace=True)
        self.assertEqual(model.events[0]['cursor'], [1, 1])

    def test_ordinary_input_avoids_state_allocation(self):
        with patch('pyemuera.collation_direct_jamo.DirectJamoComparison', side_effect=AssertionError):
            self.assertIsNone(direct_jamo_sign(self.backend, '日本語', 'normal', _utf16_units))

    def test_other_script_categories_keep_existing_path(self):
        self.assertIsNone(direct_jamo_sign(self.backend, '\u1113\u00df', '\u1113a', _utf16_units))

    def test_independent_structural_and_mixed_framework_controls(self):
        folder = Path(__file__).parent / 'fixtures/post_b1_direct'
        manifest = json.loads((folder / 'MANIFEST.json').read_text(encoding='utf8'))
        self.assertEqual(sum(row['directions'] for row in manifest.values()), 11191)
        for name, item in manifest.items():
            raw = (folder / (name + '.json.gz')).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item['fixture_sha256'])
            oracle = json.loads(gzip.decompress(raw))
            values = [bytes.fromhex(h).decode('utf-16le', 'surrogatepass') for h in oracle['inputs_utf16le_hex']]
            self.assertEqual(len(oracle['pairs']), item['directions'])
            for i, row in enumerate(oracle['pairs']):
                expected = row['CompareTo_sign']
                self.assertEqual(expected, row['CompareInfo_None_sign'])
                self.assertEqual(expected, row['NLS_sign'])
                self.assertEqual(self.backend.compare(values[row['left']], values[row['right']]), expected, (name, i))

    def test_nonspace_tail_preserves_canonical_equality(self):
        prefix = '\u1113\u1162\u11ae'
        self.assertEqual(self.backend.compare(prefix + '\u00e9', prefix + 'e\u0301'), 0)
        self.assertEqual(self.backend.compare(prefix + 'e\u0301', prefix + '\u00e9'), 0)

    def test_internal_invalid_kana_cache_is_distinct_from_input_weight(self):
        from pyemuera.collation_direct_jamo import Side
        model = DirectJamoComparison(self.backend)
        side = Side(_utf16_units('\u309d'))
        side.cache = model.word(side.units[0])
        self.assertEqual(model.kana(side), [0, 0, 0, 0])
        self.assertEqual(side.cache, 0xffff)
        self.assertTrue(side.invalid_kana_cache)
        side.advance()
        self.assertFalse(side.invalid_kana_cache)
        self.assertIsNone(side.cache)

    def test_nonspace_entry_matches_entire_fixed_bmp_category(self):
        from pyemuera.collation_direct_jamo import _NONSPACE
        matched = {cp for cp in range(65536) if _NONSPACE.fullmatch(chr(cp))}
        expected = {cp for cp in range(65536) if self.backend._weight(cp)[0] == 1}
        self.assertEqual(len(expected), 500)
        self.assertEqual(matched, expected)

    def test_non_jamo_separator_and_nonspace_boundaries(self):
        for separator, expected in (('\0', 1), ('\xad', 1), ('\x7f', 1), ('\x01', 1)):
            left, right = '\u00e9', 'e' + separator + '\u0301'
            self.assertEqual(self.backend.compare(left, right), expected)
            self.assertEqual(self.backend.compare(right, left), -expected)
        self.assertEqual(self.backend.compare('\u00e9', 'e\u0301'), 0)

    def test_custom_string_hooks_keep_existing_path(self):
        class Special(str):
            def encode(self, *args, **kwargs):
                raise AssertionError('special encoding must not be consulted')
        self.assertIsNone(direct_jamo_sign(self.backend, Special('\u1113'), '\u1114', _utf16_units))

    def test_comparisons_do_not_retain_pending_state(self):
        left, right = '\u1113\0\u1162', '\x01\u1113\u11ae\u11b5'
        for _ in range(3):
            self.assertEqual(self.backend.compare(left, right), -1)
            self.assertEqual(self.backend.compare(right, left), 1)
            self.assertEqual(self.backend.compare(left, left), 0)


if __name__ == '__main__':
    unittest.main()
