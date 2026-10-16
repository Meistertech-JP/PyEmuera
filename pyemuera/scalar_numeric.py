"""Scalar integer contracts selected by the bundled JSON registry.

Expressions receive values only after builtins has validated arguments and
evaluated every AST left-to-right. No reference, RAND, or expression is cached.
The caller owns conversion of host exceptions to the existing diagnostic.

Bit commands resolve/read the destination before evaluating bit arguments in
order, and commit exactly once after all bits succeed. An invalid later bit
must retain earlier expression side effects but never a partial destination.
"""

from .errors import EraError
from .expr import integer, i64
from .text import split_args

FUNCTION_NAMES = frozenset({'ABS', 'SIGN', 'MAX', 'MIN', 'LIMIT', 'INRANGE', 'GETBIT'})
COMMAND_NAMES = frozenset({'SETBIT', 'CLEARBIT', 'INVERTBIT'})


def function(name, a):
    if name == 'ABS':
        v = integer(a[0])
        if v == -(1 << 63):
            raise EraError('ABS Int64 overflow', code='E_ARITH')
        return abs(v)
    if name == 'SIGN':
        return (integer(a[0]) > 0) - (a[0] < 0)
    if name in ('MAX', 'MIN'):
        return (max if name == 'MAX' else min)(map(integer, a))
    if name == 'LIMIT':
        return max(integer(a[1]), min(integer(a[2]), integer(a[0])))
    if name == 'INRANGE':
        return int(integer(a[1]) <= integer(a[0]) <= integer(a[2]))
    if name == 'GETBIT':
        bit = integer(a[1])
        # Native Creator.Method.cs:1627 uses '第２' and '０～６３' literally.
        # Keep those widths and U+FF5E in the runtime CodeEE wording.
        if not 0 <= bit < 64:
            raise EraError(
                'GETBIT関数の第２引数(' + str(bit) + ')が範囲(０～６３)を超えています',
                code='E_INDEX',
            )
        return (integer(a[0]) >> bit) & 1
    raise EraError('Unknown scalar numeric function ' + name, code='E_SPEC')


def execute(vm, spec, arg):
    from .argument_counts import expect

    op = spec['name']
    if op not in COMMAND_NAMES:
        raise EraError('Unknown scalar numeric command ' + op, code='E_SPEC')
    p = split_args(arg)
    expect(p, 2, 65, op)
    ref = vm.ref(p[0])
    value = integer(ref.get())
    for expr in p[1:]:
        bit = integer(vm.eval(expr))
        if not 0 <= bit < 64:
            raise EraError('Bit index outside 0..63', code='E_INDEX')
        value = (
            value | (1 << bit)
            if op == 'SETBIT'
            else value & ~(1 << bit) if op == 'CLEARBIT' else value ^ (1 << bit)
        )
    ref.set(i64(value))
    return True
