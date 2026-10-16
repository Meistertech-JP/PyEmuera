"""Bind declared command families to a closed table of Python handlers.

JSON selects a family, never an import path or callback. Runtime argument
diagnostics run before the handler; owners preserve their own evaluation order. DISPATCH is built once, with no per-game state captured.
"""

from . import (
    platform1824,
    array_commands,
    character_commands,
    parameter_updates,
    state_commands,
)
from .registry import COMMAND_SPECS
from .errors import Unsupported
from . import (
    printing,
    random1824,
    character_data,
    save_commands,
    input_commands,
    html1824,
)
from . import scalar_numeric, numeric_instructions, display_elements, display_commands
from . import runtime_effects, decimal_instruction, unicode_instruction, console_history
from . import shop_display, status_display, flow, expression_commands


def _character_operation(vm, spec, arg):
    """Pass RAW arguments to the sole roster owner, without pre-evaluation."""
    return character_commands.execute(vm, spec['name'], arg)


def _parameter_update(vm, spec, arg):
    """Keep loader diagnostics before the owner's ordered commits/notifications."""
    return parameter_updates.execute(vm, spec['name'], arg)


def _state_operation(vm, spec, arg):
    """RAW state operations; this family never owns clocks or frame controls."""
    return state_commands.execute(vm, spec['name'], arg, vm.console, None)


FAMILY_HANDLERS = {
    'state_operation': _state_operation,
    'character_operation': _character_operation,
    'parameter_update': _parameter_update,
    'scalar_numeric': scalar_numeric.execute,
    'display_element': display_elements.execute,
    'numeric_instruction': numeric_instructions.execute,
    'array': array_commands.execute,
    'html': html1824.execute,
    'platform': platform1824.execute,
    'source_unimplemented': platform1824.source_unimplemented,
    'input': input_commands.execute,
    'character': character_data.execute,
    'save': save_commands.execute,
    'random': random1824.execute,
    'print': printing.execute,
    'text_length': printing.text_length,
    'runtime_effect': runtime_effects.execute,
    'decimal_instruction': decimal_instruction.execute,
    'unicode_instruction': unicode_instruction.execute,
    'console_history': console_history.execute,
    'shop_display': shop_display.execute,
    'status_display': status_display.execute_spec,
    'train': flow.execute_train,
    'display': display_commands.execute,
    'expression': expression_commands.execute,
}
# Compile dispatch entries once, independent of each VM/game state.
DISPATCH = {
    name: (FAMILY_HANDLERS[spec['family']], {**spec, 'name': name})
    for name, spec in COMMAND_SPECS.items()
    if spec['family'] in FAMILY_HANDLERS
}


def execute(vm, name, arg):
    entry = DISPATCH.get(name)
    if entry is None:
        return False
    handler, spec = entry
    from .command_arguments import lazy

    lazy(vm, name, arg, spec)
    return handler(vm, spec, arg)


def describe_binding(name):
    """Report static binding and explicit direct-API policy without evaluating ERB."""
    spec = COMMAND_SPECS.get(name)
    if spec is None:
        return None
    from .direct_commands import describe

    entry = DISPATCH.get(name)
    handler = entry[0] if entry else None
    owner = (
        handler.__module__ + '.' + handler.__name__
        if handler
        else 'pyemuera.runtime.VM.execute'
    )
    if name in character_commands.COMMANDS:
        owner = 'pyemuera.character_commands.execute'
    elif name in {'UPCHECK', 'CUPCHECK'}:
        owner = 'pyemuera.parameter_updates.execute'
    elif spec['family'] == 'state_operation' or name == 'GETTIME':
        owner = 'pyemuera.state_commands.execute'
    elif name == 'CHKDATA':
        owner = 'pyemuera.save_commands.execute'
    return {
        'implementation_owner': owner,
        'family': spec['family'],
        'entrypoint': (
            handler.__module__ + '.' + handler.__name__
            if handler
            else 'pyemuera.runtime.VM.execute'
        ),
        'argument_validation': (
            'pyemuera.command_arguments.lazy' if handler else 'VM control instruction'
        ),
        'load_argument_handler': spec.get('load_argument_contract', {}).get('handler'),
        'adapter': False,
        'adapter_delegate': None,
        'direct_api_delegate': describe(name),
    }
