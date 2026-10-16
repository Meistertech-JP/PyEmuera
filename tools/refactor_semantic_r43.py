"""Independent r42 observation oracle for readability refactors.

Fresh isolated processes bind all engine imports to the requested zipapp/source.
Neutral inputs preserve failure order, exact diagnostics and access traces.
"""
from __future__ import annotations

import argparse
import ast
import copy
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BASELINE_HASH = "06ae5e5bde44401391d7224a5db5dc8a2574a1ce9b82637aed8f6b6f93c15f01"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def thaw(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {key: thaw(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(child) for child in value]
    return value


def load_engine(engine):
    sys.path.insert(0, str(Path(engine).resolve()))
    return tuple(importlib.import_module("pyemuera." + name)
                 for name in ("registry", "custom_function_arguments", "audit"))


def make_cases(registry, custom):
    cases = []
    counts = {}

    def add(group, **payload):
        index = counts.get(group, 0)
        counts[group] = index + 1
        cases.append({"id": group + "|" + str(index), "group": group, **payload})

    names = sorted(set(registry.FUNCTION_SPECS) | custom.SUPPORTED |
                   {"UNREGISTERED", "csvname", ""})
    for name in names:
        for count in list(range(11)) + [65535, 100001]:
            add("argument_counts", name=name, count=count)
    for mask in range(16):
        for name in ("OVERLAP", "FINDELEMENT", "STRFIND", "GETBIT", "SAVETEXT"):
            for count in range(8):
                add("argument_overlap", name=name, count=count,
                    categories=[category for bit, category in enumerate(
                        ("CSV_SCALAR", "CSV_NUMERIC", "RANGE", "BASE_FIXED"))
                        if mask & (1 << bit)])
    for kind, bundled in (
        ("commands", registry.COMMAND_SPECS), ("functions", registry.FUNCTION_SPECS),
        ("variables", registry.VARIABLE_SPECS), ("syntax", registry.SYNTAX_SPECS)
    ):
        table = thaw(bundled)
        add("registry_valid", kind=kind, document={"schema_version": 1, kind: table})
        for name, spec in table.items():
            add("registry_valid", kind=kind,
                document={"schema_version": 1, kind: {name: spec}})
        selected = {}
        for name, spec in table.items():
            key = (spec.get("family"), spec.get("handler"), spec.get("kind"),
                   spec.get("argument_diagnostic_policy"))
            selected.setdefault(key, (name, spec))
        for name, spec in selected.values():
            add("registry_unknown_keys", kind=kind, document={
                "schema_version": 1, "extra": "retained",
                kind: {name: {**spec, "unexpected_key": {"retained": True}}}})
            for key in spec:
                missing = copy.deepcopy(spec)
                missing.pop(key)
                add("registry_mutations", kind=kind,
                    document={"schema_version": 1, kind: {name: missing}})
            keys = ("family", "force_set_argument", "load_argument_contract",
                    "method_safe", "min_args", "max_args", "argument_mode", "column",
                    "newline", "wait", "timed", "one", "handler", "reference_first",
                    "argument_diagnostic_policy", "argument_diagnostic_types",
                    "dimensions", "legacy_a9_dimensions", "kind", "primitive")
            for key in keys:
                if key not in spec and key not in (
                    "force_set_argument", "load_argument_contract", "method_safe"
                ):
                    continue
                values = (None, False, True, -1, 0, 1, 4, 100001, "", "INVALID",
                          [], {}, [True], [0], [1000001], [1, 2, 3, 4])
                for value in values:
                    mutated = copy.deepcopy(spec)
                    mutated[key] = value
                    add("registry_mutations", kind=kind,
                        document={"schema_version": 1, kind: {name: mutated}})
        documents = (None, [], 1, "document", {}, {"schema_version": 0, kind: {}},
                     {"schema_version": True, kind: {}}, {"schema_version": 1, kind: []})
        for document in documents:
            add("registry_schema", kind=kind, document=document)
        for name in ("", "lowercase", "日本語", "SP ACE", "X!"):
            add("registry_names", kind=kind,
                document={"schema_version": 1, kind: {name: {}}})
    for entries in (
        {"X": {"family": "INVALID", "method_safe": 1}},
        {"X": {"family": "print", "force_set_argument": 1,
               "load_argument_contract": None}},
        {"FIRST": {"family": "INVALID"}, "SECOND": {"family": "print"}},
        {"SECOND": {"family": "print"}, "FIRST": {"family": "INVALID"}},
    ):
        add("registry_multiple_errors", kind="commands",
            document={"schema_version": 1, "commands": entries})
    for raw in (
        '{"schema_version":1,"commands":{"X":{"family":"call","family":"print"}}}',
        '{"schema_version":1,"schema_version":2,"commands":{}}',
        '{"schema_version":1,"commands":',
        '{\r\n"schema_version":1,"commands":{}}',
        '{"schema_version":1,"commands":{"X":{"family":"call"}}}',
    ):
        add("registry_json", kind="commands", raw=raw)
    add("registry_unknown_kind", kind="unknown",
        document={"schema_version": 1, "unknown": {"X": {"retained": [1, 2]}}})
    for syntax, commands, functions in (
        ({"S": {"closes_with": "E"}, "E": {"kind": "marker"}},
         {"F": {"family": "expression"}}, {"F": {}}),
        ({"S": {"closes_with": "E"}}, {}, {}),
        ({"S": {"closes_with": "E"}, "E": {"kind": "loop"}}, {}, {}),
        ({}, {"F": {"family": "expression"}}, {}),
        ({"S": {"closes_with": "E"}}, {"F": {"family": "expression"}}, {}),
        ({"A": {"closes_with": "NO1"}, "B": {"closes_with": "NO2"}}, {}, {}),
    ):
        add("registry_cross_reference", syntax=syntax, commands=commands,
            functions=functions)
    for with_data in (False, True):
        for attributes in ([], ["FUNCTION"], ["FUNCTIONS"]):
            for texts in (
                ["PRINTL text", "RETURN"],
                ["CALL MISSING", "TRYGOTO MISSING", "GOTO MISSING", "CALL CHILD"],
                ["CALLFORM %MISSING()%", "CALL CHILD(", "RETURN"],
                ["UNKNOWN 1", "PRINTS MISSING$", "A=NOFUNC(1)", 'PRINTS STRFORM("x")'],
                ["$LABEL", 'A=STRLEN("x")', 'LOCALS="raw"', 'PRINTV "x",2'],
                ["PRINTW text", "TINPUT 1", "SKIPDISP 1", "REUSELASTLINE x", "PRINTC x"],
                ["A++", "++A", 'S="raw"', "PRINTS S", "IF NOFUNC(1)",
                 "CALL !!ERROR!!"],
            ):
                add("audit_inventory", with_data=with_data,
                    attributes=attributes, texts=texts)
    for op in sorted(set(registry.COMMAND_SPECS) | {"_ASSIGN", "UNKNOWN"}):
        for arg in ("", "A=2", "A++", "++A", '"literal",1', "A", "NOFUNC(2)", "broken("):
            add("audit_expression_sources", op=op, arg=arg)
    return cases


class TrackedDict(dict):
    def __init__(self, value, events, path="$"):
        self.events, self.path = events, path
        for key, child in value.items():
            dict.__setitem__(self, key, track(child, events, path + "/" + str(key)))

    def get(self, key, default=None):
        self.events.append(["get", self.path, key])
        return dict.get(self, key, default)

    def __getitem__(self, key):
        self.events.append(["getitem", self.path, key])
        return dict.__getitem__(self, key)

    def __contains__(self, key):
        self.events.append(["contains", self.path, key])
        return dict.__contains__(self, key)

    def items(self):
        self.events.append(["items", self.path])
        return dict.items(self)


def track(value, events, path):
    if isinstance(value, dict):
        return TrackedDict(value, events, path)
    if isinstance(value, list):
        return [track(child, events, path + "/" + str(i))
                for i, child in enumerate(value)]
    return value


def exception(exc):
    result = {"class": type(exc).__module__ + "." + type(exc).__name__,
              "str": str(exc), "args": thaw(exc.args)}
    if hasattr(exc, "as_dict"):
        result["era_diagnostic"] = exc.as_dict()
    return result


def cross_reference(registry, case):
    if hasattr(registry, "_validate_cross_references"):
        return registry._validate_cross_references(
            case["syntax"], case["commands"], case["functions"])
    # The oracle executes the r42 module's actual import-time loops, rather
    # than implementing a second copy of the validation conditions.
    from inspect import getsource
    tree = ast.parse(getsource(registry))
    nodes = [node for node in tree.body if isinstance(node, ast.For)
             and isinstance(node.iter, ast.Call)
             and isinstance(node.iter.func, ast.Attribute)
             and isinstance(node.iter.func.value, ast.Name)
             and node.iter.func.value.id in ("SYNTAX_SPECS", "COMMAND_SPECS")]
    assert len(nodes) == 2
    code = compile(ast.Module(body=nodes, type_ignores=[]), registry.__file__, "exec")
    exec(code, {"SYNTAX_SPECS": case["syntax"], "COMMAND_SPECS": case["commands"],
                "FUNCTION_SPECS": case["functions"], "_error": registry._error})


def observe_case(case, registry, custom, audit):
    group = case["group"]
    events = []
    try:
        if group.startswith("argument_"):
            original = {key: getattr(custom, key) for key in (
                "CSV_SCALAR", "CSV_NUMERIC", "RANGE", "BASE_FIXED", "SUPPORTED")}
            try:
                if group == "argument_overlap":
                    for key in case["categories"]:
                        if key == "BASE_FIXED":
                            custom.BASE_FIXED = {
                                **custom.BASE_FIXED,
                                case["name"]: ("Int64", "Int64")}
                        else:
                            setattr(custom, key, getattr(custom, key) | {case["name"]})
                    custom.SUPPORTED = custom.SUPPORTED | {case["name"]}

                class Membership:
                    def __init__(self, label, values):
                        self.label, self.values = label, values

                    def __contains__(self, name):
                        events.append(["contains", self.label, name])
                        return name in self.values

                for key in original:
                    setattr(custom, key, Membership(key, getattr(custom, key)))

                class Nodes:
                    def __len__(self):
                        events.append("len")
                        return case["count"]

                value = custom.check_count(case["name"], Nodes())
            finally:
                for key, old in original.items():
                    setattr(custom, key, old)
        elif group == "registry_cross_reference":
            value = cross_reference(registry, case)
        elif group.startswith("registry_"):
            document = (json.loads(case["raw"], object_pairs_hook=registry._unique)
                        if "raw" in case else copy.deepcopy(case["document"]))
            document = track(document, events, "$")
            before = canonical(thaw(document))
            events.clear()
            try:
                value = registry.validate_document(document, case["kind"])
                result = {"value": thaw(value),
                          "immutable_mapping": isinstance(value, MappingProxyType),
                          "key_order": list(value)}
            finally:
                access_events = list(events)
                after = canonical(thaw(document))
                events[:] = access_events
                if before != after:
                    raise AssertionError("validator mutated input")
            value = result
        elif group == "audit_expression_sources":
            value = audit.expression_sources(case["op"], case["arg"],
                                             {"A", "LOCAL", "ARG"})
        elif group == "audit_inventory":
            from pyemuera.errors import EraError, LoadDiagnostic, Location
            lines = [SimpleNamespace(text=text, location=Location("neutral.ERB", i + 10))
                     for i, text in enumerate(case["texts"])]
            fn = SimpleNamespace(
                lines=lines, declarations=[SimpleNamespace(text="#DIM D,2"),
                                          SimpleNamespace(text="#DIMS S,2")],
                attributes=set(case["attributes"]), labels={"LABEL": 0})
            program = SimpleNamespace(
                load_errors=[EraError("neutral earlier load issue",
                                     Location("neutral.ERB", 1), "E_SYNTAX")],
                lexical_diagnostics=[LoadDiagnostic(
                    1, "E_LEX", Location("neutral.ERB", 99), "neutral",
                    "neutral lexical warning", 0)],
                functions={"MAIN": [fn], "CHILD": []},
                globals=[SimpleNamespace(text="#DIM A,3")],
                warnings=["program warning"], files=["neutral.ERB"])

            def expand(text):
                events.append(["expand", text])
                if text == "!!ERROR!!":
                    raise EraError("neutral expand error", code="E_SYNTAX")
                return text

            program.expand = expand
            data = (SimpleNamespace(
                variables={"A": SimpleNamespace(string=False),
                           "S": SimpleNamespace(string=True)},
                warnings=["data warning"], files=["neutral.CSV"])
                if case["with_data"] else None)
            value = audit.audit(program, data)
            value.pop("engine_version")  # Explicit identity-only exclusion.
        else:
            raise AssertionError(group)
        outcome = {"return": thaw(value)}
    except Exception as exc:
        outcome = {"exception": exception(exc)}
    return {"id": case["id"], "group": group, "outcome": outcome,
            "access_events": events}


def worker(args):
    registry, custom, audit = load_engine(args.engine)
    if args.positions:
        from pyemuera.errors import InternalError, Location
        try:
            registry.validate_document(
                {"schema_version": 1, "commands": {12: {"family": "call"}}},
                "commands")
        except Exception as exc:
            value = InternalError(exc, Location("neutral.ERB", 123)).as_dict()
            args.out.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            return
        raise AssertionError("neutral malformed direct API input did not fail")
    if args.generate:
        cases = make_cases(registry, custom)
        args.out.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
        print(len(cases))
        return
    cases = json.loads(args.cases.read_text())
    result = {
        "engine": str(Path(args.engine).resolve()),
        "import_origins": [module.__file__ for module in (registry, custom, audit)],
        "rows": [observe_case(case, registry, custom, audit) for case in cases]}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(len(result["rows"]))


def run(args):
    assert digest(args.baseline.read_bytes()) == BASELINE_HASH
    out = (args.proof_directory or ROOT / "verification/r43/readability/semantic").resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = out / "inputs.json"
    base = out / "r42_observations.json"
    candidate = out / "candidate_observations.json"
    positions_base = out / "r42_developer_positions.json"
    positions_candidate = out / "candidate_developer_positions.json"
    script = Path(__file__).resolve()
    commands = (
        [sys.executable, "-I", "-B", str(script), "--worker", "--generate",
         "--engine", str(args.baseline), "--out", str(cases)],
        [sys.executable, "-I", "-B", str(script), "--worker", "--engine",
         str(args.baseline), "--cases", str(cases), "--out", str(base)],
        [sys.executable, "-I", "-B", str(script), "--worker", "--engine",
         str(args.candidate), "--cases", str(cases), "--out", str(candidate)],
        [sys.executable, "-I", "-B", str(script), "--worker", "--positions",
         "--engine", str(args.baseline), "--out", str(positions_base)],
        [sys.executable, "-I", "-B", str(script), "--worker", "--positions",
         "--engine", str(args.candidate), "--out", str(positions_candidate)],
    )
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(completed.stderr)
    b = json.loads(base.read_text())
    c = json.loads(candidate.read_text())
    assert len(b["rows"]) == len(c["rows"])
    changed = [left["id"] for left, right in zip(b["rows"], c["rows"])
               if left != right]
    groups = {}
    for group in sorted({row["group"] for row in b["rows"]}):
        rows = [row for row in b["rows"] if row["group"] == group]
        groups[group] = {"count": len(rows),
                         "changed": sum(row["id"] in changed for row in rows)}
    before_debug = json.loads(positions_base.read_text())
    after_debug = json.loads(positions_candidate.read_text())
    before_frames = before_debug["internal_diagnostic"].pop("frames")
    after_frames = after_debug["internal_diagnostic"].pop("frames")
    assert before_debug == after_debug
    report = {
        "format": "PyEmuera-r43-refactor-semantics-1",
        "scope": "REFACTOR_ONLY_BASELINE_OBSERVATIONS",
        "r42_pyz_sha256": BASELINE_HASH,
        "candidate_engine": str(args.candidate),
        "candidate_pyz_sha256": (
            digest(args.candidate.read_bytes()) if args.candidate.is_file() else None),
        "candidate_source_sha256": {
            "pyemuera/" + name: digest((args.candidate / "pyemuera" / name).read_bytes())
            for name in ("registry.py", "custom_function_arguments.py", "audit.py")
        } if args.candidate.is_dir() else {},
        "cases": len(b["rows"]), "changed_ids": changed, "groups": groups,
        "baseline_import_origins": b["import_origins"],
        "candidate_import_origins": c["import_origins"],
        "proof_files": [{"file": str(p.relative_to(ROOT)),
                         "sha256": digest(p.read_bytes())}
                        for p in (cases, base, candidate, positions_base, positions_candidate)],
        "developer_position_review": {
            "same_era_location_and_diagnostic_after_frames_removed": True,
            "r42_frames": before_frames, "candidate_frames": after_frames,
            "changed_frame_sequence": before_frames != after_frames,
            "interpretation": "Python debugger/developer frame lines now refer to the reformatted source and extracted helpers; this is an intentional source-position effect, not claimed byte-identical debug metadata."},
        "excluded_identity_fields": ["audit.engine_version"],
        "not_excluded": [
            "ERA diagnostic location/body/type", "exception type and body",
            "dictionary access/short-circuit order", "JSON key order",
            "input mutation", "command counts", "dynamic call deferral",
            "audit issue ordering"],
        "limits": [
            "Enumerates registered names and selected JSON type/boundary mutation domains; not arbitrary Python objects or every malformed JSON value.",
            "Source positions and helper frames in developer tracebacks change and are documented separately. These neutral cases do not execute RNG."]}
    (ROOT / "R43_REFACTOR_SEMANTIC_VERIFICATION.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    golden = ROOT / "tests/fixtures/r43_refactor_golden.json.gz"
    payload = {"r42_pyz_sha256": BASELINE_HASH,
               "cases": json.loads(cases.read_text()), "rows": b["rows"]}
    generated_golden = gzip.compress(
        (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(),
        mtime=0)
    if args.verify_frozen_golden:
        assert golden.read_bytes() == generated_golden, "frozen r42 oracle changed"
    else:
        golden.write_bytes(generated_golden)
    print(json.dumps({"cases": len(b["rows"]), "changed": len(changed), "groups": groups}))
    if changed:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--positions", action="store_true")
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path, default=ROOT)
    parser.add_argument("--proof-directory", type=Path)
    parser.add_argument("--verify-frozen-golden", action="store_true")
    args = parser.parse_args()
    worker(args) if args.worker else run(args)


if __name__ == "__main__":
    main()
