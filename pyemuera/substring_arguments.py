"""Substring-only optional values; callers already evaluated each term once.

Creator.Method.cs casts the two Int64 indices to unchecked Int32. Missing
slots default to 0/-1; explicit zero and empty text are never truth-tested.
Character units remain owned by legacy_substring and the UTF-16 handler.
"""

from .expr import integer


def optional_index(values, index, default):
    value = values[index] if index < len(values) else None
    if value is None:
        return default
    return ((integer(value) + (1 << 31)) % (1 << 32)) - (1 << 31)
