"""Stable direct Python API. Command semantics live exclusively in family owners."""

import datetime
from .argument_counts import expect
from .plain_html import PlainHTML, html_plain
from .registry import COMMAND_SPECS
from .expr import integer
from .errors import EraError

DISPLAY_OPS = frozenset(n for n, s in COMMAND_SPECS.items() if s['family'] == 'display')


def _range(vm, ref, parts, startpos):
    start = (
        integer(vm.eval(parts[startpos]))
        if len(parts) > startpos and parts[startpos]
        else 0
    )
    end = (
        integer(vm.eval(parts[startpos + 1]))
        if len(parts) > startpos + 1 and parts[startpos + 1]
        else ref.size()
    )
    if not 0 <= start <= end <= ref.size():
        raise EraError('Array range outside bounds', code='E_INDEX')
    return start, end


def execute_command(vm, op, arg):
    """Retain direct-call policy and patchable clock; never reimplement a command."""
    from .direct_commands import execute

    return execute(vm, op, arg, datetime)
