"""ENCODETOUNI statement: FORM input and staged UTF-16 conversion before RESULT writes."""

from .errors import EraError


def execute(vm, spec, arg):
    op = spec['name']
    console = vm.console
    target = vm.format(arg)
    from .compat1824 import units, scalar_at

    count = len(units(target))
    result = vm.data.variables['RESULT']
    if count + 1 > result.dims[0]:
        raise EraError('RESULT too small', code='E_INDEX')
    # ScriptProc calls ConvertToUtf32 at every UTF-16 index before writing
    # RESULT. A low surrogate is invalid even after a valid leading pair.
    codes = [scalar_at(target, i) for i in range(count)]
    for i, v in enumerate([count] + codes):
        result.set((i,), v)
    return True
