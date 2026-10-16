"""Data-only codecs for Emuera 1.8.2.4 saves (not .NET object deserialization).

Format reference: Emuera 1.8.2.4 source (src1824.zip), Sub/EraDataStream.cs,
EraBinaryDataReader.cs and EraBinaryDataWriter.cs; VariableCode.cs,
CharacterData.cs and VariableData.cs. See THIRD_PARTY_NOTICES.md.
Text extensions 1700/1708/1729/1803/1808 and binary wire version 1808.
The typo STRAT in the text marker is intentional and part of the format.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from itertools import product
import io
import math
import re
import struct
from .errors import EraError

MAGIC = b'\x89ERA\r\n\x1a\n'
FIN = '__FINISHED'
SEP = '__EMU_SEPARATOR__'
MARKERS = {
    '__EMUERA_STRAT__': 1700,
    **{f'__EMUERA_{v}_STRAT__': v for v in (1708, 1729, 1803, 1808)},
}
MAX_BYTES = 128 * 1024 * 1024
MAX_CHARS = 100000
MAX_VALUES = 4_000_000
MAX_DIM = 1_000_000
MAX_RECORDS = 100000

# Positional legacy blocks, including the deliberately unused eramaker slots.
LEGACY_GLOBAL_NUM = (
    tuple(
        'DAY MONEY ITEM FLAG TFLAG UP PALAMLV EXPLV EJAC DOWN RESULT COUNT TARGET ASSI MASTER NOITEM LOSEBASE SELECTCOM ASSIPLAY PREVCOM NOTUSE_14 NOTUSE_15 TIME ITEMSALES PLAYER NEXTCOM PBAND BOUGHT NOTUSE_1C NOTUSE_1D'.split()
    )
    + tuple('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    + tuple('NOTUSE_38 NOTUSE_39 NOTUSE_3A NOTUSE_3B'.split())
)
LEGACY_CHAR_NUM = tuple(
    'BASE MAXBASE ABL TALENT EXP MARK PALAM SOURCE EX CFLAG JUEL RELATION EQUIP TEQUIP STAIN GOTJUEL NOWEX'.split()
)
CHAR_STR = ('NAME', 'CALLNAME')
CHAR_INT = ('ISASSI', 'NO')
CHAR_EXT = (
    ('NICKNAME', 'MASTERNAME'),
    (),
    ('CSTR',),
    ('DOWNBASE', 'CUP', 'CDOWN', 'TCVAR'),
    (),
    ('CDFLAG',),
)
GLOBAL_EXT = (
    (),
    (),
    ('TSTR',),
    ('RANDDATA',),
    (),
    ('DITEMTYPE', 'DA', 'DB', 'DC', 'DD', 'DE'),
    (),
    ('TA', 'TB'),
)
BUILTIN_NORMAL = (
    set(LEGACY_GLOBAL_NUM) | {'SAVESTR'} | {n for group in GLOBAL_EXT for n in group}
)
BUILTIN_CHAR = (
    set(LEGACY_CHAR_NUM)
    | set(CHAR_STR)
    | set(CHAR_INT)
    | {n for group in CHAR_EXT for n in group}
)
BUILTIN_GLOBAL = {'GLOBAL', 'GLOBALS'}


def failure(message: str, code='E_SAVE_FORMAT') -> EraError:
    return EraError(message, code=code)


def int64(value: str) -> int:
    if not re.fullmatch(r'[+-]?[0-9]+', value.strip()):
        raise failure('Invalid integer in native save')
    n = int(value)
    if not -(1 << 63) <= n < (1 << 63):
        raise failure('Native save integer exceeds Int64')
    return n


@dataclass
class Record:
    dims: tuple[int, ...]
    string: bool = False
    values: dict[tuple[int, ...], int | str] = field(default_factory=dict)
    user: bool = False

    def default(self):
        return '' if self.string else 0


@dataclass
class NativeSave:
    gamecode: int
    game_version: int
    description: str = ''
    global_save: bool = False
    characters: list[dict[str, Record]] = field(default_factory=list)
    variables: dict[str, Record] = field(default_factory=dict)
    wire: str = 'text'
    extension: int = 1808
    encoding: str = 'cp932'

    def metadata(self):
        return {
            'format': f'Emuera-{self.wire}-{self.extension}',
            'native_gamecode': self.gamecode,
            'game_version': self.game_version,
            'description': self.description,
            'character_count': len(self.characters),
            'global_save': self.global_save,
            'encoding': self.encoding,
        }


class TextReader:
    def __init__(self, raw: bytes, encoding='auto'):
        if len(raw) > MAX_BYTES:
            raise failure('Native save exceeds size limit', 'E_LIMIT')
        if encoding == 'auto':
            # EraDataReader uses StreamReader(file, Config.Encode), exactly
            # as game sources do. Structural/schema validation still precedes
            # every live-state commit; JSON and binary codecs are unchanged.
            from .source_encoding import decode_source

            text, codec = decode_source(raw)
        else:
            codec = (
                'utf-8-sig'
                if raw.startswith(b'\xef\xbb\xbf')
                else (
                    'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else encoding
                )
            )
            try:
                text = raw.decode(codec)
            except (UnicodeError, LookupError) as exc:
                raise failure('Native text save encoding is invalid') from exc
        self.encoding = codec
        if text.count('\n') + text.count('\r') > 2 * (MAX_VALUES + 100000):
            raise failure('Native text line budget exceeded', 'E_LIMIT')
        self.lines = re.split(r'\r\n|\r|\n', text)
        if self.lines and self.lines[-1] == '':
            self.lines.pop()
        self.pos = 0
        self.values = 0
        self.record_count = 0

    def record_budget(self, count=1):
        self.record_count += count
        if self.record_count > MAX_RECORDS:
            raise failure("Native record budget exceeded", "E_LIMIT")

    def line(self):
        if self.pos >= len(self.lines):
            raise failure(f'Truncated native text save near line {self.pos + 1}')
        result = self.lines[self.pos]
        self.pos += 1
        return result

    def number(self):
        return int64(self.line())

    def budget(self, n=1):
        self.values += n
        if self.values > MAX_VALUES:
            raise failure('Native save value budget exceeded', 'E_LIMIT')

    def array(self, string=False, rank=1, user=False):
        self.record_budget()
        values = {}
        shape = [0] * rank

        def row(line, prefix):
            entries = line.split(',') if line else []
            shape[-1] = max(shape[-1], len(entries))
            for k, item in enumerate(entries):
                value = int64(item)
                if value or user:
                    self.budget()
                    values[prefix + (k,)] = value

        if string and rank != 1:
            raise failure(
                'Emuera 1824 text saves cannot contain multidimensional string arrays; use binary'
            )
        i = 0
        while True:
            line = self.line()
            if line == FIN:
                break
            if line == SEP:
                raise failure('Missing native array terminator')
            if i >= MAX_DIM:
                raise failure('Native array extent limit', 'E_LIMIT')
            if rank == 1:
                value = line if string else int64(line)
                if value != ('' if string else 0) or user:
                    self.budget()
                    values[(i,)] = value
            elif rank == 2:
                row(line, (i,))
            elif rank == 3:
                if not re.fullmatch(r'[0-9]+\{', line):
                    raise failure('Invalid native 3D plane marker')
                j = 0
                while True:
                    sub = self.line()
                    if sub == '}':
                        break
                    if j >= MAX_DIM:
                        raise failure('Native array extent limit', 'E_LIMIT')
                    row(sub, (i, j))
                    j += 1
                shape[1] = max(shape[1], j)
            i += 1
        shape[0] = i
        if any(n > MAX_DIM for n in shape):
            raise failure('Native array extent limit', 'E_LIMIT')
        return Record(tuple(shape), string, values, user)

    def group(self, result, string, rank, user=False):
        while True:
            line = self.line()
            if line == SEP:
                return
            if line == FIN:
                raise failure('Unexpected terminator in native extension group')
            if rank == 0:
                self.record_budget()
                name, separator, value = line.partition(':')
                if not separator:
                    raise failure('Missing scalar separator in native extension')
                value = value if string else int64(value)
                self.budget()
                record = Record(
                    (),
                    string,
                    {(): value} if value != ('' if string else 0) else {},
                    user,
                )
            else:
                name = line
                record = self.array(string, rank, user)
            name = validate_name(name)
            if name in result:
                raise failure('Duplicate native variable: ' + name)
            result[name] = record


def validate_name(name):
    if (
        not name
        or len(name) > 1024
        or any(ord(c) < 32 for c in name)
        or name in (SEP, FIN)
    ):
        raise failure('Invalid native variable name')
    return name.upper()


def decode_text(raw: bytes, global_save=False, encoding='auto', metadata_only=False):
    r = TextReader(raw, encoding)
    save = NativeSave(
        r.number(), r.number(), global_save=global_save, encoding=r.encoding
    )
    if not global_save:
        save.description = r.line()
        count = r.number()
        if not 0 <= count <= MAX_CHARS:
            raise failure('Invalid native character count')
        if metadata_only:
            # No allocations proportional to a potentially corrupt count.
            meta = save.metadata()
            meta['character_count'] = count
            return meta
        for _ in range(count):
            c = {}
            for name in CHAR_STR:
                r.budget()
                r.record_budget()
                value = r.line()
                c[name] = Record((), True, {(): value} if value else {})
            for name in CHAR_INT:
                r.budget()
                r.record_budget()
                value = r.number()
                c[name] = Record((), False, {(): value} if value else {})
            for name in LEGACY_CHAR_NUM:
                c[name] = r.array()
            save.characters.append(c)
        for name in LEGACY_GLOBAL_NUM:
            save.variables[name] = r.array()
        save.variables['SAVESTR'] = r.array(True)
    else:
        if metadata_only:
            return save.metadata()
        save.variables['GLOBAL'] = r.array()
        save.variables['GLOBALS'] = r.array(True)
    # eramaker files have no extension. The reference seeks the marker.
    marker = next(
        (i for i in range(r.pos, len(r.lines)) if r.lines[i] in MARKERS), None
    )
    if marker is None:
        save.extension = 0
        return save
    r.pos = marker + 1
    save.extension = MARKERS[r.lines[marker]]
    basic = [(True, 0), (False, 0), (True, 1), (False, 1)]
    if not global_save:
        char_types = basic + ([(True, 2), (False, 2)] if save.extension >= 1803 else [])
        for c in save.characters:
            for string, rank in char_types:
                r.group(c, string, rank)
        global_types = (
            basic
            + ([(True, 2), (False, 2)] if save.extension >= 1708 else [])
            + ([(True, 3), (False, 3)] if save.extension >= 1729 else [])
        )
        for string, rank in global_types:
            r.group(save.variables, string, rank)
    if save.extension >= 1808:
        for rank in (1, 2, 3):
            for string in (True, False):
                r.group(save.variables, string, rank, user=True)
    if any(line not in ('', SEP) for line in r.lines[r.pos :]):
        raise failure('Unexpected trailing data in native text save')
    return save


class BinaryReader:
    def __init__(self, raw):
        if len(raw) > MAX_BYTES:
            raise failure('Native save exceeds size limit', 'E_LIMIT')
        self.stream = io.BytesIO(raw)
        self.values = 0
        self.record_count = 0

    def read(self, n):
        b = self.stream.read(n)
        if len(b) != n:
            raise failure(f'Truncated native binary save at byte {self.stream.tell()}')
        return b

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.read(struct.calcsize('<' + fmt)))[0]

    def byte(self):
        return self.read(1)[0]

    def string(self):
        length = 0
        for shift in range(0, 35, 7):
            b = self.byte()
            if shift == 28 and b > 7:
                raise failure('Invalid .NET string length')
            length |= (b & 0x7F) << shift
            if not b & 0x80:
                break
        else:
            raise failure('Invalid .NET string length')
        if length > MAX_BYTES or length % 2:
            raise failure('Invalid UTF-16 string byte length')
        try:
            return self.read(length).decode('utf-16-le', errors='surrogatepass')
        except UnicodeError as exc:
            raise failure('Invalid UTF-16 in native save') from exc

    def number(self, marker=None):
        b = self.byte() if marker is None else marker
        if b <= 0xCF:
            return b
        if b in (0xD0, 0xD1, 0xD2):
            return self.unpack({0xD0: 'h', 0xD1: 'i', 0xD2: 'q'}[b])
        raise failure('Invalid native packed integer')

    def record(self, typ, user=False):
        self.record_count += 1
        if self.record_count > MAX_RECORDS:
            raise failure("Native record budget exceeded", "E_LIMIT")
        if typ not in (0, 1, 2, 3, 0x10, 0x11, 0x12, 0x13):
            raise failure(f'Unsupported native variable type 0x{typ:02x}')
        rank = typ & 0x0F
        string = bool(typ & 0x10)
        if rank == 0:
            value = self.string() if string else self.number()
            self.values += 1
            if self.values > MAX_VALUES:
                raise failure('Native value budget exceeded', 'E_LIMIT')
            return Record(
                (), string, {(): value} if value != ('' if string else 0) else {}, user
            )
        dims = tuple(self.unpack('i') for _ in range(rank))
        if any(n < 0 or n > MAX_DIM for n in dims):
            raise failure('Invalid native binary dimensions')
        values = {}
        cursor = [0] * rank
        while True:
            b = self.byte()
            if b == 0xFF:
                break
            if b in (0xF0, 0xF1, 0xF2):
                level = b - 0xF0
                axis = rank - 1 - level
                if axis < 0 or any(cursor[j] for j in range(axis + 1, rank)):
                    raise failure('Invalid zero-run position in native array')
                count = self.number()
                if (
                    count <= 0
                    or cursor[axis] + count > dims[axis]
                    or any(cursor[j] >= dims[j] for j in range(axis))
                ):
                    raise failure('Native zero-run exceeds array bounds')
                cursor[axis] += count
                continue
            if b in (0xE0, 0xE1):
                axis = rank - 2 - (b - 0xE0)
                if axis < 0 or any(cursor[j] >= dims[j] for j in range(axis + 1)):
                    raise failure('Invalid native array row/plane terminator')
                cursor[axis] += 1
                for j in range(axis + 1, rank):
                    cursor[j] = 0
                continue
            if any(k >= size for k, size in zip(cursor, dims)):
                raise failure('Native array element exceeds declared bounds')
            if string:
                if b != 0xD8:
                    raise failure('Invalid native string element marker')
                value = self.string()
            else:
                value = self.number(b)
            if value != ('' if string else 0):
                self.values += 1
                if self.values > MAX_VALUES:
                    raise failure('Native value budget exceeded', 'E_LIMIT')
                values[tuple(cursor)] = value
            cursor[-1] += 1
        return Record(dims, string, values, user)

    def records(self, ending):
        result = {}
        user = False
        while True:
            typ = self.byte()
            if typ == ending:
                return result
            if typ == 0xFD:
                if ending != 0xFE or user:
                    raise failure('Unexpected native character separator')
                user = True
                continue
            if typ in (0xFE, 0xFF):
                raise failure('Unexpected native record terminator')
            name = validate_name(self.string())
            if name in result:
                raise failure('Duplicate native variable: ' + name)
            result[name] = self.record(typ, user)


def decode_binary(raw, metadata_only=False):
    r = BinaryReader(raw)
    if r.read(8) != MAGIC:
        raise failure('Native binary magic mismatch')
    version = r.unpack('I')
    count = r.unpack('I')
    if version != 1808:
        raise failure(f'Unsupported native binary version {version}')
    if count > 1024:
        raise failure('Native header extension count limit')
    r.read(count * 4)
    typ = r.byte()
    if typ not in (0, 1):
        raise failure('Only normal and global .sav types are supported, not .dat')
    save = NativeSave(
        r.unpack('q'),
        r.unpack('q'),
        r.string(),
        typ == 1,
        wire='binary',
        encoding='utf-16-le',
    )
    n = 0 if typ == 1 else r.unpack('q')
    if not 0 <= n <= MAX_CHARS:
        raise failure('Invalid native character count')
    if metadata_only:
        meta = save.metadata()
        meta['character_count'] = n
        return meta
    for _ in range(n):
        save.characters.append(r.records(0xFE))
    save.variables = r.records(0xFF)
    for name, rec in save.variables.items():
        rec.user = name not in (BUILTIN_GLOBAL if save.global_save else BUILTIN_NORMAL)
    if r.stream.read(1):
        raise failure('Unexpected trailing native binary data')
    return save


def decode(raw, global_save=False, encoding='auto', metadata_only=False):
    if raw.startswith(MAGIC):
        result = decode_binary(raw, metadata_only)
        actual = result['global_save'] if metadata_only else result.global_save
        if actual != global_save:
            raise failure('Native normal/global file type mismatch')
        return result
    return decode_text(raw, global_save, encoding, metadata_only)


class BinaryWriter:
    def __init__(self):
        self.stream = io.BytesIO()

    def put(self, b):
        self.stream.write(b)
        if self.stream.tell() > MAX_BYTES:
            raise failure('Native output exceeds size limit', 'E_LIMIT')

    def number(self, n):
        if type(n) is not int or not -(1 << 63) <= n < (1 << 63):
            raise failure('Invalid native Int64 value')
        if 0 <= n <= 0xCF:
            self.put(bytes([n]))
        elif -(1 << 15) <= n < (1 << 15):
            self.put(b'\xd0' + struct.pack('<h', n))
        elif -(1 << 31) <= n < (1 << 31):
            self.put(b'\xd1' + struct.pack('<i', n))
        else:
            self.put(b'\xd2' + struct.pack('<q', n))

    def string(self, s):
        data = s.encode('utf-16-le', errors='surrogatepass')
        length = len(data)
        while length >= 0x80:
            self.put(bytes([(length & 0x7F) | 0x80]))
            length >>= 7
        self.put(bytes([length]))
        self.put(data)

    def record(self, name, rec):
        validate_record(name, rec)
        rank = len(rec.dims)
        self.put(bytes([rank | (0x10 if rec.string else 0)]))
        self.string(name)

        def value(v):
            if rec.string:
                if rank:
                    self.put(b'\xd8')
                self.string(v)
            else:
                self.number(v)

        if rank == 0:
            value(rec.values.get((), rec.default()))
            return
        self.put(struct.pack('<' + 'i' * rank, *rec.dims))
        # Traverse only nonempty rows/planes, not a dense array.
        tree = {}
        for key, v in sorted(rec.values.items()):
            if v == rec.default():
                continue
            branch = tree
            for index in key[:-1]:
                branch = branch.setdefault(index, {})
            branch[key[-1]] = v

        def emit(branch, depth):
            cursor = 0
            for index, child in sorted(branch.items()):
                if index > cursor:
                    self.put(bytes([0xF0 + rank - 1 - depth]))
                    self.number(index - cursor)
                if depth == rank - 1:
                    value(child)
                else:
                    emit(child, depth + 1)
                    self.put(bytes([0xE0 + rank - 2 - depth]))
                cursor = index + 1

        emit(tree, 0)
        self.put(b'\xff')


def validate_record(name, rec):
    validate_name(name)
    if len(rec.dims) > 3 or any(
        type(n) is not int or not 0 <= n <= MAX_DIM for n in rec.dims
    ):
        raise failure('Invalid native record dimensions')
    if len(rec.values) > MAX_VALUES:
        raise failure('Native record value budget', 'E_LIMIT')
    for key, value in rec.values.items():
        if len(key) != len(rec.dims) or any(
            type(k) is not int or not 0 <= k < n for k, n in zip(key, rec.dims)
        ):
            raise failure('Invalid native output array index')
        if (
            rec.string != isinstance(value, str)
            or not rec.string
            and type(value) is not int
        ):
            raise failure('Native record type mismatch')
        if not rec.string and not -(1 << 63) <= value < (1 << 63):
            raise failure('Native Int64 overflow')


def encode_binary(save):
    w = BinaryWriter()
    w.put(
        MAGIC
        + struct.pack(
            '<IIBqq', 1808, 0, int(save.global_save), save.gamecode, save.game_version
        )
    )
    w.string(save.description)
    if not save.global_save:
        w.put(struct.pack('<q', len(save.characters)))
        for c in save.characters:
            for name, rec in sorted(c.items()):
                if not rec.user:
                    w.record(name, rec)
            users = [(name, rec) for name, rec in sorted(c.items()) if rec.user]
            if users:
                w.put(b'\xfd')
                for name, rec in users:
                    if len(rec.dims) > 2:
                        raise failure(
                            'Emuera 1824 does not support 3D character save arrays'
                        )
                    w.record(name, rec)
            w.put(b'\xfe')
    for name, rec in sorted(save.variables.items()):
        w.record(name, rec)
    w.put(b'\xff')
    return w.stream.getvalue()


class TextWriter:
    def __init__(self):
        self.lines = []
        self.size = 0

    def line(self, value, *, data=False):
        s = str(value)
        if '\r' in s or '\n' in s or data and (s in (FIN, SEP) or s in MARKERS):
            raise failure(
                'String cannot be represented safely in native text format; select emuera-binary'
            )
        self.size += len(s) + 2
        if self.size > MAX_BYTES or len(self.lines) > MAX_VALUES:
            raise failure('Native text output limit', 'E_LIMIT')
        self.lines.append(s)

    def array(self, rec):
        rank = len(rec.dims)
        values = {k: v for k, v in rec.values.items() if v != rec.default()}
        if rec.string and rank > 1:
            raise failure(
                'Emuera 1824 text cannot save multidimensional strings; select emuera-binary'
            )
        # User initializers can be nonzero. Unlike binary/legacy arrays, the
        # text extension does NOT clear omitted tails in the reference reader.
        # Emit explicit zeros for the full user array to preserve its state.
        if rec.user and math.prod(rec.dims) > MAX_VALUES:
            raise failure('Native text user array expansion budget', 'E_LIMIT')
        limit = rec.dims[0] if rec.user else max((k[0] + 1 for k in values), default=0)
        if rank == 1:
            for i in range(limit):
                self.line(values.get((i,), rec.default()), data=rec.string)
        elif rank in (2, 3):

            def row(prefix):
                n = (
                    rec.dims[-1]
                    if rec.user
                    else max((k[-1] + 1 for k in values if k[:-1] == prefix), default=0)
                )
                self.line(','.join(str(values.get(prefix + (j,), 0)) for j in range(n)))

            for i in range(limit):
                if rank == 2:
                    row((i,))
                else:
                    self.line(str(i) + '{')
                    m = (
                        rec.dims[1]
                        if rec.user
                        else max((k[1] + 1 for k in values if k[0] == i), default=0)
                    )
                    for j in range(m):
                        row((i, j))
                    self.line('}')
        else:
            raise failure('Invalid text array rank')
        self.line(FIN)

    def group(self, records, string, rank):
        for name, rec in sorted(records.items()):
            if rec.string != string or len(rec.dims) != rank:
                continue
            validate_record(name, rec)
            if string and rank > 1:
                raise failure(
                    'Emuera 1824 text cannot save multidimensional strings; select emuera-binary'
                )
            values = {k: v for k, v in rec.values.items() if v != rec.default()}
            if not values and not rec.user:
                continue
            if rank == 0:
                self.line(name + ':' + str(values.get((), rec.default())), data=True)
            else:
                self.line(name)
                self.array(rec)
        self.line(SEP)


def encode_text(save, encoding='cp932'):
    w = TextWriter()
    w.line(save.gamecode)
    w.line(save.game_version)
    default = lambda string=False, rank=1: Record((0,) * rank, string)
    if not save.global_save:
        w.line(save.description, data=True)
        w.line(len(save.characters))
        for c in save.characters:
            if any(r.user for r in c.values()):
                raise failure(
                    'User CHARADATA saves require emuera-binary in Emuera 1824'
                )
            for name in CHAR_STR + CHAR_INT:
                rec = c.get(name, default(name in CHAR_STR, 0))
                w.line(rec.values.get((), rec.default()), data=rec.string)
            for name in LEGACY_CHAR_NUM:
                rec = c.get(name, default())
                validate_record(name, rec)
                w.array(rec)
        for name in LEGACY_GLOBAL_NUM + ('SAVESTR',):
            rec = save.variables.get(name, default(name == 'SAVESTR'))
            validate_record(name, rec)
            w.array(rec)
    else:
        w.array(save.variables.get('GLOBAL', default()))
        w.array(save.variables.get('GLOBALS', default(True)))
    w.line('__EMUERA_1808_STRAT__')
    if not save.global_save:
        for c in save.characters:
            for index, names in enumerate(CHAR_EXT):
                w.group({n: c[n] for n in names if n in c}, index % 2 == 0, index // 2)
        for index, names in enumerate(GLOBAL_EXT):
            w.group(
                {n: save.variables[n] for n in names if n in save.variables},
                index % 2 == 0,
                index // 2,
            )
    users = {n: r for n, r in save.variables.items() if r.user}
    for rank in (1, 2, 3):
        for string in (True, False):
            w.group(users, string, rank)
    try:
        raw = ('\r\n'.join(w.lines) + '\r\n').encode(encoding)
    except UnicodeError as exc:
        raise failure(
            'Native text encoding cannot represent a string; select emuera-binary'
        ) from exc
    if len(raw) > MAX_BYTES:
        raise failure('Native output exceeds size limit', 'E_LIMIT')
    return raw
