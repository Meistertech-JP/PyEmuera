"""Test the exact zipapp, preserving every ID, outcome and skip reason."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
ROOT = Path(__file__).resolve().parents[1]
if not sys.flags.utf8_mode:
    # Test modules and the engine subprocesses they start exchange UTF-8 text
    # with the default encoding. Run the whole suite in Python's UTF-8 mode
    # (PEP 540) on every platform, e.g. on Windows with a CP932 locale; the
    # environment variable is inherited by subprocesses. Keep the exit code.
    import subprocess
    raise SystemExit(subprocess.call([sys.executable, *sys.argv], env={**os.environ, 'PYTHONUTF8': '1'}))
parser = argparse.ArgumentParser()
parser.add_argument('--pyz', type=Path, required=True)
parser.add_argument('--baseline-ids', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
pyz = args.pyz.resolve()
sys.path[:0] = [str(pyz), str(ROOT / 'tests'), str(ROOT)]
import pyemuera
assert pyemuera.__file__.replace('\\', '/').startswith(str(pyz).replace('\\', '/') + '/')
suite = unittest.defaultTestLoader.discover(
    str(ROOT / 'tests'),
    pattern='test_*.py',
    top_level_dir=str(ROOT / 'tests'),
)
assert not unittest.defaultTestLoader.errors, unittest.defaultTestLoader.errors

def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()
ids = list(flatten(suite))
baseline = json.loads(args.baseline_ids.read_text(encoding='utf-8'))
missing = sorted(set(baseline) - set(ids))
assert not missing, missing
rows = {}

class Recorded(unittest.TextTestResult):

    def addSuccess(self, test):
        super().addSuccess(test)
        rows[test.id()] = {'outcome': 'PASS'}

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        rows[test.id()] = {'outcome': 'SKIP', 'reason': reason}

    def addFailure(self, test, err):
        super().addFailure(test, err)
        rows[test.id()] = {'outcome': 'FAIL', 'detail': self._exc_info_to_string(err, test)}

    def addError(self, test, err):
        super().addError(test, err)
        rows[test.id()] = {'outcome': 'ERROR', 'detail': self._exc_info_to_string(err, test)}

    def addSubTest(self, test, subtest, err):
        # A failing subtest makes its test unsuccessful without addFailure/addError;
        # record it so that no FAIL/ERROR is left without an outcome row.
        super().addSubTest(test, subtest, err)
        if err is not None:
            kind = 'FAIL' if issubclass(err[0], test.failureException) else 'ERROR'
            row = rows.setdefault(test.id(), {'outcome': kind, 'subtests': []})
            if kind == 'ERROR':
                row['outcome'] = 'ERROR'
            row.setdefault('subtests', []).append(
                {'id': subtest.id(), 'outcome': kind, 'detail': self._exc_info_to_string(err, test)})
# Never let a test read the developer's keyboard: on Windows a console stdin
# selects the native console reader instead of the patched input().
sys.stdin = open(os.devnull, encoding='utf-8')
started = time.monotonic()
args.out.parent.mkdir(parents=True, exist_ok=True)
with args.out.with_suffix('.log').open('w', encoding='utf-8') as log:
    result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Recorded).run(suite)
summary = {
    'schema': 'r47-unit-tests-1',
    'version': pyemuera.__version__,
    'pyz_sha256': hashlib.sha256(pyz.read_bytes()).hexdigest(),
    'origin': pyemuera.__file__,
    'python': sys.version,
    'tests': result.testsRun,
    'failures': len(result.failures),
    'errors': len(result.errors),
    'skipped': len(result.skipped),
    'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
    'baseline_test_count': len(baseline),
    'missing_baseline_ids': missing,
    'new_ids': sorted(set(ids) - set(baseline)),
    'test_ids': ids,
    'results': rows,
    'elapsed_seconds': time.monotonic() - started,
    'successful': result.wasSuccessful(),
}
args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in summary.items() if k not in {'test_ids', 'results', 'new_ids'}}))
raise SystemExit(0 if result.wasSuccessful() else 1)
