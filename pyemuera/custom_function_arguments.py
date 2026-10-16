"""Closed v24 custom CheckArgumentType contracts, without value evaluation.

Creator.Method.cs remains the authority; these handlers preserve per-method
wording/descriptor constraints instead of treating every method as fixed arity.
"""

from .errors import EraError

CSV_NUMERIC = frozenset(
    'CSVABL CSVBASE CSVCFLAG CSVCSTR CSVEQUIP CSVEXP CSVJUEL CSVMARK CSVRELATION CSVTALENT'.split()
)
CSV_SCALAR = frozenset('CSVNAME CSVCALLNAME CSVNICKNAME CSVMASTERNAME'.split())
MATCH = frozenset(
    ('MATCH', 'CMATCH', 'FINDELEMENT', 'FINDLASTELEMENT', 'FINDCHARA', 'FINDLASTCHARA')
)
RANGE = frozenset(('INRANGEARRAY', 'INRANGECARRAY'))
BASE_FIXED = {
    'GETBIT': ('Int64', 'Int64'),
    'GETNUMB': ('string', 'string'),
    'GETEXPLV': ('Int64', 'Int64'),
    'GETPALAMLV': ('Int64', 'Int64'),
}
SUPPORTED = (
    CSV_NUMERIC
    | CSV_SCALAR
    | MATCH
    | RANGE
    | frozenset(BASE_FIXED)
    | {
        'ARRAYMSORT',
        'GETNUM',
        'SAVETEXT',
        'STRFIND',
        'STRFINDU',
        'MESSKIP',
        'MOUSESKIP',
    }
)


def fail(name, suffix, code='E_ARGUMENT'):
    raise EraError(name + '関数' + suffix, code=code)


def _collection_argument_bounds(name):
    """Preserve the first matching category, even if category sets overlap.

    Count-only checks occur before node/type/descriptor validation. Keep the
    separate minimum lookup and the scalar-first maximum lookup in r42 order.
    """
    minimum = 1 if name in CSV_SCALAR else 2
    if name in CSV_SCALAR:
        maximum = 2
    elif name in CSV_NUMERIC or name in ('STRFIND', 'STRFINDU'):
        maximum = 3
    elif name in RANGE:
        maximum = 6
    elif name in ('FINDELEMENT', 'FINDLASTELEMENT'):
        maximum = 5
    else:
        maximum = 4
    return minimum, maximum


def check_count(name, nodes):
    if name not in SUPPORTED:
        return
    n = len(nodes)
    if name in BASE_FIXED:
        if n != 2:
            fail(name, ':引数の数が間違っています')
        return
    if name == 'GETNUM':
        if n != 2:
            fail(name, 'には2つの引数が必要です')
        return
    if name in ('MESSKIP', 'MOUSESKIP'):
        if n:
            fail(name, 'の引数が多すぎます')
        return
    if name == 'ARRAYMSORT':
        # Creator.Method.cs:1958 intentionally has '2の', without a counter.
        # Preserve this source spelling rather than inserting '個' or 'つ'.
        if n < 2:
            fail(name, ':少なくとも2の引数が必要です')
        return
    if name == 'SAVETEXT':
        # Creator.Method.cs:4144 uses Resources.resx:160, whose format has '個'.
        # This distinct native wording must not be unified with ARRAYMSORT.
        if n < 2:
            fail(name, ':少なくとも2個の引数が必要です')
        if n > 4:
            fail(name, ':引数の数が多すぎます')
        return
    minimum, maximum = _collection_argument_bounds(name)
    if n < minimum:
        fail(name, 'には少なくとも' + str(minimum) + 'つの引数が必要です')
    if n > maximum:
        fail(name, 'の引数が多すぎます')


def _required(name, nodes, index, default=False):
    if nodes[index][0] == 'missing':
        fail(
            name,
            (
                (':第' + str(index + 1) + '引数は省略できません')
                if default
                else 'の' + str(index + 1) + '番目の引数は省略できません'
            ),
        )


def _type(name, actuals, index, expected, suffix=None):
    if actuals[index] is not None and actuals[index] != expected:
        fail(
            name,
            suffix or 'の' + str(index + 1) + '番目の引数の型が正しくありません',
            'E_TYPE',
        )


def _descriptor(context, node):
    return (
        context.descriptor(node[1])
        if context is not None and node[0] == 'var'
        else None
    )


def validate(name, actuals, nodes, context=None):
    if name not in SUPPORTED:
        return
    if name in BASE_FIXED:
        for i, expected in enumerate(BASE_FIXED[name]):
            _required(name, nodes, i, True)
            _type(
                name,
                actuals,
                i,
                expected,
                ':第' + str(i + 1) + '引数の型が間違っています',
            )
        if name == 'GETBIT' and nodes[1][0] == 'lit' and not 0 <= nodes[1][1] <= 63:
            # CheckArgumentType in Creator.Method.cs:1618 uses full-width
            # digits and U+FF5E, just like the separate runtime CodeEE.
            fail(
                name,
                'の第２引数(' + str(nodes[1][1]) + ')が範囲(０～６３)を超えています',
                'E_INDEX',
            )
        if (
            name == 'GETNUMB'
            and nodes[0][0] == 'lit'
            and context is not None
            and nodes[0][1].upper() not in context.types
        ):
            fail(name, 'の1番目の引数が変数名ではありません', 'E_REFERENCE')
        return
    if name in CSV_NUMERIC | CSV_SCALAR:
        required = 2 if name in CSV_NUMERIC else 1
        for i, node in enumerate(nodes):
            if i < required:
                _required(name, nodes, i)
            elif node[0] == 'missing':
                continue
            _type(
                name,
                actuals,
                i,
                'Int64',
                'の'
                + str(i + 1)
                + '番目の'
                + ('引数' if i == 0 else '変数')
                + 'が数値ではありません',
            )
        return
    if name in ('STRFIND', 'STRFINDU', 'SAVETEXT'):
        for i, node in enumerate(nodes):
            if name == 'SAVETEXT':
                _required(name, nodes, i, True)
                _type(
                    name,
                    actuals,
                    i,
                    'string' if i == 0 else 'Int64',
                    ':第' + str(i + 1) + '引数の型が間違っています',
                )
            else:
                if i < 2:
                    _required(name, nodes, i)
                elif node[0] == 'missing':
                    continue
                _type(name, actuals, i, 'string' if i < 2 else 'Int64')
        return
    if name in ('MESSKIP', 'MOUSESKIP'):
        return
    if name == 'ARRAYMSORT':
        for i, node in enumerate(nodes):
            prefix = ':' + str(i + 1) + '番目の引数'
            if node[0] == 'missing':
                fail(name, prefix + 'は省略できません')
            descriptor = _descriptor(context, node)
            if node[0] != 'var' or getattr(descriptor, 'readonly', False):
                fail(name, prefix + 'が変数ではありません', 'E_REFERENCE')
            if getattr(descriptor, 'character', False):
                fail(name, prefix + 'がキャラクタ変数です', 'E_TYPE')
            dims = getattr(descriptor, 'dims', None)
            if dims is not None:
                if i == 0 and len(dims) != 1:
                    fail(name, prefix + 'が一次元配列ではありません', 'E_TYPE')
                # Source repeats IsArray2D; 3D is deliberately rejected here.
                if len(dims) not in (1, 2):
                    fail(name, prefix + 'が配列変数ではありません', 'E_TYPE')
        return
    _required(name, nodes, 0)
    if nodes[0][0] != 'var':
        suffix = (
            'の1番目の引数の型が正しくありません'
            if name in ('GETNUM', 'FINDCHARA', 'FINDLASTCHARA')
            else 'の1番目の引数が変数ではありません'
        )
        fail(name, suffix, 'E_REFERENCE')
    descriptor = _descriptor(context, nodes[0])
    if name == 'GETNUM':
        _required(name, nodes, 1)
        _type(name, actuals, 1, 'string')
        return
    chara = name in ('CMATCH', 'FINDCHARA', 'FINDLASTCHARA', 'INRANGECARRAY')
    if chara and descriptor is not None and not getattr(descriptor, 'character', True):
        suffix = (
            'の1番目の引数の変数がキャラクタ変数ではありません'
            if name.startswith('FIND')
            else 'の1番目の引数がキャラクタ変数ではありません'
        )
        fail(name, suffix, 'E_TYPE')
    dims = getattr(descriptor, 'dims', None)
    if not chara and dims is not None and len(dims) > 1:
        fail(name, 'は二重配列・三重配列には対応していません', 'E_TYPE')
    if name in RANGE:
        _type(name, actuals, 0, 'Int64', 'の1番目の引数が数値型変数ではありません')
        # The source tests length<2 but subsequently indexes [2]. Keep the
        # established runtime arity guard for this malformed two-term case.
        for i in range(1, min(3, len(nodes))):
            _required(name, nodes, i)
            _type(
                name,
                actuals,
                i,
                'Int64',
                'の' + str(i + 1) + '番目の引数が数値型ではありません',
            )
        start = 3
    else:
        _required(name, nodes, 1)
        suffix = (
            'の1番目の引数と2番目の引数の型が異なります'
            if name in ('MATCH', 'CMATCH')
            else None
        )
        _type(name, actuals, 1, actuals[0], suffix)
        start = 2
    for i in range(start, len(nodes)):
        if nodes[i][0] != 'missing':
            _type(name, actuals, i, 'Int64')
