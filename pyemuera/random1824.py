"""SFMT19937 and Emuera 1824's ordered-u32 / modulo range adapter.

Compatibility reference: supplied _Library/SFMT.cs (MTRandom); this is not
Python's MT19937 and not SFMT's little-endian uint64 interface. Emuera takes
TWO consecutive uint32 words: first << 32 | second, then unsigned modulo max.
See THIRD_PARTY_NOTICES.md. Not for cryptographic use.
"""

from __future__ import annotations
import hashlib
import json
import random
import secrets
from .errors import EraError

MASK = 0xFFFFFFFF
ALGORITHM = 'sfmt19937-emuera1824'


def fail(message):
    return EraError(message, code='E_RANDOM_STATE')


class SFMT19937:
    def __init__(self, seed=0):
        self.seed(seed)

    def seed(self, value=0):
        if type(value) is not int:
            raise fail('SFMT seed must be an integer')
        words = [value & MASK]
        for i in range(1, 624):
            prev = words[-1]
            words.append((1812433253 * (prev ^ (prev >> 30)) + i) & MASK)
        inner = (words[0] & 1) ^ (words[3] & 0x13C9E684)
        if inner.bit_count() % 2 == 0:
            words[0] ^= 1
        self.words = words
        self.index = 624

    def _generate(self):
        # Direct fixed-19937 recurrence, preserving the reference's in-place
        # update order (high to low words within each 128-bit block).
        p = self.words
        b = 488
        c = 616
        d = 620
        for a in range(0, 624, 4):
            p[a + 3] = (
                p[a + 3]
                ^ (p[a + 3] << 8)
                ^ (p[a + 2] >> 24)
                ^ (p[c + 3] >> 8)
                ^ ((p[b + 3] >> 11) & 0xBFFFFFF6)
                ^ (p[d + 3] << 18)
            ) & MASK
            p[a + 2] = (
                p[a + 2]
                ^ (p[a + 2] << 8)
                ^ (p[a + 1] >> 24)
                ^ (p[c + 3] << 24)
                ^ (p[c + 2] >> 8)
                ^ ((p[b + 2] >> 11) & 0xBFFAFFFF)
                ^ (p[d + 2] << 18)
            ) & MASK
            p[a + 1] = (
                p[a + 1]
                ^ (p[a + 1] << 8)
                ^ (p[a] >> 24)
                ^ (p[c + 2] << 24)
                ^ (p[c + 1] >> 8)
                ^ ((p[b + 1] >> 11) & 0xDDFECB7F)
                ^ (p[d + 1] << 18)
            ) & MASK
            p[a] = (
                p[a]
                ^ (p[a] << 8)
                ^ (p[c + 1] << 24)
                ^ (p[c] >> 8)
                ^ ((p[b] >> 11) & 0xDFFFFFEF)
                ^ (p[d] << 18)
            ) & MASK
            c, d = d, a
            b = (b + 4) % 624
        self.index = 0

    def uint32(self):
        if self.index >= 624:
            self._generate()
        value = self.words[self.index]
        self.index += 1
        return value

    def uint64(self):
        return (self.uint32() << 32) | self.uint32()

    def randrange(self, start, stop=None):
        lo, hi = (0, start) if stop is None else (start, stop)
        if type(lo) is not int or type(hi) is not int or not 0 < hi - lo < 1 << 63:
            raise EraError(
                'RAND range must be positive and fit Int64', code='E_ARGUMENT'
            )
        return lo + self.uint64() % (hi - lo)

    def get_words(self):
        return self.words[:] + [self.index]

    def set_words(self, values):
        if (
            not isinstance(values, (list, tuple))
            or len(values) != 625
            or any(type(x) is not int or not -(1 << 63) <= x < 1 << 63 for x in values)
        ):
            raise fail('RANDDATA must contain exactly 625 Int64 elements')
        # Source casts the words to UInt32; retain that behavior. A negative
        # index would crash the host: reject it before mutating the live RNG.
        index = ((values[624] + (1 << 31)) % (1 << 32)) - (1 << 31)
        if index < 0:
            raise fail('RANDDATA index is negative after Int32 conversion')
        self.words = [x & MASK for x in values[:624]]
        self.index = index


class EngineRandom:
    """Versioned state plus backward-compatible a1-a7 Python JSON restoration.

    Newly constructed VMs use SFMT. Loading an old Python state retains its
    future sequence; RANDOMIZE and INITRAND intentionally enter SFMT mode.
    """

    def __init__(self, seed=None):
        self.algorithm = ALGORITHM
        self.impl = SFMT19937(secrets.randbits(32) if seed is None else seed)

    def seed(self, value=0):
        self.impl = SFMT19937(0 if value is None else value)
        self.algorithm = ALGORITHM

    def randrange(self, *args):
        return self.impl.randrange(*args)

    def getstate(self):
        if self.algorithm == 'python-mt19937':
            # Preserve the old JSON shape for old-stream consumers.
            return self.impl.getstate()
        return {
            'format': 'PyEmueraRNG1',
            'algorithm': ALGORITHM,
            'state': self.impl.get_words(),
        }

    def setstate(self, state):
        if isinstance(state, dict):
            if (
                set(state) != {'format', 'algorithm', 'state'}
                or state.get('format') != 'PyEmueraRNG1'
                or state.get('algorithm') != ALGORITHM
            ):
                raise fail('Unsupported RNG state schema or algorithm')
            trial = SFMT19937(0)
            trial.set_words(state['state'])
            self.impl = trial
            self.algorithm = ALGORITHM
        else:
            if not isinstance(state, (list, tuple)) or len(state) != 3:
                raise fail('Invalid legacy Python RNG state')
            try:
                trial = random.Random()
                trial.setstate((state[0], tuple(state[1]), state[2]))
            except (ValueError, TypeError, IndexError) as exc:
                raise fail('Invalid legacy Python RNG state') from exc
            self.impl = trial
            self.algorithm = 'python-mt19937'

    def set_native(self, values):
        trial = SFMT19937(0)
        trial.set_words(values)
        self.impl = trial
        self.algorithm = ALGORITHM

    def get_native(self, *, allow_reseed=False):
        if self.algorithm == ALGORITHM:
            return self.impl.get_words()
        if not allow_reseed:
            raise fail(
                'Legacy Python RNG cannot be converted to an identical SFMT stream. Use RANDOMIZE, or explicitly --allow-rng-reseed for native export.'
            )
        seed = int.from_bytes(
            hashlib.sha256(
                json.dumps(self.impl.getstate(), separators=(',', ':')).encode('ascii')
            ).digest()[:4],
            'little',
        )
        return SFMT19937(seed).get_words()


def execute(vm, spec, arg):
    from .expr import integer

    name = spec['name']
    if name == 'RANDOMIZE':
        parts = vm.args(arg)
        if len(parts) > 1:
            raise EraError('RANDOMIZE accepts zero or one argument', code='E_ARGUMENT')
        vm.rng.seed(integer(parts[0]) if parts else 0)
    else:
        # INITRAND/DUMPRAND use the source VOID builder: runtime discards
        # surplus text without parsing/evaluating it or flushing warnings.
        variable = vm.data.variables['RANDDATA']
        if variable.dims != (625,):
            raise fail('RANDDATA must be an array of length 625')
        if name == 'INITRAND':
            vm.rng.set_native([variable.get((i,)) for i in range(625)])
        elif name == 'DUMPRAND':
            values = vm.rng.get_native()
            variable.values = {(i,): x for i, x in enumerate(values) if x}
        else:
            return False
    return True
