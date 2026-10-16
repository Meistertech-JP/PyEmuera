"""Sparse, typed ERB variables and legacy CSV metadata loading."""

from __future__ import annotations
from dataclasses import dataclass, field, replace
from itertools import product
from pathlib import Path
import copy
import re
from .errors import EraError, Location
from .expr import i64
from .text import read_text, load_config
from .source_lines import source_lines
from .registry import VARIABLE_SPECS
from .settings import Settings, DEFAULT_EXPLV, DEFAULT_PALAMLV


@dataclass
class Variable:
    name: str
    dims: tuple[int, ...] = (1,)
    string: bool = False
    character: bool = False
    readonly: bool = False
    saved: bool = False
    global_save: bool = False
    forbidden: bool = False
    default: int | str = 0
    values: dict[tuple[int, ...], int | str] = field(default_factory=dict)

    write_observer: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self.string and self.default == 0:
            self.default = ''

    def index_diagnostic(self, position, index):
        """VariableToken.CheckElement wording depends on its native subtype."""
        if position >= 3:
            return None
        if self.character:
            return (
                'キャラクタ配列変数'
                + self.name
                + 'の第'
                + ('１', '２', '３')[position]
                + f'引数({index})は'
                + ('キャラ登録番号' if position == 0 else '配列')
                + 'の範囲外です'
            )
        # Built-in and legacy 1D tokens use 配列変数; declared DIM/DIMS tokens
        # inherit UserDefinedVariableToken, whose wording is 配列型変数.
        builtin = (
            self.name in NUM_GLOBAL
            or self.name in CAN_FORBID
            or self.name in ('LOCAL', 'LOCALS', 'ARG', 'ARGS')
        )
        prefix = '配列変数' if len(self.dims) == 1 and builtin else '配列型変数'
        return (
            prefix
            + self.name
            + 'の第'
            + ('１', '２', '３')[position]
            + f'引数({index})は配列の範囲外です'
        )

    def validate(self, key: tuple[int, ...]):
        # Fast successful ranks keep the exact slow error path and diagnostics.
        rank = len(self.dims)
        if not self.character:
            if (
                rank == 1
                and len(key) == 1
                and isinstance(key[0], int)
                and 0 <= key[0] < self.dims[0]
            ):
                return
            if (
                rank == 2
                and len(key) == 2
                and isinstance(key[0], int)
                and isinstance(key[1], int)
                and 0 <= key[0] < self.dims[0]
                and 0 <= key[1] < self.dims[1]
            ):
                return
        elif (
            rank == 1
            and len(key) == 2
            and isinstance(key[0], int)
            and key[0] >= 0
            and isinstance(key[1], int)
            and 0 <= key[1] < self.dims[0]
        ):
            return
        dims = (None,) + self.dims if self.character else self.dims
        if len(key) != len(dims):
            raise EraError(
                f"{self.name}: expected {len(dims)} indices, got {len(key)}",
                code='E_INDEX',
            )
        for position, (idx, size) in enumerate(zip(key, dims)):
            if (
                not isinstance(idx, int)
                or idx < 0
                or (size is not None and idx >= size)
            ):
                diagnostic = None
                if isinstance(idx, int):
                    diagnostic = self.index_diagnostic(position, idx)
                raise EraError(
                    f"{self.name}{key}: array index outside {dims}",
                    code='E_INDEX',
                    diagnostic_message=diagnostic,
                )

    def get(self, key):
        self.validate(key)
        return self.values.get(tuple(key), self.default)

    def set(self, key, value, internal=False):
        self.validate(key)
        if self.readonly and not internal:
            raise EraError(f"{self.name} is read-only", code='E_READONLY')
        if self.string != isinstance(value, str):
            raise EraError(
                f"{self.name}: expected {'string' if self.string else 'integer'}",
                code='E_TYPE',
            )
        value = value if self.string else i64(value)
        key = tuple(key)
        observer = self.write_observer
        if observer is not None:
            old = self.values.get(key, self.default)
        if value == self.default:
            self.values.pop(key, None)
        else:
            self.values[key] = value
        if observer is not None:
            observer(self, key, old, value)


@dataclass
class Ref:
    variable: Variable
    key: tuple[int, ...]

    def get(self):
        return self.variable.get(self.key)

    def set(self, value):
        self.variable.set(self.key, value)

    def shifted(self, n: int):
        if not self.key:
            raise EraError('Scalar reference cannot be shifted', code='E_INDEX')
        return Ref(self.variable, self.key[:-1] + (self.key[-1] + n,))

    def size(self):
        return self.variable.dims[-1] if self.variable.dims else 1


# Defaults of the base language, not unlimited auto-created names.
NUM_GLOBAL = {
    **{chr(c): 1000 for c in range(ord('A'), ord('Z') + 1)},
    'FLAG': 10000,
    'TFLAG': 1000,
    'ITEM': 1000,
    'ITEMSALES': 1000,
    'UP': 100,
    'DOWN': 100,
    'LOSEBASE': 100,
    'PALAMLV': 100,
    'EXPLV': 100,
    'RESULT': 100,
    'COUNT': 1,
    'MONEY': 1,
    'DAY': 1,
    'TIME': 1,
    'TARGET': 1,
    'MASTER': 1,
    'ASSI': 1,
    'PLAYER': 1,
    'ASSIPLAY': 1,
    'PREVCOM': 1,
    'NEXTCOM': 1,
    'SELECTCOM': 1000,
    'BOUGHT': 1,
    'NOITEM': 1,
    'PBAND': 1,
    'LASTLOAD_VERSION': 1,
    'LASTLOAD_NO': 1,
    'GLOBAL': 1000,
    'RANDDATA': 625,
    'SAVESTR': 100,
    'TSTR': 100,
    'RESULTS': 100,
    'STR': 20000,
    'GLOBALS': 100,
    'WINDOW_TITLE': 1,
}
NUM_GLOBAL.update(
    {
        'EJAC': 1000,
        **{
            n: 1000
            for n in (
                'NOTUSE_14',
                'NOTUSE_15',
                'NOTUSE_1C',
                'NOTUSE_1D',
                'NOTUSE_38',
                'NOTUSE_39',
                'NOTUSE_3A',
                'NOTUSE_3B',
            )
        },
    }
)
STR_GLOBAL = {
    'STR',
    'TSTR',
    'SAVESTR',
    'RESULTS',
    'GLOBALS',
    'WINDOW_TITLE',
    'LASTLOAD_TEXT',
    'SAVEDATA_TEXT',
}
NUM_CHAR = {
    'BASE': 100,
    'MAXBASE': 100,
    'ABL': 100,
    'TALENT': 1000,
    'MARK': 100,
    'EXP': 100,
    'PALAM': 100,
    'SOURCE': 100,
    'EX': 100,
    'NOWEX': 100,
    'JUEL': 100,
    'GOTJUEL': 100,
    'CFLAG': 1000,
    'EQUIP': 100,
    'TEQUIP': 100,
    'STAIN': 1000,
    'RELATION': 1000,
    'CUP': 100,
    'CDOWN': 100,
    'DOWNBASE': 100,
    'TCVAR': 100,
    'CSTR': 100,
}
CHAR_SCALARS = {
    'NAME': True,
    'CALLNAME': True,
    'NICKNAME': True,
    'MASTERNAME': True,
    'NO': False,
    'ISASSI': False,
}
CSV_ALIASES = {
    'MAXBASE': 'BASE',
    'UP': 'PALAM',
    'DOWN': 'PALAM',
    'JUEL': 'PALAM',
    'GOTJUEL': 'PALAM',
    'CUP': 'PALAM',
    'CDOWN': 'PALAM',
    'NOWEX': 'EX',
    'LOSEBASE': 'BASE',
    'DOWNBASE': 'BASE',
    'ITEMSALES': 'ITEM',
    'ITEMPRICE': 'ITEM',
}
CHAR_KEYS = {
    '番号': 'NO',
    '名前': 'NAME',
    '呼び名': 'CALLNAME',
    'あだ名': 'NICKNAME',
    '主人の呼び方': 'MASTERNAME',
    '基礎': 'BASE',
    '能力': 'ABL',
    '素質': 'TALENT',
    '刻印': 'MARK',
    '経験': 'EXP',
    '珠': 'JUEL',
    '装着物': 'EQUIP',
    '相性': 'RELATION',
    'フラグ': 'CFLAG',
    '汚れ': 'STAIN',
}

# Built-ins whose VariableCode carries __CAN_FORBID__ in Emuera 1824.
# VariableSize.csv uses a negative first dimension to mark these unavailable.
CAN_FORBID = {
    'DAY',
    'MONEY',
    'ITEM',
    'FLAG',
    'TFLAG',
    'UP',
    'EJAC',
    'DOWN',
    'ASSI',
    'MASTER',
    'NOITEM',
    'LOSEBASE',
    'ASSIPLAY',
    'PREVCOM',
    'NOTUSE_14',
    'NOTUSE_15',
    'TIME',
    'ITEMSALES',
    'PLAYER',
    'NEXTCOM',
    'PBAND',
    'BOUGHT',
    *map(chr, range(ord('A'), ord('Z') + 1)),
    'ITEMPRICE',
    'LOCAL',
    'ARG',
    'GLOBAL',
    'SAVESTR',
    'STR',
    'LOCALS',
    'ARGS',
    'GLOBALS',
    'TSTR',
    'BASE',
    'MAXBASE',
    'ABL',
    'TALENT',
    'EXP',
    'MARK',
    'PALAM',
    'SOURCE',
    'EX',
    'CFLAG',
    'JUEL',
    'RELATION',
    'EQUIP',
    'TEQUIP',
    'GOTJUEL',
    'NOWEX',
    'DOWNBASE',
    'CUP',
    'CDOWN',
    'TCVAR',
    'CSTR',
    'CDFLAG',
    'DITEMTYPE',
    'DA',
    'DB',
    'DC',
    'DD',
    'DE',
    'TA',
    'TB',
    'ABLNAME',
    'EXPNAME',
    'TALENTNAME',
    'PALAMNAME',
    'TRAINNAME',
    'MARKNAME',
    'ITEMNAME',
    'BASENAME',
    'SOURCENAME',
    'EXNAME',
    'EQUIPNAME',
    'TEQUIPNAME',
    'FLAGNAME',
    'TFLAGNAME',
    'CFLAGNAME',
    'TCVARNAME',
    'CSTRNAME',
    'STAINNAME',
    'CDFLAGNAME1',
    'CDFLAGNAME2',
    'STRNAME',
    'TSTRNAME',
    'SAVESTRNAME',
    'GLOBALNAME',
    'GLOBALSNAME',
}

BASE_KEYS = {
    '作者': 'AUTHOR',
    '追加情報': 'INFO',
    '製作年': 'YEAR',
    'タイトル': 'TITLE',
    'コード': 'GAMECODE',
    'バージョン': 'VERSION',
    'バージョン違い認める': 'ALLOWVERSION',
    '最初からいるキャラ': 'DEFAULTCHARA',
    'アイテムなし': 'NOITEM',
    'ウィンドウタイトル': 'WINDOW_TITLE',
}


def gamebase_integer(text: str) -> tuple[bool, int]:
    """GameBase.tryatoi: Int64.TryParse, then a leading numeric run only.

    No float conversion, scaling or wrapping. A sign followed by a suffix is NOT
    a valid fallback. Unicode numeric runs cannot be parsed as .NET Int64.
    """

    def parsed(s):
        if not re.fullmatch(r'[+-]?[0-9]+', s):
            return None
        n = int(s) if len(s) < 64 else 1 << 64
        return n if -(1 << 63) <= n < (1 << 63) else None

    n = parsed(text.strip())
    if n is not None:
        return True, n
    end = 0
    import unicodedata

    while end < len(text) and unicodedata.category(text[end]).startswith('N'):
        end += 1
    n = parsed(text[:end]) if end else None
    return (True, n) if n is not None else (False, 0)


def character_csv_integer(text: str) -> tuple[bool, int]:
    """ConstantData.tryToInt64 / LexicalAnalyzer.ReadInt64 prefix contract.

    Unlike GameBase.tryatoi, signed/hex/binary prefixes are accepted, but an
    absent/overflowing numeric token is invalid. Callers supply default 1.
    """
    sign = 1
    if text.startswith(('+', '-')):
        sign = -1 if text[0] == '-' else 1
        text = text[1:]
    if not text or text[0] not in '0123456789':
        return False, 0
    base = 10
    if text[:2].lower() in ('0x', '0b'):
        base = 16 if text[1].lower() == 'x' else 2
        text = text[2:]
    digits = '0123456789abcdefABCDEF' if base == 16 else '0123456789'
    match = re.match('[+-]?[' + digits + ']+', text)
    if not match:
        return False, 0
    token = match[0]
    tail = text[match.end() :]
    if tail and tail[0].isdigit():
        return False, 0
    try:
        value = int(token, base)
        if base == 10:
            if not -(1 << 63) <= value < (1 << 63):
                return False, 0
        else:
            if not 0 <= value < 1 << 64:
                return False, 0
            value = i64(value)
        if tail.startswith(('p', 'P', 'e', 'E')):
            exponent = re.match('[+-]?[' + digits + ']+', tail[1:])
            if not exponent:
                return False, 0
            power = int(exponent[0], base)
            if not -(1 << 63) <= power < (1 << 63):
                return False, 0
            power = ((power + (1 << 31)) % (1 << 32)) - (1 << 31)
            if power:
                import math

                scaled = float(value) * math.pow(
                    2 if tail[0].lower() == 'p' else 10, power
                )
                if not math.isfinite(scaled) or not -(1 << 63) <= scaled < (1 << 63):
                    return False, 0
                value = int(scaled)
        return True, i64(sign * value)
    except (ValueError, OverflowError):
        return False, 0


def _callname_config_bool(raw_value: str) -> bool:
    """Native ConfigItem<bool> parsing for this one compatibility option.

    Decimal input is limited to signed Int32; Python's larger integers, hex,
    underscores and Unicode decimal digits must not silently enable it.
    """
    value = raw_value.strip()
    if re.fullmatch(r'[+-]?[0-9]+', value):
        number = int(value)
        if -(1 << 31) <= number < (1 << 31):
            return number != 0
    if value.upper() in {'YES', 'TRUE', '前'}:
        return True
    if value.upper() in {'NO', 'FALSE', '後'}:
        return False
    raise ValueError('不正な指定です')


class GameData:
    def __init__(self, root: Path, encoding='auto', *, analysis_mode=False):
        self.root, self.encoding = root.resolve(), encoding
        self.analysis_mode = analysis_mode
        self.variables: dict[str, Variable] = {}
        self.symbols: dict[str, dict[str, int]] = {}
        self.csv_rows: dict[str, list[list[str]]] = {}
        self.item_name_definitions: set[int] = set()
        self.templates: dict[int, list[list[str]]] = {}
        self.sp_templates: dict[int, list[list[str]]] = {}
        self._templates_by_csv_number: list[tuple[int, int, list[list[str]]]] = []
        self.sizes: dict[str, tuple[int, ...]] = {}
        self.gamebase: dict[str, str] = {}
        self.replacements: dict[str, str] = {}
        self.config: dict[str, str] = {}
        # ConstantData captures this compatibility switch before CSV loading.
        # Resolved template names are independent of subsequent live writes.
        self._compat_callname = False
        self._callname_config_fixed = False
        self._auto_save = True
        self._auto_save_fixed = False
        self._auto_save_seen = False
        self._template_callnames: dict[int, str] = {}
        self._sp_template_callnames: dict[int, str] = {}
        self.files: list[dict] = []
        self.warnings: list[str] = []
        self.size_diagnostics = []
        self.character_count = 0
        self.settings = Settings()
        self._defaults()
        self._load()
        self.train_ids = sorted(
            {
                int(row[0])
                for row in self.csv_rows.get('TRAIN', [])
                if len(row) > 1
                and row[0].lstrip('-').isdigit()
                and 0 <= int(row[0]) < self.variables['TRAINNAME'].dims[0]
            }
        )
        self.initial = copy.deepcopy(self.variables)

    def _defaults(self):
        for name, n in NUM_GLOBAL.items():
            self.variables[name] = Variable(
                name,
                (n,),
                name in STR_GLOBAL,
                saved=name
                not in {
                    'RESULT',
                    'RESULTS',
                    'COUNT',
                    'WINDOW_TITLE',
                    'PALAMLV',
                    'EXPLV',
                },
                global_save=name in {'GLOBAL', 'GLOBALS'},
            )
        for name in STR_GLOBAL - self.variables.keys():
            self.variables[name] = Variable(name, string=True)
        for name, n in NUM_CHAR.items():
            self.variables[name] = Variable(
                name, (n,), string=name == 'CSTR', character=True, saved=True, default=0
            )
        for name, string in CHAR_SCALARS.items():
            self.variables[name] = Variable(name, (), string, True, saved=True)
        self.variables['CDFLAG'] = Variable(
            'CDFLAG', (1, 1), character=True, saved=True
        )
        for name in ('DITEMTYPE', 'DA', 'DB', 'DC', 'DD', 'DE'):
            self.variables[name] = Variable(name, (100, 100), saved=True)
        for name in ('TA', 'TB'):
            self.variables[name] = Variable(name, (100, 100, 100), saved=True)
        for name, spec in VARIABLE_SPECS.items():
            self.variables[name].dims = tuple(spec['dimensions'])
        for name in ('TARGET', 'ASSI', 'PREVCOM', 'NEXTCOM'):
            self.variables[name].set((0,), -1)
        for name in (
            'AUTHOR',
            'INFO',
            'YEAR',
            'TITLE',
            'GAMECODE',
            'VERSION',
            'ALLOWVERSION',
            'DEFAULTCHARA',
            'NOITEM',
        ):
            isstr = name in {'AUTHOR', 'INFO', 'YEAR', 'TITLE'}
            self.variables['GAMEBASE_' + name] = Variable(
                'GAMEBASE_' + name, string=isstr, readonly=True
            )
        self.variables['GAMEBASE_DEFAULTCHARA'].set((0,), -1, True)
        self.variables['GAMEBASE_ALLOWVERSION'].set((0,), -1, True)
        self.variables['EJAC'].set((0,), 10000)
        for name, val in {'MONEYLABEL': '$', 'DRAWLINESTR': '-'}.items():
            self.variables[name] = Variable(
                name, string=True, readonly=True, default=val
            )
        self.variables['PBAND'].set((0,), 4)
        for name, values in [('PALAMLV', DEFAULT_PALAMLV), ('EXPLV', DEFAULT_EXPLV)]:
            for i, v in enumerate(values):
                self.variables[name].set((i,), v, True)

    def _read(self, path):
        if not path.resolve().is_relative_to(self.root):
            raise EraError(f'Source leaves game root: {path}', code='E_PATH')
        text, codec = read_text(path, self.encoding)
        self.files.append(
            {
                'file': path.relative_to(self.root).as_posix(),
                'encoding': codec,
                'bytes': path.stat().st_size,
            }
        )
        return text

    def _read_config(self, path: Path) -> str:
        return self._read(path)

    def _load(self):
        self.config = load_config(
            self.root,
            self.encoding,
            self._read_config,
            self.warnings,
            analysis_mode=self.analysis_mode,
        )
        self._compat_callname = self.config.get('CompatiCALLNAME', 'NO') == 'YES'
        self.use_sp = self.config.get('SPキャラを使用する', 'NO').upper() == 'YES'
        folder = next(
            (p for p in self.root.iterdir() if p.is_dir() and p.name.upper() == 'CSV'),
            None,
        )
        if not folder:
            self.warnings.append('CSV directory not found. Built-in defaults only.')
            return
        paths = sorted(
            (
                p
                for p in folder.rglob('*')
                if p.suffix.lower() == '.csv' and p.is_file()
            ),
            key=lambda p: str(p).casefold(),
        )
        size_rows = []
        replace_texts = []
        from .startup import replace_enabled

        for p in paths:
            if not p.resolve().is_relative_to(self.root):
                raise EraError(f'CSV symlink leaves game root: {p}', code='E_PATH')
            if p.stem.upper() == '_REPLACE' and not replace_enabled(
                self.config, self.analysis_mode
            ):
                continue
            csv_text = self._read(p)
            if p.stem.upper() == '_REPLACE':
                replace_texts.append((p.relative_to(self.root).as_posix(), csv_text))
            if p.stem.upper() == 'VARIABLESIZE':
                for line_number, source in enumerate(source_lines(csv_text), 1):
                    if source.strip() and not source.lstrip().startswith(';'):
                        size_rows.append(
                            (
                                source.split(','),
                                Location(p.relative_to(self.root).as_posix(), line_number),
                                source,
                            )
                        )
            rows = [
                line.lstrip(' \t\u3000').split(',')
                for line in source_lines(csv_text)
                if line.strip() and not line.lstrip().startswith(';')
            ]
            key = p.stem.upper()
            if key != 'GAMEBASE':
                rows = [[c.strip() for c in row] for row in rows]
            if key in self.csv_rows:
                self.csv_rows[key].extend(rows)
            else:
                self.csv_rows[key] = rows
        from .variable_sizes import parse_size_row

        for row, location, source in size_rows:
            accepted = parse_size_row(row, location, source, self.size_diagnostics)
            if accepted is None:
                continue
            name, dims = accepted
            duplicate = name in self.sizes
            self.sizes[name] = dims
            if name in self.variables:
                variable = self.variables[name]
                variable.forbidden = dims[0] < 0
                if variable.forbidden:
                    variable.values.clear()
                else:
                    variable.dims = dims
                    variable.values = {
                        key: value
                        for key, value in variable.values.items()
                        if len(key) == len(dims) + int(variable.character)
                        and all(
                            0 <= index < size
                            for index, size in zip(
                                key[1:] if variable.character else key, dims
                            )
                        )
                    }
            if duplicate:
                from .errors import LoadDiagnostic

                self.size_diagnostics.append(
                    LoadDiagnostic(
                        1,
                        'CSV_VARIABLE_SIZE',
                        location,
                        source,
                        name + 'の要素数は既に定義されています（上書きします）',
                        len(self.size_diagnostics),
                        phase='csv-load',
                    )
                )
        # Keep the public warning-list contract, but display these structured
        # CSV diagnostics once through the shared load-diagnostic path.
        self.size_warning_texts = [
            f'{d.location}: 警告Lv{d.severity}: {d.reference_message}'
            for d in self.size_diagnostics
        ]
        self.warnings.extend(self.size_warning_texts)
        self._reconcile_name_sizes()
        for row in self.csv_rows.get('GAMEBASE', []):
            if len(row) < 2:
                continue
            key = BASE_KEYS.get(row[0], row[0].upper())
            value = row[1]
            self.gamebase[key] = value
            n = key if key == 'WINDOW_TITLE' else 'GAMEBASE_' + key
            if n in self.variables:
                var = self.variables[n]
                if var.string:
                    var.set((0,), value, True)
                else:
                    valid, number = gamebase_integer(value)
                    var.set((0,), number, True)
                    self.gamebase[key] = str(number)
                    if key == 'VERSION' and not valid:
                        self.gamebase.pop('VERSION', None)
                    if not valid:
                        self.warnings.append(
                            f'GameBase.csv: {key} is not an Int64/prefix integer; source default 0 used.'
                        )
        self.settings = Settings.from_texts(
            replace_texts, self.warnings, self.replacements
        )
        self.variables['MONEYLABEL'].default = self.settings.money_label
        self.variables['DRAWLINESTR'].default = self.settings.drawline
        self.variables['RELATION'].default = self.settings.relation
        if self.variables['PBAND'].dims[0]:
            self.variables['PBAND'].set((0,), self.settings.pband)
        for name, values in [
            ('EXPLV', self.settings.explv),
            ('PALAMLV', self.settings.palamlv),
        ]:
            var = self.variables[name]
            var.values.clear()
            for i, value in enumerate(values[: var.dims[0]]):
                var.set((i,), value, True)
        for key, rows in self.csv_rows.items():
            if key.startswith('CHARA'):
                self._remember_csv_character(key, rows)
                match = re.search(r'(\d+)', key)
                number = int(match.group()) if match else None
                for row in rows:
                    if row[0] in ('番号', 'NO') and len(row) > 1:
                        number = int(row[1])
                if number is not None:
                    special = False
                    for r in rows:
                        if (
                            CHAR_KEYS.get(r[0], r[0].upper()) == 'CFLAG'
                            and len(r) > 1
                            and r[1] == '0'
                        ):
                            special = int(r[2] if len(r) > 2 and r[2] else 1) != 0
                    table = (
                        self.sp_templates if self.use_sp and special else self.templates
                    )
                    if number in table:
                        self.warnings.append(
                            f'Duplicate character ID {number} (SP={special}); first definition retained.'
                        )
                    else:
                        table[number] = rows

                continue
            if key in ('GAMEBASE', 'VARIABLESIZE', '_REPLACE') or key.startswith('_'):
                continue
            mapped = (
                'STR' if key == 'STR' else key if key.endswith('NAME') else key + 'NAME'
            )
            if key in ('PALAMLV', 'EXPLV'):
                mapped = key
            known = (
                key in NUM_CHAR
                or key in NUM_GLOBAL
                or key in ('TRAIN', 'STRNAME', 'CDFLAG1', 'CDFLAG2')
                or key.endswith('NAME')
            )
            if not known:
                self.warnings.append(f'CSV table {key} loaded as generic name table.')
            fallback = self.variables[key].dims if key in self.variables else (1000,)
            raw_size = self.sizes.get(mapped, self.sizes.get(key, fallback))
            disabled = bool(raw_size and raw_size[0] < 0)
            size = fallback if disabled else raw_size
            if mapped not in self.variables:
                self.variables[mapped] = Variable(
                    mapped, size, string=True, readonly=True, forbidden=disabled
                )
            var = self.variables[mapped]
            if disabled:
                var.forbidden = True
            self.symbols.setdefault(key, {})
            for row in rows:
                if len(row) < 2:
                    continue
                try:
                    index = int(row[0])
                except ValueError:
                    self.warnings.append(
                        f'{key}: non-numeric key {row[0]!r}; ignored as metadata.'
                    )
                    continue
                if var.forbidden or index < 0 or index >= var.dims[0]:
                    self.warnings.append(
                        f'{key}.csv: index {index} outside enabled {mapped} dimensions; row ignored.'
                    )
                    continue
                value = ','.join(row[1:]) if key == 'STR' else row[1]
                var.set((index,), value if var.string else int(value), True)
                if mapped == 'ITEMNAME':
                    self.item_name_definitions.add(index)
                self.symbols[key].setdefault(row[1].upper(), index)
                if key == 'ITEM' and len(row) > 2 and row[2]:
                    if 'ITEMPRICE' not in self.variables:
                        disabled = self.sizes.get('ITEMPRICE') == (-1,)
                        self.variables['ITEMPRICE'] = Variable(
                            'ITEMPRICE', var.dims, readonly=True, forbidden=disabled
                        )
                    self.variables['ITEMPRICE'].set((index,), int(row[2]), True)
        if 'ITEMPRICE' not in self.variables:
            disabled = self.sizes.get('ITEMPRICE') == (-1,)
            self.variables['ITEMPRICE'] = Variable(
                'ITEMPRICE',
                (1000,) if disabled else self.sizes.get('ITEMPRICE', (1000,)),
                readonly=True,
                forbidden=disabled,
            )
        for key in set(NUM_CHAR) | {
            'ITEM',
            'TRAIN',
            'STRNAME',
            'TSTR',
            'SAVESTR',
            'FLAG',
            'TFLAG',
            'GLOBAL',
            'GLOBALS',
        }:
            mapped = key if key.endswith('NAME') else key + 'NAME'
            if mapped not in self.variables:
                fallback = (NUM_CHAR.get(key, 1000),)
                raw_size = self.sizes.get(mapped, fallback)
                disabled = bool(raw_size and raw_size[0] < 0)
                self.variables[mapped] = Variable(
                    mapped,
                    fallback if disabled else raw_size,
                    string=True,
                    readonly=True,
                    forbidden=disabled,
                )
        self._freeze_template_callnames()

    def _remember_csv_character(self, filename, rows):
        """Keep native file-number lookup separate from existing NO/SP tables.

        ConstantData creates a template at the first valid NO row. Preceding
        metadata and duplicate NO declarations do not initialize that template.
        This narrow record is used only by ADDDEFCHARA, not by CSV queries.
        """
        number = None
        accepted = []
        for row in rows:
            if row[0] in ('番号', 'NO'):
                if number is None and len(row) > 1:
                    try:
                        candidate = int(row[1])
                    except ValueError:
                        continue
                    if -(1 << 63) <= candidate < (1 << 63):
                        number = candidate
                continue
            if number is not None:
                accepted.append(row)
        if number is not None:
            match = re.match(r'CHARA(\d+)', filename)
            csv_no = int(match.group(1)) if match else 0
            self._templates_by_csv_number.append((csv_no, number, accepted))

    def _freeze_template_callnames(self) -> None:
        """Resolve final scalar rows once, as native loadCharacterData does.

        Raw rows remain available to indexed CSV queries and incremental live
        initialization. Only an absent/empty final CALLNAME may use final NAME,
        and only with the option captured during configuration loading.
        """
        for templates, names in [
            (self.templates, self._template_callnames),
            (self.sp_templates, self._sp_template_callnames),
        ]:
            for number, rows in templates.items():
                names[number] = self._callname_from_rows(rows)

    def _callname_from_rows(self, rows) -> str:
        """Use final scalar rows and the option captured before CSV loading."""
        name = callname = ''
        for row in rows:
            if len(row) < 2:
                continue
            field = CHAR_KEYS.get(row[0], row[0].upper())
            if field == 'NAME':
                name = row[1]
            elif field == 'CALLNAME':
                callname = row[1]
        return name if self._compat_callname and not callname else callname

    def _reconcile_name_sizes(self):
        """Source CSV dimension coupling; not auto-growing to fit CSV contents."""
        pairs = 'ABL TALENT EXP MARK BASE SOURCE EX EQUIP TEQUIP FLAG TFLAG CFLAG TCVAR CSTR STAIN STR TSTR SAVESTR GLOBAL GLOBALS'.split()
        for main in pairs:
            alias = main + 'NAME'
            vm = self.variables[main]
            has_main = main in self.sizes
            has_alias = alias in self.sizes
            if not has_main and not has_alias:
                continue
            a = 0 if vm.forbidden else vm.dims[0]
            b = self.sizes[alias][0] if has_alias else a
            b = max(0, b)
            n = max(a, b) if has_main and has_alias else b if has_alias else a
            if has_main and has_alias and a != b:
                self.warnings.append(
                    f'VariableSize.csv: {main}/{alias} disagree; using maximum {n}.'
                )
            vm.forbidden = n == 0
            if n:
                vm.dims = (n,)
            else:
                vm.values.clear()
            self.sizes[alias] = (n,) if n else (-1,)
        # PALAM/JUEL jointly bound PALAMNAME; do not change unrelated UP/DOWN.
        palam = self.variables['PALAM']
        juel = self.variables['JUEL']
        size = max(0 if v.forbidden else v.dims[0] for v in (palam, juel))
        changed = any(n in self.sizes for n in ('PALAM', 'JUEL'))
        if 'PALAMNAME' in self.sizes:
            proposed = max(0, self.sizes['PALAMNAME'][0])
            if not changed:
                palam.forbidden = proposed == 0
                if proposed:
                    palam.dims = (proposed,)
                size = max(proposed, 0 if juel.forbidden else juel.dims[0])
            elif proposed != size:
                n = max(size, proposed)
                for v in (palam, juel):
                    if (0 if v.forbidden else v.dims[0]) == size:
                        v.forbidden = n == 0
                        if n:
                            v.dims = (n,)
                size = n
        self.sizes['PALAMNAME'] = (size,) if size else (-1,)
        # In 1824 ITEMNAME and ITEMPRICE are linked, not ITEM's inventory size.
        price = self.sizes.get('ITEMPRICE', (1000,))[0]
        itemname = self.sizes.get('ITEMNAME', (1000,))[0]
        if 'ITEMPRICE' in self.sizes and 'ITEMNAME' in self.sizes:
            n = max(price, itemname)
        elif 'ITEMPRICE' in self.sizes:
            n = price
        else:
            n = itemname
        self.sizes['ITEMNAME'] = (n,) if n > 0 else (-1,)
        self.sizes['ITEMPRICE'] = self.sizes['ITEMNAME']

    def index_of(self, name: str, key: str, axis: int = -1) -> int:
        name = name.upper().split('@')[0]
        if name == 'CDFLAG':
            name = 'CDFLAG1' if axis == 1 else 'CDFLAG2'
        if name.endswith('NAME') and name != 'STRNAME':
            name = name[:-4]
        name = CSV_ALIASES.get(name, name)
        if name == 'STR':
            name = 'STRNAME'
        try:
            return self.symbols[name][key.upper()]
        except KeyError as e:
            raise EraError(f'{name}: unknown CSV index {key!r}', code='E_SYMBOL') from e

    def keyword_number(self, name: str, key: str) -> int:
        # v24 ConstantData: these descriptors use the Chara template relation
        # dictionary, including all four name fields. Never read live characters.
        name = name.upper().split('@')[0]
        if name in ('NAME', 'CALLNAME', 'NICKNAME', 'MASTERNAME', 'RELATION'):
            table = {}
            for number, rows in self.templates.items():
                values = {}
                for row in rows:
                    k = CHAR_KEYS.get(row[0], row[0].upper())
                    if (
                        k in ('NAME', 'CALLNAME', 'NICKNAME', 'MASTERNAME')
                        and len(row) > 1
                    ):
                        values[k] = row[1]
                values['CALLNAME'] = self.template_callname(number)
                for k in ('NAME', 'CALLNAME', 'NICKNAME', 'MASTERNAME'):
                    value = values.get(k, '')
                    if value:
                        table.setdefault(value, number)
            return table.get(key, -1)
        try:
            return self.index_of(name, key)
        except EraError:
            return -1

    def template(self, number: int, sp=False):
        table = self.sp_templates if sp and self.use_sp else self.templates
        return table.get(number)

    def template_callname(self, number: int, sp=False) -> str:
        """Return the load-time value of an already selected existing template.

        Callers retain their own template-existence/SP checks and diagnostics.
        Config changes and live NAME/CALLNAME assignments do not recalculate it.
        """
        names = (
            self._sp_template_callnames
            if sp and self.use_sp
            else self._template_callnames
        )
        return names[number]

    def add_character(self, number: int, void=False, sp=False):
        """Construct before roster commit; retain the public direct API.

        Template selection uses CSV NO and the existing normal/SP dictionary.
        Pseudo creation uses NO0 and no CSV. An exception cannot append a
        half-built record, but earlier records from this instruction remain.
        """
        if void:
            return self.add_pseudo_character()
        rows = self.template(number, sp)
        if rows is None:
            raise EraError(
                f'No Chara CSV for ID {number}',
                code='E_CSV',
                diagnostic_message='定義していないキャラクタを作成しようとしました',
            )
        return self._append_constructed_character(
            number, rows, self.template_callname(number, sp)
        )

    def add_pseudo_character(self):
        """Native AddPseudoCharacter: NO0, empty names, no RESET_STAIN."""
        return self._append_constructed_character(0, [], '')

    def _populate_character_rows(self, idx, number, rows, variables):
        """Populate one record in row order; caller owns its commit boundary.

        All character constructors supply staged descriptors
        and appends only after construction, as native CharacterData does.
        """
        for row in rows:
            if row[0].upper() in ('ISASSI', '助手'):
                continue
            key = CHAR_KEYS.get(row[0], row[0].upper())
            if key not in variables or not variables[key].character:
                warning = f'Chara {number}: unrecognized metadata key {row[0]!r}'
                if warning not in self.warnings:
                    self.warnings.append(warning)
                continue
            var = variables[key]
            if len(row) < 2:
                continue
            if not var.dims:
                var.set((idx,), row[1] if var.string else int(row[1] or 0))
            elif len(row) >= 2:
                numeric, j = character_csv_integer(row[1])
                if not numeric:
                    j = self.index_of(key, row[1])
                if var.forbidden or not 0 <= j < var.dims[0]:
                    warning = f'Chara {number}: {key} index {j} outside enabled dimensions; row ignored.'
                    if warning not in self.warnings:
                        self.warnings.append(warning)
                    continue
                if var.string:
                    val = row[2] if len(row) > 2 else ''
                else:
                    # ConstantData.toCharacterTemplate uses tryToInt64 (an
                    # integer prefix, not whole-field parsing), defaulting to
                    # 1 when omitted/invalid. A semicolon suffix is retained
                    # for string fields; it is not a global CSV comment rule.
                    numeric, val = character_csv_integer(row[2] if len(row) > 2 else '')
                    if not numeric:
                        val = 1
                var.set((idx, j), val)
                if key == 'BASE':
                    variables['MAXBASE'].set((idx, j), val)

    def add_default_character(self, csv_number: int):
        """Native AddCharacterFromCsvNo, distinct from lookup by CSV NO.

        Missing files use a pseudo template with NO=0, empty names and zero
        arrays. They do not run RESET_STAIN. Constructor failure does not append
        the current record; earlier ADDDEFCHARA records stay committed.
        """
        selected = next(
            (
                (number, rows)
                for file_no, number, rows in self._templates_by_csv_number
                if file_no == csv_number
            ),
            None,
        )
        number, rows = selected if selected is not None else (0, [])
        return self._append_constructed_character(
            number, rows, self._callname_from_rows(rows)
        )

    def _append_constructed_character(self, number, rows, callname):
        """Allocate zero cells and RELATION defaults, populate, then append.

        Staged descriptors suppress live write observers during construction.
        Allocation defaults are not RESET_STAIN settings. Native constructors
        never initialize STAIN from that reset-time configuration.
        """
        if self.character_count >= 100_000:
            raise EraError('Character limit reached', code='E_LIMIT')
        idx = self.character_count
        staged = {
            name: replace(var, values={}, write_observer=None)
            for name, var in self.variables.items()
            if var.character
        }
        for variable in staged.values():
            zero = '' if variable.string else 0
            if variable.default != zero and variable.name != 'RELATION':
                for key in product(*(range(size) for size in variable.dims)):
                    variable.set((idx,) + key, zero, True)
        staged['NO'].set((idx,), number)
        self._populate_character_rows(idx, number, rows, staged)
        if staged['CALLNAME'].get((idx,)) != callname:
            staged['CALLNAME'].set((idx,), callname)
        for name, variable in staged.items():
            self.variables[name].values.update(variable.values)
        self.character_count += 1
        return idx

    def reset_stain(self, character: int):
        if not 0 <= character < self.character_count:
            raise EraError('RESET_STAIN: invalid character index', code='E_CHARACTER')
        var = self.variables['STAIN']
        var.values = {
            key: value for key, value in var.values.items() if key[0] != character
        }
        for i, value in enumerate(self.settings.stain[: var.dims[0]]):
            var.set((character, i), value)

    def reorder_characters(self, old_indices: list[int], *, remap_roles=True):
        if len(set(old_indices)) != len(old_indices) or any(
            i < 0 or i >= self.character_count for i in old_indices
        ):
            raise EraError('Invalid character reorder', code='E_INDEX')
        mapping = {old: new for new, old in enumerate(old_indices)}
        for var in self.variables.values():
            if var.character:
                var.values = {
                    (mapping[k[0]],) + k[1:]: v
                    for k, v in var.values.items()
                    if k[0] in mapping
                }
        self.character_count = len(old_indices)
        if remap_roles:
            for name in ('TARGET', 'MASTER', 'ASSI', 'PLAYER'):
                var = self.variables[name]
                var.set((0,), mapping.get(var.get((0,)), -1))
