"""Convert already-evaluated values to text without owning AST evaluation.

The callers retain argument validation, left-to-right evaluation, RESULT writes
and Python exception translation. Numeric formats follow Int64.ToString and
width policy belongs to width1824; these handlers do not evaluate FORM
text, read clocks, normalize arbitrary Unicode or modify script state.
"""

from __future__ import annotations

from .errors import EraError, Unsupported
from .expr import integer


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise EraError('String required', code='E_TYPE')
    return value


def _integer_text(values: list, name: str = 'TOSTR') -> str:
    """Validate values, then translate only Framework FormatException."""
    value = integer(values[0])
    if len(values) < 2 or values[1] is None or values[1] == '':
        return str(value)
    spec = _string(values[1])
    from .numeric_format import format_int64, NumericFormatError

    try:
        return format_int64(value, spec)
    except NumericFormatError as exc:
        message = (
            'MONEYSTR関数の第2引数の書式指定が間違っています'
            if name == 'MONEYSTR'
            else 'TOSTR関数の書式指定が間違っています'
        )
        raise EraError(message, code='E_ARGUMENT') from exc


def function(vm, name: str, values: list) -> str:
    """Dispatch only the owned conversion names, preserving lookup order.

    Case changes need no VM state. Width conversion validates its string before
    accessing program.config and retains width1824's empty-string early return,
    Japanese locale policy and explicit unsupported-character diagnostics.
    """
    if name == 'TOSTR':
        return _integer_text(values)
    if name == 'TOUPPER':
        return _string(values[0]).upper()
    if name == 'TOLOWER':
        return _string(values[0]).lower()
    if name in {'TOHALF', 'TOFULL'}:
        from .width1824 import convert

        return convert(_string(values[0]), name == 'TOFULL', vm.program.config)
    raise Unsupported('String conversion expression function ' + name)
