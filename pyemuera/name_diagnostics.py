"""Source-derived builtin-variable label warnings; no execution or name bans."""

import json
from importlib.resources import files
from .errors import LoadDiagnostic

TABLE = json.loads(
    files('pyemuera')
    .joinpath('specs/function_collision_v24.json')
    .read_text(encoding='utf-8')
)
BUILTIN_VARIABLE_NAMES = frozenset(TABLE['system_variables'])
SYSTEM_METHOD_NAMES = frozenset(TABLE['system_methods'])
RESERVED_NAMES = frozenset(TABLE['reserved'])
SYSTEM_INSTRUMENT_NAMES = frozenset(TABLE['system_instruments'])


def function_definition_warning(program, name, location):
    allowed = (
        program.config.get('システム関数の上書きを許可する', 'YES').upper() == 'YES'
    )
    if (
        allowed
        and program.config.get(
            'システム関数が上書きされたとき警告を表示する', 'YES'
        ).upper()
        != 'YES'
    ):
        return
    level = 1
    if name in RESERVED_NAMES:
        category = 'W_FUNCTION_RESERVED_COLLISION'
        body = (
            'はEmueraの予約語と衝突しています。Emuera専用構文の構文解析に支障をきたす恐れがあります'
            if allowed
            else 'はEmueraの予約語です'
        )
        level = 1 if allowed else 2
    elif name in SYSTEM_METHOD_NAMES:
        category = 'W_FUNCTION_METHOD_COLLISION'
        body = (
            'はEmueraの式中関数を上書きします'
            if allowed
            else 'はEmueraの式中関数名として使われています'
        )
        level = 1 if allowed else 2
    elif name in BUILTIN_VARIABLE_NAMES:
        category = 'W_FUNCTION_VARIABLE_COLLISION'
        body = 'はEmueraの変数で使われています'
    elif name in SYSTEM_INSTRUMENT_NAMES:
        category = 'W_FUNCTION_INSTRUMENT_COLLISION'
        body = 'はEmueraの変数もしくは命令で使われています'
    else:
        return
    source = program.original_source[location.path][location.line - 1]
    program.definition_diagnostics.append(
        LoadDiagnostic(
            level,
            category,
            location,
            source,
            '関数名' + name + body,
            len(program.definition_diagnostics),
        )
    )


def overload_notice_lines(program):
    if (
        program.config.get(
            'システム関数が上書きされたとき警告を表示する', 'YES'
        ).upper()
        != 'YES'
        or program.config.get('システム関数の上書きを許可する', 'YES').upper() != 'YES'
    ):
        return []
    names = [
        name
        for name in TABLE['system_methods']
        if any(
            f.attributes & {'FUNCTION', 'FUNCTIONS'}
            for f in program.functions.get(name, [])
        )
    ]
    if not names:
        return []
    return [
        ' ',
        '＊＊＊＊＊警告＊＊＊＊＊',
        *[
            '  システム関数"' + name + '"がユーザー定義関数によって上書きされています'
            for name in names
        ],
        '  上記の関数を利用するスクリプトは意図通りに動かない可能性があります',
        ' ',
        '  ※この警告は該当する式中関数を利用しているEmuera専用スクリプト向けの警告です。',
        '  eramaker用のスクリプトの動作には影響しません。',
        '  今後この警告が不要ならばコンフィグの「システム関数が上書きされたとき警告を表示する」をOFFにして下さい。',
        '＊＊＊＊＊＊＊＊＊＊＊＊',
    ]
