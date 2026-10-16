"""Declarative display-command diagnostics without expression execution.

The JSON key argument_check_r13 is a historical data contract, not a module
version. StaticContext owns type inference/reduction and diagnostic collection.
Inner expression diagnostics precede outer command type diagnostics. Successful
lazy checks are cached per function/command/source text; values are never cached.
"""

from .errors import EraError
from .expr import parse
from .text import split_args
from .internal_state import successful_validation_cache


def check(context, op, arg, spec):
    """Validate builder arguments and append their existing reduction plans.

    Returns the historical builder label or None for unowned contracts. Emits
    warnings through context; raises EraError with the existing text and code.
    Plans are appended incrementally, including before a later argument fails.
    No script values, references or RNG are read/evaluated by this adapter.
    """
    if op in ('SAVENOS', 'PRINTCPERLINE'):
        return integer_destination(context, op, arg)
    contract = spec.get('argument_check_r13')
    if not contract:
        return None
    parts = split_args(arg) if arg.strip() else []
    minimum, maximum = contract['minimum'], contract['maximum']
    extra_policy = contract.get('extra')
    if len(parts) < minimum:
        if not parts and contract.get('omitted_zero'):
            if contract.get('omitted_warning'):
                context.warning(
                    1,
                    op + '命令:省略できない引数が省略されています。Emueraは0を補います',
                    'omitted_zero',
                )
            return 'r13_nullable_integer_builder'
        raise EraError(op + '命令:引数が足りません', code='E_ARGUMENT')
    if len(parts) > maximum:
        if extra_policy == 'void_warn_ignore':
            context.warning(1, op + '命令:引数は不要です', 'unneeded_arguments')
            return 'r13_void_builder'
        if extra_policy != 'warn_ignore':
            raise EraError(op + '命令:引数が多すぎます', code='E_ARGUMENT')
        context.warning(1, op + '命令:引数が多すぎます', 'excess_arguments')

    for index, text in enumerate(parts):
        if not text:
            raise EraError(
                op + '命令:省略できない引数が省略されています', code='E_ARGUMENT'
            )
        expanded = context.vm.program.expand(text)
        node = parse(expanded)
        actual_type = context.infer(node)
        expected_type = (
            contract['types'][index] if index < len(contract['types']) else None
        )
        if (
            expected_type is not None
            and actual_type is not None
            and actual_type != expected_type
        ):
            raise EraError(
                op + '命令:第' + str(index + 1) + '引数の型が正しくありません',
                code='E_TYPE',
            )
        context.plans.append((expanded, context.reduce(node)))
    return 'r13_known_argument_builder'


def lazy(vm, op, arg, spec):
    """Check once at runtime, after skip policy, caching only successful checks.

    The old _r13_command_argument_cache attribute remains stable for existing
    integrations. Failures are not cached; the next call repeats diagnostics.
    """
    if op in ('DOTRAIN', 'CALLTRAIN', 'AWAIT') and vm.frames:
        from .load_arguments import StaticContext
        from .load_builders import dispatch

        context = StaticContext(vm, vm.frames[-1].function)
        context.runtime = True
        dispatch(context, op, arg, spec)
        return
    if op in ('SAVENOS', 'PRINTCPERLINE'):
        if not vm.frames:
            return
        from .load_arguments import StaticContext

        context = StaticContext(vm, vm.frames[-1].function)
        context.runtime = True
        integer_destination(context, op, arg)
        return
    if op in ('REF', 'REFBYNAME'):
        from .errors import EraError

        raise EraError(op + '命令:書式が間違っています', code='E_ARGUMENT')
    if spec.get('load_argument_contract', {}).get('handler') == 'character_terms':
        # Keep static parsing separate from the SP gate/value evaluation. This
        # adapter belongs to VM dispatch; commands.execute_command remains its
        # historical direct API without a synthetic caller frame.
        if not vm.frames:
            return
        key = (vm.frames[-1].function.uid, op, arg)
        cache = successful_validation_cache(vm, '_r33_character_argument_cache')
        if key not in cache:
            from .load_arguments import StaticContext
            from .load_builders import character_terms

            context = StaticContext(vm, vm.frames[-1].function)
            context.runtime = True
            character_terms(context, op, arg)
            cache.add(key)
        return
    if not spec.get('argument_check_r13'):
        return
    if vm.console.skip_print and (spec.get('skip_before_eval') or op == 'HTML_PRINT'):
        return
    key = (vm.frames[-1].function.uid, op, arg)
    cache = successful_validation_cache(vm, '_r13_command_argument_cache')
    if key in cache:
        return
    from .load_arguments import StaticContext

    context = StaticContext(vm, vm.frames[-1].function)
    context.runtime = True
    check(context, op, arg, spec)
    cache.add(key)


def integer_destination(context, op, arg):
    """SP_GETINT: parse/type, restructure *all* terms, then mutable destination.

    In particular constant 1/0 fails before the non-variable diagnostic, whereas
    a postfix or RAND term is never evaluated merely to discover its shape.
    Excess terms are restructured but their runtime values are discarded.
    """
    parts = split_args(arg) if arg.strip() else []
    if not parts:
        return 'v24_sp_getint_default_result'
    nodes = [parse(context.vm.program.expand(p)) if p else ('missing',) for p in parts]
    actuals = [context.infer(node) for node in nodes]
    if len(nodes) > 1:
        context.warning(1, op + '命令:引数が多すぎます', 'E_ARGUMENT')
    if nodes[0][0] == 'missing':
        raise EraError(op + '命令:第1引数を認識できません', code='E_ARGUMENT')
    if actuals[0] not in (None, 'Int64'):
        raise EraError(op + '命令:第1引数の型が正しくありません', code='E_TYPE')
    reduced = [context.reduce(node) for node in nodes]
    first = reduced[0]
    if first[0] != 'var':
        raise EraError(
            op + '命令:第1引数に変数以外を指定することはできません', code='E_ARGUMENT'
        )
    descriptor = context.descriptor(first[1])
    if descriptor is not None and descriptor.readonly:
        raise EraError(
            op + '命令:第1引数に変更できない変数を指定することはできません',
            code='E_ARGUMENT',
        )
    context.plans.extend(
        (context.vm.program.expand(p), n) for p, n in zip(parts, reduced)
    )
    return 'v24_sp_getint_destination'
