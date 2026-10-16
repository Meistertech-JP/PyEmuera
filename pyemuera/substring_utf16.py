"""Emuera1824+v24 LangManager.GetSubStringLang (40-95).

Walk UTF-16 units, skip the unit crossing start, include the unit crossing end.
CP932 unencodable units use one replacement byte. Whole surrogate pair costs
TWO replacement bytes in archived Windows grids; not Python scalar encoding.
Other Windows best-fit/culture conditions remain independently pending.
"""

from .unicode_boundary import units, from_units


def unit_width(n):
    return len(chr(n).encode('cp932', errors='replace'))


def substring(text, start, length=-1):
    u = units(text)
    total = sum(unit_width(n) for n in u)
    if start >= total or length == 0:
        return ''
    if length < 0 or length > total:
        length = total
    if start <= 0 and length == total:
        return text
    i = 0
    if start > 0:
        consumed = 0
        while i < len(u):
            consumed += unit_width(u[i])
            i += 1
            if consumed >= start:
                break
        if i >= len(u):
            return ''
    out = []
    consumed = 0
    while i < len(u):
        out.append(u[i])
        consumed += unit_width(u[i])
        i += 1
        if consumed >= length:
            break
    return from_units(out)
