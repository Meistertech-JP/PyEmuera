"""UNRUN Native-v24 ERB contracts; no Python method/mapping replacement gates.

Requires the selected engine + existing test_core.Harness on the import path.
Source references and scope are in NATIVE_CONTRACT.md. No production changes.
"""
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.runtime import FlowSignal


class NativeVariableContracts(Harness):
    def execute_erb(self, source, **kwargs):
        vm = self.make(source, **kwargs)
        vm.call('MAIN')
        return vm

    def test_global_descriptor_is_not_a_cached_value(self):
        self.execute_erb('@MAIN\nNC_VALUE=1\nPRINTFORML {NC_VALUE}\n'
                         'NC_VALUE=9\nPRINTFORML {NC_VALUE}\nRETURN\n',
                         headers='#DIM NC_VALUE,2')
        self.assertEqual(self.output.getvalue(), '1\n9\n')

    def test_resetdata_keeps_global_namespace_but_restores_initial_values(self):
        self.execute_erb('@MAIN\nA=9\nNC_VALUE=88\nRESETDATA\n'
                         'PRINTFORML {A},{NC_VALUE}\nRETURN\n',
                         headers='#DIM NC_VALUE,2 = 7')
        self.assertEqual(self.output.getvalue(), '0,7\n')

    def test_resetglobal_is_distinct_from_resetdata(self):
        self.execute_erb('@MAIN\nA=9\nGLOBAL=7\nRESETDATA\n'
                         'PRINTFORML {A},{GLOBAL}\nA=4\nRESETGLOBAL\n'
                         'PRINTFORML {A},{GLOBAL}\nRETURN\n')
        self.assertEqual(self.output.getvalue(), '0,7\n4,0\n')

    def test_erb_save_load_restores_values_before_a_later_read(self):
        source = ('@MAIN\nA=11\nSAVEDATA 95,"contract"\nA=99\nLOADDATA 95\n'
                  'A=123\nRETURN\n@CHECK\nPRINTFORML {A}\nRETURN\n')
        vm = self.make(source)
        # LOADDATA transfers control; do not suppress or replace that command.
        with self.assertRaises(FlowSignal):
            vm.call('MAIN')
        vm.call('CHECK')
        self.assertEqual(self.output.getvalue(), '11\n')
        # This fixture is JSON-backed. No claim of complete Native save parity,
        # SAVEDATA RESULT behavior, or a new fixed-EXE probe is made here.

    def test_dimensions_belong_to_each_loaded_program_not_shared_name_plan(self):
        source = '@MAIN\nNC_GRID:1:2=23\nRETURN\n'
        first = self.execute_erb(source, headers='#DIM NC_GRID,2,3')
        self.assertEqual(first.get('NC_GRID:1:2'), 23)
        second = self.make(source, headers='#DIM NC_GRID,1,3')
        with self.assertRaises(EraError) as caught:
            second.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_INDEX')

    def test_csv_name_table_read_keeps_dynamic_index_function_effect(self):
        self.execute_erb('@MAIN\nSTR \'= ABLNAME:NC_INDEX()\nRETURN\n'
                         '@NC_INDEX\n#FUNCTION\nB++\nRETURNF 149\n',
                         csv={'VariableSize.csv': 'ABL,150\n',
                              'ABL.csv': '149,NativeSlot\n'})
        self.assertEqual((self.vm.get('STR'), self.vm.get('B')), ('NativeSlot', 1))

    def test_local_is_function_specific_and_persistent(self):
        vm = self.execute_erb('@MAIN\nCALL NC_ONE\nA=RESULT\nCALL NC_TWO\n'
                              'B=RESULT\nCALL NC_ONE\nC=RESULT\nRETURN\n'
                              '@NC_ONE\nLOCAL++\nRETURN LOCAL\n'
                              '@NC_TWO\nLOCAL+=10\nRETURN LOCAL\n')
        self.assertEqual((vm.get('A'), vm.get('B'), vm.get('C')), (1, 10, 2))

    def test_local_of_one_function_is_shared_by_its_recursive_calls(self):
        vm = self.execute_erb('@MAIN\nCALL NC_RECUR\nA=RESULT\nRETURN\n'
                              '@NC_RECUR\nLOCAL++\nIF LOCAL<3\nCALL NC_RECUR\n'
                              'ENDIF\nRETURN LOCAL\n')
        self.assertEqual(vm.get('A'), 3)

    def test_dynamic_private_storage_is_restored_after_recursion(self):
        vm = self.execute_erb('@MAIN\nCALL NC_RECUR,2\nA=RESULT\nRETURN\n'
                              '@NC_RECUR(NC_DEPTH)\n#DIM DYNAMIC NC_DEPTH\n'
                              '#DIM DYNAMIC NC_TEMP\nNC_TEMP=NC_DEPTH\n'
                              'IF NC_DEPTH>0\nCALL NC_RECUR,NC_DEPTH-1\nENDIF\n'
                              'RETURN NC_TEMP\n')
        self.assertEqual(vm.get('A'), 2)

    def test_ref_parameter_target_is_per_call(self):
        vm = self.execute_erb('@MAIN\nCALL NC_READ,NC_ONE\nA=RESULT\n'
                              'CALL NC_READ,NC_TWO\nB=RESULT\nRETURN\n'
                              '@NC_READ(NC_DEST)\n#DIM REF NC_DEST\n'
                              'RETURN NC_DEST:1\n',
                              headers='#DIM NC_ONE,2 = 11,12\n#DIM NC_TWO,2 = 21,22')
        self.assertEqual((vm.get('A'), vm.get('B')), (12, 22))

    def test_recursive_ref_call_restores_outer_target(self):
        vm = self.execute_erb('@MAIN\nCALL NC_READ,NC_ONE,1\nA=RESULT\nRETURN\n'
                              '@NC_READ(NC_DEST,NC_DEPTH)\n#DIM REF NC_DEST\n'
                              '#DIM DYNAMIC NC_DEPTH\nIF NC_DEPTH>0\n'
                              'CALL NC_READ,NC_TWO,0\nB=RESULT\nENDIF\n'
                              'RETURN NC_DEST:0\n',
                              headers='#DIM NC_ONE,2 = 11,12\n#DIM NC_TWO,2 = 21,22')
        self.assertEqual((vm.get('A'), vm.get('B')), (11, 21))

    def test_implicit_target_is_sampled_before_element_function(self):
        vm = self.execute_erb('@MAIN\nADDVOIDCHARA\nADDVOIDCHARA\nTARGET=0\n'
                              'CFLAG:0:1=11\nCFLAG:1:1=22\n'
                              'A=CFLAG:NC_ELEMENT()\nB=CFLAG:1\nRETURN\n'
                              '@NC_ELEMENT\n#FUNCTION\nTARGET=1\nRETURNF 1\n')
        self.assertEqual((vm.get('A'), vm.get('B'), vm.get('TARGET')), (11, 22, 1))

    def test_character_roster_mutation_changes_row_meaning_not_descriptor_name(self):
        vm = self.execute_erb('@MAIN\nADDVOIDCHARA\nADDVOIDCHARA\n'
                              'CFLAG:0:1=11\nCFLAG:1:1=22\nA=CFLAG:0:1\n'
                              'DELCHARA 0\nB=CFLAG:0:1\nRETURN\n')
        self.assertEqual((vm.get('A'), vm.get('B')), (11, 22))

    def test_assignment_source_effect_precedes_destination_index_effect(self):
        vm = self.execute_erb('@MAIN\nA:NC_INDEX()=NC_SOURCE()\nRETURN\n'
                              '@NC_SOURCE\n#FUNCTION\nC=C*10+1\nRETURNF 9\n'
                              '@NC_INDEX\n#FUNCTION\nC=C*10+2\nRETURNF 0\n')
        self.assertEqual((vm.get('A'), vm.get('C')), (9, 12))

    def test_all_index_functions_run_before_array_bounds_error_and_no_write(self):
        source = ('@MAIN\nA=9\nA=NC_GRID:NC_FIRST():NC_SECOND()\nRETURN\n'
                  '@NC_FIRST\n#FUNCTION\nC=C*10+1\nRETURNF 99\n'
                  '@NC_SECOND\n#FUNCTION\nC=C*10+2\nRETURNF 1\n')
        vm = self.make(source, headers='#DIM NC_GRID,2,3')
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_INDEX')
        self.assertEqual((vm.get('A'), vm.get('C')), (9, 12))

    def test_second_index_error_precedes_bounds_and_preserves_prior_effects(self):
        source = ('@MAIN\nA=9\nD=0\nA=NC_GRID:NC_FIRST():NC_SECOND()\nRETURN\n'
                  '@NC_FIRST\n#FUNCTION\nC=C*10+1\nRETURNF 99\n'
                  '@NC_SECOND\n#FUNCTION\nC=C*10+2\nRETURNF 1/D\n')
        vm = self.make(source, headers='#DIM NC_GRID,2,3')
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_ARITH')
        self.assertEqual(caught.exception.location.line,
                         source.splitlines().index('RETURNF 1/D') + 1)
        self.assertEqual((vm.get('A'), vm.get('C')), (9, 12))

    def test_division_and_modulo_evaluate_rhs_first(self):
        for op in ('/', '%'):
            with self.subTest(op=op):
                vm = self.execute_erb('@MAIN\nA=NC_LEFT()'+op+'NC_RIGHT()\nRETURN\n'
                                      '@NC_LEFT\n#FUNCTION\nC=C*10+1\nRETURNF 8\n'
                                      '@NC_RIGHT\n#FUNCTION\nC=C*10+2\nRETURNF 3\n')
                self.assertEqual((vm.get('A'), vm.get('C')), (2, 21))

    def test_rhs_zero_prevents_lhs_effects_and_destination_write(self):
        for op in ('/', '%'):
            with self.subTest(op=op):
                source = ('@MAIN\nA=9\nA=NC_LEFT()'+op+'NC_RIGHT()\nRETURN\n'
                          '@NC_LEFT\n#FUNCTION\nC=C*10+1\nRETURNF 8\n'
                          '@NC_RIGHT\n#FUNCTION\nC=C*10+2\nRETURNF 0\n')
                vm = self.make(source)
                with self.assertRaises(EraError) as caught:
                    vm.call('MAIN')
                self.assertEqual(caught.exception.code, 'E_ARITH')
                self.assertEqual((vm.get('A'), vm.get('C')), (9, 2))

    def test_unary_minus_reads_effectful_operand_twice(self):
        vm = self.execute_erb('@MAIN\nA=-NC_TICK()\nRETURN\n'
                              '@NC_TICK\n#FUNCTION\nC++\nRETURNF C\n')
        self.assertEqual((vm.get('A'), vm.get('C')), (-2, 2))

    def test_unary_minus_min_warning_precedes_second_operand_read(self):
        vm = self.execute_erb('@MAIN\nA=-NC_TICK()\nRETURN\n'
                              '@NC_TICK\n#FUNCTION\nC++\nIF C==1\n'
                              'RETURNF (-9223372036854775807-1)\nENDIF\n'
                              'D=LINECOUNT\nRETURNF 5\n')
        self.assertEqual((vm.get('A'), vm.get('C'), vm.get('D')), (-5, 2, 1))
        self.assertEqual(self.output.getvalue().count('整数型最小値'), 1)

    def test_lazy_untaken_index_function_is_not_evaluated(self):
        vm = self.execute_erb('@MAIN\nA=1 ? 7 # NC_BAD()\nRETURN\n'
                              '@NC_BAD\n#FUNCTION\nC++\nRETURNF 1/D\n')
        self.assertEqual((vm.get('A'), vm.get('C')), (7, 0))
