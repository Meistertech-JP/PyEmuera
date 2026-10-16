"""Interpret contextual Jamo records without normalizing the input string.

This module owns the L/V/T lookahead and weight emission for the pinned
Microsoft Windows 10 JAMOSORT data. The portable backend owns level assembly,
byte arithmetic, caching and the other scripts. Neither module sorts rows.

MS-UCODEREF describes the older transition-table algorithm, but explicitly
limits it to Windows 7/Server 2008 R2 and earlier. Windows 10 publishes 357
flat records without those transitions. The modern-profile boundary and old
cluster rules below are a reconstruction constrained by that public data and
the received Framework/NLS comparisons, not a verbatim implementation of the
older pseudocode. COMPATIBILITY_ja.md describes the measured scope and the
remaining known disagreements.
"""

from dataclasses import dataclass
from enum import IntEnum


class JamoClass(IntEnum):
    LEADING = 0
    VOWEL = 1
    TRAILING = 2


LEADING_FILLER = 0x115F
VOWEL_FILLER = 0x1160
COMPATIBILITY_FILLER = 0x3164
FIRST_SYLLABLE = 0xAC00
SYLLABLES_PER_LEADING = 21 * 28

# The published JAMOSORT row has a code-unit key followed by these five
# fields. Resource loading stores only the five fields as an ordinary tuple;
# the code unit remains the dictionary key. Keep the fields opaque and read
# them individually: unpacking or validating the whole row would change read
# order and the exception raised by a short or lazy record.
OLD_FLAG_INDEX = 0
NEAREST_LEADING_INDEX = 1
NEAREST_VOWEL_INDEX = 2
NEAREST_TRAILING_INDEX = 3
EXTRA_WEIGHT_INDEX = 4


@dataclass(frozen=True)
class JamoEmission:
    """One base element and optional primary contextual elements.

    ``context`` begins with the base element's third byte, followed by pairs
    of (extra-script-member, class weight). ``consumed`` counts original
    UTF-16 code units; it never counts a normalized or composed string.
    """

    base: tuple
    context: bytes = b""
    consumed: int = 1
    deferred_leading: int | None = None

    @property
    def extra_elements(self):
        return (len(self.context) - 1) // 2 if self.context else 0


def jamo_class(code_unit):
    """Classify the published combining-Jamo ranges, including extensions."""
    if 0x1100 <= code_unit <= 0x115F or 0xA960 <= code_unit <= 0xA97C:
        return JamoClass.LEADING
    if 0x1160 <= code_unit <= 0x11A7 or 0xD7B0 <= code_unit <= 0xD7C6:
        return JamoClass.VOWEL
    return JamoClass.TRAILING


def _ordered_cluster(units, start, records):
    """Read at most one L, V and T, stopping at a class reversal/repetition.

    The Windows 10 data has no historical same-class transition records.
    Repeated leading/vowel/trailing characters therefore retain their own
    elements, rather than being silently folded into a made-up contraction.
    Non-Jamo characters, NUL and combining marks also end this lookahead.
    """
    cluster = [(units[start], jamo_class(units[start]), records[units[start]])]
    index = start + 1
    while index < len(units) and units[index] in records:
        character = units[index]
        category = jamo_class(character)
        if category <= cluster[-1][1]:
            break
        cluster.append((character, category, records[character]))
        index += 1
    return cluster


def _class_weights(cluster):
    # The first vowel has published XW=3. Missing leading/trailing components
    # use the minimum legal weight, 2; no key byte is introduced as 0 or 1.
    weights = [2, 3, 2]
    for character, category, record in cluster:
        if character != LEADING_FILLER:
            weights[category] = record[EXTRA_WEIGHT_INDEX]
    return weights


def _context_bytes(weights):
    # MS-UCODEREF's additional Unicode-weight elements use script 255. The
    # initial 2 is the base element's third primary byte, not a new element.
    result = bytearray((2,))
    for weight in weights:
        result.extend((255, weight))
    return bytes(result)


def _vowel_boundary(character_weight):
    script, primary, _, _ = character_weight(COMPATIBILITY_FILLER)
    return script, primary, 2, 2


def _leading_boundary(record, character_weight):
    # LIndex is the published nearest modern leading index. This is a weight
    # boundary before its first syllable, not Unicode Hangul composition.
    first = FIRST_SYLLABLE + record[NEAREST_LEADING_INDEX] * SYLLABLES_PER_LEADING
    script, primary, _, _ = character_weight(first)
    return script, primary - 1, 2, 2


def _cluster_boundary(cluster, character_weight):
    """Locate an old cluster's boundary using the published nearest indices.

    The flat Windows 10 rows include fallback indices for absent components.
    Taking their maxima retains those fallbacks; selecting only each row's
    own L/V/T index loses the observed old-vowel and final-leading boundary.
    Within a leading group the component offsets remain in ``context``.
    At its final vowel the old cluster precedes the next modern leading
    boundary. That boundary and the old-cluster boundary are distinct.

    These phases are reconstructed from captured Windows 10 comparisons.
    They do not claim that the older MS-UCODEREF implementation applies to
    Windows 10, or that our serialized key equals a Windows sort-key byte.
    """
    indices = [
        max(record[index] for _, _, record in cluster)
        for index in (
            NEAREST_LEADING_INDEX,
            NEAREST_VOWEL_INDEX,
            NEAREST_TRAILING_INDEX,
        )
    ]
    if indices[JamoClass.VOWEL] != 20:
        return _leading_boundary(cluster[0][2], character_weight)

    nearest = FIRST_SYLLABLE + (indices[0] * 21 + indices[1]) * 28 + indices[2]
    if nearest == 0xD7A3:
        return _vowel_boundary(character_weight)
    script, primary, _, _ = character_weight(nearest + 1)
    return script, primary - 2, 2, 2


def interpret_jamo(units, start, records, character_weight):
    """Return a table-driven emission for the Jamo starting at ``start``.

    Modern L/V/T characters remain independent: e.g. L+V is not rewritten to
    a precomposed syllable. Context begins at L and needs V, except that a
    leading filler also admits T. V/T-starting sequences and L+T retain their
    standalone elements. A filler can activate context when another class
    follows; a lone filler still represents an absent component.
    """
    cluster = _ordered_cluster(units, start, records)
    contains_old = any(record[OLD_FLAG_INDEX] for _, _, record in cluster)
    starts_leading = cluster[0][1] == JamoClass.LEADING
    has_vowel = any(category == JamoClass.VOWEL for _, category, _ in cluster)
    allows_missing_vowel = cluster[0][0] == LEADING_FILLER
    if (
        contains_old
        and len(cluster) > 1
        and starts_leading
        and (has_vowel or allows_missing_vowel)
    ):
        base = _cluster_boundary(cluster, character_weight)
        weights = _class_weights(cluster)
        if (
            base[:2] == _vowel_boundary(character_weight)[:2]
            and weights[:2] == [2, 3]
            and cluster[-1][1] == JamoClass.TRAILING
            and weights[JamoClass.TRAILING] == 3
        ):
            # A neutral leading/vowel placeholder followed by the first
            # trailing component has the same emission as that trailing
            # component alone. Its distinction is case weight 4, not three
            # extra primary elements. Measured with repeated fillers and
            # trailing components on Framework/NLS (r47).
            return JamoEmission((*base[:3], 4), consumed=len(cluster))
        deferred_leading = None
        if base[:2] != _vowel_boundary(character_weight)[:2]:
            # In a leading-group cluster this offset follows the remaining
            # primary text. Keeping it inline reverses captured old-L+V+T
            # comparisons when the other string continues with ordinary text.
            deferred_leading = weights[JamoClass.LEADING]
            weights[JamoClass.LEADING] = 2
        # A vowel-boundary cluster whose L/V/T weights are all neutral
        # compares as the base element alone. The three neutral primary
        # elements are not a tie-break: on repeated fillers they reverse
        # the Framework order. This is the measured class, not a string.
        context = b''
        if deferred_leading is not None or weights != [2, 3, 2]:
            context = _context_bytes(weights)
        return JamoEmission(
            base,
            context,
            len(cluster),
            deferred_leading,
        )

    character, category, record = cluster[0]
    if category == JamoClass.LEADING and character != LEADING_FILLER:
        base = _leading_boundary(record, character_weight)
        if record[OLD_FLAG_INDEX]:
            return JamoEmission(base, _context_bytes(_class_weights(cluster[:1])))
        return JamoEmission(base)

    base = _vowel_boundary(character_weight)
    if category == JamoClass.TRAILING:
        base = (*base[:3], 4)
    weights = _class_weights(cluster[:1])
    # XW=3 is the first component's neutral position in each Jamo class.
    # A lone first trailing component distinguishes itself by CW=4 only;
    # adding a primary context there would reverse its observed ordering
    # against compatibility filler (CW=7).
    if character != LEADING_FILLER and record[EXTRA_WEIGHT_INDEX] != 3:
        return JamoEmission(base, _context_bytes(weights))
    return JamoEmission(base)


def jamo_boundary_key(units, records, character_weight):
    """Retain weightless separators between increasing Jamo classes.

    A zero-weight character contributes no ordinary collation element, but
    ends raw Jamo lookahead. NUL and soft hyphen are equivalent boundaries.
    This is a supplemental direct-comparison level when existing element
    streams tie; it does not replace their primary/class ordering.
    """
    boundaries = bytearray()
    previous = None
    separated = False
    for unit in units:
        if character_weight(unit)[0] == 0:
            separated = True
            continue
        if unit in records:
            category = jamo_class(unit)
            if previous is not None and previous < category:
                boundaries.append(2 if separated else 3)
            previous = category
        else:
            previous = None
        separated = False
    return bytes(boundaries)


HANGUL_BASE = 0xAC00
VOWEL_ANCHOR = 0xD7A2
SYLLABLES_PER_VOWEL = 28


def _pair(character_weight, code_point):
    script, primary, _, _ = character_weight(code_point)
    return script, primary


def _element(script, primary, tail):
    return bytes((script & 255, primary & 255, *tail))


def _neutral_vowel(records, character_weight):
    return _single_vowel(records[VOWEL_FILLER], character_weight)


def _single_vowel(record, character_weight):
    script, primary = _pair(character_weight, VOWEL_ANCHOR)
    return _element(
        script,
        primary,
        (255, 255, 255, record[EXTRA_WEIGHT_INDEX] & 255, 255, 2),
    )


def _single_trailing(record, character_weight):
    script, primary = _pair(character_weight, VOWEL_ANCHOR)
    return _element(
        script,
        primary,
        (255, 255, 255, 3, 255, record[EXTRA_WEIGHT_INDEX] & 255),
    )


def _vowel_trailing(vowel_record, trailing_record, character_weight):
    script, primary = _pair(character_weight, VOWEL_ANCHOR)
    return _element(
        script,
        primary,
        (
            255,
            255,
            255,
            vowel_record[EXTRA_WEIGHT_INDEX] & 255,
            255,
            trailing_record[EXTRA_WEIGHT_INDEX] & 255,
        ),
    )


def _modern_leading_primary(record, character_weight):
    leading = record[NEAREST_LEADING_INDEX]
    if leading == 0:
        script, primary = _pair(character_weight, HANGUL_BASE)
        if primary == 0:
            return (script - 1) & 255, 255
        return script, primary - 1
    return _pair(character_weight, HANGUL_BASE + leading * SYLLABLES_PER_LEADING - 1)


def _old_leading_primary(record, character_weight):
    return _pair(
        character_weight,
        HANGUL_BASE + (record[NEAREST_LEADING_INDEX] + 1) * SYLLABLES_PER_LEADING - 2,
    )


def _old_leading_vowel_primary(record, character_weight):
    return _pair(
        character_weight,
        HANGUL_BASE + (record[NEAREST_LEADING_INDEX] + 1) * SYLLABLES_PER_LEADING - 1,
    )


def _single_leading(record, character_weight):
    if record[OLD_FLAG_INDEX]:
        script, primary = _old_leading_primary(record, character_weight)
    else:
        script, primary = _modern_leading_primary(record, character_weight)
    return _element(
        script,
        primary,
        (255, (record[EXTRA_WEIGHT_INDEX] + 128) & 255, 255, 3, 255, 2),
    )


def _leading_trailing(leading_record, trailing_record, character_weight):
    if leading_record[OLD_FLAG_INDEX]:
        script, primary = _old_leading_primary(leading_record, character_weight)
    else:
        script, primary = _pair(
            character_weight,
            HANGUL_BASE
            + leading_record[NEAREST_LEADING_INDEX] * SYLLABLES_PER_LEADING
            + trailing_record[NEAREST_TRAILING_INDEX]
            - 1,
        )
    return _element(
        script,
        primary,
        (
            255,
            (leading_record[EXTRA_WEIGHT_INDEX] + 128) & 255,
            255,
            3,
            255,
            trailing_record[EXTRA_WEIGHT_INDEX] & 255,
        ),
    )


def _attached_vowel(leading_record, vowel_record, trailing_record, character_weight):
    last = 2 if trailing_record is None else trailing_record[EXTRA_WEIGHT_INDEX] & 255
    if leading_record[OLD_FLAG_INDEX]:
        script, primary = _old_leading_vowel_primary(leading_record, character_weight)
    elif vowel_record[OLD_FLAG_INDEX]:
        script, primary = _pair(
            character_weight,
            HANGUL_BASE
            + leading_record[NEAREST_LEADING_INDEX] * SYLLABLES_PER_LEADING
            + vowel_record[NEAREST_VOWEL_INDEX] * SYLLABLES_PER_VOWEL
            + vowel_record[NEAREST_TRAILING_INDEX],
        )
    elif trailing_record is not None and trailing_record[OLD_FLAG_INDEX]:
        script, primary = _pair(
            character_weight,
            HANGUL_BASE
            + leading_record[NEAREST_LEADING_INDEX] * SYLLABLES_PER_LEADING
            + vowel_record[NEAREST_VOWEL_INDEX] * SYLLABLES_PER_VOWEL
            + trailing_record[NEAREST_TRAILING_INDEX],
        )
        return [
            _element(
                script,
                primary,
                (
                    255,
                    leading_record[EXTRA_WEIGHT_INDEX] & 255,
                    255,
                    vowel_record[EXTRA_WEIGHT_INDEX] & 255,
                    255,
                    trailing_record[EXTRA_WEIGHT_INDEX] & 255,
                ),
            )
        ]
    else:
        elements = [_single_leading(leading_record, character_weight)]
        if trailing_record is None:
            elements.append(_single_vowel(vowel_record, character_weight))
        else:
            elements.append(_vowel_trailing(vowel_record, trailing_record, character_weight))
        return elements
    return [
        _element(
            script,
            primary,
            (
                255,
                leading_record[EXTRA_WEIGHT_INDEX] & 255,
                255,
                vowel_record[EXTRA_WEIGHT_INDEX] & 255,
                255,
                last,
            ),
        )
    ]


def _emit_cluster(cluster, records, character_weight):
    """Unicode weights for one increasing L/V/T run.

    The bytes are the Windows 10 ja-JP sort-key Unicode weights measured for
    every published Jamo row and for the L/V/T compositions of those rows.
    Filler characters stand for an absent component. A weightless character
    is not consumed here; the caller stops the run before it.
    """
    leading = next((item for item in cluster if item[1] == JamoClass.LEADING), None)
    vowel = next((item for item in cluster if item[1] == JamoClass.VOWEL), None)
    trailing = next((item for item in cluster if item[1] == JamoClass.TRAILING), None)
    if vowel is not None and vowel[0] == VOWEL_FILLER:
        vowel = None
    if leading is None and vowel is None and trailing is None:
        # U+1160 alone is the neutral vowel, the same measured key as U+115F.
        return [_neutral_vowel(records, character_weight)]
    if leading is not None and leading[0] == LEADING_FILLER:
        if vowel is None and trailing is None:
            return [_neutral_vowel(records, character_weight)]
        if vowel is None:
            return [_single_trailing(trailing[2], character_weight)]
        if trailing is None:
            return [_single_vowel(vowel[2], character_weight)]
        return [_vowel_trailing(vowel[2], trailing[2], character_weight)]
    if leading is not None and vowel is not None:
        return _attached_vowel(leading[2], vowel[2], None if trailing is None else trailing[2], character_weight)
    if leading is not None and trailing is not None:
        return [_leading_trailing(leading[2], trailing[2], character_weight)]
    if leading is not None:
        return [_single_leading(leading[2], character_weight)]
    if vowel is not None and trailing is not None:
        return [_vowel_trailing(vowel[2], trailing[2], character_weight)]
    if vowel is not None:
        return [_single_vowel(vowel[2], character_weight)]
    return [_single_trailing(trailing[2], character_weight)]


def consume_jamo_cluster(units, start, records, character_weight):
    """Consume one increasing Jamo run and return its Unicode-weight elements."""
    cluster = [(units[start], jamo_class(units[start]), records[units[start]])]
    index = start + 1
    while index < len(units) and units[index] in records:
        category = jamo_class(units[index])
        if category <= cluster[-1][1]:
            break
        cluster.append((units[index], category, records[units[index]]))
        index += 1
    return _emit_cluster(cluster, records, character_weight), index - start
