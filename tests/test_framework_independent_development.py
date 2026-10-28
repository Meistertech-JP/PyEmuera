"""Replay selected, directly measured Framework development observations.

The fixture contains a deliberately selected matching subset, not an oracle
coverage estimate. UTF-16LE hex preserves the exact original code units.
"""
import hashlib
import json
from pathlib import Path
import unittest

from pyemuera.collation_portable import PortableNLSBackend


FIXTURE = Path(__file__).parent / "fixtures" / "framework_independent_development_comparisons.json"
FIXTURE_SHA256 = "b24b6af7022fae0467e0997c34348b7b639e3027d99d98edddcbfe4e059ca104"


def decode_utf16(value):
    return bytes.fromhex(value).decode("utf-16-le", errors="surrogatepass")


class IndependentDevelopmentFrameworkComparisons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
            raise ValueError("Framework development fixture bytes changed")
        cls.fixture = json.loads(raw)

    def test_provenance_and_observation_integrity(self):
        fixture = self.fixture
        profile = fixture["profile"]
        self.assertEqual(fixture["oracle_source"],
                         "oracle-indexed-independent-20261028/development/oracle.json")
        self.assertEqual(fixture["oracle_sha256"],
                         "1ab04eeaeb3bbe6e5940d7a271842bc73dfef5ca2653336db54f3f42d5e12b34")
        self.assertEqual((profile["schema"], profile["culture"], profile["compare_options"]),
                         ("r49-framework-oracle-1", "ja-JP", "None"))
        rows = fixture["comparisons"]
        self.assertEqual(len(rows), 30)
        self.assertEqual(len({row["oracle_pair_index"] for row in rows}), len(rows))
        self.assertEqual(len({row["category"] for row in rows}), 15)
        self.assertEqual({row["CompareTo_sign"] for row in rows}, {-1, 1})
        for row in rows:
            with self.subTest(oracle_pair_index=row["oracle_pair_index"]):
                self.assertEqual(row["group"], "generated")
                self.assertEqual(row["CompareTo_sign"], row["CompareInfo_None_sign"])
                self.assertEqual(row["CompareTo_sign"], row["NLS_sign"])
                for field in ("left_utf16le_hex", "right_utf16le_hex"):
                    value = row[field]
                    self.assertEqual(decode_utf16(value).encode("utf-16-le", errors="surrogatepass").hex(), value)
        for forward, reverse in zip(rows[::2], rows[1::2]):
            self.assertEqual(reverse["oracle_pair_index"], forward["oracle_pair_index"] + 1)
            self.assertEqual((reverse["left_index"], reverse["right_index"]),
                             (forward["right_index"], forward["left_index"]))
            self.assertEqual((reverse["left_utf16le_hex"], reverse["right_utf16le_hex"]),
                             (forward["right_utf16le_hex"], forward["left_utf16le_hex"]))
            self.assertEqual(reverse["CompareTo_sign"], -forward["CompareTo_sign"])

    def test_portable_comparer_matches_each_recorded_direct_sign(self):
        backend = PortableNLSBackend()
        for row in self.fixture["comparisons"]:
            with self.subTest(oracle_pair_index=row["oracle_pair_index"], category=row["category"]):
                self.assertEqual(backend.compare(decode_utf16(row["left_utf16le_hex"]),
                                                 decode_utf16(row["right_utf16le_hex"])),
                                 row["CompareTo_sign"])


if __name__ == "__main__":
    unittest.main()
