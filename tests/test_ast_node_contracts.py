"""Tuple compatibility and observable evaluation contracts for typed increments."""
import unittest
from pyemuera.expr import parse, evaluate
from pyemuera.ast_nodes import IncrementNode
from test_core import Harness


class NodeLayout(unittest.TestCase):
    def test_parser_prefix_layout_and_names(self):
        node = parse('++A')
        self.assertIs(type(node), tuple)
        self.assertEqual(node, ('inc', ('var', 'A', ()), 1, False))
        _, target, delta, postfix = node
        self.assertEqual(target, ('var', 'A', ()))
        self.assertEqual(delta, 1)
        self.assertFalse(postfix)

    def test_parser_postfix_layout(self):
        node = parse('A--')
        self.assertIs(type(node), tuple)
        self.assertEqual(tuple(node), ('inc', ('var', 'A', ()), -1, True))

    def test_hash_and_cache_compatibility(self):
        node = parse('A++')
        self.assertEqual(hash(node), hash(tuple(node)))
        self.assertIs(parse('A++'), node)
        self.assertEqual({node: 1}[tuple(node)], 1)

    def test_immutable_and_no_instance_dictionary(self):
        node = parse('A++')
        self.assertFalse(hasattr(node, '__dict__'))
        with self.assertRaises(TypeError):
            node[2] = 3


class IncrementEvaluation(Harness):
    def test_legacy_tuple_remains_accepted(self):
        vm = self.make()
        vm.set('A', 4)
        self.assertEqual(evaluate(('inc', ('var', 'A', ()), 1, True), vm), 4)
        self.assertEqual(vm.get('A'), 5)

    def test_prefix_and_postfix_sequence(self):
        vm = self.make()
        self.assertEqual(vm.eval('++A + A++'), 2)
        self.assertEqual(vm.get('A'), 2)

    def test_minus_still_evaluates_operand_twice(self):
        vm = self.make()
        self.assertEqual(vm.eval('-A++'), -1)
        self.assertEqual(vm.get('A'), 2)

    def test_division_still_evaluates_rhs_before_lhs(self):
        vm = self.make()
        vm.set('A', 1)
        self.assertEqual(vm.eval('A++ / A++'), 2)
        self.assertEqual(vm.get('A'), 3)

    def test_zero_divisor_keeps_only_rhs_write(self):
        vm = self.make()
        with self.assertRaises(Exception) as caught:
            vm.eval('A++ / A++')
        self.assertEqual(caught.exception.code, 'E_ARITH')
        self.assertEqual(vm.get('A'), 1)

    def test_short_circuit_does_not_increment(self):
        vm = self.make()
        self.assertEqual(vm.eval('0 && A++'), 0)
        self.assertEqual(vm.get('A'), 0)

    def test_int64_wrap(self):
        vm = self.make()
        vm.set('A', (1 << 63) - 1)
        self.assertEqual(vm.eval('++A'), -(1 << 63))

    def test_index_side_effect_precedes_value_write(self):
        vm = self.make()
        vm.set('B', 0)
        self.assertEqual(vm.eval('(A:(B++))++'), 0)
        self.assertEqual(vm.get('B'), 1)
        self.assertEqual(vm.get('A:0'), 1)
