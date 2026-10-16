import unittest,json,pathlib,hashlib
from test_evidence_r7 import FixtureR7
from pyemuera.errors import EraError
from pyemuera.constant_ast import Reducer
from pyemuera.expr import parse
from tools.oracle_outcome_r9 import outcome_comparison,reference_outcome,py_outcome,validated_error

class ResolutionR9(FixtureR7):
    def source(self,expression,definition):return '@SYSTEM_TITLE\nOR_A='+expression+'\nQUIT\n'+definition
    def test_archived_abs_and_independent_rand(self):
        for name,arg in [('ABS','-2'),('RAND','100'),('POWER','2,3')]:
            params='ARG,ARG:1' if name=='POWER' else 'ARG'
            vm=self.vm(self.source(name+'('+arg+')','@'+name+'('+params+')\n#FUNCTION\nRETURNF 9\n'));vm.run();self.assertEqual(vm.eval('OR_A'),9)
    def test_normal_label_keeps_builtin(self):
        vm=self.vm(self.source('ABS(-2)','@ABS(ARG)\nRETURN\n'),'YES');vm.run();self.assertEqual(vm.eval('OR_A'),2)
    def test_builtin_without_user(self):
        vm=self.vm(self.source('ABS(-2)',''),'YES');vm.run();self.assertEqual(vm.eval('OR_A'),2)
    def test_functions_string_overrides_numeric_builtin(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_STR\'=ABS(1)\nQUIT\n@ABS(ARG)\n#FUNCTIONS\nRETURNF "user"\n','YES');vm.run();self.assertEqual(vm.eval('OR_STR'),'user')
    def test_user_signature_precedes_builtin_arity(self):
        vm=self.vm(self.source('ABS(1,2)','@ABS(ARG,ARG:1)\n#FUNCTION\nRETURNF ARG+ARG:1\n'),'YES');vm.run();self.assertEqual(vm.eval('OR_A'),3);self.assertEqual(vm.emitted_diagnostics[0]['severity'],1)
    def test_user_type_precedes_builtin(self):
        vm=self.vm(self.source('ABS("ab")','@ABS(ARGS)\n#FUNCTION\nRETURNF STRLENS(ARGS)\n'),'YES');vm.run();self.assertEqual(vm.eval('OR_A'),2)
    def test_error_does_not_fallback(self):
        vm=self.vm(self.source('ABS(1)','@ABS(ARG)\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1/0\n'))
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.code,'E_ARITH');self.assertEqual(vm.eval('OR_TRACE'),1)
    def test_no_builtin_fold_user_power(self):
        vm=self.vm(self.source('POWER(2,3)','@POWER(ARG,ARG:1)\n#FUNCTION\nOR_TRACE+=1\nRETURNF 9\n'),'YES');self.assertEqual(vm.eval('OR_TRACE'),0);self.assertEqual(vm._expression_cache['POWER(2,3)'][0],'call');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(9,1))
    def test_normal_power_can_fold(self):
        vm=self.vm(self.source('POWER(2,3)','@POWER(ARG,ARG:1)\nRETURN\n'),'YES');self.assertEqual(vm._expression_cache['POWER(2,3)'],('lit',8));vm.run();self.assertEqual(vm.eval('OR_A'),8)
    def test_warning_off_does_not_change_resolution(self):
        vm=self.vm(self.source('ABS(-2)','@ABS(ARG)\n#FUNCTION\nRETURNF 9\n'),'YES',config='システム関数が上書きされたとき警告を表示する:NO\n');vm.run();self.assertEqual(vm.eval('OR_A'),9);self.assertEqual(vm.emitted_diagnostics,[])
    def test_lower_case_and_form(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML V={abs(-2)}\nQUIT\n@abs(ARG)\n#FUNCTION\nRETURNF 9\n');vm.run();self.assertIn('V=9',self.out.getvalue())
    def test_cache_per_program(self):
        a=self.vm(self.source('ABS(-2)','@ABS(ARG)\n#FUNCTION\nRETURNF 9\n'),'YES');a.run();b=self.vm(self.source('ABS(-2)',''),'YES');b.run();self.assertEqual((a.eval('OR_A'),b.eval('OR_A')),(9,2))
    def test_argument_order_and_nested_calls(self):
        vm=self.vm(self.source('ABS(OR_E(1),OR_E(2))','@ABS(ARG,ARG:1)\n#FUNCTION\nRETURNF ARG+ARG:1\n@OR_E(ARG)\n#FUNCTION\nOR_TRACE=OR_TRACE*10+ARG\nRETURNF ARG\n'));vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(3,12))
    def test_default_argument_selected_user(self):
        vm=self.vm(self.source('ABS()','@ABS(ARG=9)\n#FUNCTION\nRETURNF ARG\n'),'YES');vm.run();self.assertEqual(vm.eval('OR_A'),9)
    def test_extra_arity_rejected_before_effect(self):
        vm=self.vm(self.source('ABS(OR_E())','@ABS\n#FUNCTION\nRETURNF 9\n@OR_E\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1\n'))
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.code,'E_ARGUMENT');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_multifile_forward_definition(self):
        (self.g/'ERB/Other.ERB').write_text('@ABS(ARG)\n#FUNCTION\nRETURNF 9\n');vm=self.vm(self.source('ABS(-2)',''),'YES');vm.run();self.assertEqual(vm.eval('OR_A'),9)

class InitRandR9(FixtureR7):
    def test_void_extras(self):
        for mode in ('NO','YES'):
            for extra in ('','42','"abc"','1+','OR_E()','1,2,3'):
                vm=self.vm('@SYSTEM_TITLE\nINITRAND '+extra+'\nOR_A=RAND:100\nDUMPRAND\nQUIT\n@OR_E\n#FUNCTION\nOR_TRACE+=1\nRETURNF 42\n',mode);vm.run();self.assertEqual(vm.eval('OR_A'),0);self.assertEqual(vm.eval('OR_TRACE'),0);self.assertEqual(vm.eval('RANDDATA:624'),2)
                d=vm.emitted_diagnostics;self.assertEqual(len(d),int(mode=='YES' and bool(extra)))
                if d:self.assertEqual((d[0]['severity'],d[0]['line'],d[0]['reference_message']),(1,2,'INITRAND命令:引数は不要です'))
    def test_dump_void_does_not_execute_extra(self):
        vm=self.vm('@SYSTEM_TITLE\nDUMPRAND OR_E()\nQUIT\n@OR_E\n#FUNCTION\nOR_TRACE+=1\nRETURNF 4\n','YES');vm.run();self.assertEqual(vm.eval('OR_TRACE'),0);self.assertEqual(vm.eval('RANDDATA:624'),624)
    def test_no_extra_runtime_warning(self):
        vm=self.vm('@SYSTEM_TITLE\nINITRAND 42\nINITRAND 42\nQUIT\n','NO');vm.run();self.assertEqual(vm.emitted_diagnostics,[])
    def test_restore_not_seed(self):
        vm=self.vm('@SYSTEM_TITLE\nRANDDATA:0=123\nRANDDATA:1=456\nINITRAND 42\nOR_A=RAND:10000\nDUMPRAND\nQUIT\n');vm.run();self.assertEqual(vm.eval('OR_A'),((123<<32)|456)%10000);self.assertEqual(vm.eval('RANDDATA:0'),123)
    def test_rand_variable_not_user_call(self):
        vm=self.vm('@SYSTEM_TITLE\nINITRAND\nOR_A=RAND:100\nQUIT\n@RAND(ARG)\n#FUNCTION\nOR_TRACE+=1\nRETURNF 9\n');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(0,0))
    def test_nonzero_roundtrip(self):
        vm=self.vm('@SYSTEM_TITLE\nDUMPRAND\nQUIT\n');vm.run();words=vm.rng.get_native();a=vm.rng.randrange(100000);vm.rng.set_native(words);b=vm.rng.randrange(100000);self.assertEqual(a,b)

class OutcomeR9(unittest.TestCase):
    def test_reference_success_py_error_capture_missing(self):
        r=outcome_comparison('normal_complete','script_error',capture_status='capture_incomplete');self.assertEqual(r['status'],'mismatch_open');self.assertTrue(r['mismatch_detected']);self.assertEqual(r['capture_status'],'capture_incomplete')
    def test_reverse_mismatch(self):self.assertEqual(outcome_comparison('script_error','normal_complete')['status'],'mismatch_open')
    def test_both_error_state_pending(self):
        r=outcome_comparison('script_error','script_error',capture_status='capture_complete',marker_status='verified_equal',warning_status='verified_equal',error_category_status='verified_equal',error_location_status='verified_equal',error_text_status='verified_equal',post_error_state_status='not_observed');self.assertEqual(r['status'],'error_observation_pending')
    def test_no_log_no_error_unknown(self):self.assertEqual(outcome_comparison('not_observed','not_observed',capture_status='capture_incomplete')['status'],'capture_incomplete')
    def test_timeout_is_infrastructure(self):self.assertEqual(outcome_comparison('normal_complete','timeout')['status'],'infrastructure_pending')
    def test_platform_separate(self):self.assertEqual(outcome_comparison('normal_complete','platform_unsupported')['status'],'platform_unsupported')
    def test_warning_mismatch_and_state_pending(self):self.assertEqual(outcome_comparison('script_error','script_error',warning_status='mismatch_open',post_error_state_status='not_observed')['status'],'mismatch_open')
    def test_marker_only_without_gui_not_success(self):self.assertEqual(reference_outcome('ORACLE|end\n',{},identity_verified=True),'not_observed')
    def test_missing_expected_marker(self):self.assertEqual(reference_outcome('ORACLE|end\n',dict(warnings_and_errors_reviewed=True,observer='test',error_dialogs_observed=0),identity_verified=True,expected_ids=['value','end']),'not_observed')
    def test_identity_not_proven(self):self.assertEqual(py_outcome({'error':{'code':'E_ARGUMENT'}}),'not_observed')
    def test_exit_nonzero_alone_not_evidence(self):self.assertEqual(py_outcome({'exit_code':1},identity_verified=True),'not_observed')
    def test_stale_error_rejected(self):
        with self.assertRaises(ValueError):validated_error({'error':{'code':'E_TYPE'}},{'engine_version':'old','error':{'code':'E_TYPE'}},engine_version='new')
    def test_error_envelope_disagreement(self):
        with self.assertRaises(ValueError):validated_error({'error':None},{'engine_version':'new','error':{'code':'E_TYPE'}},engine_version='new')
    def test_wrapper_not_script_error(self):self.assertEqual(py_outcome({'error':{'code':'E_INTERNAL'}},identity_verified=True),'wrapper_exception')
    def test_normal_fixed_observations(self):
        r=outcome_comparison('normal_complete','normal_complete',marker_status='verified_equal',warning_status='verified_equal',error_category_status='not_applicable',error_location_status='not_applicable',error_text_status='not_applicable',post_error_state_status='not_applicable',capture_status='capture_complete');self.assertEqual(r['status'],'verified_equal')
