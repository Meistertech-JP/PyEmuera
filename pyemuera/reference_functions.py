"""Array expressions after argument evaluation and reference resolution.

The caller resolves the first AST as a Ref before evaluating remaining terms.
This module consumes those values; it never evaluates an expression, resolves a
new reference, writes a variable, or consumes RNG. Bounds/type checks precede
array reads in the same order as the former builtins.call implementation.
"""

from .errors import EraError, Unsupported
from .expr import integer, i64


CHARACTER_FUNCTIONS = frozenset(
    {
        'SUMCARRAY',
        'MAXCARRAY',
        'MINCARRAY',
        'CMATCH',
        'INRANGECARRAY',
        'FINDCHARA',
        'FINDLASTCHARA',
    }
)
MATCH_FUNCTIONS = frozenset(
    {
        'MATCH',
        'CMATCH',
        'FINDELEMENT',
        'FINDLASTELEMENT',
        'FINDCHARA',
        'FINDLASTCHARA',
    }
)
RANGE_FUNCTIONS = frozenset({'INRANGEARRAY', 'INRANGECARRAY'})


def _join(ref, variable, values):
    """Join a last-axis slice; the fourth argument is a count, not an end."""
    delimiter = values[1] if len(values) > 1 and values[1] is not None else ','
    if not isinstance(delimiter, str):
        raise EraError('String required', code='E_TYPE')
    start = integer(values[2]) if len(values) > 2 and values[2] is not None else 0
    count = (
        integer(values[3])
        if len(values) > 3 and values[3] is not None
        else ref.size() - start
    )
    end = start + count
    if not 0 <= start <= end <= ref.size():
        raise EraError('STRJOIN range', code='E_INDEX')
    return delimiter.join(
        str(variable.get(ref.key[:-1] + (index,))) for index in range(start, end)
    )


def function(vm, name, values):
    """Read an ordinary last axis or a character axis from an existing Ref.

    Returns an Int64-compatible aggregate/index/count or a joined string.
    Raises the existing EraError/Unsupported diagnostics without translating
    Python exceptions: builtins owns that translation boundary. Empty ranges
    are accepted for sums/counts/joins, but min/max require a value.
    """
    ref = values[0]
    variable = ref.variable
    character_axis = name in CHARACTER_FUNCTIONS
    matching = name in MATCH_FUNCTIONS
    in_range = name in RANGE_FUNCTIONS
    if name == 'STRJOIN':
        return _join(ref, variable, values)

    offset = 3 if in_range else 2 if matching else 1
    size = vm.data.character_count if character_axis else ref.size()
    start = (
        integer(values[offset])
        if len(values) > offset and values[offset] is not None
        else 0
    )
    end = (
        integer(values[offset + 1])
        if len(values) > offset + 1 and values[offset + 1] is not None
        else size
    )
    if not 0 <= start <= end <= size:
        raise EraError(f'{name}: invalid range {start}:{end}', code='E_INDEX')
    if character_axis and not variable.character:
        raise EraError('Character variable required', code='E_TYPE')
    if character_axis and start >= size:
        raise EraError(
            name + ': start must select an existing character', code='E_CHARACTER'
        )
    if matching and variable.string != isinstance(values[1], str):
        raise EraError(name + ': target type differs from array type', code='E_TYPE')
    if name in ('MATCH', 'CMATCH') and len(variable.dims) > 1:
        raise Unsupported(name + ' multidimensional matching')
    if not matching and variable.string:
        raise EraError(name + ': numeric array required', code='E_TYPE')
    if in_range:
        integer(values[1])
        integer(values[2])

    # Materialize once before reducing. Do not short-circuit matching or make
    # these reads lazy: doing so would change the observable read/error order.
    items = [
        (
            index,
            variable.get(
                (index,) + ref.key[1:] if character_axis else ref.key[:-1] + (index,)
            ),
        )
        for index in range(start, end)
    ]
    if matching:
        hits = [index for index, value in items if value == values[1]]
        if name in ('MATCH', 'CMATCH'):
            return len(hits)
        if not hits:
            return -1
        return hits[-1] if 'LAST' in name else hits[0]
    if in_range:
        return sum(values[1] <= value <= values[2] for _, value in items)

    elements = [value for _, value in items]
    if name.startswith('SUM'):
        return i64(sum(elements))
    if not elements:
        raise EraError('Empty array range', code='E_ARGUMENT')
    return (max if name.startswith('MAX') else min)(elements)
