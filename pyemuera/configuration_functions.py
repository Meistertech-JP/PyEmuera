"""Read current configuration values using the existing expression contracts.

AST validation/evaluation and RESULT assignment belong to the callers. This
module reads live settings without caching, coercing string results, or changing
script state. Python failures propagate: builtins keeps SAVENOS outside its
value-handler exception translation and the other queries inside it.
"""

from __future__ import annotations

from .errors import EraError, Unsupported
from importlib.resources import files
import json

_CONFIG_NAMES = frozenset(
    json.loads(
        files('pyemuera')
        .joinpath('specs/config_names_v24.json')
        .read_text(encoding='utf-8')
    )['names']
)


# Aliases share the same configuration key, fallback and lower bound.
_PRINT_SETTINGS = {
    'GETPRINTCPERLINE': ('PRINTCを並べる数', '3'),
    'PRINTCPERLINE': ('PRINTCを並べる数', '3'),
    'GETPRINTCLENGTH': ('PRINTCの文字数', '25'),
    'PRINTCLENGTH': ('PRINTCの文字数', '25'),
}


def _named_value(vm, name: str, key: object) -> object:
    """Validate the exact key before accessing the configuration mapping.

    Missing values, including None, retain the existing unsupported-default
    diagnostic. String queries return the configured value unchanged. Numeric
    queries recognize flags before int conversion; do not introduce trimming.
    """
    if not isinstance(key, str):
        raise EraError('String required', code='E_TYPE')
    if key == '':
        raise EraError(name + '関数に空文字列が渡されました', code='E_ARGUMENT')
    from .config1824 import BY_NAME, boolean

    replace_values = {
        'MoneyFirst': ('単位の位置', 'money_first', False),
        'MoneyLabel': ('お金の単位', 'money_label', True),
        'LoadLabel': ('起動時簡略表示', 'load_label', True),
        'MaxShopItem': ('販売アイテム数', 'shop_limit', False),
        'DrawLineString': ('DRAWLINE文字', 'drawline', True),
        'TitleMenuString0': ('システムメニュー0', 'menu_new', True),
        'TitleMenuString1': ('システムメニュー1', 'menu_load', True),
        'BarChar1': ('BAR文字1', 'bar_full', True),
        'BarChar2': ('BAR文字2', 'bar_empty', True),
        'TimeupLabel': ('時間切れ表示', 'timeup_label', True),
        'ComAbleDefault': ('COM_ABLE初期値', 'com_able_default', False),
        'pbandDef': ('PBANDの初期値', 'pband', False),
        'RelationDef': ('RELATIONの初期値', 'relation', False),
    }
    replacement = next((v for k, v in replace_values.items() if key in (k, v[0])), None)
    row = BY_NAME.get(key)
    allowed = {
        'AutoSave',
        'WindowX',
        'PrintCPerLine',
        'PrintCLength',
        'FontSize',
        'LineHeight',
        'SaveDataNos',
        'ForeColor',
        'BackColor',
        'FocusColor',
        'LogColor',
        'FontName',
        'TextDrawingMode',
    }
    if replacement is not None:
        _, attribute, is_string = replacement
        result = getattr(vm.data.settings, attribute)
    elif row is not None:
        alias, canonical, kind, default = row
        if alias not in allowed:
            raise EraError(
                name
                + '関数:コンフィグ文字列"'
                + key
                + '"の値の取得は許可されていません',
                code='E_ARGUMENT',
            )
        value = vm.data.config.get(canonical, vm.data.config.get(alias, default))
        is_string = kind in ('string', 'TextDrawingMode')
        if is_string:
            result = value
        elif kind == 'bool':
            result = int(boolean(value))
        elif kind == 'Color':
            red, green, blue = (int(x) for x in value.split(',')[:3])
            result = (red * 256 + green) * 256 + blue
        else:
            result = int(value)
    else:
        result = None
    if replacement is not None or row is not None:
        if is_string != (name == 'GETCONFIGS'):
            other = 'GETCONFIGS' if is_string else 'GETCONFIG'
            raise EraError(
                name + '関数:型が違います（' + other + '関数を使用してください）',
                code='E_TYPE',
            )
        return result if is_string else int(result)
    value = vm.data.config.get(key)
    if value is None:
        if key not in _CONFIG_NAMES:
            raise EraError(
                name + '関数:文字列"' + key + '"は適切なコンフィグ名ではありません',
                code='E_ARGUMENT',
            )
        raise Unsupported(f'Config lookup without implemented default: {key}')
    if name == 'GETCONFIGS':
        return value
    if value.upper() in ('YES', 'TRUE'):
        return 1
    if value.upper() in ('NO', 'FALSE'):
        return 0
    return int(value)


def function(vm, name: str, values: list) -> object:
    """Dispatch only the owned, already-evaluated configuration queries.

    Bounded settings use their historical string fallback and int conversion.
    Do not catch their errors here: SAVENOS and other queries deliberately have
    different exception boundaries in builtins._call_with_values.
    """
    if name == 'SAVENOS':
        configured = int(vm.data.config.get('表示するセーブデータ数', '20'))
        return min(80, max(20, configured))
    if name in ('GETCONFIG', 'GETCONFIGS'):
        return _named_value(vm, name, values[0])
    setting = _PRINT_SETTINGS.get(name)
    if setting is not None:
        key, fallback = setting
        return max(1, int(vm.data.config.get(key, fallback)))
    raise Unsupported('Configuration expression function ' + name)
