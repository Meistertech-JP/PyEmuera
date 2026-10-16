"""Physical ERB/ERH/CSV lines, following .NET StreamReader.ReadLine.

Only CR, LF and CRLF delimit physical lines. Unicode separators remain data.
Decoding, including BOM and incomplete-byte handling, belongs to read_text.
"""

import re


def source_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = re.split(r'\r\n|\r|\n', text)
    if text.endswith(('\r', '\n')):
        lines.pop()  # A final terminator does not create another physical line.
    return lines
