"""JSON and native Emuera saves with an isolated, atomic writable overlay."""

from __future__ import annotations
import hashlib
import json
import os
import errno
from pathlib import Path
import tempfile
from .errors import EraError
from .registry import VARIABLE_SPECS


class Saves:
    FORMAT = 'PyEmuera-JSON-1'

    def __init__(self, vm):
        self.vm = vm
        self.directory = vm.data.root / '.pyemuera' / 'saves'
        self.format = 'json'
        self.native_rng = 'source'
        self.allow_rng_reseed = False

    def path(self, slot):
        name = 'global' if slot == 'global' else str(int(slot))
        if slot != 'global' and not 0 <= int(slot) <= 99999:
            raise EraError('Save slot must be 0..99999', code='E_SAVE')
        from .native_store import safe_overlay

        path = safe_overlay(self.vm.data.root, 'saves', name + '.json')
        if not path.resolve().is_relative_to(self.vm.data.root):
            raise EraError('Save path escapes game directory', code='E_PATH')
        return path

    def identity(self):
        d = self.vm.data
        return {
            'gamecode': d.variables['GAMEBASE_GAMECODE'].get((0,)),
            'title': d.variables['GAMEBASE_TITLE'].get((0,)),
        }

    def _write_json(self, slot, description=''):
        path = self.path(slot)
        isglobal = slot == 'global'
        selected = {}
        for name, var in self.vm.data.variables.items():
            if (
                var.readonly
                or var.forbidden
                or not var.saved
                or var.global_save != isglobal
            ):
                continue
            selected[name] = {
                'dims': list(var.dims),
                'string': var.string,
                'character': var.character,
                'values': [[list(k), v] for k, v in sorted(var.values.items())],
            }
        state = {
            'format': self.FORMAT,
            'builtin_defaults_profile': 'src1824-a10',
            'identity': self.identity(),
            'game_version': self.vm.data.variables['GAMEBASE_VERSION'].get((0,)),
            'slot': slot,
            'description': str(description),
            'variables': selected,
        }
        if not isglobal:
            state['character_count'] = self.vm.data.character_count
            state['random_state'] = self.vm.rng.getstate()
        data = json.dumps(state, ensure_ascii=True, separators=(',', ':')).encode(
            'utf-8'
        )
        if len(data) > 128 * 1024 * 1024:
            raise EraError('Save size limit', code='E_LIMIT')
        self.atomic_write(path, data)
        self._unmask(slot)
        return 1

    def _inspect_json(self, slot):
        path = self.path(slot)
        if not path.exists():
            return None
        if path.stat().st_size > 128 * 1024 * 1024:
            raise EraError('Save too large', code='E_SAVE')
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(state, dict) or state.get('format') != self.FORMAT:
                raise ValueError('format mismatch')
            if state.get('identity') != self.identity():
                raise ValueError('different game')
            if not isinstance(state.get('variables'), dict):
                raise ValueError('variables must be an object')
            return state
        except (ValueError, UnicodeError) as e:
            raise EraError(f'Invalid save: {e}', code='E_SAVE') from e

    def _load_json(self, slot):
        state = self._inspect_json(slot)
        if state is None:
            return 0
        isglobal = slot == 'global'
        parsed = {}
        count = state.get('character_count', self.vm.data.character_count)
        if type(count) is not int or not 0 <= count <= 100000:
            raise EraError('Invalid saved character count', code='E_SAVE')
        try:
            expected = {
                name
                for name, var in self.vm.data.variables.items()
                if var.saved
                and not var.readonly
                and not var.forbidden
                and var.global_save == isglobal
            }
            added = {
                'EJAC',
                'DITEMTYPE',
                'NOTUSE_14',
                'NOTUSE_15',
                'NOTUSE_1C',
                'NOTUSE_1D',
                'NOTUSE_38',
                'NOTUSE_39',
                'NOTUSE_3A',
                'NOTUSE_3B',
                'RANDDATA',
            }
            missing = expected - set(state['variables'])
            if missing <= added:
                for name in missing:
                    v = self.vm.initial[name]
                    state['variables'][name] = {
                        'dims': list(v.dims),
                        'string': v.string,
                        'character': v.character,
                        'values': [[list(k), x] for k, x in v.values.items()],
                    }
            if set(state['variables']) != expected:
                raise ValueError('save variable set does not match this game build')
            if state.get('slot') != slot:
                raise ValueError('save slot/type mismatch')
            if type(state.get('game_version')) is not int or not isinstance(
                state.get('description'), str
            ):
                raise ValueError('invalid save metadata')
            if not isglobal and 'random_state' not in state:
                raise ValueError('missing random state')
            for name, body in state['variables'].items():
                if name not in self.vm.data.variables:
                    raise ValueError(f'unknown variable {name}')
                var = self.vm.data.variables[name]
                if (
                    var.readonly
                    or var.forbidden
                    or not var.saved
                    or var.global_save != isglobal
                ):
                    raise ValueError(f'forbidden variable {name}')
                old_dims = body['dims']
                migration = VARIABLE_SPECS.get(name)
                legacy = (
                    state.get('builtin_defaults_profile') is None
                    and name not in self.vm.data.sizes
                    and migration is not None
                    and old_dims == list(migration['legacy_a9_dimensions'])
                    and list(var.dims) == list(migration['dimensions'])
                )
                if (
                    (old_dims != list(var.dims) and not legacy)
                    or body['string'] != var.string
                    or body['character'] != var.character
                ):
                    raise ValueError(f'variable schema changed: {name}')
                values = {}
                for key, value in body['values']:
                    key = tuple(key)
                    if any(type(x) is not int for x in key):
                        raise ValueError('non-integer index')
                    if key in values:
                        raise ValueError('duplicate array index')
                    if len(key) != len(old_dims) + (1 if var.character else 0) or any(
                        i < 0 or i >= n
                        for i, n in zip(key[1:] if var.character else key, old_dims)
                    ):
                        raise ValueError('index outside stored dimensions')
                    # Even during a legacy migration, all stored entries must fit
                    # the new shape; nothing outside it is silently discarded.
                    var.validate(key)
                    if var.character and key[0] >= count:
                        raise ValueError('character index outside saved count')
                    if var.string != isinstance(value, str) or (
                        not var.string and type(value) is not int
                    ):
                        raise ValueError('wrong value type')
                    if not var.string and not -(1 << 63) <= value < (1 << 63):
                        raise ValueError('integer overflow')
                    values[key] = value
                parsed[name] = values
            random_state = None
            if not isglobal and 'random_state' in state:
                from .random1824 import EngineRandom

                random_state = state['random_state']
                trial = EngineRandom(0)
                trial.setstate(random_state)
        except (KeyError, ValueError, TypeError, IndexError, EraError) as e:
            raise EraError(
                f'Save validation failed; state unchanged: {e}', code='E_SAVE'
            ) from e
        # All validations complete before mutating any live variable.
        for name, values in parsed.items():
            self.vm.data.variables[name].values = values
        if not isglobal:
            self.vm.data.character_count = count
            if random_state is not None:
                self.vm.rng = trial
            self.vm.set('LASTLOAD_NO', int(slot))
            self.vm.set('LASTLOAD_VERSION', state.get('game_version', 0))
            self.vm.set('LASTLOAD_TEXT', state.get('description', ''))
        return 1

    def native_path(self, slot):
        from .native_store import safe_overlay

        self.path(slot)  # Validate slot before constructing any native filename.
        name = 'global.sav' if slot == 'global' else f'save{int(slot):02d}.sav'
        return safe_overlay(self.vm.data.root, 'native-saves', name)

    def candidate(self, slot):
        from .native_store import original_path

        json_path = self.path(slot)
        native_path = self.native_path(slot)
        writable = (
            [json_path, native_path]
            if self.format == 'json'
            else [native_path, json_path]
        )
        if self._tombstone(slot).is_file():
            return None
        for path in writable + [original_path(self.vm, slot)]:
            if path.is_file():
                return path
        return None

    @staticmethod
    def atomic_write(path, data):
        """Commit a complete overlay, translating expected host I/O failures.

        A script/codec error remains its original EraError; an interrupt still
        propagates after cleanup. E_SAVE_IO describes the host filesystem, not
        a claimed match to the native engine's Windows exception text.
        """
        temporary = None
        try:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=path.parent, prefix='.writing-', suffix='.tmp', delete=False
                ) as f:
                    temporary = f.name
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError as exc:
            if path.is_dir() or isinstance(exc, IsADirectoryError):
                reason = '保存先のファイル名が既存のフォルダと衝突しています'
            elif isinstance(exc, (FileExistsError, NotADirectoryError)):
                reason = '保存先の親フォルダとファイルが衝突しています'
            elif isinstance(exc, PermissionError):
                reason = '保存先への書き込み権限がありません'
            elif exc.errno == errno.ENOSPC:
                reason = '保存先の空き容量が不足しています'
            elif exc.errno == errno.EROFS:
                reason = '保存先が読み取り専用です'
            else:
                reason = '保存先への書き込み中にファイルI/Oエラーが発生しました'
            # Use an overlay-relative name where available, keeping reports
            # useful without embedding an arbitrary host exception message.
            parts = path.parts
            display = (
                Path(*parts[parts.index('.pyemuera') :]).as_posix()
                if '.pyemuera' in parts
                else path.name
            )
            message = f'セーブデータを保存できません: {reason} ({display})'
            raise EraError(
                message, code='E_SAVE_IO', diagnostic_message=message
            ) from exc

    def write(self, slot, description=''):
        if self.format == 'json':
            return self._write_json(slot, description)
        from .native_store import snapshot
        from .native_save import encode_binary, encode_text

        path = self.native_path(slot)
        state = snapshot(self.vm, slot, description)
        if slot != 'global' and self.native_rng == 'restore':
            from .native_save import Record

            words = self.vm.rng.get_native(allow_reseed=self.allow_rng_reseed)
            state.variables['RANDDATA'] = Record(
                (625,), False, {(i,): v for i, v in enumerate(words) if v}
            )
            if self.vm.rng.algorithm == 'python-mt19937':
                self.vm.console.warning(
                    'native-export-rng',
                    'Explicitly reseeding SFMT for native export; the legacy Python stream is not preserved.',
                )
        if self.format == 'emuera-binary':
            raw = encode_binary(state)
        elif self.format == 'emuera-text':
            encoding = (
                'utf-8-sig'
                if self.vm.data.config.get(
                    'セーブデータをUTF-8で保存する', 'NO'
                ).upper()
                == 'YES'
                else 'cp932'
            )
            raw = encode_text(state, encoding)
        else:
            raise EraError('Unknown save format', code='E_ARGUMENT')
        self.atomic_write(path, raw)
        self._unmask(slot)
        return 1

    def inspect(self, slot):
        path = self.candidate(slot)
        if path is None:
            return None
        if path == self.path(slot):
            return self._inspect_json(slot)
        from .native_save import decode, MAX_BYTES
        from .native_store import validate_identity

        if path.stat().st_size > MAX_BYTES:
            raise EraError('Native save too large', code='E_SAVE')
        meta = decode(path.read_bytes(), slot == 'global', metadata_only=True)
        validate_identity(self.vm, meta, slot)
        meta['slot'] = slot
        return meta

    def check(self, slot):
        try:
            path = self.candidate(slot)
            if path is None:
                return 1, '----'
            if path != self.path(slot):
                from .native_store import check_file

                return check_file(self.vm, path, slot)
            state = self._inspect_json(slot)
            return 0, state['description']
        except EraError as exc:
            if exc.code == 'E_SAVE_CHECK_TEXT':
                return 4, exc.message
            status = {'E_SAVE_GAME': 2, 'E_SAVE_VERSION': 3}.get(exc.code, 4)
            messages = {
                2: '異なるゲームのセーブデータです',
                3: 'セーブデータのバーションが異なります',
                4: '読み込み中にエラーが発生しました',
            }
            return status, messages[status]
        except (OSError, UnicodeError):
            return 4, '読み込み中にエラーが発生しました'

    def load(self, slot):
        path = self.candidate(slot)
        if path is None:
            return 0
        if path == self.path(slot):
            return self._load_json(slot)
        from .native_store import load_file

        return load_file(self.vm, path, slot)

    def _tombstone(self, slot):
        from .native_store import safe_overlay

        self.path(slot)
        return safe_overlay(self.vm.data.root, 'deleted-saves', str(slot) + '.json')

    def _unmask(self, slot):
        p = self._tombstone(slot)
        if p.exists():
            p.unlink()

    def delete(self, slot):
        # Overlay deletion policy: hide the original even across restarts. The
        # manifest is written before unlinking either private format so an I/O
        # interruption cannot resurrect an older original/alternate slot.
        if type(slot) is not int or not 0 <= slot <= 99999:
            raise EraError('DELDATA slot must be 0..99999', code='E_ARGUMENT')
        marker = self._tombstone(slot)
        self.atomic_write(marker, b'{"format":"PyEmueraDeletedSave1"}\n')
        for p in (self.path(slot), self.native_path(slot)):
            if p.exists():
                p.unlink()
        self.vm.console.warning(
            'delete-original-policy',
            'DELDATA removes private saves and masks the original in .pyemuera/deleted-saves; original .sav files are not deleted.',
        )
