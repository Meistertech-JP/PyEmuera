"""Select load-analysis labels without invoking expressions or game callbacks.

Selection is conservative for dynamic calls. Static reference scans inspect
syntax only; argument/type/reduction diagnostics belong to load_arguments.
The no-system-entry fallback is an existing embedding adaptation.
"""

from collections import deque
from importlib.resources import files
import json
import re

from .errors import EraError
from .expr import tokenize
from .program import command
from .registry import command_spec
from .text import split_args


def _system_roots(ordered, policy):
    return [
        function
        for function in ordered
        if function.name in policy['system_labels']
        or any(
            re.fullmatch(pattern, function.name)
            for pattern in policy['system_patterns']
        )
    ]


def method_roots(program):
    """Use valid method traits; native ignores method directives on system labels.

    Attribute diagnostics remain in the existing loader. This narrow exclusion
    avoids turning such an ignored directive into a new method-context error.
    """
    policy = json.loads(
        files('pyemuera')
        .joinpath('specs/load_roots_v24.json')
        .read_text(encoding='utf-8')
    )
    ordered = [function for group in program.functions.values() for function in group]
    system_uids = {function.uid for function in _system_roots(ordered, policy)}
    return [
        function
        for function in ordered
        if function.uid not in system_uids
        and function.attributes & {'FUNCTION', 'FUNCTIONS'}
    ]


def _expression_references(program, expression, tolerate_error=True):
    try:
        tokens = tokenize(expression)
    except EraError:
        if not tolerate_error:
            raise
        return []
    return [
        left.value
        for left, right in zip(tokens, tokens[1:])
        if left.kind == 'ID' and right.kind == '(' and left.value in program.functions
    ]


def constant_resolver(program, function):
    """Only immutable loaded descriptors; never VM.eval or dynamic references."""
    constants = getattr(program, 'load_constants', {}).get(function.uid, {})

    def resolve(node):
        name, indices = node[1:]
        if name in {'__INT_MAX__', '__INT_MIN__'} and not indices:
            return ('lit', (1 << 63) - 1 if name == '__INT_MAX__' else -(1 << 63))
        variable = constants.get(name)
        if variable is None or not all(
            child[0] == 'lit' and isinstance(child[1], int) for child in indices
        ):
            return None
        key = tuple(child[1] for child in indices)
        key += (0,) * (len(variable.dims) - len(key))
        return ('lit', variable.get(key))

    def special(node, reducer):
        name, arguments = node[1:]
        if name == 'GETNUM' and len(arguments) == 2 and arguments[0][0] == 'var':
            key = reducer.reduce(arguments[1])
            descriptors = getattr(program, 'load_descriptors', {}).get(function.uid, {})
            if (
                arguments[0][1] in descriptors
                and key[0] == 'lit'
                and isinstance(key[1], str)
            ):
                try:
                    value = program.load_keyword_number(arguments[0][1], key[1])
                except EraError:
                    value = -1  # Constant.TryKeywordToInteger false.
                return ('lit', value)
            return None
        if name == 'VARSIZE' and 1 <= len(arguments) <= 2:
            args = tuple(reducer.reduce(child) for child in arguments)
            if all(child[0] == 'lit' for child in args) and isinstance(args[0][1], str):
                variable = (
                    getattr(program, 'load_descriptors', {})
                    .get(function.uid, {})
                    .get(args[0][1].upper())
                )
                if variable is not None and hasattr(variable, 'dims'):
                    index = args[1][1] if len(args) == 2 else 0
                    if isinstance(index, int) and 0 <= index < len(variable.dims):
                        return ('lit', variable.dims[index])
            return None
        if name == 'STRFORM' and len(arguments) == 1:
            value = reducer.reduce(arguments[0])
            if value[0] != 'lit' or not isinstance(value[1], str):
                return None
            from .call_syntax import constant_form_name

            text = constant_form_name(
                value[1],
                program.functions,
                resolve,
                getattr(program, 'load_form_methods', None),
                trim_edges=False,
            )
            return ('lit', text) if text is not None else None
        if name not in {'STRJOIN', 'FINDELEMENT', 'FINDLASTELEMENT'} or not arguments:
            return None
        first = arguments[0]
        if first[0] != 'var' or first[1] not in constants:
            return None
        variable = constants[first[1]]
        indices = tuple(reducer.reduce(child) for child in first[2])
        rest = tuple(reducer.reduce(child) for child in arguments[1:])
        if not all(
            child[0] == 'lit' and isinstance(child[1], int) for child in indices
        ):
            return None
        if not all(child[0] in {'lit', 'missing'} for child in rest):
            return None
        from .data import Ref

        key = tuple(child[1] for child in indices)
        key += (0,) * (len(variable.dims) - len(key))
        reference = Ref(variable, key)
        if name == 'STRJOIN':
            from .reference_functions import function as array_function

            if not variable.string:
                return None  # StaticContext supplies the native type diagnostic.
            values = [
                reference,
                *[child[1] if child[0] == 'lit' else None for child in rest],
            ]
            return ('lit', array_function(None, name, values))
        if not rest:
            return None
        from .compat1824 import find_element
        from types import SimpleNamespace

        return (
            'lit',
            find_element(
                SimpleNamespace(ref_node=lambda _: reference), name, (first, *rest)
            ),
        )

    resolve.call = special
    return resolve


def _function_references(program, function, method_uids):
    names = []
    dynamic = False
    for line in function.lines:
        op, argument = command(line.text)
        spec = command_spec(op) or {}
        # VOID text cannot create references, including through macro expansion.
        if op == 'UPCHECK':
            continue
        if function.uid in method_uids and spec.get('method_safe') is False:
            # Native setArgument marks an unsafe method line before jump analysis.
            # Its rejected CALL/FORM text must not add children or dynamic scope.
            continue
        expanded = program.expand(argument)
        expression_sources = [expanded]
        if spec.get('family') == 'call':
            from .call_syntax import parse_call, is_statement_call

            if 'FORM' in op:
                from .call_syntax import constant_form_name

                try:
                    syntax = parse_call(expanded, form=True)
                    target = constant_form_name(
                        syntax.target,
                        program.functions,
                        constant_resolver(program, function),
                        getattr(program, 'load_form_methods', None),
                    )
                except EraError:
                    expression_sources = []
                else:
                    if target is None:
                        dynamic = True
                    elif target.upper() in program.functions:
                        names.append(target.upper())
                    expression_sources = list(syntax.arguments)
            elif is_statement_call(op):
                try:
                    syntax = parse_call(expanded)
                except EraError:
                    expression_sources = []
                else:
                    target = syntax.target.upper()
                    if target in program.functions:
                        names.append(target)
                    elif target.startswith('"'):
                        dynamic = True
                    expression_sources = list(syntax.arguments)
            else:
                target = (
                    split_args(expanded)[0].strip().upper() if expanded.strip() else ''
                )
                if target in program.functions:
                    names.append(target)
        # CALL names are raw strings. Scan only their expression arguments.
        for expression in expression_sources:
            names.extend(_expression_references(program, expression))
        if 'FORM' in op:
            from .formatting import form_expression_sources

            try:
                for expression, _ in form_expression_sources(expanded):
                    names.extend(
                        _expression_references(
                            program, expression, tolerate_error=False
                        )
                    )
            except EraError:
                pass
    return names, dynamic


def _walk_roots(program, roots, ordered):
    method_uids = {function.uid for function in method_roots(program)}
    pending = deque(roots)
    seen = set()
    selected = []
    dynamic = False
    while pending:
        function = pending.popleft()
        if function.uid in seen:
            continue
        seen.add(function.uid)
        selected.append(function)
        names, has_dynamic = _function_references(program, function, method_uids)
        dynamic = dynamic or has_dynamic
        children = {
            child.uid: child
            for name in names
            for child in program.functions[name]
            if child.uid not in seen
        }
        pending.extend(sorted(children.values(), key=lambda function: function.uid))
    if dynamic:
        selected.extend(function for function in ordered if function.uid not in seen)
        return selected, [], 'dynamic_target_conservative_all'
    return (
        selected,
        [function for function in ordered if function.uid not in seen],
        'reference_system_call_graph',
    )


def select_functions(program):
    """Return selected/ignored functions and the retained evidence scope label.

    Valid expression methods are independent native Depth0 roots.
    Explicit ignoreNO and analysis mode select all labels. Without system entry
    and without an explicit ignore setting, embedding APIs also retain all.
    No condition is evaluated, no frame is created and no variable/RNG is read.
    """
    policy = json.loads(
        files('pyemuera')
        .joinpath('specs/load_roots_v24.json')
        .read_text(encoding='utf-8')
    )
    ordered = sorted(
        (function for group in program.functions.values() for function in group),
        key=lambda function: function.uid,
    )
    system_roots = _system_roots(ordered, policy)
    ignore = (
        program.config.get('呼び出されなかった関数を無視する', 'YES').upper() == 'YES'
    )
    if program.analysis_mode:
        return ordered, [], 'all:AnalysisMode'
    if not ignore:
        return ordered, [], 'all:ignoreNO'
    if not system_roots and '呼び出されなかった関数を無視する' not in program.config:
        return ordered, [], 'api_module_without_system_entry'
    root_uids = {function.uid for function in system_roots}
    root_uids.update(function.uid for function in method_roots(program))
    roots = [function for function in ordered if function.uid in root_uids]
    return _walk_roots(program, roots, ordered)


def uncalled_functions(program):
    """Compute static uncalled labels independently of IgnoreUncalledFunction.

    Analysis selection and warning selection are separate. Preserve the API
    adaptation without a system entry. Existing conservative FORM/REF scope
    suppresses uncalled warnings, just as native useCallForm does.
    """
    policy = json.loads(
        files('pyemuera')
        .joinpath('specs/load_roots_v24.json')
        .read_text(encoding='utf-8')
    )
    ordered = sorted(
        (f for group in program.functions.values() for f in group), key=lambda f: f.uid
    )
    roots = _system_roots(ordered, policy)
    if (
        not roots
        and not program.analysis_mode
        and '呼び出されなかった関数を無視する' not in program.config
    ):
        return []
    root_uids = {f.uid for f in roots} | {f.uid for f in method_roots(program)}
    roots = [f for f in ordered if f.uid in root_uids]
    _, ignored, _ = _walk_roots(program, roots, ordered)
    return ignored


def diagnostic_functions(program, selected, uncalled):
    """Return called depth traversal, then the native uncalled-label pass.

    This chooses registration order only, not validation scope or execution.
    Retain the embedding adaptation when there is no system entry. Source UID
    order resolves ties within each already-selected depth/root group.
    """
    policy = json.loads(
        files('pyemuera')
        .joinpath('specs/load_roots_v24.json')
        .read_text(encoding='utf-8')
    )
    ordered = sorted(
        (function for group in program.functions.values() for function in group),
        key=lambda function: function.uid,
    )
    roots = _system_roots(ordered, policy)
    if (
        not roots
        and not program.analysis_mode
        and '呼び出されなかった関数を無視する' not in program.config
    ):
        return list(selected)
    root_uids = {function.uid for function in roots + method_roots(program)}
    called, _, _ = _walk_roots(
        program,
        [function for function in ordered if function.uid in root_uids],
        ordered,
    )
    selected_uids = {function.uid for function in selected}
    uncalled_uids = {function.uid for function in uncalled}
    return [
        function
        for function in called
        if function.uid in selected_uids and function.uid not in uncalled_uids
    ] + list(uncalled)


def prepare_constants(vm):
    """Bind immutable load metadata for FORM without providing VM expression input."""
    from .constant_ast import FORM_METHODS
    from .constant_ast import LOAD_CONSTANT_METHODS
    from .registry import FUNCTION_SPECS
    from . import builtins

    program = vm.program
    globals_constant = {
        name: value
        for name, value in vm.data.variables.items()
        if value.readonly and not value.character
    }
    program.load_constants = {
        function.uid: {
            **globals_constant,
            **{
                name: value
                for name, value in vm.static.get(function.uid, {}).items()
                if value is not None and value.readonly and not value.character
            },
        }
        for group in program.functions.values()
        for function in group
    }
    program.load_descriptors = {
        function.uid: {
            **vm.data.variables,
            **vm.legacy.get(function.name, {}),
            **vm.static.get(function.uid, {}),
        }
        for group in program.functions.values()
        for function in group
    }
    program.load_keyword_number = vm.data.keyword_number

    def adapter(name):
        def values_only(values):
            return builtins.call(vm, name, tuple(('lit', value) for value in values))

        return values_only

    # UniqueRestructure methods accepting descriptor/form operands cannot be
    # treated as ordinary literal-only methods. Their distinct paths stay out.
    excluded = {'GETNUM', 'STRFORM', 'STRJOIN', 'FINDELEMENT', 'FINDLASTELEMENT'}
    program.load_form_methods = {
        name: adapter(name)
        for name in LOAD_CONSTANT_METHODS - excluded
        if name in FUNCTION_SPECS
        and FUNCTION_SPECS[name].get('native_registered', True)
    }
    program.load_form_methods.update(FORM_METHODS)
