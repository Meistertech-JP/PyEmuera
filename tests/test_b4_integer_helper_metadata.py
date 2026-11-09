"""Actual resolver contracts for in-place mutation of the integer helper.

No dynamic code generation or VM creation on import. One declared static code
object replaces the helper body temporarily; the original metadata is restored
in finally. Each API uses a fresh minimal VM and exact builtin Variable object.
"""
from types import SimpleNamespace
import unittest

from pyemuera import expr, runtime
from pyemuera.data import Variable
from pyemuera.errors import Location


def increment_integer(value):
    return value + 1


class IntegerHelperMetadata(unittest.TestCase):
    def check_site(self, site, dims, character, operands, expected_key,
                   original_key, expected_value, original_value):
        helper = runtime.integer
        saved_code = helper.__code__
        saved_defaults, saved_kwdefaults = helper.__defaults__, helper.__kwdefaults__
        self.observations = []
        self.metadata = {}
        self.assertIs(helper, expr.integer)
        self.assertIs(helper, expr._BASE_INTEGER)
        if hasattr(runtime, '_BASE_INTEGER'):
            self.assertIs(helper, runtime._BASE_INTEGER)
        self.assertEqual(saved_code.co_freevars, increment_integer.__code__.co_freevars)
        try:
            helper.__code__ = increment_integer.__code__
            self.metadata = {
                'runtime_alias_same_object': runtime.integer is helper,
                'expr_alias_same_object': expr.integer is helper,
                'expr_anchor_same_object': expr._BASE_INTEGER is helper,
                'runtime_anchor_present': hasattr(runtime, '_BASE_INTEGER'),
                'runtime_anchor_same_object': (runtime._BASE_INTEGER is helper
                                               if hasattr(runtime, '_BASE_INTEGER') else None),
                'code_changed_without_identity_change': helper.__code__ is not saved_code,
                'replacement_is_declared_static_code': helper.__code__ is increment_integer.__code__,
                'defaults_unchanged': helper.__defaults__ is saved_defaults,
                'kwdefaults_unchanged': helper.__kwdefaults__ is saved_kwdefaults,
                'replacement_code_origin': helper.__code__.co_filename,
            }
            self.assertTrue(self.metadata['runtime_alias_same_object'])
            self.assertTrue(self.metadata['expr_anchor_same_object'])
            self.assertTrue(self.metadata['code_changed_without_identity_change'])
            self.assertTrue(self.metadata['defaults_unchanged'])
            self.assertTrue(self.metadata['kwdefaults_unchanged'])
            for entry in ('resolve', 'read'):
                with self.subTest(site=site, entry=entry):
                    events = []
                    vm = runtime.VM.__new__(runtime.VM)
                    variable = Variable('A', dims, character=character)
                    self.assertIs(type(variable), Variable)
                    variable.values[original_key] = original_value
                    variable.values[expected_key] = expected_value
                    vm.data = SimpleNamespace(variables={'A': variable}, character_count=8)
                    vm.frames, vm.active_init, vm.legacy = [], {}, {}
                    vm.location = Location('integer-metadata.ERB', 35)
                    vm.initializing_declarations = False
                    original_lookup = vm.lookup
                    def lookup(name):
                        events.append(('lookup', name))
                        return original_lookup(name)
                    vm.lookup = lookup
                    def operand(name, args):
                        events.append(('operand', name))
                        return {'X': 1, 'Y': 2}[name]
                    vm.call_expr = operand
                    checked_keys = []
                    original_validate = variable.validate
                    def validate(key):
                        events.append(('validate', tuple(key)))
                        checked_keys.append(tuple(key))
                        return original_validate(key)
                    variable.validate = validate
                    node = ('var', 'A', operands)
                    if entry == 'resolve':
                        actual, key = vm._resolve_ref(node)
                        self.assertIs(actual, variable)
                        value = actual.values[key]
                    else:
                        value = vm.read_node(node)
                        key = checked_keys[-1]
                    events.append(('return', entry, value))
                    self.observations.append({'site': site, 'entry': entry, 'key': tuple(key),
                                              'value': value, 'events': events,
                                              'vm_location': str(vm.location)})
                    self.assertEqual(tuple(key), expected_key)
                    self.assertEqual(value, expected_value)
                    expected_events = [('lookup', 'A')] + [
                        ('operand', n[1]) for n in operands if n[0] == 'call'
                    ] + [('validate', expected_key), ('return', entry, expected_value)]
                    self.assertEqual(events, expected_events)
                    self.assertEqual(vm.location, Location('integer-metadata.ERB', 35))
        finally:
            helper.__code__ = saved_code
            helper.__defaults__ = saved_defaults
            helper.__kwdefaults__ = saved_kwdefaults
            self.metadata['restored_code_identity'] = helper.__code__ is saved_code
            self.metadata['restored_defaults_identity'] = helper.__defaults__ is saved_defaults
            self.metadata['restored_kwdefaults_identity'] = helper.__kwdefaults__ is saved_kwdefaults
        self.assertIs(runtime.integer, helper)
        self.assertIs(helper.__code__, saved_code)

    def test_noncharacter_dynamic_one_index_uses_changed_helper(self):
        self.check_site('single', (8,), False, (('call', 'X', ()),),
                        (2,), (1,), 202, 101)

    def test_character_dynamic_character_literal_element_uses_changed_helper(self):
        self.check_site('character', (8,), True, (('call', 'X', ()), ('lit', 3)),
                        (2, 3), (1, 3), 203, 103)

    def test_general_two_dynamic_indices_use_changed_helper(self):
        self.check_site('general', (8, 8), False,
                        (('call', 'X', ()), ('call', 'Y', ())),
                        (2, 3), (1, 2), 223, 112)


if __name__ == '__main__':
    unittest.main()
