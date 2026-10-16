"""Native save integration: isolated output, validation-before-commit, CSV bounds."""

from __future__ import annotations
import copy
from itertools import product
import math
from pathlib import Path
from .errors import EraError
from . import native_save as codec


def safe_overlay(root: Path, folder: str, name: str) -> Path:
    path = root / '.pyemuera' / folder / name
    for p in (root / '.pyemuera', root / '.pyemuera' / folder, path):
        if p.is_symlink():
            raise EraError('Save overlay must not be a symlink', code='E_PATH')
    if not path.resolve().is_relative_to(
        (root / '.pyemuera').resolve()
    ) or not path.resolve().is_relative_to(root):
        raise EraError('Save overlay escapes game directory', code='E_PATH')
    return path


def original_path(vm, slot):
    root = vm.data.root
    use_folder = (
        vm.data.config.get('セーブデータをsavフォルダ内に作成する', 'NO').upper()
        == 'YES'
    )
    directory = root
    if use_folder:
        directory = next(
            (p for p in root.iterdir() if p.name.casefold() == 'sav' and p.is_dir()),
            root / 'sav',
        )
    name = 'global.sav' if slot == 'global' else f'save{int(slot):02d}.sav'
    path = (
        next(
            (
                p
                for p in directory.iterdir()
                if p.name.casefold() == name and p.is_file()
            ),
            directory / name,
        )
        if directory.exists()
        else directory / name
    )
    if not path.resolve().is_relative_to(root):
        raise EraError('Native save leaves game directory', code='E_PATH')
    return path


def validate_identity(vm, meta, slot):
    code = meta['native_gamecode']
    if code != 0 and code != vm.get('GAMEBASE_GAMECODE'):
        raise EraError('Native save belongs to another game', code='E_SAVE_GAME')
    target = meta['game_version']
    current = vm.get('GAMEBASE_VERSION')
    minimum = int(vm.data.gamebase.get('ALLOWVERSION', '-1'))
    undefined = 'VERSION' not in vm.data.gamebase
    compatible = undefined and target != 1000 or target >= minimum or target == current
    if not compatible:
        raise EraError(
            'Native save version is outside GameBase compatibility range',
            code='E_SAVE_VERSION',
        )
    if meta['global_save'] != (slot == 'global'):
        raise EraError('Native normal/global save mismatch', code='E_SAVE_FORMAT')


def check_file(vm, path, slot):
    """CHKDATA reads the header only, in source validation order.

    VariableEvaluator.CheckDataByFilename does not inspect the character
    count or body. A successful check is therefore not a loadability promise.
    Full load continues to decode and validate the entire detached state.
    """
    if path.stat().st_size > codec.MAX_BYTES:
        raise EraError('Native save too large', code='E_LIMIT')
    raw = path.read_bytes()
    binary = raw.startswith(codec.MAGIC)
    if binary:
        reader = codec.BinaryReader(raw)
        reader.read(8)
        version, count = reader.unpack('I'), reader.unpack('I')
        if version != 1808 or count > 1024:
            return 4, '読み込み中にエラーが発生しました'
        reader.read(count * 4)
        if reader.byte() != int(slot == 'global'):
            return 4, 'セーブデータが壊れています'
        number, string = lambda: reader.unpack('q'), reader.string
    else:
        reader = codec.TextReader(raw)

        def string():
            if reader.pos >= len(reader.lines):
                raise EraError(
                    '読み取るべき文字列がありません', code='E_SAVE_CHECK_TEXT'
                )
            return reader.line()

        def number():
            if reader.pos >= len(reader.lines):
                raise EraError('読み取るべき数値がありません', code='E_SAVE_CHECK_TEXT')
            try:
                return reader.number()
            except EraError as exc:
                raise EraError(
                    '数値として認識できません', code='E_SAVE_CHECK_TEXT'
                ) from exc

    code = number()
    if code != 0 and code != vm.get('GAMEBASE_GAMECODE'):
        return 2, '異なるゲームのセーブデータです'
    version = number()
    validate_identity(
        vm,
        {
            'native_gamecode': code,
            'game_version': version,
            'global_save': slot == 'global',
        },
        slot,
    )
    return 0, string()


def load_file(vm, path, slot):
    if path.stat().st_size > codec.MAX_BYTES:
        raise EraError('Native save too large', code='E_LIMIT')
    state = codec.decode(path.read_bytes(), slot == 'global')
    validate_identity(vm, state.metadata(), slot)
    # Build a detached transaction. Preserve live globals on normal load.
    isglobal = slot == 'global'
    staged = {}
    imported = 0
    clipped = {}
    unknown = []
    count = len(state.characters)
    expanded = 0
    for name, var in vm.data.variables.items():
        if var.readonly or var.forbidden or var.global_save != isglobal:
            continue
        values = copy.deepcopy(var.values if isglobal else vm.initial[name].values)
        if var.character:
            values = {}
            # The original loader creates zeroed character arrays, not CSV
            # characters. A nonzero sparse default needs explicit zero entries.
            if var.default not in (0, ''):
                n = math.prod(var.dims) * count
                expanded += n
                if expanded > codec.MAX_VALUES:
                    raise EraError('Native default expansion limit', code='E_LIMIT')
                for c in range(count):
                    for key in product(*(range(d) for d in var.dims)):
                        values[(c,) + key] = '' if var.string else 0
        staged[name] = values

    def apply(name, record, character=None):
        nonlocal imported, expanded
        var = vm.data.variables.get(name)
        if (
            var is None
            or var.readonly
            or var.forbidden
            or var.global_save != isglobal
            or var.character != (character is not None)
            or var.string != record.string
            or len(var.dims) != len(record.dims)
        ):
            if record.values:
                unknown.append(name)
            return
        expected = (
            codec.BUILTIN_CHAR
            if character is not None
            else codec.BUILTIN_GLOBAL if isglobal else codec.BUILTIN_NORMAL
        )
        if name not in expected and not var.saved:
            if record.values:
                unknown.append(name)
            return
        values = staged[name]
        prefix = () if character is None else (character,)
        # Legacy/binary arrays clear their omitted tail; user text extensions
        # copy only serialized cells, preserving initializer/live global tails.
        preserve_tail = state.wire == 'text' and record.user
        if character is None and not preserve_tail:
            values = {}
            staged[name] = values
        else:
            # The transaction is initially empty per character. Any explicit
            # zero overrides for nonzero defaults must remain.
            pass
        if var.default not in (0, '') and not preserve_tail:
            n = math.prod(var.dims)
            expanded += n
            if expanded > codec.MAX_VALUES:
                raise EraError('Native default expansion limit', code='E_LIMIT')
            for key in product(*(range(d) for d in var.dims)):
                values[prefix + key] = '' if var.string else 0
        for key, value in record.values.items():
            if any(k >= n for k, n in zip(key, var.dims)):
                clipped[name] = clipped.get(name, 0) + 1
                continue
            full = prefix + key
            var.validate(full)
            if value == var.default:
                values.pop(full, None)
            else:
                values[full] = value
            imported += int(value != ('' if record.string else 0))

    for c, records in enumerate(state.characters):
        for name, rec in records.items():
            apply(name, rec, c)
    for name, rec in state.variables.items():
        apply(name, rec)
    # Do not silently discard unknown nonempty variables when migrating saves.
    if unknown:
        raise EraError(
            'Native save contains unmapped nonempty variables; state unchanged: '
            + ', '.join(sorted(set(unknown))),
            code='E_SAVE_SCHEMA',
        )
    # Prepare reset local/private state before committing any game variable.
    static = (
        {
            uid: {name: copy.deepcopy(v.values) for name, v in variables.items()}
            for uid, variables in vm.static_initial.items()
        }
        if not isglobal
        else {}
    )
    legacy = (
        {
            fn: {name: copy.deepcopy(v.values) for name, v in variables.items()}
            for fn, variables in vm.legacy_initial.items()
        }
        if not isglobal
        else {}
    )
    if not isglobal:
        # Validate load metadata destinations before the atomic state switch.
        for name, value in [
            ('LASTLOAD_NO', int(slot)),
            ('LASTLOAD_VERSION', state.game_version),
            ('LASTLOAD_TEXT', state.description),
        ]:
            var = vm.data.variables[name]
            var.validate((0,))
            if var.readonly or var.string != isinstance(value, str):
                raise EraError(
                    'Invalid native load metadata destination', code='E_SAVE_SCHEMA'
                )
    next_rng = None
    if not isglobal and vm.saves.native_rng == 'restore':
        from .random1824 import EngineRandom

        rec = state.variables.get('RANDDATA')
        if rec is None:
            vm.console.warning(
                'native-missing-rng',
                'No RANDDATA in the native save; the current RNG is retained.',
            )
        else:
            if rec.string or len(rec.dims) != 1 or rec.dims[0] > 625:
                raise EraError(
                    'Invalid native RANDDATA schema; state unchanged',
                    code='E_RANDOM_STATE',
                )
            next_rng = EngineRandom(0)
            next_rng.set_native([rec.values.get((i,), 0) for i in range(625)])
    for name, values in staged.items():
        vm.data.variables[name].values = values
    if not isglobal:
        vm.data.character_count = count
        for uid, variables in static.items():
            for name, values in variables.items():
                vm.static[uid][name].values = values
        for fn, variables in legacy.items():
            for name, values in variables.items():
                vm.legacy[fn][name].values = values
        vm.set('LASTLOAD_NO', int(slot))
        vm.set('LASTLOAD_VERSION', state.game_version)
        vm.set('LASTLOAD_TEXT', state.description)
        if next_rng is not None:
            vm.rng = next_rng
        elif vm.saves.native_rng == 'source':
            vm.console.warning(
                'native-rng',
                'Native variables loaded; src1824 leaves the active RNG unchanged. ERB INITRAND or --native-rng restore applies RANDDATA.',
            )
    report = {
        'format': state.metadata()['format'],
        'source': str(path.relative_to(vm.data.root)),
        'slot': slot,
        'game_version': state.game_version,
        'character_count': count,
        'imported_nondefault_values': imported,
        'clipped_nondefault_values': clipped,
        'unmapped_variables': [],
        'rng_policy': vm.saves.native_rng,
        'rng_algorithm': vm.rng.algorithm,
    }
    vm.last_native_import = report
    if clipped:
        vm.console.warning(
            'native-clipped',
            'Native arrays were clipped to this game\'s CSV dimensions: '
            + ', '.join(sorted(clipped)),
        )
    if vm.journal:
        vm.journal.note('native_load', **report)
    return 1


def snapshot(vm, slot, description=''):
    isglobal = slot == 'global'
    save = codec.NativeSave(
        vm.get('GAMEBASE_GAMECODE'),
        vm.get('GAMEBASE_VERSION'),
        str(description),
        isglobal,
    )
    if not isglobal:
        save.characters = [{} for _ in range(vm.data.character_count)]
    total = 0
    for name, var in vm.data.variables.items():
        known = (
            codec.BUILTIN_CHAR
            if var.character
            else codec.BUILTIN_GLOBAL if isglobal else codec.BUILTIN_NORMAL
        )
        if (
            var.readonly
            or var.forbidden
            or var.global_save != isglobal
            or (name not in known and not var.saved)
        ):
            continue
        # STR is a real native variable, but VariableCode excludes it from
        # saved arrays; normal native load resets it from STR.CSV.
        # LASTLOAD*/WINDOW_TITLE also are not serialized. User saved variables are in
        # Program.globals, so distinguish them from extra builtins.
        user = name not in known
        if user and name in vm.data.initial:
            continue
        targets = range(vm.data.character_count) if var.character else [None]
        for c in targets:
            values = {
                key[1:] if c is not None else key: value
                for key, value in var.values.items()
                if c is None or key[0] == c
            }
            if var.default not in (0, ''):
                n = math.prod(var.dims)
                if n + total > codec.MAX_VALUES:
                    raise EraError(
                        'Native export default expansion limit', code='E_LIMIT'
                    )
                values = {
                    key: values.get(key, var.default)
                    for key in product(*(range(d) for d in var.dims))
                }
            values = {k: v for k, v in values.items() if v != ('' if var.string else 0)}
            total += len(values)
            if total > codec.MAX_VALUES:
                raise EraError('Native export value budget', code='E_LIMIT')
            rec = codec.Record(var.dims, var.string, values, user)
            codec.validate_record(name, rec)
            (save.characters[c] if c is not None else save.variables)[name] = rec
    return save


def export_randdata(python_state):
    """Create a valid SFMT-19937 initial state, NOT a Python-to-SFMT stream conversion.

    Reference layout/initialization: supplied Emuera/_Library/SFMT.cs,
    init_gen_rand / period_certification / GetRand. The state seed is a stable
    digest of Python's RNG state. Native export deliberately restarts the foreign
    stream instead of emitting all-zero or stale RANDDATA (which could break
    native random draws). It does not consume or modify the Python RNG.
    """
    import hashlib, json

    seed = int.from_bytes(
        hashlib.sha256(
            json.dumps(python_state, separators=(',', ':')).encode('ascii')
        ).digest()[:4],
        'little',
    )
    words = [seed]
    for i in range(1, 624):
        prev = words[-1]
        words.append((1812433253 * (prev ^ (prev >> 30)) + i) & 0xFFFFFFFF)
    # PARITY=(1,0,0,0x13c9e684); the first eligible repair bit is word0 bit0.
    parity = (words[0] & 1) ^ (words[3] & 0x13C9E684)
    if parity.bit_count() % 2 == 0:
        words[0] ^= 1
    words.append(624)
    return codec.Record((625,), False, {(i,): n for i, n in enumerate(words) if n})
