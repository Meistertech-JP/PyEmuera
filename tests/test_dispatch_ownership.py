"""Registration family and actual execution owner are independent metadata."""
import unittest
from unittest.mock import patch
from pyemuera import dispatcher
from test_core import Harness


class OwnershipContracts(unittest.TestCase):
    def test_registry_owners_come_from_actual_bound_handlers(self):
        for name, (handler, _) in dispatcher.DISPATCH.items():
            with self.subTest(command=name):
                row = dispatcher.describe_binding(name)
                self.assertEqual(row['entrypoint'], handler.__module__+'.'+handler.__name__)

    def test_input_and_array_bypass_legacy_adapter(self):
        for name, module in [('INPUT', 'input_commands'), ('VARSET', 'array_commands')]:
            row = dispatcher.describe_binding(name)
            self.assertFalse(row['adapter'])
            self.assertEqual(row['entrypoint'], 'pyemuera.'+module+'.execute')

    def test_legacy_parameter_entry_has_explicit_adapter_owner(self):
        row = dispatcher.describe_binding('UPCHECK')
        self.assertFalse(row['adapter'])
        self.assertEqual(row['implementation_owner'], 'pyemuera.parameter_updates.execute')

    def test_binding_description_cannot_execute_an_argument(self):
        with patch.object(dispatcher, 'execute', side_effect=AssertionError('executed')):
            self.assertIsNotNone(dispatcher.describe_binding('DRAWLINE'))
            self.assertIsNone(dispatcher.describe_binding('UNKNOWN'))


class AdapterReachability(Harness):
    def test_normal_vm_input_does_not_enter_command_adapter(self):
        vm = self.make('@MAIN\nINPUT\nRETURN\n', inputs=['7'])
        with patch('pyemuera.commands.execute_command', side_effect=AssertionError('adapter entered')):
            vm.call('MAIN')
        self.assertEqual(vm.get('RESULT'), 0)  # RETURN writes RESULT; input echo survives.
        self.assertIn('7', vm.console.log_lines)

    def test_direct_python_adapter_input_is_still_reachable(self):
        from pyemuera.commands import execute_command
        vm = self.make(inputs=['7'])
        self.assertTrue(execute_command(vm, 'INPUT', ''))
        self.assertEqual(vm.get('RESULT'), 7)
