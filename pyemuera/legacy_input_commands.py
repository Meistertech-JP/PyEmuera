"""Import compatibility only; input_commands owns both documented API policies."""

from .input_commands import execute_direct as execute

NAMES = frozenset(
    (
        'FORCEWAIT',
        'INPUT',
        'INPUTS',
        'ONEINPUT',
        'ONEINPUTS',
        'TINPUT',
        'TINPUTS',
        'TWAIT',
        'WAIT',
        'WAITANYKEY',
    )
)
