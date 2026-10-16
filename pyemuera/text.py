from __future__ import annotations
from pathlib import Path
from functools import lru_cache
from .errors import EraError


def read_text(path: Path, encoding: str = "auto") -> tuple[str, str]:
    data = path.read_bytes()
    if encoding != "auto":
        try:
            return data.decode(encoding).lstrip("\ufeff"), encoding
        except (UnicodeError, LookupError) as e:
            raise EraError(
                f"Cannot decode {path} as {encoding}: {e}", code="E_ENCODING"
            ) from e
    from .source_encoding import decode_source

    return decode_source(data)


def strip_comment(text: str) -> str:
    """Semicolons outside quoted strings end a logical line; ;!; enables it."""
    if text.lstrip().startswith(';!;'):
        text = text[: len(text) - len(text.lstrip())] + text.lstrip()[3:]
    quoted = escaped = False
    for i, c in enumerate(text):
        if escaped:
            escaped = False
        elif c == '\\':
            escaped = True
        elif c == '"':
            quoted = not quoted
        elif c == ';' and not quoted:
            return text[:i]
    return text


def quoted_end(text: str, start: int, formatted=False, level=0) -> int:
    """Return the end *after* a quoted token, respecting expressions in FORM."""
    if level > 64:
        raise EraError('String nesting limit', code='E_LIMIT')
    i = start + (2 if formatted else 1)
    while i < len(text):
        if formatted and text.startswith('\\@', i):
            i = conditional_end(text, i, level + 1)
            continue
        if text[i] == '\\':
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        if formatted and text[i] in '{%':
            i = (
                placeholder_end(text, i + 1, '}' if text[i] == '{' else '%', level + 1)
                + 1
            )
            continue
        i += 1
    raise EraError('Unclosed quoted string', code='E_SYNTAX')


def placeholder_end(text: str, start: int, close: str, level=0) -> int:
    if level > 64:
        raise EraError('String nesting limit', code='E_LIMIT')
    i = start
    depth = 0
    while i < len(text):
        if text.startswith('@"', i):
            i = quoted_end(text, i, True, level + 1)
            continue
        if text[i] == '"':
            i = quoted_end(text, i, False, level + 1)
            continue
        if text.startswith('\\@', i):
            i = conditional_end(text, i, level + 1)
            continue
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == close and depth == 0:
            return i
        i += 1
    raise EraError(
        "'"
        + ('{' if close == '}' else '%')
        + "'が使われましたが対応する'"
        + close
        + "'が見つかりません",
        code='E_FORMAT',
    )


def conditional_end(text: str, start: int, level=0) -> int:
    # A bare conditional is a single string expression. Placeholders can contain
    # further quoted/conditional expressions; those are skipped recursively.
    if level > 64:
        raise EraError('String nesting limit', code='E_LIMIT')
    i = start + 2
    branch = False
    depth = 0
    while i < len(text):
        if text.startswith('\\@', i):
            return i + 2
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if not branch:
            if text.startswith('@"', i):
                i = quoted_end(text, i, True, level + 1)
                continue
            if c == '"':
                i = quoted_end(text, i, False, level + 1)
                continue
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif c == '?' and depth == 0:
                branch = True
        elif c in '{%':
            i = placeholder_end(text, i + 1, '}' if c == '{' else '%', level + 1) + 1
            continue
        i += 1
    raise EraError('Unclosed FORM conditional', code='E_FORMAT')


def split_args(text: str, sep: str = ',') -> list[str]:
    """Split expression arguments, retaining nested quoted FORM tokens."""
    out = []
    start = 0
    depth = 0
    i = 0
    while i < len(text):
        if text.startswith('@"', i):
            i = quoted_end(text, i, True)
            continue
        if text.startswith('\\@', i):
            i = conditional_end(text, i)
            continue
        c = text[i]
        if c == '"':
            i = quoted_end(text, i)
            continue
        if c == '\\':
            i += 2
            continue
        if c in '({[':
            depth += 1
        elif c in ')}]':
            depth -= 1
            if depth < 0:
                raise EraError('Unbalanced delimiters: ' + text, code='E_SYNTAX')
        elif c == sep and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
        i += 1
    if depth:
        raise EraError('Unclosed delimiter: ' + text, code='E_SYNTAX')
    out.append(text[start:].strip())
    return out


def split_form_args(text: str) -> list[str]:
    out, start, depth, percent, quote, escape = [], 0, 0, False, False, False
    for i, c in enumerate(text):
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"':
            quote = not quote
        if quote:
            continue
        if c in '({':
            depth += 1
        elif c in ')}':
            depth -= 1
        elif c == '%' and not depth:
            percent = not percent
        elif c == ',' and depth == 0 and not percent:
            out.append(text[start:i].strip())
            start = i + 1
    out.append(text[start:].strip())
    return out


def find_assignment(text: str, *, legacy: bool = False):
    if '=' not in text:
        return None
    quote, escape, depth = False, False, 0
    operators = (
        "<<=",
        ">>=",
        "'=",
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "&=",
        "|=",
        "^=",
        "=",
    )
    if legacy:
        operators = ("==",) + operators
    for i, c in enumerate(text):
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"':
            quote = not quote
        if quote:
            continue
        if c in '({':
            depth += 1
        elif c in ')}':
            depth -= 1
        if depth:
            continue
        for op in operators:
            if text.startswith(op, i):
                if op == "==" and (
                    text[i : i + 3] == "===" or (i and text[i - 1] in "!<>=\'")
                ):
                    continue
                if op == '=' and (
                    text[i : i + 2] == '==' or (i and text[i - 1] in "!<>=+'-*/%&|^")
                ):
                    continue
                return text[:i].strip(), op, text[i + len(op) :].lstrip()
    return None


def display_width(text: str) -> int:
    # Legacy Emuera string widths are CP932 byte counts (not Unicode graphemes).
    return len(text.encode('cp932', errors='replace'))


def legacy_substring(text: str, start: int, length: int = -1) -> str:
    from .substring_utf16 import substring

    return substring(text, start, length)


def load_config(
    root: Path, encoding='auto', reader=None, warnings=None, *, analysis_mode=False
):
    """Native CSV default → user → CSV fixed, typed parsing and row locks."""
    from .config1824 import load

    return load(root, encoding, reader, warnings, analysis_mode=analysis_mode)


def split_printv(text: str) -> list[tuple[bool, str]]:
    """Legacy leading apostrophe is a raw field, not a quoted string."""
    result = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        literal = i < len(text) and text[i] == "'"
        if literal:
            start = i + 1
            end = text.find(',', start)
            if end < 0:
                end = len(text)
        else:
            start = i
            end = i
            quote = False
            escape = False
            depth = 0
            while end < len(text):
                c = text[end]
                if escape:
                    escape = False
                elif c == '\\':
                    escape = True
                elif c == '"':
                    quote = not quote
                elif not quote:
                    if c == '(':
                        depth += 1
                    elif c == ')':
                        depth -= 1
                    elif c == ',' and depth == 0:
                        break
                end += 1
        field = text[start:end]
        if not literal:
            field = field.strip()
        if not literal and not field:
            raise EraError('Empty PRINTV expression', code='E_SYNTAX')
        result.append((literal, field))
        i = end + 1
    return result


def split_dynamic_call(text: str) -> list[str]:
    """Separate a FORM target from expression arguments before formatting it.

    Supports both CALLFORM TARGET_{X}, expr and TARGET_{X}(expr). Parentheses
    inside {functions(...)} / %strings% belong to the name expression. Argument
    string literals must never be formatted as part of the dynamic name.
    """
    text = text.strip()
    i = 0
    while i < len(text):
        if text.startswith('\\@', i):
            i = conditional_end(text, i)
            continue
        ch = text[i]
        if ch in '{%':
            i = placeholder_end(text, i + 1, '}' if ch == '{' else '%') + 1
            continue
        if ch == '\\':
            i += 2
            continue
        if ch == ',':
            return [text[:i].strip()] + split_args(text[i + 1 :])
        if ch == '(':
            if not text.endswith(')'):
                raise EraError('Unclosed parenthesized dynamic call', code='E_SYNTAX')
            tail = text[i + 1 : -1].strip()
            return [text[:i].strip()] + (split_args(tail) if tail else [])
        i += 1
    return [text]


def split_case_args(text):
    """ExpressionParser.ReduceCaseExpressions stops after comma at EOL.

    Omitted interior CASE values remain an error; no blanket empty filtering.
    """
    return list(_case_arguments(text))


@lru_cache(maxsize=8192)
def _case_arguments(text):
    # Only immutable syntax is cached. Never retain evaluated values, variable
    # bindings or RNG results. The public splitter still returns a fresh list.
    parts = split_args(text)
    if parts and not parts[-1].strip() and text.rstrip().endswith(','):
        parts = parts[:-1]
    if not parts or any(not part.strip() for part in parts):
        raise EraError('CASEの引数は省略できません', code='E_SYNTAX')
    return tuple(parts)
