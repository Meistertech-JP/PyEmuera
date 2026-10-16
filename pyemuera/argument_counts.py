"""Argument count validation only; this module never evaluates ERB terms.

Kept below both VM adapters and handlers so a handler need not import commands
(or runtime) merely to raise the existing E_ARGUMENT diagnostic.
"""

from .errors import EraError


def expect(parts, minimum, maximum=None, op='command'):
    maximum = minimum if maximum is None else maximum
    if not minimum <= len(parts) <= maximum:
        raise EraError(
            f'{op}: expected {minimum}..{maximum} arguments, got {len(parts)}',
            code='E_ARGUMENT',
        )
