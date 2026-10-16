"""Independent r43-versus-candidate Jamo API observation harness.

The byte-pinned baseline is loaded into its own namespace. Record objects are
opaque to the interpreter: their indexing, truth tests and attempted iteration
are logged, including failures at each read. No expected emission is generated
by the candidate engine.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/r44_jamo"
SOURCE_ROWS = json.loads((ROOT / "tests/fixtures/r43_collation/public_source_model_rows.json").read_text())
RECORDS = {int(cp, 16): tuple(value["record"]) for cp, value in SOURCE_ROWS["jamo"].items()}
WEIGHTS = {int(cp, 16): tuple(value) for cp, value in SOURCE_ROWS["weights"].items()}


@lru_cache(maxsize=1)
def baseline_module():
    raw = (FIXTURE / "collation_jamo_r43.py.txt").read_bytes()
    catalog = json.loads((FIXTURE / "catalog.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == catalog["source_sha256"]
    name = "_r44_frozen_r43_jamo_contract"
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(raw, "ARCHIVED_R43/pyemuera/collation_jamo.py", "exec"), module.__dict__)
    return module


class InjectedFailure(LookupError):
    pass


class Events:
    def __init__(self, failure_at=None):
        self.rows = []
        self.failure_at = failure_at
        self.iteration_attempts = 0

    def append(self, row):
        self.rows.append(row)
        if len(self.rows) == self.failure_at:
            raise InjectedFailure("injected at operation " + str(self.failure_at))


class FlagSpy:
    def __init__(self, character, value, events):
        self.character, self.value, self.events = character, value, events

    def __bool__(self):
        self.events.append(["record_truth", self.character, bool(self.value)])
        return bool(self.value)


class RecordSpy:
    def __init__(self, character, values, events, flag_spy=False):
        self.character, self.values, self.events, self.flag_spy = character, values, events, flag_spy

    def __getitem__(self, index):
        self.events.append(["record_read", self.character, type(index).__name__, index])
        value = self.values[index]
        if index == 0 and self.flag_spy:
            return FlagSpy(self.character, value, self.events)
        return value

    def __iter__(self):
        self.events.iteration_attempts += 1
        self.events.append(["record_iteration", self.character])
        raise AssertionError("Jamo record must not be copied or iterated")

    def __len__(self):
        self.events.iteration_attempts += 1
        self.events.append(["record_length", self.character])
        raise AssertionError("Jamo record length must not be newly inspected")


class MappingSpy:
    def __init__(self, source, events, overrides=None, flag_spy=False):
        values = dict(source)
        values.update(overrides or {})
        self.values = {cp: RecordSpy(cp, value, events, flag_spy=flag_spy) for cp, value in values.items()}
        self.events = events

    def __getitem__(self, character):
        self.events.append(["mapping_read", character])
        return self.values[character]

    def __contains__(self, character):
        self.events.append(["mapping_contains", character])
        return character in self.values


def observe(module, units, *, overrides=None, failure_at=None, flag_spy=False, weight_overrides=None):
    events = Events(failure_at)
    records = MappingSpy(RECORDS, events, overrides=overrides, flag_spy=flag_spy)
    identities = {cp: id(value) for cp, value in records.values.items()}
    weights = dict(WEIGHTS)
    weights.update(weight_overrides or {})

    def weight(character):
        events.append(["weight_read", character])
        return weights[character]

    try:
        emission = module.interpret_jamo(tuple(units), 0, records, weight)
        outcome = {"base": emission.base, "context_hex": emission.context.hex(),
                   "consumed": emission.consumed, "extra_elements": emission.extra_elements}
    except Exception as exc:
        outcome = {"exception_type": type(exc).__module__ + "." + type(exc).__qualname__,
                   "exception_message": str(exc)}
    return {"outcome": outcome, "events": events.rows,
            "record_iteration_attempts": events.iteration_attempts,
            "record_identities_preserved": identities == {cp: id(value) for cp, value in records.values.items()}}


def normal_cases():
    cases = []
    for cp, row in SOURCE_ROWS["jamo"].items():
        cp = int(cp, 16)
        context = {"L": (cp, 0x1162, 0x11AB), "V": (0x1103, cp, 0x11AB),
                   "T": (0x1103, 0x1162, cp)}[row["class"]]
        cases.extend([(f"single-{cp:04x}", (cp,)), (f"context-{cp:04x}", context),
                      (f"repeat-{cp:04x}", (cp, cp)),
                      (f"filler-{cp:04x}", (0x115F, cp, 0x1160)),
                      (f"reversed-{cp:04x}", tuple(reversed(context)))])
    return cases


def invalid_cases():
    cases = []
    for cp in (0x1100, 0x1113, 0x1161, 0x119E, 0x11A8, 0x115F, 0x1160):
        for length in range(5):
            cases.append((f"short-{cp:04x}-{length}", (cp, 0x1162, 0x11AB),
                          {cp: RECORDS[cp][:length]}, None))
    for cp in (0x1100, 0x1113, 0x119E):
        for value in (None, 7, "x", (1, "wrong-index", 0, 0, 3), (1, 0, 0, 0, None),
                      (1, 19, 0, 0, 3), (1, 0, 0, 0, 256)):
            cases.append((f"invalid-{cp:04x}-{value!r}", (cp,), {cp: value}, None))
    for value in (None, (1,), (1, 2, 3), (1, 2, 3, 4, 5)):
        cases.append((f"weight-unpack-{value!r}", (0x1161,), None, {0x3164: value}))
    return cases


def compare_contracts(candidate):
    baseline = baseline_module()
    result, mismatches = [], []
    for label, units in normal_cases():
        for flag_spy in (False, True):
            old = observe(baseline, units, flag_spy=flag_spy)
            current = observe(candidate, units, flag_spy=flag_spy)
            row = {"case_id": label + ("-truth-spy" if flag_spy else ""), "equal": old == current,
                   "observation_sha256": hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest(),
                   "events": len(old["events"])}
            result.append(row)
            if old != current:
                mismatches.append({**row, "baseline": old, "candidate": current})
    for label, units, override, weight_override in invalid_cases():
        old = observe(baseline, units, overrides=override, weight_overrides=weight_override)
        current = observe(candidate, units, overrides=override, weight_overrides=weight_override)
        row = {"case_id": label, "equal": old == current, "baseline_observation": old}
        result.append(row)
        if old != current:
            mismatches.append({**row, "candidate": current})
    failure_cases = []
    for label, units in [("modern-leading", (0x1100,)), ("old-leading", (0x1113,)),
                         ("old-cluster", (0x1112, 0x119E, 0x11AB)),
                         ("filler", (0x115F, 0x1161)), ("vowel", (0x119E,)),
                         ("trailing", (0x11A9,)), ("repeat", (0x1113, 0x1113))]:
        count = len(observe(baseline, units, flag_spy=True)["events"])
        for position in range(1, count + 1):
            old = observe(baseline, units, flag_spy=True, failure_at=position)
            current = observe(candidate, units, flag_spy=True, failure_at=position)
            row = {"case_id": f"failure-{label}-{position}", "equal": old == current,
                   "baseline_observation": old}
            failure_cases.append(row)
            if old != current:
                mismatches.append({**row, "candidate": current})
    return {"normal_and_invalid_cases": result, "failure_injection_cases": failure_cases,
            "mismatches": mismatches, "cases": len(result) + len(failure_cases),
            "matching_cases": sum(row["equal"] for row in result + failure_cases)}
