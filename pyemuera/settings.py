"""Supported _replace.csv settings, parsed before character creation.

Unknown keys are ignored, as ConfigData.LoadReplaceFile ignores unknown items.
Defaults follow the documented base Emuera settings; no upstream code is bundled.
"""

from __future__ import annotations
from dataclasses import dataclass
from .source_lines import source_lines

DEFAULT_EXPLV = (0, 1, 4, 20, 50, 200)
DEFAULT_PALAMLV = (0, 100, 500, 3000, 10000, 30000, 60000, 100000, 150000, 250000)


@dataclass(frozen=True)
class Settings:
    load_label: str = 'Now Loading...'
    money_label: str = '$'
    money_first: bool = True
    shop_limit: int = 100
    drawline: str = '-'
    bar_full: str = '*'
    bar_empty: str = '.'
    menu_new: str = '最初からはじめる'
    menu_load: str = 'ロードしてはじめる'
    timeup_label: str = '時間切れ'
    com_able_default: int = 1
    stain: tuple[int, ...] = (0, 0, 2, 1, 8)
    explv: tuple[int, ...] = DEFAULT_EXPLV
    palamlv: tuple[int, ...] = DEFAULT_PALAMLV
    pband: int = 4
    relation: int = 0

    def money(self, value: int) -> str:
        return (
            self.money_label + str(value)
            if self.money_first
            else str(value) + self.money_label
        )

    @classmethod
    def from_rows(cls, rows: dict[str, str], warnings: list[str]) -> 'Settings':
        return cls._parse(list(rows.items()), warnings)

    @classmethod
    def from_texts(cls, texts, warnings, replacements=None):
        """LoadReplaceFile stops the current file, preserving prior writes."""
        import re

        settings = cls()
        for source, text in texts:
            rows = []
            for lineno, line in enumerate(source_lines(text), 1):
                if not line.strip() or line.lstrip().startswith(';'):
                    continue
                parts = re.split('[,:]', line, maxsplit=1)
                if len(parts) == 2:
                    rows.append((parts[0].strip(), parts[1], lineno))
            settings = cls._parse(rows, warnings, settings, source, replacements)
        return settings

    @classmethod
    def _parse(
        cls, rows, warnings, base=None, source='_replace.csv', replacements=None
    ):
        from dataclasses import asdict
        from .config1824 import boolean, number

        fields = {
            'LoadLabel': ('load_label', 'text'),
            '起動時簡略表示': ('load_label', 'text'),
            'MoneyLabel': ('money_label', 'text'),
            'お金の単位': ('money_label', 'text'),
            'MoneyFirst': ('money_first', 'position'),
            '単位の位置': ('money_first', 'position'),
            'MaxShopItem': ('shop_limit', 'int32'),
            '販売アイテム数': ('shop_limit', 'int32'),
            'DrawLineString': ('drawline', 'text'),
            'DRAWLINE文字': ('drawline', 'text'),
            'BarChar1': ('bar_full', 'char'),
            'BAR文字1': ('bar_full', 'char'),
            'BarChar2': ('bar_empty', 'char'),
            'BAR文字2': ('bar_empty', 'char'),
            'TitleMenuString0': ('menu_new', 'text'),
            'システムメニュー0': ('menu_new', 'text'),
            'TitleMenuString1': ('menu_load', 'text'),
            'システムメニュー1': ('menu_load', 'text'),
            'TimeupLabel': ('timeup_label', 'text'),
            '時間切れ表示': ('timeup_label', 'text'),
            'ComAbleDefault': ('com_able_default', 'int32'),
            'COM_ABLE初期値': ('com_able_default', 'int32'),
            'StainDefault': ('stain', 'array'),
            '汚れの初期値': ('stain', 'array'),
            'ExpLvDef': ('explv', 'array'),
            'EXPLVの初期値': ('explv', 'array'),
            'PalamLvDef': ('palamlv', 'array'),
            'PALAMLVの初期値': ('palamlv', 'array'),
            'pbandDef': ('pband', 'integer'),
            'PBANDの初期値': ('pband', 'integer'),
            'RelationDef': ('relation', 'integer'),
            'RELATIONの初期値': ('relation', 'integer'),
        }
        values = asdict(base or cls())
        for row in rows:
            key, raw = row[:2]
            lineno = row[2] if len(row) > 2 else None
            if key not in fields or not raw.strip():
                continue
            name, kind = fields[key]
            text = raw.strip()
            try:
                if kind == 'text':
                    value = text
                elif kind == 'char':
                    if len(text.encode('utf-16-le', errors='surrogatepass')) != 2:
                        continue
                    value = text
                elif kind == 'position':
                    value = boolean(text)
                elif kind == 'array':
                    # The native list is cleared first and populated in place.
                    prefix = []
                    values[name] = ()
                    for part in text.split('/'):
                        prefix.append(number(part, 64))
                        values[name] = tuple(prefix)
                    value = tuple(prefix)
                else:
                    value = number(text, 32 if kind == 'int32' else 64)
            except ValueError as exc:
                warnings.append(
                    f'{source}' + (f':{lineno}' if lineno else '') + f': {exc}'
                )
                break
            values[name] = value
            if replacements is not None:
                replacements[key] = text
        return cls(**values)
