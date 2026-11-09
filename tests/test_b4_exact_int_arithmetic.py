"""Semantic contracts for the installed expression arithmetic implementation.

Portable to work/tests: no proposal import, method replacement or algorithmic
reimplementation of Int64 wrapping. Expected results are language examples.
"""
import unittest

from pyemuera.errors import EraError
from pyemuera.expr import apply_binary
from pyemuera.random1824 import EngineRandom
from test_core import Harness


class ExactIntArithmetic(unittest.TestCase):
    def assert_error(self, op, a, b, code, message):
        with self.assertRaises(EraError) as caught:
            apply_binary(op, a, b)
        self.assertEqual((caught.exception.code, caught.exception.message), (code, message))

    def test_signed_boundaries_and_large_python_integers(self):
        cases = (
            ('+', 2, 3, 5), ('-', 2, 3, -1), ('*', -2, 3, -6),
            ('+', 9223372036854775807, 1, -9223372036854775808),
            ('-', -9223372036854775808, 1, 9223372036854775807),
            ('-', 9223372036854775807, -1, -9223372036854775808),
            ('*', -9223372036854775808, -1, -9223372036854775808),
            ('*', 9223372036854775807, 2, -2),
            ('+', 18446744073709551616, 7, 7),
            ('-', -18446744073709551616, 7, -7),
            ('*', 18446744073709551617, 3, 3),
            ('+', 1 << 256, 0, 0), ('*', -(1 << 256), 7, 0),
        )
        for op, a, b, expected in cases:
            with self.subTest(op=op, a=a, b=b):
                result = apply_binary(op, a, b)
                self.assertIs(type(result), int)
                self.assertEqual(result, expected)

    def test_bool_and_inherited_int_subclasses_remain_accepted(self):
        class Number(int):
            pass
        for a, b in ((True, True), (True, 1), (Number(1), 1), (1, Number(1))):
            for op, expected in (('+', 2), ('-', 0), ('*', 1)):
                with self.subTest(op=op, a_type=type(a), b_type=type(b)):
                    result = apply_binary(op, a, b)
                    self.assertIs(type(result), int)
                    self.assertEqual(result, expected)

    def test_int_subclass_operator_dispatch_is_preserved(self):
        events = []
        class Number(int):
            def __add__(self, other):
                events.append('add')
                return 41
            def __radd__(self, other):
                events.append('radd')
                return 42
            def __sub__(self, other):
                events.append('sub')
                return 43
            def __rsub__(self, other):
                events.append('rsub')
                return 44
            def __mul__(self, other):
                events.append('mul')
                return 45
            def __rmul__(self, other):
                events.append('rmul')
                return 46
        number = Number(2)
        for op, a, b, expected, event in (
            ('+', number, 3, 41, 'add'), ('+', 3, number, 42, 'radd'),
            ('-', number, 3, 43, 'sub'), ('-', 3, number, 44, 'rsub'),
            ('*', number, 3, 45, 'mul'), ('*', 3, number, 46, 'rmul'),
        ):
            with self.subTest(op=op, event=event):
                events.clear()
                self.assertEqual(apply_binary(op, a, b), expected)
                self.assertEqual(events, [event])

    def test_subclass_operator_result_keeps_i64_conversion(self):
        events = []
        class Result(int):
            def __int__(self):
                events.append('int')
                return 17
        class Number(int):
            def __add__(self, other):
                events.append('add')
                return Result(5)
        self.assertEqual(apply_binary('+', Number(2), 3), 17)
        self.assertEqual(events, ['add', 'int'])

    def test_strings_repetition_and_invalid_type_order(self):
        self.assertEqual(apply_binary('+', '日', '本'), '日本')
        self.assertEqual(apply_binary('*', 'ab', 3), 'ababab')
        self.assertEqual(apply_binary('*', 'ab', True), 'ab')
        self.assertEqual(apply_binary('*', 'ab', False), '')
        self.assert_error('*', 'ab', -1, 'E_LIMIT', 'Invalid string repetition')
        self.assert_error('*', 'ab', 5000001, 'E_LIMIT', 'Invalid string repetition')
        for op in ('+', '-', '*'):
            self.assert_error(op, None, 1.5, 'E_TYPE', 'Integer required, got NoneType')
            self.assert_error(op, 1, None, 'E_TYPE', 'Integer required, got NoneType')
            self.assert_error(op, 'x', 2.5, 'E_TYPE', 'Integer required, got str')
            self.assert_error(op, 2, 'x', 'E_TYPE', 'Integer required, got str')

    def test_unchanged_division_modulo_comparison_and_bitwise_contracts(self):
        for op, a, b, expected in (
            ('/', -7, 3, -2), ('%', -7, 3, -1),
            ('&', 6, 3, 2), ('|', 6, 3, 7), ('^', 6, 3, 5),
            ('<<', 1, 63, -9223372036854775808), ('>>', -8, 2, -2),
            ('==', 1, 1, 1), ('<', -1, 0, 1), ('&&', 1, 0, 0),
        ):
            self.assertEqual(apply_binary(op, a, b), expected)
        self.assert_error('/', 1, 0, 'E_ARITH', 'Division by zero')
        self.assert_error('/', -9223372036854775808, -1, 'E_ARITH', 'Int64 division overflow')
        self.assert_error('%', -9223372036854775808, -1, 'E_ARITH', 'Int64 division overflow')
        self.assert_error('==', True, 1, 'E_TYPE', 'Cannot compare a string and an integer')
        self.assert_error('unknown', 1, 2, 'E_RUNTIME', 'Unknown operator unknown')


class ArithmeticEffects(Harness):
    def test_arithmetic_evaluates_operands_once_left_to_right(self):
        vm = self.make()
        for op, expected in (('+', 5), ('-', -1), ('*', 6)):
            with self.subTest(op=op):
                vm.set('A', 2)
                self.assertEqual(vm.eval('(A++) ' + op + ' (A++)'), expected)
                self.assertEqual(vm.get('A'), 4)

    def test_rhs_effects_happen_before_arithmetic_type_error(self):
        vm = self.make()
        for op in ('+', '-', '*'):
            with self.subTest(op=op):
                vm.set('A', 2)
                with self.assertRaises(EraError) as caught:
                    vm.eval('1 ' + op + ' ("x" + TOSTR(A++))')
                self.assertEqual(caught.exception.code, 'E_TYPE')
                self.assertEqual(vm.get('A'), 3)

    def test_division_and_modulo_keep_rhs_first_and_zero_short_circuit(self):
        vm = self.make()
        for op in ('/', '%'):
            vm.set('A', 2)
            self.assertEqual(vm.eval('(A++) ' + op + ' (A++)'), 1)
            self.assertEqual(vm.get('A'), 4)
            vm.set('A', 2)
            with self.assertRaises(EraError) as caught:
                vm.eval('(A++) ' + op + ' 0')
            self.assertEqual(caught.exception.code, 'E_ARITH')
            self.assertEqual(vm.get('A'), 2)

    def test_rng_draw_order_and_lazy_branches(self):
        vm = self.make()
        for op in ('+', '-', '*'):
            with self.subTest(op=op):
                vm.rng.seed(123)
                reference = EngineRandom(123)
                left, right = reference.randrange(1000), reference.randrange(1000)
                expected = {'+': left + right, '-': left - right, '*': left * right}[op]
                self.assertEqual(vm.eval('RAND:1000 ' + op + ' RAND:1000'), expected)
                self.assertEqual(vm.rng.getstate(), reference.getstate())
                self.assertEqual(vm.eval('0 && RAND:1000'), 0)
                self.assertEqual(vm.eval('1 ? 7 # RAND:1000'), 7)
                self.assertEqual(vm.rng.getstate(), reference.getstate())


if __name__ == '__main__':
    unittest.main()
