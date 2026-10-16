"""Context/weight invariants outside the archived Framework input matrices.

These tests are local checks of the documented reconstructed profile. They do
not turn their additional strings into native Windows observations. Full raw
oracle replay and an independently parsed model have separate test owners.
"""

import itertools
import unittest
from unittest.mock import patch

from pyemuera.collation_jamo import interpret_jamo, jamo_class, JamoClass
from pyemuera.collation_portable import PortableNLSBackend, _Streams, _utf16_units


class CollationContextR43(unittest.TestCase):
    def setUp(self):
        self.backend = PortableNLSBackend(cache_size=32)

    def test_flat_profile_has_every_special_jamo_record(self):
        special = {
            code_unit
            for code_unit in range(65536)
            if self.backend._weight(code_unit)[0] == 4
        }
        self.assertEqual(len(special), 357)
        self.assertEqual(special, set(self.backend._jamo))

    def test_extension_ranges_keep_their_l_v_t_classes(self):
        for character, expected in (
            (0x1100, JamoClass.LEADING),
            (0x115F, JamoClass.LEADING),
            (0xA960, JamoClass.LEADING),
            (0x1160, JamoClass.VOWEL),
            (0x11A7, JamoClass.VOWEL),
            (0xD7B0, JamoClass.VOWEL),
            (0x11A8, JamoClass.TRAILING),
            (0x11FF, JamoClass.TRAILING),
            (0xD7CB, JamoClass.TRAILING),
        ):
            with self.subTest(character=character):
                self.assertEqual(jamo_class(character), expected)

    def test_all_published_singletons_have_keys_without_unsupported(self):
        for code_unit in self.backend._jamo:
            text = chr(code_unit)
            with self.subTest(code_unit=code_unit):
                self.assertIsInstance(self.backend.sort_key(text), bytes)
                self.assertEqual(self.backend.compare(text, text), 0)

    def test_modern_decomposition_is_not_normalized_to_a_syllable(self):
        # Raw received Framework matrix: the modern decomposed LV/LVT remain
        # separate linguistic elements, unlike NFC composition.
        self.assertLess(self.backend.compare('\u1100\u1161', '\uac00'), 0)
        self.assertLess(self.backend.compare('\u1100\u1161\u11a8', '\uac01'), 0)

    def test_old_cluster_uses_context_but_keeps_code_units(self):
        units = _utf16_units('\u1112\u119e\u11abx')
        emission = interpret_jamo(
            units, 0, self.backend._jamo, self.backend._weight
        )
        self.assertEqual(emission.consumed, 3)
        self.assertEqual(units, (0x1112, 0x119E, 0x11AB, ord('x')))
        self.assertEqual(emission.extra_elements, 3)

    def test_repeated_class_and_reversed_class_end_the_cluster(self):
        for text in ('\u1113\u1114\u119e', '\u119e\u1113\u11ab',
                     '\u11cb\u119e'):
            units = _utf16_units(text)
            with self.subTest(text=text):
                emission = interpret_jamo(
                    units, 0, self.backend._jamo, self.backend._weight
                )
                self.assertEqual(emission.consumed, 1)

    def test_non_jamo_and_weightless_units_end_context_lookahead(self):
        for separator in ('\0', '\u0301', '\ud800', '-', 'a'):
            units = _utf16_units('\u1113' + separator + '\u119e')
            with self.subTest(separator=separator):
                emission = interpret_jamo(
                    units, 0, self.backend._jamo, self.backend._weight
                )
                self.assertEqual(emission.consumed, 1)

    def test_scalar_and_surrogate_pair_neighbors_have_identical_keys(self):
        for body in ('\u1113\u119e\u11cb', '\u1100\u1161', '\ud7b0'):
            with self.subTest(body=body):
                self.assertEqual(
                    self.backend.sort_key('😀' + body + '𐐀'),
                    self.backend.sort_key('\ud83d\ude00' + body + '\ud801\udc00'),
                )

    def test_context_does_not_call_unicode_normalization(self):
        with patch('unicodedata.normalize', side_effect=AssertionError('normalization')):
            self.backend.sort_key('\u1113\u119e\u11cb')
            self.backend.sort_key('\u1100\u1161\u11a8')
            self.backend.sort_key('a-\u00e9\0\ud800')

    def test_unreceived_contexts_remain_reflexive_and_antisymmetric(self):
        # Extension A/B, class reversal, repeated classes, separators and
        # old/modern mixtures are LOCAL_MODEL coverage, not native oracle rows.
        sample = ('\ua960\u1171\u11ff', '\u1114\u1162\ud7cb',
                  '\u119e\u11c5', '\u1113\u1113\u119e',
                  '\u1171\u1171', '\u11ff\ua961',
                  '\u115f\ud7c6\ud7fb', '\u1113\0\u119e')
        for left, right in itertools.product(sample, repeat=2):
            with self.subTest(left=left, right=right):
                self.assertEqual(self.backend.compare(left, left), 0)
                self.assertEqual(
                    self.backend.compare(left, right),
                    -self.backend.compare(right, left),
                )

    def test_context_and_word_keys_reuse_the_bounded_cache(self):
        for index in range(90):
            self.backend.sort_key('\u1113\u119e\u11cb-' + str(index))
        first = self.backend.cache_info()
        key = self.backend.sort_key('\u1113\u119e\u11cb-89')
        second = self.backend.cache_info()
        self.assertEqual(first.currsize, 32)
        self.assertEqual(second.hits, first.hits + 1)
        self.assertEqual(key, self.backend.sort_key('\u1113\u119e\u11cb-89'))

    def test_later_word_punctuation_positions_sort_first(self):
        for word in ('abc', '12', 'Éa', 'カあ'):
            leading = '-' + word
            middle = word[:1] + '-' + word[1:]
            trailing = word + '-'
            with self.subTest(word=word):
                self.assertLess(self.backend.compare(trailing, middle), 0)
                self.assertLess(self.backend.compare(middle, leading), 0)
                self.assertLess(self.backend.compare(word, trailing), 0)

    def test_word_position_counts_elements_in_three_byte_pua(self):
        streams = _Streams()
        streams.normal((0xA9, 0x10, 0x20, 2))
        streams.normal((14, 9, 2, 2))
        self.assertEqual(len(streams.primary), 6)
        self.assertEqual(streams.primary_elements, 2)
        streams.punctuation((6, 0x82, 2, 2))
        # r45 stores a prefix-free full element position, not wrapped 16 bits.
        self.assertEqual(streams.special, bytes.fromhex('0001fd0682'))

    def test_long_marks_keep_existing_byte_arithmetic(self):
        body = '\u1113\u119e\u11cb'
        # Each U+3099 adds 3 with BYTE wrapping; 256 marks add 0 mod256.
        self.assertEqual(
            self.backend.sort_key(body + '\u3099' * 256),
            self.backend.sort_key(body),
        )


if __name__ == '__main__':
    unittest.main()
