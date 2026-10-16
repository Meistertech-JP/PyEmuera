"""Freeze real staging content, generate fresh manifests, reject later edits.

Outer ZIP hashes and the independent verifier's results are external sidecars.
Hashlists exclude themselves; PACK_MANIFEST excludes all three control files.
Every other file, including build/test reports, is included by exact bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONTROL = {'MANIFEST.sha256', 'SHA256.txt', 'PACK_MANIFEST.json'}
POST_BUILD = {'R47_DISTRIBUTION_INTEGRITY.json', 'R47_MANIFEST_VERIFICATION.json',
              'R47_CLEAN_ZIP_UNIT_TESTS.json', 'SHA256-r47.txt'}


def excluded(rel):
    return (set(rel.parts) & {'.git', '__pycache__', '.pytest_cache', '.pyemuera', '.aws'}
            or rel.suffix.lower() in {'.pyc', '.pyo', '.exe', '.dll', '.sav'}
            or rel.as_posix() in CONTROL | POST_BUILD)


def inventory(directory):
    rows = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink(): raise ValueError('symlink in stage: ' + str(path))
        if path.is_file() and path.relative_to(directory).as_posix() not in CONTROL:
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            rows[path.relative_to(directory).as_posix()] = {'bytes': path.stat().st_size, 'sha256': digest}
    return rows


def freeze(stage, version, units, role='development_candidate'):
    rows = inventory(stage)
    pyz = rows.get('PyEmuera.pyz', {}).get('sha256')
    if pyz is not None and pyz != units['pyz_sha256']: raise ValueError('untested pyz')
    pack = {'schema': 'pyemuera-pack-manifest-3', 'engine_version': version,
            'artifact_role': role, 'pyz_sha256': pyz,
            'unit_result': {k: units[k] for k in ('tests', 'failures', 'errors', 'skipped')},
            'files': rows, 'pack_excludes': sorted(CONTROL),
            'hashlists_exclude': ['MANIFEST.sha256', 'SHA256.txt'],
            'external_sidecars': sorted(POST_BUILD),
            'formal_a10_release_gate': False, 'beta_release_gate': False, 'full_compatibility': False}
    data = (json.dumps(pack, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    (stage / 'PACK_MANIFEST.json').write_bytes(data)
    hashes = {n: row['sha256'] for n, row in rows.items()}
    hashes['PACK_MANIFEST.json'] = hashlib.sha256(data).hexdigest()
    body = ''.join(f'{value}  {name}\n' for name, value in sorted(hashes.items())).encode('utf-8')
    for name in ('MANIFEST.sha256', 'SHA256.txt'): (stage / name).write_bytes(body)
    return {n: {'bytes': (stage / n).stat().st_size,
                'sha256': hashlib.sha256((stage / n).read_bytes()).hexdigest()} for n in CONTROL}


def write_zip(stage, output, control_pins):
    pack = json.loads((stage / 'PACK_MANIFEST.json').read_text(encoding='utf-8'))
    expected = {**pack['files'], **control_pins}
    actual_names = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}
    if actual_names != set(expected): raise ValueError('stage membership changed after freeze')
    pending = output.with_suffix(output.suffix + '.pending')
    with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for rel, pin in sorted(expected.items()):
            path = stage / rel
            if path.is_symlink(): raise ValueError('stage symlink after freeze')
            digest = hashlib.sha256()
            size = 0
            info = zipfile.ZipInfo(stage.name + '/' + rel, (2026, 10, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with path.open('rb') as stream, archive.open(info, 'w', force_zip64=True) as dest:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    dest.write(chunk)
            if pin != {'bytes': size, 'sha256': digest.hexdigest()}:
                raise ValueError('stage changed after freeze: ' + rel)
    if output.exists(): raise FileExistsError(output)
    pending.rename(output)
    return {'path': str(output), 'bytes': output.stat().st_size}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--kind', choices=['developer', 'runtime', 'evidence'], default='developer')
    parser.add_argument('--source', type=Path, default=ROOT)
    args = parser.parse_args()
    stage = Path(args.stage).resolve()
    if stage.exists(): raise FileExistsError('use a fresh staging directory: ' + str(stage))
    source = args.source.resolve()
    units = json.loads((ROOT / 'R47_UNIT_TESTS.json').read_text(encoding='utf-8'))
    build = json.loads((ROOT / 'R47_BUILD_CHECK.json').read_text(encoding='utf-8'))
    if build['pyz_sha256'] != units['pyz_sha256']: raise ValueError('build/test pyz differs')
    runtime_names = {'PyEmuera.pyz', 'README_ja.md', 'CHANGELOG_ja.md', 'COMPATIBILITY_ja.md',
                     'ARCHITECTURE_ja.md', 'LICENSE', 'SOURCES.md', 'THIRD_PARTY_NOTICES.md',
                     'THIRD_PARTY_MS_NLS_NOTICE_ja.md', 'CAPABILITIES.json',
                     'Start_PyEmuera.bat', 'Check_PyEmuera.bat', 'Diagnose_PyEmuera.bat'}
    if args.kind == 'runtime':
        runtime_names.update(p.relative_to(source).as_posix() for p in source.glob('R47_*') if p.suffix in {'.md','.json'})
        runtime_names.update(p.relative_to(source).as_posix() for d in ['docs','licenses'] for p in (source/d).rglob('*') if p.is_file())
        pending=list(runtime_names);seen=set()
        while pending:
            name=pending.pop()
            if name in seen:continue
            seen.add(name);doc=source/name
            if doc.suffix!='.md' or not doc.is_file():continue
            body=doc.read_text(encoding='utf-8')
            refs=re.findall(r'\]\(([^)]+)\)',body)+re.findall(r'`([^`\n]+\.(?:md|json|txt))`',body)
            for ref in refs:
                ref=ref.split('#')[0]
                if not ref or ':' in ref:continue
                target=(doc.parent/ref).resolve()
                if not target.is_relative_to(source) or not target.is_file():continue
                rel=target.relative_to(source)
                if excluded(rel):continue
                key=rel.as_posix()
                if key not in runtime_names:runtime_names.add(key);pending.append(key)
    for path in sorted(source.rglob('*')):
        if not path.is_file(): continue
        rel = path.relative_to(source)
        if excluded(rel): continue
        if path.is_symlink(): raise ValueError('source symlink: ' + str(path))
        name = rel.as_posix()
        if args.kind == 'runtime' and not (name in runtime_names or name.startswith(('docs/', 'licenses/'))
                or (len(rel.parts) == 1 and name.startswith('R47_') and path.suffix in {'.md', '.json'})):
            continue
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    controls = freeze(stage, '3.0.0a10.dev4+r47', units, build['artifact_role'])
    result = write_zip(stage, Path(args.out).resolve(), controls)
    print(json.dumps(result))


if __name__ == '__main__': main()
