"""Implemented expression functions. Unsupported functions never return fake zeros."""

from __future__ import annotations
import datetime
import html
import math
import re
import unicodedata
from .data import Ref
from .expr import evaluate, integer, i64, parse
from .errors import EraError, Unsupported
from .text import display_width, legacy_substring

from .registry import FUNCTION_SPECS
from . import compat1824

NAMES = frozenset(FUNCTION_SPECS)
ARITY = {
    name: (spec['min_args'], spec['max_args']) for name, spec in FUNCTION_SPECS.items()
}
REF_FIRST = frozenset(
    name for name, spec in FUNCTION_SPECS.items() if spec['reference_first']
)


def _string(value):
    if not isinstance(value, str):
        raise EraError('String required', code='E_TYPE')
    return value


def validate_call_arguments(vm, name, nodes):
    """Method signature only, before METHOD builder constant restructuring."""
    from .expression_arguments import validate_runtime

    validate_runtime(vm, name, nodes)
    minimum, maximum = ARITY[name]
    if not minimum <= len(nodes) <= maximum:
        raise EraError(
            f'{name}: accepted argument count {minimum}..{maximum}; got {len(nodes)}',
            code='E_ARGUMENT',
        )


def call(vm, name, nodes):
    """Validate and dispatch an expression AST without eager reference reads.

    GETNUM consumes a descriptor. Declared AST-aware families own evaluation;
    only remaining handlers receive values. Do not move validation/evaluation
    into the value-handler try block: diagnostics and side effects depend on it.
    """
    if name in {'ISSKIP', 'MESSKIP', 'MOUSESKIP'}:
        if name == 'ISSKIP':
            validate_call_arguments(vm, name, nodes)
        if nodes:
            raise EraError(name + '関数の引数が多すぎます', code='E_ARGUMENT')
        return (
            int(vm.console.skip_print) if name == 'ISSKIP' else int(vm.console.no_wait)
        )
    if name not in NAMES:
        raise Unsupported(f'Expression function {name}')
    validate_call_arguments(vm, name, nodes)
    if name in (
        'ALLSAMES',
        'NOSAMES',
        'GROUPMATCH',
        'GETSPCHARA',
        'SUMARRAY',
        'SUMCARRAY',
        'MAXARRAY',
        'MAXCARRAY',
        'MINARRAY',
        'MINCARRAY',
        'STRJOIN',
    ):
        from .expression_arguments import restructure_runtime

        nodes = restructure_runtime(vm, nodes, name)
    if name == 'ALLSAMES':
        # AllsamesMethod validates all operand types, then stops at the first
        # unequal value. Static bounds were checked in Restructure; later
        # dynamic index reads, increments and RAND stay untouched.
        first = evaluate(nodes[0], vm)
        for node in nodes[1:]:
            if evaluate(node, vm) != first:
                return 0
        return 1
    if name == 'GETSPCHARA' and not vm.data.use_sp:
        # GetspcharaMethod's compatibility gate precedes its operand read.
        raise EraError(
            'SPキャラ関係の機能は標準では使用できません'
            '(互換性オプション「SPキャラを使用する」をONにしてください)',
            code='E_ARGUMENT',
        )
    if name == 'GETNUM':
        if nodes[0][0] != 'var':
            raise EraError('GETNUM requires a variable descriptor', code='E_TYPE')
        vm.lookup(nodes[0][1])
        key = _string(evaluate(nodes[1], vm))
        return vm.data.keyword_number(nodes[0][1], key)
    if FUNCTION_SPECS[name]['handler'] == 'compat1824':
        return compat1824.call(vm, name, nodes)
    if FUNCTION_SPECS[name]['handler'] == 'character':
        from .character_data import function

        return function(vm, name, nodes)
    if FUNCTION_SPECS[name]['handler'] == 'html':
        from .html1824 import function

        return function(vm, name, nodes)
    if FUNCTION_SPECS[name]['handler'] == 'platform':
        from .platform1824 import function

        return function(vm, name, nodes)
    if FUNCTION_SPECS[name]['handler'] == 'regex1824':
        from .regex1824 import function

        return function(vm, name, nodes)
    if FUNCTION_SPECS[name]['handler'] == 'resource':
        from .resources1824 import function

        return function(vm, name, nodes)
    values = _evaluate_arguments(vm, name, nodes)
    return _call_with_values(vm, name, values)


def _evaluate_arguments(vm, name, nodes):
    """Evaluate each method's operands in its registered source order.

    The first array/character argument is a Ref, not a scalar read, including
    empty character arrays. Resolution precedes later side effects/RNG draws.
    Aggregate/join methods first evaluate their optional scalar operands, as
    their source resolves the fixed descriptor afterwards. This phase stays
    outside the value-handler exception translation boundary.
    """
    if name in REF_FIRST:
        if not nodes:
            raise EraError(f'{name} needs a reference', code='E_ARGUMENT')
        from .reference_functions import CHARACTER_FUNCTIONS
        from .expression_arguments import ARRAY_METHODS

        if name in ARRAY_METHODS:
            # These methods read bounds/delimiter before GetFixedVariableTerm.
            # Descriptor syntax/type was checked without evaluating its index.
            values = [evaluate(node, vm) for node in nodes[1:]]
            reference = vm.ref_node(
                nodes[0],
                allow_character_descriptor=name in CHARACTER_FUNCTIONS,
            )
            return [reference] + values
        reference = vm.ref_node(
            nodes[0],
            allow_character_descriptor=name in CHARACTER_FUNCTIONS,
        )
        return [reference] + [evaluate(node, vm) for node in nodes[1:]]
    return [evaluate(node, vm) for node in nodes]


def _call_with_values(vm, name, a):
    """Apply value handlers; translate only their existing Python failures.

    CHKFONT/non-BMP checks remain outside the try block. Exceptions during
    AST evaluation are deliberately not reclassified as E_ARGUMENT here.
    Remaining legacy branches stay in place until their contracts are moved.
    """
    if name == 'CHKFONT':
        _string(a[0])
        vm.console.warning(
            'font-query', 'CLI cannot select game fonts; CHKFONT returns 0.'
        )
        return 0
    if name == 'SAVENOS':
        from .configuration_functions import function

        return function(vm, name, a)
    if (
        name in {'STRLENSU', 'SUBSTRINGU', 'STRFINDU', 'CHARATU', 'ENCODETOUNI'}
        and a
        and isinstance(a[0], str)
        and any(ord(c) > 0xFFFF for c in a[0])
    ):
        raise Unsupported(
            name + ' with non-BMP characters (UTF-16 semantics not implemented)'
        )
    try:
        if FUNCTION_SPECS[name]['handler'] == 'scalar_numeric':
            from .scalar_numeric import function

            return function(name, a)
        if name == 'SQRT':
            return math.isqrt(integer(a[0]))
        if name == 'POWER':
            base, exponent = map(integer, a[:2])
            # Normally unreachable: bundled POWER selects compat1824 above.
            # Keep the legacy adapter consistent if that binding is inspected.
            from .numeric_instructions import power_value

            return power_value(base, exponent)
        if name == 'RAND':
            lo, hi = (
                (0, integer(a[0]))
                if len(a) == 1
                else (0 if a[0] is None else integer(a[0]), integer(a[1]))
            )
            if hi <= lo:
                raise EraError(
                    'RAND upper bound must exceed lower bound', code='E_ARGUMENT'
                )
            return vm.rng.randrange(lo, hi)
        if name == 'ISNUMERIC':
            try:
                int(_string(a[0]).strip(), 10)
                return 1
            except ValueError:
                return 0
        if name == 'TOINT':
            s = _string(a[0]).strip()
            try:
                return i64(
                    int(
                        s,
                        (
                            16
                            if s.lower().startswith('0x')
                            else 2 if s.lower().startswith('0b') else 10
                        ),
                    )
                )
            except ValueError:
                return 0
        if name in {'TOSTR', 'TOUPPER', 'TOLOWER', 'TOHALF', 'TOFULL'}:
            from .string_conversions import function

            return function(vm, name, a)
        if name == 'STRLENS':
            return display_width(_string(a[0]))
        if name == 'STRLENSU':
            return len(_string(a[0]).encode('utf-16-le')) // 2
        if name in ('SUBSTRING', 'SUBSTRINGU'):
            # Only the source-declared optional positions accept an omitted term.
            from .substring_arguments import optional_index

            s = _string(a[0])
            start = optional_index(a, 1, 0)
            n = optional_index(a, 2, -1)
            if name == 'SUBSTRING':
                return legacy_substring(s, start, n)
            start = max(0, start)
            return s[start:] if n < 0 else s[start : start + n]
        if name in ('STRFIND', 'STRFINDU'):
            s, part = _string(a[0]), _string(a[1])
            start = integer(a[2]) if len(a) > 2 else 0
            if name == 'STRFINDU':
                return s.find(part, max(0, start))
            prefix = legacy_substring(s, 0, start)
            idx = s.find(part, len(prefix))
            return -1 if idx < 0 else display_width(s[:idx])
        if name == 'CHARATU':
            return _string(a[0])[integer(a[1]) : integer(a[1]) + 1]
        if name == 'STRCOUNT':
            return len(re.findall(_string(a[1]), _string(a[0])))
        if name == 'REPLACE':
            # Common .NET $1 replacement groups mapped to Python; advanced .NET constructs rejected.
            repl = re.sub(
                r'\$(\d+)', lambda m: r'\g<' + m.group(1) + '>', _string(a[2])
            )
            return re.sub(_string(a[1]), repl, _string(a[0]))
        if name == 'ESCAPE':
            return re.escape(_string(a[0]))
        if name == 'UNICODE':
            value = integer(a[0])
            if not 0 <= value <= 0xFFFF or 0xD800 <= value <= 0xDFFF:
                raise Unsupported('UNICODE outside non-surrogate BMP')
            return chr(value)
        if name == 'ENCODETOUNI':
            s = _string(a[0])
            idx = integer(a[1]) if len(a) > 1 else 0
            return ord(s[idx]) if 0 <= idx < len(s) else 0
        if name == 'STRFORM':
            return vm.format(_string(a[0]))
        if name in ('GROUPMATCH', 'NOSAMES', 'ALLSAMES'):
            if not a or a[0] is None or any(type(x) != type(a[0]) for x in a):
                raise EraError(
                    name + ' requires same-type non-omitted arguments', code='E_TYPE'
                )
            return (
                sum(x == a[0] for x in a[1:])
                if name == 'GROUPMATCH'
                else (
                    int(len(set(a)) == len(a))
                    if name == 'NOSAMES'
                    else int(len(set(a)) <= 1)
                )
            )
        if name == 'VARSIZE':
            var = vm.lookup(_string(a[0]).upper())
            if isinstance(var, Ref):
                var = var.variable
            axis = integer(a[1]) if len(a) > 1 and a[1] is not None else 0
            if axis < 0 or axis >= len(var.dims or (1,)):
                raise EraError('VARSIZE axis outside rank', code='E_INDEX')
            return var.dims[axis] if var.dims else 1
        if name == 'GETNUM':
            try:
                return vm.data.index_of(_string(a[0]), _string(a[1]))
            except EraError:
                return -1
        if (
            name == 'EXISTCSV'
            or name.startswith('CSV')
            or name in {'GETCHARA', 'GETSPCHARA'}
        ):
            from .character_functions import function

            return function(vm, name, a)
        if name in REF_FIRST:
            from .reference_functions import function

            return function(vm, name, a)
        from .runtime_queries import NAMES as QUERY_NAMES, function as query_value

        if name in QUERY_NAMES:
            return query_value(vm, name, a, datetime)
        if name == 'HTML_ESCAPE':
            return html.escape(_string(a[0]))
        if name == 'HTML_TOPLAINTEXT':
            return vm.html_plain(_string(a[0]))
        if name in {
            'GETCONFIG',
            'GETCONFIGS',
            'GETPRINTCPERLINE',
            'PRINTCPERLINE',
            'GETPRINTCLENGTH',
            'PRINTCLENGTH',
        }:
            from .configuration_functions import function

            return function(vm, name, a)
    except (IndexError, TypeError, ValueError, OverflowError, re.error) as e:
        raise EraError(f'{name}: invalid arguments ({e})', code='E_ARGUMENT') from e
    raise Unsupported(f'Expression function {name}')


def describe_value_binding(name):
    """Describe the public AST route separately from a value-adapter fallback.

    Metadata is generated from the closed registry and owned-name sets; it never
    evaluates nodes, resolves REF, samples a clock or writes RESULT.
    """
    spec = FUNCTION_SPECS.get(name)
    if spec is None:
        return None
    from .runtime_queries import NAMES as QUERY_NAMES

    if name in {'ISSKIP', 'MESSKIP', 'MOUSESKIP', 'GETNUM'}:
        public = 'pyemuera.builtins.call special AST contract'
    elif spec['handler'] not in {'legacy', 'scalar_numeric'}:
        public = spec['handler'] + ' AST handler'
    else:
        public = 'pyemuera.builtins._evaluate_arguments -> _call_with_values'
    CONVERSION_NAMES = frozenset({'TOSTR', 'TOUPPER', 'TOLOWER', 'TOHALF', 'TOFULL'})
    if name in QUERY_NAMES:
        value_owner = 'pyemuera.runtime_queries.function'
    elif (
        name == 'EXISTCSV'
        or name.startswith('CSV')
        or name in {'GETCHARA', 'GETSPCHARA'}
    ):
        value_owner = 'pyemuera.character_functions.function'
    elif name in REF_FIRST:
        value_owner = 'pyemuera.reference_functions.function'
    elif name in CONVERSION_NAMES:
        value_owner = 'pyemuera.string_conversions.function'
    elif name in {
        'SAVENOS',
        'GETCONFIG',
        'GETCONFIGS',
        'GETPRINTCPERLINE',
        'PRINTCPERLINE',
        'GETPRINTCLENGTH',
        'PRINTCLENGTH',
    }:
        value_owner = 'pyemuera.configuration_functions.function'
    else:
        value_owner = 'pyemuera.builtins._call_with_values'
    public_owner = (
        'pyemuera.' + spec['handler'] + '.call'
        if spec['handler'] == 'compat1824'
        else (
            'pyemuera.character_data.function'
            if spec['handler'] == 'character'
            else (
                'pyemuera.'
                + {
                    'html': 'html1824',
                    'platform': 'platform1824',
                    'regex1824': 'regex1824',
                    'resource': 'resources1824',
                }[spec['handler']]
                + '.function'
                if spec['handler'] in {'html', 'platform', 'regex1824', 'resource'}
                else (
                    'pyemuera.scalar_numeric.function'
                    if spec['handler'] == 'scalar_numeric'
                    else value_owner
                )
            )
        )
    )
    if name in {'ISSKIP', 'MESSKIP', 'MOUSESKIP', 'GETNUM'}:
        public_owner = 'pyemuera.builtins.call'
    return {
        'implementation_owner': public_owner,
        'value_implementation_owner': value_owner,
        'declared_handler': spec['handler'],
        'public_AST_route': public,
        'value_adapter_delegate': (
            'pyemuera.runtime_queries.function' if name in QUERY_NAMES else None
        ),
        'same_as_public_route': (name in QUERY_NAMES and spec['handler'] == 'legacy'),
    }
