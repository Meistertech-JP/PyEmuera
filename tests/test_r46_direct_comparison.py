"""Framework direct-comparison regressions measured on Windows for r46.

The 1,936-pair oracle is the r45 alias population. Signs were copied from the
Framework probe JSON; they were not produced by this engine. Direct comparison
is pairwise and is not required to match the unary sort key.
"""
import gzip
import hashlib
import json
from pathlib import Path
import unittest

from pyemuera.collation_portable import PortableNLSBackend


FIXTURE = Path(__file__).resolve().parent / "fixtures/r46_collation/alias_1936_framework.json.gz"
FIXTURE_SHA256 = "89017a4b6057ad55bf8c26814b3402fb2b610671fd622e351007e5728a36c18d"
ORACLE = json.loads(gzip.decompress(FIXTURE.read_bytes()))


def decoded(value):
    return bytes.fromhex(value).decode("utf-16-le", "surrogatepass")


class DirectComparisonR46(unittest.TestCase):
    def setUp(self):
        self.backend = PortableNLSBackend(cache_size=0)

    def test_alias_fixture_is_hash_pinned_and_not_self_generated(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FIXTURE_SHA256)
        self.assertTrue(ORACLE["expected_signs_not_generated_from_candidate"])
        self.assertEqual(len(ORACLE["inputs_utf16le_hex"]), 44)
        self.assertEqual(len(ORACLE["comparisons"]), 1936)

    def test_alias_1936_framework_direct_signs(self):
        strings = [decoded(value) for value in ORACLE["inputs_utf16le_hex"]]
        for row in ORACLE["comparisons"]:
            self.assertEqual(row["CompareTo_sign"], row["CompareInfo_None_sign"])
            self.assertEqual(row["CompareTo_sign"], row["CompareStringEx_sign"])
            left = strings[row["left_index"]]
            right = strings[row["right_index"]]
            self.assertEqual(self.backend.compare(left, right), row["CompareTo_sign"])

    def test_measured_three_cycle_is_not_rewritten_to_sort_key_order(self):
        strings = [decoded(value) for value in ORACLE["inputs_utf16le_hex"]]
        # Indexes 22, 21, 31 are the measured A, C, B cycle.
        signs = {}
        for row in ORACLE["comparisons"]:
            signs[(row["left_index"], row["right_index"])] = row
        cycle = ((22, 21), (21, 31), (31, 22))
        direct_signs = []
        sortkey_signs = []
        for left, right in cycle:
            row = signs[(left, right)]
            direct_signs.append(row["CompareTo_sign"])
            sortkey_signs.append(row["Framework_SortKey_Compare_sign"])
            self.assertEqual(
                self.backend.compare(strings[left], strings[right]),
                row["CompareTo_sign"],
            )
        self.assertEqual(direct_signs, [-1, -1, -1])
        self.assertNotEqual(sortkey_signs, [-1, -1, -1])


if __name__ == "__main__":
    unittest.main()
