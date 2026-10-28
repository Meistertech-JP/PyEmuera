"""Framework-observed controls for separator/Jamo continuation regressions."""
import hashlib
import json
from pathlib import Path
import unittest

from pyemuera.collation_portable import PortableNLSBackend


class FrameworkSeparatorRegressionControls(unittest.TestCase):
    def test_recorded_direct_comparisons(self):
        fixture = Path(__file__).parent / "fixtures" / "framework_separator_regression_controls.json"
        raw = fixture.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "3baae11d4ecfa487d9e1c2b2065315cfa19e142234d3aba9e5366c339bfc5954")
        data = json.loads(raw)
        self.assertEqual(len(data["comparisons"]), 16)
        self.assertEqual(data["oracle_sha256"],
                         "caa7cb5b767eec02dee3c3124d9d995c41f6a38f125f99ec3b002d1d2179ed13")
        backend = PortableNLSBackend()
        seen = set()
        for row in data["comparisons"]:
            with self.subTest(oracle_row=row["oracle_row"]):
                self.assertNotIn(row["oracle_row"], seen)
                seen.add(row["oracle_row"])
                left, right = (bytes.fromhex(row[key]).decode("utf-16le", "surrogatepass")
                               for key in ("left_utf16le_hex", "right_utf16le_hex"))
                self.assertEqual(backend.compare(left, right), row["expected"])


if __name__ == "__main__":
    unittest.main()
