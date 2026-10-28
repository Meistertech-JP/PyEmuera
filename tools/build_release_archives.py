"""Build the two public ZIPs and SHA-256 inventory from a frozen source tree.

Usage: python tools/build_pyz.py --out PyEmuera.pyz
       python tools/build_release_archives.py --out ../beta2-dist

Standard-library only. Refuses existing output files, symlinks and mismatched
pyz sources. ZIP metadata and entry order are deterministic on one zlib build.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '3.0.0b2'
STAMP = (2026, 10, 28, 0, 0, 0)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def path_inventory():
    """Use a pinned allowlist instead of archiving every file in the worktree."""
    listing = ROOT / 'packaging/public/source-files.txt'
    names = listing.read_text(encoding='utf-8').splitlines()
    if not names or len(names) != len(set(names)) or names != sorted(names):
        raise ValueError('Source allowlist is missing, duplicated or unsorted')
    if 'packaging/public/source-files.txt' not in names:
        raise ValueError('Source allowlist must include itself')
    entries = {}
    for name in names:
        parts = name.split('/')
        if (name.startswith('/') or '\\' in name or any(v in ('', '.', '..') for v in parts)
                or name == 'SHA256SUMS.txt' or any(v in ('.git', '__pycache__', '.pyemuera') for v in parts)):
            raise ValueError('Unsafe source allowlist entry: ' + name)
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked listed source file: ' + name)
        entries[name] = path.read_bytes()
    return entries


def verify_zipapp(pyz_data):
    sys.path.insert(0, str(ROOT / 'tools'))
    import build_pyz
    expected = build_pyz.source_members(ROOT)
    with zipfile.ZipFile(io.BytesIO(pyz_data)) as z:
        if z.testzip():
            raise ValueError('Corrupt pyz')
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Duplicate pyz members')
        actual = {p: z.read(p) for p in z.namelist()}
    if actual != expected:
        delta = sorted(k for k in set(actual) | set(expected) if actual.get(k) != expected.get(k))
        raise ValueError('pyz/source mismatch: ' + str(delta[:10]))
    if f'__version__ = "{VERSION}"' not in actual['pyemuera/__init__.py'].decode():
        raise ValueError('Wrong version in pyz')


def write_archive(path, files):
    if path.exists():
        raise FileExistsError(str(path))
    seen = set()
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(files.items()):
            parts = name.split('/')
            if name.startswith('/') or '\\' in name or any(v in ('.', '..', '') for v in parts):
                raise ValueError('Unsafe ZIP path: ' + name)
            norm = name.casefold()
            if norm in seen:
                raise ValueError('Case-insensitive collision: ' + name)
            seen.add(norm)
            info = zipfile.ZipInfo(name, STAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def add_manifest(files):
    lines = ['# SHA-256 of all files except SHA256SUMS.txt itself.']
    lines += [f'{sha(raw)}  {name}' for name, raw in sorted(files.items())]
    return {**files, 'SHA256SUMS.txt': ('\r\n'.join(lines) + '\r\n').encode('ascii')}


def runtime_files(source):
    direct = {
        'PyEmuera.pyz': 'PyEmuera.pyz',
        'README_ja.txt': 'packaging/public/README_ja.txt',
        'HOW_TO_USE_ja.txt': 'packaging/public/HOW_TO_USE_ja.txt',
        'KNOWN_ISSUES_ja.txt': 'packaging/public/KNOWN_ISSUES_ja.txt',
        'CHANGELOG_ja.txt': 'packaging/public/CHANGELOG_ja.txt',
        'THIRD_PARTY_NOTICES.txt': 'packaging/public/THIRD_PARTY_NOTICES.txt',
        'Start_PyEmuera.bat': 'packaging/public/Start_PyEmuera.bat',
        'Check_PyEmuera.bat': 'packaging/public/Check_PyEmuera.bat',
        'Diagnose_PyEmuera.bat': 'packaging/public/Diagnose_PyEmuera.bat',
        'LICENSE.txt': 'LICENSE',
        'sample/README_ja.txt': 'packaging/public/sample_README_ja.txt',
        'licenses/MS_OPEN_SPECIFICATIONS_NOTICE.txt': 'pyemuera/resources/MS_OPEN_SPECIFICATIONS_NOTICE.txt',
    }
    out = {dest: source[src] for dest, src in direct.items()}
    for name, raw in source.items():
        if name.startswith('licenses/'):
            out[name] = raw
        elif name.startswith('examples/smoke/') and name != 'examples/smoke/README_ja.txt':
            out['sample/' + name[len('examples/smoke/'):]] = raw
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if ROOT == out or ROOT in out.parents or out.exists():
        raise ValueError('Output must be a new directory outside the source tree')
    inputs = path_inventory()
    pyz_data = inputs.get('PyEmuera.pyz')
    if pyz_data is None:
        raise FileNotFoundError('Build PyEmuera.pyz before packaging')
    verify_zipapp(pyz_data)
    out.mkdir(parents=True)
    candidates = {
        f'PyEmuera-{VERSION}-runtime.zip': add_manifest(runtime_files(inputs)),
        f'PyEmuera-{VERSION}-source.zip': add_manifest(inputs),
    }
    reports = {}
    for name, entries in candidates.items():
        p = out / name
        write_archive(p, entries)
        with zipfile.ZipFile(p) as z:
            if z.testzip():
                raise ValueError('ZIP CRC failure: ' + name)
            for entry, raw in entries.items():
                if z.read(entry) != raw:
                    raise ValueError('ZIP member mismatch: ' + entry)
        reports[name] = {'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size, 'members': len(entries)}
    (out / f'PyEmuera-{VERSION}.pyz').write_bytes(pyz_data)
    reports[f'PyEmuera-{VERSION}.pyz'] = {'sha256': sha(pyz_data), 'bytes': len(pyz_data), 'members': None}
    (out / 'SHA256-public.txt').write_text(''.join(f'{item["sha256"]}  {name}\n' for name, item in sorted(reports.items())), encoding='ascii')
    (out / 'BUILD_REPORT.json').write_text(json.dumps({'version': VERSION, 'python': sys.version, 'archives': reports}, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
