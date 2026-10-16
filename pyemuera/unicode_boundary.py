"""UTF-16 state is lossless; only output boundaries replace lone units.

JSON uses ASCII escapes (standard JSON, reversible). Log UTF-8 is standard
Unicode with U+FFFD for unpaired units, matching archived StreamWriter Unicode
replacement. No normalization of BMP characters, spaces or line endings.
"""

import json


def units(text):
    b = text.encode('utf-16-le', 'surrogatepass')
    return [int.from_bytes(b[i : i + 2], 'little') for i in range(0, len(b), 2)]


def from_units(values):
    return b''.join(v.to_bytes(2, 'little') for v in values).decode(
        'utf-16-le', 'surrogatepass'
    )


def display_text(text):
    u = units(text)
    out = []
    i = 0
    while i < len(u):
        n = u[i]
        if 0xD800 <= n <= 0xDBFF and i + 1 < len(u) and 0xDC00 <= u[i + 1] <= 0xDFFF:
            out.append(chr(0x10000 + ((n - 0xD800) << 10) + u[i + 1] - 0xDC00))
            i += 2
            continue
        out.append('\ufffd' if 0xD800 <= n <= 0xDFFF else chr(n))
        i += 1
    return ''.join(out)


def utf8_log(text):
    return display_text(text).encode('utf-8')


def json_text(value):
    return (
        (json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        .encode('utf-8', 'backslashreplace')
        .decode('utf-8')
    )


def loss_records(lines):
    return [
        dict(
            history_entry=i,
            utf16_units=units(s),
            display_utf16_units=units(display_text(s)),
            lossy=True,
        )
        for i, s in enumerate(lines)
        if units(s) != units(display_text(s))
    ]
