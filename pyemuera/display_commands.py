"""Display state transitions, separate from PRINT and terminal projection.

The declarative display family selects this closed handler. Background is a
console-wide state; foreground and font style belong to individual text runs.
"""

from .argument_counts import expect
from .errors import EraError
from .expr import integer


def _set_color(vm, op, value):
    if 'BG' in op:
        vm.console.set_background(value)
    else:
        vm.ui['color'] = value


def execute(vm, spec, arg):
    op = spec['name']
    console = vm.console
    console.warning(
        'style',
        'Text layout uses a logical cell grid; fonts and pixel positioning are not reproduced.',
    )
    if op in {'SETCOLOR', 'SETBGCOLOR'}:
        a = vm.args(arg)
        expect(a, 1, 3, op)
        if len(a) == 2:
            raise EraError(
                op
                + '命令:'
                + op
                + 'の引数の数が不正です('
                + op
                + 'の引数は1個もしくは3個です)',
                code='E_ARGUMENT',
            )
        for x in a:
            integer(x)
        if len(a) == 3 and any(x < 0 for x in a):
            raise EraError(op + 'の引数に0未満の値が指定されました', code='E_ARGUMENT')
        if len(a) == 3 and any(x > 255 for x in a):
            raise EraError(
                op + 'の引数に255を超える値が指定されました', code='E_ARGUMENT'
            )
        color = a[0] if len(a) == 1 else (a[0] << 16) + (a[1] << 8) + a[2]
        if not 0 <= color <= 0xFFFFFF:
            raise EraError('Invalid RGB color', code='E_ARGUMENT')
        _set_color(vm, op, color)
    elif op in {'SETCOLORBYNAME', 'SETBGCOLORBYNAME'}:
        from .display_contracts import color_name

        value = color_name(vm, op, arg)
        _set_color(vm, op, value)
    elif op in {'RESETCOLOR', 'RESETBGCOLOR'}:
        _set_color(vm, op, vm.default_background if 'BG' in op else 0xC0C0C0)
    elif op in {'FONTNAME', 'SETFONT'}:
        value = (
            vm.eval(arg) if arg else vm.data.config.get('フォント名', 'ＭＳ ゴシック')
        )
        if not isinstance(value, str):
            raise EraError('SETFONT needs a string', code='E_TYPE')
        vm.ui['font'] = value
    elif op == 'FONTSTYLE':
        vm.ui['style'] = integer(vm.eval(arg))
    elif op == 'FONTBOLD':
        vm.ui['style'] |= 1
    elif op == 'FONTITALIC':
        vm.ui['style'] |= 2
    elif op == 'FONTREGULAR':
        vm.ui['style'] = 0
    elif op == 'ALIGNMENT':
        value = arg.strip().upper()
        if not value:
            raise EraError('ALIGNMENT命令:引数が設定されていません', code='E_ARGUMENT')
        if value not in {'LEFT', 'CENTER', 'RIGHT'}:
            raise EraError(
                'ALIGNMENTのキーワード"' + value + '"は未定義です', code='E_ARGUMENT'
            )
        vm.ui['alignment'] = value
    elif op == 'REDRAW':
        vm.ui['redraw'] = integer(vm.eval(arg)) if arg.strip() else 0
        console.set_redraw(vm.ui['redraw'])
    elif op == 'FORCEKANA':
        value = integer(vm.eval(arg))
        if not 0 <= value <= 3:
            raise EraError('FORCEKANA requires 0..3', code='E_ARGUMENT')
        vm.ui['kana'] = value
    return True
