import unittest,tempfile,pathlib,json,io
from unittest.mock import patch
from pyemuera import cli
from pyemuera.journal import RunJournal
class PrimaryErrorReportingR13(unittest.TestCase):
 def test_report_failure_is_not_retried(self):
  with tempfile.TemporaryDirectory()as td:
   root=pathlib.Path(td);(root/'ERB').mkdir();(root/'CSV').mkdir();(root/'ERB/Oracle.ERB').write_text('@SYSTEM_TITLE\nPRINTFORM {1 / 0}\nQUIT\n');out=root/'session.json';err=root/'error.json'
   with patch.object(RunJournal,'report',side_effect=ValueError('capture \ud800'))as report,patch('sys.stdout',io.StringIO()),patch('sys.stderr',io.StringIO()):
    code=cli.main([str(root),'--seed','42','--no-wait','--session-report',str(out),'--error-report',str(err)])
   self.assertEqual(code,1);self.assertEqual(report.call_count,1)
   session=json.loads(out.read_text());primary=json.loads(err.read_text())['error'];self.assertEqual(session['error'],primary);self.assertFalse(session['capture_complete']);self.assertEqual(session['secondary_capture_failure']['type'],'ValueError');self.assertEqual(session['secondary_capture_failure']['message'],'capture \ud800')
 def test_report_failure_preserves_successful_calculation_scope(self):
  with tempfile.TemporaryDirectory()as td:
   root=pathlib.Path(td);(root/'ERB').mkdir();(root/'CSV').mkdir();(root/'ERB/Oracle.ERB').write_text('@SYSTEM_TITLE\nPRINTL ORACLE|end\nQUIT\n');out=root/'session.json'
   physical=io.StringIO()
   with patch.object(RunJournal,'report',side_effect=ValueError('report failure'))as report,patch('sys.stdout',physical),patch('sys.stderr',io.StringIO()):code=cli.main([str(root),'--no-wait','--session-report',str(out)])
   self.assertEqual(code,1);self.assertEqual(report.call_count,1);self.assertIn('ORACLE|end',physical.getvalue());self.assertIsNone(json.loads(out.read_text())['error']);self.assertFalse(json.loads(out.read_text())['capture_complete'])
