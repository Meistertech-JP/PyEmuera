"""Small raw-argument contracts from ArgumentBuilder.STR/INT_NULLABLE."""

from .errors import EraError


def color_name(vm, op, arg):
    from .compat1824 import call

    # STR builder keeps quotation marks and trailing spaces.
    if not arg:
        raise EraError('引数が設定されていません', code='E_ARGUMENT')
    if arg.casefold() == 'transparent':
        raise EraError(
            '無色透明(Transparent)は色として指定できません', code='E_ARGUMENT'
        )
    value = call(vm, 'COLOR_FROMNAME', [('lit', arg)])
    if value < 0:
        raise EraError('指定された色名"' + arg + '"は無効な色名です', code='E_ARGUMENT')
    return value
