"""Expression method selection after the complete label dictionary is loaded.

IdentifierDictionary.GetFunctionMethod: #FUNCTION/#FUNCTIONS override a
SystemMethod; an ordinary label does not. Selection is per program and never
falls back after an execution/type/arity failure. Command dispatch stays separate.
"""

from .errors import EraError


def expression_user_method(functions, name):
    rows = functions.get(name)
    fn = rows[0] if rows else None
    return fn if fn is not None and fn.attributes & {'FUNCTION', 'FUNCTIONS'} else None


def resolve_expression_method(functions, name, builtins):
    fn = expression_user_method(functions, name)
    if fn is not None:
        return fn
    if name in builtins:
        if hasattr(builtins, 'items'):
            spec = builtins[name]
        else:
            from .registry import FUNCTION_SPECS

            spec = FUNCTION_SPECS.get(name)
        if spec is None or spec.get('native_registered', True):
            return None
    rows = functions.get(name)
    if not rows:
        from .registry import COMMAND_SPECS

        if name in COMMAND_SPECS and COMMAND_SPECS[name].get('native_registered', True):
            raise EraError(
                '命令名\"' + name + '\"が関数のように使われています', code='E_FUNCTION'
            )
    if rows:
        raise EraError('@' + name + ' is not #FUNCTION/#FUNCTIONS', code='E_FUNCTION')
    raise EraError(f'Unknown function @{name}', code='E_FUNCTION')


def parameter_type(vm, fn, node):
    # Callee signature metadata, without copying the entire global type map or
    # scanning every method once per call. No default/index value evaluation.
    if node[0] != 'var':
        return None
    name = node[1]
    for declaration in vm.declarations[fn.uid]:
        if declaration.name == name:
            return 'string' if declaration.string else 'Int64'
    value = vm.legacy[fn.name].get(name) or vm.data.variables.get(name)
    return ('string' if value.string else 'Int64') if value is not None else None
