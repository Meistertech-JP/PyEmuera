"""Selected Framework development controls; not a representative sample."""
import hashlib
import json
from pathlib import Path
import unittest

from pyemuera.collation_portable import PortableNLSBackend


FIXTURE = Path(__file__).parent / 'fixtures/framework_decisive_jamo_development.json'
FIXTURE_SHA256 = 'ef118921b4f16e9be7a38ee6b10c1b35519060ea70847d17367a8a38ea3b17c0'


def decode(value):
    return bytes.fromhex(value).decode('utf-16le', 'surrogatepass')


class FrameworkDecisiveJamoDevelopment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
            raise ValueError('Framework fixture bytes changed')
        cls.data = json.loads(raw)

    def test_provenance_and_three_api_observations(self):
        data = self.data
        self.assertIn('nonrepresentative development', data['description'])
        self.assertEqual(data['source_sha256']['r49_prefix_alignment'],
                         '4d6b753a4c511480931862550e2e86f9e4d1476f3f7bf7424974f574dee18672')
        self.assertEqual(data['source_sha256']['fresh_oracle'],
                         '15a464365e86f3a4e40c5fa6b6d8cf4be0055ac2c4ed6fcfe9e28ef5d8fe64fe')
        profile = data['profile']
        self.assertEqual((profile['culture'], profile['compare_options'], profile['nls_version'], profile['nls_sort_id']),
                         ('ja-JP', 'None', 393989, '00000046-57ee-1e5c-00b4-d0000bb1e11e'))
        rows = data['comparisons']
        self.assertEqual(len(rows), 22)
        self.assertEqual(sum(r['source'] == 'r49_prefix_alignment' for r in rows), 6)
        self.assertEqual(sum(r['category'].startswith('stress_improvement_') for r in rows), 8)
        self.assertEqual(sum(r['category'].startswith('stress_known_match_') for r in rows), 8)
        for forward, reverse in zip(rows[::2], rows[1::2], strict=True):
            self.assertEqual((forward['left_utf16le_hex'], forward['right_utf16le_hex']),
                             (reverse['right_utf16le_hex'], reverse['left_utf16le_hex']))
            self.assertEqual(forward['category'], reverse['category'])
            self.assertEqual(forward['CompareTo_sign'], -reverse['CompareTo_sign'])
            for row in (forward, reverse):
                self.assertIn(row['CompareTo_sign'], (-1, 0, 1))
                self.assertEqual(row['CompareTo_sign'], row['CompareInfo_None_sign'])
                self.assertEqual(row['CompareTo_sign'], row['NLS_sign'])
                for key in ('left_utf16le_hex', 'right_utf16le_hex'):
                    self.assertEqual(decode(row[key]).encode('utf-16le', 'surrogatepass').hex(), row[key])

    def test_portable_comparer_against_fresh_direct_observations(self):
        backend = PortableNLSBackend()
        for row in self.data['comparisons']:
            with self.subTest(category=row['category'], source_row=row['source_row']):
                actual = backend.compare(decode(row['left_utf16le_hex']), decode(row['right_utf16le_hex']))
                self.assertEqual(actual, row['CompareTo_sign'])

    def test_decisive_prefix_custom_string_access_is_not_used(self):
        class CustomString(str):
            def __getitem__(self, index):
                raise AssertionError('custom indexing must not be used by this rule')

        backend = PortableNLSBackend()
        for left, right in ((CustomString('-\u1100'), '+\u1101'),
                            ('-\u1100', CustomString('+\u1101'))):
            with self.subTest(left=type(left), right=type(right)):
                self.assertIsNone(backend._decisive_prefix_jamo_sign(left, right))

    def test_decisive_prefix_plain_string_subclass_matches_str(self):
        class PlainString(str):
            pass

        backend = PortableNLSBackend()
        for row in self.data['comparisons']:
            left, right = decode(row['left_utf16le_hex']), decode(row['right_utf16le_hex'])
            expected = backend._decisive_prefix_jamo_sign(left, right)
            for a, b in ((PlainString(left), right), (left, PlainString(right)),
                         (PlainString(left), PlainString(right))):
                self.assertEqual(backend._decisive_prefix_jamo_sign(a, b), expected)


if __name__ == '__main__':
    unittest.main()
