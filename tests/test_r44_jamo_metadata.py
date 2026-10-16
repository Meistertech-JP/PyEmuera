"""Preserve r43 Jamo record access, opaque storage and failure behavior."""
import ast
import hashlib
import json
import unittest

from pyemuera import collation_jamo as candidate
from pyemuera.collation_portable import PortableNLSBackend
import r44_jamo_contract as contract
import r44_collation_boundaries as boundaries
import r43_source_collation_model as source_model
import r45_frozen_jamo_contract as historical


def _combining_jamo(text):
    return any(
        0x1100 <= ord(char) <= 0x11FF
        or 0xA960 <= ord(char) <= 0xA97C
        or 0xD7B0 <= ord(char) <= 0xD7FF
        for char in text
    )


class JamoMetadataR44(unittest.TestCase):
    def test_named_indices_match_the_actual_published_record(self):
        expected = {"OLD_FLAG_INDEX": 0, "NEAREST_LEADING_INDEX": 1,
                    "NEAREST_VOWEL_INDEX": 2, "NEAREST_TRAILING_INDEX": 3,
                    "EXTRA_WEIGHT_INDEX": 4}
        self.assertEqual(len(contract.RECORDS), 357)
        backend = PortableNLSBackend(cache_size=0)
        for name, index in expected.items():
            self.assertIs(type(getattr(candidate, name)), int)
            self.assertEqual(getattr(candidate, name), index)
        for cp, record in backend._jamo.items():
            self.assertIs(type(record), tuple)
            self.assertEqual(record, contract.RECORDS[cp])
            self.assertEqual(len(record), 5)

    def test_r43_record_reads_truth_tests_and_failures_are_unchanged(self):
        # Historical r44 pure named-index refactor, pinned independently of
        # r45's intentional semantic changes. Current record identity and
        # failure propagation are covered by new R45 tests and native oracles.
        result = contract.compare_contracts(historical.historical_r44_module())
        self.assertEqual(result["cases"], 3691)
        self.assertEqual(result["matching_cases"], result["cases"])
        self.assertEqual(result["mismatches"], [])

    def test_unused_nearest_vowel_and_trailing_fields_remain_opaque(self):
        class Record:
            def __init__(self):
                self.reads = []

            def __getitem__(self, index):
                self.reads.append(index)
                if index in (2, 3):
                    raise AssertionError("Unused field must remain unread")
                return {0: 1, 1: 2, 4: 7}[index]

            def __iter__(self):
                raise AssertionError("Opaque record must not be unpacked")

        original = Record()
        current = Record()
        old = contract.baseline_module().interpret_jamo((0x1113,), 0, {0x1113: original}, contract.WEIGHTS.__getitem__)
        new = candidate.interpret_jamo((0x1113,), 0, {0x1113: current}, contract.WEIGHTS.__getitem__)
        self.assertEqual((new.base, new.context, new.consumed), (old.base, old.context, old.consumed))
        self.assertEqual(current.reads, original.reads)
        self.assertEqual(current.reads, [0, 1, 0, 4])

    def test_short_leading_record_fails_at_the_same_read(self):
        old = contract.observe(contract.baseline_module(), (0x1113,), overrides={0x1113: (1,)})
        current = contract.observe(candidate, (0x1113,), overrides={0x1113: (1,)})
        self.assertEqual(current, old)
        self.assertEqual(current["outcome"]["exception_type"], "builtins.IndexError")
        self.assertEqual(current["outcome"]["exception_message"], "tuple index out of range")
        self.assertEqual(current["events"][-1], ["record_read", 0x1113, "int", 1])

    def test_record_objects_are_not_copied_or_mutated(self):
        for units in ((0x1113,), (0x1112, 0x119E, 0x11AB), (0x1100, 0x1161),
                      (0x115F, 0x1160), (0xD7B0,), (0xD7DD,)):
            result = contract.observe(candidate, units)
            self.assertNotIn("exception_type", result["outcome"])
            self.assertEqual(result["record_iteration_attempts"], 0)
            self.assertTrue(result["record_identities_preserved"])

    def test_all_published_classes_match_the_record_annotations(self):
        mapping = {"L": candidate.JamoClass.LEADING, "V": candidate.JamoClass.VOWEL,
                   "T": candidate.JamoClass.TRAILING}
        for cp, source in contract.SOURCE_ROWS["jamo"].items():
            self.assertEqual(candidate.jamo_class(int(cp, 16)), mapping[source["class"]])

    def test_named_index_rewrite_keeps_the_original_function_ast(self):
        # Replace only the new constant names by their pinned integer values,
        # then compare function ASTs to the immutable r43 source. Added module
        # assignments are structural changes and are not called FORMAT.
        source = contract.FIXTURE / "collation_jamo_r43.py.txt"
        current = historical.SOURCE
        old_tree = ast.parse(source.read_text())
        tree = ast.parse(current.read_text())
        indices = {"OLD_FLAG_INDEX": 0, "NEAREST_LEADING_INDEX": 1,
                   "NEAREST_VOWEL_INDEX": 2, "NEAREST_TRAILING_INDEX": 3,
                   "EXTRA_WEIGHT_INDEX": 4}

        class ResolveIndex(ast.NodeTransformer):
            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Load) and node.id in indices:
                    return ast.copy_location(ast.Constant(value=indices[node.id]), node)
                return node

        normalized = ResolveIndex().visit(tree)
        old_functions = {node.name: ast.dump(node, include_attributes=False) for node in old_tree.body
                         if isinstance(node, ast.FunctionDef)}
        functions = {node.name: ast.dump(node, include_attributes=False) for node in normalized.body
                     if isinstance(node, ast.FunctionDef)}
        self.assertEqual(functions, old_functions)

    def test_long_boundaries_keep_the_existing_profile_model(self):
        backend = PortableNLSBackend()
        inputs, pairs, _ = boundaries.inputs_and_pairs()
        self.assertEqual((len(inputs), len(pairs)), (76, 292))
        expected = {value: source_model.sort_key(value) for value in inputs}
        for value, key in expected.items():
            actual = backend.sort_key(value)
            if _combining_jamo(value):
                # r48 replaces reconstructed Jamo weights with measured Windows
                # Unicode weights. This population's order is checked below.
                self.assertTrue(actual)
            else:
                self.assertEqual(actual, key)
        for left, right in pairs:
            a, b = inputs[left], inputs[right]
            sign = (expected[a] > expected[b]) - (expected[a] < expected[b])
            self.assertEqual(backend.compare(a, b), sign)
        # Received r44 Windows Framework boundary oracle row 70 observes
        # +1 for exactly these original UTF-16 inputs. It refutes the old
        # LOCAL_MODEL 16-bit wrap; its original test source is archived.
        self.assertGreater(backend.compare("-" + "a" * 8192, "a" * 8192 + "-"), 0)

    def test_new_windows_boundary_probe_preserves_utf16_and_plan_hashes(self):
        manifest = json.loads((boundaries.DIRECTORY / "manifest.json").read_text())
        for row in manifest["files"]:
            raw = (boundaries.DIRECTORY / row["path"]).read_bytes()
            self.assertEqual(len(raw), row["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])
        expected, pairs, _ = boundaries.inputs_and_pairs()
        actual = [bytes.fromhex(value).decode("utf-16-le", errors="surrogatepass")
                  for value in (boundaries.DIRECTORY / "inputs_utf16hex.txt").read_text().splitlines()]
        self.assertEqual(actual, expected)
        self.assertEqual(len(pairs), manifest["pairs"])
        self.assertIsNone(manifest["expected_native_results"])
