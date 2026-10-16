"""Captured Windows rule regressions and separate local ordering properties.

The complete new 31,991-pair replay remains a separate verification population.
Its one unresolved partial-cluster comparison is preserved in this fixture;
the source preservation test does not turn that disagreement into a success.
Unmeasured lengths below check local properties, not new Windows observations.
"""

import gzip
import hashlib
import json
from pathlib import Path
import unittest

from pyemuera.collation_portable import PortableNLSBackend, _Streams


FIXTURE = Path(__file__).resolve().parent / 'fixtures/r45_collation'
ORACLE = json.loads(gzip.decompress((FIXTURE / 'oracle_rule_excerpts.json.gz').read_bytes()))


def decoded(value):
    return bytes.fromhex(value).decode('utf-16-le', 'surrogatepass')


class CollationRulesR45(unittest.TestCase):
    def setUp(self):
        self.backend = PortableNLSBackend()

    def observed_case(self, index):
        return next(
            row for row in ORACLE['cases']
            if row['population'] == 'main' and row['comparison_index'] == index
        )

    def check_observation(self, index):
        row = self.observed_case(index)
        left, right = decoded(row['left_utf16le_hex']), decoded(row['right_utf16le_hex'])
        self.assertEqual(self.backend.compare(left, right), row['sign'])
        self.assertEqual(self.backend.compare(right, left), -row['sign'])

    def test_excerpt_bytes_are_hash_pinned(self):
        for row in json.loads((FIXTURE / 'catalog.json').read_text())['files']:
            raw = (FIXTURE / row['path']).read_bytes()
            self.assertEqual(len(raw), row['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
        self.assertTrue(ORACLE['expected_signs_not_generated_from_candidate'])

    def test_unresolved_oracle_original_utf16_and_sign_are_preserved(self):
        row = self.observed_case(5613)
        self.assertEqual(row['status'], 'UNRESOLVED')
        self.assertEqual(row['left_utf16le_hex'], '131162112700ab11610062006300')
        self.assertEqual(row['right_utf16le_hex'], '31fe13116211ab11610062006300')
        self.assertEqual(row['sign'], 1)

    def test_captured_old_leading_cluster_is_before_first_vowel(self):
        self.check_observation(2541)

    def test_captured_old_trailing_cluster_keeps_leading_group(self):
        self.check_observation(2906)

    def test_captured_filler_context_keeps_primary_element_boundaries(self):
        self.check_observation(676)

    def test_captured_vowel_start_retains_independent_jamo(self):
        self.check_observation(749)

    def test_captured_leading_without_vowel_remains_independent(self):
        self.check_observation(25378)

    def test_captured_old_leading_offset_follows_primary_continuation(self):
        self.check_observation(7033)

    def test_captured_old_leading_repetition_and_old_trailing_priority(self):
        self.check_observation(7274)

    def test_captured_modern_leading_old_vowel_boundary(self):
        self.check_observation(3424)

    def test_captured_leading_filler_can_start_trailing_context(self):
        self.check_observation(14719)

    def test_captured_leading_filler_can_start_modern_vowel_context(self):
        self.check_observation(13602)

    def test_captured_mixed_context_excerpts_match_in_both_directions(self):
        rows = [
            row for row in ORACLE['cases']
            if row['population'] == 'main' and row['status'] == 'CAPTURED_EXPECTATION'
        ]
        self.assertEqual(len(rows), 35)
        for row in rows:
            self.check_observation(row['comparison_index'])

    def test_captured_long_excerpts_match_in_both_directions(self):
        rows = [row for row in ORACLE['cases'] if row['population'] == 'long']
        self.assertEqual(len(rows), 24)
        for row in rows:
            left = decoded(row['left_utf16le_hex'])
            right = decoded(row['right_utf16le_hex'])
            self.assertEqual(self.backend.compare(left, right), row['sign'])
            self.assertEqual(self.backend.compare(right, left), -row['sign'])

    def test_local_unmeasured_hyphen_positions_do_not_wrap(self):
        for count in (255, 256, 511, 512, 8179, 8192, 8201, 16384, 16397, 32771):
            text = 'r' * count
            self.assertGreater(self.backend.compare('-' + text, text + '-'), 0)

    def test_local_unmeasured_punctuation_positions_are_ordered(self):
        text = 'r' * 11003
        values = [text + '-', text[:7335] + '-' + text[7335:],
                  text[:1227] + '-' + text[1227:], '-' + text]
        for left, right in zip(values, values[1:]):
            self.assertLess(self.backend.compare(left, right), 0)

    def test_local_unbounded_position_encoding_is_not_machine_integer_sized(self):
        keys = []
        for count in (0, 255, 256, 65535, 65536, 1 << 80, 1 << 2048):
            stream = _Streams()
            stream.primary_elements = count
            stream.punctuation((6, 130, 2, 2))
            keys.append(bytes(stream.special))
        for earlier, later in zip(keys, keys[1:]):
            self.assertGreater(earlier, later)

    def test_local_cache_reuses_cluster_and_long_key(self):
        backend = PortableNLSBackend(cache_size=2)
        values = ['q\u1115\u1164\u11a9e', '\u3402' * 4107 + '-']
        first = [backend.sort_key(value) for value in values]
        before = backend.cache_info()
        second = [backend.sort_key(value) for value in values]
        self.assertEqual(first, second)
        self.assertEqual(backend.cache_info().hits, before.hits + 2)
        self.assertEqual(backend.cache_info().currsize, 2)

    def test_local_long_utf16_inputs_preserve_original_units(self):
        values = ['\ud800r\udfff', '\0\u1114\u1163\u11a9\0',
                  '\ud83d\ude00' * 4109 + '-', 'r\u3099' * 8203]
        for value in values:
            original = value.encode('utf-16-le', 'surrogatepass')
            self.assertEqual(self.backend.compare(value, value), 0)
            self.assertIsInstance(self.backend.sort_key(value), bytes)
            self.assertEqual(value.encode('utf-16-le', 'surrogatepass'), original)


if __name__ == '__main__':
    unittest.main()
