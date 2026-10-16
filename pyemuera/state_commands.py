"""State writes, with explicit sequential failure contracts.

The caller supplies its captured Console and live datetime module. Entry-time
argument evaluation stays here; pure value queries remain separate. Display/RNG
flags and prior variable writes are not rolled back on a later failure.
"""

from .expr import integer
from .argument_counts import expect
from .errors import EraError, Unsupported
from .text import split_args

NAMES = frozenset(
    (
        'ENDNOSKIP',
        'GETTIME',
        'NOSKIP',
        'PUTFORM',
        'RANDOMIZE',
        'RESETDATA',
        'RESETGLOBAL',
        'RESET_STAIN',
        'SKIPDISP',
    )
)


def execute(vm, op, arg, console, clock_module):
    """Evaluate, validate and mutate in each original command's order.

    SKIPDISP writes flags before RESULT; GETTIME reads each component separately
    then writes RESULT before sampling RESULTS. VOID arguments are discarded.
    NOSKIP stores the previous flag in the active frame; ENDNOSKIP restores it.
    The helper does not own VM frame unwinding or runtime argument diagnostics.
    """
    if op == 'RESET_STAIN':
        a = vm.args(arg)
        expect(a, 1, 1, op)
        vm.data.reset_stain(integer(a[0]))
        return True
    if op == 'SKIPDISP':
        a = vm.args(arg)
        expect(a, 1, 1, op)
        console.skip_print = console.user_skip = integer(a[0]) != 0
        # Reference source sets RESULT to the flag; some older prose documents say 0.
        vm.set('RESULT', int(console.skip_print))
        return True
    if op in {'NOSKIP', 'ENDNOSKIP'}:
        marks = vm.frames[-1].skip_marks
        if op == 'NOSKIP':
            marks.append(console.skip_print)
            console.skip_print = False
        else:
            if not marks:
                raise EraError('ENDNOSKIP reached without active NOSKIP', code='E_FLOW')
            console.skip_print = marks.pop()
        return True
    if op in {'RESETDATA', 'RESETGLOBAL'}:
        vm.reset(op == 'RESETGLOBAL')
        return True
    if op == 'GETTIME':
        from .runtime_queries import numeric_time

        vm.set('RESULT', numeric_time(clock_module))
        vm.set('RESULTS', clock_module.datetime.now().strftime('%Y/%m/%d %H:%M:%S'))
        return True
    if op == 'RANDOMIZE':
        a = vm.args(arg)
        expect(a, 1, 1, op)
        vm.rng.seed(integer(a[0]))
        return True
    if op == 'PUTFORM':
        vm.set('SAVEDATA_TEXT', vm.get('SAVEDATA_TEXT') + vm.format(arg))
        return True
    return False
