"""Test the exact zipapp, preserving every ID, outcome and skip reason."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
if sys.version_info < (3, 11):
    raise SystemExit('The test suite requires Python 3.11 or later. The PyEmuera runtime supports Python 3.10 or later.')
ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SUITE = ROOT / 'tests' / 'fixtures' / 'public_suite'
if not sys.flags.utf8_mode:
    # Test modules and the engine subprocesses they start exchange UTF-8 text
    # with the default encoding. Run the whole suite in Python's UTF-8 mode
    # (PEP 540) on every platform, e.g. on Windows with a CP932 locale; the
    # environment variable is inherited by subprocesses. Keep the exit code.
    import subprocess
    raise SystemExit(subprocess.call([sys.executable, *sys.argv], env={**os.environ, 'PYTHONUTF8': '1'}))
# Startup -X utf8 is not inherited by child Python interpreters.
os.environ['PYTHONUTF8'] = '1'
parser = argparse.ArgumentParser()
parser.add_argument('--pyz', type=Path, required=True)
parser.add_argument('--baseline-ids', type=Path, default=PUBLIC_SUITE / 'initial-3384-ids.json')
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--suite', choices=('all','release','characterization'), default='all')
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
assert sorted(ids) == json.loads((PUBLIC_SUITE/'expected-3678-ids.json').read_text(encoding='utf-8')), 'Exact full56 ID union mismatch'
all_discovered_ids=ids[:]
scope_path=PUBLIC_SUITE/'test-scope-native56-v2.json'
scope=json.loads(scope_path.read_text(encoding='utf-8'))
assert hashlib.sha256((PUBLIC_SUITE/'expected-3678-ids.json').read_bytes()).hexdigest()==scope['all_inventory_sha256']
initial_path=PUBLIC_SUITE/'initial-3384-ids.json'
assert hashlib.sha256(initial_path.read_bytes()).hexdigest()==scope['initial3384_sha256']
initial=set(json.loads(initial_path.read_text(encoding='utf-8')))
char=set(scope['characterization_ids']); release=set(scope['release_ids']); discovered=set(ids)
assert len(ids)==len(discovered)==3678 and len(char)==22 and len(release)==3656
assert char=={entry['id'] for entry in scope['entries']} and char<=discovered
assert not initial&char and initial<=release and not release&char and release|char==discovered
for entry in scope['entries']:
    raw=(ROOT/entry['old_source_file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==entry.get('current_file_sha256',entry['old_file_sha256']),entry['id']
    start,end=entry['method_byte_lines']
    assert hashlib.sha256(b''.join(raw.splitlines(keepends=True)[start-1:end])).hexdigest()==entry['old_body_sha256']
selected=discovered if args.suite=='all' else release if args.suite=='release' else char
def selected_tests(items):
    for item in items:
        if isinstance(item,unittest.TestSuite): yield from selected_tests(item)
        elif item.id() in selected: yield item
suite=unittest.TestSuite(selected_tests(suite))
ids=list(flatten(suite))
assert len(ids)==len(selected) and set(ids)==selected
baseline = json.loads(args.baseline_ids.read_text(encoding='utf-8'))
missing = sorted(set(baseline) - set(all_discovered_ids))
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
# unittest counts failing subtest events separately; these totals count final IDs.
outcome_counts = {
    outcome: sum(row['outcome'] == outcome for row in rows.values())
    for outcome in ('PASS', 'FAIL', 'ERROR', 'SKIP')
}
summary = {
    'schema': 'r47-unit-tests-2',
    'counting_convention': 'Disjoint per-ID final results[row].outcome; raw unittest events reported separately',
    'outcome_counts': outcome_counts,
    'suite': args.suite,
    'all_discovered_test_ids': all_discovered_ids,
    'scope_manifest_sha256': hashlib.sha256(scope_path.read_bytes()).hexdigest(),
    'unique_passed': outcome_counts['PASS'],
    'version': pyemuera.__version__,
    'pyz_sha256': hashlib.sha256(pyz.read_bytes()).hexdigest(),
    'origin': pyemuera.__file__,
    'python': sys.version,
    'tests': result.testsRun,
    'testsRun': result.testsRun,
    'failures': outcome_counts['FAIL'],
    'errors': outcome_counts['ERROR'],
    'skipped': outcome_counts['SKIP'],
    'passed': outcome_counts['PASS'],
    'failure_events': len(result.failures),
    'error_events': len(result.errors),
    'skip_events': len(result.skipped),
    'counted_outcome_ids': sum(outcome_counts.values()),
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
