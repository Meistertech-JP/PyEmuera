"""Constructor-only contracts. No general host-metaprogramming framework."""
import ast
import inspect
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from pyemuera import expr, runtime
from test_core import Harness
from construction_fixture import construct_vm


class ConstructorEntry(Harness):
    def test_public_entry_is_exact_dynamic_global_call(self):
        body = ast.parse(inspect.getsource(runtime.VM.eval_node).strip()).body[0].body
        expected = ast.parse('return evaluate(node, self)').body
        self.assertEqual(ast.dump(ast.Module(body=body, type_ignores=[])),
                         ast.dump(ast.Module(body=expected, type_ignores=[])))
        self.assertNotIn('expression_backend', runtime.VM.__dict__)

    def test_default_environment_unset_has_no_instance_entry(self):
        with patch.dict(os.environ, {}, clear=True):
            vm = self.make()
        self.assertEqual(vm.expression_backend, 'legacy')
        self.assertNotIn('eval_node', vm.__dict__)
        self.assertIs(vm.eval_node.__func__, runtime.VM.eval_node)
        self.assertEqual(vm.eval('1+2'), 3)

    def test_default_does_not_poll_custom_backend_getattribute(self):
        class Custom(runtime.VM):
            def __getattribute__(self, name):
                if name == 'expression_backend':
                    raise AssertionError('backend polled after construction')
                return super().__getattribute__(name)
        vm = Custom.__new__(Custom)
        self.assertEqual(vm.eval_node(('lit', 7)), 7)

    def test_explicit_and_environment_selection_and_override(self):
        with patch.dict(os.environ, {'PYEMUERA_EXPRESSION_BACKEND':'closures'}):
            closure = self.make()
            legacy = self.make(expression_backend='legacy')
        self.assertEqual(closure.eval_node.__func__.__module__, 'pyemuera.closure_entry')
        self.assertNotIn('eval_node', legacy.__dict__)
        self.assertEqual(closure.eval('7+9'), 16)
        self.assertIsNotNone(closure._closure_plans)

    def test_invalid_environment_and_explicit_backend_fail_at_construction(self):
        with patch.dict(os.environ, {'PYEMUERA_EXPRESSION_BACKEND':'invalid'}):
            with self.assertRaisesRegex(ValueError, 'Unknown expression evaluator backend'):
                self.make()
            self.assertEqual(self.make(expression_backend='legacy').eval('1'), 1)
        with self.assertRaisesRegex(ValueError, 'Unknown expression evaluator backend'):
            self.make(expression_backend='invalid')

    def test_later_field_assignment_and_deletion_never_select(self):
        for initial in ('legacy', 'closures'):
            vm = self.make(expression_backend=initial)
            entry = vm.eval_node.__func__
            for value in ('closures', 'legacy', 'invalid', None, object()):
                vm.expression_backend = value
                self.assertIs(vm.eval_node.__func__, entry)
                self.assertEqual(vm.eval('2+3'), 5)
            del vm.expression_backend
            self.assertIs(vm.eval_node.__func__, entry)
            self.assertEqual(vm.eval('2+3'), 5)
        # This is an explicitly authorized host selection contract change.

    def test_bare_new_with_field_stays_default_legacy(self):
        vm = runtime.VM.__new__(runtime.VM)
        vm.expression_backend = 'closures'
        self.assertNotIn('eval_node', vm.__dict__)
        self.assertEqual(vm.eval_node(('binary','+',('lit',2),('lit',5))), 7)
        self.assertNotIn('_closure_plans', vm.__dict__)

    def test_new_fixture_runs_real_constructor_and_selects_closures(self):
        vm = construct_vm(runtime.VM, 'closures')
        self.assertEqual(vm.eval_node.__func__.__module__, 'pyemuera.closure_entry')
        self.assertEqual(vm.eval_node(('binary','+',('lit',3),('lit',4))), 7)
        self.assertGreater(vm._closure_plans.misses, 0)

    def test_runtime_global_hook_remains_live_in_both_entries(self):
        for backend in ('legacy', 'legacy'):
            vm = self.make(expression_backend=backend)
            node = expr.parse('3+4')
            calls = []
            def hook(node, owner):
                calls.append((node, owner))
                return 91
            with patch.object(runtime, 'evaluate', hook):
                self.assertEqual(vm.eval_node(node), 91)
            self.assertEqual(calls, [(node, vm)])
            self.assertEqual(vm.eval_node(node), 7)

    def test_default_instance_and_class_hooks_remain_live(self):
        vm = self.make(expression_backend='legacy')
        vm.eval_node = lambda node: 78
        self.assertEqual(vm.eval('1'), 78)
        del vm.eval_node
        self.assertEqual(vm.eval('1'), 1)
        with patch.object(runtime.VM, 'eval_node', lambda self,node: 79):
            self.assertEqual(vm.eval('1'), 79)
        self.assertEqual(vm.eval('1'), 1)

    def test_custom_legacy_subclass_super_chain_stays_live(self):
        events = []
        class Custom(runtime.VM):
            def eval_node(self, node):
                events.append(node)
                return super().eval_node(node) + 1
        vm = construct_vm(Custom, 'legacy', expected_entry_module=__name__)
        self.assertNotIn('eval_node', vm.__dict__)
        self.assertEqual(vm.eval_node(('lit', 3)), 4)
        self.assertEqual(events, [('lit', 3)])

    def test_existing_custom_entry_not_hidden_at_closure_construction(self):
        class Custom(runtime.VM):
            def eval_node(self, node): return super().eval_node(node) + 2
        vm = construct_vm(Custom, 'closures', expected_entry_module=__name__)
        self.assertNotIn('eval_node', vm.__dict__)
        self.assertEqual(vm.eval_node(('lit', 3)), 5)

    def test_selected_entry_has_no_backend_flag_check(self):
        vm = self.make(expression_backend='closures')
        source = inspect.getsource(vm.eval_node.__func__)
        self.assertNotIn('expression_backend', source)
        self.assertNotIn('__mro__', source)
        self.assertNotIn('legacy', source)
        self.assertEqual(vm.eval('2+5'), 7)

    def test_experimental_module_import_is_not_in_default_runtime_imports(self):
        tree = ast.parse(inspect.getsource(runtime))
        eager = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any('closure' in ast.unparse(node) for node in eager))


if __name__ == '__main__': unittest.main()
