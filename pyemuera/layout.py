"""Terminal projection, separate from ERB string values and CP932 offsets.

The logical layout is a CP932 half-cell grid. Modern terminals often draw the
JIS box-drawing characters in one cell, while U+3000 occupies two. Merely
preserving the original string does not preserve that grid. This projection
reserves the intended cells at output time only. Never feed it back into a VM
variable, an expression, or a native save.
"""

from functools import lru_cache
import unicodedata

# A narrow box glyph is anchored at the left half-cell. Extend its right arm
# across the reserved second cell, instead of inserting gaps in horizontal lines.
_RIGHT_LIGHT = set('─┌└├┬┴┼╭╰')
_RIGHT_HEAVY = set('━┏┗┣┳┻╋')
_RIGHT_DOUBLE = set('═╔╚╠╦╩╬')


@lru_cache(maxsize=8192)
def cell_width(char, ambiguous=1):
    if unicodedata.combining(char) or unicodedata.category(char) in ('Mn', 'Me', 'Cf'):
        return 0
    eaw = unicodedata.east_asian_width(char)
    return 2 if eaw in ('W', 'F') else ambiguous if eaw == 'A' else 1


@lru_cache(maxsize=8192)
def _small_terminal_width(text, ambiguous=1):
    return sum(cell_width(c, ambiguous) for c in text)


def terminal_width(text, ambiguous=1):
    if len(text) <= 512:
        return _small_terminal_width(text, ambiguous)
    return sum(cell_width(c, ambiguous) for c in text)


@lru_cache(maxsize=8192)
def project_char(char, ambiguous=1):
    if char in '\n\t':
        return char
    # Inexpressible Unicode (e.g. game bar blocks, emoji) is kept as Unicode;
    # this adapter promises the CP932-layout invariant for CP932 characters.
    try:
        target = len(char.encode('cp932'))
    except UnicodeEncodeError:
        return char
    current = cell_width(char, ambiguous)
    if target <= current:
        return char
    extra = target - current
    if current == 1 and extra == 1:
        if char in _RIGHT_LIGHT:
            return char + '─'
        if char in _RIGHT_HEAVY:
            return char + '━'
        if char in _RIGHT_DOUBLE:
            return char + '═'
    return char + ' ' * extra


_LEFT_LIGHT = set('─┐┘┤┬┴┼╮╯')
_LEFT_HEAVY = set('━┓┛┫┳┻╋')
_LEFT_DOUBLE = set('═╗╝╣╦╩╬')
_VERTICAL = set('│┃║┐┘┓┛╗╝┤┫╣')


@lru_cache(maxsize=8192)
def projected_cell(char, next_char='', ambiguous=1):
    result = project_char(char, ambiguous)
    # The right side of a room abuts a corridor. Continue that corridor across
    # the reserved half-cell instead of inserting a visible break in the line.
    if char in _VERTICAL and result == char + ' ':
        if next_char in _LEFT_LIGHT:
            return char + '─'
        if next_char in _LEFT_HEAVY:
            return char + '━'
        if next_char in _LEFT_DOUBLE:
            return char + '═'
    return result


def project(text, ambiguous=1):
    return ''.join(
        projected_cell(c, text[i + 1] if i + 1 < len(text) else '', ambiguous)
        for i, c in enumerate(text)
    )


def project_rule(text, width, *, layout='terminal', ambiguous=1, alignment='LEFT'):
    """Fit a command-generated rule to one physical row, never ERB history.

    Width is a cell budget with the backend's final-column reserve already
    removed. Budget ambiguous glyphs at two cells: a host may be wider than the
    requested projection (notably classic conhost). Do not change general PRINT
    projection, repeat the rule, or alter the GETLINESTR result. A narrow host
    may leave spare cells; safety is preferable to inventing font measurements.
    """
    width = max(0, int(width))
    used = 0
    out = []
    rendered = project(text, ambiguous) if layout == 'terminal' else text
    for glyph in rendered:
        if glyph == '\t':
            glyph = ' ' * (8 - used % 8)
        size = terminal_width(glyph, 2)
        if used + size > width:
            break
        out.append(glyph)
        used += size
    pad = max(0, width - used) if alignment in ('CENTER', 'RIGHT') else 0
    if alignment == 'CENTER':
        pad //= 2
    return ' ' * pad + ''.join(out), used + pad
