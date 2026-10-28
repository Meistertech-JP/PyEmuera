"""Small regression checks for the bounded public pair inventory."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('post_b1_pairs_inventory', ROOT/'tools/post_b1_pairs_inventory.py')
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class PublicArraySupersets(unittest.TestCase):
    def test_raw_utf16_pairs_include_self_and_reverse_only_once(self):
        inv = inventory.Inventory()
        values = [inventory.enc('a'), inventory.enc('\ud800'), inventory.enc('a')]
        inv.array_superset(values)
        self.assertEqual(inv.keys, {inventory.pair(values[0], values[0]),
                                    inventory.pair(values[0], values[1]),
                                    inventory.pair(values[1], values[1])})
        self.assertEqual(inv.counts['conservative_array_pairs'], 6)

    def test_sort_plan_validates_all_rows_before_adding(self):
        inputs, plan = Path('inputs.txt'), Path('sorts.tsv')
        inv = inventory.Inventory()
        with patch.object(Path, 'read_text', side_effect=['6100\n6200\n', 'good\t0,1\nbad\t0,2\n']):
            with self.assertRaises(ValueError):
                inv.sort_plan_superset(plan, inputs)
        self.assertFalse(inv.keys)
        with patch.object(Path, 'read_text', side_effect=['6100\n6200\n', 'good\t0,1\n']):
            inv.sort_plan_superset(plan, inputs)
        self.assertEqual(inv.keys, {('6100','6100'), ('6100','6200'), ('6200','6200')})

    def test_native_six_validates_mapping_before_adding(self):
        case = {'input_utf16le_hex':['6100','6200'], 'input_values':['a','b'], 'count':2}
        obj = {'schema':'r50-arraysort-received-native-six-v1', 'cases':[case.copy() for _ in range(6)]}
        inv = inventory.Inventory()
        inv.native_six_superset(obj)
        self.assertIn(('6100','6200'), inv.keys)
        obj['cases'][-1] = dict(case, input_values=['a','x'])
        invalid = inventory.Inventory()
        with self.assertRaises(ValueError):
            invalid.native_six_superset(obj)
        self.assertFalse(invalid.keys)

    def test_native_plan_keeps_sentinels_and_rejects_mixed(self):
        inv = inventory.Inventory()
        inv.native_plan_superset({'cases':[{'input':['sentinel','a']}, {'input':[1,2]}]})
        self.assertIn(inventory.pair(inventory.enc('sentinel'), inventory.enc('a')), inv.keys)
        invalid = inventory.Inventory()
        with self.assertRaises(ValueError):
            invalid.native_plan_superset({'cases':[{'input':['a', 1]}]})
        self.assertFalse(invalid.keys)

    def test_reviewed_test_pair_and_changed_source(self):
        inv = inventory.Inventory()
        inv.reviewed_test_pair(ROOT/'tests/test_r47_compatibility.py')
        self.assertIn(inventory.pair(inventory.enc('\u115f\u11a8'), inventory.enc('\u11a8')), inv.keys)
        with patch.object(Path, 'read_text', return_value='def test_placeholder_shape_does_not_invent_boundary_order():\n    backend.compare("a", "b")\n'):
            with self.assertRaises(ValueError):
                inventory.Inventory().reviewed_test_pair(Path('test.py'))

    def test_holdout_paths_are_pruned_before_opening(self):
        dirs = ['sealed_holdout']
        with patch.object(inventory.os, 'walk', return_value=iter([('root', dirs, ['public.txt', 'new_holdout.json'])])):
            with patch.object(Path, 'is_symlink', return_value=False):
                self.assertEqual([p.name for p in inventory.files(Path('root'))], ['public.txt'])
        self.assertEqual(dirs, [])


if __name__ == '__main__':
    unittest.main()
