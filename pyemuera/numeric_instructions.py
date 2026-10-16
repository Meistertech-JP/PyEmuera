"""Typed instruction builders, separate from same-name expression methods.

The identifiers in bundled JSON select this closed registry, never imports.
POWER uses SP_POWER, not the two-argument PowerMethod adapter.
"""

from dataclasses import dataclass
import math
from .errors import EraError
from .expr import parse, integer
from .text import split_args


@dataclass(frozen=True)
class PowerArgument:
    destination: tuple
    base: tuple
    exponent: tuple


def power_value(base, exponent):
    """Process.ScriptProc and PowerMethod: double Pow, finite Int64 interior."""
    base, exponent = integer(base), integer(exponent)
    try:
        value = math.pow(base, exponent)
    except OverflowError as exc:
        raise EraError('累乗結果が無限大です', code='E_ARITH') from exc
    except ValueError as exc:
        # Integer exponents: zero to a negative power is +Infinity in .NET.
        message = (
            '累乗結果が無限大です'
            if base == 0 and exponent < 0
            else '累乗結果が非数値です'
        )
        raise EraError(message, code='E_ARITH') from exc
    if math.isnan(value):
        raise EraError('累乗結果が非数値です', code='E_ARITH')
    if math.isinf(value):
        raise EraError('累乗結果が無限大です', code='E_ARITH')
    if value >= float((1 << 63) - 1) or value <= -(1 << 63):
        raise EraError(
            '累乗結果(' + format(value, '.15G') + ')が64ビット符号付き整数の範囲外です',
            code='E_ARITH',
        )
    return int(value)


def build_power(context, spec, text):
    parts = split_args(text) if text.strip() else []
    nodes = [
        parse(context.vm.program.expand(part)) if part else ('missing',)
        for part in parts
    ]
    types = [context.infer(node) if node[0] != 'missing' else None for node in nodes]
    if len(parts) < spec['min_args']:
        raise EraError('POWER命令:引数が足りません', code='E_ARGUMENT')
    if len(parts) > spec['max_args']:
        context.warning(1, 'POWER命令:引数が多すぎます', 'E_ARGUMENT')
    # Count warning precedes first-three type checks and all Restructure.
    # Native ArgumentBuilder.cs:80/85 formats this index with Int32.ToString:
    # preserve the ASCII digit, unlike SP_TIMES' literal full-width digit.
    for index, node in enumerate(nodes[: spec['max_args']]):
        if node[0] == 'missing':
            raise EraError(
                'POWER命令:第' + str(index + 1) + '引数を認識できません',
                code='E_ARGUMENT',
            )
        if types[index] != 'Int64':
            raise EraError(
                'POWER命令:第' + str(index + 1) + '引数の型が正しくありません',
                code='E_TYPE',
            )
    # C# also restructures ignored extra terms. They are never runtime-evaluated.
    nodes = [context.reduce(node) for node in nodes]
    target = nodes[0]
    if target[0] != 'var':
        raise EraError(
            'POWER命令:第1引数に変数以外を指定することはできません', code='E_REFERENCE'
        )
    variable = context.descriptor(target[1])
    if variable is not None and variable.readonly:
        # CONST and special integer constants restructure to SingleTerm in v24.
        message = (
            '変数以外' if all(n[0] == 'lit' for n in target[2]) else '変更できない変数'
        )
        raise EraError(
            'POWER命令:第1引数に' + message + 'を指定することはできません',
            code='E_REFERENCE',
        )
    return PowerArgument(target, nodes[1], nodes[2])


def execute_power(vm, argument):
    # X then Y then SetValue. The target index is evaluated once, only on write.
    base = vm.eval_node(argument.base)
    exponent = vm.eval_node(argument.exponent)
    value = power_value(base, exponent)
    vm.ref_node(argument.destination).set(value)


BUILDERS = {'power_int64_destination': build_power}
HANDLERS = {'power_int64_destination': execute_power}


def compile_instruction(context, spec, text):
    return BUILDERS[spec['argument_builder']](context, spec, text)


def execute(vm, spec, text):
    from .load_arguments import StaticContext

    context = StaticContext(vm, vm.frames[-1].function)
    context.runtime = True
    argument = compile_instruction(context, spec, text)
    HANDLERS[spec['instruction_handler']](vm, argument)
    return True
