"""Source-default method diagnostics, separate from expression/FORM typing.

Only declared v24_default_fixed methods use FunctionMethod.CheckArgumentType.
Declared substring/variadic validators use their own source contracts.
Other custom validators and user signatures retain their existing paths. No argument
values, defaults, RNG or references are evaluated during validation.
"""

from .errors import EraError
from . import custom_function_arguments as custom
from .internal_state import successful_validation_cache

ARRAY_METHODS = frozenset(
    (
        'SUMARRAY',
        'SUMCARRAY',
        'MAXARRAY',
        'MAXCARRAY',
        'MINARRAY',
        'MINCARRAY',
        'STRJOIN',
    )
)


def check_count(name, spec, nodes):
    custom.check_count(name, nodes)
    if name in ARRAY_METHODS:
        if not nodes:
            raise EraError(
                name + '関数には少なくとも1つの引数が必要です', code='E_ARGUMENT'
            )
        if len(nodes) > (4 if name == 'STRJOIN' else 3):
            raise EraError(name + '関数の引数が多すぎます', code='E_ARGUMENT')
    if name == 'MONEYSTR':
        if not nodes:
            raise EraError(
                name + '関数には少なくとも1つの引数が必要です', code='E_ARGUMENT'
            )
        if len(nodes) > 2:
            raise EraError(name + '関数の引数が多すぎます', code='E_ARGUMENT')
    if name in ('ALLSAMES', 'NOSAMES', 'GROUPMATCH') and len(nodes) < 2:
        raise EraError(
            name + '関数には少なくとも2つの引数が必要です', code='E_ARGUMENT'
        )
    policy = spec.get('argument_diagnostic_policy')
    if policy in ('v24_substring', 'v24_numeric_variadic'):
        if not nodes:
            raise EraError(
                name + '関数には少なくとも1つの引数が必要です', code='E_ARGUMENT'
            )
        if policy == 'v24_substring' and len(nodes) > 3:
            raise EraError(name + '関数の引数が多すぎます', code='E_ARGUMENT')
    elif policy == 'v24_default_fixed' and len(nodes) != spec['min_args']:
        raise EraError(name + '関数:引数の数が間違っています', code='E_ARGUMENT')


def check_type(name, spec, index, actual, node):
    if name == 'MONEYSTR':
        if node[0] == 'missing':
            if index:
                return
            raise EraError(
                name + '関数の1番目の引数は省略できません', code='E_ARGUMENT'
            )
        if actual is not None and actual != ('Int64' if index == 0 else 'string'):
            raise EraError(
                name + '関数の' + str(index + 1) + '番目の引数の型が正しくありません',
                code='E_TYPE',
            )
        return
    policy = spec.get('argument_diagnostic_policy')
    if not policy:
        return
    if policy in ('v24_substring', 'v24_numeric_variadic'):
        if node[0] == 'missing':
            if policy == 'v24_substring' and index > 0:
                return
            raise EraError(
                name + '関数の' + str(index + 1) + '番目の引数は省略できません',
                code='E_ARGUMENT',
            )
        expected = 'string' if policy == 'v24_substring' and index == 0 else 'Int64'
        if actual is not None and actual != expected:
            raise EraError(
                name + '関数の' + str(index + 1) + '番目の引数の型が正しくありません',
                code='E_TYPE',
            )
        return
    if node[0] == 'missing':
        raise EraError(
            name + '関数:第' + str(index + 1) + '引数は省略できません',
            code='E_ARGUMENT',
        )
    expected = spec['argument_diagnostic_types'][index]
    if actual is not None and actual != expected:
        raise EraError(
            name + '関数:第' + str(index + 1) + '引数の型が間違っています',
            code='E_TYPE',
        )


def check_homogeneous(name, actuals, nodes):
    """The three registered comparison methods accept one shared operand type."""
    if name not in ('ALLSAMES', 'NOSAMES', 'GROUPMATCH'):
        return
    for i, (actual, node) in enumerate(zip(actuals, nodes)):
        if node[0] == 'missing':
            raise EraError(
                name + '関数の' + str(i + 1) + '番目の引数は省略できません',
                code='E_ARGUMENT',
            )
        if i and actual is not None and actuals[0] is not None and actual != actuals[0]:
            raise EraError(
                name + '関数の' + str(i + 1) + '番目の引数の型が正しくありません',
                code='E_TYPE',
            )


def check_array_descriptor(name, actuals, nodes, context=None):
    """Custom array validators inspect descriptors, never array elements."""
    if name not in ARRAY_METHODS:
        return
    first = nodes[0]
    if first[0] == 'missing':
        raise EraError(name + '関数の1番目の引数は省略できません', code='E_ARGUMENT')
    if first[0] != 'var':
        raise EraError(
            name + '関数の1番目の引数が変数ではありません', code='E_REFERENCE'
        )
    descriptor = context.descriptor(first[1]) if context is not None else None
    chara = name in ('SUMCARRAY', 'MAXCARRAY', 'MINCARRAY')
    if (
        name in ('MAXCARRAY', 'MINCARRAY')
        and descriptor is not None
        and not getattr(descriptor, 'character', True)
    ):
        raise EraError(
            name + '関数の1番目の引数がキャラクタ変数ではありません', code='E_TYPE'
        )
    if name != 'STRJOIN' and actuals[0] not in (None, 'Int64'):
        raise EraError(
            name + '関数の1番目の引数が数値変数ではありません', code='E_TYPE'
        )
    if chara and descriptor is not None and not getattr(descriptor, 'character', True):
        raise EraError(
            name + '関数の1番目の引数がキャラクタ変数ではありません', code='E_TYPE'
        )
    dims = getattr(descriptor, 'dims', None)
    if (
        not chara
        and name.startswith(('MAX', 'MIN'))
        and dims is not None
        and len(dims) > 1
    ):
        raise EraError(
            name + '関数は二重配列・三重配列には対応していません', code='E_TYPE'
        )
    for i in range(1, len(nodes)):
        if nodes[i][0] == 'missing':
            continue
        expected = 'string' if name == 'STRJOIN' and i == 1 else 'Int64'
        if actuals[i] not in (None, expected):
            if name.startswith('SUM') or name == 'STRJOIN':
                suffix = (
                    '変数が'
                    + ('文字列' if expected == 'string' else '数値')
                    + 'ではありません'
                )
            else:
                suffix = '引数の型が正しくありません'
            raise EraError(
                name + '関数の' + str(i + 1) + '番目の' + suffix, code='E_TYPE'
            )


def validate_literals(name, nodes):
    from .registry import FUNCTION_SPECS

    spec = FUNCTION_SPECS[name]
    check_count(name, spec, nodes)
    actuals = [
        (
            ('string' if isinstance(node[1], str) else 'Int64')
            if node[0] == 'lit'
            else None
        )
        for node in nodes
    ]
    check_homogeneous(name, actuals, nodes)
    check_array_descriptor(name, actuals, nodes)
    custom.validate(name, actuals, nodes)
    if not spec.get('argument_diagnostic_policy') and name != 'MONEYSTR':
        return
    for i, node in enumerate(nodes):
        actual = (
            ('string' if isinstance(node[1], str) else 'Int64')
            if node[0] == 'lit'
            else None
        )
        check_type(name, spec, i, actual, node)


def validate_runtime(vm, name, nodes):
    from .registry import FUNCTION_SPECS

    spec = FUNCTION_SPECS[name]
    if not spec.get(
        'argument_diagnostic_policy'
    ) and name not in ARRAY_METHODS | custom.SUPPORTED | {
        'ALLSAMES',
        'NOSAMES',
        'GROUPMATCH',
        'MONEYSTR',
    }:
        return
    if (
        (all(node[0] in ('lit', 'missing') for node in nodes) and name != 'GETNUMB')
        or not hasattr(vm, 'program')
        or not hasattr(vm, 'declarations')
    ):
        # Minimal caller adapters can still validate literal terms without a VM.
        return validate_literals(name, nodes)
    frames = getattr(vm, 'frames', [])
    fn = frames[-1].function if frames else next(iter(vm.program.functions.values()))[0]
    key = (fn.uid, name, tuple(nodes))
    cache = successful_validation_cache(vm, '_expression_argument_type_cache')
    if key in cache:
        return
    from .load_arguments import StaticContext

    context = StaticContext(vm, fn)
    actuals = [context.infer(node) for node in nodes]
    check_count(name, spec, nodes)
    check_homogeneous(name, actuals, nodes)
    check_array_descriptor(name, actuals, nodes, context)
    custom.validate(name, actuals, nodes, context)
    for i, node in enumerate(nodes):
        check_type(name, spec, i, actuals[i], node)
    # Successful signatures only: never cache a value, index, REF or exception.
    if not getattr(vm, 'initializing_declarations', False):
        cache.add(key)


def restructure_runtime(vm, nodes, name=None):
    """METHOD/default term restructuring, with no effectful operand reads."""
    from .constant_ast import Reducer

    if (
        not hasattr(vm, 'program')
        or not hasattr(vm, 'declarations')
        or not getattr(vm.program, 'functions', None)
    ):
        reducer = Reducer()
    else:
        from .load_arguments import StaticContext

        frames = getattr(vm, 'frames', [])
        function = (
            frames[-1].function
            if frames
            else next(iter(vm.program.functions.values()))[0]
        )
        context = StaticContext(vm, function)
        context.runtime = True
        reducer = context.reducer
    return reducer.arguments(name, nodes)
