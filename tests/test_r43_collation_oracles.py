"""Raw Windows Framework observations and independent source contracts.

The three oracle populations overlap and remain separate. Extra examples are
LOCAL_SOURCE_MODEL checks, not additional Windows native observations.
"""
import hashlib
import io
import json
from pathlib import Path
import random
import shutil
import tempfile
import unittest
from unittest.mock import patch

from pyemuera.collation_portable import PortableNLSBackend
from pyemuera.console import Console
from pyemuera.data import GameData
from pyemuera.errors import EraError, Unsupported
from pyemuera.program import Program
from pyemuera.runtime import VM
from pyemuera.sort1824 import framework_list_order
from test_core import Harness
import r43_source_collation_model as source_model


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/r43_collation"
OLD = json.loads((ROOT / "tests/fixtures/r42_framework_string_probe.json").read_text())
NEW = json.loads((FIXTURE / "framework-probe-new.json").read_text())
HANGUL = json.loads((FIXTURE / "hangul-framework.json").read_text())
SOURCE_ROWS = json.loads((FIXTURE / "public_source_model_rows.json").read_text())


def decode_hex(value):
    return bytes.fromhex(value).decode("utf-16-le", errors="surrogatepass")


HANGUL_INPUTS = [decode_hex(value) for value in
                 (FIXTURE / "hangul_inputs.txt").read_text(encoding="ascii").splitlines()]
NEW_INPUTS = [decode_hex(value) for value in NEW["inputs_utf16le_hex"]]


class CollationArchivedOraclesR43(unittest.TestCase):
    def setUp(self):
        self.backend = PortableNLSBackend()

    def test_archived_input_and_oracle_bytes_are_pinned(self):
        catalog = json.loads((FIXTURE / "catalog.json").read_text())
        for row in catalog["files"]:
            raw = (FIXTURE / row["path"]).read_bytes()
            self.assertEqual(len(raw), row["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])

    def test_old_300_archived_forward_reverse_signs(self):
        self.assertEqual(len(OLD["comparisons"]), 300)
        for row in OLD["comparisons"]:
            self.assertEqual(self.backend.compare(row["left"], row["right"]), row["sign"])
            self.assertEqual(self.backend.compare(row["right"], row["left"]), -row["sign"])

    def test_new_3916_archived_forward_reverse_signs(self):
        self.assertEqual(len(NEW["comparisons"]), 3916)
        for row in NEW["comparisons"]:
            left, right = decode_hex(row["left_utf16le_hex"]), decode_hex(row["right_utf16le_hex"])
            self.assertEqual(row["CompareTo_sign"], row["CompareInfo_None_sign"])
            self.assertEqual(row["CompareTo_sign"], row["NLS_sign"])
            self.assertEqual(row["NLS_error"], 0)
            self.assertEqual(self.backend.compare(left, right), row["CompareTo_sign"])
            self.assertEqual(self.backend.compare(right, left), -row["CompareTo_sign"])

    def test_hangul_1296_archived_all_ordered_signs(self):
        self.assertEqual(len(HANGUL_INPUTS), 36)
        self.assertEqual({(r["l"], r["r"]) for r in HANGUL["pairs"]},
                         {(i, j) for i in range(36) for j in range(36)})
        for row in HANGUL["pairs"]:
            self.assertEqual(row["CompareTo"], row["CompareInfo"])
            self.assertEqual(self.backend.compare(HANGUL_INPUTS[row["l"]],
                                                 HANGUL_INPUTS[row["r"]]), row["CompareTo"])

    def test_archived_inputs_self_compare_and_key_generation(self):
        for value in NEW_INPUTS + HANGUL_INPUTS:
            self.assertEqual(self.backend.compare(value, value), 0)
            # Key generation must also succeed; compare's identical fast path
            # alone would conceal the old contextual Unsupported boundary.
            self.assertIsInstance(self.backend.sort_key(value), bytes)

    def test_distinct_input_equal_pairs_preserve_original_text(self):
        pairs = [(decode_hex(r["left_utf16le_hex"]), decode_hex(r["right_utf16le_hex"]))
                 for r in NEW["comparisons"] if r["CompareTo_sign"] == 0 and
                 r["left_utf16le_hex"] != r["right_utf16le_hex"]]
        self.assertEqual(len(pairs), 21)
        for left, right in pairs:
            original = (left, right)
            self.assertEqual(self.backend.compare(left, right), 0)
            self.assertEqual((left, right), original)

    def test_nul_and_ignorable_units_do_not_normalize_other_text(self):
        self.assertEqual(self.backend.compare("xy\0z\u00ad", "xyz"), 0)
        self.assertEqual(self.backend.compare("\0", ""), 0)
        self.assertNotEqual(self.backend.compare("xば", "xは\u3099"), 0)

    def test_surrogates_are_compared_by_utf16_units(self):
        self.assertEqual(self.backend.compare("q😀x", "q\ud83d\ude00x"), 0)
        self.assertLess(self.backend.compare("\ud800k", "\ud801k"), 0)
        self.assertLess(self.backend.compare("k\udc00", "k\udc01"), 0)

    def test_local_long_combining_byte_wrap_contract(self):
        # Unary BYTE addition/trim wraps after 256 steps. Saved Framework
        # direct-sortkey-wrap controls prove direct comparison is different;
        # do not use unary key equality as its expected result.
        for prefix in ("x", "Ω", "qwerty"):
            self.assertEqual(self.backend.sort_key(prefix + "\u3099" * 256), self.backend.sort_key(prefix))
            self.assertEqual(self.backend.compare(prefix + "\u3099" * 256, prefix), 1)
            self.assertEqual(self.backend.compare(prefix, prefix + "\u3099" * 256), -1)
        self.assertEqual(self.backend.sort_key("x\u0301"), self.backend.sort_key("x\u0301" + "\u3099" * 256))
        self.assertEqual(self.backend.compare("x\u0301", "x\u0301" + "\u3099" * 256), -1)

    def test_cache_reuses_unseen_context_and_has_bounded_eviction(self):
        backend = PortableNLSBackend(cache_size=2)
        values = ["q\u1113\u1162x", "q\u1103\u119ex", "q\u1105\ud7b7\u11a9x"]
        for value in values:
            backend.sort_key(value)
        self.assertEqual(backend.cache_info().currsize, 2)
        before = backend.cache_info().hits
        backend.sort_key(values[-1])
        self.assertEqual(backend.cache_info().hits, before + 1)
        backend.sort_key(values[0])
        self.assertEqual(backend.cache_info().currsize, 2)

    def test_unsupported_profile_fails_before_identical_fast_path(self):
        with self.assertRaises(Unsupported):
            self.backend.compare("same", "same", culture="ko-KR")
        with self.assertRaises(Unsupported):
            self.backend.compare("same", "same", options="IgnoreCase")
        with self.assertRaises(EraError) as error:
            self.backend.compare(7, 7)
        self.assertEqual(error.exception.code, "E_TYPE")

    def test_published_all_357_jamo_records_and_anchor_weights(self):
        # Independent textual parser output is cross-checked with the compiled
        # runtime data, rather than asking that data compiler for expectations.
        self.assertEqual(len(SOURCE_ROWS["jamo"]), 357)
        for cp, source in SOURCE_ROWS["jamo"].items():
            self.assertEqual(tuple(source["record"]), self.backend._jamo[int(cp, 16)])
        for cp in ("ac00", "ac01", "c544", "c9dc", "d558", "d7a3", "3164"):
            self.assertEqual(tuple(SOURCE_ROWS["weights"][cp]), self.backend._weight(int(cp, 16)))

    def test_unseen_all_jamo_records_generate_keys_in_new_contexts(self):
        for cp, row in SOURCE_ROWS["jamo"].items():
            value = chr(int(cp, 16))
            context = {"L": value + "\u1162\u11ab", "V": "\u1103" + value + "\u11ab",
                       "T": "\u1103\u1162" + value}[row["class"]]
            for text in (value, "q" + context + "e", "\0" + context + "\0"):
                self.assertIsInstance(self.backend.sort_key(text), bytes)
                self.assertEqual(self.backend.compare(text, text), 0)
                self.assertEqual(self.backend.compare(text, "q\u1102\u1163\u11a8e"),
                                 -self.backend.compare("q\u1102\u1163\u11a8e", text))

    def test_published_kana_case_width_accent_contracts(self):
        self.assertLess(self.backend.compare("ロ", "ろ"), 0)
        self.assertLess(self.backend.compare("o", "ó"), 0)
        self.assertLess(self.backend.compare("r", "R"), 0)
        self.assertNotEqual(self.backend.compare("ろ", "ﾛ"), 0)

    def test_unseen_source_model_keys_cover_punctuation_and_context(self):
        # This model is a separately written interpreter, with independently
        # parsed source rows. Its inferred modern rules are not new native
        # facts; equality here detects implementation/data integration errors.
        # r48 sort keys for combining and compatibility Jamo use the measured
        # Windows 10 ja-JP Unicode weights. The r43 source model still emits
        # the older short boundary key, so byte equality remains the contract
        # only where that model was already the Framework sort-key shape.
        values = source_model.review_inputs()
        self.assertEqual(len(values), 5177)
        checked = 0
        for value in values:
            if self._jamo_weight_changed(value):
                self.assertIsInstance(self.backend.sort_key(value), bytes)
                continue
            checked += 1
            self.assertEqual(self.backend.sort_key(value), source_model.sort_key(value))
        self.assertEqual(checked, 1405)

    def test_unseen_source_model_pair_signs_and_reused_cache(self):
        values = source_model.review_inputs()
        expected = {value: source_model.sort_key(value) for value in values}
        randomizer = random.Random(4305177)
        checked = 0
        for _ in range(10000):
            left, right = randomizer.choice(values), randomizer.choice(values)
            if self._jamo_weight_changed(left) or self._jamo_weight_changed(right):
                compared = self.backend.compare(left, right)
                self.assertEqual(self.backend.compare(right, left), -compared)
                continue
            sign = (expected[left] > expected[right]) - (expected[left] < expected[right])
            # r46 separates direct comparison from the unary sort key. Windows
            # measurements show those orders differ, including non-transitive
            # direct comparisons. This source-model contract stays on sort_key
            # order. The original compare-equals-key assertions are preserved
            # in verification/r46/test_contract_originals/.
            left_key = self.backend.sort_key(left)
            right_key = self.backend.sort_key(right)
            actual = (left_key > right_key) - (left_key < right_key)
            self.assertEqual(actual, sign)
            compared = self.backend.compare(left, right)
            self.assertEqual(self.backend.compare(right, left), -compared)
            checked += 1
        self.assertEqual(checked, 743)

    def _jamo_weight_changed(self, value):
        return any(
            ord(ch) in self.backend._jamo or 0x3131 <= ord(ch) <= 0x318E
            for ch in value
        )


class CollationArrayMSortR43(Harness):
    def test_new_windows_jamo_fixture_source_bytes_and_row_markers(self):
        manifest = json.loads((FIXTURE / "windows_unseen_probe_manifest.json").read_text())
        for row in manifest["files"]:
            raw = (FIXTURE / row["path"]).read_bytes()
            self.assertEqual(len(raw), row["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])
        fixture = FIXTURE / "windows_jamo_arraymsort"
        self.assertTrue((fixture / "ERB/Main.ERB").read_bytes().startswith(b"\xef\xbb\xbf"))
        namespace = {"__name__": "pyemuera._r43_archived_sort_model", "__package__": "pyemuera"}
        exec(compile((FIXTURE / "framework_sort_r42.py.txt").read_bytes(),
                     "ARCHIVED_R42/pyemuera/sort1824.py", "exec"), namespace)
        captured = {(HANGUL_INPUTS[r["l"]], HANGUL_INPUTS[r["r"]]): r["CompareTo"]
                    for r in HANGUL["pairs"]}
        expected = []
        for line in (FIXTURE / "windows_jamo_sort_orders.tsv").read_text().splitlines():
            label, indices = line.split("\t")
            keys = [HANGUL_INPUTS[int(index)] for index in indices.split(",")]
            with patch("pyemuera.collation1824.compare_strings", side_effect=lambda l, r: captured[l, r]):
                order = namespace["framework_list_order"](keys, string=True)
            expected.append(f"R43_JAMO_SORT|{label}|1")
            expected.extend(f"R43_JAMO_ROW|{label}|{row}|{index + 1}" for row, index in enumerate(order))
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "game"
            shutil.copytree(fixture, game)
            output = io.StringIO()
            vm = VM(Program(game), GameData(game), Console([], output, no_wait=True), seed=43,
                    max_steps=50000)
            rng = vm.rng.getstate()
            vm.run()
            actual = [line for line in output.getvalue().splitlines() if line.startswith("R43_JAMO_")]
            self.assertEqual(actual, expected)
            self.assertEqual(vm.rng.getstate(), rng)

    def test_hangul_rows_match_archived_pair_frozen_sort_model(self):
        import pyemuera.collation1824 as facade
        path = FIXTURE / "framework_sort_r42.py.txt"
        namespace = {"__name__": "pyemuera._r43_archived_sort_model", "__package__": "pyemuera"}
        exec(compile(path.read_bytes(), "ARCHIVED_R42/pyemuera/sort1824.py", "exec"), namespace)
        captured = {(HANGUL_INPUTS[r["l"]], HANGUL_INPUTS[r["r"]]): r["CompareTo"]
                    for r in HANGUL["pairs"]}
        shuffled = list(HANGUL_INPUTS)
        random.Random(4301296).shuffle(shuffled)
        for keys in (list(HANGUL_INPUTS), list(reversed(HANGUL_INPUTS)), shuffled):
            with patch.object(facade, "compare_strings", side_effect=lambda l, r: captured[l, r]):
                expected = namespace["framework_list_order"](keys, string=True)
            count = len(keys)
            vm = self.make(headers=f"#DIMS KEYS,{count}\n#DIM ROWS,{count}")
            for index, key in enumerate(keys):
                vm.set(f"KEYS:{index}", key)
                vm.set(f"ROWS:{index}", index + 1)
            rng = vm.rng.getstate()
            self.assertEqual(vm.eval("ARRAYMSORT(KEYS,ROWS)"), 1)
            self.assertEqual([vm.get(f"ROWS:{i}") for i in range(count)], [i + 1 for i in expected])
            self.assertEqual(vm.rng.getstate(), rng)

    def test_archived_framework_fifteen_source_row_permutations(self):
        backend = PortableNLSBackend()
        with patch("pyemuera.collation1824.compare_strings", side_effect=backend.compare):
            for row in NEW["sorts"]:
                keys = [NEW_INPUTS[i % 25] for i in range(row["length"])]
                self.assertEqual([i + 1 for i in framework_list_order(keys, string=True)],
                                 row["permutation"])

    def test_arraymsort_archived_row_order_and_rng_preservation(self):
        for row in NEW["sorts"]:
            if row["length"] == 0:
                continue  # Empty List.Sort is covered above; ERH DIM0 is invalid.
            count = row["length"]
            vm = self.make(headers=f"#DIMS KEYS,{count}\n#DIM ROWS,{count},2")
            for index in range(count):
                vm.set(f"KEYS:{index}", NEW_INPUTS[index % 25])
                vm.set(f"ROWS:{index}:0", index + 1)
                vm.set(f"ROWS:{index}:1", index + 10001)
            rng = vm.rng.getstate()
            self.assertEqual(vm.eval("ARRAYMSORT(KEYS,ROWS)"), 1)
            self.assertEqual([vm.get(f"ROWS:{i}:0") for i in range(count)], row["permutation"])
            self.assertEqual([vm.get(f"ROWS:{i}:1") for i in range(count)],
                             [value + 10000 for value in row["permutation"]])
            self.assertEqual(vm.rng.getstate(), rng)

    def test_hyphen_rows_match_the_archived_pair_order(self):
        keys = ["ab-", "-ab", "a-b"]
        # These three were the independent new Framework failures. Their
        # ranking is obtained from the raw comparisons, not the new engine.
        ids = [NEW_INPUTS.index(key) for key in keys]
        expected = sorted(range(3), key=lambda i: sum(
            next(row["CompareTo_sign"] for row in NEW["comparisons"]
                 if row["left_index"] == min(ids[i], other) and
                 row["right_index"] == max(ids[i], other)) * (1 if ids[i] <= other else -1)
            for other in ids))
        vm = self.make(headers="#DIMS KEYS,3\n#DIM ROWS,3")
        for index, key in enumerate(keys):
            vm.set(f"KEYS:{index}", key)
            vm.set(f"ROWS:{index}", index + 1)
        self.assertEqual(vm.eval("ARRAYMSORT(KEYS,ROWS)"), 1)
        self.assertEqual([vm.get(f"ROWS:{i}") for i in range(3)], [i + 1 for i in expected])
