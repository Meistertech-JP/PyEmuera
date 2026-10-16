"""Japanese Framework resource + source print contract, not a fresh GUI oracle."""
import copy
import hashlib
import json
from pathlib import Path
import struct

from test_core import Harness
from pyemuera.errors import EraError


ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "verification/r42/received_r41/evidence/oracle-r41/results/dotnet/format-probe-framework.json"
PIN = "c959d490fe7ba08c651551c3c7e8d034a11572cf8df529d0af0e004799fc9de3"
CAPTURE = json.loads(ORACLE.read_text(encoding="utf-8-sig"))
OVERFLOWS = [row for row in CAPTURE["times"] if "exception" in row]
INTERNAL = "値がDecimal型に対して大きすぎるか、または小さすぎます。"


class DecimalOverflowDiagnosticR44(Harness):
    def test_original_framework_probe_hash_and_japanese_resource_are_pinned(self):
        self.assertEqual(hashlib.sha256(ORACLE.read_bytes()).hexdigest(), PIN)
        self.assertEqual(CAPTURE["framework_target"], ".NETFramework,Version=v4.8")
        self.assertEqual(CAPTURE["current_culture"], "ja-JP")
        self.assertEqual(len(OVERFLOWS), 8)
        self.assertEqual({row["exception"] for row in OVERFLOWS}, {"System.OverflowException"})
        self.assertEqual({row["message"] for row in OVERFLOWS}, {"Decimal 型の値が大きすぎるか、または小さすぎます。"})
        source_base = ROOT / "tests/fixtures/r44_native_diagnostics"
        manifest = json.loads((source_base / "NUMERIC_SOURCE_MANIFEST.json").read_text())
        for source in manifest["source_files"]:
            raw = (source_base / source["local_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), source["sha256"])
            for quote in source["source_quotes"]:
                self.assertEqual(raw.decode("utf-8-sig").splitlines()[quote["line"] - 1], quote["text"])

    def test_dynamic_index_is_read_once_before_overflow_and_never_written(self):
        source = (
            "@MAIN\nTIMES OR_VALUE:INDEX(),1e29\nOR_TRACE+=100\nRETURN\n"
            "@INDEX\n#FUNCTION\nOR_TRACE+=1\nRETURNF RAND(1)\n"
        )
        vm = self.make(source, headers="#DIM OR_VALUE,4=1\n#DIM OR_TRACE\n")
        before = copy.deepcopy(vm.lookup("OR_VALUE").values)
        expected_rng = copy.deepcopy(vm.rng)
        expected_rng.randrange(1)
        with self.assertRaises(EraError) as caught:
            vm.call("MAIN")
        self.assertEqual(caught.exception.message, INTERNAL)
        self.assertEqual(caught.exception.code, "E_ARITH")
        self.assertEqual(vm.get("OR_TRACE"), 1)
        self.assertEqual(vm.lookup("OR_VALUE").values, before)
        self.assertEqual(vm.rng.getstate(), expected_rng.getstate())


def make_overflow_test(row):
    def test(self):
        multiplier = struct.unpack("<d", int(row["multiplier_bits"]).to_bytes(8, "little", signed=True))[0]
        literal = format(multiplier, ".17g").replace("e+", "e")
        self.assertEqual(struct.unpack("<q", struct.pack("<d", float(literal)))[0], int(row["multiplier_bits"]))
        vm = self.make("@MAIN\nTIMES OR_VALUE," + literal + "\nOR_TRACE+=1\nRETURN\n",
                       headers="#DIM OR_VALUE\n#DIM OR_TRACE\n")
        # The oracle supplies an Int64 value, not an ERB decimal literal.
        # In particular, parsing the positive token in -Int64.MinValue would
        # exercise a separate lexer contract before reaching TIMES.
        vm.set("OR_VALUE", int(row["original"]))
        before_value = vm.get("OR_VALUE")
        before_rng = vm.rng.getstate()
        with self.assertRaises(EraError) as caught:
            vm.call("MAIN")
        error = caught.exception
        self.assertEqual(error.code, "E_ARITH")
        self.assertEqual(error.message, INTERNAL)
        self.assertEqual(error.as_dict()["internal_message"], INTERNAL)
        self.assertEqual(error.as_dict()["diagnostic_message"], row["exception"] + ":" + row["message"])
        self.assertEqual(Path(error.location.path).name, "Main.ERB")
        self.assertEqual(error.location.line, 2)
        self.assertEqual(vm.get("OR_VALUE"), before_value)
        self.assertEqual(vm.get("OR_TRACE"), 0)
        self.assertEqual(vm.rng.getstate(), before_rng)
    return test


for index, row in enumerate(OVERFLOWS):
    setattr(DecimalOverflowDiagnosticR44, "test_captured_overflow_" + str(index + 1).zfill(2), make_overflow_test(row))
