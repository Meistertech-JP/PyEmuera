"""Array command family, isolated from console/save dispatch.

Source-reviewed fixes: CVARSET name indices, full VARSIZE dimension output,
SPLIT destination-token semantics/truncation, and reversed VARSET ranges.
"""

from .errors import EraError, Unsupported
from .expr import integer, parse
from .text import split_args


def _bulk_modules():
    """Bind bulk helpers at command time, after argument validation.

    Keep the two imports together and in source order. A direct-API caller can
    replace sys.modules or inject an import failure between calls; eager global
    binding would change that behavior and the failure precedence.
    """
    import itertools
    import math

    return itertools, math


def expect(args, lo, hi, name):
    if not lo <= len(args) <= hi:
        raise EraError(name + ' argument count', code='E_ARGUMENT')


def _range(vm, ref, parts, startpos):
    # Source evaluates end before start. Its reversed-range branch collapses
    # both endpoints to end (it does not perform the intended swap).
    end = (
        integer(vm.eval(parts[startpos + 1]))
        if len(parts) > startpos + 1 and parts[startpos + 1]
        else ref.size()
    )
    start = (
        integer(vm.eval(parts[startpos]))
        if len(parts) > startpos and parts[startpos]
        else 0
    )
    if start > end:
        start = end
    if not 0 <= start <= end <= ref.size():
        raise EraError('Array range outside bounds', code='E_INDEX')
    return start, end


def _set_variable(vm, arg):
    """Resolve destination, range (end first), then value before writing.

    Validation order and partial writes are part of the command contract.
    """
    op = 'VARSET'
    p = split_args(arg)
    expect(p, 1, 4, op)
    ref = vm.ref(p[0])
    var = ref.variable
    if var.readonly:
        raise EraError('VARSET read-only variable', code='E_READONLY')
    selected_range = _range(vm, ref, p, 2) if len(var.dims) == 1 else None
    value = vm.eval(p[1]) if len(p) > 1 and p[1] else '' if var.string else 0
    if isinstance(value, str) != var.string:
        raise EraError('VARSET value type mismatch', code='E_TYPE')
    if var.character:
        if len(var.dims) > 1 and len(p) > 2:
            raise Unsupported('VARSET range on multidimensional character arrays')
        if not var.dims:
            ref.set(value)
        else:
            start, end = selected_range if len(var.dims) == 1 else (0, 0)
            if len(var.dims) == 1:
                for i in range(start, end):
                    var.set((ref.key[0], i), value)
            else:
                itertools, math = _bulk_modules()

                if math.prod(var.dims) > 1_000_000:
                    raise EraError('Bulk assignment budget exceeded', code='E_LIMIT')
                for key in itertools.product(*(range(n) for n in var.dims)):
                    var.set((ref.key[0],) + key, value)
    elif len(var.dims) == 1:
        start, end = selected_range
        if start == 0 and end == var.dims[0] and value == var.default:
            var.values.clear()
        else:
            for i in range(start, end):
                var.set((i,), value)
    elif value == var.default:
        var.values.clear()
    else:
        itertools, math = _bulk_modules()

        if math.prod(var.dims) > 1_000_000:
            raise EraError('Bulk assignment budget exceeded', code='E_LIMIT')
        for key in itertools.product(*(range(n) for n in var.dims)):
            var.set(key, value)
    return True


def _set_character_range(vm, arg):
    """Resolve descriptor, index, character range, then value before writes.

    Validation order and partial writes are part of the command contract.
    """
    op = 'CVARSET'
    p = split_args(arg)
    expect(p, 2, 5, op)
    descriptor = vm.ref_node(
        parse(vm.program.expand(p[0])), allow_character_descriptor=True
    )
    var = descriptor.variable
    if not var.character or len(var.dims) > 1:
        raise Unsupported(
            'CVARSET supports character scalar/1D arrays as in the source setter'
        )
    if var.readonly:
        raise EraError('CVARSET read-only variable', code='E_READONLY')
    key = vm.eval(p[1])
    index = (
        vm.data.index_of(var.name, key)
        if isinstance(key, str) and var.dims
        else integer(key) if not isinstance(key, str) else 0
    )
    start = integer(vm.eval(p[3])) if len(p) > 3 and p[3] else 0
    end = integer(vm.eval(p[4])) if len(p) > 4 and p[4] else vm.data.character_count
    if (
        len(p) > 3 and p[3] and not 0 <= start < vm.data.character_count
    ) or not 0 <= end <= vm.data.character_count:
        raise EraError('Invalid character range', code='E_INDEX')
    if start > end:
        start = end
    value = vm.eval(p[2]) if len(p) > 2 and p[2] else '' if var.string else 0
    if isinstance(value, str) != var.string:
        raise EraError('CVARSET value type mismatch', code='E_TYPE')
    if var.dims and vm.data.character_count:
        var.validate((0, index))
    for i in range(start, end):
        var.set((i, index) if var.dims else (i,), value)
    return True


def _split_into_array(vm, arg):
    """Evaluate strings before destination; write count before pieces.

    Validation order and partial writes are part of the command contract.
    """
    op = 'SPLIT'
    p = split_args(arg)
    expect(p, 3, 4, op)
    value, delim = vm.eval(p[0]), vm.eval(p[1])
    node = parse(vm.program.expand(p[2]))
    if not isinstance(value, str) or not isinstance(delim, str) or node[0] != 'var':
        raise EraError(
            'SPLIT expects string, string, writable string array', code='E_TYPE'
        )
    var = vm.lookup(node[1])
    if not var.string or var.readonly or not var.dims:
        raise EraError('SPLIT destination must be writable string array', code='E_TYPE')
    count = vm.ref(p[3]) if len(p) > 3 else vm.ref('RESULT')
    if count.variable.string or count.variable.readonly:
        raise EraError('SPLIT count must be writable integer', code='E_TYPE')
    # String.Split(string[] { "" }, None) does not split into characters.
    pieces = value.split(delim) if delim else [value]
    keep = pieces[: var.dims[0]]
    # Source uses zero base indices independent of the destination syntax.
    prefix = (0,) * (len(var.dims) + (1 if var.character else 0) - 1)
    keys = [prefix + (i,) for i in range(len(keep))]
    for key in keys:
        var.validate(key)
    if var.character and vm.data.character_count == 0:
        raise EraError(
            'SPLIT character destination has no character', code='E_CHARACTER'
        )
    count.set(len(pieces))
    for key, value in zip(keys, keep):
        var.set(key, value)
    return True


def execute(vm, spec, arg):
    op = spec['name']
    if op == 'VARSET':
        return _set_variable(vm, arg)
    if op == 'CVARSET':
        return _set_character_range(vm, arg)
    if op == 'SWAP':
        p = split_args(arg)
        expect(p, 2, 2, op)
        a, b = map(vm.ref, p)
        av, bv = a.get(), b.get()
        if a.variable.string != b.variable.string:
            raise EraError('SWAP type mismatch', code='E_TYPE')
        if a.variable.readonly or b.variable.readonly:
            raise EraError('SWAP read-only', code='E_READONLY')
        a.set(bv)
        b.set(av)
        return True
    if op == 'VARSIZE':
        p = split_args(arg)
        expect(p, 1, 1, op)
        name = p[0].strip()
        name = vm.eval(name) if name.startswith('"') else name
        var = vm.lookup(name)
        for i, length in enumerate(var.dims or (1,)):
            vm.set('RESULT:' + str(i), length)
        return True
    if op == 'ARRAYCOPY':
        a = vm.args(arg)
        expect(a, 2, 2, op)
        if not all(isinstance(x, str) for x in a):
            raise EraError('ARRAYCOPY uses quoted variable names', code='E_TYPE')
        src, dst = [vm.lookup(x) for x in a]
        if src.character or dst.character:
            raise Unsupported('ARRAYCOPY character arrays')
        if src.string != dst.string or len(src.dims) != len(dst.dims):
            raise EraError('ARRAYCOPY rank/type mismatch', code='E_TYPE')
        if dst.readonly:
            raise EraError('ARRAYCOPY read-only destination', code='E_READONLY')
        # Only the intersection is overwritten; destination tail is preserved.
        # Bind product before accessing dims; a direct API can mutate the
        # module during dimension access. Keep import errors command-local.
        from itertools import product
        import math

        dims = tuple(min(x, y) for x, y in zip(src.dims, dst.dims))
        if math.prod(dims) > 1_000_000:
            raise EraError('ARRAYCOPY bulk limit', code='E_LIMIT')
        copied = [(key, src.get(key)) for key in product(*(range(n) for n in dims))]
        for key, value in copied:
            dst.set(key, value)
        return True
    if op in {'ARRAYSORT', 'ARRAYSHIFT', 'ARRAYREMOVE'}:
        p = split_args(arg)
        expect(p, 1 if op == 'ARRAYSORT' else 3, 4 if op != 'ARRAYSHIFT' else 5, op)
        ref = vm.ref(p[0])
        var = ref.variable
        if var.readonly:
            raise EraError('Array is read-only', code='E_READONLY')
        if len(var.dims) != 1 or var.character:
            raise Unsupported(op + ' on multidimensional/character arrays')
        if op == 'ARRAYSORT':
            order = p[1].strip().upper() if len(p) > 1 and p[1] else 'FORWARD'
            if order not in {'FORWARD', 'BACK'}:
                raise EraError('Sort order must be FORWARD or BACK', code='E_ARGUMENT')
            start = integer(vm.eval(p[2])) if len(p) > 2 and p[2] else 0
            count = (
                integer(vm.eval(p[3])) if len(p) > 3 and p[3] else var.dims[0] - start
            )
            end = start + count
            if not 0 <= start <= end <= var.dims[0]:
                raise EraError('Sort range', code='E_INDEX')
            if var.string:
                # The native command sorts a temporary string[] with the
                # current-culture comparer. BACK reverses comparator arguments,
                # rather than reversing an already sorted result. Stage every
                # comparison before the existing writeback/type checks below.
                from .arraysort1824 import framework_array_sort

                vals = framework_array_sort(
                    [var.get((i,)) for i in range(start, end)],
                    backward=order == 'BACK',
                )
            else:
                vals = sorted(
                    [var.get((i,)) for i in range(start, end)], reverse=order == 'BACK'
                )
        elif op == 'ARRAYSHIFT':
            offset = integer(vm.eval(p[1]))
            fill = vm.eval(p[2])
            start = integer(vm.eval(p[3])) if len(p) > 3 and p[3] else 0
            count = (
                integer(vm.eval(p[4])) if len(p) > 4 and p[4] else var.dims[0] - start
            )
            end = start + count
            if not 0 <= start <= end <= var.dims[0]:
                raise EraError('Shift range', code='E_INDEX')
            old = [var.get((i,)) for i in range(start, end)]
            vals = [
                old[i - offset] if 0 <= i - offset < count else fill
                for i in range(count)
            ]
        else:
            expect(p, 3, 3, op)
            start = integer(vm.eval(p[1]))
            count = integer(vm.eval(p[2]))
            end = var.dims[0]
            if not 0 <= start <= start + count <= end:
                raise EraError('Remove range', code='E_INDEX')
            vals = [var.get((i,)) for i in range(start + count, end)] + [
                var.default
            ] * count
        if any(isinstance(x, str) != var.string for x in vals):
            raise EraError('Array value type mismatch', code='E_TYPE')
        for i, v in enumerate(vals, start):
            var.set((i,), v)
        return True
    if op == 'SPLIT':
        return _split_into_array(vm, arg)
    return False
