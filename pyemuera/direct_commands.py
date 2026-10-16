"""Closed direct-Python compatibility bindings; contains no command semantics.

Normal VM never enters here. Historical direct-only input/HTML validation is
owned by the corresponding family. Unsupported VM controls still return False.
"""

from . import (
    array_commands,
    scalar_numeric,
    character_commands,
    state_commands,
    parameter_updates,
    display_commands,
    save_commands,
    input_commands,
    html1824,
    expression_commands,
    runtime_effects,
    decimal_instruction,
    unicode_instruction,
    console_history,
    status_display,
    shop_display,
    flow,
)
from .registry import COMMAND_SPECS

DIRECT_INPUT = frozenset(
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
SAVE_NAMES = frozenset(
    (
        'SAVEDATA',
        'LOADDATA',
        'CHKDATA',
        'SAVEGLOBAL',
        'LOADGLOBAL',
        'SAVEGAME',
        'LOADGAME',
    )
)
OWNERS = {
    'array': array_commands.execute,
    'scalar_numeric': scalar_numeric.execute,
    'display': display_commands.execute,
    'runtime_effect': runtime_effects.execute,
    'decimal_instruction': decimal_instruction.execute,
    'unicode_instruction': unicode_instruction.execute,
    'console_history': console_history.execute,
    'status_display': status_display.execute_spec,
    'shop_display': shop_display.execute,
    'train': flow.execute_train,
}


def describe(name):
    if name in DIRECT_INPUT:
        return 'pyemuera.input_commands.execute_direct'
    if name in state_commands.NAMES:
        return 'pyemuera.state_commands.execute'
    if name in character_commands.COMMANDS:
        return 'pyemuera.character_commands.execute'
    if name in {'UPCHECK', 'CUPCHECK'}:
        return 'pyemuera.parameter_updates.execute'
    if name in SAVE_NAMES:
        return 'pyemuera.save_commands.execute'
    if name == 'HTML_PRINT':
        return 'pyemuera.html1824.execute_direct'
    spec = COMMAND_SPECS.get(name, {})
    handler = OWNERS.get(spec.get('family'))
    if handler:
        return handler.__module__ + '.' + handler.__name__
    from .builtins import NAMES

    if name in NAMES:
        return 'pyemuera.expression_commands.execute'
    return None


def execute(vm, name, arg, clock_module):
    """Select a unique semantic owner. Deliberately do not call lazy validation."""
    console = vm.console
    spec = {**COMMAND_SPECS.get(name, {}), 'name': name}
    if name in DIRECT_INPUT:
        return input_commands.execute_direct(vm, name, arg, console)
    if name in state_commands.NAMES:
        return state_commands.execute(vm, name, arg, console, clock_module)
    if name in character_commands.COMMANDS:
        return character_commands.execute(vm, name, arg)
    if name in {'UPCHECK', 'CUPCHECK'}:
        return parameter_updates.execute(vm, name, arg)
    if name in SAVE_NAMES:
        return save_commands.execute(vm, spec, arg)
    if name == 'HTML_PRINT':
        return html1824.execute_direct(vm, spec, arg)
    handler = OWNERS.get(spec.get('family'))
    if handler:
        return handler(vm, spec, arg)
    from .builtins import NAMES

    if name in NAMES:
        return expression_commands.execute(vm, spec, arg)
    return False
