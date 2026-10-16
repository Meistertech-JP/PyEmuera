"""Per-VM lifecycle contracts and the explicit-invalidation compatibility fix."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_core import Harness
from pyemuera.runtime import VM, Frame
from pyemuera.expr import parse
from pyemuera.errors import EraError
from pyemuera.registry import COMMAND_SPECS
from pyemuera import command_arguments, parameter_arguments, expression_arguments, formatting, resources1824
from pyemuera.internal_state import LAZY_VALIDATION_CACHE_ATTRIBUTES, SYNTAX_CACHE_ATTRIBUTES


class InternalStateR44(Harness):
    def prepared(self):
        vm = self.make('@MAIN\nRETURN\n@INTF\n#DIM DYNAMIC TEMP\nRETURN\n@STRF\n#DIMS DYNAMIC TEMP\nRETURN\n@ALIAS(DEST)\n#DIM REF DEST\nRETURN\n@SIDE\n#FUNCTION\nRESULT=77\nRESULTS \'= "side"\nRETURNF RAND(8)+A:0++\n')
        vm.frames = [Frame(vm.function('MAIN'), {})]
        return vm

    @staticmethod
    def validate(vm, name, bad=False):
        if name == '_r13_command_argument_cache':
            return command_arguments.lazy(vm, 'PRINTS', 'A' if bad else 'STR', COMMAND_SPECS['PRINTS'])
        if name == '_r33_character_argument_cache':
            return command_arguments.lazy(vm, 'ADDCHARA', '"x"' if bad else 'A:0++', COMMAND_SPECS['ADDCHARA'])
        if name == '_parameter_argument_cache':
            return parameter_arguments.lazy(vm, 'CUPCHECK', '"x"' if bad else 'A:0++,RAND(3)')
        if name == '_expression_argument_type_cache':
            return expression_arguments.validate_runtime(vm, 'STRLENS', (parse('A' if bad else 'STR'),))
        return formatting.validate_types('{STR}' if bad else '{A:0++}', vm)

    def test_initial_state_keeps_lazy_caches_absent(self):
        vm = self.prepared()
        self.assertTrue(all(not hasattr(vm, n) for n in LAZY_VALIDATION_CACHE_ATTRIBUTES))
        self.assertTrue(all(isinstance(getattr(vm, n), dict) for n in SYNTAX_CACHE_ATTRIBUTES))
        self.assertFalse(hasattr(vm, '_resource_catalog_checked'))

    def test_explicit_invalidation_preserves_absence_and_none(self):
        vm = self.prepared()
        vm._form_type_cache = None
        vm.invalidate_execution_cache()
        self.assertIsNone(vm._form_type_cache)
        self.assertTrue(all(not hasattr(vm, n) for n in LAZY_VALIDATION_CACHE_ATTRIBUTES if n != '_form_type_cache'))
        self.assertFalse(hasattr(vm, '_resource_catalog_checked'))

    def test_invalidation_clears_existing_content_in_place(self):
        vm = self.prepared()
        for n in LAZY_VALIDATION_CACHE_ATTRIBUTES:
            self.validate(vm, n)
        held = {n: getattr(vm, n) for n in LAZY_VALIDATION_CACHE_ATTRIBUTES + SYNTAX_CACHE_ATTRIBUTES}
        vm.invalidate_execution_cache()
        for n, cache in held.items():
            with self.subTest(name=n):
                self.assertIs(cache, getattr(vm, n))
                self.assertFalse(cache)
        for n in LAZY_VALIDATION_CACHE_ATTRIBUTES:
            self.validate(vm, n)

    def test_invalidation_read_and_clear_order_is_explicit(self):
        events = []
        class Cache:
            def __init__(self, name): self.name = name
            def clear(self): events.append(('clear', self.name))
        class Adapter(SimpleNamespace):
            def __getattribute__(self, name):
                if name in SYNTAX_CACHE_ATTRIBUTES + LAZY_VALIDATION_CACHE_ATTRIBUTES:
                    events.append(('read', name))
                return super().__getattribute__(name)
        names = SYNTAX_CACHE_ATTRIBUTES + LAZY_VALIDATION_CACHE_ATTRIBUTES
        adapter = Adapter(**{name: Cache(name) for name in names})
        VM.invalidate_execution_cache(adapter)
        self.assertEqual(events, [event for name in names for event in (('read', name), ('clear', name))])

    def test_syntax_clear_failure_does_not_touch_validation_sets(self):
        vm = self.prepared()
        vm._form_type_cache = {'kept'}
        class Broken:
            def clear(self): raise RuntimeError('clear failure')
        vm._assignment_cache = Broken()
        vm._expression_cache['old'] = ('lit', 1)
        vm._loop_cache['kept'] = ('A', '0', '1')
        with self.assertRaisesRegex(RuntimeError, 'clear failure'):
            vm.invalidate_execution_cache()
        self.assertEqual(vm._expression_cache, {})
        self.assertIn('kept', vm._loop_cache)
        self.assertEqual(vm._form_type_cache, {'kept'})

    def test_reset_restores_values_without_recreating_checks(self):
        vm = self.prepared()
        self.validate(vm, '_form_type_cache')
        held = vm._form_type_cache
        vm.set('A:0', 9)
        vm.reset()
        self.assertIs(held, vm._form_type_cache)
        self.assertEqual(vm.format('{A:0++}'), '0')
        self.assertEqual(vm.get('A:0'), 1)

    def test_save_load_restores_values_without_recreating_checks(self):
        vm = self.prepared()
        self.validate(vm, '_form_type_cache')
        held = vm._form_type_cache
        vm.set('FLAG:0', 12)
        vm.saves.write(0, 'cache-neutral')
        vm.set('FLAG:0', 99)
        self.assertEqual(vm.saves.load(0), 1)
        self.assertEqual(vm.get('FLAG:0'), 12)
        self.assertIs(held, vm._form_type_cache)

    def test_private_function_uid_protects_same_form_text(self):
        vm = self.prepared()
        vm.frames = []
        vm._new_frame(vm.function('INTF'))
        self.assertEqual(vm.format('{TEMP}'), '0')
        first = set(vm._form_type_cache)
        vm.clear_frames()
        vm._new_frame(vm.function('STRF'))
        with self.assertRaises(EraError) as caught:
            vm.format('{TEMP}')
        self.assertEqual(caught.exception.code, 'E_TYPE')
        self.assertEqual(vm._form_type_cache, first)

    def test_ref_binding_values_are_not_cached(self):
        vm = self.prepared()
        vm.frames = []
        vm.set('A:0', 3); vm.set('A:1', 4)
        vm.set('B:0', 7); vm.set('B:1', 8)
        result = []
        for argument in ('A', 'B', 'A'):
            vm._new_frame(vm.function('ALIAS'), [parse(argument)])
            result.append(vm.eval('SUMARRAY(DEST,0,2)'))
            vm.clear_frames()
        self.assertEqual(result, [7, 15, 7])
        self.assertEqual(len(vm._expression_argument_type_cache), 1)

    def test_ref_type_mismatch_precedes_cache_access(self):
        vm = self.prepared()
        vm.frames = []
        vm._expression_argument_type_cache = {('kept',)}
        before = vm.rng.getstate()
        with self.assertRaises(EraError) as caught:
            vm._new_frame(vm.function('ALIAS'), [parse('STR')])
        self.assertEqual(caught.exception.code, 'E_REFERENCE')
        self.assertEqual(vm.frames, [])
        self.assertEqual(vm._expression_argument_type_cache, {('kept',)})
        self.assertEqual(vm.rng.getstate(), before)

    def test_macro_rebuild_checks_types_before_operand_increment(self):
        vm = self.prepared()
        vm.program.macros['VAL'] = '1'
        self.assertEqual(vm.format('{A:0++}{VAL}'), '01')
        vm.set('A:0', 0)
        vm.set('RESULT', 21); vm.set('RESULTS', 'kept')
        before = vm.rng.getstate()
        vm.program.macros['VAL'] = '"x"'
        vm.invalidate_execution_cache()
        with self.assertRaises(EraError) as caught:
            vm.format('{A:0++}{VAL}')
        self.assertEqual((caught.exception.code, caught.exception.message), ('E_TYPE', '{}の中の式が数式ではありません'))
        self.assertEqual(vm.get('A:0'), 0)
        self.assertEqual(vm.get('RESULT'), 21)
        self.assertEqual(vm.get('RESULTS'), 'kept')
        self.assertEqual(vm.rng.getstate(), before)
        self.assertEqual(vm._form_type_cache, set())

    def test_macro_rebuild_precedes_rng_and_method_side_effects(self):
        vm = self.prepared()
        vm.program.macros['VAL'] = '1'
        vm.format('{SIDE()}{VAL}')
        vm.set('A:0', 0); vm.set('RESULT', 21); vm.set('RESULTS', 'kept')
        vm.rng.seed(123)
        before = vm.rng.getstate()
        vm.program.macros['VAL'] = '"x"'
        vm.invalidate_execution_cache()
        with self.assertRaises(EraError): vm.format('{SIDE()}{VAL}')
        self.assertEqual((vm.get('A:0'), vm.get('RESULT'), vm.get('RESULTS')), (0, 21, 'kept'))
        self.assertEqual(vm.rng.getstate(), before)

    def test_resource_none_is_a_completed_snapshot(self):
        vm = self.prepared()
        self.assertEqual(resources1824.function(vm, 'SPRITECREATED', (parse('"s"'),)), 0)
        self.assertTrue(hasattr(vm, '_resource_catalog_checked'))
        self.assertIsNone(vm._resource_catalog_checked)
        vm.invalidate_execution_cache()
        self.assertIsNone(vm._resource_catalog_checked)

    def test_minimal_literal_adapter_does_not_create_full_vm_caches(self):
        adapter = SimpleNamespace()
        expression_arguments.validate_runtime(adapter, 'STRLENS', (('lit', 'a'),))
        self.assertFalse(hasattr(adapter, '_expression_argument_type_cache'))


def _lifecycle_case(name, mode):
    def test(self):
        vm = self.prepared()
        initial = vm.rng.getstate()
        if mode == 'none': setattr(vm, name, None)
        if mode == 'failure':
            with self.assertRaises(EraError): self.validate(vm, name, True)
            self.assertEqual(getattr(vm, name), set())
        self.validate(vm, name)
        cache = getattr(vm, name)
        self.assertTrue(cache)
        with patch('pyemuera.load_arguments.StaticContext', side_effect=AssertionError('cached signature must not revalidate')):
            self.validate(vm, name)
        self.assertIs(cache, getattr(vm, name))
        self.assertEqual(vm.get('A:0'), 0)
        self.assertEqual(vm.rng.getstate(), initial)
    return test


for _name in LAZY_VALIDATION_CACHE_ATTRIBUTES:
    for _mode in ('first_reuse', 'none', 'failure'):
        setattr(InternalStateR44, 'test_' + _name.lstrip('_') + '_' + _mode, _lifecycle_case(_name, _mode))


if __name__ == '__main__': unittest.main()
