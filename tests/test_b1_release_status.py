"""Release acceptance must remain tied to complete, versioned outcomes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from pyemuera import __version__

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('b1_release_status', ROOT / 'tools/build_release_status.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseStatusB1(unittest.TestCase):
    def report(self, folder, **updates):
        data = {'version': __version__, 'python': 'test interpreter', 'tests': 1,
                'pyz_sha256': '0' * 64, 'test_ids': ['example'],
                'results': {'example': {'outcome': 'PASS'}}, 'missing_baseline_ids': []}
        data.update(updates)
        path = Path(folder) / 'tests.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_gate_is_closed_without_explicit_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            status = builder.generate([self.report(folder)])
        self.assertFalse(status['beta_release_gate'])
        self.assertFalse(status['formal_a10_release_gate'])
        self.assertFalse(status['full_compatibility'])
        self.assertFalse(status['published'])

    def test_beta_gate_keeps_other_gates_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            status = builder.generate([self.report(folder)], True)
        self.assertTrue(status['beta_release_gate'])
        self.assertFalse(status['formal_a10_release_gate'])
        self.assertFalse(status['full_compatibility'])
        self.assertEqual(status['engine_version'], __version__)

    def test_wrong_version_and_missing_ids_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for change in ({'version': 'old'}, {'missing_baseline_ids': ['missing']}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    builder.generate([self.report(folder, **change)], True)

    def test_incomplete_outcomes_and_failure_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for change in ({'results': {}}, {'results': {'example': {'outcome': 'FAIL'}}}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    builder.generate([self.report(folder, **change)], True)

    def test_skip_is_retained_and_not_counted_as_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            status = builder.generate([self.report(folder, results={
                'example': {'outcome': 'SKIP', 'reason': 'platform prerequisite'}})], True)
        row = status['test_populations'][0]
        self.assertEqual(row['outcomes'], {'SKIP': 1})
        self.assertEqual(row['skips'], {'example': 'platform prerequisite'})


if __name__ == '__main__':
    unittest.main()
