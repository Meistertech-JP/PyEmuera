"""Measured Windows 10 ja-JP Jamo weights and the direct-comparison split.

Sort-key prefixes are the Unicode weights returned by .NET Framework 4.8
CompareInfo.GetSortKey on this machine. Signs for the mixed pairs are the
CompareTo signs already stored in the r47 oracles; they are not derived from
this engine.
"""
import unittest

from pyemuera.collation_portable import PortableNLSBackend


def _units(hex_text):
    raw = bytes.fromhex(hex_text)
    return raw.decode("utf-16-le", "surrogatepass")


class JamoWeightsR48(unittest.TestCase):
    def setUp(self):
        self.backend = PortableNLSBackend(cache_size=0)

    def test_single_leading_sort_key_contains_measured_unicode_weight(self):
        key = self.backend.sort_key("ᄀ")
        self.assertTrue(key.startswith(bytes.fromhex("c002ff83ff03ff02")))

    def test_fillers_compare_equal(self):
        self.assertEqual(self.backend.compare("ᅟ", "ᅠ"), 0)
        self.assertTrue(
            self.backend.sort_key("ᅠ").startswith(bytes.fromhex("ec97ffffff03ff02"))
        )

    def test_weightless_unit_between_modern_l_and_v_stays_equal(self):
        plain = "각"
        for mark in ("\x00", "­"):
            self.assertEqual(self.backend.compare(plain, "ᄀ" + mark + "ᅡᆨ"), 0)

    def test_modern_lt_outranks_punctuation_split(self):
        # r47 development oracle row whose previous portable sign was -1.
        left = _units("0011a811")
        right = _units("00110100a811")
        self.assertEqual(self.backend.compare(left, right), 1)

    def test_holdout_nul_inside_repeated_vowel_is_equal(self):
        # r47 holdout02 rows 4 and 5. Framework CompareTo is 0.
        left = _units("68006f006c006400e8d7edd7cd11d9d70f116e117ba93f11f7116f0075007400")
        right = _units("68006f006c006400e8d7edd7cd11d9d70f11000000006e117ba93f11f7116f0075007400")
        self.assertEqual(self.backend.compare(left, right), 0)

    def test_compatibility_jamo_direct_order_is_not_the_sort_key_order(self):
        # Framework CompareTo(U+1100, U+3131) is -1. GetSortKey order is +1.
        modern = "ᄀ"
        compatibility = "ㄱ"
        self.assertEqual(self.backend.compare(modern, compatibility), -1)
        modern_key = self.backend.sort_key(modern)
        compatibility_key = self.backend.sort_key(compatibility)
        self.assertGreater(modern_key, compatibility_key)

    def test_leading_nul_flips_vowel_against_trailing_vowel_cluster(self):
        # Framework CompareTo is -1. GetSortKey is +1. NUL and soft hyphen match.
        cluster = "ᆰᅲ"
        self.assertEqual(self.backend.compare("ᆈ", cluster), 1)
        self.assertEqual(self.backend.compare("\x00ᆈ", cluster), -1)
        self.assertEqual(self.backend.compare("­ᆈ", cluster), -1)
        self.assertEqual(self.backend.compare("\x00ᅢ", "ᅡ"), 0)

    def test_modern_leading_cluster_ignores_one_weightless_separator(self):
        # Measured CompareTo is 0 for a modern L+V+T cluster. Old leadings stay ordered.
        self.assertEqual(self.backend.compare("멊", "ᄆ\x00ᅰᆫ"), 0)
        self.assertEqual(self.backend.compare("허", "ᄒ\x00ᅥ"), 0)
        self.assertEqual(self.backend.compare("ᄓᅥᆫ", "ᄓ\x00ᅰᆨ"), 1)
        self.assertEqual(self.backend.compare("ᄀᅠᆨ", "ᄀ\x00ᅠᆨ"), 1)
