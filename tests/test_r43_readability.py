"""r42-generated observations for readable count/registry/audit refactors."""
import gzip
import importlib.util
import json
from pathlib import Path
import re
import unittest

from pyemuera import audit, custom_function_arguments, registry

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "refactor_oracle_r43", ROOT / "tools" / "refactor_semantic_r43.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
GOLDEN = json.loads(gzip.decompress(
    (ROOT / "tests/fixtures/r43_refactor_golden.json.gz").read_bytes()))
CASES = {case["id"]: case for case in GOLDEN["cases"]}


class ReadabilityR43(unittest.TestCase):
    def test_oracle_is_pinned_to_r42_final_zipapp(self):
        self.assertEqual(
            GOLDEN["r42_pyz_sha256"],
            "06ae5e5bde44401391d7224a5db5dc8a2574a1ce9b82637aed8f6b6f93c15f01")
        self.assertEqual(len(CASES), 12079)
        self.assertEqual(len(GOLDEN["rows"]), len(CASES))

    def test_unknown_name_never_requests_argument_length(self):
        class NoLength:
            def __len__(self):
                raise AssertionError("unknown name attempted to read nodes")

        self.assertIsNone(custom_function_arguments.check_count("UNREGISTERED", NoLength()))

    def test_frozen_nested_registry_values_reject_mutation(self):
        value = registry.validate_document({
            "schema_version": 1,
            "unknown": {"X": {"payload": {"value": [1, 2]}}},
        }, "unknown")
        with self.assertRaises(TypeError):
            value["X"]["payload"]["value"][0] = 3
        with self.assertRaises(TypeError):
            value["X"]["payload"]["value"] = (3,)
        self.assertEqual(value["X"]["payload"]["value"], (1, 2))


# Python 3.14 extended the interpreter's own TypeError text for unhashable set
# members and dict keys ("cannot use 'list' as a set element (unhashable type:
# 'list')"). The golden rows were recorded with the earlier wording. Only that
# interpreter-owned text is mapped back; the exception class, the reported
# type name, the args shape and every access event are still compared exactly.
_PY314_UNHASHABLE = re.compile(
    r"cannot use '[^']+' as a (?:set element|dict key) \((unhashable type: '[^']+')\)\Z")


def python_wording_compatible(actual, expected):
    outcome = actual.get("outcome") if isinstance(actual, dict) else None
    exc = outcome.get("exception") if isinstance(outcome, dict) else None
    want = expected.get("outcome", {}).get("exception") if isinstance(expected.get("outcome"), dict) else None
    if not (isinstance(exc, dict) and isinstance(want, dict)):
        return actual
    if exc.get("class") != "builtins.TypeError" or want.get("class") != "builtins.TypeError":
        return actual
    if set(exc) != {"class", "str", "args"} or exc.get("args") != [exc.get("str")]:
        return actual
    match = _PY314_UNHASHABLE.match(exc["str"])
    if match is None:
        return actual
    legacy = match.group(1)
    return dict(actual, outcome=dict(outcome, exception=dict(exc, str=legacy, args=[legacy])))


def group_test(group):
    def check(self):
        for expected in GOLDEN["rows"]:
            if expected["group"] == group:
                with self.subTest(case=expected["id"]):
                    actual = oracle.observe_case(
                        CASES[expected["id"]], registry, custom_function_arguments, audit)
                    self.assertEqual(python_wording_compatible(actual, expected), expected)
    return check


class PythonWordingCompatibilityR51(unittest.TestCase):
    """The mapping accepts only the interpreter's reworded unhashable TypeError."""

    @staticmethod
    def row(kind, text, events=(("get", "$", "schema_version"),)):
        return {"id": "x", "group": "g", "outcome": {"exception": {"class": kind, "str": text, "args": [text]}},
                "access_events": [list(e) for e in events]}

    def test_maps_python_314_set_and_dict_wording_only(self):
        legacy = self.row("builtins.TypeError", "unhashable type: 'list'")
        for text in ("cannot use 'list' as a set element (unhashable type: 'list')",
                     "cannot use 'list' as a dict key (unhashable type: 'list')"):
            self.assertEqual(python_wording_compatible(self.row("builtins.TypeError", text), legacy), legacy)

    def test_current_interpreter_message_is_one_of_the_two_forms(self):
        with self.assertRaises(TypeError) as raised:
            [1] in set()
        actual = self.row("builtins.TypeError", str(raised.exception))
        legacy = self.row("builtins.TypeError", "unhashable type: 'list'")
        self.assertEqual(python_wording_compatible(actual, legacy), legacy)

    def test_still_detects_wrong_type_class_events_and_other_messages(self):
        legacy = self.row("builtins.TypeError", "unhashable type: 'list'")
        wrong = [
            self.row("builtins.TypeError", "cannot use 'dict' as a set element (unhashable type: 'dict')"),
            self.row("builtins.ValueError", "cannot use 'list' as a set element (unhashable type: 'list')"),
            self.row("builtins.TypeError", "cannot use 'list' as a set element (unhashable type: 'list')",
                     events=(("contains", "$", "commands"),)),
            self.row("builtins.TypeError", "some other failure"),
        ]
        for actual in wrong:
            with self.subTest(actual=actual):
                self.assertNotEqual(python_wording_compatible(actual, legacy), legacy)

    def test_era_diagnostics_and_extra_fields_are_never_rewritten(self):
        text = "cannot use 'list' as a set element (unhashable type: 'list')"
        actual = self.row("builtins.TypeError", text)
        actual["outcome"]["exception"]["era_diagnostic"] = {"code": "E_INTERNAL"}
        self.assertIs(python_wording_compatible(actual, self.row("builtins.TypeError", "unhashable type: 'list'")), actual)


for group in sorted({row["group"] for row in GOLDEN["rows"]}):
    setattr(ReadabilityR43, "test_r42_observations_" + group, group_test(group))
