"""Selected regressions of the rejected inline-filler candidate, not a sample."""
import hashlib
import json
from pathlib import Path
import unittest

from pyemuera.collation_portable import PortableNLSBackend


class FrameworkInlineCandidateRegressions(unittest.TestCase):
    def test_recorded_direct_comparisons(self):
        path = Path(__file__).parent / 'fixtures' / 'framework_inline_candidate_regressions.json'
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '2b0dd82cb2f0c26603860631123773c2faa296df027a2380d936ca739c4c48bc')
        data = json.loads(raw)
        self.assertEqual(data['oracle_sha256'],
                         'f0424631056a69163e35dd52a7ba5af196dab1cc6941c62c54bfaa97b901e87d')
        self.assertEqual(data['correlated_results_sha256'],
                         '9dc2c50026474b6595a0b9f8b7d6da3dd01074419f75046ab0dcbd7140768699')
        rows = data['comparisons']
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({r['oracle_row'] for r in rows}), len(rows))
        backend = PortableNLSBackend()
        for i in range(0, len(rows), 2):
            a, b = rows[i:i + 2]
            self.assertEqual((a['left_utf16le_hex'], a['right_utf16le_hex']),
                             (b['right_utf16le_hex'], b['left_utf16le_hex']))
            self.assertEqual(a['expected'], -b['expected'])
            for row in (a, b):
                with self.subTest(oracle_row=row['oracle_row']):
                    self.assertEqual(row['rejected_candidate_sign'], -row['expected'])
                    left, right = (bytes.fromhex(row[key]).decode('utf-16le', 'surrogatepass')
                                   for key in ('left_utf16le_hex', 'right_utf16le_hex'))
                    self.assertEqual(backend.compare(left, right), row['expected'])


if __name__ == '__main__':
    unittest.main()
