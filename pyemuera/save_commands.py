"""Script save commands, separate from codecs and interactive save menus.

Arguments are evaluated once in source order before count/type checks. The
store owns serialization and original-file protection. These adapters own
RESULT/RESULTS and the LOADDATAEND control transfer, not the save format.
"""

from .errors import EraError, Unsupported, FlowSignal
from .expr import integer


def _expect(values, minimum, maximum, name):
    if not minimum <= len(values) <= maximum:
        raise EraError(
            f'{name}: expected {minimum}..{maximum} arguments, got {len(values)}',
            code='E_ARGUMENT',
        )


def _global(vm, name, arg):
    """A global load error becomes a warning and RESULT=0, not a transfer."""
    _expect(vm.args(arg), 0, 0, name)
    if name == 'SAVEGLOBAL':
        vm.saves.write('global')
        vm.set('RESULT', 1)
        return
    try:
        loaded = vm.saves.load('global')
    except EraError as exc:
        vm.console.warning('global-load', str(exc))
        loaded = 0
    vm.set('RESULT', int(loaded))


def _slot(vm, name, arg):
    """CHKDATA only reports; a successful LOADDATA transfers to LOADDATAEND.

    A failed load sets RESULT=0. A successful load raises FlowSignal immediately
    after restoration, leaving RESULT as restored by the store. Store exceptions
    propagate; this differs deliberately from LOADGLOBAL's warning policy.
    """
    values = vm.args(arg)
    _expect(values, 1, 2 if name == 'SAVEDATA' else 1, name)
    slot = integer(values[0])
    if name == 'SAVEDATA':
        description = values[1] if len(values) > 1 else ''
        if not isinstance(description, str):
            raise EraError('Save description must be string', code='E_TYPE')
        vm.saves.write(slot, description)
        vm.set('RESULT', 1)
    elif name == 'CHKDATA':
        status, message = vm.saves.check(slot)
        vm.set('RESULT', status)
        vm.set('RESULTS', message)
    elif vm.saves.load(slot):
        raise FlowSignal('LOADDATAEND')
    else:
        vm.set('RESULT', 0)


def execute(vm, spec, arg):
    """Execute a declared save operation, retaining the historical direct-API fallback.

    CHKDATA remains callable through the direct entry point; its JSON binding
    stays unchanged. DELDATA only deletes store overlays, never original saves.
    Interactive SAVEGAME/LOADGAME retain their raw-argument rejection policy.
    Non-save calls through this historical adapter still reach the direct
    binding table. The dispatcher only sends the declared save family here.
    """
    name = spec['name']
    if name == 'DELDATA':
        values = vm.args(arg)
        if len(values) != 1:
            raise EraError('DELDATA requires one slot', code='E_ARGUMENT')
        slot = integer(values[0])
        vm.saves.delete(slot)
    elif name in {'SAVEGLOBAL', 'LOADGLOBAL'}:
        _global(vm, name, arg)
    elif name in {'SAVEDATA', 'LOADDATA', 'CHKDATA'}:
        _slot(vm, name, arg)
    elif name in {'SAVEGAME', 'LOADGAME'}:
        from .save_menu import run_save_menu

        if arg:
            raise Unsupported(name + ' arguments')
        run_save_menu(vm, saving=name == 'SAVEGAME')
    else:
        # The historical direct-API fallback receives the clock module bound
        # at this call, including replacement and import-failure semantics.
        import datetime
        from .direct_commands import execute as execute_direct

        return execute_direct(vm, name, arg, datetime)
    return True
