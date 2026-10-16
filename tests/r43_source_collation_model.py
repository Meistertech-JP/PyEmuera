"""Independent narrow interpreter for public rows and modern-profile hypotheses.

This review model does not import any PyEmuera module. It deliberately handles
only the data subset in its fixture (Jamo/Hangul, ASCII, selected marks, word
punctuation, PUA/Extension-A and surrogate boundaries). Its modern Jamo context
and late word-position rules share documented compatibility hypotheses;
model agreement is LOCAL_SOURCE_MODEL, never independent Windows confirmation.
"""
import json
from pathlib import Path
import random


FIXTURE = Path(__file__).parent / "fixtures/r43_collation/public_source_model_rows.json"
DATA = json.loads(FIXTURE.read_text())
WEIGHTS = {int(cp, 16): tuple(value) for cp, value in DATA["weights"].items()}
JAMO = {int(cp, 16): value for cp, value in DATA["jamo"].items()}
CLASSES = {"L": 0, "V": 1, "T": 2}
FILLERS = {0x115F, 0x1160}


def code_units(text):
    raw = text.encode("utf-16-le", errors="surrogatepass")
    return [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]


def contextual_primary(group):
    categories = {JAMO[cp]["class"]: JAMO[cp]["record"][4]
                  for cp in group if cp != 0x115F}
    return bytes([2, 255, categories.get("L", 2),
                  255, categories.get("V", 3), 255, categories.get("T", 2)])


def jamo_plan(units, offset):
    group = [units[offset]]
    for cp in units[offset + 1:offset + 3]:
        if cp not in JAMO or CLASSES[JAMO[cp]["class"]] <= CLASSES[JAMO[group[-1]]["class"]]:
            break
        group.append(cp)
    filler = (*WEIGHTS[0x3164][:2], 2, 2)
    first = group[0]
    categories = {JAMO[cp]["class"] for cp in group}
    old_context = any(JAMO[cp]["record"][0] for cp in group)
    accepts_context = (JAMO[first]["class"] == "L" and len(group) > 1
                       and old_context and ("V" in categories or first == 0x115F))
    if accepts_context:
        indices = [max(JAMO[cp]["record"][field] for cp in group) for field in (1, 2, 3)]
        if indices[1] == 20:
            nearest = 0xAC00 + (indices[0] * 21 + indices[1]) * 28 + indices[2]
            if nearest == 0xD7A3:
                base = filler
            else:
                anchor = WEIGHTS[nearest + 1]
                base = (anchor[0], anchor[1] - 2, 2, 2)
        else:
            anchor = WEIGHTS[0xAC00 + 588 * JAMO[first]["record"][1]]
            base = (anchor[0], anchor[1] - 1, 2, 2)
        offsets = {JAMO[cp]["class"]: JAMO[cp]["record"][4]
                   for cp in group if cp != 0x115F}
        if (base[:2] == filler[:2] and offsets.get("L", 2) == 2
                and offsets.get("V", 3) == 3
                and JAMO[group[-1]]["class"] == "T" and offsets["T"] == 3):
            return (*base[:3], 4), b"", len(group), None
        deferred = offsets.get("L", 2) if base[:2] != filler[:2] else None
        weights = [2 if deferred is not None else offsets.get("L", 2),
                   offsets.get("V", 3), offsets.get("T", 2)]
        # Same measured exception as collation_jamo: a neutral
        # vowel-boundary cluster compares as its base element alone.
        if deferred is None and weights == [2, 3, 2]:
            extra = b""
        else:
            extra = bytes([2, 255, weights[0], 255, weights[1], 255, weights[2]])
        return base, extra, len(group), deferred
    cp = first
    kind, record = JAMO[cp]["class"], JAMO[cp]["record"]
    if kind == "L" and cp != 0x115F:
        syllable = WEIGHTS[0xAC00 + 588 * record[1]]
        base = (syllable[0], syllable[1] - 1, 2, 2)
        extra = contextual_primary([cp]) if record[0] else b""
    else:
        base = (*filler[:3], 4 if kind == "T" else 2)
        extra = contextual_primary([cp]) if cp != 0x115F and record[4] != 3 else b""
    return base, extra, 1, None


def trimmed(values):
    values = list(values)
    while values and values[-1] <= 2:
        values.pop()
    return bytes(values)


def sort_key(text):
    units = code_units(text)
    primary, leading_extra, secondary, tertiary, punctuation = [], [], [], [], []
    count, offset = 0, 0
    while offset < len(units):
        cp = units[offset]
        consumed, context, deferred = 1, b"", None
        weight = WEIGHTS.get(cp)
        if weight is None:
            raise ValueError("Outside the independent model input domain")
        if cp in JAMO:
            weight, context, consumed, deferred = jamo_plan(units, offset)
        script, letter, accent, casing = weight
        if script == 0:
            pass
        elif script == 1:
            if secondary:
                secondary[-1] = (secondary[-1] + accent) % 256
            else:
                secondary.append(accent)
        elif script == 6:
            # Captured Windows 10 signs retain positions beyond 8192. This
            # prefix-free encoding is the model's representation, not a
            # received Windows sort-key byte sequence.
            width = max(1, (count.bit_length() + 7) // 8)
            punctuation.extend([0] * width + [1])
            punctuation.extend(value ^ 255 for value in count.to_bytes(width, "big"))
            punctuation.extend([script, letter])
        elif script in (2, 3, 4):
            raise ValueError("Outside the independent model algorithm domain")
        elif script == 5:
            primary.extend([254, 255, 2, letter, accent, 2])
            secondary.append(2)
            tertiary.append(2)
            count += 2
        else:
            primary.extend([script, letter, accent if 169 <= script <= 175 else 2])
            if not 169 <= script <= 175:
                secondary.append(accent)
            tertiary.append(casing & 63)
            for index in range(1, len(context), 2):
                primary.extend([context[index], context[index + 1], 2])
            if deferred is not None:
                leading_extra.append(deferred)
            count += 1 + (3 if context else 0)
        offset += consumed
    return (bytes(primary) + b"\1" + bytes(leading_extra) + b"\1" + trimmed(secondary) + b"\1" + trimmed(tertiary)
            + b"\1\1" + bytes(punctuation) + b"\0")


def compare(left, right):
    left_key, right_key = sort_key(left), sort_key(right)
    return (left_key > right_key) - (left_key < right_key)


def review_inputs():
    """Unseen examples exercise every public record and class-order boundary."""
    result = set()
    for cp, item in JAMO.items():
        value = chr(cp)
        result.add(value)
        result.add("q" + value + "e")
        contexts = {"L": value + "\u1162\u11ab", "V": "\u1103" + value + "\u11ab",
                    "T": "\u1103\u1162" + value}
        context = contexts[item["class"]]
        result.update([context, "q" + context + "e", value + value,
                       value + "\0\u1103\u1162\u11ab", "\u115f" + value + "\u1160"])
    # Reverse class sequences, repeated classes, fillers, combining/ignorable
    # boundaries and separators are outside the original 36-input corpus.
    randomizer = random.Random(430357)
    all_units = tuple(sorted(JAMO))
    for _ in range(512):
        sequence = "".join(chr(randomizer.choice(all_units)) for _ in range(randomizer.randrange(1, 7)))
        result.add(sequence)
        result.add("q" + sequence + "-e")
    for cp, weight in WEIGHTS.items():
        if weight[0] == 6:
            for base in ("abcde", "12345", "AbCdE", "\ue3f8abc", "\u3400abc",
                         "\u1113\u1162\u11ababc"):
                for position in range(len(base) + 1):
                    result.add(base[:position] + chr(cp) + base[position:])
    result.update(["abcde", "abcde\u0301", "a\u3099" * 256, "\ud800abc", "abc\udc00"])
    return sorted(result, key=lambda value: value.encode("utf-16-le", errors="surrogatepass"))
