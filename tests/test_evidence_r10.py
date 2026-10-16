import unittest,json,math,struct
from pathlib import Path
from test_evidence_r7 import FixtureR7
from pyemuera.errors import EraError
from pyemuera.registry import FUNCTION_SPECS,COMMAND_SPECS
from pyemuera.numeric_instructions import power_value
from tools.oracle_outcome_r10 import outcome_comparison
from tools.oracle_status_r10 import error_axes,error_stack_axes

class CaseFlowR10(FixtureR7):
    def source(self,cases,select='1'):
        return '@SYSTEM_TITLE\nPRINTL ORACLE|prior\nSELECTCASE '+select+'\n'+cases+'\nENDSELECT\nPRINTL ORACLE|end\nQUIT\n'
    def test_archived_case_search_skips_error(self):
        vm=self.vm(self.source('CASE 1,,2'));vm.run();self.assertIn('ORACLE|end',self.out.getvalue());self.assertEqual(len(vm.emitted_diagnostics),1);self.assertEqual((vm.emitted_diagnostics[0]['severity'],vm.emitted_diagnostics[0]['line']),(2,4))
    def test_archived_else(self):
        vm=self.vm(self.source('CASE 1,,2\nPRINTL bad\nCASEELSE\nPRINTL else'));vm.run();self.assertIn('else',self.out.getvalue());self.assertNotIn('\nbad\n',self.out.getvalue())
    def test_archived_fallthrough(self):
        vm=self.vm(self.source('CASE 1\nPRINTL first\nCASE 2,,3\nPRINTL second'))
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual((e.exception.code,e.exception.location.line,e.exception.message),('E_SYNTAX',6,'CASEの引数は省略できません'));self.assertEqual(e.exception.era_stack[-1]['line'],6);self.assertIn('first',self.out.getvalue());self.assertNotIn('ORACLE|end',self.out.getvalue())
    def test_later_valid_candidate(self):
        vm=self.vm(self.source('CASE 1,,2\nPRINTL bad\nCASE 1,3\nPRINTL good'));vm.run();self.assertIn('good',self.out.getvalue());self.assertIn('ORACLE|end',self.out.getvalue())
    def test_force_set_arg_no_yes(self):
        for mode in ('NO','YES'):
            vm=self.vm(self.source('CASE 1,,2'),mode);vm.run();self.assertEqual(len(vm.emitted_diagnostics),1)
    def test_normal_multi(self):
        vm=self.vm(self.source('CASE 2,1,3\nOR_A=9'));vm.run();self.assertEqual(vm.eval('OR_A'),9)
    def test_normal_no_else(self):
        vm=self.vm(self.source('CASE 2\nOR_A=9'));vm.run();self.assertEqual(vm.eval('OR_A'),0);self.assertIn('ORACLE|end',self.out.getvalue())
    def test_nested_searches(self):
        vm=self.vm(self.source('CASE 1\nSELECTCASE 2\nCASE 1,,2\nCASE 2\nOR_A=9\nENDSELECT'));vm.run();self.assertEqual(vm.eval('OR_A'),9)
    def test_normal_next_body_not_executed(self):
        vm=self.vm(self.source('CASE 1\nOR_A=9\nCASE 2\nOR_A=3'));vm.run();self.assertEqual(vm.eval('OR_A'),9)
    def test_error_first_multiple_then_else(self):
        vm=self.vm(self.source('CASE 1,,2\nCASE 2,,3\nCASEELSE\nOR_A=8'));vm.run();self.assertEqual(vm.eval('OR_A'),8);self.assertEqual(len(vm.emitted_diagnostics),2)

class RegistryR10(FixtureR7):
    def test_declarative_distinction(self):
        for n in ('STRLEN','STRLENU'):self.assertIn(n,COMMAND_SPECS);self.assertNotIn(n,FUNCTION_SPECS)
        for n in ('STRLENS','STRLENSU'):self.assertIn(n,FUNCTION_SPECS)
    def test_strlen_as_expression_rejected(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML {STRLEN("abc")}\nQUIT\n')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.message,'命令名"STRLEN"が関数のように使われています')
    def test_strlenu_as_expression_source_pending(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\n')
        with self.assertRaises(EraError) as e:vm.eval('STRLENU("abc")')
        self.assertEqual(e.exception.message,'命令名"STRLENU"が関数のように使われています')
    def test_valid_registered_methods(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\n');self.assertEqual(vm.eval('STRLENS("abc")'),3);self.assertEqual(vm.eval('STRLENSU("日本")'),2)
    def test_strlen_command_preserved(self):
        vm=self.vm('@SYSTEM_TITLE\nSTRLEN abc\nOR_A=RESULT\nQUIT\n');vm.run();self.assertEqual(vm.eval('OR_A'),3)
    def test_user_command_name_method(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=STRLEN(1)\nQUIT\n@STRLEN(ARG)\n#FUNCTION\nRETURNF 9\n');vm.run();self.assertEqual(vm.eval('OR_A'),9)
    def test_user_functions_collision(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_STR\'=STRLENS(1)\nQUIT\n@STRLENS(ARG)\n#FUNCTIONS\nRETURNF "user"\n');vm.run();self.assertEqual(vm.eval('OR_STR'),'user')
    def test_forward_string_signature_valid(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=ABS("abc")\nQUIT\n@ABS(ARGS)\n#FUNCTION\nRETURNF STRLENS(ARGS)\n','YES');vm.run();self.assertEqual(vm.eval('OR_A'),3)
    def test_type_error(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\n')
        with self.assertRaises(EraError) as e:vm.eval('STRLENS(1)')
        self.assertEqual(e.exception.code,'E_TYPE')
    def test_selected_user_error_no_fallback(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=STRLENS("abc")\nQUIT\n@STRLENS(ARGS)\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1/0\n')
        with self.assertRaises(EraError):vm.run()
        self.assertEqual(vm.eval('OR_TRACE'),1)

class FormDiagnosticsR10(FixtureR7):
    def bad(self,form,definition='',mode='NO'):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML '+form+'\nQUIT\n'+definition,mode)
        with self.assertRaises(EraError) as e:vm.run()
        return vm,e.exception
    def test_archived_curly_message(self):
        _,e=self.bad('{ABS(1)}','@ABS(ARG)\n#FUNCTIONS\nRETURNF "user"\n');self.assertEqual(e.message,'{}の中の式が数式ではありません');self.assertEqual(e.location.line,2)
    def test_percent_message_source(self):
        _,e=self.bad('%1%');self.assertEqual(e.message,'%%の中の式が文字列式ではありません')
    def test_curly_side_effect_not_executed(self):
        vm,e=self.bad('{SIDE()}','@SIDE\n#FUNCTIONS\nOR_TRACE+=1\nRETURNF "text"\n');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_percent_side_effect_not_executed(self):
        vm,e=self.bad('%SIDE()%','@SIDE\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1\n');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_whole_form_checked_before_first_effect(self):
        vm,e=self.bad('{SIDE()}{"bad"}','@SIDE\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1\n');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_yes_error_line_still_reached(self):
        vm,e=self.bad('{"bad"}',mode='YES');self.assertEqual(e.message,'{}の中の式が数式ではありません');self.assertEqual(vm.emitted_diagnostics[0]['severity'],2)
    def test_string_percent_normal(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML %ABS(1)%\nQUIT\n@ABS(ARG)\n#FUNCTIONS\nRETURNF "user"\n');vm.run();self.assertIn('user',self.out.getvalue())
    def test_raw_print_not_form(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTL {"bad"}\nQUIT\n');vm.run();self.assertIn('{"bad"}',self.out.getvalue())

class PowerFormattingR10(unittest.TestCase):
    def message(self,x,y):
        with self.assertRaises(EraError) as e:power_value(x,y)
        self.assertEqual(e.exception.code,'E_ARITH');return e.exception.message
    def test_archived_2pow63(self):self.assertIn('9.22337203685478E+18',self.message(2,63))
    def test_supplement_2pow64(self):self.assertIn('1.84467440737096E+19',self.message(2,64))
    def test_negative_boundary_source(self):self.assertIn('-9.22337203685478E+18',self.message(-2,63))
    def test_exponent_and_rounding(self):self.assertIn('3.64729963771708E+19',self.message(3,41));self.assertIn('1E+19',self.message(10,19))
    def test_24_dotnet_supplement_bitpatterns(self):
        rows=json.loads((Path(__file__).resolve().parents[1]/'verification/evidence/run09_received/dotnet-supplement/OracleRun09-records/power-format-probe/result.json').read_text())['rows']
        for r in rows:
            v=struct.unpack('<d',struct.pack('<q',int(r['double_bits_int64'])))[0];self.assertEqual(format(v,'.15G'),r['dotnet_framework']['default'])
    def test_success_infinity_nan_paths(self):
        self.assertEqual(power_value(2,3),8);self.assertEqual(self.message(2,1024),'累乗結果が無限大です');self.assertEqual(self.message(0,-1),'累乗結果が無限大です')

class ComparatorPartialR10(unittest.TestCase):
    REF='Oracle.ERBの2行目でエラーが発生しました:Emuera\nエラー内容：{}の中の式が数式ではありません\n現在の関数：@SYSTEM_TITLE（Oracle.ERBの1行目）\n関数呼び出しスタック：\n'
    def py(self,message=None):return dict(code='E_TYPE',file='ERB/Oracle.ERB',line=2,diagnostic_message=message or '{}の中の式が数式ではありません',stack=[dict(function='SYSTEM_TITLE',file='ERB/Oracle.ERB',line=2)])
    def test_error_comparable_without_outputlog(self):
        axes=error_axes(self.REF,self.py());r=outcome_comparison('script_error','script_error',capture_status='capture_incomplete',**axes);self.assertEqual(r['status'],'capture_incomplete');self.assertEqual(r['error_text_status'],'verified_equal');self.assertEqual(r['post_error_state_status'],'not_observed')
    def test_error_message_mismatch_without_capture(self):
        r=outcome_comparison('script_error','script_error',capture_status='capture_incomplete',**error_axes(self.REF,self.py('different')));self.assertEqual(r['status'],'mismatch_open')
    def test_stack_mismatch(self):
        p=self.py();p['stack'][0]['line']=3;a=error_stack_axes(self.REF,p);r=outcome_comparison('script_error','script_error',capture_status='capture_incomplete',**a);self.assertEqual(r['status'],'mismatch_open')
    def test_stack_equal(self):self.assertEqual(error_stack_axes(self.REF,self.py())['error_stack_status'],'verified_equal')
    def test_normal_vs_error_capture_missing(self):self.assertEqual(outcome_comparison('normal_complete','script_error',capture_status='capture_incomplete')['status'],'mismatch_open')
    def test_error_vs_normal_capture_missing(self):self.assertEqual(outcome_comparison('script_error','normal_complete',capture_status='capture_incomplete')['status'],'mismatch_open')
    def test_both_unobserved(self):self.assertEqual(outcome_comparison('not_observed','not_observed',capture_status='capture_incomplete')['status'],'capture_incomplete')
    def test_timeout(self):self.assertEqual(outcome_comparison('normal_complete','timeout',capture_status='capture_incomplete')['status'],'infrastructure_pending')
    def test_platform(self):self.assertEqual(outcome_comparison('normal_complete','platform_unsupported',capture_status='capture_incomplete')['status'],'platform_unsupported')
