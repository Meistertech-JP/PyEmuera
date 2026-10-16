import unittest,json,math
from pathlib import Path
from unittest.mock import patch
from test_evidence_r7 import FixtureR7
from pyemuera.errors import EraError
from pyemuera.expr import parse
from pyemuera.numeric_instructions import power_value
from pyemuera.constant_ast import Reducer
from tools.oracle_status_r11 import error_axes,error_stack_axes
from tools.oracle_outcome_r11 import outcome_comparison

class PowerPathsR11(FixtureR7):
    def vm0(self):return self.vm('@SYSTEM_TITLE\nQUIT\n')
    def compare(self,x,y):
        vm=self.vm0();expr='POWER('+str(x)+','+str(y)+')'
        try:expected=power_value(x,y)
        except EraError as target:
            for operation in (lambda:vm.eval(expr),lambda:Reducer().reduce(parse(expr))):
                with self.assertRaises(EraError) as e:operation()
                self.assertEqual((e.exception.code,e.exception.message),(target.code,target.message))
        else:
            self.assertEqual(vm.eval(expr),expected);self.assertEqual(Reducer().reduce(parse(expr)),('lit',expected))
    def test_2pow63(self):self.compare(2,63)
    def test_10pow19(self):self.compare(10,19)
    def test_2pow64(self):self.compare(2,64)
    def test_3pow41(self):self.compare(3,41)
    def test_negative_base_min_boundary(self):self.compare(-2,63)
    def test_negative_exponent(self):self.compare(2,-3)
    def test_zero_zero(self):self.compare(0,0)
    def test_zero_positive(self):self.compare(0,5)
    def test_zero_negative_infinity(self):self.compare(0,-1)
    def test_overflow_infinity(self):self.compare(2,1024)
    def test_max_rounds_outside(self):self.compare(9223372036854775807,1)
    def test_inside_boundary(self):self.compare(2,62)
    def test_negative_inside(self):self.compare(-2,61)
    def test_normal(self):self.compare(2,3)
    def test_nested(self):
        self.assertEqual(self.vm0().eval('POWER(POWER(2,3),2)'),64);self.assertEqual(Reducer().reduce(parse('POWER(POWER(2,3),2)')),('lit',64))
    def test_dynamic_command_method(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=2\nPOWER OR_A,OR_A,3\nOR_TRACE=POWER(2,3)\nQUIT\n');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(8,8))
    def test_effect_order(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=POWER(OR_LEFT(),OR_RIGHT())\nQUIT\n@OR_LEFT\n#FUNCTION\nOR_TRACE=OR_TRACE*10+1\nRETURNF 2\n@OR_RIGHT\n#FUNCTION\nOR_TRACE=OR_TRACE*10+2\nRETURNF 3\n');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(8,12))
    def test_user_power_not_folded(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=POWER(2,63)\nQUIT\n@POWER(ARG,ARG:1)\n#FUNCTION\nOR_TRACE+=1\nRETURNF 9\n','YES');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(9,1))
    def test_sqrt_unchanged(self):
        vm=self.vm0();self.assertEqual(vm.eval('SQRT(9)'),3)
        with self.assertRaises(EraError) as e:vm.eval('SQRT(-1)')
        self.assertEqual(e.exception.message,'Math domain/overflow')
    def test_nan_diagnostic_branch_only(self):
        # Injected branch coverage; integer inputs do not prove reachable NaN.
        with patch('pyemuera.numeric_instructions.math.pow',return_value=math.nan):
            with self.assertRaises(EraError) as e:power_value(1,1)
            self.assertEqual(e.exception.message,'累乗結果が非数値です')

class ArgumentDiagnosticsR11(FixtureR7):
    def failure(self,expr,mode='NO'):
        vm=self.vm('@SYSTEM_TITLE\nOR_A='+expr+'\nQUIT\n',mode)
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.location.line,2);self.assertEqual(e.exception.era_stack[-1]['line'],2)
        return vm,e.exception
    def test_strlens_empty(self):self.assertEqual(self.failure('STRLENS()')[1].message,'STRLENS関数:引数の数が間違っています')
    def test_strlens_wrong_type(self):self.assertEqual(self.failure('STRLENS(1)')[1].message,'STRLENS関数:第1引数の型が間違っています')
    def test_strlens_extra(self):self.assertEqual(self.failure('STRLENS("a","b")')[1].message,'STRLENS関数:引数の数が間違っています')
    def test_strlensu_empty(self):self.assertEqual(self.failure('STRLENSU()')[1].message,'STRLENSU関数:引数の数が間違っています')
    def test_strlensu_wrong_type(self):self.assertEqual(self.failure('STRLENSU(1)')[1].message,'STRLENSU関数:第1引数の型が間違っています')
    def test_strlensu_extra(self):self.assertEqual(self.failure('STRLENSU("a","b")')[1].message,'STRLENSU関数:引数の数が間違っています')
    def test_normal_both(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=STRLENS("abc")\nOR_TRACE=STRLENSU("abc")\nQUIT\n');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(3,3))
    def test_yes_no_message(self):
        for mode in ('NO','YES'):
            vm,e=self.failure('STRLENS(1)',mode);self.assertEqual((e.code,e.message),('E_TYPE','STRLENS関数:第1引数の型が間違っています'));self.assertEqual(len(vm.emitted_diagnostics),int(mode=='YES'))
    def test_abs_default_count(self):self.assertEqual(self.failure('ABS()')[1].message,'ABS関数:引数の数が間違っています')
    def test_power_second_type(self):self.assertEqual(self.failure('POWER(2,"3")')[1].message,'POWER関数:第2引数の型が間違っています')
    def test_power_fold_arity(self):
        with self.assertRaises(EraError) as e:Reducer().reduce(parse('POWER(2)'))
        self.assertEqual((e.exception.code,e.exception.message),('E_ARGUMENT','POWER関数:引数の数が間違っています'))
    def test_user_strlens_forward(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=STRLENS(1)\nQUIT\n@STRLENS(ARG)\n#FUNCTION\nRETURNF ARG+8\n','YES');vm.run();self.assertEqual(vm.eval('OR_A'),9)
    def test_user_functions_forward(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML %STRLENS(1)%\nQUIT\n@STRLENS(ARG)\n#FUNCTIONS\nRETURNF "user"\n','YES');vm.run();self.assertIn('user',self.out.getvalue())
    def test_type_check_before_effect(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_A=STRLENS(SIDE())\nQUIT\n@SIDE\n#FUNCTION\nOR_TRACE+=1\nRETURNF 1\n')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.message,'STRLENS関数:第1引数の型が間違っています');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_cache_not_values(self):
        vm=self.vm('@SYSTEM_TITLE\nOR_STR\'="a"\nOR_A=STRLENS(OR_STR)\nOR_STR\'="abcd"\nOR_A=STRLENS(OR_STR)\nQUIT\n');vm.run();self.assertEqual(vm.eval('OR_A'),4)
    def test_general_expression_error_not_reformatted(self):
        _,e=self.failure('1+"text"');self.assertNotIn('関数:第',e.message)
    def test_form_actual_error(self):
        vm=self.vm('@SYSTEM_TITLE\nPRINTFORML {"bad"}\nQUIT\n')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.message,'{}の中の式が数式ではありません')

class Run10MismatchComparatorR11(unittest.TestCase):
    def check(self,cid):
        root=Path(__file__).resolve().parents[1];d=root/'verification/evidence/run10_received'/cid
        raw=(d/'reference-output.txt').read_bytes();ref=raw.decode('utf-16') if raw[:2] in (b'\xff\xfe',b'\xfe\xff') else raw.decode('utf-8-sig');py=json.loads((d/'py-session.json').read_text())['error'];axes=error_axes(ref,py);axes.update(error_stack_axes(ref,py));self.assertEqual(axes['error_text_status'],'mismatch_open');self.assertEqual(outcome_comparison('script_error','script_error',capture_status='capture_incomplete',**axes)['status'],'mismatch_open')
    def test_power_2pow63_detected(self):self.check('power-format-method-2pow63')
    def test_power_10pow19_detected(self):self.check('power-format-method-10pow19')
    def test_arity_detected(self):self.check('registry-arity-error')
    def test_type_detected(self):self.check('registry-type-error')

class DiagnosticClassificationR11(unittest.TestCase):
    def test_case_omission_not_function_omission(self):
        r=error_axes('Oracle.ERBの6行目でエラーが発生しました\nエラー内容：CASEの引数は省略できません\n',dict(code='E_SYNTAX',file='ERB/Oracle.ERB',line=6,message='CASEの引数は省略できません'));self.assertEqual(r['error_category_status'],'verified_equal')
    def test_function_omission_argument(self):
        r=error_axes('Oracle.ERBの2行目でエラーが発生しました\nエラー内容：STRLENS関数:第1引数は省略できません\n',dict(code='E_ARGUMENT',file='ERB/Oracle.ERB',line=2,message='STRLENS関数:第1引数は省略できません'));self.assertEqual(r['error_category_status'],'verified_equal')
    def test_unknown_diagnostic_not_guessed(self):
        r=error_axes('Oracle.ERBの2行目でエラーが発生しました\nエラー内容：未知の本文\n',dict(code='E_ARGUMENT',file='ERB/Oracle.ERB',line=2,message='未知の本文'));self.assertEqual(r['error_category_status'],'not_observed')
