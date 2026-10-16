"""Non-executing, conservative Restructure over the shared immutable AST.

Only literal operators and explicitly bound pure adapters are reduced. No VM
evaluate/call_expr, variable reads, RNG, scope, REF or user function execution.
Children are restructured before their parent, including short-circuit arms.
Uncovered CanRestructure/UniqueRestructure contracts stay runtime expressions.
"""

from .expr import apply_binary, integer, i64
from .errors import EraError


def _unary(op, value):
    value = integer(value)
    return {
        '+': lambda: value,
        '-': lambda: i64(-value),
        '!': lambda: int(not value),
        '~': lambda: i64(~value),
    }[op]()


def _power(args):
    from .numeric_instructions import power_value

    return power_value(*args)


def _tostr(args):
    from .string_conversions import _integer_text

    return _integer_text(args)


def _scalar(name):
    def reduce(args):
        from .scalar_numeric import function

        return function(name, args)

    return reduce


# Creator.Method.cs marks these value-only adapters CanRestructure=true.
# Configuration, arrays/references, RAND, clocks and user methods are excluded.
PURE_METHODS = {'POWER': _power}
FORM_METHODS = {
    **PURE_METHODS,
    'TOSTR': _tostr,
    **{
        name: _scalar(name)
        for name in ('ABS', 'SIGN', 'MAX', 'MIN', 'LIMIT', 'INRANGE', 'GETBIT')
    },
}


class Reducer:
    def __init__(
        self, user_methods=(), warning=None, *, methods=None, constant_resolver=None
    ):
        self.user_methods = user_methods
        self.warning = warning
        self.methods = PURE_METHODS if methods is None else methods
        self.constant_resolver = constant_resolver
        self.coverage = []

    def reduce(self, node):
        handler = REDUCERS.get(node[0], _unchanged)
        result = handler(self, node)
        self.coverage.append(
            {
                'kind': node[0],
                'category': (
                    'constant_expression'
                    if result[0] == 'lit'
                    else 'runtime_expression'
                ),
                'safe_reduction': result != node,
            }
        )
        return result

    def arguments(self, name, nodes):
        """Source UniqueRestructure exceptions for descriptor operands."""
        skip_first = name in ('GETNUM', 'STRJOIN')
        retain_first = name in (
            'MATCH',
            'CMATCH',
            'FINDELEMENT',
            'FINDLASTELEMENT',
            'STRFORM',
        )
        args = []
        for i, node in enumerate(nodes):
            if i == 0 and skip_first:
                args.append(node)
                continue
            reduced = self.reduce(node)
            args.append(node if i == 0 and retain_first else reduced)
        return tuple(args)


def _unchanged(reducer, node):
    return node


def _variable(reducer, node):
    result = ('var', node[1], tuple(reducer.reduce(x) for x in node[2]))
    if reducer.constant_resolver is not None:
        literal = reducer.constant_resolver(result)
        if literal is not None:
            return literal
    return result


def _call(reducer, node):
    from collections.abc import Mapping
    from .function_resolution import expression_user_method

    selected_user = (
        expression_user_method(reducer.user_methods, node[1]) is not None
        if isinstance(reducer.user_methods, Mapping)
        else node[1] in reducer.user_methods
    )
    special = getattr(reducer.constant_resolver, 'call', None)
    if special is not None and not selected_user:
        literal = special(node, reducer)
        if literal is not None:
            return literal
    args = (
        tuple(reducer.reduce(x) for x in node[2])
        if selected_user
        else reducer.arguments(node[1], node[2])
    )
    method = reducer.methods.get(node[1]) if not selected_user else None
    fold_args = args
    if method is _tostr and len(args) == 2 and args[1][0] == 'missing':
        # ToStrMethod permits a null second (format) operand. This exception is
        # confined to the explicitly selected FORM adapter, not default Reducer
        # or arbitrary pure-method signatures; the required value still binds.
        fold_args = args[:1]
    if method is not None and all(x[0] == 'lit' for x in fold_args):
        from .expression_arguments import validate_literals

        validate_literals(node[1], args)
        return ('lit', method([x[1] for x in fold_args]))
    return ('call', node[1], args)


def _binary(reducer, node):
    left, right = reducer.reduce(node[2]), reducer.reduce(node[3])
    if left[0] == right[0] == 'lit':
        try:
            return ('lit', apply_binary(node[1], left[1], right[1]))
        except EraError as exc:
            if node[1] in ('/', '%') and right[1] == 0:
                raise EraError('0による除算が行なわれました', code='E_ARITH') from exc
            raise
    return ('binary', node[1], left, right)


def _prefix(reducer, node):
    child = reducer.reduce(node[2])
    if child[0] == 'lit':
        if node[1] == '-' and child[1] == -(1 << 63):
            # This warning is printed by MinusInt, not an ArgumentParser error.
            # Preserve the runtime route until its load-console contract is run.
            return ('unary', node[1], child)
        return ('lit', _unary(node[1], child[1]))
    return ('unary', node[1], child)


def _ternary(reducer, node):
    children = tuple(reducer.reduce(x) for x in node[1:])
    if all(x[0] == 'lit' for x in children):
        return children[1] if integer(children[0][1]) else children[2]
    return ('ternary',) + children


def _increment(reducer, node):
    return ('inc', reducer.reduce(node[1]), node[2], node[3])


REDUCERS = {
    'lit': _unchanged,
    'missing': _unchanged,
    'form': _unchanged,
    'var': _variable,
    'inc': _increment,
    'call': _call,
    'binary': _binary,
    'unary': _prefix,
    'ternary': _ternary,
}


# Creator.Method.cs CanRestructure=true registrations. Array references and
# STRFORM have additional checks below; mutable operands never pass this gate.
LOAD_CONSTANT_METHODS = frozenset(
    """ABS BARSTR CBRT CHARATU CHKFONT COLOR_FROMNAME
COLOR_FROMRGB CONVERT CSVABL CSVBASE CSVCALLNAME CSVCFLAG CSVCSTR CSVEQUIP CSVEXP
CSVJUEL CSVMARK CSVMASTERNAME CSVNAME CSVNICKNAME CSVRELATION CSVTALENT ENCODETOUNI
ESCAPE EXISTCSV EXPONENT FINDELEMENT FINDLASTELEMENT GETBIT GETCONFIG GETCONFIGS
GETDEFCOLOR GETDEFBGCOLOR GETFOCUSCOLOR GETLINESTR GETNUM GETNUMB INRANGE ISNUMERIC
LIMIT LOG LOG10 MAX MIN MONEYSTR POWER PRINTCLENGTH PRINTCPERLINE REPLACE SAVENOS
SIGN SQRT STRCOUNT STRFIND STRFINDU STRFORM STRJOIN STRLENS STRLENSU SUBSTRING
SUBSTRINGU TOFULL TOHALF TOINT TOLOWER TOSTR TOUPPER UNICODE UNICODEBYTE VARSIZE""".split()
)
