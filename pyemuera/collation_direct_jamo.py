"""Input-driven direct Jamo comparison for the pinned Windows 10 NLS profile.

Separate from unary sort keys: sampled categories survive mapping and a
one-sided skip can retain the other cursor's synthesized cache. Secondary
weights, kana differences and word punctuation remain deferred until the
primary comparison and original-input termination scan permit them.

This loop consumes only fixed profile weights and the original UTF-16 units.
Unsupported reached categories return None to the established portable path.
No native calls, Unicode normalization, or pair-answer tables are used.
"""
from dataclasses import dataclass
import re

_JAMO = re.compile('[\u1100-\u11ff\ua960-\ua97c\ud7b0-\ud7c6\ud7cb-\ud7fb]')


def sign(a, b):
    return (a > b) - (a < b)


@dataclass
class Side:
    units: tuple
    cursor: int = 0
    cache: int | None = None
    extra: int = 0
    invalid_kana_cache: bool = False

    def advance(self):
        self.cursor += 1
        self.cache = None
        self.invalid_kana_cache = False


class DirectJamoComparison:
    def __init__(self, backend):
        self.b = backend
        self.reason = ''
        self.events = []

    def word(self, cp):
        sm, aw, dw, cw = self.b._weight(cp)
        return aw | sm << 8 | dw << 16 | cw << 24

    def mapper(self, s):
        # MapOldHangulSortKey 5a460..5a743 and UpdateJamoState.
        u, start = s.units, s.cursor
        if u[start] not in self.b._jamo:
            # GetOldHangulWeight 58150..58193 when MapOldHangulSortKey
            # returns zero: rebuild from CURRENT RAW character, not cache.
            w = self.word(u[start])
            s.extra = 0
            s.cache = (w & 0x3f000000) | 0x00020000 | ((w & 255) << 8) | ((w >> 16) & 255)
            return 0
        pos = start
        selected = []
        missing = False
        for cls, default in ((0, 0x115f), (1, 0x1160), (2, None)):
            cp = u[pos] if pos < len(u) else None
            match = cp in self.b._jamo and (
                (cls == 0 and (0x1100 <= cp <= 0x115f or 0xa960 <= cp <= 0xa97c)) or
                (cls == 1 and (0x1160 <= cp <= 0x11a7 or 0xd7b0 <= cp <= 0xd7c6)) or
                (cls == 2 and (0x11a8 <= cp <= 0x11ff or 0xd7cb <= cp <= 0xd7fb)))
            if match:
                pos += 1
            else:
                cp = default
            if cp is not None:
                selected.append((cls, self.b._jamo[cp]))
                missing |= cp in (0x115f, 0x1160)
        if not any(row[0] for _, row in selected):
            # Native resets state and processes current row as slot L, then V filler.
            selected = [(0, self.b._jamo[u[start]]), (1, self.b._jamo[0x1160])]
            pos = start + 1
            missing = True
        nearest = [max(0, *(row[k] if row[k] < 128 else row[k] - 256 for _, row in selected)) for k in (1, 2, 3)]
        extras = [0, 0, 0]
        for cls, row in selected:
            extras[cls] = max(extras[cls], row[4])
        cp = (0xac00 + (nearest[0]*21 + nearest[1])*28 + nearest[2]) & 65535
        if missing:
            cp = (cp-1) & 65535
            if cp < 0xac00:
                cp = 0x3260
            extras[0] = (extras[0]+128) & 255
        extras = [max(2, x) for x in extras]
        s.cache = 0x02020000 | (self.word(cp) & 65535)
        s.extra = extras[0] << 16 | extras[1] << 8 | extras[2]
        s.cursor = pos - 1
        return pos - start

    def kana(self, s):
        w = s.cache
        invalid = False
        s.invalid_kana_cache = False
        aw = w & 255
        cw = (w >> 24) & 63
        marks = [cw & 6, 3, cw & 0x24, cw & 5]
        primary = 0x2200 | aw
        if aw <= 1:
            invalid = True
            marks = [0, 0, 0, 0]
            primary = 0xffff
            for cp in reversed(s.units[:s.cursor]):
                prior = self.word(cp)
                cat = (prior >> 8) & 255
                if cat == 2:
                    break
                if cat < 3 or (cat == 3 and (prior & 255) <= 1):
                    continue
                invalid = False
                if cat == 3:
                    pc = (prior >> 24) & 63
                    primary = 0x2200 | (prior & 255)
                    marks = [pc & 6, 4 + aw, pc & 0x24, (pc if aw == 0 else cw) & 5]
                    if aw == 1:
                        primary &= 0xff87
                else:
                    primary = prior & 65535
                break
        if invalid:
            # 2f0a3..2f0b3 / 2f351: an internally generated sentinel,
            # NOT a raw input category-FF weight and NOT 0x0202ffff.
            s.cache = 0xffff
            s.extra = 0
            s.invalid_kana_cache = True
        else:
            s.cache = (w & 0x00ff0000) | 0x02000000 | primary
        return marks

    def compare(self, left, right, *, trace=False):
        self.events = []
        self.reason = ''
        l, r = Side(left), Side(right)
        if l.units == r.units:
            return 0
        # Explicit-length prefix scan and rewind, 4070/412b..418c.
        # Preserve original buffers: a Jamo immediately before the mismatch
        # resets BOTH cursors to original starts, not the previous cluster.
        common = 0
        while common < min(len(l.units),len(r.units)) and l.units[common] == r.units[common]:
            common += 1
        if common:
            prev = l.units[common-1]
            rewind = ((prev-0x1100)&65535)<=0xff or ((prev+0x56a0)&65535)<=0x1c or ((prev+0x2850)&65535)<=0x16 or ((prev+0x2835)&65535)<=0x30
            cursor = 0 if rewind else common-1 if prev == 0xdb40 else common
            l.cursor = r.cursor = cursor
        special_seen = False
        pending_special = 0
        pending_case = 0
        pending_dia = 0
        pending_kana = [0, 0, 0, 0]
        while True:
            if trace:
                self.events.append(dict(cursor=[l.cursor,r.cursor],cache=[l.cache,r.cache],extra=[l.extra,r.extra],special_seen=special_seen,pending=[pending_dia,pending_case,pending_special]))
            if l.cursor >= len(l.units) or r.cursor >= len(r.units):
                # 47ca/4a03: scan actual remaining raw units, not mapped clusters.
                for s, direction in ((l,1),(r,-1)):
                    while s.cursor < len(s.units):
                        cat = self.b._weight(s.units[s.cursor])[0]
                        if cat not in (0,1,3,4,6) and not (0x07 <= cat < 0xa9 or 0xb0 <= cat < 0xfd):
                            self.reason = 'unsupported_tail_category'
                            return None
                        if cat == 1:
                            # 2f69c / 2f71d: remaining nonspace is significant
                            # only while diacritic comparison remains active.
                            if not pending_dia:
                                return direction
                            s.advance()
                            continue
                        if cat not in (0,6):
                            return direction
                        if cat == 6 and not special_seen:
                            pending_special = direction
                            special_seen = True
                        s.advance()
                return pending_dia or pending_case or next((v for v in pending_kana if v), 0) or pending_special
            for s in (l,r):
                if s.cache is None:
                    s.cache = self.word(s.units[s.cursor])
            samples = [l.cache,r.cache]
            cats = [(w>>8)&255 for w in samples]
            if trace:
                self.events.append(dict(kind='samples',cursor=[l.cursor,r.cursor],samples=samples,categories=cats))
            if samples[0] == samples[1] and (cats[0] not in (2,3,4,5,6,13) and not 0xa9 <= cats[0] <= 0xaf and cats[0] < 0xfd or cats[0] == 3 and (samples[0] & 255) > 1):
                l.advance();r.advance();continue
            if all(s.invalid_kana_cache and s.cache == 0xffff for s in (l,r)):
                l.advance();r.advance();continue
            if any(cat not in (0, 1, 3, 4, 6) and not (0x07 <= cat < 0xa9 or 0xb0 <= cat < 0xfd)
                   and not (cat == 255 and s.invalid_kana_cache and s.cache == 0xffff)
                   for s,cat in zip((l,r),cats)):
                self.reason = 'unsupported_reached_category'
                return None
            # Dispatch uses the sampled category even after the mapper updates cache.
            for s,cat in zip((l,r),cats):
                if cat == 4:
                    start=s.cursor
                    consumed=self.mapper(s)
                    if trace:
                        self.events.append(dict(kind='map',side='left' if s is l else 'right',start=start,end=s.cursor,consumed=consumed,cache=s.cache,extra=s.extra))
                elif cat == 0 or (cat == 6 and special_seen):
                    s.advance()
            if l.cache is None or r.cache is None:
                continue
            # 4ea6 -> 2f0db; 5048 -> 2f45b. A standalone nonspace
            # records presence at the diacritic level and consumes one side.
            # Equal-primary nonspace pairs bypass this dispatch (4925/5277).
            if 1 in cats and (l.cache & 65535) != (r.cache & 65535):
                for s, cat, direction in ((l,cats[0],1),(r,cats[1],-1)):
                    if cat == 1:
                        if not pending_dia:
                            pending_dia = direction
                        s.advance()
                    elif cat == 3:
                        marks = self.kana(s)
                        for i in range(4):
                            if not pending_kana[i]:
                                pending_kana[i] = direction * sign(marks[i],0)
                    elif cat == 6:
                        if not special_seen:
                            pending_special = direction
                            special_seen = True
                        s.advance()
                continue
            if cats[0] == 6 or cats[1] == 6:
                if cats == [6,6]:
                    key = lambda w: (w&255, ((((w>>16)&255)<<3)+((w>>24)&63))&255)
                    difference = sign(key(l.cache),key(r.cache))
                    if difference:
                        pending_special = difference
                        special_seen = True
                    l.advance();r.advance()
                elif cats[0] == 6:
                    pending_special = 1;special_seen = True;l.advance()
                else:
                    pending_special = -1;special_seen = True;r.advance()
                continue
            kana_marks = [self.kana(s) if cat == 3 else [0,0,0,0] for s,cat in zip((l,r),cats)]
            if 3 in cats:
                for i in range(4):
                    if not pending_kana[i]:
                        pending_kana[i] = sign(kana_marks[0][i], kana_marks[1][i])
            diff = sign(l.cache&65535,r.cache&65535)
            if trace:
                self.events.append(dict(kind='compare',left16=l.cache&65535,right16=r.cache&65535,categories=cats,extras=[l.extra,r.extra]))
            if diff:
                return diff
            if cats == [4,4]:
                diff = sign(l.extra,r.extra)
                if diff:
                    return diff
            if not pending_dia:
                dw = [(l.cache>>16)&255,(r.cache>>16)&255]
                if dw[0] != dw[1]:
                    # 5614/5691; 2f577/2f631: only a current DW mismatch
                    # triggers consumption of immediately adjacent cat1 units.
                    for i,s in enumerate((l,r)):
                        start = s.cursor
                        while s.cursor + 1 < len(s.units):
                            next_word = self.word(s.units[s.cursor+1])
                            if (next_word >> 8) & 255 != 1:
                                break
                            s.cursor += 1
                            dw[i] = (dw[i] + ((next_word >> 16) & 255)) & 255
                        if trace and start != s.cursor:
                            self.events.append(dict(kind='nonspace_lookahead',side=i,start=start,end=s.cursor,dw=dw[i]))
                    pending_dia = sign(dw[0],dw[1])
            if not pending_case:
                pending_case = sign((l.cache>>24)&63,(r.cache>>24)&63)
            l.advance();r.advance()


def direct_jamo_sign(backend, left, right, utf16_units):
    # Preserve str-subclass hooks and avoid allocating state on ordinary input.
    if type(left) is not str or type(right) is not str:
        return None
    if _JAMO.search(left) is None and _JAMO.search(right) is None:
        return None
    return DirectJamoComparison(backend).compare(utf16_units(left), utf16_units(right))
