"""Build an explicitly allowlisted public r50 ZIP from final, tested inputs.

The external hygiene policy is authoritative. Historical inputs are never
rewritten. Only a fresh stage and a fresh output are accepted. Verification
reports and the ZIP's own SHA belong in external sidecars, not this ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '3.0.0a10.dev4+r50'
CONTROL = {'MANIFEST.sha256', 'SHA256.txt', 'PACK_MANIFEST.json'}
POST_BUILD = {'R50_DISTRIBUTION_INTEGRITY.json', 'R50_MANIFEST_VERIFICATION.json',
              'R50_CLEAN_ZIP_UNIT_TESTS.json', 'SHA256-r50.txt'}
GATES = ('formal_a10_release_gate', 'beta_release_gate', 'full_compatibility')
BASELINE_COUNT = 3209
BASELINE_IDS_SHA256 = 'de10a433b6bc4ed66e3b65d3e59e9ce5f2102bcd5f827ad299a0f9dd52575ac2'
COMMON = {'PyEmuera.pyz', 'README_ja.md', 'ARCHITECTURE_ja.md',
          'COMPATIBILITY_ja.md', 'CHANGELOG_ja.md', 'TEST_REPORT_ja.md',
          'LICENSE', 'THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_MS_NLS_NOTICE_ja.md',
          'docs/R50_KNOWN_LIMITATIONS_ja.md', 'R50_DEVELOPMENT_REPORT_ja.md',
          'R50_ARRAYSORT_COMPATIBILITY_ja.md', 'R50_BETA_READINESS_ASSESSMENT_ja.md',
          'R50_COMPATIBILITY_DELTA.json', 'R50_BUILD_CHECK.json',
          'R50_REPRODUCIBLE_BUILD_CHECK.json', 'R50_UNIT_TESTS.json'}
EVIDENCE = {'R50_ARRAYSORT_NATIVE_RESULTS.json', 'R50_ARRAYSORT_PY_RESULTS.json',
            'R50_ARRAYSORT_CALL_TRACE.json', 'R50_ARRAYSORT_STATE_VERIFICATION.json',
            'R50_ARRAYMSORT_NONREGRESSION.json', 'R50_GENERAL_COMPATIBILITY_VERIFICATION.json',
            'R50_WINDOWS_INTEGRATION_REPORT_ja.md', 'R50_WINDOWS_INTERRUPT_RESULTS.json',
            'R50_REAL_GAME_WINDOWS_RESULTS.json', 'tools/framework_arraysort_r50.cs',
            'tools/verify_arraysort_r50.py',
            'verification/r50/native-arraysort/R49_ARRAYSORT_PROBE.ERB',
            'verification/r50/native-arraysort/R49_ARRAYSORT_NATIVE_emuera.log',
            'verification/r50/native-arraysort/R50_ARRAYSORT_NEUTRAL.ERB',
            'verification/r50/native-arraysort/plans.json'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def safe_path(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        return False
    parts = name.split('/')
    return (not any(ord(c) < 32 or ord(c) == 127 for c in name)
            and all(p and p not in {'.', '..'} and not p.endswith((' ', '.'))
                    and not re.search(r'[<>"|?*]', p)
                    and not re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p)
                    for p in parts))


def check_names(names):
    if any(not safe_path(n) for n in names):
        raise ValueError('unsafe relative member name')
    if len({n.casefold() for n in names}) != len(names):
        raise ValueError('duplicate or Windows case-collision')


def no_link(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('symlink or reparse point in input')


def source_file(root, rel):
    check_names([rel])
    no_link(root)
    path = root
    for part in PurePosixPath(rel).parts:
        path = path / part
        no_link(path)
    if not path.is_file():
        raise ValueError('required input is not a file: ' + rel)
    return path


def inventory(stage):
    """Do not silently ignore extra directories, junctions, or special files."""
    no_link(stage)
    rows = {}
    for folder, dirs, files in os.walk(stage, followlinks=False):
        for name in dirs + files:
            no_link(Path(folder) / name)
        for name in files:
            path = Path(folder) / name
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError('nonregular stage file')
            rel = path.relative_to(stage).as_posix()
            raw = path.read_bytes()
            rows[rel] = {'bytes': len(raw), 'sha256': sha(raw)}
    check_names(list(rows))
    return dict(sorted(rows.items()))


def load_policy(path, kind):
    raw = path.read_bytes()
    policy = json.loads(raw)
    role = 'windows' if kind == 'evidence' else kind
    for required_role in ('runtime', 'developer', 'windows', 'pyz'):
        names = policy.get('allowlists', {}).get(required_role)
        if not isinstance(names, list):
            raise ValueError('policy requires four exact allowlists')
        check_names(names)
    names = set(policy['allowlists'][role])
    if not CONTROL <= names:
        raise ValueError('policy omits manifest control files')
    if names & POST_BUILD:
        raise ValueError('postbuild sidecars must not be inside frozen ZIP')
    required = COMMON | set(policy.get('required', {}).get(role, []))
    if kind in {'developer', 'evidence'}:
        required |= EVIDENCE
    if not required <= names:
        raise ValueError('policy missing required public members: ' + ', '.join(sorted(required - names)))
    return policy, role, names, sha(raw)


def validate_metadata(root):
    units = json.loads(source_file(root, 'R50_UNIT_TESTS.json').read_bytes())
    if (units.get('version') != VERSION or units.get('failures') != 0
            or units.get('errors') != 0 or units.get('successful') is not True
            or units.get('missing_baseline_ids') != []
            or units.get('baseline_test_count') != BASELINE_COUNT):
        raise ValueError('final unit report is incomplete or unsuccessful')
    ids, new = units['test_ids'], units['new_ids']
    if len(set(ids)) != len(ids) or not set(new) <= set(ids):
        raise ValueError('unit test ID membership')
    baseline = sorted(set(ids) - set(new))
    if (len(baseline) != BASELINE_COUNT
            or sha(('\n'.join(baseline) + '\n').encode()) != BASELINE_IDS_SHA256):
        raise ValueError('original 3209 baseline IDs not preserved')
    outcomes = units['results']
    if set(outcomes) != set(ids) or units['tests'] != len(ids):
        raise ValueError('unit result membership or count')
    for label, key in [('PASS', 'passed'), ('SKIP', 'skipped'), ('FAIL', 'failures'), ('ERROR', 'errors')]:
        if sum(row.get('outcome') == label for row in outcomes.values()) != units[key]:
            raise ValueError('unit outcome count: ' + key)
    if any(row.get('outcome') not in {'PASS', 'SKIP', 'FAIL', 'ERROR'} for row in outcomes.values()):
        raise ValueError('unknown unit outcome')
    if any(row.get('outcome') == 'SKIP' and not row.get('reason') for row in outcomes.values()):
        raise ValueError('unit skip reason missing')
    pyz = sha(source_file(root, 'PyEmuera.pyz').read_bytes())
    if units['pyz_sha256'] != pyz:
        raise ValueError('untested pyz')
    reports = []
    for name in ('R50_BUILD_CHECK.json', 'R50_REPRODUCIBLE_BUILD_CHECK.json'):
        report = json.loads(source_file(root, name).read_bytes())
        if (report.get('engine_version') != VERSION or report.get('pyz_sha256') != pyz
                or report.get('passed') is not True or report.get('full_raw_bytes_equal') is not True
                or report.get('source_member_payloads_equal') is not True
                or not isinstance(report.get('source_input_sha256'), dict)
                or not report['source_input_sha256'] or any(report.get(k) is not False for k in GATES)):
            raise ValueError('final reproducible build acceptance: ' + name)
        reports.append(report)
    if reports[0]['source_input_sha256'] != reports[1]['source_input_sha256']:
        raise ValueError('build reports disagree on source inputs')
    return units, reports[0]


def freeze(stage, version, units, role='development_candidate', *, kind='developer', policy_sha256=None):
    rows = {n: p for n, p in inventory(stage).items() if n not in CONTROL}
    if 'PyEmuera.pyz' in rows and rows['PyEmuera.pyz']['sha256'] != units['pyz_sha256']:
        raise ValueError('untested pyz')
    if set(rows) & POST_BUILD:
        raise ValueError('postbuild sidecar in stage')
    pack = {'schema': 'pyemuera-public-pack-manifest-r50-1', 'engine_version': version,
            'artifact_role': role, 'kind': kind, 'public_policy_sha256': policy_sha256,
            'pyz_sha256': rows.get('PyEmuera.pyz', {}).get('sha256'),
            'unit_result': {k: units[k] for k in ('tests', 'failures', 'errors', 'skipped')},
            'files': rows, 'pack_excludes': sorted(CONTROL),
            'hashlists_exclude': ['MANIFEST.sha256', 'SHA256.txt'],
            'external_sidecars': sorted(POST_BUILD), **{k: False for k in GATES}}
    data = json_bytes(pack)
    (stage / 'PACK_MANIFEST.json').write_bytes(data)
    hashes = {n: row['sha256'] for n, row in rows.items()}
    hashes['PACK_MANIFEST.json'] = sha(data)
    body = ''.join(f'{digest}  {name}\n' for name, digest in sorted(hashes.items())).encode('utf-8')
    for name in ('MANIFEST.sha256', 'SHA256.txt'):
        (stage / name).write_bytes(body)
    # Full in-memory pins protect the manifest and membership, not just its text.
    return inventory(stage)


def write_zip(stage, output, pins):
    """Stream and recheck every byte; never replace an existing output."""
    check_names(list(pins))
    if output.exists():
        raise FileExistsError('fresh ZIP output required')
    pending = output.with_name(output.name + '.pending')
    if inventory(stage) != pins:
        raise ValueError('stage membership or content changed after freeze')
    check_names([stage.name])
    created = False
    try:
        with pending.open('xb') as target:
            created = True
            with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for rel, pin in sorted(pins.items()):
                    path = source_file(stage, rel)
                    digest, size = hashlib.sha256(), 0
                    info = zipfile.ZipInfo(stage.name + '/' + rel, (2026, 10, 15, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    with path.open('rb') as stream, archive.open(info, 'w', force_zip64=True) as dest:
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                            size += len(chunk)
                            dest.write(chunk)
                    if pin != {'bytes': size, 'sha256': digest.hexdigest()}:
                        raise ValueError('stage content changed after freeze: ' + rel)
            target.flush()
            os.fsync(target.fileno())
        if inventory(stage) != pins:
            raise ValueError('stage membership or content changed after freeze')
        # Atomic, no-clobber publication on the same filesystem (Windows/Unix).
        os.link(pending, output)
    finally:
        if created:
            pending.unlink(missing_ok=True)
    raw = output.read_bytes()
    return {'artifact': output.name, 'bytes': len(raw), 'sha256': sha(raw)}


def prepare(root, stage, output, kind, policy_path):
    if stage.exists() or output.exists() or output.with_name(output.name + '.pending').exists():
        raise FileExistsError('fresh stage and output required')
    if stage == root or stage.is_relative_to(root) or root.is_relative_to(stage):
        raise ValueError('stage must be outside source tree')
    if output.is_relative_to(stage):
        raise ValueError('output must be outside stage')
    policy, role, names, policy_pin = load_policy(policy_path, kind)
    if kind == 'developer':
        all_tests = {p.relative_to(root).as_posix() for p in (root / 'tests').glob('*.py')}
        required_tools = {'tools/package_r50.py', 'tools/verify_distribution_r50.py',
                          'tools/check_public_hygiene_r50.py', 'tools/run_final_tests_r47.py',
                          'tools/build_pyz.py', 'tools/zipapp_inputs/__main__.py', 'build_zipapp.py', 'pyproject.toml'}
        if not all_tests | required_tools <= names:
            raise ValueError('developer policy omits tests or required release tools: '
                             + ', '.join(sorted((all_tests | required_tools) - names)))
    # Preflight all inputs before creating a stage; never copy a broad directory.
    for name in sorted(names - CONTROL):
        source_file(root, name)
    units, build = validate_metadata(root)
    stage.mkdir(parents=True, exist_ok=False)
    for name in sorted(names - CONTROL):
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_file(root, name).read_bytes())
    pins = freeze(stage, VERSION, units, build.get('artifact_role', 'development_candidate'),
                  kind=kind, policy_sha256=policy_pin)
    # Independent byte privacy/license audit. Never modify the scanner's policy.
    check = subprocess.run([sys.executable, '-B', str(root / 'tools/check_public_hygiene_r50.py'),
                            str(stage), '--kind', role, '--policy', str(policy_path)],
                           capture_output=True, text=True, encoding='utf-8')
    if check.returncode or not json.loads(check.stdout).get('passed'):
        raise ValueError('public stage hygiene failed; inspect scanner independently')
    return write_zip(stage, output, pins)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--kind', required=True, choices=['runtime', 'developer', 'evidence'])
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--policy', type=Path)
    args = parser.parse_args()
    root = args.source.resolve()
    policy = args.policy.resolve() if args.policy else root / 'R50_PUBLIC_PACKAGE_POLICY.json'
    try:
        result = prepare(root, args.stage.absolute(), args.out.absolute(), args.kind, policy)
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
        # Avoid serializing source absolute paths from filesystem exceptions.
        print(json.dumps({'passed': False, 'error': type(error).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
