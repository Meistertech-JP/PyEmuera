"""v24 bracket-parser boundaries and independent warning settings."""
from test_core import Harness
from pyemuera.call_syntax import parse_call
from pyemuera.errors import EraError
from pyemuera.load_arguments import display_diagnostics


class BracketCalls(Harness):
    def test_empty_brackets_preserve_target(self):
        s = parse_call(' CHILD [] ')
        self.assertEqual((s.target, s.arguments, s.empty_subnames), ('CHILD', (), True))

    def test_FORM_placeholder_parentheses_are_inside_name(self):
        s = parse_call('CHILD_{ABS(-2)}[]', True)
        self.assertEqual(s.target, 'CHILD_{ABS(-2)}')
        self.assertTrue(s.empty_subnames)

    def test_nonempty_brackets_are_native_syntax_error(self):
        for argument in ['CHILD[1]', 'CHILD["x"]']:
            with self.assertRaises(EraError) as e: parse_call(argument)
            self.assertEqual(e.exception.code, 'E_SYNTAX')
            self.assertIn("記号']'", e.exception.message)

    def test_bracket_error_does_not_run_effects_or_RNG(self):
        vm = self.make('@MAIN\nCALL CHILD[RAND(10)+A++]\nRETURN\n@CHILD\nB++\nRETURN\n')
        before = vm.rng.getstate()
        with self.assertRaises(EraError) as e: vm.call('MAIN')
        self.assertEqual(e.exception.code, 'E_SYNTAX')
        self.assertEqual((vm.get('A'), vm.get('B')), (0, 0))
        self.assertEqual(vm.rng.getstate(), before)

    def test_parenthesis_after_empty_brackets_is_not_native_arglist(self):
        with self.assertRaises(EraError) as e: parse_call('CHILD[](1)')
        self.assertEqual(e.exception.code, 'E_SYNTAX')

    def test_unclosed_brackets(self):
        with self.assertRaises(EraError) as e: parse_call('CHILD[')
        self.assertEqual(e.exception.code, 'E_SYNTAX')

    def test_CALLF_empty_bracket_calls_user_method(self):
        vm = self.script('CALLF VALUE[]\nRETURN\n@VALUE\n#FUNCTION\nB++\nRETURNF 9')
        self.assertEqual(vm.get('B'), 1)

    def test_CALLFORMF_dynamic_empty_bracket_calls_user_method(self):
        vm = self.script('STR=VALUE\nCALLFORMF %STR%[]\nRETURN\n@VALUE\n#FUNCTION\nB++\nRETURNF 9')
        self.assertEqual(vm.get('B'), 1)

    def test_TRY_missing_brackets_does_not_run_body(self):
        vm = self.script('TRYCCALL MISSING[]\nCATCH\nB=7\nENDCATCH')
        self.assertEqual(vm.get('B'), 7)

    def test_direct_VM_empty_bracket_entry(self):
        vm=self.make('@MAIN\nRETURN\n@CHILD\nB++\nRETURN\n')
        frame=vm._new_frame(vm.function('MAIN'),())
        self.assertTrue(vm._call_instruction(frame, 'CALL', 'CHILD[]'))
        vm._run_until(1)
        self.assertEqual(vm.get('B'), 1)


for operation in ['CALL', 'CALLFORM', 'TRYCALL', 'TRYCALLFORM', 'JUMP', 'JUMPFORM', 'TRYJUMP', 'TRYJUMPFORM']:
    def run(self, operation=operation):
        vm=self.script(operation + ' CHILD[]\nA=8\nRETURN\n@CHILD\nB++\nRETURN')
        self.assertEqual(vm.get('B'), 1)
        self.assertEqual(vm.get('A'), 0 if 'JUMP' in operation else 8)
    setattr(BracketCalls, 'test_empty_' + operation, run)


class WarningFamilies(Harness):
    def make_policy(self, mode='IGNORE', other='IGNORE', level=1, analysis=False):
        source='@SYSTEM_TITLE\nRETURN\n@UNUSED\nCALL FIRST\nCALL FIRST\nCALL SECOND\nRETURN\n@ALSO_UNUSED\nRETURN\n'
        config=f'IgnoreUncalledFunction:NO\nFunctionNotFoundWarning:{mode}\nFunctionNotCalledWarning:{other}\nDisplayWarningLevel:{level}\n'
        vm=self.make(source,csv={'_fixed.config':config})
        if analysis:
            vm.program.analysis_mode=True
            from pyemuera.load_arguments import compile_arguments
            compile_arguments(vm)
        return vm

    def test_uncalled_display_is_independent_of_analysis_selection(self):
        vm=self.make_policy(other='DISPLAY');display_diagnostics(vm)
        ds=[d for d in vm.emitted_diagnostics if d['diagnostic_phase']=='uncalled-function']
        self.assertEqual(len(ds),2)
        self.assertEqual(vm.data.character_count,0)

    def test_uncalled_IGNORE_keeps_raw_records(self):
        vm=self.make_policy();display_diagnostics(vm)
        self.assertEqual(vm.emitted_diagnostics,[])
        self.assertEqual(len(vm.program.uncalled_diagnostics),2)

    def test_uncalled_ONCE_uses_separate_filename_set(self):
        vm=self.make_policy('ONCE','ONCE');display_diagnostics(vm)
        self.assertEqual([d['diagnostic_phase'] for d in vm.emitted_diagnostics],['uncalled-function','call-resolution'])
        self.assertEqual(vm.program.call_warning_projection['uncalled_suppressed'],1)
        self.assertIn('警告Lv1:', self.output.getvalue())
        self.assertIn('警告Lv2:', self.output.getvalue())

    def test_uncalled_LATER_summary_without_individual_warnings(self):
        vm=self.make_policy(other='LATER');display_diagnostics(vm)
        self.assertFalse(any(d['diagnostic_phase']=='uncalled-function' for d in vm.emitted_diagnostics))
        self.assertIn('呼び出されていない事に関する警告を2件',self.output.getvalue())

    def test_analysis_missing_names_are_aggregated(self):
        vm=self.make_policy('IGNORE','IGNORE',3,True);display_diagnostics(vm)
        self.assertEqual(vm.program.call_warning_projection['analysis_missing_names'],{'FIRST':2,'SECOND':1})
        self.assertFalse(any(d['diagnostic_phase']=='call-resolution' for d in vm.emitted_diagnostics))
        self.assertIn('FIRST: 2回',self.output.getvalue())
        fn=vm.function('UNUSED')
        self.assertTrue(all(i.argument_error is None for i in fn.code))

    def test_analysis_CALLF_still_has_individual_line_error(self):
        vm=self.make('@SYSTEM_TITLE\nCALLF MISSING\nRETURN\n',csv={'_fixed.config':'FunctionNotFoundWarning:IGNORE\nDisplayWarningLevel:3\n'})
        vm.program.analysis_mode=True
        from pyemuera.load_arguments import compile_arguments
        compile_arguments(vm)
        display_diagnostics(vm)
        self.assertTrue(any(d['diagnostic_phase']=='callf-resolution' for d in vm.emitted_diagnostics))
        self.assertIsNotNone(vm.function('SYSTEM_TITLE').code[0].argument_error)

    def test_level_filter_does_not_clear_missing_CALL_error(self):
        vm=self.make_policy('DISPLAY','DISPLAY',3);display_diagnostics(vm)
        self.assertEqual(vm.emitted_diagnostics,[])
        with self.assertRaises(EraError):vm.call('UNUSED')

    def test_warning_settings_are_load_snapshot_for_emission(self):
        vm=self.make_policy('DISPLAY');display_diagnostics(vm)
        text=self.output.getvalue();vm.program.config['関数が見つからない警告の扱い']='IGNORE';display_diagnostics(vm)
        self.assertEqual(self.output.getvalue(),text)

for mode in ['IGNORE','DISPLAY','ONCE','LATER']:
    for other in ['IGNORE','DISPLAY','ONCE','LATER']:
        def run(self,mode=mode,other=other):
            vm=self.make_policy(mode,other);display_diagnostics(vm)
            missing=[d for d in vm.emitted_diagnostics if d['diagnostic_phase']=='call-resolution']
            self.assertEqual(len(missing),{'IGNORE':0,'DISPLAY':3,'ONCE':1,'LATER':3}[mode])
            self.assertEqual(vm.program.call_warning_projection['suppressed_individual_warnings'],{'IGNORE':3,'ONCE':2}.get(mode,0))
            self.assertEqual(sum('警告Lv2:' in line for line in self.output.getvalue().splitlines()),
                             len(missing)+(int(mode in {'IGNORE','ONCE'} and other!='IGNORE')))
        setattr(WarningFamilies,'test_matrix_'+mode+'_'+other,run)
