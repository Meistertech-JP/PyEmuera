"""Bounded helper-fetch contracts for legacy and closure expression backends.

Portable to work/tests: requires only pyemuera on sys.path, not test_core.
External invocation from work (PowerShell):
  $env:PYTHONPATH='.'
  python -B -m unittest discover -s ../evidence/closure-evaluator-audit-25 -p test_b4_closure_helper_order.py -v

Every backend gets fresh VM, hooks, exception objects and ordered event state.
The legacy oracle is the original evaluate function, not a closure plan.
"""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera import expr, runtime
from construction_fixture import construct_vm
from pyemuera.closure_evaluator import ClosurePlans


BASE = expr._BASE_EVALUATE
INTEGER = expr.integer
I64 = expr.i64
APPLY = expr.apply_binary


def var(name):
    return ('var', name, ())


class ClosureHelperOrder(unittest.TestCase):
    def pair(self, setup, expected, expected_events, raises=False, backends=('legacy','closures')):
        """setup(events) returns node, VM, and an optional exact exception."""
        outcomes = []
        for backend in backends:
            with self.subTest(backend=backend), ExitStack() as stack:
                for name, value in (('evaluate', BASE), ('integer', INTEGER),
                                    ('i64', I64), ('apply_binary', APPLY)):
                    stack.enter_context(patch.object(expr, name, value))
                stack.enter_context(patch.object(runtime, 'evaluate', BASE))
                events = []
                with patch.object(self, 'vm', lambda: construct_vm(runtime.VM, backend)):
                    node, vm, failure = setup(events)
                # Warm structural binding must itself cause no fixture effects.
                vm._closure_plans = ClosurePlans()
                if backend == 'closures':
                    before = list(events)
                    vm._closure_plans.plan(node)
                    self.assertEqual(events, before)
                if raises:
                    with self.assertRaises(type(failure)) as caught:
                        vm.eval_node(node)
                    self.assertIs(caught.exception, failure)
                    result = (type(failure).__name__, str(failure))
                else:
                    result = vm.eval_node(node)
                self.assertEqual(result, expected)
                self.assertEqual(events, expected_events)
                outcomes.append((result, list(events)))
        self.assertEqual(outcomes[0], outcomes[1])

    @staticmethod
    def vm():
        return runtime.VM.__new__(runtime.VM)

    def test_ternary_captures_outer_evaluator_before_condition(self):
        for recursive in (False, True):
            for initial, replacement in (('base', 'B'), ('A', 'B'),
                                         ('A', 'base'), ('A', 'A')):
                with self.subTest(recursive=recursive, initial=initial,
                                  replacement=replacement):
                    def setup(events):
                        vm = self.vm()
                        def a(node, vm):
                            events.append(('A', node[0]))
                            return 100 if node == ('lit', 7) else BASE(node, vm)
                        def b(node, vm):
                            events.append(('B', node[0]))
                            return 700 if node == ('lit', 7) else BASE(node, vm)
                        hooks = {'base': BASE, 'A': a, 'B': b}
                        def read(node):
                            events.append('condition')
                            expr.evaluate = hooks[replacement]
                            return 1
                        vm.read_node = read
                        expr.evaluate = hooks[initial]
                        node = ('ternary', var('C'), ('lit', 7), ('lit', 9))
                        if recursive:
                            node = ('binary', '+', node, ('lit', 1))
                        return node, vm, None
                    events = []
                    if recursive and initial == 'A':
                        events.append(('A', 'ternary'))
                    if initial == 'A':
                        events.append(('A', 'var'))
                    events.append('condition')
                    if initial == 'A':
                        events.append(('A', 'lit'))
                    if recursive and replacement != 'base':
                        events.append((replacement, 'lit'))
                    self.pair(setup, (100 if initial == 'A' else 7)
                              + int(recursive), events, backends=('legacy','legacy'))

    def test_ternary_integer_subclass_truth_is_tested_once(self):
        for recursive in (False, True):
            with self.subTest(recursive=recursive):
                def setup(events):
                    class FlippingInt(int):
                        def __bool__(self):
                            events.append('truth')
                            return len(events) % 2 == 1
                    vm = self.vm()
                    vm.read_node = lambda node: FlippingInt(1)
                    node = ('ternary', var('C'), ('lit', 7), ('lit', 9))
                    if recursive:
                        node = ('binary', '+', node, ('lit', 1))
                    return node, vm, None
                self.pair(setup, 7 + int(recursive), ['truth'])

    def test_selected_entry_bypasses_new_hook_but_descendants_are_live(self):
        for recursive in (False, True):
            with self.subTest(recursive=recursive):
                def setup(events):
                    vm = self.vm()
                    def hook(node, vm):
                        events.append(('hook', node[0]))
                        return 40 if node == ('lit', 7) else BASE(node, vm)
                    def read(node):
                        events.append('condition')
                        expr.evaluate = hook
                        return 1
                    vm.read_node = read
                    selected = ('binary', '+', ('lit', 7), ('lit', 2))
                    node = ('ternary', var('C'), selected, ('lit', 9))
                    if recursive:
                        node = ('binary', '+', node, ('lit', 1))
                    return node, vm, None
                self.pair(setup, 42 + int(recursive),
                          ['condition'] + [('hook', 'lit')] * (2 + int(recursive)), backends=('legacy','legacy'))

    def test_binary_fetches_apply_after_lhs_before_rhs(self):
        def setup(events):
            vm = self.vm()
            def a(op, left, right):
                events.append(('apply-A', op, left, right))
                return 23
            def b(*args):
                events.append('apply-B')
                return -1
            def read(node):
                events.append(node[1])
                expr.apply_binary = a if node[1] == 'L' else b
                return 2 if node[1] == 'L' else 3
            vm.read_node = read
            return ('binary', '+', var('L'), var('R')), vm, None
        self.pair(setup, 23, ['L', 'R', ('apply-A', '+', 2, 3)])

    def test_division_modulo_fetch_integer_before_rhs_apply_before_lhs(self):
        for op in ('/', '%'):
            with self.subTest(op=op):
                def setup(events):
                    vm = self.vm()
                    def integer_a(value):
                        events.append(('integer-A', value))
                        return value
                    def integer_b(value):
                        events.append('integer-B')
                        return 0
                    def apply_a(operator, left, right):
                        events.append(('apply-A', operator, left, right))
                        return 71
                    def apply_b(*args):
                        events.append('apply-B')
                        return -1
                    def read(node):
                        events.append(node[1])
                        if node[1] == 'R':
                            expr.integer = integer_b
                            expr.apply_binary = apply_a
                            return 2
                        expr.apply_binary = apply_b
                        return 8
                    expr.integer = integer_a
                    vm.read_node = read
                    return ('binary', op, var('L'), var('R')), vm, None
                self.pair(setup, 71, ['R', ('integer-A', 2), 'L',
                                      ('apply-A', op, 8, 2)])

    def test_ternary_fetches_integer_before_condition(self):
        def setup(events):
            vm = self.vm()
            def integer_a(value):
                events.append(('integer-A', value))
                return 1
            def integer_b(value):
                events.append('integer-B')
                return 0
            def read(node):
                events.append('condition')
                expr.integer = integer_b
                return 4
            expr.integer = integer_a
            vm.read_node = read
            return ('ternary', var('C'), ('lit', 7), ('lit', 9)), vm, None
        self.pair(setup, 7, ['condition', ('integer-A', 4)])

    def test_unary_minus_fetches_helpers_before_each_operand_evaluation(self):
        def setup(events):
            vm = self.vm()
            reads = []
            def old_integer(value):
                events.append(('integer-old', value))
                return value
            def new_integer(value):
                events.append(('integer-new', value))
                return value
            def late_integer(value):
                events.append('integer-too-late')
                return 99
            def old_i64(value):
                events.append(('i64-selected', value))
                return value
            def late_i64(value):
                events.append('i64-too-late')
                return 99
            def read(node):
                reads.append(None)
                events.append(('read', len(reads)))
                if len(reads) == 1:
                    expr.integer = new_integer
                    expr.i64 = old_i64
                    return 3
                expr.integer = late_integer
                expr.i64 = late_i64
                return 5
            expr.integer = old_integer
            vm.read_node = read
            return ('unary', '-', var('A')), vm, None
        self.pair(setup, -5, [('read', 1), ('integer-old', 3),
                             ('read', 2), ('integer-new', 5),
                             ('i64-selected', -5)])

    def test_minvalue_warning_precedes_second_helper_fetch(self):
        def setup(events):
            vm = self.vm()
            def replacement(value):
                events.append(('i64-warning', value))
                return I64(value)
            def write(message, newline):
                events.append(('warning', newline))
                expr.i64 = replacement
            vm.console = SimpleNamespace(write=write)
            def read(node):
                events.append('read')
                return -(1 << 63)
            vm.read_node = read
            return ('unary', '-', var('A')), vm, None
        self.pair(setup, -(1 << 63), ['read', ('warning', True), 'read',
                                     ('i64-warning', 1 << 63)])

    def test_increment_fetches_integer_before_get_i64_before_add_then_set(self):
        for postfix in (False, True):
            with self.subTest(postfix=postfix):
                def setup(events):
                    vm = self.vm()
                    def integer_a(value):
                        events.append('integer-A')
                        return value
                    def integer_b(value):
                        events.append('integer-too-late')
                        return 90
                    def i64_a(value):
                        events.append(('i64-A', value))
                        return value
                    def i64_b(value):
                        events.append('i64-too-late')
                        return 90
                    class Number(int):
                        def __add__(self, delta):
                            events.append(('add', delta))
                            expr.i64 = i64_b
                            return int(self) + delta
                    def get():
                        events.append('get')
                        expr.integer = integer_b
                        expr.i64 = i64_a
                        return Number(4)
                    def set_value(value):
                        events.append(('set', value))
                    ref = SimpleNamespace(get=get, set=set_value)
                    def resolve(node):
                        events.append('ref')
                        return ref
                    expr.integer = integer_a
                    vm.ref_node = resolve
                    return ('inc', var('A'), 1, postfix), vm, None
                self.pair(setup, 4 if postfix else 5,
                          ['ref', 'get', 'integer-A', ('add', 1),
                           ('i64-A', 5), ('set', 5)])

    def test_captured_binary_helper_exception_identity_after_rhs_effect(self):
        def setup(events):
            vm = self.vm()
            failure = RuntimeError('captured helper failure')
            def selected(*args):
                events.append('selected-raises')
                raise failure
            def late(*args):
                events.append('wrong-helper')
                return 0
            def read(node):
                events.append(node[1])
                expr.apply_binary = selected if node[1] == 'L' else late
                return 1
            vm.read_node = read
            return ('binary', '+', var('L'), var('R')), vm, failure
        self.pair(setup, ('RuntimeError', 'captured helper failure'),
                  ['L', 'R', 'selected-raises'], raises=True)


if __name__ == '__main__':
    unittest.main()
