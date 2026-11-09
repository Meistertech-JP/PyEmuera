"""UNRUN: minimal real-ERB supplements for mixed assertion coverage gaps.

Not installed in the frozen full52 stage. Requires existing test_core.Harness.
No engine creation on import, Python helper patches or artificial scope maps.
"""
from test_core import Harness
from pyemuera.errors import EraError


class NativeMixedLookupSupplement(Harness):
    def test_configured_forbidden_global_rejected_in_erb(self):
        with self.assertRaises(EraError) as caught:
            vm = self.make('@MAIN\nA=DA:0:0\nRETURN\n',
                           csv={'VariableSize.csv': 'DA,-1\n'})
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_VARIABLE_FORBIDDEN')

    def test_unknown_identifier_rejected_in_loaded_erb(self):
        with self.assertRaises(EraError) as caught:
            vm = self.make('@MAIN\nA=NC_NO_SUCH_SYMBOL\nRETURN\n')
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_VARIABLE')

    def test_same_private_name_is_isolated_between_functions(self):
        vm = self.make('@MAIN\nCALL NC_ONE\nA=RESULT\nCALL NC_TWO\n'
                       'B=RESULT\nCALL NC_ONE\nC=RESULT\nRETURN\n'
                       '@NC_ONE\n#DIM NC_PRIVATE\nNC_PRIVATE++\nRETURN NC_PRIVATE\n'
                       '@NC_TWO\n#DIM NC_PRIVATE\nNC_PRIVATE+=10\nRETURN NC_PRIVATE\n')
        vm.call('MAIN')
        self.assertEqual((vm.get('A'), vm.get('B'), vm.get('C')), (1, 10, 2))

    def test_character_metadata_does_not_require_target_registration(self):
        vm = self.make('@MAIN\nTARGET=999\nA=VARSIZE("CFLAG",0)\nRETURN\n',
                       csv={'VariableSize.csv': 'CFLAG,1001\n'})
        vm.call('MAIN')
        self.assertEqual((vm.get('A'), vm.get('TARGET')), (1001, 999))

    def test_explicit_dynamic_character_read_ignores_target_and_keeps_error_effect(self):
        source = ('@MAIN\nADDVOIDCHARA\nTARGET=999\nCFLAG:0:1=23\n'
                  'A=CFLAG:NC_ROW():1\nB=CFLAG:NC_ROW():1\nRETURN\n'
                  '@NC_ROW\n#FUNCTION\nC++\nRETURNF C-1\n')
        vm = self.make(source)
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_CHARACTER')
        self.assertEqual((vm.get('A'), vm.get('B'), vm.get('C'), vm.get('TARGET')),
                         (23, 0, 2, 999))
