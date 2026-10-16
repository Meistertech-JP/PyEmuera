"""Normal VM bypasses the legacy adapter; its direct API stays live."""
from unittest.mock import patch
from test_core import Harness
from pyemuera.commands import execute_command
from pyemuera import dispatcher, character_commands


class MigratedDispatch(Harness):
    def test_normal_roster_dispatch_bypasses_legacy(self):
        vm = self.make('@MAIN\nADDVOIDCHARA\nADDVOIDCHARA\nSWAPCHARA 0, 1\nRETURN\n')
        with patch('pyemuera.commands.execute_command', side_effect=AssertionError('legacy entered')):
            vm.call('MAIN')
        self.assertEqual(vm.data.character_count, 2)

    def test_normal_parameter_dispatch_bypasses_legacy(self):
        vm = self.make('@MAIN\nADDVOIDCHARA\nTARGET = 0\nUP:0 = 3\nUPCHECK\nCUP:0:0 = 2\nCUPCHECK 0\nRETURN\n')
        with patch('pyemuera.commands.execute_command', side_effect=AssertionError('legacy entered')):
            vm.call('MAIN')
        self.assertEqual(vm.get('PALAM:0:0'), 5)
        self.assertEqual(vm.get('UP:0'), 0)
        self.assertEqual(vm.get('CUP:0:0'), 0)

    def test_direct_adapter_delegates_to_same_roster_owner(self):
        vm = self.make()
        with patch.object(character_commands, 'execute', wraps=character_commands.execute) as owner:
            self.assertTrue(execute_command(vm, 'ADDVOIDCHARA', ''))
        owner.assert_called_once_with(vm, 'ADDVOIDCHARA', '')
        self.assertEqual(vm.data.character_count, 1)

    def test_metadata_has_closed_owners(self):
        for name in character_commands.COMMANDS | {'UPCHECK', 'CUPCHECK'}:
            row = dispatcher.describe_binding(name)
            self.assertFalse(row['adapter'])
            self.assertTrue(row['implementation_owner'].startswith('pyemuera.'))

    def test_expect_alias_keeps_public_entry(self):
        from pyemuera.commands import expect
        from pyemuera.argument_counts import expect as owner
        self.assertIs(expect, owner)
