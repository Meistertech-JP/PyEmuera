"""Statement result commits, separate from builtins value evaluation."""

import datetime
from . import builtins, state_commands
from .expr import parse
from .text import split_args


def save_numbers(vm, spec, arg):
    op = spec['name']
    console = vm.console
    # SP_GETINT restructuring precedes the mutable-variable check. Do not
    # evaluate discarded excess terms or a rejected destination expression.
    from .command_arguments import integer_destination
    from .load_arguments import StaticContext

    function = (
        vm.frames[-1].function
        if vm.frames
        else next(iter(vm.program.functions.values()))[0]
    )
    context = StaticContext(vm, function)
    context.runtime = True
    integer_destination(context, op, arg)
    parts = split_args(arg) if arg.strip() else []
    dest = vm.ref(parts[0]) if parts else vm.ref('RESULT')
    dest.set(builtins.call(vm, op, ()))
    return True


def execute(vm, spec, arg):
    name = spec['name']
    if name == 'CHKDATA':
        from .save_commands import execute as check_slot

        return check_slot(vm, spec, arg)
    if name in ('SAVENOS', 'PRINTCPERLINE'):
        return save_numbers(vm, spec, arg)
    if name == 'GETTIME':
        return state_commands.execute(vm, name, arg, vm.console, datetime)
    return evaluate_and_commit(vm, spec, arg)


def evaluate_and_commit(vm, spec, arg):
    """Parse nodes in order; builtins owns argument policy; commit only on success."""
    nodes = (
        [parse(vm.program.expand(x)) if x else ('missing',) for x in split_args(arg)]
        if arg
        else []
    )
    builtins.validate_call_arguments(vm, spec['name'], nodes)
    from .expression_arguments import restructure_runtime

    nodes = restructure_runtime(vm, nodes, spec['name'])
    value = builtins.call(vm, spec['name'], nodes)
    vm.set('RESULTS' if isinstance(value, str) else 'RESULT', value)
    return True
