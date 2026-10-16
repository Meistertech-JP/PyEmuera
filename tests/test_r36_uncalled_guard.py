"""Ignored body guarding is independent from warning visibility/evaluation."""
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.load_arguments import display_diagnostics, _guard_uncalled_entry

class Guard(Harness):
    def unused(self,body='A++\nRETURN',extra=''):
        return self.make('@SYSTEM_TITLE\nRETURN\n@UNUSED\n'+body+'\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'+extra})

    def test_first_line_is_guarded_without_side_effects(self):
        vm=self.unused('A=RAND(10)\nRETURN');rng=vm.rng.getstate()
        with self.assertRaises(EraError) as e:vm.call('UNUSED')
        self.assertEqual(e.exception.code,'E_UNCALLED');self.assertEqual(e.exception.location.line,4)
        self.assertEqual(e.exception.message,'呼び出されないはずの関数が呼ばれた')
        self.assertEqual(vm.get('A'),0);self.assertEqual(vm.rng.getstate(),rng)

    def test_empty_body_has_no_guard(self):
        vm=self.unused('');self.assertEqual(vm.call('UNUSED'),0)

    def test_warning_hidden_does_not_remove_guard(self):
        vm=self.unused(extra='FunctionNotCalledWarning:IGNORE\nDisplayWarningLevel:3\n')
        display_diagnostics(vm);self.assertEqual(vm.emitted_diagnostics,[])
        with self.assertRaises(EraError) as e:vm.call('UNUSED')
        self.assertEqual(e.exception.code,'E_UNCALLED')

    def test_existing_first_line_error_is_not_overwritten(self):
        vm=self.unused();fn=vm.program.functions['UNUSED'][0]
        original=EraError('preexisting',fn.code[0].location,'E_TYPE');fn.code[0].argument_error=original
        _guard_uncalled_entry(vm.program,fn)
        self.assertIs(fn.code[0].argument_error,original)

    def test_later_line_is_not_guarded(self):
        vm=self.unused();fn=vm.program.functions['UNUSED'][0]
        self.assertEqual(fn.code[0].argument_error.code,'E_UNCALLED')
        self.assertIsNone(fn.code[1].argument_error)

    def test_first_label_is_pending_not_next_line(self):
        vm=self.unused('$START\nA++\nRETURN')
        self.assertIsNone(vm.program.functions['UNUSED'][0].code[0].argument_error)
        # r40 closes the documented gap: native ErbLoader guards label.NextLine,
        # including a GotoLabelLine, without marking the following instruction.
        self.assertEqual(vm.program.functions['UNUSED'][0].entry_error.code, 'E_UNCALLED')
        with self.assertRaises(EraError) as caught:
            vm.call('UNUSED')
        self.assertEqual(caught.exception.location.line, 4)
        self.assertEqual(vm.get('A'), 0)

    def test_ignoreNO_checks_body_instead(self):
        vm=self.make('@SYSTEM_TITLE\nRETURN\n@UNUSED\nA++\nRETURN',csv={'_fixed.config':'IgnoreUncalledFunction:NO\n'})
        vm.call('UNUSED');self.assertEqual(vm.get('A'),1)

    def test_valid_method_is_independent_root(self):
        vm=self.unused();vm=self.make('@SYSTEM_TITLE\nRETURN\n@UNUSED\n#FUNCTION\nA++\nRETURNF 1',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertEqual(vm.eval('UNUSED()'),1);self.assertEqual(vm.get('A'),1)

    def test_method_unsafe_error_is_not_uncalled_guard(self):
        vm=self.make('@SYSTEM_TITLE\nRETURN\n@UNUSED\n#FUNCTION\nCALL CHILD\nRETURNF 0\n@CHILD\nRETURN',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        ins=vm.program.functions['UNUSED'][0].code[0]
        self.assertEqual(ins.argument_error.code,'E_METHOD_CONTEXT')
        self.assertEqual(vm.steps,0)

    def test_dynamic_FORM_scope_retained(self):
        vm=self.make('@SYSTEM_TITLE\nCALLFORM %STR%\nRETURN\n@UNUSED\nA++\nRETURN',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertIsNone(vm.program.functions['UNUSED'][0].code[0].argument_error)
        self.assertEqual(vm.program.argument_analysis_scope,'dynamic_target_conservative_all')

    def test_unknown_first_command_keeps_existing_runtime_diagnostic(self):
        vm=self.unused('NOT_A_COMMAND\nRETURN')
        self.assertEqual(vm.program.functions['UNUSED'][0].code[0].argument_error.code,'E_SYNTAX')
        with self.assertRaises(EraError) as e:vm.call('UNUSED')
        self.assertNotEqual(e.exception.code,'E_UNCALLED')

    def test_bad_header_is_still_a_load_error(self):
        vm=self.unused('@ BAD HEADER(\nRETURN')
        with self.assertRaises(EraError) as e:vm.run()
        self.assertEqual(e.exception.code,'E_LOAD');self.assertIsNotNone(e.exception.location)
