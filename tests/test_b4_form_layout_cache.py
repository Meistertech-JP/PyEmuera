"""Lexical FORM reuse must not retain values or move parse/evaluation boundaries."""
import gc
import unittest
import weakref
from types import SimpleNamespace
from unittest.mock import patch

from test_core import Harness
from pyemuera import formatting as form
from pyemuera.errors import EraError
from pyemuera.runtime import Frame


class Adapter:
    """No frames: lexical and runtime failures must remain interleaved."""

    def __init__(self, values):
        self.values = values
        self.events = []
        self.console = SimpleNamespace(warning=self.warning)

    def warning(self, key, message):
        self.events.append(('warning', key))

    def eval(self, expression):
        expression = expression.strip()
        self.events.append(('eval', expression))
        value = self.values[expression]
        return value() if callable(value) else value


class CacheTests(unittest.TestCase):
    def setUp(self):
        form._cached_placeholder_parts.cache_clear()

    def tearDown(self):
        form._cached_placeholder_parts.cache_clear()

    def test_warm_lexical_work_still_evaluates_value_then_width(self):
        vm = Adapter({'VALUE': 'a', 'WIDTH': 3})
        text = '%VALUE, WIDTH, LEFT%'
        with patch.object(form, '_end', wraps=form._end) as end, patch.object(
            form, 'split_args', wraps=form.split_args
        ) as split:
            self.assertEqual(form.render(text, vm), 'a  ')
            vm.values.update(VALUE='日本', WIDTH=6)
            self.assertEqual(form.render(text, vm), '日本  ')
            self.assertEqual((end.call_count, split.call_count), (1, 1))
        self.assertEqual(vm.events, [('eval', 'VALUE'), ('eval', 'WIDTH')] * 2)
        self.assertEqual(form._cached_placeholder_parts.cache_info().hits, 1)

    def test_value_type_error_precedes_width_and_later_malformed_placeholder(self):
        text = '%VALUE, WIDTH%{'
        vm = Adapter({'VALUE': 1, 'WIDTH': 2})
        for _ in range(2):
            vm.events.clear()
            with self.assertRaises(EraError) as caught:
                form.render(text, vm)
            self.assertEqual(caught.exception.code, 'E_TYPE')
            self.assertEqual(vm.events, [('eval', 'VALUE')])
        self.assertEqual(form._cached_placeholder_parts.cache_info().currsize, 1)

    def test_width_is_live_and_fails_after_value_effect_on_cache_hit(self):
        effects = []
        vm = Adapter({'VALUE': lambda: effects.append('value') or 'x', 'WIDTH': 2})
        text = '%VALUE, WIDTH%'
        self.assertEqual(form.render(text, vm), ' x')
        for bad_width, code in [('2', 'E_TYPE'), (1_000_001, 'E_LIMIT')]:
            vm.values['WIDTH'] = bad_width
            vm.events.clear()
            with self.assertRaises(EraError) as caught:
                form.render(text, vm)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(vm.events, [('eval', 'VALUE'), ('eval', 'WIDTH')])
        self.assertEqual(effects, ['value'] * 3)

    def test_chosen_branch_and_condition_remain_live(self):
        vm = Adapter({'C': 1, 'YES': 5, 'NO': 9})
        text = r'\@C?{YES}#{NO}\@'
        self.assertEqual(form.render(text, vm), '5')
        vm.values.update(C=0, NO=13)
        self.assertEqual(form.render(text, vm), '13')
        vm.values.update(C=1, YES=17)
        self.assertEqual(form.render(text, vm), '17')
        self.assertEqual(vm.events, [('eval', 'C'), ('eval', 'YES'),
                                     ('eval', 'C'), ('eval', 'NO'),
                                     ('eval', 'C'), ('eval', 'YES')])

    def test_missing_false_warning_stays_between_earlier_effect_and_condition(self):
        vm = Adapter({'FIRST': 7, 'C': 0})
        text = r'{FIRST}\@C?yes\@'
        expected = [('eval', 'FIRST'), ('warning', 'conditional-missing-false'),
                    ('eval', 'C')]
        for _ in range(2):
            vm.events.clear()
            self.assertEqual(form.render(text, vm), '7')
            self.assertEqual(vm.events, expected)
        def fail():
            raise EraError('first operand failed', code='E_ARITH')
        vm.values['FIRST'] = fail
        vm.events.clear()
        with self.assertRaises(EraError):
            form.render(text, vm)
        self.assertEqual(vm.events, [('eval', 'FIRST')])

    def test_trim_applies_to_literal_edges_not_live_expression_values(self):
        vm = Adapter({'C': 1, 'S': ' value '})
        text = r'\@C? \t%S%\t #bad\@'
        self.assertEqual(form.render(text, vm), ' value ')
        vm.values['S'] = ' next '
        self.assertEqual(form.render(text, vm), ' next ')
        for _ in range(2):
            self.assertEqual(form.render(' \t%S%\t ', vm, trim_edges=True), ' next ')
            self.assertEqual(form.render('　%S%　', vm, trim_edges=True), '　 next 　')

    def test_nested_quoted_arguments_and_escapes_keep_their_boundaries(self):
        expression = 'F("a,b", @"n={X}")'
        vm = Adapter({expression: 'ok', 'W(1,2)': 4})
        text = r'\{literal\}%' + expression + ',W(1,2),LEFT%'
        for _ in range(2):
            self.assertEqual(form.render(text, vm), '{literal}ok  ')

    def test_nesting_and_output_limits_still_apply_after_lexical_warmup(self):
        vm = Adapter({'C': 1, 'N': 3})
        text = r'\@C?{N}#no\@'
        self.assertEqual(form.render(text, vm), '3')
        vm.events.clear()
        with self.assertRaises(EraError) as caught:
            form.render(text, vm, level=32)
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_LIMIT', 'FORM nesting limit'))
        self.assertEqual(vm.events, [('eval', 'C')])
        vm = Adapter({'S': 'short', 'N': 1})
        text = '%S%{N}'
        self.assertEqual(form.render(text, vm), 'short1')
        vm.values['S'] = 'x' * 10_000_000
        vm.events.clear()
        with self.assertRaises(EraError) as caught:
            form.render(text, vm)
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_LIMIT', 'FORM output limit'))
        self.assertEqual(vm.events, [('eval', 'S'), ('eval', 'N')])

    def test_cache_is_bounded_immutable_and_does_not_retain_vm(self):
        vm = Adapter({'N': 7})
        ref = weakref.ref(vm)
        form.render('{N}', vm)
        del vm
        gc.collect()
        self.assertIsNone(ref())
        result = form._placeholder_parts('{N, 4, LEFT}', 1, '}')
        self.assertEqual(result, (11, ('N', '4', 'LEFT')))
        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[1], tuple)
        vm = Adapter({'N': 1})
        for i in range(form._FORM_PARTS_CACHE_SIZE + 1):
            form.render(str(i) + '{N}', vm)
        info = form._cached_placeholder_parts.cache_info()
        self.assertEqual((info.maxsize, info.currsize),
                         (form._FORM_PARTS_CACHE_SIZE, form._FORM_PARTS_CACHE_SIZE))

    def test_size_boundary_and_str_subclasses_bypass_cache(self):
        vm = Adapter({'N': 1})
        text = 'x' * (form._FORM_PARTS_MAX_TEXT - 3) + '{N}'
        form.render(text, vm)
        info = form._cached_placeholder_parts.cache_info()
        self.assertEqual(info.currsize, 1)
        for _ in range(2):
            form.render('x' + text, vm)
        self.assertEqual(form._cached_placeholder_parts.cache_info(), info)
        class Text(str):
            __hash__ = None
        for _ in range(2):
            self.assertEqual(form.render(Text('{N}'), vm), '1')
            self.assertEqual(list(form.form_components(Text('{N}'))),
                             [('N', 'Int64', '{')])
        self.assertEqual(form._cached_placeholder_parts.cache_info(), info)


class LiveVMTests(Harness):
    def setUp(self):
        form._cached_placeholder_parts.cache_clear()

    def tearDown(self):
        form._cached_placeholder_parts.cache_clear()

    def test_no_frame_late_parse_errors_preserve_increment_and_rng_order(self):
        vm = self.make()
        self.assertFalse(vm.frames)
        for suffix, code in [('{1', 'E_FORMAT'), ('{B]}', 'E_SYNTAX')]:
            form._cached_placeholder_parts.cache_clear()
            text = '{A:0++}{RAND:1000}' + suffix
            vm.set('A:0', 0)
            vm.rng.seed(123)
            expected_states = []
            for _ in range(2):
                vm.eval('RAND:1000')
                expected_states.append(vm.rng.getstate())
            vm.rng.seed(123)
            for i in range(2):
                with self.assertRaises(EraError) as caught:
                    vm.format(text)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(vm.get('A:0'), i + 1)
                self.assertEqual(vm.rng.getstate(), expected_states[i])
            info = form._cached_placeholder_parts.cache_info()
            self.assertEqual((info.currsize, info.hits, info.misses), (2, 2, 4))

    def test_live_values_widths_and_random_stream_across_cache_hits(self):
        vm = self.make()
        vm.set('A:0', 7)
        vm.set('B:0', 3)
        text = '{A:0++,B:0++,LEFT}'
        self.assertEqual(vm.format(text), '7  ')
        self.assertEqual(vm.format(text), '8   ')
        self.assertEqual((vm.get('A:0'), vm.get('B:0')), (9, 5))
        vm.rng.seed(321)
        expected = [str(vm.eval('RAND:100000')) for _ in range(3)]
        vm.rng.seed(321)
        self.assertEqual([vm.format('{RAND:100000}') for _ in range(3)], expected)

    def test_real_unselected_branch_has_no_rng_or_increment_effects(self):
        vm = self.make()
        before = vm.rng.getstate()
        text = r'\@A?{RAND:1000}{++B}#{C:0++}\@'
        self.assertEqual(vm.format(text), '0')
        self.assertEqual(vm.format(text), '1')
        self.assertEqual((vm.get('B'), vm.get('C:0')), (0, 2))
        self.assertEqual(vm.rng.getstate(), before)

    def test_frame_type_validation_still_precedes_all_side_effects_when_warm(self):
        vm = self.make()
        text = '{A:0++}{RAND:1000}{STR}'
        # Successful lexical analysis is independent of semantic type validity.
        list(form.form_components(text))
        vm.frames.append(Frame(vm.function('MAIN'), {}))
        before = vm.rng.getstate()
        for _ in range(2):
            with self.assertRaises(EraError) as caught:
                vm.format(text)
            self.assertEqual(caught.exception.code, 'E_TYPE')
            self.assertEqual(vm.get('A:0'), 0)
            self.assertEqual(vm.rng.getstate(), before)
            self.assertNotIn((vm.frames[-1].function.uid, text), vm._form_type_cache)

    def test_frame_validation_catches_unchosen_bad_type_without_effect_or_warning(self):
        vm = self.make()
        text = r'{A:0++}\@1?{RAND:1000}#{STR}\@'
        list(form.form_components(text))
        vm.frames.append(Frame(vm.function('MAIN'), {}))
        before = vm.rng.getstate()
        with patch.object(vm.console, 'warning') as warning:
            with self.assertRaises(EraError) as caught:
                vm.format(text)
        self.assertEqual(caught.exception.code, 'E_TYPE')
        self.assertEqual(vm.get('A:0'), 0)
        self.assertEqual(vm.rng.getstate(), before)
        warning.assert_not_called()
