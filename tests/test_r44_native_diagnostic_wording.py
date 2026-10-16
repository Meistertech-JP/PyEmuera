"""Exact native-source spellings, fatal stages and priorities are goldens.

Counter omission, digit widths and U+FF5E are deliberate source contracts;
messages must not be normalized or copied from a fresh Python observation.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/r44_native_diagnostics"
spec = importlib.util.spec_from_file_location("r44_wording_observer", ROOT / "verification/r44/diagnostic_golden.py")
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
GOLDEN = observer.load_goldens()


class NativeDiagnosticWordingR44(unittest.TestCase):
    def test_three_original_native_source_files_retain_complete_sha(self):
        manifest = json.loads((FIXTURES / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_zip_sha256"], "fd0dd5b83ab3f929e69de0b9af739fa9bf785b6f510b30d11aaf44db35af182a")
        self.assertEqual(len(manifest["source_files"]), 3)
        for source in manifest["source_files"]:
            raw = (FIXTURES / source["local_path"]).read_bytes()
            self.assertEqual(len(raw), source["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), source["sha256"])
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(manifest["source_exe_build_same"], "UNPROVEN")

    def test_original_source_line_quotes_and_resource_counter_are_exact(self):
        manifest = json.loads((FIXTURES / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
        sources = {source["native_path"]: source for source in manifest["source_files"]}
        for case in GOLDEN["cases"]:
            for location in case["native_source_location"]:
                source = sources[location["path"]]
                raw = (FIXTURES / source["local_path"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), location["sha256"])
                self.assertEqual(raw.decode("utf-8-sig").splitlines()[location["line"] - 1], location["text"])
        text = (FIXTURES / "sources/Resources.resx").read_text(encoding="utf-8-sig")
        self.assertIn("{0}関数:少なくとも{1}個の引数が必要です", text)

    def test_direct_getbit_runtime_owner_preserves_widths_and_tilde(self):
        from pyemuera.errors import EraError
        from pyemuera.scalar_numeric import function
        with self.assertRaises(EraError) as caught:
            function("GETBIT", [1, 64])
        self.assertEqual(caught.exception.code, "E_INDEX")
        self.assertEqual(caught.exception.message, "GETBIT関数の第２引数(64)が範囲(０～６３)を超えています")
        self.assertIn("\uff5e", caught.exception.message)
        self.assertNotIn("\u301c", caught.exception.message)

    def assert_string_context(self, spelling):
        from pyemuera.decimal_instruction import build
        from pyemuera.errors import EraError
        reads = []
        context = SimpleNamespace(
            vm=SimpleNamespace(program=SimpleNamespace(expand=lambda text: text)),
            warning=lambda *arguments: reads.append(("warning", arguments)),
            infer=lambda node: spelling,
            reduce=lambda node: node,
            descriptor=lambda name: reads.append(("descriptor", name)),
            plans=[],
        )
        with self.assertRaises(EraError) as caught:
            build(context, "STR:0,2.0")
        self.assertEqual(caught.exception.code, "E_TYPE")
        self.assertEqual(caught.exception.message, "TIMES命令:第１引数を文字列変数にすることはできません")
        self.assertEqual(context.plans, [])
        self.assertEqual(reads, [])

    def test_canonical_lowercase_string_context_stops_before_descriptor_or_plan(self):
        self.assert_string_context("string")

    def test_legacy_capital_string_mock_keeps_its_existing_fatal_contract(self):
        self.assert_string_context("String")


def make_case_test(case, mode):
    def test(self):
        observation = observer.observe_case(case, mode)
        observer.assert_expected(case, observation)
        self.assertEqual(case["comparison_status"], "SOURCE_CONTRACT_MATCH")
        self.assertEqual(case["native_execution_status"], "UNOBSERVED")
    return test


for case in GOLDEN["cases"]:
    for mode in ("YES", "NO"):
        setattr(NativeDiagnosticWordingR44, "test_" + case["id"] + "_" + mode.lower(), make_case_test(case, mode))
