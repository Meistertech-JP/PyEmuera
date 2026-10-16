"""Targeted source-reviewed 1824 overloads. See SOURCE_AUDIT_1824.json for residuals.

No module-level game state; all changes are per VM. Errors are not stubbed out.
"""

from __future__ import annotations
import datetime
import math
import re
from pathlib import Path
from .errors import EraError, Unsupported
from .expr import integer, evaluate, i64
from .text import display_width, legacy_substring

from .registry import FUNCTION_SPECS

ARITY = {
    n: (s['min_args'], s['max_args'])
    for n, s in FUNCTION_SPECS.items()
    if s['handler'] == 'compat1824'
}


def error(message, code='E_ARGUMENT'):
    return EraError(message, code=code)


def string(value):
    if not isinstance(value, str):
        raise error('String required', 'E_TYPE')
    return value


def utf16(text):
    return string(text).encode('utf-16-le', errors='surrogatepass')


def units(text):
    raw = utf16(text)
    return [int.from_bytes(raw[i : i + 2], 'little') for i in range(0, len(raw), 2)]


def scalar_at(text, index):
    a = units(text)
    if not 0 <= index < len(a):
        raise error('UTF-16 index outside string', 'E_INDEX')
    n = a[index]
    if 0xD800 <= n <= 0xDBFF:
        if index + 1 >= len(a) or not 0xDC00 <= a[index + 1] <= 0xDFFF:
            raise error('Unpaired UTF-16 high surrogate')
        return 0x10000 + ((n - 0xD800) << 10) + (a[index + 1] - 0xDC00)
    if 0xDC00 <= n <= 0xDFFF:
        raise error('Index points at a UTF-16 low surrogate')
    return n


def rule_string(vm, pattern):
    pattern = string(pattern)
    if not pattern or display_width(pattern) <= 0:
        raise error('GETLINESTR関数の引数が空文字列です')
    width = getattr(vm.console, 'columns', 100)
    return legacy_substring(
        pattern * (width // max(1, display_width(pattern)) + 1), 0, width
    )


def int_text(text):
    # Fullwidth digits, whitespace and trailing junk are not accepted by 1824.
    text = string(text)
    if (
        re.fullmatch(r'[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)(?:\.[0-9]*)?', text)
        is None
    ):
        return None
    head = text.split('.', 1)[0]
    sign = -1 if head.startswith('-') else 1
    digits = head.lstrip('+-')
    base = (
        16
        if digits.lower().startswith('0x')
        else 2 if digits.lower().startswith('0b') else 10
    )
    n = sign * int(digits, base)
    if not -(1 << 63) <= n < 1 << 63:
        raise error('Int64 text overflow', 'E_ARITH')
    return n


def text_path(vm, index, force):
    from .native_store import safe_overlay

    index = integer(index)
    if not 0 <= index <= 0x7FFFFFFF:
        return None, None
    name = f'txt{index:02d}.txt'
    use_folder = (
        bool(force)
        or vm.data.config.get('セーブデータをsavフォルダ内に作成する', 'NO').upper()
        == 'YES'
    )
    folder = 'text-sav' if use_folder else 'text-root'
    private = safe_overlay(vm.data.root, folder, name)
    original = vm.data.root / ('sav' if use_folder else '') / name
    if not original.resolve().is_relative_to(vm.data.root):
        raise error('Text input path escapes game', 'E_PATH')
    return private, original


def numeric_check(text):
    """ASCII path of v24 IsNumericMethod + NumericCheck; not TOINT.

    v24 still calls readDigits, so conversion/overflow can still raise.
    Non-ASCII/culture boundaries remain explicitly unverified in the audit.
    """
    text = string(text)
    if not text or text[0] not in '+-0123456789':
        return 0
    if text[0] in '+-' and (len(text) < 2 or text[1] not in '0123456789'):
        return 0
    base = (
        16
        if text.startswith(('0x', '0X'))
        else 2 if text.startswith(('0b', '0B')) else 10
    )
    pos = 2 if base != 10 else 0
    alphabet = '0123456789abcdefABCDEF' if base == 16 else '0123456789'
    if pos >= len(text) or text[pos] not in alphabet + '+-':
        return 0

    def digits(pos):
        start = pos
        if pos < len(text) and text[pos] in '+-':
            pos += 1
        while pos < len(text) and text[pos] in alphabet:
            if base == 2 and text[pos] not in '01':
                raise error('Invalid binary digit', 'E_ARITH')
            pos += 1
        try:
            n = int(text[start:pos], base)
        except ValueError as exc:
            raise error('Invalid numeric digits', 'E_ARITH') from exc
        if base != 10 and n < 0:
            raise error('Negative nondecimal numeric digits', 'E_ARITH')
        if base != 10 and 0 <= n < 1 << 64:
            n = i64(n)
        elif not -(1 << 63) <= n < 1 << 63:
            raise error('Int64 text overflow', 'E_ARITH')
        return n, pos

    significand, pos = digits(pos)
    if pos < len(text) and text[pos] in 'pPeE':
        expbase = 2 if text[pos] in 'pP' else 10
        pos += 1
        if pos >= len(text) or text[pos] not in '0123456789':
            return 0
        exponent, pos = digits(pos)
        exponent = (exponent + (1 << 31)) % (1 << 32) - (1 << 31)
        if exponent:
            try:
                value = significand * math.pow(expbase, exponent)
            except OverflowError as exc:
                raise error('Numeric exponent overflow', 'E_ARITH') from exc
            if (
                not math.isfinite(value)
                or value > float((1 << 63) - 1)
                or value < float(-(1 << 63))
            ):
                raise error('Numeric exponent overflow', 'E_ARITH')
    return int(
        pos == len(text)
        or text[pos] == '.'
        and all(c in '0123456789' for c in text[pos + 1 :])
    )


def call(vm, name, nodes):
    if name == 'ARRAYMSORT':
        return array_msort(vm, nodes)
    if name in ('FINDELEMENT', 'FINDLASTELEMENT'):
        return find_element(vm, name, nodes)
    a = [evaluate(n, vm) for n in nodes]

    def optional(i, default):
        return a[i] if len(a) > i and a[i] is not None else default

    if name == 'POWER':
        from .numeric_instructions import power_value

        return power_value(*a)
    if name == 'SQRT':
        x = integer(a[0])
        try:
            y = math.sqrt(x)
        except (OverflowError, ValueError) as exc:
            raise error('Math domain/overflow', 'E_ARITH') from exc
        if not math.isfinite(y) or not -(1 << 63) < y < (1 << 63):
            raise error('Math overflow', 'E_ARITH')
        return int(y)
    if name in ('CBRT', 'LOG', 'LOG10', 'EXPONENT'):
        x = integer(a[0])
        if (name == 'CBRT' and x < 0) or (name in ('LOG', 'LOG10') and x <= 0):
            raise error('Math domain error', 'E_ARITH')
        try:
            y = (
                x ** (1 / 3)
                if name == 'CBRT'
                else (
                    math.log(x)
                    if name == 'LOG'
                    else math.log10(x) if name == 'LOG10' else math.exp(x)
                )
            )
        except OverflowError as exc:
            raise error('Math overflow', 'E_ARITH') from exc
        if not math.isfinite(y) or not -(1 << 63) < y < (1 << 63):
            raise error('Math overflow', 'E_ARITH')
        return int(y)
    if name == 'CONVERT':
        n, base = map(integer, a)
        if base not in (2, 8, 10, 16):
            raise error('CONVERT base must be 2,8,10,16')
        if base == 10:
            return str(n)
        return format(n & ((1 << 64) - 1), {2: 'b', 8: 'o', 16: 'x'}[base])
    if name == 'UNICODE':
        n = integer(a[0])
        if not 0 <= n <= 65535:
            raise error('UNICODE関数に範囲外の値(' + str(n) + ')が渡されました')
        if (n < 0x1F and n not in (10, 13)) or 0x7F <= n <= 0x9F:
            message = (
                'UNICODE関数に制御文字に対応する値(0x'
                + format(n, 'X')
                + ')が渡されました'
            )
            location = getattr(vm, 'location', None)
            if location is not None:
                vm.console.system_line(
                    '注意:'
                    + str(location.path).replace('\\', '/').split('/')[-1]
                    + 'の'
                    + str(location.line)
                    + '行目で'
                    + message
                )
            elif hasattr(vm, 'program'):
                vm.program.warnings.append(message)
            return ''
        return chr(n)
    if name == 'UNICODEBYTE':
        s = string(a[0])
        if not s:
            raise error('UNICODEBYTE requires a nonempty string')
        # .NET UTF32 encoder replaces an unpaired surrogate.
        try:
            return scalar_at(s, 0)
        except EraError:
            return 0xFFFD
    if name in ('STRLENU', 'STRLENSU'):
        return len(utf16(a[0])) // 2
    if name == 'SUBSTRINGU':
        from .substring_arguments import optional_index

        raw = utf16(a[0])
        start = max(0, optional_index(a, 1, 0))
        count = optional_index(a, 2, -1)
        return raw[start * 2 : None if count < 0 else (start + count) * 2].decode(
            'utf-16-le', errors='surrogatepass'
        )
    if name == 'CHARATU':
        raw = utf16(a[0])
        index = integer(a[1])
        return (
            raw[index * 2 : index * 2 + 2].decode('utf-16-le', errors='surrogatepass')
            if 0 <= index < len(raw) // 2
            else ''
        )
    if name == 'STRFINDU':
        hay, needle = units(a[0]), units(a[1])
        start = integer(optional(2, 0))
        if not 0 <= start <= len(hay):
            raise error('STRFINDU start outside string', 'E_INDEX')
        return next(
            (
                i
                for i in range(start, len(hay) - len(needle) + 1)
                if hay[i : i + len(needle)] == needle
            ),
            -1,
        )
    if name == 'ENCODETOUNI':
        s = string(a[0])
        index = integer(optional(1, 0))
        if not s:
            return -1
        return scalar_at(s, index)
    if name == 'ISNUMERIC':
        return numeric_check(a[0])
    if name == 'TOINT':
        n = int_text(a[0])
        return 0 if n is None else n
    if name == 'GETTIMES':
        return datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    if name == 'GETSTYLE':
        return vm.ui['style']
    if name == 'GETFOCUSCOLOR':
        return (
            int(vm.data.config.get('選択中文字色', '16776960'), 0)
            if vm.data.config.get('選択中文字色', '').startswith('0x')
            else 0xFFFF00
        )
    if name == 'CURRENTALIGN':
        return vm.ui['alignment']
    if name == 'COLOR_FROMRGB':
        rgb = list(map(integer, a))
        if any(not 0 <= x <= 255 for x in rgb):
            raise error('RGB component outside 0..255')
        return rgb[0] * 65536 + rgb[1] * 256 + rgb[2]
    if name == 'COLOR_FROMNAME':
        from .named_colors import COLORS

        n = string(a[0]).lower()
        if n == 'transparent':
            raise error('Transparent is not a valid display color')
        return COLORS.get(n, -1)
    if name == 'CHKDATA':
        status, description = vm.saves.check(integer(a[0]))
        vm.set('RESULTS', description)
        return status
    if name == 'GETNUMB':
        name_string = string(a[0])
        vm.lookup(name_string.upper())
        return vm.data.keyword_number(name_string, string(a[1]))
    if name == 'GETLINESTR':
        return rule_string(vm, a[0])
    if name in ('SAVETEXT', 'LOADTEXT'):
        # Deliberate isolation policy: original text files are read-only.
        # Writes use .pyemuera/text-root or text-sav, like native save overlays.
        writing = name == 'SAVETEXT'
        pos = 1 if writing else 0
        if any(x is None for x in a):
            raise error(name + ' does not allow omitted argument holes')
        force = integer(optional(pos + 1, 0))
        utf8 = integer(optional(pos + 2, 0))
        dest, original = text_path(vm, a[pos], force)
        if dest is None:
            return 0 if writing else ''
        codec = (
            'utf-8-sig'
            if utf8
            or vm.data.config.get('セーブデータをUTF-8で保存する', 'NO').upper()
            == 'YES'
            else 'cp932'
        )
        try:
            if writing:
                data = string(a[0]).encode(codec)
                if len(data) > 16 * 1024 * 1024:
                    raise error('SAVETEXT size limit', 'E_LIMIT')
                vm.saves.atomic_write(dest, data)
                return 1
            p = dest if dest.is_file() else original
            if not p.is_file():
                return ''
            if p.stat().st_size > 16 * 1024 * 1024:
                raise error('LOADTEXT size limit', 'E_LIMIT')
            raw = p.read_bytes()
            if raw.startswith(b'\xef\xbb\xbf'):
                codec = 'utf-8-sig'
            elif raw.startswith((b'\xff\xfe', b'\xfe\xff')):
                codec = 'utf-16'
            return raw.decode(codec)
        except (OSError, UnicodeError):
            return 0 if writing else ''
    raise Unsupported('Source-compat function ' + name)


def find_element(vm, name, nodes):
    ref = vm.ref_node(nodes[0])
    var = ref.variable
    if len(var.dims) != 1:
        raise error('FINDELEMENT requires a one-dimensional array', 'E_TYPE')
    target = evaluate(nodes[1], vm)
    if var.string != isinstance(target, str):
        raise error('FINDELEMENT type mismatch', 'E_TYPE')
    a = [evaluate(n, vm) for n in nodes[2:]]
    start = integer(a[0]) if a and a[0] is not None else 0
    end = integer(a[1]) if len(a) > 1 and a[1] is not None else ref.size()
    exact = bool(integer(a[2])) if len(a) > 2 and a[2] is not None else False
    if not 0 <= start <= end <= ref.size():
        raise error('FINDELEMENT range', 'E_INDEX')
    from .regex1824 import Pattern, unit_string

    try:
        pattern = Pattern(target) if var.string else None
    except re.error as exc:
        raise error('Invalid regular expression') from exc
    for i in range(end - 1, start - 1, -1) if 'LAST' in name else range(start, end):
        value = var.get(ref.key[:-1] + (i,))
        if pattern:
            match = pattern.search(value)
            hit = bool(match) and (
                not exact
                or (match.start() == 0 and match.end() == len(unit_string(value)))
            )
        else:
            hit = value == target
        if hit:
            return i
    return -1


def array_msort(vm, nodes):
    from .sort1824 import framework_list_order
    from .expression_arguments import restructure_runtime

    # GetArray reads the token, not the element denoted by its subscripts.
    # Argument type/constant-axis validation is performed before this handler.
    nodes = restructure_runtime(vm, nodes)
    vars = [vm.lookup(n[1]) for n in nodes]
    if (
        any(v.character or v.readonly or len(v.dims) not in (1, 2) for v in vars)
        or len(vars[0].dims) != 1
    ):
        raise error(
            'ARRAYMSORT requires writable non-character arrays; first must be 1D',
            'E_TYPE',
        )
    first = vars[0]
    keys = []
    for i in range(first.dims[0]):
        value = first.get((i,))
        if value == ('' if first.string else 0):
            if first.string:
                return 0
            break
        keys.append(value)
    n = len(keys)
    order = framework_list_order(keys, string=first.string)
    destinations = {}
    for new, old in enumerate(order):
        destinations.setdefault(old, []).append(new)
    for v in vars:
        if v.dims[0] < n:
            return 0
        # Clone each argument when it is reached: aliases are sorted repeatedly,
        # and a later short array returns 0 after earlier arrays have changed.
        clone = v.values
        values = {k: value for k, value in clone.items() if k[0] >= n}
        for k, value in clone.items():
            for new in destinations.get(k[0], ()):
                values[(new,) + k[1:]] = value
        v.values = values
    return 1
