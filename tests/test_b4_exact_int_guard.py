"""Portable semantics for installed arithmetic with custom operators/helpers."""
import unittest
from unittest.mock import patch

from pyemuera import expr


class ExactIntGuardHooks(unittest.TestCase):
    def test_custom_operator_and_str_subclass_keep_original_comparison_precedence(self):
        for subclass in (False, True):
            events = []
            class Custom:
                def __eq__(self, other):
                    events.append(other)
                    return other in ('==', '+')
            class Text(str):
                def __eq__(self, other):
                    events.append(other)
                    return other in ('==', '+')
            op = Text('+') if subclass else Custom()
            self.assertEqual(expr.apply_binary(op, 2, 3), 0)
            self.assertEqual(events, ['==', '=='])

    def test_custom_operator_exception_is_not_preempted_or_repeated(self):
        failure = ValueError('operator failed')
        events = []
        class Text(str):
            def __eq__(self, other):
                events.append(other)
                raise failure
        with self.assertRaises(ValueError) as caught:
            expr.apply_binary(Text('+'), 2, 3)
        self.assertIs(caught.exception, failure)
        self.assertEqual(events, ['=='])

    def test_integer_wrapper_observes_both_operands_exactly_once(self):
        original = expr.integer
        for op, expected in (('+', 5), ('-', -1), ('*', 6)):
            events = []
            def integer(value):
                events.append(value)
                return original(value)
            with patch.object(expr, 'integer', integer):
                self.assertEqual(expr.apply_binary(op, 2, 3), expected)
            self.assertEqual(events, [2, 3])

    def test_integer_failure_keeps_exception_identity_and_blocks_rhs_and_i64(self):
        failure = ValueError('integer hook failed')
        events = []
        def integer(value):
            events.append(('integer', value))
            raise failure
        def i64(value):
            self.fail('conversion must not run after integer failure')
        for op in ('+', '-', '*'):
            events.clear()
            with patch.object(expr, 'integer', integer), patch.object(expr, 'i64', i64):
                with self.assertRaises(ValueError) as caught:
                    expr.apply_binary(op, 2, 3)
            self.assertIs(caught.exception, failure)
            self.assertEqual(events, [('integer', 2)])

    def test_integer_hook_can_replace_i64_before_its_lookup(self):
        base_integer = expr.integer
        base_i64 = expr.i64
        for op, converted in (('+', 5), ('-', -1), ('*', 6)):
            events = []
            def late(value):
                events.append(('late-i64', value))
                return 42
            def early(value):
                self.fail('old i64 must not be captured before integer hooks')
            def integer(value):
                events.append(('integer', value))
                expr.i64 = late
                return base_integer(value)
            with patch.object(expr, 'integer', integer), patch.object(expr, 'i64', early):
                self.assertEqual(expr.apply_binary(op, 2, 3), 42)
            self.assertIs(expr.i64, base_i64)
            self.assertEqual(events, [('integer', 2), ('integer', 3), ('late-i64', converted)])

    def test_integer_hook_replacement_between_operands_is_live(self):
        events = []
        def second(value):
            events.append(('second', value))
            return value + 10
        def first(value):
            events.append(('first', value))
            expr.integer = second
            return value
        with patch.object(expr, 'integer', first):
            self.assertEqual(expr.apply_binary('+', 2, 3), 15)
        self.assertEqual(events, [('first', 2), ('second', 3)])

    def test_live_i64_failure_identity_is_preserved_on_default_integer_path(self):
        failure = ValueError('i64 failed')
        events = []
        def i64(value):
            events.append(value)
            raise failure
        for op, expected in (('+', 5), ('-', -1), ('*', 6)):
            events.clear()
            with patch.object(expr, 'i64', i64):
                with self.assertRaises(ValueError) as caught:
                    expr.apply_binary(op, 2, 3)
            self.assertIs(caught.exception, failure)
            self.assertEqual(events, [expected])

    def test_restored_integer_and_replaced_i64_remain_live(self):
        original_integer = expr.integer
        events = []
        def integer(value):
            events.append(value)
            return original_integer(value)
        with patch.object(expr, 'integer', integer):
            self.assertEqual(expr.apply_binary('+', 2, 3), 5)
        self.assertIs(expr.integer, original_integer)
        with patch.object(expr, 'i64', lambda value: 99):
            self.assertEqual(expr.apply_binary('+', 2, 3), 99)
        self.assertEqual(expr.apply_binary('+', 2, 3), 5)
        self.assertEqual(events, [2, 3])


if __name__ == '__main__':
    unittest.main()
