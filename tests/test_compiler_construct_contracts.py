"""Construct lowering preserves source diagnostics and partial compile state."""
import unittest
from pyemuera.program import Compiler, Function, SourceLine
from pyemuera.errors import EraError, Location
from test_core import Harness


class CompileFailures(unittest.TestCase):
    def compiler(self, lines):
        function = Function('MAIN', [], Location('ERB/Main.ERB', 1))
        function.lines = [SourceLine(text, Location('ERB/Main.ERB', i+2)) for i, text in enumerate(lines)]
        return Compiler(function)

    def test_unclosed_loop_keeps_emitted_body_and_active_patch_context(self):
        compiler = self.compiler(['IF 1','FOR A,0,3','B = 1'])
        with self.assertRaises(EraError) as caught:
            compiler.compile()
        self.assertEqual(caught.exception.message, 'Unclosed FOR')
        self.assertEqual(caught.exception.location.line, 3)
        self.assertEqual([i.op for i in compiler.code], ['_IF','_FOR','_ASSIGN'])
        self.assertEqual(compiler.i, 3)
        self.assertEqual(len(compiler.loops), 1)

    def test_bad_case_reports_marker_and_retains_select_prefix(self):
        compiler = self.compiler(['SELECTCASE A','PRINTL bad'])
        with self.assertRaises(EraError) as caught:
            compiler.compile()
        self.assertEqual(caught.exception.message, 'Expected CASE')
        self.assertEqual(caught.exception.location.line, 3)
        self.assertEqual([i.op for i in compiler.code], ['_SELECT'])
        self.assertEqual(compiler.i, 2)

    def test_unclosed_data_group_reports_opening_without_emitting_data(self):
        compiler = self.compiler(['PRINTDATAL','DATALIST','DATA first','ENDDATA'])
        with self.assertRaises(EraError) as caught:
            compiler.compile()
        self.assertEqual(caught.exception.message, 'Unclosed DATALIST')
        self.assertEqual(caught.exception.location.line, 2)
        self.assertEqual(compiler.code, [])
        self.assertEqual(compiler.i, 4)


class NestedExecution(Harness):
    def test_nested_if_select_continue_and_break_patch_targets(self):
        vm = self.script('FOR A,0,5\nIF A == 1\nCONTINUE\nELSEIF A == 4\nBREAK\nENDIF\nSELECTCASE A\nCASE 0\nB += 1\nCASE 2\nB += 10\nCASEELSE\nB += 100\nENDSELECT\nNEXT')
        self.assertEqual((vm.get('A'), vm.get('B')), (5, 111))

    def test_dataform_evaluates_selected_group_at_execution(self):
        vm = self.make('@MAIN\nA = 4\nPRINTDATAL\nDATALIST\nDATA raw\nDATAFORM {A++}\nENDLIST\nENDDATA\nRETURN\n')
        self.assertEqual(vm.get('A'), 0)
        vm.call('MAIN')
        self.assertEqual(vm.get('A'), 5)
        self.assertEqual(self.output.getvalue(), 'raw\n4\n')
