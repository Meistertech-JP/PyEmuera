"""Int64 formatting for the .NET Framework 4.x numeric format contract.

This is an integer/digit implementation: no float conversion, host locale, or
.NET installation is involved. The default profile is the Japanese Windows
reference culture. NumberFormat exposes the culture data separately from the
format grammar; Emuera's configurable money label is applied by its caller.

Contracts: referencesource/mscorlib/system/number.cs and Framework-era CoreCLR
release/1.0.0/src/classlibnative/bcltype/number.cpp (ParseFormatSpecifier,
RoundNumber, FindSection, NumberToStringFormat). The modern runtime's larger
precision limit and midpoint-to-even formatting are deliberately not used.
"""

from dataclasses import dataclass


class NumericFormatError(ValueError):
    """The Framework equivalent is FormatException, not Unsupported."""


@dataclass(frozen=True)
class NumberFormat:
    negative_sign: str = '-'
    positive_sign: str = '+'
    decimal_separator: str = '.'
    group_separator: str = ','
    group_sizes: tuple = (3,)
    number_digits: int = 2
    number_negative_pattern: int = 1
    currency_symbol: str = '¥'
    currency_digits: int = 0
    currency_decimal_separator: str = '.'
    currency_group_separator: str = ','
    currency_group_sizes: tuple = (3,)
    currency_positive_pattern: int = 0
    currency_negative_pattern: int = 1
    percent_symbol: str = '%'
    permille_symbol: str = '‰'
    percent_digits: int = 2
    percent_decimal_separator: str = '.'
    percent_group_separator: str = ','
    percent_group_sizes: tuple = (3,)
    percent_positive_pattern: int = 1
    percent_negative_pattern: int = 1


JAPANESE = NumberFormat()


def _standard_spec(spec):
    # The old parser accepts leading zeroes, but stops as soon as precision
    # reaches two significant digits. D100 is consequently a custom format.
    if not spec:
        return 'G', -1
    ch = spec[0]
    if not ('A' <= ch <= 'Z' or 'a' <= ch <= 'z'):
        return None
    index, precision = 1, -1
    if index < len(spec) and '0' <= spec[index] <= '9':
        precision = int(spec[index])
        index += 1
        while index < len(spec) and '0' <= spec[index] <= '9':
            precision = precision * 10 + int(spec[index])
            index += 1
            if precision >= 10:
                break
    return (ch, precision) if index == len(spec) else None


def _round(digits, scale, position):
    """Round a decimal digit buffer away from zero, then remove zeroes."""
    if position < 0:
        return '', 0
    if position < len(digits):
        kept = digits[:position]
        if digits[position] >= '5':
            increased = str(int(kept or '0') + 1)
            if len(increased) > position:
                scale += 1
            kept = increased
        digits = kept
    digits = digits.rstrip('0')
    return (digits, scale) if digits else ('', 0)


def _group_positions(count, sizes):
    positions = set()
    if not sizes:
        return positions
    index, size = 0, sizes[0]
    total = size
    while size and count > total:
        positions.add(total)
        if index < len(sizes) - 1:
            index += 1
            size = sizes[index]
        total += size
    return positions


def _group(text, separator, sizes):
    positions = _group_positions(len(text), sizes)
    return ''.join(
        ch + (separator if len(text) - index - 1 in positions else '')
        for index, ch in enumerate(text)
    )


def _exponent(value, letter, minimum, positive, culture):
    sign = (
        culture.negative_sign
        if value < 0
        else culture.positive_sign if positive else ''
    )
    return letter + sign + str(abs(value)).zfill(minimum)


def _pattern(pattern, text, culture):
    replacements = {
        '#': text,
        '-': culture.negative_sign,
        '$': culture.currency_symbol,
        '%': culture.percent_symbol,
    }
    return ''.join(replacements.get(ch, ch) for ch in pattern)


def _standard(value, letter, precision, culture):
    kind = letter.upper()
    sign = culture.negative_sign if value < 0 else ''
    magnitude = abs(value)
    if kind in ('D', 'X'):
        text = (
            str(magnitude) if kind == 'D' else format(value & ((1 << 64) - 1), letter)
        )
        return (sign if kind == 'D' else '') + text.zfill(max(0, precision))
    if kind == 'G' and precision <= 0:
        return sign + str(magnitude)
    if kind in ('E', 'G'):
        precision = (6 if kind == 'E' else 19) if precision < 0 else precision
        significant = precision + 1 if kind == 'E' else max(1, precision)
        digits, scale = _round(
            str(magnitude) if magnitude else '',
            len(str(magnitude)) if magnitude else 0,
            significant,
        )
        if kind == 'E':
            mantissa = (digits or '0').ljust(significant, '0')
            text = mantissa[0]
            if precision:
                text += culture.decimal_separator + mantissa[1:]
            return (
                sign
                + text
                + _exponent(scale - 1 if digits else 0, letter, 3, True, culture)
            )
        if scale > significant:
            text = (digits or '0')[0]
            if len(digits) > 1:
                text += culture.decimal_separator + digits[1:]
            return (
                sign
                + text
                + _exponent(scale - 1, 'E' if letter == 'G' else 'e', 2, True, culture)
            )
        return sign + (digits.ljust(scale, '0') if digits else '0')
    if kind not in ('F', 'N', 'C', 'P'):
        raise NumericFormatError('Invalid numeric format specifier')
    if kind == 'C':
        default, decimal, group, sizes = (
            culture.currency_digits,
            culture.currency_decimal_separator,
            culture.currency_group_separator,
            culture.currency_group_sizes,
        )
    elif kind == 'P':
        default, decimal, group, sizes = (
            culture.percent_digits,
            culture.percent_decimal_separator,
            culture.percent_group_separator,
            culture.percent_group_sizes,
        )
        magnitude *= 100
    else:
        default, decimal, group, sizes = (
            culture.number_digits,
            culture.decimal_separator,
            culture.group_separator,
            culture.group_sizes,
        )
    places = default if precision < 0 else precision
    text = str(magnitude)
    if kind != 'F':
        text = _group(text, group, sizes)
    if places:
        text += decimal + '0' * places
    if kind == 'F':
        return sign + text
    if kind == 'N':
        pattern = (
            ('(#)', '-#', '- #', '#-', '# -')[culture.number_negative_pattern]
            if value < 0
            else '#'
        )
    elif kind == 'C':
        patterns = (
            '($#)',
            '-$#',
            '$-#',
            '$#-',
            '(#$)',
            '-#$',
            '#-$',
            '#$-',
            '-# $',
            '-$ #',
            '# $-',
            '$ #-',
            '$ -#',
            '#- $',
            '($ #)',
            '(# $)',
        )
        pattern = (
            patterns[culture.currency_negative_pattern]
            if value < 0
            else ('$#', '#$', '$ #', '# $')[culture.currency_positive_pattern]
        )
    else:
        patterns = (
            '-# %',
            '-#%',
            '-%#',
            '%-#',
            '%#-',
            '#-%',
            '#%-',
            '-% #',
            '# %-',
            '% #-',
            '% -#',
            '#- %',
        )
        pattern = (
            patterns[culture.percent_negative_pattern]
            if value < 0
            else ('# %', '#%', '%#', '% #')[culture.percent_positive_pattern]
        )
    return _pattern(pattern, text, culture)


def _sections(spec):
    """Tokenize quotes/escapes before splitting sections or counting digits."""
    sections = [[]]
    index = 0
    while index < len(spec):
        ch = spec[index]
        index += 1
        if ch in ('"', "'"):
            end = spec.find(ch, index)
            if end < 0:
                end = len(spec)
            sections[-1].append(('literal', spec[index:end]))
            index = min(end + 1, len(spec))
        elif ch == '\\':
            if index < len(spec):
                sections[-1].append(('literal', spec[index]))
                index += 1
            else:
                # FindSection distinguishes an empty section from a section
                # containing an escape that happens to emit no characters.
                sections[-1].append(('literal', ''))
        elif ch == ';':
            sections.append([])
        elif ch in ('E', 'e'):
            end = index
            exp_sign = ''
            if end < len(spec) and spec[end] in ('+', '-'):
                exp_sign = spec[end]
                end += 1
            start = end
            while end < len(spec) and spec[end] == '0':
                end += 1
            if end > start:
                sections[-1].append(('exponent', ch, exp_sign, end - start))
                index = end
            else:
                sections[-1].append(('literal', ch))
        elif ch in '#0.,%‰':
            sections[-1].append((ch,))
        else:
            sections[-1].append(('literal', ch))
    return sections


def _section_index(sections, value):
    wanted = 2 if value == 0 else 1 if value < 0 else 0
    return wanted if wanted < len(sections) and sections[wanted] else 0


def _custom(value, spec, culture):
    sections = _sections(spec)
    selected = _section_index(sections, value)
    digits = str(abs(value)) if value else ''
    scale = len(digits)
    negative = value < 0
    while True:
        tokens = sections[selected]
        count, decimal, first, last = 0, -1, None, 0
        comma_position, comma_count, grouping, scale_adjust, scientific = (
            -1,
            0,
            False,
            0,
            False,
        )
        for token in tokens:
            ch = token[0]
            if ch in ('#', '0'):
                if ch == '0':
                    if first is None:
                        first = count
                    last = count + 1
                count += 1
            elif ch == '.' and decimal < 0:
                decimal = count
            elif ch == ',' and count > 0 and decimal < 0:
                if comma_position == count:
                    comma_count += 1
                else:
                    grouping |= comma_position >= 0
                    comma_position, comma_count = count, 1
            elif ch == '%':
                scale_adjust += 2
            elif ch == '‰':
                scale_adjust += 3
            elif ch == 'exponent':
                scientific = True
        if decimal < 0:
            decimal = count
        if comma_position >= 0:
            if comma_position == decimal:
                scale_adjust -= comma_count * 3
            else:
                grouping = True
        if digits:
            scale += scale_adjust
            position = count if scientific else scale + count - decimal
            digits, scale = _round(digits, scale, position)
            if not digits:
                negative = False
                zero_section = _section_index(sections, 0)
                if zero_section != selected:
                    selected = zero_section
                    continue
        else:
            negative, scale = False, 0
        break
    first = decimal - first if first is not None and first < decimal else 0
    last = decimal - last if last > decimal else 0
    dig_position = decimal if scientific else max(scale, decimal)
    adjust = 0 if scientific else scale - decimal
    separators = (
        _group_positions(max(first, dig_position + min(adjust, 0)), culture.group_sizes)
        if grouping
        else set()
    )
    output = [culture.negative_sign] if negative and selected == 0 else []
    digit_index, decimal_written = 0, False

    def emit_digit(ch, position):
        output.append(ch)
        if position > 1 and position - 1 in separators:
            output.append(culture.group_separator)

    for token in tokens:
        ch = token[0]
        if adjust > 0 and ch in ('#', '0', '.'):
            while adjust > 0:
                emit_digit(
                    digits[digit_index] if digit_index < len(digits) else '0',
                    dig_position,
                )
                digit_index += digit_index < len(digits)
                dig_position -= 1
                adjust -= 1
        if ch in ('#', '0'):
            if adjust < 0:
                adjust += 1
                digit = '0' if dig_position <= first else ''
            elif digit_index < len(digits):
                digit = digits[digit_index]
                digit_index += 1
            else:
                digit = '0' if dig_position > last else ''
            if digit:
                emit_digit(digit, dig_position)
            dig_position -= 1
        elif ch == '.':
            if (
                dig_position == 0
                and not decimal_written
                and (last < 0 or decimal < count and digit_index < len(digits))
            ):
                output.append(culture.decimal_separator)
                decimal_written = True
        elif ch == '%':
            output.append(culture.percent_symbol)
        elif ch == '‰':
            output.append(culture.permille_symbol)
        elif ch == 'literal':
            output.append(token[1])
        elif ch == 'exponent':
            if scientific:
                output.append(
                    _exponent(
                        scale - decimal if digits else 0,
                        token[1],
                        min(10, token[3]),
                        token[2] == '+',
                        culture,
                    )
                )
                scientific = False
            else:
                output.append(token[1] + token[2] + '0' * token[3])
    return ''.join(output)


def format_int64(value, spec='', culture=JAPANESE):
    """Format an already validated Int64 using a separate NumberFormat profile."""
    # Framework treats an embedded NUL as the end of the format string.
    spec = spec.split('\0', 1)[0]
    standard = _standard_spec(spec)
    return (
        _standard(value, *standard, culture)
        if standard is not None
        else _custom(value, spec, culture)
    )
