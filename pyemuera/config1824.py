"""Typed native configuration rows (ConfigData.cs 40–110, ConfigItem.cs).

Defaults and aliases are contract data, not executable external configuration.
"""

import re

# code name, displayed name, native type, serialized default
ITEMS = (
    ('IgnoreCase', '大文字小文字の違いを無視する', 'bool', 'YES'),
    ('UseRenameFile', '_Rename.csvを利用する', 'bool', 'NO'),
    ('UseReplaceFile', '_Replace.csvを利用する', 'bool', 'YES'),
    ('UseMouse', 'マウスを使用する', 'bool', 'YES'),
    ('UseMenu', 'メニューを使用する', 'bool', 'YES'),
    ('UseDebugCommand', 'デバッグコマンドを使用する', 'bool', 'NO'),
    ('AllowMultipleInstances', '多重起動を許可する', 'bool', 'YES'),
    ('AutoSave', 'オートセーブを行なう', 'bool', 'YES'),
    ('UseKeyMacro', 'キーボードマクロを使用する', 'bool', 'YES'),
    ('SizableWindow', 'ウィンドウの高さを可変にする', 'bool', 'YES'),
    ('TextDrawingMode', '描画インターフェース', 'TextDrawingMode', 'TEXTRENDERER'),
    ('WindowX', 'ウィンドウ幅', 'int', '760'),
    ('WindowY', 'ウィンドウ高さ', 'int', '480'),
    ('WindowPosX', 'ウィンドウ位置X', 'int', '0'),
    ('WindowPosY', 'ウィンドウ位置Y', 'int', '0'),
    ('SetWindowPos', '起動時のウィンドウ位置を指定する', 'bool', 'NO'),
    ('WindowMaximixed', '起動時にウィンドウを最大化する', 'bool', 'NO'),
    ('MaxLog', '履歴ログの行数', 'int', '5000'),
    ('PrintCPerLine', 'PRINTCを並べる数', 'int', '3'),
    ('PrintCLength', 'PRINTCの文字数', 'int', '25'),
    ('FontName', 'フォント名', 'string', 'ＭＳ ゴシック'),
    ('FontSize', 'フォントサイズ', 'int', '18'),
    ('LineHeight', '一行の高さ', 'int', '19'),
    ('ForeColor', '文字色', 'Color', '192,192,192'),
    ('BackColor', '背景色', 'Color', '0,0,0'),
    ('FocusColor', '選択中文字色', 'Color', '255,255,0'),
    ('LogColor', '履歴文字色', 'Color', '192,192,192'),
    ('FPS', 'フレーム毎秒', 'int', '5'),
    ('SkipFrame', '最大スキップフレーム数', 'int', '3'),
    ('ScrollHeight', 'スクロール行数', 'int', '1'),
    ('InfiniteLoopAlertTime', '無限ループ警告までのミリ秒数', 'int', '5000'),
    ('DisplayWarningLevel', '表示する最低警告レベル', 'int', '1'),
    ('DisplayReport', 'ロード時にレポートを表示する', 'bool', 'NO'),
    (
        'ReduceArgumentOnLoad',
        'ロード時に引数を解析する',
        'ReduceArgumentOnLoadFlag',
        'NO',
    ),
    ('IgnoreUncalledFunction', '呼び出されなかった関数を無視する', 'bool', 'YES'),
    (
        'FunctionNotFoundWarning',
        '関数が見つからない警告の扱い',
        'DisplayWarningFlag',
        'IGNORE',
    ),
    (
        'FunctionNotCalledWarning',
        '関数が呼び出されなかった警告の扱い',
        'DisplayWarningFlag',
        'IGNORE',
    ),
    (
        'ChangeMasterNameIfDebug',
        'デバッグコマンドを使用した時にMASTERの名前を変更する',
        'bool',
        'YES',
    ),
    ('ButtonWrap', 'ボタンの途中で行を折りかえさない', 'bool', 'NO'),
    ('SearchSubdirectory', 'サブディレクトリを検索する', 'bool', 'NO'),
    ('SortWithFilename', '読み込み順をファイル名順にソートする', 'bool', 'NO'),
    ('LastKey', '最終更新コード', 'long', '0'),
    ('SaveDataNos', '表示するセーブデータ数', 'int', '20'),
    ('WarnBackCompatibility', 'eramaker互換性に関する警告を表示する', 'bool', 'YES'),
    ('AllowFunctionOverloading', 'システム関数の上書きを許可する', 'bool', 'YES'),
    (
        'WarnFunctionOverloading',
        'システム関数が上書きされたとき警告を表示する',
        'bool',
        'YES',
    ),
    ('TextEditor', '関連づけるテキストエディタ', 'string', 'notepad'),
    (
        'EditorType',
        'テキストエディタコマンドライン指定',
        'TextEditorType',
        'USER_SETTING',
    ),
    ('EditorArgument', 'エディタに渡す行指定引数', 'string', ''),
    (
        'WarnNormalFunctionOverloading',
        '同名の非イベント関数が複数定義されたとき警告する',
        'bool',
        'NO',
    ),
    ('CompatiErrorLine', '解釈不可能な行があっても実行する', 'bool', 'NO'),
    ('CompatiCALLNAME', 'CALLNAMEが空文字列の時にNAMEを代入する', 'bool', 'NO'),
    ('UseSaveFolder', 'セーブデータをsavフォルダ内に作成する', 'bool', 'NO'),
    ('CompatiRAND', '擬似変数RANDの仕様をeramakerに合わせる', 'bool', 'NO'),
    ('CompatiDRAWLINE', 'DRAWLINEを常に新しい行で行う', 'bool', 'NO'),
    (
        'CompatiFunctionNoignoreCase',
        '関数・属性については大文字小文字を無視しない',
        'bool',
        'NO',
    ),
    ('SystemAllowFullSpace', '全角スペースをホワイトスペースに含める', 'bool', 'YES'),
    ('SystemSaveInUTF8', 'セーブデータをUTF-8で保存する', 'bool', 'NO'),
    ('CompatiLinefeedAs1739', 'ver1739以前の非ボタン折り返しを再現する', 'bool', 'NO'),
    ('useLanguage', '内部で使用する東アジア言語', 'UseLanguage', 'JAPANESE'),
    (
        'AllowLongInputByMouse',
        'ONEINPUT系命令でマウスによる2文字以上の入力を許可する',
        'bool',
        'NO',
    ),
    ('CompatiCallEvent', 'イベント関数のCALLを許可する', 'bool', 'NO'),
    ('CompatiSPChara', 'SPキャラを使用する', 'bool', 'NO'),
    ('SystemSaveInBinary', 'セーブデータをバイナリ形式で保存する', 'bool', 'NO'),
    (
        'CompatiFuncArgOptional',
        'ユーザー関数の全ての引数の省略を許可する',
        'bool',
        'NO',
    ),
    (
        'CompatiFuncArgAutoConvert',
        'ユーザー関数の引数に自動的にTOSTRを補完する',
        'bool',
        'NO',
    ),
    ('SystemIgnoreTripleSymbol', 'FORM中の三連記号を展開しない', 'bool', 'NO'),
    ('TimesNotRigorousCalculation', 'TIMESの計算をeramakerにあわせる', 'bool', 'NO'),
    ('SystemNoTarget', 'キャラクタ変数の引数を補完しない', 'bool', 'NO'),
    ('SystemIgnoreStringSet', '文字列変数の代入に文字列式を強制する', 'bool', 'NO'),
)
BY_NAME = {name: row for row in ITEMS for name in row[:2]}
ENUMS = {
    'TextDrawingMode': ('GRAPHICS', 'TEXTRENDERER', 'WINAPI'),
    'ReduceArgumentOnLoadFlag': ('YES', 'ONCE', 'NO'),
    'DisplayWarningFlag': ('IGNORE', 'LATER', 'ONCE', 'DISPLAY'),
    'UseLanguage': ('JAPANESE', 'KOREAN', 'CHINESE_HANS', 'CHINESE_HANT'),
    'TextEditorType': ('SAKURA', 'TERAPAD', 'EMEDITOR', 'USER_SETTING'),
}


def number(text, bits=32):
    if not re.fullmatch(r'[+-]?[0-9]+', text.strip()):
        raise ValueError('数字でない文字が含まれています')
    value = int(text)
    if not -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
        raise ValueError('数字でない文字が含まれています')
    return value


def boolean(text):
    value = text.strip().upper()
    if value in ('YES', 'TRUE', '前'):
        return True
    if value in ('NO', 'FALSE', '後'):
        return False
    try:
        return number(value) != 0
    except ValueError:
        raise ValueError('不正な指定です') from None


def parsed(kind, raw):
    value = raw.strip()
    if kind == 'bool':
        return 'YES' if boolean(raw) else 'NO'
    if kind in ('int', 'long'):
        return str(number(value, 64 if kind == 'long' else 32))
    if kind == 'Color':
        parts = value.split(',')
        try:
            numbers = [number(x) for x in parts[:3]]
            if len(numbers) != 3 or any(not 0 <= x <= 255 for x in numbers):
                raise ValueError()
        except ValueError:
            raise ValueError('値をColor指定子として認識できません') from None
        return ','.join(map(str, numbers))
    if kind in ENUMS:
        value = value.upper()
        if value not in ENUMS[kind]:
            raise ValueError('不正な指定です')
    return value


def load(root, encoding, reader, warnings, *, analysis_mode=False):
    from .text import read_text
    from .errors import EraError

    root = root.resolve()
    csv = next(
        (x for x in root.iterdir() if x.is_dir() and x.name.upper() == 'CSV'), None
    )

    def named(folder, name):
        return (
            next(
                (
                    x
                    for x in folder.iterdir()
                    if x.is_file() and x.name.casefold() == name
                ),
                None,
            )
            if folder
            else None
        )

    paths = [
        (named(csv, '_default.config') or named(csv, 'default.config'), False),
        (named(root, 'emuera.config'), False),
        (named(csv, '_fixed.config') or named(csv, 'fixed.config'), True),
    ]
    config = {}  # Preserve absence for embedding API entry-point policy.
    locked = set()
    for path, fix in paths:
        if path is None:
            continue
        if not path.resolve().is_relative_to(root):
            raise EraError('Configuration leaves game root', code='E_PATH')
        text = reader(path) if reader else read_text(path, encoding)[0]
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(';') or ':' not in line:
                continue
            parts = line.split(':')
            row = BY_NAME.get(parts[0].strip())
            if row is None:
                continue
            alias, key, kind, _ = row
            if alias == 'CompatiDRAWLINE':
                row = BY_NAME['CompatiLinefeedAs1739']
                alias, key, kind, _ = row
            if alias in locked:
                continue
            raw = parts[1]
            if alias == 'EditorArgument':
                config[alias] = config[key] = raw
                continue
            if analysis_mode and alias == 'MaxLog':
                raw = '10000'
            if not raw:
                continue
            if alias == 'TextEditor' and len(parts) > 2:
                if parts[2].startswith('\\'):
                    raw += ':' + parts[2]
                if len(parts) > 3:
                    raw += ':' + ':'.join(parts[3:])
            try:
                value = parsed(kind, raw)
            except ValueError as exc:
                if warnings is not None:
                    warnings.append(
                        f'{path.relative_to(root).as_posix()}:{lineno}: {alias}: {exc}'
                    )
                break
            config[alias] = config[key] = value
            if fix:
                locked.add(alias)
    return config
