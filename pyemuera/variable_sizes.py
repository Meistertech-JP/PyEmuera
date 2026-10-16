"""Validate CSV resize requests before touching sizes or variable storage.

The closed target table reflects native VariableCode flags, not Python storage
rank: character identity fields and calculated values may have scalar backing
storage without being resizable arrays. Rejected rows never enter the changed
set, so later reconciliation sees only successfully accepted declarations.
"""

from importlib.resources import files
import json
import re
from .errors import LoadDiagnostic

_TARGETS = json.loads(
    files('pyemuera').joinpath('specs/variable_sizes.json').read_text(encoding='utf-8')
)['targets']


def _int32(text):
    if not re.fullmatch(r'[+-]?[0-9]+', text.strip()):
        return None
    # Avoid Python's long-string conversion limit; .NET TryParse rejects these.
    digits = text.strip().lstrip('+-').lstrip('0') or '0'
    if len(digits) > 10:
        return None
    value = (
        int(text.strip())
        if len(text.strip()) < 100
        else int(digits) * (-1 if text.strip().startswith('-') else 1)
    )
    return value if -(1 << 31) <= value < (1 << 31) else None


def parse_size_row(row, location, source_text, diagnostics):
    """Return (native name, dimensions), or None after ordered diagnostics.

    A negative first dimension bypasses all remaining dimension parsing when
    forbidding is allowed. Zero is a level-2 warning. Positive non-local 1D
    requests below 100 are rejected, retaining the *previous* accepted size;
    local and multi-dimensional arrays do not share that lower bound.
    """

    def warn(level, message):
        diagnostics.append(
            LoadDiagnostic(
                level,
                'CSV_VARIABLE_SIZE',
                location,
                source_text,
                message,
                len(diagnostics),
                phase='csv-load',
            )
        )

    if len(row) < 2:
        warn(1, '","が必要です')
        return None
    name = row[0].strip().upper()
    target = _TARGETS.get(name)
    if target is None:
        warn(1, '一つ目の値を変数名として認識できません')
        return None
    rank = target['rank']
    if not rank:
        warn(1, '配列変数でない変数' + name + 'のサイズを変更できません')
        return None
    if not target['changeable']:
        warn(1, name + 'のサイズは変更できません')
        return None
    first = _int32(row[1])
    if first is None:
        warn(1, '二つ目の値を整数値として認識できません')
        return None
    if first == 0:
        warn(
            2,
            '配列長に0は指定できません（変数を使用禁止にするには配列長に負の値を指定してください）',
        )
        return None
    if first < 0 and not target['forbid']:
        warn(2, '使用禁止にできない変数に対して負の配列長が指定されています')
        return None
    # Native extra-data warning occurs before positive size checks, and uses
    # only the first unnecessary token's leading decimal digit.
    used_rank = 1 if first < 0 else rank
    if first > 0 and len(row) < rank + 1:
        warn(
            1,
            ('二' if rank == 2 else '三')
            + '次元配列のサイズ指定には'
            + str(rank)
            + 'つの数値が必要です',
        )
        return None
    if len(row) > used_rank + 1 and row[used_rank + 1].strip()[:1].isdecimal():
        warn(
            0,
            ('一', '二', '三')[used_rank - 1]
            + '次元配列のサイズ指定に不必要なデータは無視されます',
        )
    if first < 0:
        return name, (-1,)
    if rank == 1:
        if not target['local'] and first < 100:
            warn(1, 'ローカル変数でない一次元配列のサイズを100未満にはできません')
            return None
        if first > 1000000:
            warn(1, '一次元配列のサイズを1000000より大きくすることはできません')
            return None
        return name, (first,)
    dimensions = [first]
    for axis in range(1, rank):
        value = _int32(row[axis + 1])
        if value is None:
            warn(1, ('三', '四')[axis - 1] + 'つ目の値を整数値として認識できません')
            return None
        dimensions.append(value)
    if any(value < 1 for value in dimensions):
        warn(1, '配列サイズを1未満にはできません')
        return None
    if any(value > 1000000 for value in dimensions):
        warn(1, '配列サイズを1000000より大きくすることはできません')
        return None
    # The native expression multiplies Int32 operands in unchecked context.
    product = 1
    for value in dimensions:
        product = ((product * value + (1 << 31)) % (1 << 32)) - (1 << 31)
    if product > (1000000 if rank == 2 else 10000000):
        warn(
            1,
            (
                '二次元配列の要素数は最大で100万個までです'
                if rank == 2
                else '三次元配列の要素数は最大で1000万個までです'
            ),
        )
        return None
    return name, tuple(dimensions)
