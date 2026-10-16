"""Ordering and failure boundaries in the old VM/array core."""
from test_core import Harness
from pyemuera.errors import EraError


class CallAndLoopContracts(Harness):
    def test_actuals_capture_caller_scope_before_callee_binding(self):
        vm = self.make('@MAIN\nARG:0 = 8\nCALL CHILD, 3, ARG:0\nRETURN\n'
                       '@CHILD(ARG:0, ARG:1)\nB = ARG:1\nRETURN\n')
        vm.call('MAIN')
        self.assertEqual(vm.get('B'), 8)

    def test_default_evaluates_after_first_callee_parameter_write(self):
        vm = self.make('@MAIN\nARG:0 = 8\nCALL CHILD, 3\nRETURN\n'
                       '@CHILD(ARG:0, ARG:1=ARG:0+1)\nB = ARG:1\nRETURN\n')
        vm.call('MAIN')
        self.assertEqual(vm.get('B'), 4)

    def test_binding_failure_keeps_earlier_write_but_removes_child_frame(self):
        vm = self.make('@MAIN\nCALL CHILD, 67, 4\nRETURN\n'
                       '@CHILD(ARG:0, ARGS:0)\nRETURN\n')
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_TYPE')
        self.assertEqual(vm.legacy['CHILD']['ARG'].get((0,)), 67)
        self.assertEqual([f.function.name for f in vm.frames], ['MAIN'])
        self.assertEqual(caught.exception.location.line, 2)

    def test_argument_failure_retains_prior_caller_effect_and_no_child(self):
        vm = self.make('@MAIN\nCALL CHILD, A++, 1/C\nRETURN\n'
                       '@CHILD(ARG:0, ARG:1)\nRETURN\n')
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_ARITH')
        self.assertEqual(vm.get('A'), 1)
        self.assertEqual([f.function.name for f in vm.frames], ['MAIN'])

    def test_load_flag_rejects_line_before_actual_side_effect(self):
        vm = self.make('@MAIN\nCALL CHILD, A++, 1/0\nRETURN\n'
                       '@CHILD(ARG:0, ARG:1)\nRETURN\n')
        with self.assertRaises(EraError):
            vm.call('MAIN')
        self.assertEqual(vm.get('A'), 0)

    def test_for_bounds_evaluate_in_order_after_reference(self):
        vm = self.script('FOR B:(A++), A++, A++ + 2, A++\nBREAK\nNEXT')
        self.assertEqual(vm.get('A'), 4)
        self.assertEqual(vm.get('B:0'), 4)
        invalid = self.make('@MAIN\nFOR B:A++, A++, A++ + 2, A++\nBREAK\nNEXT\nRETURN\n')
        with self.assertRaises(EraError):invalid.call('MAIN')
        self.assertEqual(invalid.get('A'), 0)

    def test_repeat_break_increments_and_does_not_restore_shared_count(self):
        vm = self.script('COUNT = 99\nREPEAT 5\nBREAK\nREND')
        self.assertEqual(vm.get('COUNT'), 1)

    def test_varset_reads_end_start_then_value(self):
        vm = self.make('@MAIN\nVARSET A, MARK(9), MARK(2), MARK(4)\nRETURN\n'
                       '@MARK(ARG:0)\n#FUNCTION\nB = B*10+ARG:0\nRETURNF ARG:0\n')
        vm.call('MAIN')
        self.assertEqual(vm.get('B'), 429)
        self.assertEqual([vm.get('A:'+str(i)) for i in range(5)], [0, 0, 9, 9, 0])

    def test_varset_readonly_rejects_before_value_side_effect(self):
        vm = self.make('@MAIN\nVARSET LOCKED, A++\nRETURN\n', headers='#DIM CONST LOCKED,1 = 3\n')
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_READONLY')
        self.assertEqual(vm.get('A'), 0)

    def test_split_count_is_original_piece_count_after_truncation(self):
        vm = self.make('@MAIN\nSPLIT "a,b,c", ",", SMALL, A\nRETURN\n', headers='#DIMS SMALL,2\n')
        vm.call('MAIN')
        self.assertEqual(vm.get('A'), 3)
        self.assertEqual([vm.get('SMALL:'+str(i)) for i in range(2)], ['a', 'b'])
