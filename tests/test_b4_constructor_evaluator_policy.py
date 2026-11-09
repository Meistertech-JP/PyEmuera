"""Experimental evaluator policy is chosen once; helper semantics stay live."""
import ast
import inspect
from unittest.mock import patch
from pyemuera import expr, runtime, closure_entry, closure_evaluator
from test_core import Harness


class ConstructorEvaluatorPolicy(Harness):
    def test_preinstalled_runtime_evaluator_selects_live_legacy_fallback(self):
        calls=[]
        def hook(node,vm): calls.append(node); return 71
        with patch.object(runtime,'evaluate',hook):
            vm=self.make(expression_backend='closures')
            self.assertNotIn('eval_node',vm.__dict__)
            self.assertEqual(vm.eval('1+2'),71)
        self.assertEqual(len(calls),1)
        self.assertNotIn('eval_node',vm.__dict__)
        self.assertEqual(vm.eval('1+2'),3)

    def test_preinstalled_recursive_evaluator_selects_live_legacy_fallback(self):
        def hook(node,vm): return 9
        with patch.object(expr,'evaluate',hook):
            vm=self.make(expression_backend='closures')
            self.assertNotIn('eval_node',vm.__dict__)
            self.assertEqual(vm.eval('1+2'),18)
        self.assertEqual(vm.eval('1+2'),3)
        self.assertNotIn('eval_node',vm.__dict__)

    def test_selected_closures_ignore_late_both_evaluator_replacements_cold_and_warm(self):
        vm=self.make(expression_backend='closures')
        entry=vm.eval_node
        with patch.object(runtime,'evaluate',lambda node,vm:71), \
             patch.object(expr,'evaluate',lambda node,vm:99):
            for _ in range(2):
                self.assertIs(vm.eval_node,entry)
                self.assertEqual(vm.eval('1+2'),3)
        self.assertEqual(vm.eval('1+2'),3)

    def test_depth_and_malformed_container_fallback_do_not_reenter_late_evaluator(self):
        vm=self.make(expression_backend='closures')
        node=('lit',3)
        for _ in range(70): node=('binary','+',node,('lit',0))
        with patch.object(expr,'evaluate',lambda node,vm:99), \
             patch.object(runtime,'evaluate',lambda node,vm:71):
            self.assertEqual(vm.eval_node(node),3)
            # Lists remain supported through the old-dispatch-shaped fallback.
            self.assertEqual(vm.eval_node(['binary','+',('lit',1),('lit',2)]),3)

    def test_other_arithmetic_helpers_are_live_after_selection(self):
        vm=self.make(expression_backend='closures')
        seen=[]
        def integer(value): seen.append(value); return 11
        with patch.object(expr,'integer',integer):
            self.assertEqual(vm.eval_node(('unary','+',('lit',1))),11)
        self.assertEqual(seen,[1])
        with patch.object(expr,'apply_binary',lambda op,a,b:23):
            self.assertEqual(vm.eval_node(('binary','+',('lit',1),('lit',2))),23)
            self.assertEqual(vm.eval_node(['binary','+',('lit',1),('lit',2)]),23)

    def test_legacy_runtime_and_recursive_evaluator_replacement_remain_live(self):
        vm=self.make(expression_backend='legacy')
        with patch.object(runtime,'evaluate',lambda node,vm:71): self.assertEqual(vm.eval('1+2'),71)
        with patch.object(expr,'evaluate',lambda node,vm:9): self.assertEqual(vm.eval('1+2'),18)
        self.assertEqual(vm.eval('1+2'),3)

    def test_default_public_body_remains_exact_direct_global_call(self):
        function=ast.parse(inspect.getsource(runtime.VM.eval_node).strip()).body[0]
        wanted=ast.parse('return evaluate(node, self)').body
        self.assertEqual([ast.dump(n) for n in function.body],[ast.dump(n) for n in wanted])

    def test_experimental_entries_have_no_evaluator_identity_polling(self):
        for module in (closure_entry,closure_evaluator):
            tree=ast.parse(inspect.getsource(module))
            accesses=[n for n in ast.walk(tree) if isinstance(n,ast.Attribute) and n.attr=='evaluate']
            self.assertEqual(accesses,[])


if __name__=='__main__':
    import unittest
    unittest.main()
