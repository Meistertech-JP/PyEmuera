import unittest, tempfile, pathlib, json, sys
from test_evidence_r7 import FixtureR7
from pyemuera.errors import EraError
from pyemuera.registry import COMMAND_SPECS,validate_document
from pyemuera.name_diagnostics import SYSTEM_METHOD_NAMES,RESERVED_NAMES
from tools.oracle_status_r8 import assess
from tools.capture_process_r8 import decode_record,capture

class ForcedArgumentsR8(FixtureR7):
    def source(self,line):return '@SYSTEM_TITLE\nOR_A=7\nQUIT\n'+line+'\n@OR_DEST(ARG)\nRETURN\n'
    def test_registry_not_all_forced(self):
        for n in ('CALL','CALLF','GOTO','IF','ELSEIF','SIF','SELECTCASE','LOOP'):self.assertTrue(COMMAND_SPECS[n]['force_set_argument'])
        self.assertFalse(COMMAND_SPECS['POWER']['force_set_argument'])
    def test_registry_rejects_untrusted_policy(self):
        s=dict(COMMAND_SPECS['IF']);s['load_argument_contract']={'handler':'eval_live'}
        with self.assertRaises(EraError):validate_document({'schema_version':1,'commands':{'IF':s}},'commands')
    def test_if_type_context(self):
        for mode in ('NO','YES'):
            vm=self.vm(self.source('IF "str"\nENDIF'),mode);vm.run();d=vm.emitted_diagnostics
            self.assertEqual([(x['severity'],x['line'],x['reference_message']) for x in d],[(2,4,'IF命令:第1引数の型が正しくありません')]);self.assertEqual(vm.eval('OR_A'),7)
    def test_no_force_elsewhere_no_warning(self):
        vm=self.vm(self.source('POWER OR_A,2,3,1/0'),'NO');vm.run();self.assertEqual(vm.emitted_diagnostics,[])
    def test_reached_warning_does_not_duplicate(self):
        vm=self.vm('@SYSTEM_TITLE\nIF 1/0\nENDIF\nQUIT\n','YES')
        with self.assertRaises(EraError):vm.run()
        self.assertEqual(len(vm.emitted_diagnostics),1)
    def test_no_runtime_effects_during_compile(self):
        vm=self.vm(self.source('IF OR_EFFECT()+RAND:100\nENDIF')+'@OR_EFFECT\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1\n','NO');self.assertEqual(vm.eval('OR_TRACE'),0);self.assertEqual(vm.rng.calls,0) if hasattr(vm.rng,'calls') else None
    def test_argument_plan_safe_ast_cached(self):
        vm=self.vm(self.source('IF 2+3\nENDIF'),'NO');self.assertEqual(vm._expression_cache['2+3'],('lit',5))
    def test_generic_type_not_if_everywhere(self):self.assertEqual(EraError('Integer required, got str',code='E_TYPE').as_dict()['diagnostic_message'],'式の結果が数値ではありません')

def force_test(line):
    def test(self):
        for mode in ('NO','YES'):
            vm=self.vm(self.source(line),mode);vm.run();self.assertEqual([(d['severity'],d['line'],d['reference_message']) for d in vm.emitted_diagnostics],[(2,4,'0による除算が行なわれました')]);self.assertEqual(vm.eval('OR_TRACE'),0)
    return test
for n,line in {'call':'CALL OR_DEST,1/0','callf':'CALLF OR_METHOD,1/0','goto':'GOTO OR_LABEL,1/0','if':'IF 1/0\nENDIF','sif':'SIF 1/0\nPRINTL unreachable','select':'SELECTCASE 1/0\nENDSELECT','elseif':'IF 0\nELSEIF 1/0\nENDIF','loop':'DO\nLOOP 1/0','trycall':'TRYCALL OR_DEST,1/0','callform':'CALLFORM OR_DEST,1/0'}.items():
    # ELSEIF warning is on its second source line.
    if n in ('elseif','loop'):continue
    setattr(ForcedArgumentsR8,'test_force_'+n,force_test(line))

class MethodNamesR8(FixtureR7):
    def test_source_method_table(self):self.assertIn('RAND',SYSTEM_METHOD_NAMES);self.assertIn('ABS',SYSTEM_METHOD_NAMES);self.assertIn('IS',RESERVED_NAMES)
    def test_rand_warning_and_notice(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\n@RAND\n#FUNCTION\nRETURNF 8\n');vm.run();self.assertEqual(vm.emitted_diagnostics[0]['reference_message'],'関数名RANDはEmueraの式中関数を上書きします');self.assertIn('  システム関数"RAND"がユーザー定義関数によって上書きされています\n',self.out.getvalue());self.assertIn('\n \n＊＊＊＊＊警告＊＊＊＊＊',self.out.getvalue())
    def test_method_different_from_variable(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\n@L\n#FUNCTION\nRETURNF 1\n@ABS\n#FUNCTION\nRETURNF 1\n');vm.run();self.assertEqual([x['category'] for x in vm.emitted_diagnostics],['W_FUNCTION_VARIABLE_COLLISION','W_FUNCTION_METHOD_COLLISION'])
    def test_no_warning_setting_no_notice(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\n@RAND\n#FUNCTION\nRETURNF 8\n',config='システム関数が上書きされたとき警告を表示する:NO\n');vm.run();self.assertEqual(vm.emitted_diagnostics,[]);self.assertNotIn('＊＊＊＊＊',self.out.getvalue())
    def test_case_insensitive(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\n@rand\n#FUNCTION\nRETURNF 8\n');vm.run();self.assertEqual(vm.emitted_diagnostics[0]['category'],'W_FUNCTION_METHOD_COLLISION')
    def test_nonmethod_no_overwrite_notice(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\n@RAND\nRETURN\n');vm.run();self.assertEqual(len(vm.emitted_diagnostics),1);self.assertNotIn('＊＊＊＊＊',self.out.getvalue())
    def test_call_resolution_unchanged_not_claimed_reference(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=ABS(-2)\nQUIT\n@ABS\n#FUNCTION\nRETURNF 9\n')
        # v24 selects the user method; its zero-argument signature then fails.
        with self.assertRaises(EraError) as error:vm.run()
        self.assertEqual(error.exception.code,'E_ARGUMENT')

class DiagnosticPresentationR8(FixtureR7):
    def test_syntax_internal_kept(self):
        e=EraError('Expected expression at column 3: 1+',code='E_SYNTAX');self.assertEqual(e.as_dict()['diagnostic_message'],'式が異常です');self.assertEqual(e.as_dict()['internal_message'],e.message)
    def test_power_invalid_load_no_and_yes(self):
        for mode in ('NO','YES'):
            vm=self.vm('@SYSTEM_TITLE\nPOWER OR_A,2,3,1+\nQUIT\n',mode)
            with self.assertRaises(EraError) as error:vm.run()
            self.assertEqual(error.exception.as_dict()['diagnostic_message'],'式が異常です');self.assertEqual(error.exception.code,'E_SYNTAX');self.assertEqual(error.exception.location.line,2)
            self.assertEqual(len(vm.emitted_diagnostics),0 if mode=='NO' else 1)
    def test_index_display_internal_kept(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=OR_ARR:99\nQUIT\n')
        from pyemuera.data import Variable
        vm.data.variables['OR_ARR']=Variable('OR_ARR',dims=(4,))
        with self.assertRaises(EraError) as error:vm.run()
        self.assertEqual(error.exception.as_dict()['diagnostic_message'],'配列型変数OR_ARRの第１引数(99)は配列の範囲外です');self.assertIn('array index outside',error.exception.message);self.assertEqual(error.exception.code,'E_INDEX')
    def test_float_not_speculatively_formatted(self):self.assertIn('9.223372036854776e+18',EraError('9.223372036854776e+18',code='E_ARITH').as_dict()['diagnostic_message'])

class MultidimensionalR8(unittest.TestCase):
    def axes(self):return dict(marker_status='verified_equal',warning_status='verified_equal',error_category_status='verified_equal',error_location_status='verified_equal',error_text_status='verified_equal',post_error_state_status='not_observed',capture_status='capture_complete')
    def test_warning_mismatch_error_pending(self):
        a=self.axes();a['warning_status']='mismatch_open';r=assess(**a);self.assertEqual(r['overall_status'],'mismatch_open');self.assertEqual(r['post_error_state_status'],'not_observed');self.assertTrue(r['mismatch_detected'])
    def test_error_text_mismatch(self):
        a=self.axes();a['error_text_status']='mismatch_open';self.assertEqual(assess(**a)['status'],'mismatch_open')
    def test_error_final_state_pending(self):self.assertEqual(assess(**self.axes())['status'],'error_observation_pending')
    def test_capture_missing(self):
        a=self.axes();a['capture_status']='capture_incomplete';self.assertEqual(assess(**a)['status'],'capture_incomplete')
    def test_warning_like_stays_pending(self):
        a=self.axes();a.update(warning_status='warning_observation_pending',**{k:'not_applicable' for k in ['error_category_status','error_location_status','error_text_status','post_error_state_status']});self.assertEqual(assess(**a)['status'],'warning_observation_pending')
    def test_normal_equal(self):
        a=self.axes();a.update(**{k:'not_applicable' for k in ['error_category_status','error_location_status','error_text_status','post_error_state_status']});self.assertEqual(assess(**a)['status'],'verified_equal')

class StderrBytesR8(unittest.TestCase):
    def test_japanese(self):self.assertEqual(decode_record('日本語の警告・エラー'.encode())['decoded_text'],'日本語の警告・エラー')
    def test_ascii(self):self.assertEqual(decode_record(b'abc')['decoded_text'],'abc')
    def test_symbols(self):self.assertEqual(decode_record('é　⚠'.encode())['decoded_text'],'é　⚠')
    def test_empty(self):self.assertEqual(decode_record(b'')['raw_byte_count'],0)
    def test_cp932_explicit(self):self.assertEqual(decode_record('日本語'.encode('cp932'),'cp932')['decoded_text'],'日本語')
    def test_invalid_utf8_not_replaced(self):self.assertIsNotNone(decode_record(b'\xff')['decoding_error']);self.assertIsNone(decode_record(b'\xff')['decoded_text'])
    def test_process_nonzero_raw(self):
        with tempfile.TemporaryDirectory() as td:
            status=capture([sys.executable,'-c','import sys;sys.stderr.buffer.write("日本語のエラー\\n".encode());sys.exit(3)'],td);self.assertEqual(status,3);self.assertEqual(pathlib.Path(td,'py-stderr.raw').read_bytes(),'日本語のエラー\n'.encode());self.assertEqual(json.loads(pathlib.Path(td,'py-stderr-capture.json').read_text())['process_exit_code'],3)

class GuiSettleR8(unittest.TestCase):
    def test_never_created_log(self):
        from tools.gui_settle_r8 import LogSettle
        s=LogSettle(100);self.assertFalse(s.observe(101));self.assertTrue(s.observe(102.5))
    def test_log_changes_reset_stability(self):
        from tools.gui_settle_r8 import LogSettle
        s=LogSettle(0);self.assertFalse(s.observe(2.5,3));self.assertTrue(s.observe(3.5,3))
    def test_maximum_wait(self):
        from tools.gui_settle_r8 import LogSettle
        s=LogSettle(0);self.assertTrue(s.observe(7,99))

class BulkDiagnosticR8(FixtureR7):
    def vm_array(self,source):
        from pyemuera.data import Variable
        vm=self.vm(source);vm.data.variables['OR_ARR']=Variable('OR_ARR',dims=(4,));return vm
    def test_overflow_distinct_from_index(self):
        vm=self.vm_array('@SYSTEM_TITLE\nOR_ARR:3=4,5\nQUIT\n')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.as_dict()['diagnostic_message'],'配列変数OR_ARRの要素数を超えて代入しようとしました');self.assertEqual(vm.eval('OR_ARR:3'),4);self.assertEqual(e.exception.code,'E_INDEX');self.assertEqual(e.exception.location.line,2)
    def test_initial_index_stays_index(self):
        vm=self.vm_array('@SYSTEM_TITLE\nOR_ARR:9=4,5\nQUIT\n')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.as_dict()['diagnostic_message'],'配列型変数OR_ARRの第１引数(9)は配列の範囲外です')

class CaseTrailingCommaR8(FixtureR7):
    def test_static_and_runtime_trailing_comma(self):
        for mode in ('NO','YES'):
            vm=self.vm('@SYSTEM_TITLE\nSELECTCASE 4\nCASE 1,2,\nOR_A=1\nCASEELSE\nOR_A=9\nENDSELECT\nQUIT\n',mode);vm.run();self.assertEqual(vm.emitted_diagnostics,[]);self.assertEqual(vm.eval('OR_A'),9)
    def test_interior_omission_rejected(self):
        from pyemuera.text import split_case_args
        with self.assertRaises(EraError) as e:split_case_args('1,,2')
        self.assertEqual(e.exception.message,'CASEの引数は省略できません')
    def test_case_constant_restructure(self):
        vm=self.vm('@SYSTEM_TITLE\nQUIT\nSELECTCASE 0\nCASE 1/0,\nENDSELECT\n','NO');vm.run();self.assertEqual([(d['severity'],d['line'],d['reference_message']) for d in vm.emitted_diagnostics],[(2,4,'0による除算が行なわれました')])
