"""Conservative .NET Regex adapter for ERB text, no external dependency.

Matches operate on UTF-16 code units. Named groups/backreferences and .NET dollar
replacement tokens are translated explicitly. Balancing groups, duplicate named
captures, Unicode category escapes and class subtraction are NOT silently treated
as Python regex; they raise E_UNSUPPORTED. Culture/case-folding still differs.
"""

import re
from .errors import EraError, Unsupported


def unit_string(text):
    if not isinstance(text, str):
        raise EraError('Regex arguments must be strings', code='E_TYPE')
    raw = text.encode('utf-16-le', errors='surrogatepass')
    return ''.join(
        chr(int.from_bytes(raw[i : i + 2], 'little')) for i in range(0, len(raw), 2)
    )


def from_units(text):
    return text.encode('utf-16-le', errors='surrogatepass').decode(
        'utf-16-le', errors='surrogatepass'
    )


def escape(text):
    # Regex.Escape escapes this minimum set, unlike Python re.escape (which
    # also escapes ] } - & ~). Line controls have named escapes in .NET.
    if not isinstance(text, str):
        raise EraError('ESCAPE requires a string', code='E_TYPE')
    table = {'\n': r'\n', '\r': r'\r', '\t': r'\t', '\f': r'\f'}
    return ''.join(
        table.get(ch, ('\\' + ch) if ch in r'\*+?|{[()^$.# ' else ch) for ch in text
    )


class Pattern:
    def __init__(self, source):
        source = unit_string(source)
        if len(source) > 65536:
            raise EraError('Regex pattern budget', code='E_LIMIT')
        if re.search(r'\\[pP]\{|\(\?<[^>]*-|\(\?\'[^\']*-|\[[^\]]*-\[|\(\?\(', source):
            raise Unsupported(
                'Regex balancing/conditional groups, Unicode categories or class subtraction need .NET semantics'
            )
        # Reject Python-only constructs instead of accidentally adding a dialect.
        if '(?P' in source or re.search(r'\\[gUN]', source):
            raise Unsupported('Python-only regex syntax is not Emuera syntax')
        names = re.findall(
            r'\(\?<([A-Za-z_][A-Za-z0-9_]*)>|\(\?\'([A-Za-z_][A-Za-z0-9_]*)\'', source
        )
        flat = [a or b for a, b in names]
        if len(flat) != len(set(flat)):
            raise Unsupported('.NET repeated capture names are not implemented')
        source = re.sub(r'\(\?<([A-Za-z_][A-Za-z0-9_]*)>', r'(?P<\1>', source)
        source = re.sub(r'\(\?\'([A-Za-z_][A-Za-z0-9_]*)\'', r'(?P<\1>', source)
        source = re.sub(
            r'\\k<([A-Za-z_][A-Za-z0-9_]*)>|\\k\'([A-Za-z_][A-Za-z0-9_]*)\'',
            lambda m: '(?P=' + (m[1] or m[2]) + ')',
            source,
        )
        if flat and re.search(r'\\[1-9]', source):
            raise Unsupported(
                'Numbered backreferences mixed with named groups require .NET group numbering'
            )
        try:
            self.pattern = re.compile(source)
        except re.error as exc:
            raise EraError(
                'Invalid/unsupported regex: ' + str(exc), code='E_REGEX'
            ) from exc
        named = set(self.pattern.groupindex.values())
        unnamed = [i for i in range(1, self.pattern.groups + 1) if i not in named]
        self.numbering = {
            0: 0,
            **{i: n for i, n in enumerate(unnamed + sorted(named), 1)},
        }

    def search(self, text):
        return self.pattern.search(unit_string(text))

    def count(self, text):
        return sum(1 for _ in self.pattern.finditer(unit_string(text)))

    def replace(self, text, replacement):
        source = unit_string(text)
        replacement = unit_string(replacement)
        if len(source) > 16 * 1024 * 1024:
            raise EraError('Regex text budget', code='E_LIMIT')

        def substitute(m):
            out = []
            i = 0
            while i < len(replacement):
                if replacement[i] != '$' or i + 1 == len(replacement):
                    out.append(replacement[i])
                    i += 1
                    continue
                ch = replacement[i + 1]
                end = i + 2
                value = None
                if ch == '$':
                    value = '$'
                elif ch == '&':
                    value = m.group(0)
                elif ch == '`':
                    value = source[: m.start()]
                elif ch == "'":
                    value = source[m.end() :]
                elif ch == '_':
                    value = source
                elif ch == '+':
                    value = ''
                    for dotnet in sorted(self.numbering, reverse=True):
                        if dotnet and m.group(self.numbering[dotnet]) is not None:
                            value = m.group(self.numbering[dotnet])
                            break
                elif ch == '{':
                    close = replacement.find('}', end)
                    if close >= 0:
                        name = replacement[end:close]
                        key = (
                            self.numbering.get(int(name))
                            if name.isascii() and name.isdigit()
                            else name if name in self.pattern.groupindex else None
                        )
                        if key is not None:
                            value = m.group(key) or ''
                            end = close + 1
                elif ch.isascii() and ch.isdigit():
                    while (
                        end < len(replacement)
                        and replacement[end].isascii()
                        and replacement[end].isdigit()
                    ):
                        end += 1
                    key = self.numbering.get(int(replacement[i + 1 : end]))
                    if key is not None:
                        value = m.group(key) or ''
                if value is None:
                    out.append('$')
                    i += 1
                else:
                    out.append(value)
                    i = end
            return ''.join(out)

        return from_units(self.pattern.sub(substitute, source))


def function(vm, name, nodes):
    from .expr import evaluate

    a = [evaluate(n, vm) for n in nodes]
    if name == 'ESCAPE':
        return escape(a[0])
    p = Pattern(a[1])
    if name == 'STRCOUNT':
        return p.count(a[0])
    return p.replace(a[0], a[2])
