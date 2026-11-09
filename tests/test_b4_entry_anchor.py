"""Host entry counterexamples and fail-closed construction proof."""
import unittest
from unittest.mock import patch
from pyemuera import runtime, expr
from pyemuera.closure_evaluator import ClosurePlans
import test_core
from test_core import Harness
from construction_fixture import construct_vm, COMPOSITE_PROOFS


class OriginalEntryAnchor(Harness):
    def test_preinstalled_baseclass_callable_is_preserved(self):
        original = runtime.VM._LEGACY_EVAL_NODE
        events = []
        def hook(vm, node):
            events.append((vm, node))
            return original(vm, node) + 100
        with patch.object(runtime.VM, 'eval_node', hook):
            for backend in ('legacy', 'closures'):
                vm = self.make(expression_backend=backend)
                self.assertNotIn('eval_node', vm.__dict__)
                self.assertIs(runtime.VM._LEGACY_EVAL_NODE, original)
                self.assertIs(vm.eval_node.__func__, hook)
                self.assertEqual(vm.eval_node(('lit', 7)), 107)
                self.assertEqual(events[-1], (vm, ('lit', 7)))

    def test_preinstalled_baseclass_noncallable_is_preserved(self):
        for hook in (None, 17):
            with patch.object(runtime.VM, 'eval_node', hook):
                for backend in ('legacy', 'closures'):
                    with self.subTest(hook=hook, backend=backend):
                        vm = self.make(expression_backend=backend)
                        self.assertNotIn('eval_node', vm.__dict__)
                        self.assertIs(vm.eval_node, hook)
                        with self.assertRaises(TypeError): vm.eval_node(('lit', 3))

    def test_preinstalled_subclass_callable_and_super_chain_preserved(self):
        class Custom(runtime.VM):
            def eval_node(self, node): return super().eval_node(node) + 10
        with patch.object(test_core, 'VM', Custom):
            for backend in ('legacy', 'closures'):
                vm = self.make(expression_backend=backend)
                self.assertNotIn('eval_node', vm.__dict__)
                self.assertIs(vm.eval_node.__func__, Custom.eval_node)
                self.assertEqual(vm.eval_node(('lit', 2)), 12)

    def test_preinstalled_subclass_noncallable_is_preserved(self):
        class Custom(runtime.VM): eval_node = None
        with patch.object(test_core, 'VM', Custom):
            for backend in ('legacy', 'closures'):
                vm = self.make(expression_backend=backend)
                self.assertNotIn('eval_node', vm.__dict__)
                self.assertIsNone(vm.eval_node)
                with self.assertRaises(TypeError): vm.eval('1')

    def test_default_class_and_instance_changes_after_creation_remain_live(self):
        vm = self.make(expression_backend='legacy')
        with patch.object(runtime.VM, 'eval_node', lambda self,node: 31):
            self.assertEqual(vm.eval('1'), 31)
            vm.eval_node = lambda node: 32
            self.assertEqual(vm.eval('1'), 32)
            del vm.eval_node
            self.assertEqual(vm.eval('1'), 31)
        with patch.object(runtime.VM, 'eval_node', None):
            with self.assertRaises(TypeError): vm.eval('1')
        self.assertEqual(vm.eval('1'), 1)

    def test_optin_postconstruction_class_change_does_not_reselect(self):
        vm = self.make(expression_backend='closures')
        entry = vm.eval_node
        for hook in (lambda self,node: 999, None):
            with patch.object(runtime.VM, 'eval_node', hook):
                self.assertIs(vm.eval_node, entry)
                self.assertEqual(vm.eval('1+2'), 3)
        # Explicit constructor-selection boundary; no per-node MRO check.

    def test_fixture_rejects_unselected_proposed_entry(self):
        with patch.object(runtime.VM, 'eval_node', lambda self,node: 0):
            with self.assertRaises(AssertionError):
                construct_vm(runtime.VM, 'closures')

    def test_fixture_does_not_execute_expression_with_observable_helpers(self):
        events = []
        def forbidden(*args, **kwargs):
            events.append(args)
            raise AssertionError('generic construction evaluated an expression')
        with patch.object(expr, 'integer', forbidden), \
             patch.object(expr, 'apply_binary', forbidden), \
             patch.object(ClosurePlans, 'plan', forbidden):
            vm = construct_vm(runtime.VM, 'closures')
        self.assertEqual(events, [])
        self.assertIsNone(vm._closure_plans)

    def test_separate_composite_proof_uses_plans_under_normal_helpers(self):
        self.assertIs(expr.evaluate, expr._BASE_EVALUATE)
        self.assertIs(expr.integer, expr._BASE_INTEGER)
        calls = []
        original = ClosurePlans.plan
        def counted(plans, node, *args, **kwargs):
            calls.append(node)
            return original(plans, node, *args, **kwargs)
        with patch.object(ClosurePlans, 'plan', counted):
            vm = construct_vm(runtime.VM, 'closures')
            self.assertEqual(calls, [])
            self.assertIsNone(vm._closure_plans)
            node = ('binary', '+', ('lit', 3), ('lit', 4))
            self.assertEqual(vm.eval_node(node), 7)
            self.assertIsInstance(vm._closure_plans, ClosurePlans)
            self.assertGreater(vm._closure_plans.misses, 0)
            self.assertIn(node, calls)
        COMPOSITE_PROOFS.append((vm.eval_node.__func__.__module__, len(calls)))


if __name__ == '__main__': unittest.main()
