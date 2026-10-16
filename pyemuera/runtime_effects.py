"""Non-frame runtime effects. Each handler owns evaluation before its effect."""

from .expr import integer
from .argument_counts import expect
from .errors import EraError


def output_log(vm, spec, arg):
    op = spec['name']
    console = vm.console
    from .outputlog import write

    write(vm)
    return True


def await_delay(vm, spec, arg):
    op = spec['name']
    console = vm.console
    # Keep command-time binding/import failure before expression evaluation.
    import time
    from .text import split_args

    parts = split_args(arg) if arg.strip() else []
    ms = integer(vm.eval(parts[0])) if parts else -1
    if parts and ms < 0:
        raise EraError(
            'AWAIT命令:負の値(' + str(ms) + ')が指定されました', code='E_ARGUMENT'
        )
    if ms > 10000:
        raise EraError(
            'AWAIT命令:10秒以上の待機時間(' + str(ms) + ' ms)が指定されました',
            code='E_ARGUMENT',
        )
    # RefreshStrings(true) precedes the delay even when omitted, zero, skipped,
    # or no-wait. Flush output without adding a logical newline.
    console.flush(force=True)
    console.output.flush()
    if not console.no_wait and ms > 0:
        time.sleep(ms / 1000)
    return True


def debug_clear(vm, spec, arg):
    op = spec['name']
    console = vm.console
    # Debug-window contents have no CLI transcript counterpart. In normal
    # mode DEBUG_FUNC never evaluates its raw argument.
    pass
    return True


HANDLERS = {'AWAIT': await_delay, 'OUTPUTLOG': output_log, 'DEBUGCLEAR': debug_clear}


def execute(vm, spec, arg):
    return HANDLERS[spec['name']](vm, spec, arg)
