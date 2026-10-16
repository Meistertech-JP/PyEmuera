"""r44 Windows Framework observations replayed through the selected engine.

Expected signs and row identities are the original UTF-16 oracle bytes. The
additional context properties are local model checks, never new Windows facts.
"""
import gzip
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from pyemuera.collation_portable import PortableNLSBackend
from pyemuera import collation_jamo
from pyemuera.sort1824 import framework_list_order
import r44_jamo_contract
from test_core import Harness


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/r45_collation"
PINS = {
    "NEW_framework_r44.json.gz": "e1fff148009bcdd74b5eacc1a8f919bbccbb73ad222f7f903ad279c2ba69738c",
    "NEW_framework_boundaries_r44.json.gz": "60c066917782741079efd4833bbcfc6c9ed3e6ab15a3aac9a4a2584836b13261",
}


def decode(value):
    return bytes.fromhex(value).decode("utf-16-le", errors="surrogatepass")


def load(name):
    raw = (FIXTURE / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PINS[name]:
        raise ValueError("Received r44 Framework oracle bytes differ")
    return json.loads(gzip.decompress(raw))


MAIN = load("NEW_framework_r44.json.gz")
LONG = load("NEW_framework_boundaries_r44.json.gz")


class CollationReceivedR45(unittest.TestCase):
    def setUp(self):
        self.backend = PortableNLSBackend(cache_size=16384)

    def test_received_original_utf16_inputs_and_framework_sign_agreement(self):
        for oracle in (MAIN, LONG):
            for row in oracle["comparisons"]:
                self.assertEqual(row["left_utf16le_hex"], oracle["inputs_utf16le_hex"][row["left_index"]])
                self.assertEqual(row["right_utf16le_hex"], oracle["inputs_utf16le_hex"][row["right_index"]])
                self.assertEqual(row["CompareTo_sign"], row["CompareInfo_None_sign"])
                self.assertEqual(row["CompareTo_sign"], row["NLS_sign"])
                self.assertEqual(row["NLS_error"], 0)
                for field in ("left_utf16le_hex", "right_utf16le_hex"):
                    self.assertEqual(decode(row[field]).encode("utf-16-le", errors="surrogatepass").hex(), row[field])

    def test_new_31991_framework_forward_signs(self):
        self.assertEqual(len(MAIN["comparisons"]), 31991)
        for index, row in enumerate(MAIN["comparisons"]):
            self.assertEqual(self.backend.compare(decode(row["left_utf16le_hex"]), decode(row["right_utf16le_hex"])),
                             row["CompareTo_sign"], f"received oracle row {index}")

    def test_new_31991_framework_reverse_signs(self):
        for index, row in enumerate(MAIN["comparisons"]):
            self.assertEqual(self.backend.compare(decode(row["right_utf16le_hex"]), decode(row["left_utf16le_hex"])),
                             -row["CompareTo_sign"], f"received oracle row {index}")

    def test_all_5213_inputs_key_generation_self_and_cache(self):
        self.assertEqual(len(MAIN["inputs_utf16le_hex"]), 5213)
        for value in MAIN["inputs_utf16le_hex"]:
            text = decode(value)
            key = self.backend.sort_key(text)
            self.assertIsInstance(key, bytes)
            self.assertEqual(self.backend.compare(text, text), 0)
            before = self.backend.cache_info().hits
            self.assertEqual(self.backend.sort_key(text), key)
            self.assertEqual(self.backend.cache_info().hits, before + 1)

    def test_new_18_distinct_original_strings_equal_without_rewriting(self):
        rows = [r for r in MAIN["comparisons"] if r["CompareTo_sign"] == 0
                and r["left_utf16le_hex"] != r["right_utf16le_hex"]]
        self.assertEqual(len(rows), 18)
        for row in rows:
            left, right = decode(row["left_utf16le_hex"]), decode(row["right_utf16le_hex"])
            before = left.encode("utf-16-le", errors="surrogatepass"), right.encode("utf-16-le", errors="surrogatepass")
            self.assertEqual(self.backend.compare(left, right), 0)
            self.assertEqual(before, (left.encode("utf-16-le", errors="surrogatepass"), right.encode("utf-16-le", errors="surrogatepass")))

    def test_long_292_framework_forward_reverse_signs(self):
        self.assertEqual(len(LONG["comparisons"]), 292)
        for index, row in enumerate(LONG["comparisons"]):
            left, right = decode(row["left_utf16le_hex"]), decode(row["right_utf16le_hex"])
            self.assertEqual(self.backend.compare(left, right), row["CompareTo_sign"], f"long oracle row {index}")
            self.assertEqual(self.backend.compare(right, left), -row["CompareTo_sign"], f"long oracle row {index}")

    def test_all_long_76_inputs_generate_keys_and_reuse_cache(self):
        self.assertEqual(len(LONG["inputs_utf16le_hex"]), 76)
        for value in LONG["inputs_utf16le_hex"]:
            text = decode(value)
            key = self.backend.sort_key(text)
            self.assertIsInstance(key, bytes)
            self.assertEqual(self.backend.compare(text, text), 0)
            before = self.backend.cache_info().hits
            self.assertEqual(self.backend.sort_key(text), key)
            self.assertEqual(self.backend.cache_info().hits, before + 1)

    def test_new_three_framework_jamo_list_sort_observations(self):
        self.assertEqual(len(MAIN["sorts"]), 3)
        for row in MAIN["sorts"]:
            keys = [decode(MAIN["inputs_utf16le_hex"][i]) for i in row["input_indices"]]
            with patch("pyemuera.collation1824.compare_strings", side_effect=self.backend.compare):
                order = framework_list_order(keys, string=True)
            self.assertEqual([i + 1 for i in order], row["permutation"])
            self.assertEqual([keys[i].encode("utf-16-le", errors="surrogatepass").hex() for i in order], row["keys_utf16le_hex"])

    def test_long_76_framework_list_sort_observation(self):
        row = LONG["sorts"][0]
        keys = [decode(LONG["inputs_utf16le_hex"][i]) for i in row["input_indices"]]
        self.assertEqual((row["length"], row["capacity"]), (76, 128))
        with patch("pyemuera.collation1824.compare_strings", side_effect=self.backend.compare):
            order = framework_list_order(keys, string=True)
        self.assertEqual([i + 1 for i in order], row["permutation"])
        self.assertEqual([keys[i].encode("utf-16-le", errors="surrogatepass").hex() for i in order], row["keys_utf16le_hex"])

    def test_unreceived_jamo_lengths_repetitions_and_context_boundaries(self):
        # Properties of the reconstructed model, with no invented native sign.
        bodies = ("\ua961\ud7b3\ud7cf", "\u115f\ud7b4\u11f9", "\u1117\u1167\u11c5",
                  "\u1169\u1113\u11dd", "\u11ef\u11ef", "\u115f\u1160", "\u1113\u1114\u1115")
        values = [prefix + body * count + suffix for body in bodies for count in (1, 2, 5, 13)
                  for prefix, suffix in (("z", "q"), ("\0", "\0"), ("😀", "\udc01"), ("'", "-"))]
        for text in values:
            self.assertIsInstance(self.backend.sort_key(text), bytes)
            self.assertEqual(self.backend.compare(text, text), 0)
        randomizer = random.Random(4505213)
        for _ in range(1000):
            left, right = randomizer.choice(values), randomizer.choice(values)
            self.assertEqual(self.backend.compare(left, right), -self.backend.compare(right, left))

    def test_unreceived_jamo_mixed_context_transitivity(self):
        values = ["z" + chr(cp) + "\u1169\u11c6-q" for cp in (0x1113, 0x1121, 0x1145, 0xA96B)]
        values += ["z\u1103" + chr(cp) + "\u11c6-q" for cp in (0x119E, 0x11A6, 0xD7B8, 0xD7C6)]
        keys = {text: self.backend.sort_key(text) for text in values}
        ordered = sorted(values, key=keys.get)
        for left, middle, right in itertools.combinations(ordered, 3):
            self.assertLessEqual(self.backend.compare(left, middle), 0)
            self.assertLessEqual(self.backend.compare(middle, right), 0)
            self.assertLessEqual(self.backend.compare(left, right), 0)

    def test_new_jamo_and_long_keys_preserve_instance_cache_eviction(self):
        first, second = PortableNLSBackend(cache_size=2), PortableNLSBackend(cache_size=2)
        values = [decode(MAIN["inputs_utf16le_hex"][i]) for i in (680, 681, 682)]
        values += [decode(LONG["inputs_utf16le_hex"][70])]
        for value in values:
            first.sort_key(value)
        self.assertEqual(first.cache_info().currsize, 2)
        self.assertEqual(second.cache_info().currsize, 0)
        before = first.cache_info().hits
        first.sort_key(values[-1])
        self.assertEqual(first.cache_info().hits, before + 1)

    def test_independent_tuple_source_model_extra_10000_pair_signs(self):
        path = ROOT / "verification/r45/collation_verify/singleton_source_model.py"
        spec = importlib.util.spec_from_file_location("r45_extra_singleton_model", path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        values = model.review_inputs()
        expected = [model.logical_key(text) for text in values]
        self.assertEqual(len(values), 4299)
        # r49 measures this exact unchanged population in Framework. The old
        # tuple model is retained for provenance, but cannot overrule measured
        # direct comparison. Both original directions remain asserted.
        raw = (ROOT / 'tests/fixtures/r49/model-r45.json.gz').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '899ff0a24a369fbd9c483db4becac72ecdfaa7d07a1f20f6b468cc1b062a52e7')
        native = json.loads(gzip.decompress(raw))
        self.assertEqual(native['inputs_utf16le_hex'], [text.encode('utf-16-le', 'surrogatepass').hex() for text in values])
        self.assertEqual(len(native['pairs']), 20000)
        randomizer = random.Random(4504299)
        for index in range(10000):
            left, right = randomizer.randrange(len(values)), randomizer.randrange(len(values))
            row = native['pairs'][index * 2]
            reverse = native['pairs'][index * 2 + 1]
            self.assertEqual((row['left'], row['right']), (left, right))
            self.assertEqual((reverse['left'], reverse['right']), (right, left))
            sign = row['CompareTo_sign']
            self.assertEqual(sign, row['CompareInfo_None_sign'])
            self.assertEqual(sign, row['NLS_sign'])
            self.assertEqual(reverse['CompareTo_sign'], -sign)
            self.assertEqual(self.backend.compare(values[left], values[right]), sign)
            self.assertEqual(self.backend.compare(values[right], values[left]), -sign)

    def test_new_all_357_real_records_keep_identity_without_iteration(self):
        # The new algorithm may read newly required nearest V/T indices. It
        # must continue indexing opaque records without copying or mutation.
        for cp, row in r44_jamo_contract.SOURCE_ROWS["jamo"].items():
            unit = int(cp, 16)
            units = {"L": (unit, 0x116B, 0x11CE), "V": (0x1116, unit, 0x11CE),
                     "T": (0x1116, 0x116B, unit)}[row["class"]]
            observed = r44_jamo_contract.observe(collation_jamo, units)
            self.assertNotIn("exception_type", observed["outcome"], cp)
            self.assertEqual(observed["record_iteration_attempts"], 0)
            self.assertTrue(observed["record_identities_preserved"])

    def test_new_required_metadata_reads_propagate_injected_failures(self):
        # Additional nearest V/T reads are necessary for the new composition
        # rule. Validate failure at every observed operation without requiring
        # r44's superseded record-read sequence for a different algorithm.
        cases = ((0x1113,), (0x1100,), (0x1161,), (0x11AB,), (0x115F,),
                 (0x1113, 0x1162, 0x11AB), (0x1103, 0x119E, 0x11AB),
                 (0x115F, 0x1162, 0x11AB), (0xA97B, 0xD7B4, 0xD7D5))
        for units in cases:
            normal = r44_jamo_contract.observe(collation_jamo, units, flag_spy=True)
            self.assertNotIn("exception_type", normal["outcome"])
            for operation in range(1, len(normal["events"]) + 1):
                failed = r44_jamo_contract.observe(collation_jamo, units, failure_at=operation, flag_spy=True)
                self.assertEqual(failed["outcome"].get("exception_type"), "r44_jamo_contract.InjectedFailure")
                self.assertEqual(failed["events"], normal["events"][:operation])
                self.assertEqual(failed["record_iteration_attempts"], 0)
                self.assertTrue(failed["record_identities_preserved"])


class CollationArrayMSortR45(Harness):
    def test_long_76_real_vm_arraymsort_all_arrays_result_and_rng(self):
        row = LONG["sorts"][0]
        keys = [decode(LONG["inputs_utf16le_hex"][i]) for i in row["input_indices"]]
        vm = self.make(headers="#DIMS KEYS,76\n#DIM ROWS,76\n#DIM ASSOC,76,2")
        for index, key in enumerate(keys):
            vm.set(f"KEYS:{index}", key)
            vm.set(f"ROWS:{index}", index + 1)
            vm.set(f"ASSOC:{index}:0", index + 10001)
            vm.set(f"ASSOC:{index}:1", -(index + 1))
        rng = vm.rng.getstate()
        self.assertEqual(vm.eval("ARRAYMSORT(KEYS,ROWS,ASSOC)"), 1)
        self.assertEqual([vm.get(f"ROWS:{i}") for i in range(76)], row["permutation"])
        self.assertEqual([vm.get(f"KEYS:{i}").encode("utf-16-le", errors="surrogatepass").hex() for i in range(76)], row["keys_utf16le_hex"])
        self.assertEqual([[vm.get(f"ASSOC:{i}:0"), vm.get(f"ASSOC:{i}:1")] for i in range(76)],
                         [[10000 + index, -index] for index in row["permutation"]])
        self.assertEqual(vm.rng.getstate(), rng)
