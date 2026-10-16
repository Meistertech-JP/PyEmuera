"""Compare string ARRAYSORT output of a chosen engine with saved native Emuera logs.

The neutral probes in verification/r50/native-arraysort were run by the original
Emuera1824+v24 executable on Windows 10 (ja-JP); its raw UTF-16 logs are kept
unchanged next to them. This tool runs the same probes with the selected engine
and compares every RESULT_/CASE_/STATE_/RNG_AFTER line with the native log.

  six      R49_ARRAYSORT_PROBE.ERB  vs R49_ARRAYSORT_NATIVE_emuera.log (6 results)
  neutral  R50_ARRAYSORT_NEUTRAL.ERB vs native-no-config.log (32 cases,
           their RESULT/RESULTS state and the RNG state after sorting)

Backends: "default" uses the platform's normal comparer (Windows: NLS API,
elsewhere: portable). "portable" forces the portable comparer on any platform.
The report records the actual platform; a forced-portable run on Windows is not
a run on another operating system. Standard library only; Python 3.10+.

  python tools/verify_arraysort_native.py --pyz PyEmuera.pyz --out arraysort-check
  python tools/verify_arraysort_native.py --source --out arraysort-check
  python tools/verify_arraysort_native.py --installed --out arraysort-check
    (--installed tests the pyemuera package installed for the running Python,
     for example after "pip install"; run it with that Python, not from source.)
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'verification/r50/native-arraysort'
PROBES = (
    ('six', 'R49_ARRAYSORT_PROBE.ERB', 'R49_ARRAYSORT_NATIVE_emuera.log'),
    ('neutral', 'R50_ARRAYSORT_NEUTRAL.ERB', 'native-no-config.log'),
)
KEYS = ('RESULT_', 'CASE_', 'STATE_', 'RNG_AFTER|')

INNER = r'''
import json, sys
engine, game, mode, meta = sys.argv[1:]
if engine.startswith('installed:'):
    source_root = engine[len('installed:'):]
    sys.path[:] = [p for p in sys.path if p not in ('', '.')]
    import pyemuera
    if pyemuera.__file__.startswith(source_root):
        raise SystemExit('pyemuera was imported from the source tree, not an installation')
else:
    sys.path.insert(0, engine)
    import pyemuera
    if not pyemuera.__file__.startswith(engine):
        raise SystemExit('engine was not imported from ' + engine)
import pyemuera.collation1824 as C
if mode == 'portable':
    from pyemuera.collation_portable import PortableNLSBackend
    backend = PortableNLSBackend()
    C._backend = lambda: backend
    C._culture = lambda backend, culture: culture or 'ja-JP'
identity = C.comparison_identity()
original = C.compare_strings
count = [0]
def counted(left, right, culture=None):
    count[0] += 1
    return original(left, right, culture)
C.compare_strings = counted
sys.argv = ['PyEmuera', game, '--no-wait']
from pyemuera.cli import entrypoint
code = 0
try:
    entrypoint()
except SystemExit as e:
    code = e.code or 0
with open(meta, 'w', encoding='utf-8') as f:
    json.dump({'version': pyemuera.__version__, 'module': pyemuera.__file__, 'backend_identity': identity,
               'compare_strings_calls': count[0], 'returncode': code}, f, ensure_ascii=True, indent=2)
raise SystemExit(code)
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def keyed(lines):
    rows = {}
    for line in lines:
        if line.startswith(KEYS):
            key, _, value = line.partition('|')
            if key in rows:
                raise ValueError('duplicate output key ' + key)
            rows[key] = value
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    engine = parser.add_mutually_exclusive_group(required=True)
    engine.add_argument('--pyz', type=Path, help='engine to test (a PyEmuera.pyz file)')
    engine.add_argument('--source', action='store_true', help='test the pyemuera package in this source tree')
    engine.add_argument('--installed', action='store_true', help='test the pyemuera package installed for this Python')
    parser.add_argument('--backend', choices=('default', 'portable', 'both'), default='both')
    parser.add_argument('--out', type=Path, required=True, help='new folder for the probe games and summary.json')
    args = parser.parse_args()
    target = args.pyz.resolve() if args.pyz else ROOT
    engine_arg = 'installed:' + str(ROOT) if args.installed else str(target)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    env.pop('PYTHONPATH', None)
    modes = ('default', 'portable') if args.backend == 'both' else (args.backend,)
    report = {'schema': 'pyemuera-arraysort-native-check-1', 'platform': sys.platform,
              'platform_detail': platform.platform(), 'python': sys.version.split()[0],
              'engine': 'pyz' if args.pyz else ('installed' if args.installed else 'source'),
              'engine_sha256': sha(target.read_bytes()) if args.pyz else None,
              'native_reference': 'Emuera1824+v24 executable, Windows 10 ja-JP (saved raw logs)', 'runs': []}
    for mode in modes:
        for label, erb, log in PROBES:
            native_bytes = (NATIVE / log).read_bytes()
            expected = keyed(native_bytes.decode('utf-16').replace('\r', '').splitlines())
            game = out / mode / label
            (game / 'ERB').mkdir(parents=True)
            (game / 'CSV').mkdir()
            (game / 'ERB/PROBE.ERB').write_bytes((NATIVE / erb).read_bytes())
            meta = game / 'engine.json'
            proc = subprocess.run([sys.executable, '-B', '-c', INNER, engine_arg, str(game), mode, str(meta)],
                                  capture_output=True, env=env, timeout=600, cwd=str(out))
            (game / 'stdout.txt').write_bytes(proc.stdout)
            (game / 'stderr.txt').write_bytes(proc.stderr)
            info = json.loads(meta.read_text(encoding='utf-8')) if meta.exists() else {}
            actual = keyed(proc.stdout.decode('utf-8', 'replace').replace('\r', '').splitlines())
            differences = sorted(k for k in set(expected) | set(actual) if expected.get(k) != actual.get(k))
            run = {'backend': mode, 'probe': label, 'engine_module': info.get('module'),
                   'native_log': log, 'native_log_sha256': sha(native_bytes),
                   'probe_sha256': sha((NATIVE / erb).read_bytes()), 'returncode': proc.returncode,
                   'engine_version': info.get('version'), 'backend_identity': info.get('backend_identity'),
                   'compare_strings_calls': info.get('compare_strings_calls'),
                   'compared_lines': len(expected), 'differences': differences[:50],
                   'difference_count': len(differences)}
            run['passed'] = (proc.returncode == 0 and bool(expected) and not differences
                             and (info.get('compare_strings_calls') or 0) > 0)
            report['runs'].append(run)
    report['passed'] = all(r['passed'] for r in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for r in report['runs']:
        print('%-8s %-8s lines=%-4d differences=%-3d %s' % (
            r['backend'], r['probe'], r['compared_lines'], r['difference_count'], 'PASS' if r['passed'] else 'FAIL'))
    print('platform:', sys.platform, '| all passed:', report['passed'])
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
