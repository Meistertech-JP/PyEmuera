"""VariableEvaluator status display (854-1032); projection stays in Console."""

from .errors import EraError
from .expr import integer, i64
from .text import split_args


def execute(vm, op, arg):
    con = vm.console
    if con.skip_print:
        return True
    if op == 'PRINT_ITEM':
        items = vm.data.variables['ITEM']
        names = vm.data.variables['ITEMNAME']
        rows = [
            str(names.get((i,))) + '(' + str(items.get((i,))) + ') '
            for i in range(min(items.dims[0], names.dims[0]))
            if items.get((i,))
        ]
        con.write('所持アイテム：' + (''.join(rows) if rows else 'なし'), True)
        return True
    parts = split_args(arg) if arg.strip() else []
    if len(parts) > 1:
        raise EraError('引数が多すぎます', code='E_ARGUMENT')
    c = integer(vm.eval(parts[0])) if parts else 0
    if not 0 <= c < vm.data.character_count:
        raise EraError(
            '存在しない登録キャラクタを参照しようとしました', code='E_CHARACTER'
        )
    kind = op[6:]
    var = vm.data.variables[kind]
    names = vm.data.variables[kind + 'NAME']
    rows = []
    for i in range(
        min(var.dims[0], names.dims[0], 100 if kind == 'PALAM' else var.dims[0])
    ):
        n = names.get((i,))
        v = var.get((c, i))
        if kind == 'PALAM':
            if not v and not n:
                continue
            lv = vm.data.variables['PALAMLV']
            border = lv.get((1,))
            ch = '-'
            for j, k in [(2, '='), (3, '>'), (4, '*')]:
                if v >= border:
                    ch = k
                    border = lv.get((j,))
            count = (
                10
                if border <= 0 or border <= v
                else 0 if v <= 0 else int(i64(v * 10) / border)
            )
            from .printing import column_text

            rows.append(
                column_text(
                    vm,
                    str(n)
                    + '['
                    + ch * count
                    + '.' * (10 - count)
                    + ']'
                    + str(v).rjust(6),
                    'right',
                )
            )
        elif n and v:
            rows.append(
                '[' + n + ']'
                if kind == 'TALENT'
                else n + ('LV' if kind in ('ABL', 'MARK') else '') + str(v) + ' '
            )
    if kind == 'PALAM':
        columns = int(vm.data.config.get('PRINTCを並べる数', '3'))
        for j, t in enumerate(rows):
            con.write(t, (columns > 0 and (j + 1) % columns == 0) or j == len(rows) - 1)
    else:
        con.write(''.join(rows), True)
    return True


def execute_spec(vm, spec, arg):
    return execute(vm, spec['name'], arg)
