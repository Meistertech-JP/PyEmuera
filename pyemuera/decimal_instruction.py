"""SP_TIMES: a double literal, two destination-index evaluations, .NET casts."""

from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import math
import re
from .expr import integer, parse
from .text import split_args
from .errors import EraError

DECIMAL_MAX = (1 << 96) - 1
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

# Japanese Framework capture (format-probe-framework.json, eight overflows)
# plus Process.cs:501's type-and-message rendering. This bounded presentation
# profile preserves the internal E_ARITH API; other UI resources are unmeasured.
DECIMAL_OVERFLOW_DIAGNOSTIC_JA = (
    'System.OverflowException:Decimal 型の値が大きすぎるか、または小さすぎます。'
)


def _multiplier(raw, warning=None):
    # LexicalAnalyzer.ReadDouble consumes a numeric prefix; exponent '+' is
    # deliberately not consumed in v24. A bad/overflowing literal warns -> 0.
    match = re.match(r'[+-]?[\d.]*(?:[eE]-?[\d.]*)?', raw.lstrip())
    token = match.group() if match else ''
    try:
        value = float(token)
        if not math.isfinite(value):
            raise ValueError()
    except ValueError:
        if warning:
            warning(
                1,
                'TIMES命令:第２引数が実数値ではありません（常に0と解釈されます）',
                'E_ARGUMENT',
            )
        return 0.0
    if raw.lstrip()[len(token) :].strip() and warning:
        warning(1, 'TIMES命令:引数が多すぎます', 'E_ARGUMENT')
    return value


def build(context, arg):
    parts = split_args(arg)
    if len(parts) < 2 or not ','.join(parts[1:]).strip():
        raise EraError('TIMES命令:引数が足りません', code='E_ARGUMENT')
    multiplier = _multiplier(','.join(parts[1:]), context.warning)
    target = parse(context.vm.program.expand(parts[0]))
    actual = context.infer(target)
    target = context.reduce(target)
    # SP_TIMES_ArgumentBuilder (ArgumentBuilder.cs:275/277/279) spells the
    # first index as full-width '１'; preserve it rather than matching POWER.
    if target[0] != 'var':
        raise EraError(
            'TIMES命令:第１引数に変数以外を指定することはできません', code='E_REFERENCE'
        )
    # StaticContext uses 'string'; retain the older direct-context spelling.
    if actual == 'String' or actual == 'string':
        raise EraError(
            'TIMES命令:第１引数を文字列変数にすることはできません', code='E_TYPE'
        )
    variable = context.descriptor(target[1])
    if variable is not None and variable.readonly:
        raise EraError(
            'TIMES命令:第１引数に変更できない変数を指定することはできません',
            code='E_READONLY',
        )
    context.plans.append((context.vm.program.expand(parts[0]), target))
    return target, multiplier


def _fit_decimal(value):
    """Round a decimal product to .NET Decimal's scale/96-bit coefficient."""
    with localcontext() as context:
        context.prec = 100
        scale = min(28, max(0, -value.as_tuple().exponent))
        while scale >= 0:
            rounded = value.quantize(
                Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN
            )
            if abs(rounded.scaleb(scale)) <= DECIMAL_MAX:
                return rounded
            scale -= 1
    raise EraError(
        '値がDecimal型に対して大きすぎるか、または小さすぎます。',
        code='E_ARITH',
        diagnostic_message=DECIMAL_OVERFLOW_DIAGNOSTIC_JA,
    )


def _from_double(value):
    if abs(value) > DECIMAL_MAX:
        raise EraError(
            '値がDecimal型に対して大きすぎるか、または小さすぎます。',
            code='E_ARITH',
            diagnostic_message=DECIMAL_OVERFLOW_DIAGNOSTIC_JA,
        )
    # System.Decimal(double) retains 15 significant decimal digits, with
    # midpoint-to-even and scale at most 28; it does not preserve literal text.
    return _fit_decimal(Decimal(format(value, '.15g')))


def _unchecked_int64(value):
    # Windows CLR cvttsd2si produces the integer-indefinite sentinel for an
    # out-of-range binary64. Never emulate this as modular integer wrapping.
    if not math.isfinite(value) or value >= (1 << 63) or value < INT64_MIN:
        return INT64_MIN
    return int(value)


def execute(vm, spec, arg):
    from .load_arguments import StaticContext

    context = StaticContext(
        vm,
        (
            vm.frames[-1].function
            if vm.frames
            else vm.function(next(iter(vm.program.functions)))
        ),
    )
    context.runtime = True
    target, multiplier = build(context, arg)
    original = integer(vm.eval_node(target))
    from .config1824 import boolean

    raw = vm.data.config.get(
        'TIMESの計算をeramakerにあわせる',
        vm.data.config.get('TimesNotRigorousCalculation', 'NO'),
    )
    if boolean(raw):
        value = _unchecked_int64(float(original) * multiplier)
    else:
        with localcontext() as decimal_context:
            decimal_context.prec = 100
            product = _fit_decimal(Decimal(original) * _from_double(multiplier))
        value = (
            int(product)
            if INT64_MIN <= product <= INT64_MAX
            else _unchecked_int64(float(product))
        )
    # VariableTerm.GetIntValue and SetValue each evaluate a dynamic index.
    vm.ref_node(target).set(value)
    return True
