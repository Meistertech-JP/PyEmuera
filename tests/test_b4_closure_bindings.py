"""Compare independent live VMs; plans retain syntax rather than VM state."""
import os
from unittest.mock import patch

from test_core import Harness, EXPR_CASES
from pyemuera import expr, runtime
from pyemuera.closure_evaluator import ClosurePlans
from pyemuera.data import Variable
from pyemuera.errors import EraError


class ClosureBindings(Harness):
    def pair(self):
        return [self.make(expression_backend=backend)
                for backend in ('legacy', 'closures')]

    def test_neutral_expression_corpus_in_independent_vms(self):
        old, new = self.pair()
        for name, text, expected in EXPR_CASES:
            with self.subTest(name=name):
                self.assertEqual(old.eval(text), expected)
                self.assertEqual(new.eval(text), expected)

    def test_default_and_environment_flag_and_explicit_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.make().expression_backend, 'legacy')
        with patch.dict(os.environ, {'PYEMUERA_EXPRESSION_BACKEND': 'closures'}):
            self.assertEqual(self.make().expression_backend, 'closures')
            self.assertEqual(self.make(expression_backend='legacy').expression_backend,
                             'legacy')
        with self.assertRaises(ValueError):
            self.make(expression_backend='unknown')

    def test_rng_and_partial_writes_match_without_double_evaluating_one_vm(self):
        old, new = self.pair()
        for text in ('A++ + A++', 'A++ / ++A', 'A++ % ++A',
                     '-A++', 'RAND:100 + RAND:100',
                     '0 && A++', '1 || A++', '1 ? A++ # RAND:100'):
            self.assertEqual(old.eval(text), new.eval(text), text)
            self.assertEqual(old.get('A'), new.get('A'), text)
        # The next 625 outputs also expose accidental extra RNG consumption.
        for _ in range(625):
            self.assertEqual(old.eval('RAND:1000000'), new.eval('RAND:1000000'))

    def test_replaced_variable_and_resized_csv_shape_are_live(self):
        for vm in self.pair():
            node = expr.parse('A:1 + A:0')
            variable = Variable('A', (2,))
            variable.set((0,), 3)
            variable.set((1,), 7)
            vm.data.variables['A'] = variable
            self.assertEqual(vm.eval_node(node), 10)
            variable = Variable('A', (1,))
            vm.data.variables['A'] = variable
            with self.assertRaises(EraError) as caught:
                vm.eval_node(node)
            self.assertEqual(caught.exception.code, 'E_INDEX')

    def test_character_target_remains_live_after_plan_creation(self):
        for vm in self.pair():
            vm.data.character_count = 2
            variable = Variable('CFLAG', (2,), character=True)
            variable.set((0, 1), 13)
            variable.set((1, 1), 29)
            vm.data.variables['CFLAG'] = variable
            node = expr.parse('CFLAG:1 + 1')
            vm.set('TARGET', 0)
            self.assertEqual(vm.eval_node(node), 14)
            vm.set('TARGET', 1)
            self.assertEqual(vm.eval_node(node), 30)

    def test_unexecuted_invalid_branch_is_not_rejected_during_planning(self):
        vm = self.make(expression_backend='closures')
        plans = ClosurePlans()
        bad = ('binary', '/', ('lit', 1), ('lit', 0))
        node = ('ternary', ('lit', 1), ('lit', 19), bad)
        run = plans.plan(node)
        self.assertEqual(run(vm, True), 19)
        run = plans.plan(bad)
        with self.assertRaises(EraError) as caught:
            run(vm, True)
        self.assertEqual(caught.exception.code, 'E_ARITH')

    def test_cache_uses_identity_and_retains_no_vm_binding(self):
        plans = ClosurePlans(capacity=3)
        a = tuple(['lit', 1234])
        b = tuple(['lit', 1234])
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        first = plans.plan(a)
        self.assertIs(first, plans.plan(a))
        self.assertIsNot(first, plans.plan(b))
        for i in range(20):
            plans.plan(('lit', i))
        self.assertLessEqual(len(plans.entries), 3)
        self.assertGreater(plans.clears, 0)
        self.assertEqual(first(None, True), 1234)

    def test_runtime_evaluator_override_is_never_bypassed(self):
        vm = self.make(expression_backend='legacy')
        node = expr.parse('1 + 2')
        calls = []
        def replacement(value, owner):
            calls.append((value, owner))
            return 71
        with patch.object(runtime, 'evaluate', replacement):
            self.assertEqual(vm.eval_node(node), 71)
        self.assertEqual(calls, [(node, vm)])

    def test_error_location_and_prior_instruction_effects_match(self):
        results = []
        for backend in ('legacy', 'closures'):
            vm = self.make('@MAIN\nA=7\nB = A++ / 0\nRETURN\n',
                           expression_backend=backend)
            with self.assertRaises(EraError) as caught:
                vm.call('MAIN')
            error = caught.exception
            results.append((error.code, error.message, error.location.line,
                            vm.get('A'), vm.get('B')))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], ('E_ARITH', 'Division by zero', 3, 7, 0))
