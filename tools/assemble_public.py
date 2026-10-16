"""Assemble the public PyEmuera ZIP from this source tree and a matching pyz.

  python tools/assemble_public.py --pyz PyEmuera.pyz --out ../public-build

The selection rules are in packaging/public/selection.json; the user documents and
launchers in packaging/public/ are copied byte for byte. The same command works in
the full development tree and in the extracted public "source" folder, and gives
the same ZIP for the same inputs. The pyz must have been built from this tree
(every module and document inside it must equal the file here). Files created by
running tests (__pycache__, .pyemuera, *.pyc) and a PyEmuera.pyz in this folder
are never copied; the --pyz file is placed at the ZIP root and in source/.
Standard library only; Python 3.10+. The output folder must be new and outside
this tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / 'packaging/public/selection.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tree_files():
    for path in sorted(ROOT.rglob('*')):
        if path.is_symlink():
            raise SystemExit('symlink in source tree: ' + str(path))
        if path.is_file():
            yield path.relative_to(ROOT).as_posix()


def select(rules, names):
    tools = {'tools/' + t for t in rules['source_tools']}
    picked = []
    for rel in names:
        parts = rel.split('/')
        if any(p in rules['excluded_path_parts'] for p in parts):
            continue
        if rel.endswith(tuple(rules['excluded_suffixes'])) or rel == 'PyEmuera.pyz':
            continue
        if (rel in rules['source_files'] or rel in tools
                or any(rel == p or (p.endswith('/') and rel.startswith(p)) for p in rules['source_prefixes'])):
            picked.append(rel)
    missing = sorted((set(rules['source_files']) | tools) - set(picked))
    if missing:
        raise SystemExit('required source files are missing: ' + ', '.join(missing))
    for prefix in rules['source_prefixes']:
        if not any(r == prefix or r.startswith(prefix) for r in picked):
            raise SystemExit('selection rule matched nothing: ' + prefix)
    return picked


def check_pyz(pyz_bytes, version):
    """The pyz must contain exactly the engine, licenses and documents of this tree."""
    import io
    sys.path.insert(0, str(ROOT / 'tools'))
    import build_pyz
    expected = build_pyz.source_members(ROOT)
    with zipfile.ZipFile(io.BytesIO(pyz_bytes)) as archive:
        actual = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
    if set(actual) != set(expected):
        raise SystemExit('pyz members differ from this tree: %s' % sorted(set(actual) ^ set(expected))[:10])
    changed = sorted(n for n in expected if actual[n] != expected[n])
    if changed:
        raise SystemExit('pyz was not built from this tree; differing members: %s' % changed[:10])
    marker = '__version__ = "%s"' % version
    if marker not in actual['pyemuera/__init__.py'].decode('utf-8'):
        raise SystemExit('pyz version is not ' + version)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--pyz', type=Path, required=True, help='PyEmuera.pyz built from this tree')
    parser.add_argument('--out', type=Path, required=True, help='new output folder outside this tree')
    args = parser.parse_args()
    rules = json.loads(SELECTION.read_text(encoding='utf-8'))
    out = args.out.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit('--out must be outside the source tree')
    out.mkdir(parents=True, exist_ok=False)
    pyz = args.pyz.resolve().read_bytes()
    check_pyz(pyz, rules['version'])

    files = {}  # path inside the ZIP root folder -> bytes

    def add(name, data):
        if name in files:
            raise SystemExit('duplicate output path: ' + name)
        files[name] = data

    for rel in select(rules, list(tree_files())):
        add('source/' + rel, (ROOT / rel).read_bytes())
    add('source/PyEmuera.pyz', pyz)
    add('PyEmuera.pyz', pyz)
    for name, rel in rules['user_files'].items():
        add(name, (ROOT / rel).read_bytes())
    excluded = set(rules['user_tree_excludes'])
    for dst, src in rules['user_trees'].items():
        for rel in tree_files():
            if rel.startswith(src) and rel not in excluded and not any(
                    p in rules['excluded_path_parts'] for p in rel.split('/')):
                add(dst + rel[len(src):], (ROOT / rel).read_bytes())
    for name in files:
        if name.startswith('/') or '..' in name.split('/') or '\\' in name:
            raise SystemExit('unsafe path: ' + name)
    lowered = {}
    for name in files:
        if name.lower() in lowered:
            raise SystemExit('case-insensitive name collision: %s / %s' % (name, lowered[name.lower()]))
        lowered[name.lower()] = name
    sums = ['# SHA-256 of every file in this folder, except SHA256SUMS.txt itself.',
            '# Check: sha256sum -c SHA256SUMS.txt (Linux), or Get-FileHash in PowerShell.']
    sums += ['%s  %s' % (sha(data), name) for name, data in sorted(files.items())]
    add('SHA256SUMS.txt', ('\r\n'.join(sums) + '\r\n').encode('ascii'))

    root_name = rules['zip_root']
    zip_path = out / (root_name + '.zip')
    stamp = tuple(rules['zip_timestamp'])
    with zipfile.ZipFile(zip_path, 'w') as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(root_name + '/' + name, stamp)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    for name, data in files.items():
        target = out / root_name / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    summary = {'version': rules['version'], 'zip': str(zip_path), 'zip_sha256': sha(zip_path.read_bytes()),
               'pyz_sha256': sha(pyz), 'files': len(files),
               'source_files': sum(1 for n in files if n.startswith('source/'))}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
