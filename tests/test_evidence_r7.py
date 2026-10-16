import unittest, json, tempfile, pathlib, io
from tools.oracle_warning_r7 import warning_records,compare_warnings,fixture_sources
from pyemuera.program import Program
from pyemuera.data import GameData
from pyemuera.runtime import VM
from pyemuera.console import Console
from pyemuera.errors import EraError,Location
ROOT=pathlib.Path(__file__).resolve().parents[1]
class OracleWarningsR7(unittest.TestCase):
    def compare(self,a,b,**kwargs):
        return compare_warnings(a,b,{('Oracle.ERB',2):'POWER OR_A,2,3,OR_BASE()',('A.ERB',1):'@L'},origin_reviewed=True,**kwargs)
    def test_none(self):self.assertEqual(self.compare('ORACLE|end\n','ORACLE|end\n')['warning_status'],'verified_equal')
    def test_located(self):self.assertEqual(self.compare('警告Lv1:A.ERB:1行目:本文\n@L\n','警告Lv1:A.ERB:1行目:本文\n@L\n')['warning_status'],'verified_equal')
    def test_positionless(self):
        r=warning_records('警告Lv1:本文\n')[0];self.assertIsNone(r['file']);self.assertIsNone(r['line']);self.assertEqual(r['raw_line'],'警告Lv1:本文\n');self.assertIsNone(r['diagnostic_phase'])
    def test_one_vs_two(self):self.assertEqual(self.compare('警告Lv1:本文\n','警告Lv1:本文\n'*2)['warning_status'],'mismatch_open')
    def test_repeat_count(self):self.assertEqual(warning_records('警告Lv1:x\n'*2)[1]['occurrence_count'],2)
    def test_order(self):self.assertIn('warning_order',self.compare('警告Lv1:x\n警告Lv1:y\n','警告Lv1:y\n警告Lv1:x\n')['warning_differences'])
    def test_level(self):self.assertFalse(self.compare('警告Lv1:x\n','警告Lv2:x\n')['logical_warning_records_equal'])
    def test_body_with_line_like_colon(self):
        r=warning_records('警告Lv1:A.ERB:1行目:本文:9行目:続き\n')[0];self.assertEqual((r['file'],r['line'],r['message']),('A.ERB',1,'本文:9行目:続き'))
    def test_file(self):self.assertFalse(self.compare('警告Lv1:A.ERB:1行目:x\n@L\n','警告Lv1:B.ERB:1行目:x\n@L\n')['logical_warning_records_equal'])
    def test_line(self):self.assertFalse(self.compare('警告Lv1:A.ERB:1行目:x\n@L\n','警告Lv1:A.ERB:2行目:x\n@L\n')['logical_warning_records_equal'])
    def test_original(self):self.assertFalse(self.compare('警告Lv1:A.ERB:1行目:x\n@L\n','警告Lv1:A.ERB:1行目:x\n@R\n')['logical_warning_records_equal'])
    def test_unicode_not_normalized(self):self.assertFalse(self.compare('警告Lv1:é\n','警告Lv1:é\n')['logical_warning_records_equal'])
    def test_unicode_line_separator_preserved(self):self.assertEqual(warning_records('警告Lv1:x y\n')[0]['message'],'x y')
    def test_spaces_preserved(self):self.assertFalse(self.compare('警告Lv1: x \n','警告Lv1:x\n')['logical_warning_records_equal'])
    def test_crlf_retained(self):self.assertEqual(warning_records('警告Lv1:x\r\n')[0]['raw_line'],'警告Lv1:x\r\n')
    def test_print_like_pending(self):self.assertEqual(self.compare('警告Lv1:x\n','警告Lv1:x\n',warning_like_user_text=True)['warning_status'],'warning_observation_pending')
    def test_unknown_origin_pending(self):self.assertEqual(compare_warnings('警告Lv1:x\n','警告Lv1:x\n')['warning_status'],'warning_observation_pending')
    def test_structured_origin_disagrees(self):self.assertEqual(self.compare('警告Lv1:x\n','警告Lv1:x\n',structured_py_diagnostics=[])['warning_status'],'warning_observation_pending')
    def test_markers_same_warning_diff(self):self.assertEqual(self.compare('ORACLE|end\n','警告Lv1:x\nORACLE|end\n')['warning_status'],'mismatch_open')
class Run06ReassessmentR7(unittest.TestCase):
    def rows(self):return json.loads((ROOT/'verification/run06_warning_reassessment_r7.json').read_text())
    def test_counts(self):self.assertEqual(self.rows()['counts'],{'verified_equal':32,'mismatch_open':2,'error_observation_pending':18,'capture_incomplete':3})
    def test_false_verified(self):
        r=next(x for x in self.rows()['cases'] if x['case_id']=='power-extra-warning');self.assertEqual((r['old_kit_status'],r['status']),('verified_equal','mismatch_open'));self.assertEqual((len(r['reference_warnings']),len(r['py_warnings'])),(1,2))
    def test_b_still_mismatch(self):self.assertEqual(next(x for x in self.rows()['cases'] if x['case_id']=='run03-b-recheck')['status'],'mismatch_open')
    def test_no_raw_changes(self):self.assertFalse(self.rows()['raw_files_changed'])
class FixtureR7(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.g=pathlib.Path(self.tmp.name);(self.g/'ERB').mkdir();(self.g/'CSV').mkdir();self.out=io.StringIO()
    def vm(self,src,mode='NO',config=''):
        (self.g/'ERB/Oracle.ERB').write_text(src,encoding='utf-8-sig');(self.g/'ERB/Oracle.ERH').write_text('#DIM OR_A\n#DIM OR_TRACE\n#DIMS OR_STR\n#DIM CONST OR_CONST=3\n',encoding='utf-8-sig');(self.g/'emuera.config').write_text('ロード時に引数を解析する:'+mode+'\n'+config,encoding='utf-8-sig');return VM(Program(self.g),GameData(self.g),Console([],self.out,no_wait=True),seed=42)
class PowerWarningR7(FixtureR7):
    SOURCE='@SYSTEM_TITLE\nPOWER OR_A,2,3,OR_EXTRA()\nQUIT\n@OR_EXTRA\n#FUNCTION\nOR_TRACE+=1\nRETURNF 2\n'
    def test_yes_once_and_location(self):
        vm=self.vm(self.SOURCE,'YES');vm.run();r=warning_records(self.out.getvalue());self.assertEqual(len(r),1);self.assertEqual((r[0]['severity'],r[0]['file'],r[0]['line']),(1,'Oracle.ERB',2));self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(8,0));self.assertEqual(len(vm.emitted_diagnostics),1)
    def test_no_none(self):
        vm=self.vm(self.SOURCE);vm.run();self.assertEqual(warning_records(self.out.getvalue()),[]);self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(8,0))
    def test_invalid_extra_no_side_effect(self):
        vm=self.vm(self.SOURCE.replace('OR_EXTRA()','OR_UNDEFINED()'),'YES');self.assertEqual([d.severity for d in vm.program.argument_diagnostics],[2]);self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_extra_constant_restructure_warn_before_error(self):
        vm=self.vm(self.SOURCE.replace('OR_EXTRA()','1/0'),'YES');self.assertEqual([d.severity for d in vm.program.argument_diagnostics],[1,2]);self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_bad_type_message_category_location(self):
        vm=self.vm('@SYSTEM_TITLE\nPOWER OR_STR,2,3\nQUIT\n');
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual((e.exception.code,e.exception.location.line,e.exception.message),('E_TYPE',2,'POWER命令:第1引数の型が正しくありません'));self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_readonly_message_category(self):
        vm=self.vm('@SYSTEM_TITLE\nPOWER OR_CONST,2,3\nQUIT\n')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.code,'E_REFERENCE');self.assertIn('変数以外',e.exception.message)
class FunctionCollisionR7(FixtureR7):
    def source(self,names):return '@SYSTEM_TITLE\nQUIT\n'+''.join('@'+n+'\n#FUNCTION\nRETURNF 1\n' for n in names)
    def test_general_registry_and_order(self):
        vm=self.vm(self.source(['L','R','Z','TARGET','BASE','RAND','OR_OTHER']));vm.run();rows=vm.emitted_diagnostics;self.assertEqual([r['reference_message'] for r in rows],['関数名'+n+'はEmueraの変数で使われています' for n in ['L','R','Z','TARGET','BASE']]+['関数名RANDはEmueraの式中関数を上書きします']);self.assertEqual([r['line'] for r in rows],[3,6,9,12,15,18]);self.assertEqual(len(warning_records(self.out.getvalue())),6)
    def test_case(self):
        vm=self.vm(self.source(['l']));vm.run();self.assertEqual(len(vm.emitted_diagnostics),1)
    def test_config_no(self):
        vm=self.vm(self.source(['L']),config='システム関数が上書きされたとき警告を表示する:NO\n');vm.run();self.assertEqual(vm.emitted_diagnostics,[])
    def test_user_variable_not_builtin(self):
        vm=self.vm(self.source(['OR_A']));vm.run();self.assertEqual(vm.emitted_diagnostics,[])
    def test_merged_order(self):
        vm=self.vm('@SYSTEM_TITLE\nPOWER OR_A,2,3,1\nQUIT\n@L\n#FUNCTION\nRETURNF 8\n','YES');vm.run();self.assertEqual([d['display_order'] for d in vm.emitted_diagnostics],[0,1]);self.assertEqual([d['category'] for d in vm.emitted_diagnostics],['W_FUNCTION_VARIABLE_COLLISION','E_ARGUMENT'])
    def test_warning_does_not_ban_call(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=L()\nQUIT\n@L\n#FUNCTION\nRETURNF 8\n');vm.run();self.assertEqual(vm.eval('OR_A'),8);self.assertEqual(len(vm.emitted_diagnostics),1)
class DiagnosticFormattingR7(unittest.TestCase):
    def test_division_keeps_exception_fields(self):
        e=EraError('Division by zero',Location('ERB/Oracle.ERB',7),'E_ARITH');e.era_stack=[{'function':'OR_OUTER'}];d=e.as_dict();self.assertEqual(d['message'],'Division by zero');self.assertEqual(d['diagnostic_message'],'0による除算が行なわれました');self.assertEqual((d['line'],d['stack']),(7,e.era_stack));self.assertIn(d['diagnostic_message'],str(e))
    def test_string_numeric_diagnostic(self):self.assertEqual(EraError('Integer required, got str',code='E_TYPE').as_dict()['diagnostic_message'],'式の結果が数値ではありません')
    def test_unknown_not_translated(self):self.assertEqual(EraError('x',code='E_ARITH').as_dict()['diagnostic_message'],'x')
class ForceInventoryR7(unittest.TestCase):
    def test_source_derived_commands(self):
        d=json.loads((ROOT/'verification/force_set_arg_contracts_r7.json').read_text());self.assertTrue({'CALL','CALLF','GOTO','IF','SIF','SELECTCASE','CASE','LOOP'}<=set(d['forced_commands']));self.assertNotIn('POWER',d['forced_commands']);self.assertFalse(d['runtime_values_executed_at_load']);self.assertEqual(d['status'],'source_verified_runtime_pending')
