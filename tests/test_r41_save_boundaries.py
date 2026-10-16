"""Neutral BEGIN/SAVEINFO and method-return boundaries from native source."""
from unittest.mock import patch
from test_core import Harness
from pyemuera.autosave import run as autosave
from pyemuera.errors import FlowSignal
from pyemuera.save_menu import SaveMenu


class SaveBoundaryContracts(Harness):
    SOURCE = '@SAVEINFO\nA=1\nCALL HELPER\nA=A*10+3\nRETURN\n@HELPER\nA=A*10+2\nBEGIN TITLE\nA=999\n'

    def test_nested_saveinfo_begin_skips_autosave_after_caller_return(self):
        vm=self.make(self.SOURCE)
        vm.saves.write(99,'old autosave');path=vm.saves.path(99);before=path.read_bytes()
        with patch.object(vm.saves,'write',wraps=vm.saves.write) as writer:
            with self.assertRaises(FlowSignal) as caught:autosave(vm)
            writer.assert_not_called()
        self.assertEqual(caught.exception.state,'TITLE');self.assertEqual(vm.get('A'),123)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(vm.frames,[])

    def test_nested_saveinfo_begin_skips_manual_save_after_caller_return(self):
        vm=self.make(self.SOURCE,inputs=['0','0'])
        vm.saves.write(0,'old manual');path=vm.saves.path(0);before=path.read_bytes()
        with patch.object(vm.saves,'write',wraps=vm.saves.write) as writer:
            with self.assertRaises(FlowSignal) as caught:SaveMenu(vm,True).run()
            writer.assert_not_called()
        self.assertEqual(caught.exception.state,'TITLE');self.assertEqual(vm.get('A'),123)
        self.assertEqual(path.read_bytes(),before)

    def test_saveinfo_restart_preserves_pending_begin(self):
        vm=self.make('@SAVEINFO\nA++\nIF A==1\nCALL HELPER\nRESTART\nENDIF\nPUTFORM restarted={A}\nRETURN\n@HELPER\nBEGIN TITLE\n')
        vm.saves.write(99,'old');path=vm.saves.path(99);before=path.read_bytes()
        with self.assertRaises(FlowSignal) as caught:autosave(vm)
        self.assertEqual(caught.exception.state,'TITLE');self.assertEqual(vm.get('A'),2)
        self.assertEqual(path.read_bytes(),before)

    def test_saveinfo_method_restart_returnf_preserves_private_local(self):
        vm=self.make('@SAVEINFO\nA=METHOD()\nPUTFORM method={A}\nRETURN\n@METHOD\n#FUNCTION\nLOCAL++\nIF LOCAL==1\nRESTART\nENDIF\nRETURNF LOCAL\n')
        autosave(vm)
        self.assertEqual(vm.get('A'),2);self.assertEqual(vm.saves.inspect(99)['description'].split()[-1],'method=2')
        self.assertEqual(vm.frames,[])
