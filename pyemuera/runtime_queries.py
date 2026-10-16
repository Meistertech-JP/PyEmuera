"""Read live runtime state and clocks from already-evaluated values.

AST validation/evaluation, RESULT writes and Python-error translation belong to
builtins/commands. This module neither caches state nor changes script variables.
The caller passes its live datetime module so existing clock seams are retained;
dispatch does not sample a clock or merge successive reads.
"""

from .expr import integer
from .errors import EraError, Unsupported

NAMES = frozenset(
    (
        'BARSTR',
        'CURRENTALIGN',
        'CURRENTREDRAW',
        'EXISTFUNCTION',
        'EXISTVAR',
        'GETBGCOLOR',
        'GETCOLOR',
        'GETDEFBGCOLOR',
        'GETDEFCOLOR',
        'GETEXPLV',
        'GETFONT',
        'GETLINESTR',
        'GETMILLISECOND',
        'GETPALAMLV',
        'GETSECOND',
        'GETTIME',
        'ISDEFINED',
        'LINEISEMPTY',
        'MONEYSTR',
    )
)


def _string(value):
    if not isinstance(value, str):
        raise EraError('String required', code='E_TYPE')
    return value


def function(vm, name, a, clock_module):
    """Read existence/level/display/formatting state or one requested clock.

    EXISTVAR absorbs the same EraError classes as before. Level bounds are
    converted before table lookup. BARSTR validates maximum, then length. Clock
    functions each sample now() once, retaining the original epoch arithmetic.
    Python failures escape to the caller's existing value-handler try block.
    CURRENTALIGN/GETLINESTR here are value-adapter fallbacks; their public AST
    routes remain owned by compat1824 and must not be replaced by this handler.
    """
    if name == 'EXISTFUNCTION':
        return int(_string(a[0]).upper() in vm.program.functions)
    if name == 'ISDEFINED':
        return int(_string(a[0]).upper() in vm.program.macros)
    if name == 'EXISTVAR':
        try:
            vm.lookup(_string(a[0]).upper())
            return 1
        except EraError:
            return 0
    if name in ('GETPALAMLV', 'GETEXPLV'):
        v = integer(a[0])
        maxlevel = integer(a[1])
        table = vm.data.variables['PALAMLV' if name == 'GETPALAMLV' else 'EXPLV']
        return max(
            (
                i
                for i in range(min(maxlevel + 1, table.dims[0]))
                if v >= table.get((i,))
            ),
            default=0,
        )
    if name == 'GETTIME':
        return numeric_time(clock_module)
    if name in ('GETMILLISECOND', 'GETSECOND'):
        delta = clock_module.datetime.now() - clock_module.datetime(1, 1, 1)
        return int(delta.total_seconds() * (1000 if name == 'GETMILLISECOND' else 1))
    if name in ('GETCOLOR', 'GETBGCOLOR', 'GETDEFCOLOR', 'GETDEFBGCOLOR'):
        return (
            vm.ui['bgcolor' if 'BG' in name else 'color']
            if 'DEF' not in name
            else (0 if 'BG' in name else 0xC0C0C0)
        )
    if name == 'GETFONT':
        return vm.ui['font']
    if name == 'CURRENTALIGN':
        return {'LEFT': 0, 'CENTER': 1, 'RIGHT': 2}.get(vm.ui['alignment'], 0)
    if name == 'CURRENTREDRAW':
        return vm.ui['redraw']
    if name == 'LINEISEMPTY':
        return int(not vm.console.current)
    if name == 'GETLINESTR':
        return vm.console.last_line(integer(a[0]) if a else 0)
    if name == 'MONEYSTR':
        from .string_conversions import _integer_text

        return vm.data.settings.money(_integer_text(a, name='MONEYSTR'))
    if name == 'BARSTR':
        val, maximum, length = map(integer, a[:3])
        if maximum <= 0:
            raise EraError('BARの最大値が正の値ではありません', code='E_ARGUMENT')
        if length <= 0:
            raise EraError('BARの長さが正の値ではありません', code='E_ARGUMENT')
        if length >= 100:
            raise EraError('BARが長すぎます', code='E_ARGUMENT')
        filled = max(0, min(length, val * length // maximum))
        return (
            '['
            + vm.data.settings.bar_full * filled
            + vm.data.settings.bar_empty * (length - filled)
            + ']'
        )
    raise Unsupported('Runtime query expression function ' + name)


def numeric_time(clock_module):
    """GETTIME's seven DateTime.Now reads, including torn boundary values."""
    now = clock_module.datetime.now
    value = now().year
    for component in ('month', 'day', 'hour', 'minute', 'second'):
        value = value * 100 + getattr(now(), component)
    return value * 1000 + now().microsecond // 1000
