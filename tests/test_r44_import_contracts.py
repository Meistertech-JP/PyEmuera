"""Call-time binding and failure stages are public direct-API seams, not globals."""
import builtins
import importlib
import io
import itertools
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera import array_commands, printing, runtime_effects, save_commands


def bulk_vm(trace):
    variable = SimpleNamespace(readonly=False, character=False, string=False,
        dims=(2, 2), default=0, values={},
        set=lambda key, value: trace.append(['set', list(key), value]))
    reference = SimpleNamespace(variable=variable)
    return SimpleNamespace(console=SimpleNamespace(),
        ref=lambda text: (trace.append(['ref', text]), reference)[1],
        eval=lambda text: (trace.append(['eval', text]), int(text))[1])


class LocalImportContracts(unittest.TestCase):
    def test_bulk_import_replacement_preserves_order_and_direct_minimal_vm(self):
        trace = []
        math = ModuleType('math')
        math.prod = lambda dims: (trace.append(['prod', list(dims)]), 4)[1]
        product = ModuleType('itertools')
        product.product = lambda *axes: (trace.append(['product']), [(1, 1)])[1]
        with patch.dict(sys.modules, {'math': math, 'itertools': product}):
            result = array_commands.execute(bulk_vm(trace), {'name': 'VARSET'}, 'A,7')
        self.assertTrue(result)
        self.assertEqual(trace, [['ref', 'A'], ['eval', '7'], ['prod', [2, 2]],
                                 ['product'], ['set', [1, 1], 7]])

    def test_bulk_import_failure_occurs_after_value_before_writes(self):
        trace = []
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == 'math':
                raise ModuleNotFoundError('neutral blocked math')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guarded):
            with self.assertRaisesRegex(ModuleNotFoundError, '^neutral blocked math$'):
                array_commands.execute(bulk_vm(trace), {'name': 'VARSET'}, 'A,7')
        self.assertEqual(trace, [['ref', 'A'], ['eval', '7']])

    def test_await_binds_replaced_time_before_expression_and_flush(self):
        trace = []
        clock = ModuleType('time')
        clock.sleep = lambda duration: trace.append(['sleep', duration])
        console = SimpleNamespace(no_wait=False,
            flush=lambda **kw: trace.append(['flush', kw]),
            output=SimpleNamespace(flush=lambda: trace.append(['output_flush'])))
        vm = SimpleNamespace(console=console,
            eval=lambda raw: (trace.append(['eval', raw]), 5)[1])
        with patch.dict(sys.modules, {'time': clock}):
            runtime_effects.await_delay(vm, {'name': 'AWAIT'}, '5')
        self.assertEqual(trace, [['eval', '5'], ['flush', {'force': True}],
                                 ['output_flush'], ['sleep', 0.005]])

    def test_debug_print_binds_replaced_sys_only_after_debug_gate(self):
        diagnostic = io.StringIO()
        replacement = ModuleType('sys')
        replacement.stderr = diagnostic
        vm = SimpleNamespace(console=SimpleNamespace(), program=SimpleNamespace(debug=True),
                             format=lambda raw: 'formatted:' + raw)
        with patch.dict(sys.modules, {'sys': replacement}):
            printing.execute(vm, {'debug': True, 'argument_mode': 'form', 'newline': True}, 'value')
        self.assertEqual(diagnostic.getvalue(), 'formatted:value\n')

    def test_save_direct_fallback_receives_call_bound_datetime(self):
        from pyemuera import direct_commands
        replacement = ModuleType('datetime')
        vm = SimpleNamespace(console=SimpleNamespace())
        observed = []
        with patch.dict(sys.modules, {'datetime': replacement}), patch.object(
            direct_commands, 'execute', side_effect=lambda vm, name, arg, clock:
                (observed.append((name, arg, clock)), False)[1]):
            result = save_commands.execute(vm, {'name': 'UNKNOWN_DIRECT'}, 'raw')
        self.assertFalse(result)
        self.assertEqual(observed[0][:2], ('UNKNOWN_DIRECT', 'raw'))
        self.assertIs(observed[0][2], replacement)

    def test_arraycopy_binds_product_before_dimension_getter_changes_module(self):
        original = itertools.product
        trace = []
        counter = [0]
        class Variable:
            character = False
            string = False
            readonly = False
            @property
            def dims(self):
                counter[0] += 1
                if counter[0] == 3:
                    itertools.product = lambda *axes: [(9, 9)]
                return (2, 2)
            def get(self, key):
                return key[0] * 10 + key[1]
            def set(self, key, value):
                trace.append([list(key), value])
        source, destination = Variable(), Variable()
        vm = SimpleNamespace(args=lambda raw: ['SRC', 'DST'],
                             lookup=lambda name: source if name == 'SRC' else destination)
        try:
            array_commands.execute(vm, {'name': 'ARRAYCOPY'}, 'ignored')
        finally:
            itertools.product = original
        self.assertEqual(trace, [[[0, 0], 0], [[0, 1], 1], [[1, 0], 10], [[1, 1], 11]])

    def test_reload_preserves_minimal_api_and_instance_state_separation(self):
        first, second = [], []
        array_commands.execute(bulk_vm(first), {'name': 'VARSET'}, 'A,3')
        importlib.reload(array_commands)
        array_commands.execute(bulk_vm(second), {'name': 'VARSET'}, 'A,7')
        self.assertEqual([row[-1] for row in first if row[0] == 'set'], [3] * 4)
        self.assertEqual([row[-1] for row in second if row[0] == 'set'], [7] * 4)
