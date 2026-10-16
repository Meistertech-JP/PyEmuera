"""Distribution/report drift and duplicate modules, not duplicate helper text."""
from pathlib import Path
import tempfile,unittest,uuid
from tools.test_inventory import discover,snapshot,validate_report

BODY='import unittest\nclass Example(unittest.TestCase):\n    def test_value(self):pass\n'

class TestInventory(unittest.TestCase):
    def fixture(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);(root/'tests').mkdir()
        path=root/'tests'/('test_inventory_'+uuid.uuid4().hex+'.py')
        path.write_text(BODY)
        return root,path
    def report(self,root):
        inventory=snapshot(root,discover(root))
        return {'tests':inventory['tests'],'test_inventory':inventory,
                'executed_test_ids':inventory['test_ids']}
    def test_identical_complete_test_modules_rejected(self):
        root,path=self.fixture();path.with_name('test_duplicate_'+uuid.uuid4().hex+'.py').write_text(BODY)
        with self.assertRaisesRegex(ValueError,'Duplicate complete test modules'):self.report(root)
    def test_identical_helper_text_with_distinct_tests_allowed(self):
        root,path=self.fixture();path.with_name('test_distinct_'+uuid.uuid4().hex+'.py').write_text(BODY.replace('test_value','test_other'))
        self.assertEqual(self.report(root)['tests'],2)
    def test_unchanged_collection_and_execution_accepted(self):
        root,path=self.fixture();report=self.report(root)
        self.assertEqual(validate_report(root,report),report['test_inventory'])
    def test_source_changed_after_run_rejected(self):
        root,path=self.fixture();report=self.report(root);path.write_text(BODY+'\n# changed after test\n')
        with self.assertRaisesRegex(ValueError,'collection differs'):validate_report(root,report)
    def test_extra_test_file_after_run_rejected(self):
        root,path=self.fixture();report=self.report(root)
        path.with_name('test_added_'+uuid.uuid4().hex+'.py').write_text(BODY.replace('test_value','test_added'))
        with self.assertRaisesRegex(ValueError,'collection differs'):validate_report(root,report)
    def test_missed_execution_and_wrong_count_rejected(self):
        root,path=self.fixture();report=self.report(root);report['executed_test_ids']=[]
        with self.assertRaisesRegex(ValueError,'Executed tests differ'):validate_report(root,report)
        report=self.report(root);report['tests']=2
        with self.assertRaisesRegex(ValueError,'Reported count differs'):validate_report(root,report)
