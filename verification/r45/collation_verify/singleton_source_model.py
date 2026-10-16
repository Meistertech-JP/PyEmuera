"""Narrow independent interpreter of publicly parsed NLS/JAMOSORT rows.

No PyEmuera module is imported. Logical primary elements are tuples rather
than serialized bytes. This model intentionally accepts isolated or repeated
same-class Jamo, ordinary weights, marks, PUA and Extension A; it rejects an
ordered mixed-class Jamo cluster rather than inventing its Windows result.
The Jamo boundary and late punctuation direction are bounded reconstructions,
so agreement remains LOCAL_MODEL_MATCH with shared-inference limitations.
"""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "tests/fixtures/r43_collation/public_source_model_rows.json"
DATA = json.loads(SOURCE.read_text())
WEIGHTS = {int(cp, 16): tuple(row) for cp, row in DATA["weights"].items()}
JAMO = {int(cp, 16): row for cp, row in DATA["jamo"].items()}
CLASS = {"L": 0, "V": 1, "T": 2}


def trim(values):
    result = list(values)
    while result and result[-1] <= 2:
        result.pop()
    return tuple(result)


def singleton_emission(cp):
    row = JAMO[cp]
    record, category = row["record"], CLASS[row["class"]]
    filler = (*WEIGHTS[0x3164][:2], 2, 2)
    if category == 0 and cp != 0x115F:
        anchor = WEIGHTS[0xAC00 + 588 * record[1]]
        base = (anchor[0], anchor[1] - 1, 2, 2)
        context = bool(record[0])
    else:
        base = (*filler[:3], 4 if category == 2 else 2)
        context = cp != 0x115F and record[4] != 3
    extra = [2, 3, 2]
    if cp != 0x115F:
        extra[category] = record[4]
    return base, tuple((255, value, 2) for value in extra) if context else ()


def logical_key(text):
    raw = text.encode("utf-16-le", errors="surrogatepass")
    units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]
    primary, secondary, tertiary, punctuation = [], [], [], []
    for index, cp in enumerate(units):
        if cp not in WEIGHTS:
            raise ValueError("Outside explicitly declared independent source-row domain")
        extras = ()
        if cp in JAMO:
            if index + 1 < len(units) and units[index + 1] in JAMO:
                if CLASS[JAMO[units[index + 1]]["class"]] > CLASS[JAMO[cp]["class"]]:
                    raise ValueError("Ordered mixed-class Jamo context requires a separate reconstruction")
            weight, extras = singleton_emission(cp)
        else:
            weight = WEIGHTS[cp]
        script, letter, accent, case = weight
        if script == 0:
            continue
        if script == 1:
            if secondary:
                secondary[-1] = (secondary[-1] + accent) % 256
            else:
                secondary.append(accent)
            continue
        if script == 6:
            punctuation.append((-len(primary), script, letter))
            continue
        if script in (2, 3, 4):
            raise ValueError("Outside independent expansion/kana algorithm domain")
        if script == 5:
            primary.extend(((254, 255, 2), (letter, accent, 2)))
            secondary.append(2)
            tertiary.append(2)
            continue
        primary.append((script, letter, accent if 169 <= script <= 175 else 2))
        if not 169 <= script <= 175:
            secondary.append(accent)
        tertiary.append(case & 63)
        primary.extend(extras)
    return tuple(primary), trim(secondary), trim(tertiary), tuple(punctuation)


def compare(left, right):
    a, b = logical_key(left), logical_key(right)
    return (a > b) - (a < b)


def review_inputs():
    values = []
    for cp in sorted(JAMO):
        for length in (1, 3, 7, 13):
            body = chr(cp) * length
            values.extend(("v" + body + "w", "v\0" + body + "-w", "v'" + body + "w-"))
    for cp, length in ((0x61, 8190), (0x61, 16386), (0x3400, 4095), (0xE3F8, 8194), (0xD800, 8190)):
        body = chr(cp) * length
        values.extend(("'" + body + "-", body + "'-", body[:len(body) // 2] + "'-" + body[len(body) // 2:]))
    return values
