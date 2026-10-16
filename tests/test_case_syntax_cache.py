"""Cached syntax must preserve runtime evaluation and caller list ownership."""
import unittest
from test_core import Harness
from pyemuera.text import split_case_args, _case_arguments
from pyemuera.errors import EraError


class SplitContracts(unittest.TestCase):
    def test_caller_mutation_cannot_change_later_result(self):
        parts = split_case_args('1, 2,')
        parts[0] = '99'
        self.assertEqual(split_case_args('1, 2,'), ['1', '2'])

    def test_quoted_commas_and_form_remain_intact(self):
        self.assertEqual(split_case_args('"a,b", @"{1,2}"'), ['"a,b"', '@"{1,2}"'])

    def test_interior_omission_still_fails(self):
        for text in ('', ',1', '1,,2', ','):
            with self.assertRaises(EraError):split_case_args(text)

    def test_cache_is_bounded(self):
        self.assertEqual(_case_arguments.cache_info().maxsize, 8192)


class EvaluationContracts(Harness):
    def test_variable_values_are_read_on_every_execution(self):
        v = self.make();v.set('A', 1)
        self.assertTrue(v._case(1, 'A'))
        v.set('A', 2)
        self.assertFalse(v._case(1, 'A'))

    def test_later_condition_is_not_evaluated_after_match(self):
        v = self.make()
        before = v.rng.getstate()
        self.assertTrue(v._case(1, '1, RAND:100'))
        self.assertEqual(v.rng.getstate(), before)

    def test_rng_is_consumed_on_each_case_evaluation(self):
        v = self.make();before = v.rng.getstate()
        v._case(0, 'RAND:100');one = v.rng.getstate()
        v._case(0, 'RAND:100');two = v.rng.getstate()
        self.assertNotEqual(before, one);self.assertNotEqual(one, two)

    def test_range_upper_bound_remains_lazy(self):
        v = self.make()
        self.assertFalse(v._case(1, '2 TO 1/0'))
        with self.assertRaises(EraError):v._case(2, '2 TO 1/0')

    def test_runtime_type_error_still_occurs(self):
        v = self.make()
        with self.assertRaises(EraError) as exc:v._case(1, '"1"')
        self.assertEqual(exc.exception.code, 'E_TYPE')
