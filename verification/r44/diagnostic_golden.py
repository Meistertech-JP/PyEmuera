"""Run source-derived spelling fixtures without changing their raw bytes.

This observer is shared by fixed unittest expectations and the independent
r43/final-pyz replay. It never manufactures an expected message from PyEmuera.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/r44_native_diagnostics"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_goldens():
    return json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))


def observe_case(case, mode):
    from pyemuera.console import Console
    from pyemuera.data import GameData
    from pyemuera.errors import EraError
    from pyemuera.program import Program
    from pyemuera.runtime import VM

    source = FIXTURES / case["fixture"]
    if sha(source) != case["fixture_sha256"]:
        raise AssertionError("Diagnostic fixture source changed: " + case["id"])
    header = FIXTURES / "Header.ERH"
    if sha(header) != load_goldens()["Header.ERH_sha256"]:
        raise AssertionError("Diagnostic header source changed")
    with tempfile.TemporaryDirectory(prefix="r44-wording-") as temporary:
        game = Path(temporary)
        (game / "ERB").mkdir()
        (game / "CSV").mkdir()
        shutil.copyfile(source, game / "ERB/Main.ERB")
        shutil.copyfile(header, game / "ERB/Header.ERH")
        # This explicit configuration is a separate derived control, not a
        # rewrite of either immutable UTF-8 BOM ERB/ERH input.
        (game / "emuera.config").write_bytes(
            b"\xef\xbb\xbf" + ("ロード時に引数を解析する:" + mode + "\n").encode("utf-8"))
        stream = io.StringIO()
        vm = VM(Program(game), GameData(game), Console([], stream, no_wait=True), seed=42, max_steps=1000)
        initial_rng = copy.deepcopy(vm.rng.getstate())
        initial_values = {name: vm.get(name) for name in ("OR_TARGET", "OR_BIT", "OR_TRACE", "RESULT", "RESULTS")}
        load_diagnostics = [{"level": diagnostic.severity, "message": diagnostic.reference_message,
                             "file": Path(diagnostic.location.path.replace("\\", "/")).name,
                             "line": diagnostic.location.line, "category": diagnostic.category}
                            for diagnostic in vm.program.argument_diagnostics]
        error = None
        try:
            vm.run()
        except EraError as exception:
            error = exception.as_dict()
        if error is None:
            raise AssertionError("Expected exact diagnostic was not raised: " + case["id"])
        return {
            "id": case["id"], "mode": mode,
            "message": error["message"], "diagnostic_message": error["diagnostic_message"],
            "error_code": error["code"], "file": Path(error["file"].replace("\\", "/")).name,
            "line": error["line"], "load_diagnostics": load_diagnostics,
            "emitted_diagnostics": [{"level": item["severity"], "message": item["reference_message"],
                                     "file": Path(item["file"].replace("\\", "/")).name,
                                     "line": item["line"], "category": item["category"]}
                                    for item in vm.emitted_diagnostics],
            "initial_values": initial_values,
            "final_values": {name: vm.get(name) for name in initial_values},
            "rng_unchanged": vm.rng.getstate() == initial_rng,
            "trailing_marker_absent": "R44_DIAGNOSTIC_TRAILING" not in stream.getvalue(),
            "source_original_and_copy_unchanged": sha(source) == case["fixture_sha256"] == sha(game / "ERB/Main.ERB")
                and sha(header) == sha(game / "ERB/Header.ERH"),
            "frames_after_failure": len(vm.frames), "exit_reason": vm.exit_reason,
            "output": stream.getvalue(),
            "runtime_exception_numeric_level": None,
        }


def assert_expected(case, observation, strict=True):
    exact = observation["message"] == observation["diagnostic_message"] == case["native_message"] == case["pyemuera_message"]
    expected_diagnostics = []
    if observation["mode"] == "YES" and case["load_mode_fatal_at_load"]:
        expected_diagnostics = case["warning_prefix"] + [{"level": 2, "message": case["native_message"]}]
    actual_diagnostics = [{"level": item["level"], "message": item["message"]}
                          for item in observation["load_diagnostics"]]
    emitted = [{"level": item["level"], "message": item["message"]}
               for item in observation["emitted_diagnostics"]]
    checks = {
        "message_exact": exact,
        "error_code_exact": observation["error_code"] == case["error_code"],
        "file_line_exact": observation["file"] == case["file_line"]["file"] and observation["line"] == case["file_line"]["line"],
        "diagnostic_stage_level_order_exact": actual_diagnostics == emitted == expected_diagnostics,
        "diagnostic_positions_exact": all(item["file"] == "Main.ERB" and item["line"] == 2
                                           for item in observation["load_diagnostics"] + observation["emitted_diagnostics"]),
        "no_unexpected_variable_change": observation["initial_values"] == observation["final_values"],
        "rng_unchanged": observation["rng_unchanged"],
        "stop_before_trailing_marker": observation["trailing_marker_absent"],
        "source_bytes_unchanged": observation["source_original_and_copy_unchanged"],
        "frames_cleared_on_failure": observation["frames_after_failure"] == 0 and observation["exit_reason"] == "error",
    }
    if strict and not all(checks.values()):
        raise AssertionError((case["id"], observation["mode"], checks, observation))
    return checks


def run_all(strict=True):
    rows = []
    for case in load_goldens()["cases"]:
        for mode in ("YES", "NO"):
            observation = observe_case(case, mode)
            checks = assert_expected(case, observation, strict=strict)
            rows.append({"expected": case, "actual": observation, "checks": checks,
                         "comparison_status": "SOURCE_CONTRACT_MATCH" if all(checks.values()) else "SOURCE_CONTRACT_MISMATCH",
                         "new_native_execution": False})
    return rows


def module_origins():
    return {name: str(module.__file__) for name, module in sys.modules.items()
            if (name == "pyemuera" or name.startswith("pyemuera.")) and getattr(module, "__file__", None)}
