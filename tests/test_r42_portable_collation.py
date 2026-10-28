"""Pinned source-model tests plus the received Framework comparison oracle.

r45 canonical portable keys contain explicit third primary components and a
separate old-Jamo leading-offset level. These byte literals test our declared
representation, not Windows sort-key bytes (which were not captured).

Additional source-model examples are not fresh native Windows observations.
Expected keys come from Microsoft source rows/stages, never this comparator's
output. ARRAYMSORT integration/permutations are tested by their separate owner.
"""
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zlib

from pyemuera.collation_portable import PortableNLSBackend
from pyemuera.errors import EraError, Unsupported


ROOT = Path(__file__).resolve().parents[1]


class PortableCollationR42(unittest.TestCase):
    def setUp(self):
        self.backend = PortableNLSBackend(cache_size=128)

    def test_received_framework_300_pair_signs(self):
        fixture = json.loads((ROOT/'tests/fixtures/r42_framework_string_probe.json').read_text('utf-8-sig'))
        self.assertEqual(len(fixture['comparisons']), 300)
        self.assertEqual((fixture['CultureInfo'], fixture['CompareOptions']), ('ja-JP', 'None'))
        for row in fixture['comparisons']:
            with self.subTest(left=row['left'], right=row['right']):
                self.assertEqual(self.backend.compare(row['left'], row['right']), row['sign'])
                self.assertEqual(self.backend.compare(row['right'], row['left']), -row['sign'])

    def test_source_default_latin_weights_and_case(self):
        # Windows 10 DEFAULT U+0062=(14,9,2,2), U+0042=(14,9,2,18).
        self.assertEqual(self.backend.sort_key('b'), bytes.fromhex('0e0902010101010100'))
        self.assertEqual(self.backend.sort_key('B'), bytes.fromhex('0e090201010112010100'))
        self.assertLess(self.backend.compare('b', 'B'), 0)

    def test_source_japanese_exception_pronunciation_order(self):
        # ja-JP exception rows: 亜=(196,8,2,2), 愛=(196,13,2,2), 悪=(196,20,2,2).
        self.assertEqual(self.backend.sort_key('亜'), bytes.fromhex('c40802010101010100'))
        self.assertLess(self.backend.compare('亜', '愛'), 0)
        self.assertLess(self.backend.compare('愛', '悪'), 0)

    def test_source_japanese_backslash_yen_exception(self):
        # Japanese exception U+005C maps to the U+00A5 weights (7,154,2,2).
        self.assertEqual(self.backend.sort_key('\\'), bytes.fromhex('079a02010101010100'))
        self.assertEqual(self.backend.compare('x\\y', 'x¥y'), 0)

    def test_latin_combining_marks_and_japanese_different_weights(self):
        # é DW14=e DW2+acute12. Kana Ba DW3 differs from Ha2+daku3=5.
        self.assertEqual(self.backend.compare('abÉcd', 'abE\u0301cd'), 0)
        self.assertEqual(self.backend.compare('ç', 'c\u0327'), 0)
        self.assertEqual(self.backend.compare('abcば', 'abcは\u3099'), -1)

    def test_source_wrapped_secondary_minimums_are_trimmed(self):
        # a DW2 + U+3099 DW3 *85/*170 wraps to BYTE1/BYTE0.
        # GetWindowsSortKey removes trailing DW <= MIN_DW, not only DW2.
        # Keep this unary source-model boundary distinct from direct comparison.
        # post_b1_direct/direct-sortkey-wrap.json.gz records all three Framework
        # APIs: the trailing marks remain significant in direct comparison.
        for count in (85, 170):
            with self.subTest(count=count):
                self.assertEqual(self.backend.compare('a'+'\u3099'*count, 'a'), 1)
                self.assertEqual(self.backend.compare('a', 'a'+'\u3099'*count), -1)
                self.assertEqual(self.backend.sort_key('a'+'\u3099'*count),
                                 bytes.fromhex('0e0202010101010100'))

    def test_source_nested_expansions_beyond_received_strings(self):
        # EXPANSION U+FB03 -> f,U+FB01 -> f,f,i; U+FB00 -> f,f.
        self.assertEqual(self.backend.compare('office', 'oﬃce'), 0)
        self.assertEqual(self.backend.compare('ﬀ', 'ff'), 0)
        self.assertEqual(self.backend.compare('xßy', 'xssy'), 0)

    def test_source_weightless_code_units_in_context(self):
        # DEFAULT declares soft hyphen, ZWJ and NUL weightless.
        self.assertEqual(self.backend.compare('a\u00adb\u200dc\0', 'abc'), 0)
        self.assertEqual(self.backend.compare('\0\u00ad', ''), 0)

    def test_case_width_and_kana_are_not_folded(self):
        for left, right in [('b','B'), ('b','ｂ'), ('ア','あ'), ('ｱ','ア'), ('1','１')]:
            with self.subTest(left=left, right=right):
                self.assertNotEqual(self.backend.compare(left, right), 0)

    def test_scalar_and_explicit_surrogate_pair_have_same_utf16(self):
        self.assertEqual(self.backend.compare('😀', '\ud83d\ude00'), 0)
        self.assertEqual(self.backend.compare('x𐐀z', 'x\ud801\udc00z'), 0)

    def test_lone_surrogates_follow_published_code_unit_weights(self):
        # DEFAULT U+D800=(176,2,63,63), U+D801=(176,3,63,63).
        self.assertEqual(self.backend.sort_key('\ud800'), bytes.fromhex('b0020201013f013f010100'))
        self.assertLess(self.backend.compare('\ud800', '\ud801'), 0)

    def test_source_small_kana_extra_stage(self):
        # Source small/full kana share primary; CW bit1 supplies W4=0xC4/0xC6.
        self.assertLess(self.backend.compare('ぁ', 'あ'), 0)
        self.assertLess(self.backend.compare('ァ', 'ア'), 0)
        self.assertLess(self.backend.compare('ｧ', 'ｱ'), 0)

    def test_source_repeat_and_prolonged_sound_context(self):
        # MS-UCODEREF WT_FIVE_KANA=3, WT_FIVE_REPEAT=4, WT_FIVE_CHO_ON=5.
        self.assertLess(self.backend.compare('アア', 'アヽ'), 0)
        self.assertLess(self.backend.compare('アヽ', 'アー'), 0)
        self.assertGreater(self.backend.compare('ー', 'ア'), 0)

    def test_source_non_kana_context_carries_primary_only(self):
        # MS-UCODEREF SpecialCaseHandler copies a non-kana predecessor's
        # primary, then the mark's DW and MIN_CW. Uppercase/accent weights
        # must not be duplicated onto the prolonged-sound mark.
        self.assertEqual(self.backend.compare('Aー', 'Aa'), 0)
        self.assertEqual(self.backend.compare('Éー', 'Ée'), 0)
        self.assertLess(self.backend.compare('Aー', 'AA'), 0)

    def test_source_word_punctuation_is_a_late_position_weight(self):
        # The '-' primary is deferred; all remaining ordinary primary weights
        # are compared first. This is a source-model, not a new Windows probe.
        self.assertLess(self.backend.compare('ab', 'a-b'), 0)
        self.assertLess(self.backend.compare('a-b', 'ac'), 0)

    def test_identical_contextual_jamo_is_provably_reflexive(self):
        old_sequence = '\u1113\u1161'
        self.assertEqual(self.backend.compare(old_sequence, old_sequence), 0)
        # r43 adds contextual Jamo support. Preserve this r42 ID, but replace
        # its intentional unsupported-boundary expectation. The extra vowel
        # weights 3/7 give the local reconstructed model's order; this pair
        # is not an additional native Windows measurement.
        other_sequence = '\u1113\u1162'
        self.assertLess(self.backend.compare(old_sequence, other_sequence), 0)
        self.assertGreater(self.backend.compare(other_sequence, old_sequence), 0)

    def test_unknown_culture_and_options_fail_before_identical_fast_path(self):
        for options in (1, 0x1000, 'IgnoreCase'):
            with self.subTest(options=options):
                with self.assertRaises(Unsupported):
                    self.backend.compare('same', 'same', options=options)
        with self.assertRaises(Unsupported):
            self.backend.compare('same', 'same', culture='en-US')
        with self.assertRaises(Unsupported):
            self.backend.identity('ja-JP_radstr')

    def test_types_are_checked_before_identical_fast_path(self):
        with self.assertRaises(EraError) as caught:
            self.backend.compare(7, 7)
        self.assertEqual(caught.exception.code, 'E_TYPE')

    def test_general_input_reflexivity_and_antisymmetry(self):
        strings = ['', '日本', '亜愛悪', 'BETA', 'beta', 'ｂｅｔａ', 'Αθήνα',
                   'мир', 'mañana', 'man\u0303ana', '한', '😀abc', '\ud800x']
        for left in strings:
            self.assertEqual(self.backend.compare(left, left), 0)
            for right in strings:
                self.assertEqual(self.backend.compare(left, right), -self.backend.compare(right, left))

    def test_cache_is_bounded_and_instance_owned(self):
        first = PortableNLSBackend(cache_size=2)
        second = PortableNLSBackend(cache_size=2)
        for value in ('b', 'c', 'd'):
            first.sort_key(value)
        self.assertEqual((first.cache_info().currsize, first.cache_info().maxsize), (2, 2))
        self.assertEqual(second.cache_info().currsize, 0)
        first.sort_key('d')
        self.assertEqual(first.cache_info().hits, 1)

    def test_host_locale_and_unicode_normalization_are_not_used(self):
        with (patch('locale.strcoll', side_effect=AssertionError('host locale')),
              patch('unicodedata.normalize', side_effect=AssertionError('normalization'))):
            self.assertEqual(self.backend.compare('abcé', 'abce\u0301'), 0)

    def test_bundled_data_hash_counts_and_identity(self):
        profile = self.backend.profile
        path = files('pyemuera').joinpath('resources/nls_ja_windows10.bin.zlib')
        compressed = path.read_bytes()
        self.assertEqual(hashlib.sha256(compressed).hexdigest(), profile['compiled_sha256'])
        self.assertEqual(hashlib.sha256(zlib.decompress(compressed)).hexdigest(), profile['payload_sha256'])
        self.assertEqual((profile['bmp_slots'], profile['bmp_default_rows'], profile['ja_jp_exception_rows']), (65536, 60536, 7073))
        self.assertEqual((profile['expansion_rows'], profile['compatibility_aliases']), (730, 955))
        self.assertEqual(profile['nls_version'], 0x60305)
        self.assertEqual(self.backend.identity('ja-JP')['data_sha256'], profile['compiled_sha256'])


if __name__ == '__main__':
    unittest.main()
