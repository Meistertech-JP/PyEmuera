"""Trace live legacy adapters, including the public paths bypassed by the VM."""
import datetime
import io
import types
import unittest
from unittest.mock import patch
from pyemuera import builtins, commands, dispatcher
from pyemuera.errors import EraError
from test_core import Harness


class ExecutionAdapterContracts(Harness):
    def test_gettime_retains_caller_clock_module_and_single_sample(self):
        vm = self.make()
        instant = datetime.datetime(2026, 1, 2, 3, 4, 5, 123000)
        events = []
        clock = types.SimpleNamespace(datetime=types.SimpleNamespace(
            now=lambda: events.append('now') or instant))
        with patch.object(builtins, 'datetime', clock):
            self.assertEqual(builtins._call_with_values(vm, 'GETTIME', []), 20260102030405123)
            self.assertEqual(builtins._call_with_values(vm, 'GETTIME', []), 20260102030405123)
        self.assertEqual(events, ['now'] * 14)

    def test_epoch_queries_each_sample_now_before_epoch_construction(self):
        vm = self.make()
        events = []
        class Clock:
            @staticmethod
            def now():
                events.append('now')
                return datetime.datetime(1, 1, 1, 0, 0, 2, 500000)
            def __new__(cls, *args):
                events.append(list(args))
                return datetime.datetime(*args)
        with patch.object(builtins, 'datetime', types.SimpleNamespace(datetime=Clock)):
            self.assertEqual(builtins._call_with_values(vm, 'GETSECOND', []), 2)
            self.assertEqual(builtins._call_with_values(vm, 'GETMILLISECOND', []), 2500)
        self.assertEqual(events, ['now', [1, 1, 1], 'now', [1, 1, 1]])

    def test_gettime_keeps_numeric_write_when_string_write_fails(self):
        vm = self.make()
        instant = datetime.datetime(2026, 1, 2, 3, 4, 5, 123000)
        events = []
        original = vm.set
        def write(name, value):
            events.append(name)
            if name == 'RESULTS':
                raise EraError('blocked', code='E_READONLY')
            original(name, value)
        clock = types.SimpleNamespace(datetime=types.SimpleNamespace(
            now=lambda: events.append('now') or instant))
        with patch.object(commands, 'datetime', clock), patch.object(vm, 'set', write):
            with self.assertRaisesRegex(EraError, 'blocked'):
                commands.execute_command(vm, 'GETTIME', '')
        self.assertEqual(events, ['now'] * 7 + ['RESULT', 'now', 'RESULTS'])
        self.assertEqual(vm.get('RESULT'), 20260102030405123)

    def test_skipdisp_flags_precede_failing_result_write(self):
        vm = self.make()
        with patch.object(vm, 'set', side_effect=EraError('blocked', code='E_READONLY')):
            with self.assertRaises(EraError):
                commands.execute_command(vm, 'SKIPDISP', '1')
        self.assertTrue(vm.console.skip_print)
        self.assertTrue(vm.console.user_skip)

    def test_reset_nonempty_raw_argument_is_not_evaluated(self):
        vm = self.make()
        with patch.object(vm, 'args', side_effect=AssertionError('evaluated')), patch.object(vm, 'reset') as reset:
            for op in ('RESETDATA', 'RESETGLOBAL'):
                for raw in (' ', 'RAND(10)', '1/0'):
                    commands.execute_command(vm, op, raw)
            # Native VOID builder discards raw arguments, then performs reset.
            self.assertEqual(reset.call_count, 6)

    def test_putform_reads_old_value_before_form_side_effect(self):
        vm = self.make()
        vm.set('SAVEDATA_TEXT', 'old')
        def form(raw):
            vm.set('SAVEDATA_TEXT', 'changed')
            return ':suffix'
        with patch.object(vm, 'format', form):
            commands.execute_command(vm, 'PUTFORM', 'unused')
        self.assertEqual(vm.get('SAVEDATA_TEXT'), 'old:suffix')

    def test_direct_nested_noskip_restores_frame_marks(self):
        vm = self.make()
        vm.frames.append(types.SimpleNamespace(skip_marks=[], scope={}))
        for op, raw in [('SKIPDISP', '1'), ('NOSKIP', ''), ('NOSKIP', ''),
                        ('ENDNOSKIP', ''), ('ENDNOSKIP', '')]:
            commands.execute_command(vm, op, raw)
        self.assertEqual(vm.frames[-1].skip_marks, [])
        self.assertTrue(vm.console.skip_print)
        self.assertTrue(vm.console.user_skip)

    def test_direct_oneinput_rejects_whole_entry_without_result_write(self):
        vm = self.make(inputs=['12'])
        vm.set('RESULT', 77)
        with self.assertRaises(EraError):
            commands.execute_command(vm, 'ONEINPUT', '')
        self.assertEqual(vm.get('RESULT'), 77)
        self.assertEqual(self.output.getvalue(), '')

    def test_vm_oneinput_retains_dedicated_first_unit_and_echo(self):
        vm = self.script('ONEINPUT\nA=RESULT\nRETURN', inputs=['12'])
        self.assertEqual(vm.get('A'), 1)
        self.assertEqual(self.output.getvalue(), '1\n')

    def test_binding_distinguishes_input_vm_and_direct_api(self):
        row = dispatcher.describe_binding('INPUT')
        self.assertIn('input_commands', row['entrypoint'])
        self.assertIsNone(row['adapter_delegate'])
        self.assertEqual(row['direct_api_delegate'], 'pyemuera.input_commands.execute_direct')

    def test_binding_distinguishes_randomize_vm_and_direct_api(self):
        row = dispatcher.describe_binding('RANDOMIZE')
        self.assertIn('random1824', row['entrypoint'])
        self.assertEqual(row['direct_api_delegate'], 'pyemuera.state_commands.execute')

    def test_state_binding_and_value_fallback_are_explicit(self):
        self.assertEqual(dispatcher.describe_binding('GETTIME')['implementation_owner'],
                         'pyemuera.state_commands.execute')
        row = builtins.describe_value_binding('GETLINESTR')
        self.assertFalse(row['same_as_public_route'])
        self.assertEqual(row['value_adapter_delegate'], 'pyemuera.runtime_queries.function')
        self.assertIsNone(builtins.describe_value_binding('NOT_A_FUNCTION'))
