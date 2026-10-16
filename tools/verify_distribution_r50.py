"""Read back saved public ZIP bytes independently of the package builder.

Use an external, reviewed exact hygiene policy. This module never imports the
builder, extracts an archive, executes its code, or edits an archived report.
ZIP CRC/SHA/size/member pins and the outer SHA are separate checks.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import struct
import subprocess
import sys
from urllib.parse import unquote
import zipfile
import zlib

VERSION = '3.0.0a10.dev4+r50'
CONTROL = {'MANIFEST.sha256', 'SHA256.txt', 'PACK_MANIFEST.json'}
HASHLISTS = {'MANIFEST.sha256', 'SHA256.txt'}
POST_BUILD = {'R50_DISTRIBUTION_INTEGRITY.json', 'R50_MANIFEST_VERIFICATION.json',
              'R50_CLEAN_ZIP_UNIT_TESTS.json', 'SHA256-r50.txt'}
GATES = ('formal_a10_release_gate', 'beta_release_gate', 'full_compatibility')
BASELINE_COUNT = 3209
BASELINE_IDS_SHA256 = 'de10a433b6bc4ed66e3b65d3e59e9ce5f2102bcd5f827ad299a0f9dd52575ac2'
BASELINE_SKIPS = {
    'test_boundary_a8.PseudoTerminalInputA8.test_one_key_needs_no_enter_and_restores_terminal',
    'test_boundary_a8.PseudoTerminalInputA8.test_single_key_interrupt_restores_terminal',
    'test_boundary_a8.PseudoTerminalInputA8.test_single_key_timeout_restores_terminal',
    'test_distribution.EdgeCases.test_save_symlink_escape',
    'test_native_save.NativeIntegration.test_symlink_native_destination_is_denied',
    'test_native_save.NativeIntegration.test_symlink_overlay_is_denied',
    'test_source_functions_a7.SourceFunctionsA7.test_text_output_symlink_rejected',
}
DOCUMENTS = {'README_ja.md', 'ARCHITECTURE_ja.md', 'COMPATIBILITY_ja.md',
             'CHANGELOG_ja.md', 'TEST_REPORT_ja.md', 'THIRD_PARTY_NOTICES.md',
             'THIRD_PARTY_MS_NLS_NOTICE_ja.md', 'docs/R50_KNOWN_LIMITATIONS_ja.md',
             'R50_DEVELOPMENT_REPORT_ja.md', 'R50_ARRAYSORT_COMPATIBILITY_ja.md',
             'R50_BETA_READINESS_ASSESSMENT_ja.md'}
COMMON = DOCUMENTS | {'LICENSE', 'PyEmuera.pyz', 'R50_UNIT_TESTS.json',
                      'R50_BUILD_CHECK.json', 'R50_REPRODUCIBLE_BUILD_CHECK.json',
                      'R50_COMPATIBILITY_DELTA.json'}
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


def safe_path(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        return False
    return (not any(ord(c) < 32 or ord(c) == 127 for c in name)
            and all(p and p not in {'.', '..'} and not p.endswith((' ', '.'))
                    and not re.search(r'[<>"|?*]', p)
                    and not re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p)
                    for p in name.split('/')))


def load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def exact_zip_coverage(raw):
    """Reject bytes that ZipFile can ignore, including inside deflate streams.

    The public builder emits single-disk ZIPs without comments, descriptors or
    discretionary extras. ZIP64 sizes/offsets are supported, including local
    force_zip64 headers below 4 GiB. Every raw byte must belong to a validated
    header, exact filename, ZIP64 field, compressed stream or central directory.
    """
    def fail():
        raise ValueError('ZIP has unsupported or unconsumed raw bytes')

    def unpack(fmt, offset):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(raw):
            fail()
        return struct.unpack_from(fmt, raw, offset)

    def zip64(extra, values, sentinel, widths):
        required = [i for i, value in enumerate(values) if value == sentinel[i]]
        if not required:
            if extra:
                fail()
            return values
        if len(extra) < 4:
            fail()
        tag, size = struct.unpack_from('<HH', extra)
        if tag != 1 or size != sum(widths[i] for i in required) or len(extra) != size + 4:
            fail()
        offset = 4
        for index in required:
            values[index] = int.from_bytes(extra[offset:offset + widths[index]], 'little')
            offset += widths[index]
        return values

    end = len(raw) - 22
    e = unpack('<4s4H2IH', end)
    if e[0] != b'PK\x05\x06' or e[1] or e[2] or e[3] != e[4] or e[7]:
        fail()
    count, central_size, central_start = e[4], e[5], e[6]
    central_end = end
    if end >= 20 and raw[end - 20:end - 16] == b'PK\x06\x07':
        locator = unpack('<4sIQI', end - 20)
        if locator[1] or locator[3] != 1:
            fail()
        z = unpack('<4sQ2H2I4Q', locator[2])
        if (z[0] != b'PK\x06\x06' or z[1] != 44 or z[4] or z[5]
                or z[6] != z[7] or locator[2] + 56 != end - 20):
            fail()
        if ((count != 0xffff and count != z[7])
                or (central_size != 0xffffffff and central_size != z[8])
                or (central_start != 0xffffffff and central_start != z[9])):
            fail()
        count, central_size, central_start, central_end = z[7], z[8], z[9], locator[2]
    elif count == 0xffff or central_size == 0xffffffff or central_start == 0xffffffff:
        fail()
    if count > 100000 or central_start + central_size != central_end:
        fail()
    entries, position = [], central_start
    for _ in range(count):
        c = unpack('<4s6H3I5H2I', position)
        if c[0] != b'PK\x01\x02' or c[3] & ~0x800 or c[4] not in (0, 8) or c[12]:
            fail()
        name_start = position + 46
        name = raw[name_start:name_start + c[10]]
        extra = raw[name_start + c[10]:name_start + c[10] + c[11]]
        values = zip64(extra, [c[9], c[8], c[16], c[13]],
                       [0xffffffff, 0xffffffff, 0xffffffff, 0xffff], [8, 8, 8, 4])
        if values[3] or len(name) != c[10]:
            fail()
        size, compressed, offset, _ = values
        if size > 128 * 1024**2:
            fail()
        entries.append((offset, name, c, size, compressed))
        position = name_start + c[10] + c[11]
    if position != central_end or sum(e[3] for e in entries) > 2 * 1024**3:
        fail()
    cursor = 0
    for offset, name, c, size, compressed in sorted(entries):
        if offset != cursor:
            fail()
        h = unpack('<4s5H3I2H', offset)
        if (h[0] != b'PK\x03\x04' or h[2] != c[3] or h[3] != c[4]
                or h[4:7] != c[5:8]):
            fail()
        name_start = offset + 30
        extra_start = name_start + h[9]
        data_start = extra_start + h[10]
        if raw[name_start:extra_start] != name:
            fail()
        local_size, local_compressed = zip64(raw[extra_start:data_start], [h[8], h[7]],
                                              [0xffffffff, 0xffffffff], [8, 8])
        if local_size != size or local_compressed != compressed:
            fail()
        cursor = data_start + compressed
        if cursor > central_start:
            fail()
        payload = raw[data_start:cursor]
        if c[4] == 8:
            decoder = zlib.decompressobj(-15)
            expanded = decoder.decompress(payload, size + 1)
            if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                    or len(expanded) != size):
                fail()
        elif compressed != size:
            fail()
    if cursor != central_start:
        fail()


def inspect_archive(path):
    """Independent CRC, exact byte pin and membership validation only.

    Return saved payload bytes for additional semantic checks. Structural errors
    are always failures, even when a forged manifest agrees with the payload.
    """
    errors, payloads = [], {}
    if hasattr(path, 'read'):
        raw_zip = path.read()
    else:
        raw_zip = Path(path).read_bytes()
    exact_zip_coverage(raw_zip)
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) > 100000 or sum(i.file_size for i in infos) > 2 * 1024**3:
            raise ValueError('archive resource limit')
        if len({n.casefold() for n in names}) != len(names):
            errors.append('duplicate or Windows case-collision')
        if any(not safe_path(n) for n in names):
            errors.append('unsafe archive member path')
        roots = {n.split('/')[0] for n in names}
        if len(roots) != 1:
            raise ValueError('archive must have one root')
        prefix = next(iter(roots)) + '/'
        for info in infos:
            if (info.flag_bits & 1 or info.is_dir()
                    or (info.external_attr >> 16) & 0o170000 not in {0, 0o100000}):
                errors.append('encrypted, directory or nonregular ZIP member')
            if info.file_size > 128 * 1024**2:
                raise ValueError('member resource limit')
            rel = info.filename[len(prefix):]
            # Reading every entry to EOF independently checks every CRC.
            raw = archive.read(info)
            if len(raw) != info.file_size:
                errors.append('ZIP size mismatch')
            payloads[rel] = raw
    if not CONTROL <= set(payloads):
        raise ValueError('missing manifest controls')
    pack = load_json(payloads['PACK_MANIFEST.json'])
    body = payloads['MANIFEST.sha256']
    if body != payloads['SHA256.txt']:
        errors.append('hashlists differ')
    if b'\r' in body or not body.endswith(b'\n'):
        errors.append('hashlist must have LF endings')
    hashes = {}
    for line in body.decode('utf-8').splitlines():
        if not re.fullmatch('[0-9a-f]{64}  .+', line):
            raise ValueError('invalid hashlist row')
        rel = line[66:]
        if rel in hashes:
            errors.append('duplicate hashlist row')
        if not safe_path(rel):
            errors.append('unsafe hashlist path')
        hashes[rel] = line[:64]
    if set(hashes) != set(payloads) - HASHLISTS:
        errors.append('hashlist membership')
    if set(pack['files']) != set(payloads) - CONTROL:
        errors.append('pack membership')
    for rel, raw in payloads.items():
        digest = sha(raw)
        if rel not in HASHLISTS and hashes.get(rel) != digest:
            errors.append('SHA mismatch: ' + rel if safe_path(rel) else 'SHA mismatch')
        if rel in pack['files'] and pack['files'][rel] != {'bytes': len(raw), 'sha256': digest}:
            errors.append('pack size/SHA mismatch: ' + rel if safe_path(rel) else 'pack size/SHA mismatch')
    if pack.get('pack_excludes') != sorted(CONTROL):
        errors.append('manifest exclusion contract')
    if pack.get('hashlists_exclude') != sorted(HASHLISTS):
        errors.append('hashlist exclusion contract')
    return payloads, pack, hashes, errors


def check_units(units, pack, pyz, version, errors):
    ids, new, rows = units['test_ids'], units['new_ids'], units['results']
    if (len(set(ids)) != len(ids) or len(set(new)) != len(new)
            or not set(new) <= set(ids) or set(rows) != set(ids)
            or units['tests'] != len(ids)):
        errors.append('unit result membership/count')
    baseline = sorted(set(ids) - set(new))
    if (len(baseline) != BASELINE_COUNT
            or sha(('\n'.join(baseline) + '\n').encode()) != BASELINE_IDS_SHA256
            or units.get('baseline_test_count') != BASELINE_COUNT
            or units.get('missing_baseline_ids') != []):
        errors.append('original 3209 baseline IDs not preserved')
    if (units.get('successful') is not True or units.get('failures') != 0
            or units.get('errors') != 0 or units.get('version') != version
            or units.get('pyz_sha256') != pyz):
        errors.append('final unit acceptance/version/pyz pin')
    for label, key in [('PASS', 'passed'), ('SKIP', 'skipped'), ('FAIL', 'failures'), ('ERROR', 'errors')]:
        if sum(row.get('outcome') == label for row in rows.values()) != units[key]:
            errors.append('unit outcome count: ' + key)
    if any(row.get('outcome') not in {'PASS', 'SKIP', 'FAIL', 'ERROR'} for row in rows.values()):
        errors.append('unknown unit outcome')
    for test_id, row in rows.items():
        if row.get('outcome') == 'SKIP' and (test_id not in BASELINE_SKIPS or not row.get('reason')):
            errors.append('new or unexplained unit skip')
    if pack.get('unit_result') != {k: units[k] for k in ('tests', 'failures', 'errors', 'skipped')}:
        errors.append('manifest unit counts')


def check_pyz(payloads, pack, policy, expected_pyz, version, errors):
    pyz_raw = payloads['PyEmuera.pyz']
    exact_zip_coverage(pyz_raw)
    pyz = sha(pyz_raw)
    if pack.get('pyz_sha256') != pyz or (expected_pyz and expected_pyz != pyz):
        errors.append('pyz pin')
    if 'PyEmuera-r50.pyz' in payloads and payloads['PyEmuera-r50.pyz'] != pyz_raw:
        errors.append('pyz alias differs')
    reports = [load_json(payloads[n]) for n in ('R50_BUILD_CHECK.json', 'R50_REPRODUCIBLE_BUILD_CHECK.json')]
    units = load_json(payloads['R50_UNIT_TESTS.json'])
    check_units(units, pack, pyz, version, errors)
    for report in reports:
        if (report.get('engine_version') != version or report.get('pyz_sha256') != pyz
                or report.get('passed') is not True or report.get('full_raw_bytes_equal') is not True
                or report.get('source_member_payloads_equal') is not True):
            errors.append('build acceptance/version/pyz pin')
        if any(report.get(k) is not False for k in GATES):
            errors.append('build release gates')
    if reports[0]['source_input_sha256'] != reports[1]['source_input_sha256']:
        errors.append('build reports disagree on source inputs')
    with zipfile.ZipFile(io.BytesIO(pyz_raw)) as app:
        infos = app.infolist()
        names = [i.filename for i in infos]
        if (names != sorted(names) or len(names) != len(set(n.casefold() for n in names))
                or any(not safe_path(n) for n in names)):
            errors.append('pyz order/duplicate/unsafe member')
        if set(names) != set(policy['allowlists']['pyz']):
            errors.append('pyz public allowlist membership')
        pins = reports[0]['source_input_sha256']
        if set(pins) != set(names):
            errors.append('pyz source pin membership')
        total = 0
        for info in infos:
            total += info.file_size
            if info.file_size > 128 * 1024**2 or total > 2 * 1024**3:
                raise ValueError('pyz resource limit')
            raw = app.read(info)
            if (info.flag_bits & 1 or info.is_dir() or info.date_time != (2026, 10, 15, 0, 0, 0)
                    or info.create_system != 3 or info.external_attr != 0o100644 << 16
                    or info.extra or info.comment or info.compress_type != zipfile.ZIP_DEFLATED):
                errors.append('pyz metadata')
            if sha(raw) != pins.get(info.filename):
                errors.append('pyz source pin: ' + info.filename)
            rel = 'tools/zipapp_inputs/__main__.py' if info.filename == '__main__.py' else info.filename
            if pack['kind'] == 'developer' and rel not in payloads:
                errors.append('developer source missing: ' + rel)
            if rel in payloads and payloads[rel] != raw:
                errors.append('source/pyz bytes: ' + rel)
        initializer = app.read('pyemuera/__init__.py').decode('utf-8')
        match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", initializer)
        if not match or match[1] != version:
            errors.append('embedded engine version')
        for rel in DOCUMENTS & set(names):
            if payloads.get(rel) != app.read(rel):
                errors.append('embedded current document: ' + rel)
        for required in policy.get('required', {}).get('pyz', []):
            if required not in names:
                errors.append('pyz license/required member missing')
    return pyz, units['tests']


def document_links(payloads, errors):
    checked = 0
    docs = DOCUMENTS | {n for n in payloads if n.startswith('R50_') and n.endswith('.md')}
    for name in sorted(docs & set(payloads)):
        body = payloads[name].decode('utf-8-sig')
        for match in re.finditer(r'\]\(([^)]+)\)', body):
            ref = match[1].strip().strip('<>').split('#', 1)[0]
            if not ref or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', ref):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(ref)))
            checked += 1
            if target not in payloads:
                errors.append('current document link: ' + name + ' -> ' + target)
    return checked


def verify(path, expected_pyz=None, version=VERSION, *, policy_path=None, scanner_path=None):
    errors, report = [], {'artifact': Path(path).name}
    try:
        raw = Path(path).read_bytes()
        report.update(bytes=len(raw), sha256=sha(raw))
        payloads, pack, hashes, structural = inspect_archive(io.BytesIO(raw))
        errors.extend(structural)
        report.update(files=len(payloads), registered=len(hashes),
                      manifest_sha256={n: sha(payloads[n]) for n in sorted(CONTROL)})
        if pack.get('schema') != 'pyemuera-public-pack-manifest-r50-1' or pack.get('engine_version') != version:
            errors.append('manifest schema/version')
        if any(pack.get(k) is not False for k in GATES):
            errors.append('manifest release gates')
        if pack.get('external_sidecars') != sorted(POST_BUILD) or set(payloads) & POST_BUILD:
            errors.append('postbuild sidecar separation')
        if policy_path is None:
            raise ValueError('external public policy required')
        policy_raw = Path(policy_path).read_bytes()
        policy = load_json(policy_raw)
        if pack.get('public_policy_sha256') != sha(policy_raw):
            errors.append('external policy SHA pin')
        kind = pack['kind']
        if kind not in {'runtime', 'developer', 'evidence'}:
            raise ValueError('invalid distribution kind')
        role = 'windows' if kind == 'evidence' else kind
        allowed = policy['allowlists'][role]
        if any(not safe_path(n) for n in allowed) or len(set(n.casefold() for n in allowed)) != len(allowed):
            raise ValueError('unsafe or duplicate policy member')
        if set(payloads) != set(allowed):
            errors.append('exact public allowlist membership')
        required = COMMON | set(policy.get('required', {}).get(role, []))
        if kind in {'developer', 'evidence'}:
            required |= EVIDENCE
        if not required <= set(payloads):
            errors.append('required current payload/document/license missing')
        if not any(n.startswith('licenses/') for n in payloads):
            errors.append('license directory missing')
        report['pyz_sha256'], report['unit_tests'] = check_pyz(payloads, pack, policy, expected_pyz, version, errors)
        report['current_document_links_checked'] = document_links(payloads, errors)
        # JSON syntax and duplicate keys are checked even in non-build summaries.
        for name, content in payloads.items():
            if name.lower().endswith('.json'):
                load_json(content)
        scanner = Path(scanner_path) if scanner_path else Path(__file__).with_name('check_public_hygiene_r50.py')
        check = subprocess.run([sys.executable, '-B', str(scanner), str(Path(path)),
                                '--kind', role, '--policy', str(Path(policy_path))],
                               capture_output=True, text=True, encoding='utf-8')
        privacy = load_json(check.stdout)
        report['public_hygiene'] = privacy
        if check.returncode or privacy.get('passed') is not True:
            errors.append('independent public hygiene failed')
        # Detect an archive replaced/modified while its saved bytes were checked.
        if Path(path).read_bytes() != raw:
            errors.append('saved archive changed during verification')
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile,
            zipfile.LargeZipFile, RuntimeError, EOFError, zlib.error, struct.error) as error:
        errors.append('verification error: ' + type(error).__name__)
    report.update(errors=errors, passed=not errors)
    return report


def verify_outer_hashlist(path, artifacts):
    """Check a separate conventional SHA256 list without resolving outside it."""
    rows, errors = {}, []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not re.fullmatch(r'[0-9a-f]{64}  [^/\\]+', line):
            raise ValueError('invalid outer SHA row')
        name = line[66:]
        if not safe_path(name) or name in rows:
            raise ValueError('unsafe/duplicate outer SHA row')
        rows[name] = line[:64]
    names = [Path(p).name for p in artifacts]
    if len(set(n.casefold() for n in names)) != len(names) or set(rows) != set(names):
        errors.append('outer SHA membership')
    for artifact in artifacts:
        if rows.get(Path(artifact).name) != sha(Path(artifact).read_bytes()):
            errors.append('outer SHA mismatch: ' + Path(artifact).name)
    return {'passed': not errors, 'errors': errors, 'artifacts': len(artifacts)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', nargs='+', type=Path)
    parser.add_argument('--policy', required=True, type=Path)
    parser.add_argument('--pyz-sha256')
    parser.add_argument('--outer-sha256', type=Path)
    parser.add_argument('--external-pyz', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    reports = [verify(p, args.pyz_sha256, policy_path=args.policy) for p in args.zip]
    result = {'schema': 'r50-distribution-independent-1', 'separate_process': True,
              'archives': reports, 'passed': all(r['passed'] for r in reports)}
    pins = {r.get('pyz_sha256') for r in reports}
    if len(pins) != 1 or None in pins:
        result['passed'] = False
        result['cross_zip_pyz_pin'] = False
    else:
        result['cross_zip_pyz_pin'] = True
    if args.external_pyz:
        result['external_pyz_matches'] = sha(args.external_pyz.read_bytes()) in pins
        result['passed'] &= result['external_pyz_matches']
    if args.outer_sha256:
        result['outer_sha256'] = verify_outer_hashlist(args.outer_sha256,
                                                      args.zip + ([args.external_pyz] if args.external_pyz else []))
        result['passed'] &= result['outer_sha256']['passed']
    # Never overwrite a ZIP, policy, input pyz, or earlier verifier report.
    if args.out.resolve() in {p.resolve() for p in args.zip + [args.policy]
                               + ([args.external_pyz] if args.external_pyz else [])
                               + ([args.outer_sha256] if args.outer_sha256 else [])}:
        parser.error('report must be separate from all inputs')
    with args.out.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'archives': [
        {k: r[k] for k in ('artifact', 'errors')} for r in reports]}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
