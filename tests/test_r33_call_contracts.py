"""Raw CALL names, optional warning display, and retained execution errors."""
from test_core import Harness
from pyemuera.call_syntax import parse_call
from pyemuera.load_arguments import display_diagnostics
from pyemuera.errors import EraError, QuitSignal


class CallSyntaxContracts(Harness):
    def test_raw_name_includes_internal_space(self):
        s=parse_call('CALL SET_CONFIG(1,"a,b")')
        self.assertEqual(s.target,'CALL SET_CONFIG')
        self.assertEqual(s.arguments,('1','"a,b"'))

    def test_comma_and_parentheses_equivalent(self):
        self.assertEqual(parse_call('CHILD, 1, A++'),parse_call('CHILD(1, A++)'))

    def test_empty_parentheses_and_ascii_trim(self):
        self.assertEqual(parse_call(' \tCHILD \t( )').arguments,())
        self.assertEqual(parse_call(' \tCHILD \t( )').target,'CHILD')

    def test_escaped_separator_belongs_to_name(self):
        self.assertEqual(parse_call(r'CHILD\(ONE, 2').target,'CHILD(ONE')
        self.assertEqual(parse_call(r'CHILD\sONE(2)').target,'CHILD ONE')

    def test_raw_name_does_not_evaluate_expression_text(self):
        vm=self.make('@MAIN\nCALL CALL SET_CONFIG(A++)\nRETURN\n@SET_CONFIG(ARG)\nB++\nRETURN\n')
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.code,'E_FUNCTION')
        self.assertEqual(caught.exception.location.line,2)
        self.assertEqual((vm.get('A'),vm.get('B')),(0,0))

    def test_regular_CALL_still_evaluates_args_left_to_right(self):
        vm=self.make('@MAIN\nCALL CHILD(A++,A++)\nRETURN\n@CHILD(ARG:0,ARG:1)\nB=ARG:0*10+ARG:1\nRETURN\n')
        vm.call('MAIN')
        self.assertEqual((vm.get('A'),vm.get('B')),(2,1))

    def test_CALLF_rejects_builtin_before_RNG_without_RESULT_write(self):
        vm=self.make('@MAIN\nRETURN\n')
        frame=vm._new_frame(vm.function('MAIN'),())
        vm.set('RESULT',77)
        before=vm.rng.getstate()
        with self.assertRaises(EraError) as caught:
            vm._call_instruction(frame,'CALLF','RAND(10)')
        self.assertEqual(caught.exception.code,'E_FUNCTION')
        self.assertEqual(vm.rng.getstate(),before)
        self.assertEqual(vm.get('RESULT'),77)

    def test_CALLFORMF_rejects_builtin_static_target(self):
        vm=self.make('@MAIN\nCALLFORMF ABS(-2)\nA=7\nRETURN\n')
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.code,'E_FUNCTION')
        self.assertEqual(vm.get('A'),0)

    def test_CALLF_user_method_arity_is_checked_before_values(self):
        vm=self.make('@MAIN\nCALLF VALUE(A++, A++)\nRETURN\n@VALUE(ARG)\n#FUNCTION\nRETURNF ARG\n')
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.code,'E_ARGUMENT')
        self.assertEqual(vm.get('A'),0)

    def test_TRYCALL_missing_does_not_evaluate_arguments(self):
        vm=self.script('TRYCALL MISSING(A++)\nB=7')
        self.assertEqual((vm.get('A'),vm.get('B')),(0,7))

    def test_constant_argument_failure_precedes_missing_binding(self):
        vm=self.make('@MAIN\nCALL CALL MISSING(1/0)\nRETURN\n')
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.code,'E_ARITH')

    def test_direct_call_entry_classifies_missing_name_without_auto_fix(self):
        vm=self.make('@MAIN\nRETURN\n@SET_CONFIG(ARG)\nB++\nRETURN\n')
        frame=vm._new_frame(vm.function('MAIN'),())
        with self.assertRaises(EraError) as caught:vm._call_instruction(frame,'CALL','CALL SET_CONFIG(A++)')
        self.assertEqual(caught.exception.code,'E_FUNCTION')
        self.assertEqual((vm.get('A'),vm.get('B')),(0,0))

    def test_FORM_dynamic_name_is_not_resolved_at_load(self):
        vm=self.make('@MAIN\nSTR=TARGET\nCALLFORM %STR%(A++)\nRETURN\n@TARGET(ARG)\nB=ARG\nRETURN\n')
        vm.call('MAIN')
        self.assertEqual((vm.get('A'),vm.get('B')),(1,0))


class CallWarningPolicy(Harness):
    def load(self, mode, reached=False, body=None, extra='', headers=''):
        body=body or 'CALL CALL SET_CONFIG(A++)\nRETURN'
        entry='CALL CHECK\n' if reached else ''
        source='@SYSTEM_TITLE\n'+entry+'PRINTL AFTER\nRETURN\n@CHECK\n'+body+'\n@SET_CONFIG(ARG)\nB++\nRETURN\n'
        return self.make(source,headers=headers,csv={'_fixed.config':f'IgnoreUncalledFunction:NO\nFunctionNotFoundWarning:{mode}\n'+extra})

    def test_ignore_keeps_line_error_but_displays_no_warning(self):
        vm=self.load('IGNORE');display_diagnostics(vm)
        self.assertEqual(vm.emitted_diagnostics,[])
        self.assertTrue(any(d.phase=='call-resolution' for d in vm.program.argument_diagnostics))
        vm.call('SYSTEM_TITLE')
        self.assertIn('AFTER',self.output.getvalue())
        self.assertEqual(vm.get('A'),0)

    def test_display_unreached_warns_at_load_without_running_it(self):
        vm=self.load('DISPLAY');display_diagnostics(vm)
        self.assertEqual(len(vm.emitted_diagnostics),1)
        self.assertEqual(vm.emitted_diagnostics[0]['severity'],2)
        self.assertIn('@CALL SET_CONFIG',vm.emitted_diagnostics[0]['reference_message'])
        vm.call('SYSTEM_TITLE')
        self.assertEqual((vm.get('A'),vm.get('B')),(0,0))

    def test_once_is_per_file_not_per_name(self):
        vm=self.load('ONCE',body='CALL FIRST\nCALL SECOND\nCALL THIRD\nRETURN')
        display_diagnostics(vm)
        self.assertEqual(len(vm.emitted_diagnostics),1)
        self.assertEqual(vm.program.call_warning_projection['suppressed_individual_warnings'],2)

    def test_once_summary_matches_source_cross_setting_condition(self):
        vm=self.load('ONCE',body='CALL FIRST\nCALL SECOND\nCALL THIRD\nRETURN',extra='FunctionNotCalledWarning:DISPLAY\n')
        display_diagnostics(vm)
        self.assertEqual(sum(d['diagnostic_phase']=='call-resolution' for d in vm.emitted_diagnostics),1)
        self.assertEqual(sum(d['diagnostic_phase']=='uncalled-function' for d in vm.emitted_diagnostics),2)
        self.assertIn('警告を2件無視しました',self.output.getvalue())
        self.assertLess(self.output.getvalue().index('2件無視しました'),self.output.getvalue().index('指定された関数名'))

    def test_source_summary_suppressed_when_other_flag_is_IGNORE(self):
        vm=self.load('ONCE',body='CALL FIRST\nCALL SECOND\nRETURN')
        display_diagnostics(vm)
        self.assertEqual(vm.program.call_warning_projection['summary_count'],0)
        self.assertNotIn('無視しました',self.output.getvalue())

    def test_level_threshold_does_not_clear_execution_error(self):
        vm=self.load('DISPLAY',True,extra='DisplayWarningLevel:3\n');display_diagnostics(vm)
        self.assertEqual(vm.emitted_diagnostics,[])
        with self.assertRaises(EraError) as caught:vm.call('SYSTEM_TITLE')
        self.assertEqual(caught.exception.code,'E_FUNCTION')

    def test_each_policy_still_fails_on_reached_missing_target(self):
        for mode in ['IGNORE','DISPLAY','ONCE']:
            vm=self.load(mode,True);display_diagnostics(vm)
            with self.assertRaises(EraError) as caught:vm.call('SYSTEM_TITLE')
            self.assertEqual(caught.exception.code,'E_FUNCTION')
            self.assertEqual(caught.exception.as_dict()['diagnostic_message'],
                             '指定された関数名\"@CALL SET_CONFIG\"は存在しません')
            self.assertEqual((vm.get('A'),vm.get('B')),(0,0))
            self.assertNotIn('AFTER',self.output.getvalue())

    def test_load_diagnostics_are_emitted_only_once(self):
        vm=self.load('DISPLAY');display_diagnostics(vm);first=self.output.getvalue();display_diagnostics(vm)
        self.assertEqual(self.output.getvalue(),first)

    def test_Japanese_and_English_aliases_share_effective_value(self):
        vm=self.load('IGNORE',extra='関数が見つからない警告の扱い:DISPLAY\n');display_diagnostics(vm)
        self.assertEqual(len(vm.emitted_diagnostics),0)

    def test_CALLF_warning_is_not_suppressed_by_CALL_policy(self):
        vm=self.make('@MAIN\nCALLF MISSING(1)\nRETURN\n',csv={'_fixed.config':'FunctionNotFoundWarning:IGNORE\n'})
        display_diagnostics(vm)
        self.assertEqual(len(vm.emitted_diagnostics),1)
        self.assertEqual(vm.program.argument_diagnostics[0].phase,'callf-resolution')

    def test_plain_CALLFORM_target_has_missing_name_policy(self):
        vm=self.make('@MAIN\nCALLFORM MISSING(A++)\nRETURN\n',csv={'_fixed.config':'FunctionNotFoundWarning:IGNORE\n'})
        display_diagnostics(vm)
        self.assertEqual(vm.emitted_diagnostics,[])
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.code,'E_FUNCTION')
        self.assertEqual(vm.get('A'),0)

    def test_ONCE_tracks_each_file_separately(self):
        vm=self.load('ONCE',body='CALL FIRST\nCALL SECOND\nRETURN',headers='')
        # Distinct file names are compared case-insensitively at projection.
        from dataclasses import replace
        from pyemuera.errors import Location
        first=vm.program.argument_diagnostics[0]
        vm.program.argument_diagnostics.extend([replace(first,location=Location('ERB/other.erb',5)),replace(first,location=Location('erb/OTHER.ERB',6))])
        display_diagnostics(vm)
        self.assertEqual(len(vm.emitted_diagnostics),2)
        self.assertEqual(vm.program.call_warning_projection['suppressed_individual_warnings'],2)
