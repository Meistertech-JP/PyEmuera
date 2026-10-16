"""Emuera 1824 binary chara_*.dat import/export, with read-only originals.

Source: VariableEvaluator.SaveChara/LoadChara/GetDatFiles; CharacterData binary
serializer. Registration indices, not CSV NO values; ordered multi-character
exports; an import appends without resetting the current game, globals or RNG.
"""

from __future__ import annotations
from dataclasses import dataclass
from itertools import product
import math
import re
import struct
from . import native_save as codec
from .native_store import safe_overlay, validate_identity
from .errors import EraError
from .expr import evaluate, integer
from .text import split_args


def fail(text, code='E_CHARADATA'):
    return EraError(text, code=code)


def name_check(value, pattern=False):
    if not isinstance(value, str):
        raise fail('Character-data filename must be a string', 'E_TYPE')
    invalid = '<>:"/\\|' + ('' if pattern else '*?')
    if (
        not value
        or any(ord(c) < 32 or c in invalid for c in value)
        or value[-1] in ' .'
    ):
        raise fail(
            'Invalid character-data name (no paths or reserved filename characters)',
            'E_PATH',
        )
    if len(value.encode('utf-16-le', errors='surrogatepass')) // 2 > 200:
        raise fail('Character-data filename length limit', 'E_LIMIT')
    return value


def paths(vm, name):
    name = name_check(name)
    basename = 'chara_' + name + '.dat'
    private = safe_overlay(vm.data.root, 'character-data', basename)
    folder = next(
        (
            p
            for p in vm.data.root.iterdir()
            if p.name.casefold() == 'dat' and p.is_dir()
        ),
        vm.data.root / 'dat',
    )
    original = folder / basename
    if folder.is_dir():
        original = next(
            (p for p in folder.iterdir() if p.name.casefold() == basename.casefold()),
            original,
        )
    # Match Windows file casing for private reads as well.
    if private.parent.is_dir():
        private = next(
            (
                p
                for p in private.parent.iterdir()
                if p.name.casefold() == basename.casefold()
            ),
            private,
        )
    for p in (private, original):
        if p.is_symlink() or not p.resolve().is_relative_to(vm.data.root):
            raise fail('Character-data path escapes its game', 'E_PATH')
    return private, original


@dataclass
class CharaData:
    gamecode: int
    version: int
    description: str
    characters: list

    def metadata(self):
        return {
            'native_gamecode': self.gamecode,
            'game_version': self.version,
            'description': self.description,
            'global_save': False,
            'character_count': len(self.characters),
        }


def encode(state):
    if len(state.characters) > codec.MAX_CHARS:
        raise fail('Character count limit', 'E_LIMIT')
    w = codec.BinaryWriter()
    w.put(
        codec.MAGIC + struct.pack('<IIBqq', 1808, 0, 3, state.gamecode, state.version)
    )
    w.string(state.description)
    w.put(struct.pack('<q', len(state.characters)))
    for c in state.characters:
        for user in (False, True):
            members = [(n, r) for n, r in sorted(c.items()) if r.user == user]
            if user and members:
                w.put(b'\xfd')
            for name, rec in members:
                if len(rec.dims) > 2:
                    raise fail('Emuera 1824 character arrays are at most 2D')
                w.record(name, rec)
        w.put(b'\xfe')
    w.put(b'\xff')
    return w.stream.getvalue()


def decode(data, metadata_only=False):
    r = codec.BinaryReader(data)
    if r.read(8) != codec.MAGIC:
        raise fail('Character-data requires native binary format', 'E_SAVE_FORMAT')
    version = r.unpack('I')
    extensions = r.unpack('I')
    if version != 1808 or extensions > 1024:
        raise fail('Unsupported native character-data header', 'E_SAVE_FORMAT')
    r.read(extensions * 4)
    if r.byte() != 3:
        raise fail('Expected native CharVar type (3)', 'E_SAVE_FORMAT')
    state = CharaData(r.unpack('q'), r.unpack('q'), r.string(), [])
    # CHKCHARADATA in src1824 only checks header, identity and description.
    if metadata_only:
        return state
    n = r.unpack('q')
    if not 0 <= n <= codec.MAX_CHARS:
        raise fail('Invalid character-data count', 'E_SAVE_FORMAT')
    for _ in range(n):
        state.characters.append(r.records(0xFE))
    if r.byte() != 0xFF or r.stream.read(1):
        raise fail('Missing EOF or trailing character-data payload', 'E_SAVE_FORMAT')
    return state


def read(vm, name, metadata_only=False):
    private, original = paths(vm, name)
    path = private if private.is_file() else original
    if not path.is_file():
        return None
    if path.stat().st_size > codec.MAX_BYTES:
        raise fail('Character-data file too large', 'E_LIMIT')
    return decode(path.read_bytes(), metadata_only)


def snapshot(vm, indices, description):
    variables = {
        n: v
        for n, v in vm.data.variables.items()
        if v.character
        and not v.readonly
        and not v.forbidden
        and (v.saved or n in codec.BUILTIN_CHAR)
    }
    chars = []
    budget = 0
    for index in indices:
        c = {}
        for name, v in variables.items():
            if len(v.dims) > 2:
                raise fail('Unsupported 3D character array', 'E_SAVE_SCHEMA')
            values = {
                key[1:]: value for key, value in v.values.items() if key[0] == index
            }
            if v.default not in (0, ''):
                budget += math.prod(v.dims)
                if budget > codec.MAX_VALUES:
                    raise fail('Character-data expansion budget', 'E_LIMIT')
                values = {
                    key: values.get(key, v.default)
                    for key in product(*(range(d) for d in v.dims))
                }
            values = {k: x for k, x in values.items() if x != ('' if v.string else 0)}
            budget += len(values)
            if budget > codec.MAX_VALUES:
                raise fail('Character-data value budget', 'E_LIMIT')
            c[name] = codec.Record(
                v.dims, v.string, values, name not in codec.BUILTIN_CHAR
            )
        chars.append(c)
    return CharaData(
        vm.get('GAMEBASE_GAMECODE'), vm.get('GAMEBASE_VERSION'), description, chars
    )


def append(vm, state):
    start = vm.data.character_count
    if start + len(state.characters) > codec.MAX_CHARS:
        raise fail('Character count limit', 'E_LIMIT')
    variables = {
        n: v
        for n, v in vm.data.variables.items()
        if v.character and not v.readonly and not v.forbidden
    }
    staged = {n: dict(v.values) for n, v in variables.items()}
    budget = 0
    clipped = {}
    # Fresh character records are zero initialized, not loaded from CSV templates.
    for offset, records in enumerate(state.characters):
        index = start + offset
        for name, v in variables.items():
            if v.default not in (0, ''):
                budget += math.prod(v.dims)
                if budget > codec.MAX_VALUES:
                    raise fail('Character-data default budget', 'E_LIMIT')
                for key in product(*(range(d) for d in v.dims)):
                    staged[name][(index,) + key] = '' if v.string else 0
        for name, rec in records.items():
            v = variables.get(name)
            if (
                v is None
                or rec.string != v.string
                or len(rec.dims) != len(v.dims)
                or (rec.user and not v.saved)
            ):
                if rec.values:
                    raise fail(
                        'Unmapped nonempty character-data field: ' + name,
                        'E_SAVE_SCHEMA',
                    )
                continue
            for key, value in rec.values.items():
                if any(k >= d for k, d in zip(key, v.dims)):
                    clipped[name] = clipped.get(name, 0) + 1
                    continue
                full = (index,) + key
                v.validate(full)
                if value == v.default:
                    staged[name].pop(full, None)
                else:
                    staged[name][full] = value
    for name, values in staged.items():
        variables[name].values = values
    vm.data.character_count = start + len(state.characters)
    if clipped:
        vm.console.warning(
            'dat-clipped',
            'Character-data values clipped to target dimensions: '
            + ', '.join(sorted(clipped)),
        )
    if vm.journal:
        vm.journal.note(
            'character_data_append', count=len(state.characters), clipped=clipped
        )


def execute(vm, spec, arg):
    name = spec['name']
    if name not in ('SAVECHARA', 'LOADCHARA'):
        return False
    a = vm.args(arg)
    if name == 'SAVECHARA':
        if len(a) < 3 or len(a) > codec.MAX_CHARS + 2:
            raise fail(
                'SAVECHARA requires name, description, one or more registration indices',
                'E_ARGUMENT',
            )
        filename = name_check(a[0])
        if not isinstance(a[1], str):
            raise fail('SAVECHARA description must be a string', 'E_TYPE')
        indices = [integer(x) for x in a[2:]]
        if any(not 0 <= i < vm.data.character_count for i in indices):
            raise fail('SAVECHARA registration index outside character list', 'E_INDEX')
        if len(set(indices)) != len(indices):
            raise fail('SAVECHARA duplicate character registration index', 'E_ARGUMENT')
        path, _ = paths(vm, filename)
        state = snapshot(vm, indices, a[1])
        vm.saves.atomic_write(path, encode(state))
        # src1824 does not set RESULT on successful SAVECHARA.
    else:
        if len(a) != 1:
            raise fail('LOADCHARA takes one name', 'E_ARGUMENT')
        vm.set('RESULT', 0)
        try:
            state = read(vm, a[0])
            if state is None:
                return True
            validate_identity(vm, state.metadata(), 0)
        except EraError as exc:
            if exc.code in ('E_SAVE_GAME', 'E_SAVE_VERSION'):
                return True
            if exc.code == 'E_SAVE_FORMAT' and (
                'Expected native CharVar' in exc.message
                or 'requires native binary' in exc.message
            ):
                return True
            raise
        append(vm, state)
        vm.set('RESULT', 1)
    return True


def function(vm, name, nodes):
    a = [evaluate(n, vm) for n in nodes]
    if name == 'CHKCHARADATA':
        try:
            state = read(vm, a[0], True)
            if state is None:
                code, message = 1, '----'
            else:
                validate_identity(vm, state.metadata(), 0)
                code, message = 0, state.description
        except EraError as exc:
            if exc.code in ('E_PATH', 'E_TYPE'):
                raise
            code = {'E_SAVE_GAME': 2, 'E_SAVE_VERSION': 3}.get(exc.code, 4)
            message = exc.message
        except (OSError, UnicodeError):
            code, message = 4, 'Character-data read failed'
        vm.set('RESULTS', message)
        return code
    if name == 'FIND_CHARADATA':
        pattern = name_check(a[0] if a and a[0] is not None else '*', True)
        regex = re.compile(
            '^' + re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.') + '$',
            re.IGNORECASE,
        )
        private, _ = paths(vm, '_probe')
        folder = next(
            (
                p
                for p in vm.data.root.iterdir()
                if p.name.casefold() == 'dat' and p.is_dir()
            ),
            vm.data.root / 'dat',
        )
        names = {}
        for directory in (folder, private.parent):
            if not directory.is_dir():
                continue
            if not directory.resolve().is_relative_to(vm.data.root):
                raise fail('Character-data directory escapes game', 'E_PATH')
            for p in directory.iterdir():
                if (
                    not p.is_file()
                    or p.is_symlink()
                    or not p.name.lower().startswith('chara_')
                    or p.suffix.lower() != '.dat'
                ):
                    continue
                value = p.stem[6:]
                if value and regex.fullmatch(value):
                    names[value.casefold()] = value
        values = sorted(names.values(), key=lambda x: (x.casefold(), x))
        dest = vm.lookup('RESULTS')
        for i, value in enumerate(values[: dest.dims[0]]):
            dest.set((i,), value)
        return len(values)
    raise fail('Unknown character-data function ' + name)
