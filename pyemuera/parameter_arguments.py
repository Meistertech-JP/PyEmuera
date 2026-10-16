"""UPCHECK/CUPCHECK builders, separate from their runtime state changes.

VOID discards even malformed text. INT_EXPRESSION parses every term and
restructures each non-null term, but only its first value executes later.
Static checks never evaluate a script expression or consume the RNG.
"""

from __future__ import annotations

from types import SimpleNamespace

from .errors import EraError
from .expr import parse
from .text import split_args
from .internal_state import successful_validation_cache


def check(context, name: str, argument: str) -> str:
    """Collect native builder warnings/plans, preserving error order.

    Extra null terms are allowed; a null first term is not. The omission
    warning occurs after the normal empty-term check, and supplies numeric 0.
    Runtime lazy parsing queues no visible warning, as in ArgumentParser.
    """
    if name == 'UPCHECK':
        if argument.strip(' \t'):
            context.warning(1, name + '命令:引数は不要です', 'E_ARGUMENT')
        return 'parameter_void_argument_discarded'
    if name != 'CUPCHECK':
        raise EraError('Unknown parameter argument builder ' + name, code='E_SPEC')

    parts = split_args(argument) if argument.strip() else []
    # Parse/type construction precedes the command's count/type warnings.
    expanded = [context.vm.program.expand(part) for part in parts]
    nodes = [parse(part) if part else None for part in expanded]
    types = [context.infer(node) if node is not None else None for node in nodes]
    if len(nodes) > 1:
        context.warning(1, name + '命令:引数が多すぎます', 'E_ARGUMENT')
    if nodes:
        if nodes[0] is None:
            raise EraError(name + '命令:第1引数を認識できません', code='E_ARGUMENT')
        if types[0] not in (None, 'Int64'):
            raise EraError(name + '命令:第1引数の型が正しくありません', code='E_TYPE')
        for text, node in zip(expanded, nodes):
            if node is not None:
                context.plans.append((text, context.reduce(node)))
    else:
        context.warning(
            1,
            name + '命令:省略できない引数が省略されています。Emueraは0を補います',
            'E_ARGUMENT',
        )
        context.plans.append(('', ('lit', 0)))
    return 'parameter_first_integer_all_terms_restructured'


def lazy(vm, name: str, argument: str) -> None:
    """Validate once per function/text; cache ASTs, never values or failures.

    A bare Python command adapter has no frame. Its first loaded function
    supplies declaration metadata only; this is an API adaptation, not a
    new native script entry point. No frame is created and no default runs.
    """
    # Neither VOID nor the synthesized zero needs expression metadata.
    # Runtime warnings are queued without a loader flush, so emit none here.
    if name == 'UPCHECK' or not argument.strip():
        return
    if vm.frames:
        function = vm.frames[-1].function
    else:
        function = min(
            (function for group in vm.program.functions.values() for function in group),
            key=lambda function: function.uid,
            default=SimpleNamespace(name='', uid=-1),
        )
    key = (function.uid, name, argument)
    cache = successful_validation_cache(vm, '_parameter_argument_cache')
    if key in cache:
        return
    from .load_arguments import StaticContext

    context = StaticContext(vm, function)
    context.runtime = True
    check(context, name, argument)
    for text, node in context.plans:
        vm._expression_cache[text] = node
    cache.add(key)
