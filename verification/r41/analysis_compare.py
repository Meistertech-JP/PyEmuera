"""Compare received native bytes, replacing only listed absolute source paths.

Unlike root substitution, complete path substitution works across Windows and
POSIX without normalizing any other slash, BOM, whitespace, newline or text.
"""
import hashlib
from pathlib import Path, PureWindowsPath


def compare(native, python, *, native_root, python_root, source_files):
    left, right = Path(native).read_bytes(), Path(python).read_bytes()
    mappings = []
    a, b = left, right
    for relative in sorted(source_files, key=len, reverse=True):
        native_path = str(PureWindowsPath(native_root) / PureWindowsPath(relative))
        python_path = str((Path(python_root) / relative).resolve())
        marker = '<SOURCE_PATH:' + relative + '>'
        a = a.replace(native_path.encode('utf-16le'), marker.encode('utf-16le'))
        b = b.replace(python_path.encode('utf-16le'), marker.encode('utf-16le'))
        mappings.append({'relative_source': relative, 'native_absolute_path': native_path,
                         'python_absolute_path': python_path, 'marker': marker})
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    if first is None and len(a) != len(b):
        first = min(len(a), len(b))
    result = {'native_sha256': hashlib.sha256(left).hexdigest(),
              'python_sha256': hashlib.sha256(right).hexdigest(),
              'native_normalized_sha256': hashlib.sha256(a).hexdigest(),
              'python_normalized_sha256': hashlib.sha256(b).hexdigest(),
              'native_bytes': len(left), 'python_bytes': len(right),
              'raw_bytes_equal': left == right, 'path_normalized_bytes_equal': a == b,
              'first_mismatch_normalized_byte': first,
              'normalization': {'absolute_source_paths_only': mappings,
                                'bom_newlines_whitespace_text_order_unchanged': True}}
    for name, value in [('native', left), ('python', right)]:
        result[name + '_utf16le_bom'] = value.startswith(b'\xff\xfe')
        text = value[2:].decode('utf-16le') if value.startswith(b'\xff\xfe') else ''
        result[name + '_crlf_only'] = bool(text) and '\n' not in text.replace('\r\n', '') and '\r' not in text.replace('\r\n', '')
        result[name + '_trailing_crlf'] = value.endswith(b'\r\x00\n\x00')
    return result
