"""Build a deterministic stdlib zipapp; requires the same Python and zlib.

All ZIP metadata, member order and compression settings are explicit. Source
mtimes, absolute paths, bytecode and build reports are not embedded.
"""
import argparse
import hashlib
from pathlib import Path
import zipfile

TIMESTAMP = (2026, 10, 16, 0, 0, 0)
COMPRESSION_LEVEL = 9
DOCUMENTS = (
    'LICENSE', 'README_ja.md', 'ARCHITECTURE_ja.md', 'COMPATIBILITY_ja.md',
    'SOURCES.md', 'THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_MS_NLS_NOTICE_ja.md',
    'SOURCE_AUDIT_1824.json', 'SOURCE_AUDIT_1824_v24.json',
)


def source_members(root):
    files = {}
    for folder in ('pyemuera', 'licenses'):
        for path in (root / folder).rglob('*'):
            if path.is_symlink():
                raise ValueError('Build input symlink: ' + str(path))
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
                files[path.relative_to(root).as_posix()] = path.read_bytes()
    for name in DOCUMENTS:
        files[name] = (root / name).read_bytes()
    files['__main__.py'] = (root / 'tools/zipapp_inputs/__main__.py').read_bytes()
    return files


def build(root, output):
    files = source_members(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=COMPRESSION_LEVEL, strict_timestamps=True) as archive:
        archive.comment = b''
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, TIMESTAMP)
            entry.create_system = 3
            entry.create_version = 20
            entry.extract_version = 20
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.flag_bits = 0
            entry.internal_attr = 0
            entry.external_attr = 0o100644 << 16
            entry.extra = b''
            entry.comment = b''
            archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=COMPRESSION_LEVEL)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(build(Path(__file__).resolve().parents[1], args.out))


if __name__ == '__main__':
    main()
