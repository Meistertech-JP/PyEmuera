"""Closed declarative load builders: type checks and safe AST reduction only.

No evaluate(), live reference or frame binding. Deferred subname/default/REF
contracts are recorded as pending rather than resolved using game state.
"""

from .errors import EraError
from .expr import parse
from .registry import command_spec
from .text import split_args, split_dynamic_call

INT = 'Int64'


def checked_terms(context, op, arg, expected):
    parts = split_args(arg) if arg.strip() else []
    if not parts:
        if expected == INT:
            suffix = (
                ''
                if command_spec(op)['load_argument_contract'].get('is_extended')
                else 'がeramakerの動作は不定です'
            )
            context.warning(
                1,
                op
                + '命令:省略できない引数が省略されています。Emueraは0を補います'
                + suffix,
                'E_ARGUMENT',
            )
            context.plans.append(('', ('lit', 0)))
            return 'omitted_integer_zero_source_pending_runtime'
        raise EraError(op + '命令:引数が足りません', code='E_ARGUMENT')
    nodes = [parse(context.vm.program.expand(p)) if p else ('missing',) for p in parts]
    types = [context.infer(node) if node[0] != 'missing' else None for node in nodes]
    if len(nodes) > 1:
        context.warning(1, op + '命令:引数が多すぎます', 'E_ARGUMENT')
    if nodes[0][0] == 'missing':
        raise EraError(op + '命令:第1引数を認識できません', code='E_ARGUMENT')
    if expected is not None and types[0] is not None and types[0] != expected:
        raise EraError(op + '命令:第1引数の型が正しくありません', code='E_TYPE')
    for part, node in zip(parts, nodes):
        node = context.reduce(node)
        context.plans.append((context.vm.program.expand(part), node))
    return 'safe_static_terms_checked'


def nullable_terms(context, op, arg):
    if not arg.strip():
        return 'nullable_expression_omitted'
    return checked_terms(context, op, arg, None)


def integer_terms(context, op, arg):
    return checked_terms(context, op, arg, INT)


def any_terms(context, op, arg):
    return checked_terms(context, op, arg, None)


def void_terms(context, op, arg):
    # VOID builder warns but discards without expression evaluation.
    if arg.strip(' \t'):
        context.warning(1, op + '命令:引数は不要です', 'E_ARGUMENT')
    return 'void_source_argument_discarded'


def case_terms(context, op, arg):
    return context.statement(op, arg)


def call_terms(context, op, arg):
    from .call_syntax import parse_call, constant_form_name, is_statement_call

    form = 'FORM' in op or op == 'FUNC'
    expanded = context.vm.program.expand(arg)
    if not is_statement_call(op):
        # GOTO/FUNC retain their existing term/name contract.
        parts = split_dynamic_call(expanded) if form else split_args(expanded)
        if not parts or not parts[0].strip():
            raise EraError(op + '命令:関数名が指定されていません', code='E_ARGUMENT')
        if form:
            context.form(parts[0])
        for term in parts[1:]:
            if term:
                context.expression(term)
        return 'call_terms_checked_binding_subnames_pending'
    syntax = parse_call(expanded, form, context.infer)
    if form:
        context.form(syntax.target)
    for term in syntax.arguments:
        if term:
            context.expression(term)
    from .load_reachability import constant_resolver

    target = (
        constant_form_name(
            syntax.target,
            context.vm.program.functions,
            constant_resolver(context.vm.program, context.function),
            getattr(context.vm.program, 'load_form_methods', None),
        )
        if form
        else syntax.target
    )
    known = target is not None and target.upper() in context.vm.program.functions
    if target is not None and not known and not op.startswith('TRY'):
        error = EraError(
            f'Unknown function @{target.upper()}',
            code='E_FUNCTION',
            diagnostic_message=(
                target.upper()
                if context.vm.program.analysis_mode and op.endswith('F')
                else '指定された関数名"@' + target.upper() + '"は存在しません'
            ),
        )
        error.call_resolution = 'callf' if op.endswith('F') else 'call'
        raise error
    if known and op.endswith('F'):
        function = context.vm.program.functions[target.upper()][0]
        if not function.attributes & {'FUNCTION', 'FUNCTIONS'}:
            error = EraError('CALLF requires #FUNCTION/#FUNCTIONS', code='E_FUNCTION')
            error.call_resolution = 'callf'
            raise error
        nodes = [
            parse(context.vm.program.expand(term)) if term else ('missing',)
            for term in syntax.arguments
        ]
        context.infer(('call', target.upper(), tuple(nodes)))
    return (
        'call_terms_checked_static_target_bound'
        if target is not None
        else 'call_terms_checked_dynamic_target'
    )


def character_terms(context, op, arg):
    """INT_ANY checks every AST/type before DoInstruction evaluates terms."""
    parts = split_args(arg) if arg.strip() else []
    if not parts:
        raise EraError('引数が設定されていません', code='E_ARGUMENT')
    for part in parts:
        if not part:
            raise EraError('省略できない引数が省略されています', code='E_ARGUMENT')
        context.expression(part, INT)
    return 'r33_character_integer_terms_checked'


def parameter_terms(context, op, arg):
    from .parameter_arguments import check

    return check(context, op, arg)


def times_terms(context, op, arg):
    from .decimal_instruction import build

    build(context, arg)
    return 'times_double_literal_destination_checked'


BUILDERS = {
    'nullable_terms': nullable_terms,
    'times_terms': times_terms,
    'character_terms': character_terms,
    'parameter_terms': parameter_terms,
    'integer_terms': integer_terms,
    'any_terms': any_terms,
    'void_terms': void_terms,
    'case_terms': case_terms,
    'call_terms': call_terms,
}


def dispatch(context, op, arg, spec):
    return BUILDERS[spec['load_argument_contract']['handler']](context, op, arg)
