import importlib.util,unittest
from pathlib import Path
from pyemuera import __version__
from pyemuera.registry import COMMAND_SPECS,FUNCTION_SPECS,fingerprint
p=Path(__file__).resolve().parents[1]/'tools/build_status.py'
spec=importlib.util.spec_from_file_location('status_builder',p);builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

class CurrentStatus(unittest.TestCase):
    def test_recount_preserves_rows(self):
        rows=[{'status':'not_observed','id':1},{'status':'verified_equal','id':2},{'status':'not_observed','id':3}]
        self.assertEqual(builder.recount(rows),{'not_observed':2,'verified_equal':1})
        self.assertEqual(rows[0],{'status':'not_observed','id':1})
    def test_current_inventory_comes_from_registry_and_report(self):
        j=builder.inventory({'engine_version':__version__,'tests':17})
        self.assertEqual(j['unit_tests'],17);self.assertEqual(j['unittest_count'],17)
        self.assertEqual(j['definition_counts']['commands'],len(COMMAND_SPECS))
        self.assertEqual(len(j['expression_functions']),len(FUNCTION_SPECS));self.assertEqual(j['language_specs_sha256'],fingerprint())
        self.assertFalse(j['full_compatibility'])
    def test_old_version_report_rejected(self):
        with self.assertRaises(ValueError):builder.inventory({'engine_version':'r17','tests':1554})
    def test_failed_or_incomplete_report_rejected(self):
        for key in ['failures','errors','skipped']:
            with self.subTest(key=key),self.assertRaises(ValueError):builder.inventory({'engine_version':__version__,'tests':17,key:1})
