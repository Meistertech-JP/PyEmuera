"""Startup label configuration and once-only presentation, before gameplay.

Native Process.Initialize prints LoadLabel before GameBase/ERB diagnostics when
DisplayReport is false. CLI preflight reads only configuration and this string;
GameData performs the full data load. Embedders can instead emit at VM.run.
No game expression, frame, input, clock or RNG is evaluated here.
"""

from pathlib import Path
import re
from .errors import EraError
from .settings import Settings
from .text import load_config, read_text
from .source_lines import source_lines

LOAD_LABEL_KEYS = frozenset(('LoadLabel', '起動時簡略表示'))


def _flag(config, key, default):
    """Interpret native bool spellings and signed Int32 values.

    Invalid general configuration still belongs to the existing config loader.
    Retain the item default here rather than silently treating garbage as NO;
    native file-abort/previous-value diagnostics remain a separate gap.
    """
    text = config.get(key, 'YES' if default else 'NO').strip()
    if text.upper() in ('YES', 'TRUE', '前'):
        return True
    if text.upper() in ('NO', 'FALSE', '後'):
        return False
    try:
        if re.fullmatch(r'[+-]?[0-9]+', text):
            value = int(text)
            if -(1 << 31) <= value < (1 << 31):
                return value != 0
    except ValueError:
        pass
    return default


def replace_enabled(config, analysis_mode=False):
    return not analysis_mode and _flag(config, '_Replace.csvを利用する', True)


def load_label_rows(text):
    """Native first comma/colon delimiter, remainder intact, last valid wins.

    Empty/missing fields are ignored, quotes are ordinary string characters.
    Both aliases update one item in file order; unknown keys belong to the
    existing Settings warning policy, rather than this label-only reader.
    """
    rows = {}
    for line in source_lines(text):
        if not line or line.startswith(';'):
            continue
        parts = re.split('[,:]', line, maxsplit=1)
        if len(parts) != 2:
            continue
        key, value = parts[0].strip(), parts[1].strip()
        if key in LOAD_LABEL_KEYS and value:
            rows.clear()  # Both native aliases name the same ConfigItem.
            rows[key] = value
    return rows


def read_startup(root: Path, encoding='auto'):
    """Read only the label needed for a visible, early CLI loading message.

    Keep Program/GameData construction and their diagnostic precedence intact.
    Configuration sources are re-read by those existing loaders; no general
    settings loader or invalid-setting recovery policy is replaced here.
    """
    root = root.resolve()
    config = load_config(root, encoding)
    settings = Settings()
    if replace_enabled(config):
        csv = next(
            (p for p in root.iterdir() if p.is_dir() and p.name.upper() == 'CSV'), None
        )
        path = (
            next(
                (
                    p
                    for p in csv.iterdir()
                    if p.is_file() and p.name.casefold() == '_replace.csv'
                ),
                None,
            )
            if csv
            else None
        )
        if path is not None:
            if not path.resolve().is_relative_to(root):
                raise EraError('Replace file leaves game root', code='E_PATH')
            settings = Settings.from_rows(
                load_label_rows(read_text(path, encoding)[0]), []
            )
    return settings, config


def emit_startup(console, settings, config):
    """Append one startup row at most once, separately from warning registration.

    The row is logical history, as native PrintSingleLine/addDisplayLine is.
    DisplayReport suppresses the simple label; this is not an implementation
    of native GUI per-file progress reporting. Empty labels produce no row.
    """
    if getattr(console, '_startup_emitted', False):
        return
    console._startup_emitted = True
    if _flag(config, 'ロード時にレポートを表示する', False):
        return
    if settings.load_label:
        console.write(settings.load_label, newline=True)
        console.flush()
