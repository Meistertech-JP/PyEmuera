"""Portable Japanese linguistic comparison from published Microsoft NLS data.

The runtime uses only the standard library and pinned generated weights. It
does not query host locale, Unicode normalization, casefolding or an oracle
result dictionary. String input is processed as UTF-16 code units, including
lone surrogates. General level assembly follows MS-UCODEREF section 3.1.5.2;
Windows 10 Jamo context and late punctuation direction also use the bounded
Framework/NLS evidence recorded in the r43 compatibility reports.

This is a declared Windows 10 data profile, not a claim that every version of
Windows/.NET NLS has identical behavior. See profile metadata and the notice.
"""

from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import struct
import zlib

from .errors import EraError, Unsupported
from .collation_jamo import (
    JamoClass,
    consume_jamo_cluster,
    interpret_jamo,
    jamo_class,
)


@lru_cache(maxsize=1)
def _load_profile():
    directory = files('pyemuera').joinpath('resources')
    metadata = json.loads(
        directory.joinpath('nls_ja_windows10.json').read_text(encoding='utf-8')
    )
    compressed = directory.joinpath('nls_ja_windows10.bin.zlib').read_bytes()
    if hashlib.sha256(compressed).hexdigest() != metadata['compiled_sha256']:
        raise EraError('Portable NLS resource checksum mismatch', code='E_SPEC')
    raw = zlib.decompress(compressed)
    if (
        raw[:8] != b'PyNLSJA1'
        or hashlib.sha256(raw).hexdigest() != metadata['payload_sha256']
    ):
        raise EraError('Portable NLS resource payload mismatch', code='E_SPEC')
    size = struct.unpack_from('<I', raw, 8)[0]
    if size != 65536 * 4:
        raise EraError('Portable NLS BMP table length mismatch', code='E_SPEC')
    extra = json.loads(raw[12 + size :])
    return metadata, raw[12 : 12 + size], extra


def _utf16_units(text):
    raw = text.encode('utf-16-le', errors='surrogatepass')
    return struct.unpack('<' + 'H' * (len(raw) // 2), raw)


def _trim(values, baseline, *, minimum=False):
    end = len(values)
    while end and (
        values[end - 1] <= baseline if minimum else values[end - 1] == baseline
    ):
        end -= 1
    return bytes(values[:end])


class _Streams:
    """Primary, diacritic, case, Japanese contextual and word-punctuation."""

    def __init__(self, *, defer_cluster_weights=False, punctuation_case=False):
        self.defer_cluster_weights = defer_cluster_weights
        self.punctuation_case = punctuation_case
        self.primary = bytearray()
        self.primary_elements = 0
        self.jamo_leading = []
        self.diacritic = []
        self.case = []
        self.kana = [[], [], [], []]  # W4 small, W5 repeat, W6 type, W7 width
        self.special = bytearray()

    def normal(self, weight):
        script, primary, diacritic, casing = weight
        # Compare primary *elements*, including a neutral third component.
        # Omitting it from ordinary elements lets an old-Jamo third byte be
        # compared against the following element's script member instead.
        third = diacritic if 0xA9 <= script <= 0xAF else 2
        self.primary.extend((script, primary, third))
        self.primary_elements += 1
        # Japanese's legacy sort has two-byte CJK weights. Private-use
        # characters always promote the third weight into the primary level.
        if not 0xA9 <= script <= 0xAF:
            self.diacritic.append(diacritic)
        self.case.append(casing & 0x3F)

    def mark(self, weight):
        # BYTE arithmetic; no normalization/reordering is performed.
        if self.diacritic:
            self.diacritic[-1] = (self.diacritic[-1] + weight[2]) & 255
        else:
            self.diacritic.append(weight[2])

    def kana_character(self, primary, diacritic, casing, repeat=3):
        self.normal((34, primary, diacritic, 2))
        values = (
            0xC4 | (casing & 2),
            repeat,
            0xC4 | (casing & 0x20),
            0xC4 | (casing & 1),
        )
        for stream, value in zip(self.kana, values):
            stream.append(value)

    def punctuation(self, weight):
        # Word punctuation is a late tie-break, not an ignored character.
        # The received Windows 10 CompareTo/CompareInfo/NLS oracle orders
        # later word positions first (ab- < a-b < -ab). This complements the
        # published positional encoding; the older pseudocode alone does not
        # establish that modern comparison direction. Count weight elements,
        # not serialized bytes: PUA and contextual Jamo have a third byte.
        # The published older 16-bit encoding wraps every 8192 elements.
        # Captured Windows 10 comparisons retain the position across that
        # boundary. Use a prefix-free, descending encoding without truncation;
        # its bytes are our comparison representation, not a native sort key.
        width = max(1, (self.primary_elements.bit_length() + 7) // 8)
        self.special.extend(b'\x00' * width + b'\x01')
        self.special.extend(
            value ^ 0xFF for value in self.primary_elements.to_bytes(width, 'big')
        )
        self.special.extend(weight[:2])
        if self.punctuation_case:
            # Fullwidth, small, and vertical forms share a primary weight with
            # the ASCII punctuation and differ in the published case byte.
            # Direct comparison keeps that byte; it is not part of the unary
            # sort-key representation above.
            self.special.append(weight[3] & 0x3F)

    def jamo_character(self, emission):
        if self.defer_cluster_weights and emission.deferred_leading is not None:
            # No shared Jamo prefix: keep the cluster boundary, but move the
            # class weights out of the primary stream. Captured Framework
            # direct comparisons use this when the strings diverge before any
            # Jamo, and the ordinary inline weights when a shared Jamo prefix
            # is present. The choice is pairwise, so the result need not be
            # transitive. It is not selected by a literal string or row number.
            self.normal(emission.base)
            for index in range(1, len(emission.context), 2):
                self.primary.extend((emission.context[index], 2, 2))
            self.primary_elements += emission.extra_elements
            self.jamo_leading.extend(
                (emission.deferred_leading, emission.context[4], emission.context[6])
            )
            return
        self.normal(emission.base)
        for index in range(1, len(emission.context), 2):
            self.primary.extend(
                (emission.context[index], emission.context[index + 1], 2)
            )
        self.primary_elements += emission.extra_elements
        if emission.deferred_leading is not None:
            self.jamo_leading.append(emission.deferred_leading)

    def jamo_unicode(self, elements, *, park_tail=False):
        """Append measured Windows 10 Unicode weights for one Jamo run.

        Each element is one primary weight, including its extra bytes. The
        neutral diacritic and case bytes trim away, so a pure Jamo key ends
        with the same 01 01 01 01 00 tail as a Framework sort key. A following
        combining mark still adds to the diacritic 2 left here.

        Direct comparison of strings that diverge before any shared Jamo and
        contain a non-Jamo unit parks those extra bytes on a later level.
        Sort keys, shared Jamo prefixes and pure Jamo strings keep the bytes
        inline. The parked level is what makes Framework's non-transitive
        direct order differ from its unary sort key.
        """
        for element in elements:
            if park_tail:
                self.primary.extend(element[:2])
                self.primary.append(2)
                self.jamo_leading.extend(element[2:])
            else:
                self.primary.extend(element)
            self.primary_elements += 1
            self.diacritic.append(2)
            self.case.append(2)

    def finish(self):
        key = bytes(self.primary) + b'\x01' + bytes(self.jamo_leading)
        key += b'\x01' + _trim(self.diacritic, 2, minimum=True)
        key += b'\x01' + _trim(self.case, 2, minimum=True) + b'\x01'
        if self.kana[2]:
            # The stage definitions name W4/W5 as well as W6/W7. Their high
            # separators make trailing baseline small/type/width weights sort
            # after a lower explicit weight, unlike a tuple-of-tuples key.
            key += _trim(self.kana[0], 0xC6) + b'\xff'
            key += _trim(self.kana[1], 3) + b'\x02'
            key += _trim(self.kana[2], 0xE4) + b'\xff'
            key += _trim(self.kana[3], 0xC5) + b'\xff'
        return key + b'\x01' + bytes(self.special) + b'\x00'


class PortableNLSBackend:
    """Pinned ja-JP/CompareOptions.None backend with bounded per-instance cache."""

    def __init__(self, cache_size=4096):
        metadata, self._weights, extra = _load_profile()
        self._metadata = metadata
        self._expansions = tuple(tuple(row) for row in extra['expansions'])
        self._contractions = {
            tuple(seq): tuple(weight) for seq, weight in extra['contractions']
        }
        self._contraction_lengths = tuple(
            sorted({len(seq) for seq in self._contractions}, reverse=True)
        )
        self._jamo = {cp: tuple(data) for cp, data in extra['jamo']}
        self._cached_key = lru_cache(maxsize=max(0, int(cache_size)))(self._make_key)

    def identity(self, culture='ja-JP'):
        self._validate_profile(culture, 0)
        return {
            'backend': 'portable-ms-nls',
            'profile': 'windows10-ja-JP-0x60305',
            'culture': 'ja-JP',
            'compare_options': 'None',
            'sort_version': self._metadata['nls_version'],
            'sort_version_hex': self._metadata['nls_version_hex'],
            'sort_guid': self._metadata['sort_guid'],
            'data_sha256': self._metadata['compiled_sha256'],
            'source_sha256': self._metadata['source_sha256'],
            'uses_host_locale': False,
            'requires_dotnet': False,
            'scope': 'published Microsoft Windows 10 ja-JP data/algorithm profile',
            'unsupported': ['other cultures/options'],
            'jamo_model': 'Windows 10 flat JAMOSORT contextual reconstruction',
            'jamo_native_scope': (
                'received Framework ja-JP matrices and r49 alignment development probes; '
                'coverage is bounded to the recorded input populations'
            ),
            'additional_native_coverage_required': [
                'Jamo classes, repetitions, fillers and old combinations beyond the received matrices',
                'partial old-Jamo cluster followed by word punctuation',
                'small kana and repeat/prolonged sound contextual weights',
                'word-sort punctuation positions',
                'CJK Extension A and private-use boundary weights',
                'long combining-mark chains and lone surrogate positions',
                'installed Windows NLS version versus published 0x60305 profile',
            ],
        }

    @property
    def profile(self):
        return {**self._metadata, **self.identity('ja-JP')}

    def cache_info(self):
        return self._cached_key.cache_info()

    def _weight(self, cp):
        start = cp * 4
        return tuple(self._weights[start : start + 4])

    def _append_expansion(self, streams, weight, depth=0):
        if depth > 8:
            raise EraError('Portable NLS expansion cycle', code='E_SPEC')
        index = weight[2] + (weight[3] << 8)
        if index >= len(self._expansions):
            raise EraError('Portable NLS expansion index outside table', code='E_SPEC')
        for cp in self._expansions[index]:
            item = self._weight(cp)
            if item[0] == 2:
                self._append_expansion(streams, item, depth + 1)
            elif item[0] == 0:
                continue
            elif item[0] == 1:
                streams.mark(item)
            else:
                streams.normal(item)

    def _append_kana(self, streams, units, index, weight):
        _, primary, diacritic, casing = weight
        if primary > 1:
            streams.kana_character(primary, diacritic, casing)
            return
        previous = index - 1
        while previous >= 0:
            prior = self._weight(units[previous])
            previous -= 1
            if prior[0] in (0, 1) or prior[0] == 3 and prior[1] <= 1:
                continue
            if prior[0] == 2:
                break
            if prior[0] != 3:
                # SpecialCaseHandler carries only CorrectUnicodeWeight from
                # a non-kana predecessor. The mark keeps its own DW and the
                # neutral case weight; it does not repeat the predecessor's
                # accent/case or its ordinary special-script processing.
                streams.primary.extend((*prior[:2], 2))
                streams.primary_elements += 1
                streams.diacritic.append(diacritic)
                streams.case.append(2)
                return
            repeated_primary = prior[1]
            repeated_case = prior[3]
            if primary == 1:
                repeated_primary &= 0x87
                repeated_case = (repeated_case & ~1) | (casing & 1)
            streams.kana_character(
                repeated_primary, diacritic, repeated_case, 4 + primary
            )
            return
        streams.primary.extend((255, 255, 2))
        streams.primary_elements += 1

    def _make_key(
        self,
        text,
        *,
        defer_cluster_weights=False,
        punctuation_case=False,
        park_jamo_tails=False,
        legacy_jamo=False,
        omit_opening_jamo_tail=False,
        punctuation_only=False,
        punctuation_from=None,
    ):
        units = _utf16_units(text)
        streams = _Streams(
            defer_cluster_weights=defer_cluster_weights,
            punctuation_case=punctuation_case,
        )
        index = 0
        while index < len(units):
            weight = self._weight(units[index])
            consumed = 1
            for length in self._contraction_lengths:
                if index + length <= len(units):
                    contracted = self._contractions.get(units[index : index + length])
                    if contracted is not None:
                        weight, consumed = contracted, length
                        break
            script, primary, diacritic, casing = weight
            if script == 0:
                pass
            elif script == 1:
                streams.mark(weight)
            elif script == 2:
                self._append_expansion(streams, weight)
            elif script == 3:
                self._append_kana(streams, units, index, weight)
            elif script == 4:
                if legacy_jamo:
                    # Compatibility Hangul and a one-sided non-Jamo prefix make
                    # CompareTo follow the short boundary emission. Sort keys
                    # keep the measured Unicode weights above.
                    emission = interpret_jamo(units, index, self._jamo, self._weight)
                    streams.jamo_character(emission)
                    consumed = emission.consumed
                else:
                    elements, consumed = consume_jamo_cluster(
                        units, index, self._jamo, self._weight
                    )
                    if omit_opening_jamo_tail:
                        elements = [elements[0][:2], *elements[1:]]
                        omit_opening_jamo_tail = False
                    streams.jamo_unicode(elements, park_tail=park_jamo_tails)
            elif script == 5:
                streams.primary.extend((254, 255, 2, primary, diacritic, 2))
                streams.primary_elements += 2
                streams.diacritic.append(2)
                streams.case.append(2)
            elif script == 6:
                streams.punctuation(weight)
            else:
                streams.normal(weight)
            index += consumed
        if punctuation_only:
            return bytes(streams.special)
        if punctuation_from is not None:
            # Aligned Jamo primaries can start at a suffix. Word punctuation
            # still uses its original position in the complete input.
            streams.special = bytearray(self._make_key(
                punctuation_from, punctuation_case=True, punctuation_only=True
            ))
        return streams.finish()

    @staticmethod
    def _validate_profile(culture, options):
        if culture != 'ja-JP':
            raise Unsupported(
                'Portable NLS culture ' + str(culture) + '; supported profile is ja-JP'
            )
        if options not in (0, 'None', None):
            raise Unsupported(
                'Portable NLS CompareOptions '
                + str(options)
                + '; supported option is None'
            )

    @staticmethod
    def _validate_text(text):
        if not isinstance(text, str):
            raise EraError('Portable NLS comparison requires a string', code='E_TYPE')

    def sort_key(self, text, culture='ja-JP', *, options=0):
        self._validate_profile(culture, options)
        self._validate_text(text)
        return self._cached_key(text)

    def compare(self, left, right, culture='ja-JP', *, options=0):
        self._validate_profile(culture, options)
        self._validate_text(left)
        self._validate_text(right)
        # String.CompareTo's reference-equal/identical-string contract is
        # independent of collation data. Profile/type validation still precedes
        # this fast path, including contextual Jamo strings.
        if left == right:
            return 0
        contextual = self._separator_jamo_sign(left, right)
        if contextual is not None:
            return contextual
        if self._leading_run_ignorable_cluster_equal(left, right):
            return 0
        adjusted = self._leading_ignorable_jamo_sign(left, right)
        if adjusted is not None:
            return adjusted
        # Sort-key order is unary and transitive. Framework direct comparison
        # is not: a shared Jamo prefix keeps inline class weights, and any
        # other pair defers them. Punctuation width is part of that direct
        # comparison and is intentionally absent from sort_key().
        left_units = _utf16_units(left)
        right_units = _utf16_units(right)
        common = 0
        limit = min(len(left_units), len(right_units))
        while common < limit and left_units[common] == right_units[common]:
            common += 1
        shared_jamo = any(unit in self._jamo for unit in left_units[:common])

        def leading_break(units):
            for unit in units:
                if unit in self._jamo:
                    return False
                if self._weight(unit)[0] != 0:
                    return True
            return False

        compatibility = any(
            0x3131 <= unit <= 0x318E for unit in left_units + right_units
        )

        def opens_on_leading(units):
            for unit in units:
                if self._weight(unit)[0] in (0, 6):
                    continue
                return (
                    unit in self._jamo
                    and jamo_class(unit) == JamoClass.LEADING
                    and unit != 0x115F
                )
            return False

        # Compatibility forms select the short leading-boundary comparison
        # only when one operand actually opens on a non-filler leading Jamo.
        # V/T openings keep their measured Unicode weights (r49 Framework).
        legacy = (
            compatibility
            and (opens_on_leading(left_units) or opens_on_leading(right_units))
        ) or (
            leading_break(left_units) != leading_break(right_units)
            and not self._same_opening_jamo(left_units, right_units)
        )
        # Parking every unshared mixed pair reverses unrelated Jamo text whose
        # inline weights already match Framework. The non-transitive level is
        # the same Jamo sequence with a non-Jamo unit moved into or out of it.
        def jamo_sequence(units):
            return tuple(unit for unit in units if unit in self._jamo)

        left_jamo = jamo_sequence(left_units)
        right_jamo = jamo_sequence(right_units)
        mixed = len(left_jamo) != len(left_units) or len(right_jamo) != len(right_units)
        park = (
            (not legacy)
            and (not shared_jamo)
            and mixed
            and left_jamo == right_jamo
            and len(left_jamo) > 0
        )
        a = self._make_key(
            left,
            defer_cluster_weights=not shared_jamo,
            punctuation_case=True,
            park_jamo_tails=park,
            legacy_jamo=legacy,
        )
        b = self._make_key(
            right,
            defer_cluster_weights=not shared_jamo,
            punctuation_case=True,
            park_jamo_tails=park,
            legacy_jamo=legacy,
        )
        if a != b:
            return (a > b) - (a < b)
        # Equal Unicode weights stay equal. A weightless separator can sit
        # between L and V without changing a modern LV/LVT key; treating that
        # separator as a boundary distinguishes strings Framework compares
        # as equal. Different cluster shapes are already different keys.
        return 0

    def _separator_jamo_sign(self, left, right):
        """Compare aligned Jamo after unequal ignorable/punctuation prefixes.

        Framework consumes matched raw units and matched separator classes
        before comparing the next Jamo element. A one-sided separator before
        unequal Jamo elements with the same base primary weight suppresses
        that first element's class tail; subsequent elements retain theirs.
        This is pairwise alignment, not a unary sort-key transformation.

        A filler remains part of the cluster. Matched separators preserve an
        existing Jamo alignment; an ordinary character ends it. Unequal
        separator classes are consumed before the next Jamo comparison.
        Equal remaining Jamo sequences retain the established boundary rules.
        Raw equality of a leading unit is insufficient to align its attached
        cluster: the complete opening element must also match. After alignment
        a one-sided separator starts the comparison; it must not be skipped a
        second time. See the r49 Framework development probes for measured scope.
        """
        first = _utf16_units(left)
        second = _utf16_units(right)
        i = j = 0
        aligned_jamo = False
        aligned_through_prefix = False
        separator_pair_seen = False

        def separator(unit):
            return self._weight(unit)[0] in (0, 6)

        def separator_length(units, position):
            end = position
            while end < len(units) and separator(units[end]):
                end += 1
            return end - position

        def first_element(units, position):
            return consume_jamo_cluster(
                units, position, self._jamo, self._weight
            )[0][0]

        while i < len(first) and j < len(second):
            if first[i] == second[j]:
                if not separator(first[i]):
                    separator_pair_seen = False
                    aligned_jamo = first[i] in self._jamo
                    if not aligned_jamo:
                        aligned_through_prefix = False
                i += 1
                j += 1
                continue
            a, b = self._weight(first[i])[0], self._weight(second[j])[0]
            if not aligned_jamo and (a == 6 or b == 6):
                aligned_through_prefix = True
            if (
                not separator_pair_seen
                and aligned_jamo
                and aligned_through_prefix
                and a in (0, 6) and b in (0, 6)
                and separator_length(first, i) == separator_length(second, j)
            ):
                # A prefix-skipping alignment is not a common raw prefix.
                # If both sides split the next cluster, keep the ordinary
                # boundary comparison instead of suppressing its tail again.
                return None
            if aligned_jamo and a in (0, 6) and b in (0, 6):
                separator_pair_seen = True
            if a == b and a in (0, 6):
                i += 1
                j += 1
                continue
            if a == 0 and b in (0, 6):
                i += 1
                continue
            if b == 0 and a in (0, 6):
                j += 1
                continue
            ii, jj = i, j
            while ii < len(first) and separator(first[ii]):
                ii += 1
            while jj < len(second) and separator(second[jj]):
                jj += 1
            if (
                (ii != i or jj != j)
                and not aligned_jamo
                and ii < len(first)
                and jj < len(second)
                and first[ii] == second[jj]
                and first[ii] in self._jamo
                and first[ii] != 0x115F
                and first_element(first, ii) == first_element(second, jj)
            ):
                aligned_through_prefix = aligned_through_prefix or any(
                    self._weight(unit)[0] == 6
                    for unit in first[i:ii] + second[j:jj]
                )
                i, j = ii + 1, jj + 1
                aligned_jamo = True
                continue
            break

        ii, jj = i, j
        while ii < len(first) and separator(first[ii]):
            ii += 1
        while jj < len(second) and separator(second[jj]):
            jj += 1
        if (ii > i) == (jj > j) or ii == len(first) or jj == len(second):
            return None
        if first[ii] not in self._jamo or second[jj] not in self._jamo:
            return None
        first_jamo = tuple(unit for unit in first[i:] if unit in self._jamo)
        second_jamo = tuple(unit for unit in second[j:] if unit in self._jamo)
        if first_jamo == second_jamo:
            return None
        a, _ = consume_jamo_cluster(first, ii, self._jamo, self._weight)
        b, _ = consume_jamo_cluster(second, jj, self._jamo, self._weight)
        if a[0][:2] != b[0][:2]:
            return None
        if aligned_jamo:
            # Matching a raw leading unit is not enough when its attached
            # cluster changes the base primary boundary. Compare that boundary
            # before entering the aligned remainder.
            def opening_base(units):
                position = 0
                while position < len(units) and separator(units[position]):
                    position += 1
                if position < len(units) and units[position] in self._jamo:
                    elements, _ = consume_jamo_cluster(
                        units, position, self._jamo, self._weight
                    )
                    return elements[0]
                return None
            if opening_base(first) != opening_base(second):
                return None

        def remaining(units):
            raw = struct.pack('<' + 'H' * len(units), *units)
            return raw.decode('utf-16-le', 'surrogatepass')

        a = self._make_key(
            remaining(first[i:]) if aligned_jamo else left,
            punctuation_case=True, omit_opening_jamo_tail=True,
            punctuation_from=left if aligned_jamo else None,
        )
        b = self._make_key(
            remaining(second[j:]) if aligned_jamo else right,
            punctuation_case=True, omit_opening_jamo_tail=True,
            punctuation_from=right if aligned_jamo else None,
        )
        if a == b:
            # Once aligned, an exhausted remainder is an equal direct
            # comparison. Falling back would restore the class tail that
            # this pairwise boundary comparison has already suppressed.
            return 0
        return (a > b) - (a < b)

    def _same_opening_jamo(self, left, right):
        """Preserve Unicode cluster weights after matching opening Jamo.

        Prefix separators may align the same raw leading Jamo while its L+T
        and L+V lookahead can emit different base primaries. The short legacy
        boundary would discard those cluster weights. The pairwise alignment
        above handles its supported boundary cases before this fallback.
        """
        def opening(units):
            position = 0
            while position < len(units) and self._weight(units[position])[0] in (0, 6):
                position += 1
            if position < len(units) and units[position] in self._jamo:
                return units[position]
            return None

        a, b = opening(left), opening(right)
        return a is not None and a == b

    def _leading_run_ignorable_cluster_equal(self, left, right):
        """A NUL or soft hyphen directly after a shared leading run compares equal.

        Framework CompareTo ignores the vowel and trailing weights of a single
        modern cluster when exactly one side places one weightless separator
        between that shared leading run and its vowel. A second cluster, a
        repeated vowel or trailing, or a non-Jamo tail keeps the normal order.
        """
        left_cluster = self._single_cluster_after_leads(left)
        right_cluster = self._single_cluster_after_leads(right)
        if left_cluster is None or right_cluster is None:
            return False
        left_leads, left_ignored = left_cluster
        right_leads, right_ignored = right_cluster
        return left_leads == right_leads and left_ignored != right_ignored

    def _single_cluster_after_leads(self, text):
        index = 0
        leads = []
        while index < len(text):
            code = ord(text[index])
            if not 0x1100 <= code <= 0x1112:
                break
            leads.append(text[index])
            index += 1
        if not leads or index >= len(text):
            return None
        ignored = False
        if text[index] in ('\x00', '\u00ad'):
            ignored = True
            index += 1
            if index < len(text) and text[index] in ('\x00', '\u00ad'):
                return None
        vowel = ord(text[index]) if index < len(text) else 0
        if not 0x1161 <= vowel <= 0x1175:
            return None
        index += 1
        if (
            index < len(text)
            and ord(text[index]) in self._jamo
            and jamo_class(ord(text[index])) == JamoClass.TRAILING
        ):
            if not 0x11A8 <= ord(text[index]) <= 0x11C2:
                return None
            index += 1
        if index != len(text):
            return None
        return tuple(leads), ignored

    def _leading_ignorable_jamo_sign(self, left, right):
        """Framework CompareTo sees a leading NUL or soft hyphen that GetSortKey drops.

        The ignorable does not change a string's sort key, but a one-sided
        prefix changes direct order when both strings open on a vowel or
        trailing Jamo. A single measured weight on each side compares equal.
        One side's extra weights outrank a single weight. Two multi-weight
        openings flip when either opening contains a trailing Jamo. Strings
        that open on a leading Jamo, or on a non-Jamo, keep the normal path.
        """
        def prefix(text):
            index = 0
            while index < len(text) and text[index] in ('\x00', '\u00ad'):
                index += 1
            return index

        left_prefix = prefix(left)
        right_prefix = prefix(right)
        if (left_prefix > 0) == (right_prefix > 0):
            return None
        left_body = left[left_prefix:]
        right_body = right[right_prefix:]
        if not left_body or not right_body:
            return None
        if not self._opens_on_vowel_or_trailing(left_body):
            return None
        if not self._opens_on_vowel_or_trailing(right_body):
            return None
        left_count, left_trailing = self._opening_jamo_weights(left_body)
        right_count, right_trailing = self._opening_jamo_weights(right_body)
        if left_count == 0 or right_count == 0:
            return None
        sort_sign = (self.sort_key(left_body) > self.sort_key(right_body)) - (
            self.sort_key(left_body) < self.sort_key(right_body)
        )
        if sort_sign == 0:
            return None
        if left_count == 1 and right_count == 1:
            return 0
        if min(left_count, right_count) == 1 and left_count != right_count:
            return 1 if left_count > right_count else -1
        if left_trailing or right_trailing:
            return -sort_sign
        return sort_sign

    def _opens_on_vowel_or_trailing(self, text):
        code = ord(text[0])
        return code in self._jamo and jamo_class(code) != JamoClass.LEADING

    def _opening_jamo_weights(self, text):
        units = _utf16_units(text)
        index = 0
        count = 0
        trailing = False
        while index < len(units):
            code = units[index]
            if code not in self._jamo or jamo_class(code) == JamoClass.LEADING:
                break
            if jamo_class(code) == JamoClass.TRAILING:
                trailing = True
            elements, consumed = consume_jamo_cluster(
                units, index, self._jamo, self._weight
            )
            count += len(elements)
            index += consumed
        return count, trailing
