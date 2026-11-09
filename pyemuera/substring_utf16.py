"""Emuera1824+v24 LangManager.GetSubStringLang (40-95).

Walk UTF-16 units, skip the unit crossing start, include the unit crossing end.
CP932 unencodable units use one replacement byte. Whole surrogate pair costs
TWO replacement bytes in archived Windows grids; not Python scalar encoding.
Other Windows best-fit/culture conditions remain independently pending.
"""

from .unicode_boundary import units, from_units
from functools import lru_cache


def unit_width(n):
    return len(chr(n).encode('cp932', errors='replace'))


@lru_cache(maxsize=65536)
def _cached_unit_width(n):
    # Only called with integer UTF-16 units from units(), never caller values.
    # CP932 width is immutable and independent of VM, locale and live state.
    # Cache no text/indices/results; retain at most the 65,536 unit values.
    return unit_width(n)


def _measure(text):
    u = tuple(units(text))
    widths = tuple(_cached_unit_width(n) for n in u)
    return u, widths, sum(widths)


@lru_cache(maxsize=256)
def _short_text_measure(text):
    # Bounded immutable source measurements, never sliced results or positions.
    # The caller's size guard also bounds retained text and measurement arrays.
    return _measure(text)


def substring(text, start, length=-1):
    u, widths, total = (_short_text_measure(text) if type(text) is str and len(text) <= 2048
                        else _measure(text))
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
            consumed += widths[i]
            i += 1
            if consumed >= start:
                break
        if i >= len(u):
            return ''
    out = []
    consumed = 0
    while i < len(u):
        out.append(u[i])
        consumed += widths[i]
        i += 1
        if consumed >= length:
            break
    return from_units(out)
