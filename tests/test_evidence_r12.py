import unittest
from test_evidence_r7 import FixtureR7
from pyemuera.errors import EraError
from pyemuera.expr import parse
from pyemuera.constant_ast import Reducer
from pyemuera.expression_arguments import validate_literals
from tools.oracle_status_r12 import error_axes
from tools.oracle_evidence_r12 import evidence_assessment

class SubstringR12(FixtureR7):
    def vm0(self):return self.vm('@SYSTEM_TITLE\nQUIT\n')
    def test_declaration_initializers_non_literal_descriptors(self):
        (self.g/'ERB/Oracle.ERB').write_text('@SYSTEM_TITLE\nQUIT\n',encoding='utf-8-sig')
        (self.g/'ERB/Oracle.ERH').write_text('#DIM CONST OR_FIRST=3\n#DIM CONST OR_SECOND=MAX(OR_FIRST,8)\n',encoding='utf-8-sig')
        from pyemuera.runtime import VM
        from pyemuera.program import Program
        from pyemuera.data import GameData
        from pyemuera.console import Console
        vm=VM(Program(self.g),GameData(self.g),Console([],self.out,no_wait=True),seed=42)
        self.assertEqual(vm.eval('OR_SECOND'),8)
    def test_defaults_and_zero(self):
        for name in ('SUBSTRING','SUBSTRINGU'):
            for args,result in [('"abc"','abc'),('"abc",0,2','ab'),('"abc",,2','ab'),('"abc",1,','bc'),('"abc",0,0',''),('"abc",,','abc'),('""',''),('"abc",-1,2','ab'),('"abc",99,2',''),('"abc",1,-3','bc')]:
                self.assertEqual(self.vm0().eval(name+'('+args+')'),result)
    def test_non_ascii_units(self):
        vm=self.vm0();self.assertEqual(vm.eval('SUBSTRING("日a",0,2)'),'日');self.assertEqual(vm.eval('SUBSTRINGU("日a",0,1)'),'日');self.assertEqual(vm.eval('SUBSTRINGU("😀a",0,2)'),'😀')
    def test_unchecked_int32_indices(self):
        for name in ('SUBSTRING','SUBSTRINGU'):self.assertEqual(self.vm0().eval(name+'("abc",4294967296,2)'),'ab')
    def test_no_global_none_default(self):
        with self.assertRaises(EraError):self.vm0().eval('POWER(,2)')
    def test_dynamic_eval_once_order(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_STR \'= SUBSTRING(OR_TEXT(),,OR_LENGTH())\nQUIT\n@OR_TEXT\n#FUNCTIONS\nOR_TRACE=OR_TRACE*10+1\nRETURNF "abc"\n@OR_LENGTH\n#FUNCTION\nOR_TRACE=OR_TRACE*10+2\nRETURNF 2\n');vm.run();self.assertEqual((vm.eval('OR_STR'),vm.eval('OR_TRACE')),('ab',12))
    def test_inner_before_outer_and_side_effects(self):
        for mode in ('NO','YES'):
            for form in ('{SUBSTRING(1)}','%SUBSTRING(1)%'):
                vm=self.vm('@SYSTEM_TITLE\nPRINTFORML '+form+'\nQUIT\n',mode)
                with self.assertRaises(EraError) as e:vm.run()
                self.assertEqual((e.exception.code,e.exception.message,e.exception.location.line),('E_TYPE','SUBSTRING関数の1番目の引数の型が正しくありません',2));self.assertEqual(vm.eval('OR_TRACE'),0)
                self.assertEqual(len(vm.emitted_diagnostics),int(mode=='YES'))
    def test_outer_only_invalid(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML {SUBSTRING("abc")}\nQUIT\n')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.message,'{}の中の式が数式ではありません')
    def test_valid_percent(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML %SUBSTRING("abc")%\nQUIT\n','YES');vm.run();self.assertIn('abc',self.out.getvalue());self.assertEqual(vm.emitted_diagnostics,[])
    def test_declared_type_validation_does_not_call_user(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML %SUBSTRING(OR_BAD(),OR_SIDE())%\nQUIT\n@OR_BAD\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1\n@OR_SIDE\n#FUNCTION\nOR_TRACE+=10\nRETURNF 2\n')
        with self.assertRaises(EraError):vm.run()
        self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_user_override_forward(self):
        for name in ('SUBSTRING','SUBSTRINGU','MAX','MIN'):
            vm=self.vm('@SYSTEM_TITLE\nOR_A='+name+'(1)\nQUIT\n@'+name+'(ARG)\n#FUNCTION\nOR_TRACE+=1\nRETURNF ARG+8\n','YES');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(9,1))
    def test_user_error_no_builtin_fallback(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=MAX()\nQUIT\n@MAX\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1/0\n')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.code,'E_ARITH');self.assertEqual(vm.eval('OR_TRACE'),1)
    def test_success_cache_never_values(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_STR\'="abc"\nPRINTFORML %SUBSTRING(OR_STR,,2)%\nOR_STR\'="xyz"\nPRINTFORML %SUBSTRING(OR_STR,,2)%\nQUIT\n');vm.run();self.assertIn('ab',self.out.getvalue());self.assertIn('xy',self.out.getvalue())
    def test_error_not_cached(self):
        vm=self.vm0()
        for _ in range(2):
            with self.assertRaises(EraError):vm.eval('SUBSTRING(1)')
        self.assertFalse(getattr(vm,'_expression_argument_type_cache',set()))
    def test_variadic_values(self):
        self.assertEqual(self.vm0().eval('MAX(-9,3,0,2)'),3);self.assertEqual(self.vm0().eval('MIN(-9,3,0,2)'),-9)
    def test_validation_in_reducer_not_falsely_folded(self):
        for text in ('SUBSTRING("abc",,2)','MAX(1,2)'):
            self.assertEqual(Reducer().reduce(parse(text))[0],'call')
    def test_variadic_side_effect_order(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=MAX(OR_NEXT(),OR_NEXT(),OR_NEXT())\nQUIT\n@OR_NEXT\n#FUNCTION\nOR_TRACE+=1\nRETURNF OR_TRACE\n');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(3,3))

class CustomValidationR12(FixtureR7):
    def check(self,name,args,code,message):
        expr=name+'('+args+')'
        with self.assertRaises(EraError) as e:validate_literals(name,parse(expr)[2])
        self.assertEqual((e.exception.code,e.exception.message),(code,message))
        for mode in ('NO','YES'):
            vm=self.vm('@SYSTEM_TITLE\nPRINTFORML '+('%'+expr+'%' if name.startswith('SUBSTRING') else '{'+expr+'}')+'\nQUIT\n',mode)
            with self.assertRaises(EraError) as e:vm.run()
            self.assertEqual((e.exception.code,e.exception.message,e.exception.location.line),(code,message,2))
            self.assertEqual(e.exception.era_stack[-1]['line'],2)

def add_validation(name,args,code,suffix,identifier):
    def test(self):self.check(name,args,code,name+suffix)
    setattr(CustomValidationR12,'test_'+name.lower()+'_'+identifier,test)
for name in ('SUBSTRING','SUBSTRINGU','MAX','MIN'):
    add_validation(name,'','E_ARGUMENT','関数には少なくとも1つの引数が必要です','empty')
    add_validation(name,',' if name.startswith('SUBSTRING') else ',1','E_ARGUMENT','関数の1番目の引数は省略できません','missing_first')
    add_validation(name,'1' if name.startswith('SUBSTRING') else '"a"','E_TYPE','関数の1番目の引数の型が正しくありません','type_first')
    if name.startswith('SUBSTRING'):
        add_validation(name,'"a",1,2,3','E_ARGUMENT','関数の引数が多すぎます','extra')
        add_validation(name,'"a","b"','E_TYPE','関数の2番目の引数の型が正しくありません','type_second')
        add_validation(name,'"a",,"b"','E_TYPE','関数の3番目の引数の型が正しくありません','type_third')
    else:
        add_validation(name,'1,,3','E_ARGUMENT','関数の2番目の引数は省略できません','missing_second')
        add_validation(name,'1,2,"a"','E_TYPE','関数の3番目の引数の型が正しくありません','type_third')

class ComparatorR12(unittest.TestCase):
    def test_exact_message_not_summary(self):
        ref='Oracle.ERBの4行目でエラーが発生しました\nエラー内容：SUBSTRING関数の1番目の引数の型が正しくありません\n'
        py=dict(file='ERB/Oracle.ERB',line=4,code='E_TYPE',message='SUBSTRING関数:第1引数の型が正しくありません')
        self.assertEqual(error_axes(ref,py)['error_text_status'],'mismatch_open')
    def test_max_category(self):
        ref='Oracle.ERBの4行目でエラーが発生しました\nエラー内容：MAX関数には少なくとも1つの引数が必要です\n';py=dict(file='ERB/Oracle.ERB',line=4,code='E_ARGUMENT',message='MAX関数には少なくとも1つの引数が必要です');self.assertEqual(error_axes(ref,py)['error_category_status'],'verified_equal')
    def test_clear_mismatch_wins_missing_capture(self):
        r=evidence_assessment('normal_complete','script_error',execution_ids=['same','same'],gui_coverage='gui_coverage_unverified',capture_status='capture_incomplete');self.assertEqual(r['status'],'mismatch_open')
    def test_gui_unverified_separate(self):
        r=evidence_assessment('normal_complete','normal_complete',execution_ids=['same','same'],gui_coverage='gui_coverage_unverified',marker_status='verified_equal',warning_status='verified_equal',error_category_status='not_applicable',error_location_status='not_applicable',error_text_status='not_applicable',post_error_state_status='not_applicable',capture_status='capture_complete');self.assertEqual(r['raw_log_status'],'verified_equal');self.assertTrue(r['gui_confirmation_unverified'])
    def test_mixed_execution_never_verified(self):
        r=evidence_assessment('normal_complete','normal_complete',execution_ids=['one','two'],gui_coverage='provider');self.assertEqual(r['status'],'infrastructure_pending')
