"""Closed state family keeps the direct Python adapter and one owner."""
import datetime
from test_core import Harness
from pyemuera.commands import execute_command
from pyemuera.dispatcher import execute, describe_binding
from pyemuera.registry import COMMAND_SPECS,validate_document
from pyemuera.errors import EraError

class StateFamily(Harness):
    def test_binding_exposes_owner_and_direct_adapter(self):
        for name in ['RESET_STAIN','RESETGLOBAL','PUTFORM']:
            b=describe_binding(name)
            self.assertEqual(b['family'],'state_operation')
            self.assertFalse(b['adapter'])
            self.assertEqual(b['direct_api_delegate'],'pyemuera.state_commands.execute')

    def test_closed_family_rejects_unowned_name(self):
        with self.assertRaises(EraError):validate_document({'schema_version':1,'commands':{'GETTIME':{'family':'state_operation'}}},'commands')

    def test_vm_and_direct_RANDOMIZE_same_RNG(self):
        a=self.make();execute_command(a,'RANDOMIZE','123')
        b=self.make();execute(b,'RANDOMIZE','123')
        self.assertEqual(a.rng.getstate(),b.rng.getstate())

    def test_vm_and_direct_PUTFORM_same_effect_order(self):
        a=self.make();execute_command(a,'PUTFORM','{A++}:{A++}')
        b=self.make();execute(b,'PUTFORM','{A++}:{A++}')
        self.assertEqual((a.get('A'),a.get('SAVEDATA_TEXT')),(b.get('A'),b.get('SAVEDATA_TEXT')))

    def test_PUTFORM_partial_effect_before_error(self):
        vm=self.make()
        with self.assertRaises(EraError):execute(vm,'PUTFORM','{A++}:{1/B}')
        self.assertEqual(vm.get('A'),1);self.assertEqual(vm.get('SAVEDATA_TEXT'),'')

    def test_RESET_STAIN_preserves_out_of_range_error(self):
        vm=self.make()
        with self.assertRaises(EraError) as e:execute(vm,'RESET_STAIN','0')
        self.assertEqual(e.exception.code,'E_CHARACTER')
