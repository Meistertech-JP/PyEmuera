"""Regression contracts for resolver temporaries released before sparse reads.

Imports the actual pyemuera package selected by the test environment. This file
creates no engine/VM on import and can be copied unchanged into ordinary tests.
"""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera.runtime import VM
from pyemuera.data import Variable, Ref


class ReferenceLifetimes(unittest.TestCase):
    def make_read(self, mode):
        events = []
        vm = VM.__new__(VM)
        variable = Variable('A', (4,), default=73)

        class Values(dict):
            def get(self, key, default=None):
                events.append(('storage-get', key, default))
                return super().get(key, default)

        class TemporaryRef(Ref):
            def __del__(self):
                events.append(('alias-finalizer', mode))
                if mode == 'value':
                    self.variable.values[(1,)] = 91
                elif mode == 'default':
                    self.variable.default = 91
                else:
                    raise RuntimeError('temporary alias finalizer')

        class Scope(dict):
            def get(self, name, *default):
                events.append(('scope-get', name, len(default)))
                # Public lookup captures the ordinary variable first. The
                # separate alias probe returns a transient zero-base REF.
                return variable if default else TemporaryRef(variable, (0,))

        variable.values = Values()
        vm.data = SimpleNamespace(variables={'A': variable}, character_count=2)
        vm.frames = [SimpleNamespace(scope=Scope())]
        vm.active_init, vm.legacy = {}, {}
        return vm, variable, ('var', 'A', (('lit', 1),)), events

    def observe(self, value, variable, events):
        # Also allows an external runner to retain the actual value/order on
        # assertion failure; expectations do not depend on an engine variant.
        self.observation = {'value': value, 'events': events,
                            'default': variable.default,
                            'storage': [(repr(key), v) for key, v in variable.values.items()]}

    def test_temporary_ref_finalizer_updates_value_before_read(self):
        vm, variable, node, events = self.make_read('value')
        value = vm.read_node(node)
        self.observe(value, variable, events)
        self.assertEqual(value, 91)
        self.assertEqual(variable.values[(1,)], 91)
        self.assertEqual(events, [
            ('scope-get', 'A', 1), ('scope-get', 'A', 0),
            ('alias-finalizer', 'value'), ('storage-get', (1,), 73),
        ])

    def test_temporary_ref_finalizer_updates_default_before_read(self):
        vm, variable, node, events = self.make_read('default')
        value = vm.read_node(node)
        self.observe(value, variable, events)
        self.assertEqual(value, 91)
        self.assertEqual(variable.default, 91)
        self.assertEqual(dict(variable.values), {})
        self.assertEqual(events, [
            ('scope-get', 'A', 1), ('scope-get', 'A', 0),
            ('alias-finalizer', 'default'), ('storage-get', (1,), 91),
        ])

    def test_unraisable_finalizer_hook_updates_value_before_read(self):
        vm, variable, node, events = self.make_read('raise')
        original_hook = sys.unraisablehook

        def observe_unraisable(error):
            events.append(('unraisable', type(error.exc_value).__name__, str(error.exc_value)))
            variable.values[(1,)] = 92

        with patch.object(sys, 'unraisablehook', observe_unraisable):
            value = vm.read_node(node)
        self.observe(value, variable, events)
        self.assertIs(sys.unraisablehook, original_hook)
        self.assertEqual(value, 92)
        self.assertEqual(variable.values[(1,)], 92)
        self.assertEqual(events, [
            ('scope-get', 'A', 1), ('scope-get', 'A', 0),
            ('alias-finalizer', 'raise'),
            ('unraisable', 'RuntimeError', 'temporary alias finalizer'),
            ('storage-get', (1,), 73),
        ])


if __name__ == '__main__':
    unittest.main()
