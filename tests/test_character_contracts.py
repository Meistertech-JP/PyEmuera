"""State/evaluation contracts for roster mutation and template lookup."""
from unittest.mock import patch
from test_core import Harness
from pyemuera import commands, dispatcher, builtins
from pyemuera.errors import EraError

CSV = {
    '_fixed.config': 'SPキャラを使用する:YES\n',
    'Chara7.csv': '番号,7\n名前,first\n名前,last\n呼び名,\n基礎,1,120\n基礎,1,121\nCFLAG,0,0\n',
    'Chara7sp.csv': '番号,7\n名前,special\nCFLAG,0,1\n基礎,1,150\n',
}


class CharacterContracts(Harness):
    def roster(self):
        return self.script(
            'ADDVOIDCHARA\nADDVOIDCHARA\nADDVOIDCHARA\n'
            'NO:0=20\nNO:1=99\nNO:2=10\n'
            'MASTER=1\nTARGET=0\nASSI=2\nPLAYER=2\n'
            'CFLAG:0:4=200\nCFLAG:2:4=100')

    def test_csv_duplicate_scalar_last_and_callname_default_empty(self):
        vm = self.make(csv=CSV)
        self.assertEqual(vm.eval('CSVNAME(7)'), 'last')
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), '')
        self.assertEqual(vm.eval('CSVBASE(7,1)'), 121)

    def test_csv_query_defaults_are_distinct(self):
        vm = self.make(csv=CSV)
        self.assertEqual(vm.eval('CSVRELATION(7,4)'), vm.data.settings.relation)
        self.assertEqual(vm.eval('CSVBASE(7,4)'), 0)
        self.assertEqual(vm.eval('CSVCSTR(7,4)'), '')

    def test_csv_evaluates_all_supplied_terms_before_template_lookup(self):
        vm = self.make(csv=CSV)
        self.assertEqual(vm.eval('CSVBASE(7,++B,++B)'), 150)
        self.assertEqual(vm.get('B'), 2)
        with self.assertRaises(EraError) as caught:
            vm.eval('CSVBASE(99,++B,++B)')
        self.assertEqual(vm.get('B'), 4)
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_CSV', 'No Chara CSV for ID 99 (SP=1)'))

    def test_csv_python_failure_translates_at_existing_value_boundary(self):
        vm = self.make(csv=CSV)
        failure = ValueError('template sentinel')
        with patch.object(vm.data, 'template', side_effect=failure):
            with self.assertRaises(EraError) as caught:
                vm.eval('CSVNAME(7)')
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertEqual(caught.exception.message, 'CSVNAME: invalid arguments (template sentinel)')
        self.assertIs(caught.exception.__cause__, failure)

    def test_getchara_sp_preference_and_no_rng_consumption(self):
        vm = self.script('ADDSPCHARA 7\nADDCHARA 7', csv=CSV)
        before = vm.rng.getstate()
        self.assertEqual(vm.eval('GETCHARA(7,1)'), 1)
        self.assertEqual(vm.eval('GETSPCHARA(7)'), 0)
        self.assertEqual(vm.rng.getstate(), before)

    def test_add_evaluation_failure_precedes_all_mutations(self):
        vm = self.make(csv=CSV)
        with self.assertRaises(EraError):
            commands.execute_command(vm, 'ADDCHARA', '7,1/0')
        # r34: native evaluates/adds each term; earlier commit survives.
        self.assertEqual(vm.data.character_count, 1)

    def test_add_missing_later_id_keeps_earlier_character(self):
        vm = self.make(csv=CSV)
        with self.assertRaises(EraError):
            commands.execute_command(vm, 'ADDCHARA', '7,99')
        self.assertEqual(vm.data.character_count, 1)
        self.assertEqual(vm.get('NO:0'), 7)

    def test_add_conversion_failure_is_incremental_after_full_evaluation(self):
        vm = self.make(csv=CSV)
        # Keep this historical test ID; the owner now evaluates individual terms.
        with patch.object(vm, 'eval', side_effect=[7, 'bad']):
            with self.assertRaises(EraError):
                commands.execute_command(vm, 'ADDCHARA', 'first,second')
        self.assertEqual(vm.data.character_count, 1)

    def test_index_conversion_precedes_count_error_and_preserves_roster(self):
        vm = self.roster()
        with patch.object(vm, 'args', return_value=['bad']):
            with self.assertRaises(EraError) as caught:
                commands.execute_command(vm, 'SWAPCHARA', 'source')
        self.assertEqual(caught.exception.code, 'E_TYPE')
        self.assertEqual([vm.get(f'NO:{i}') for i in range(3)], [20, 99, 10])

    def test_duplicate_delete_does_not_remove_any_character(self):
        vm = self.roster()
        with self.assertRaises(EraError) as caught:
            commands.execute_command(vm, 'DELCHARA', '0,0')
        self.assertEqual(caught.exception.message, 'Invalid/duplicate character index')
        self.assertEqual(vm.data.character_count, 3)

    def test_sort_resolves_descriptor_index_once_and_pins_master(self):
        vm = self.roster()
        commands.execute_command(vm, 'SORTCHARA', 'CFLAG:0:(++B)')
        self.assertEqual(vm.get('B'), 1)
        self.assertEqual(vm.get('MASTER'), 1)
        self.assertEqual(vm.get('PLAYER'), 2)

    def test_pickup_preserves_evolving_swap_list_role_bookkeeping(self):
        vm = self.roster()
        commands.execute_command(vm, 'PICKUPCHARA', '2,0')
        self.assertEqual([vm.get(f'NO:{i}') for i in range(2)], [10, 20])
        self.assertEqual((vm.get('TARGET'), vm.get('MASTER'), vm.get('ASSI'), vm.get('PLAYER')),
                         (-1, -1, 0, 2))

    def test_copy_erases_sparse_destination_entries_but_preserves_global_state(self):
        vm = self.roster()
        vm.set('CFLAG:1:5', 999)
        vm.set('A', 123)
        commands.execute_command(vm, 'COPYCHARA', '0,1')
        self.assertEqual(vm.get('CFLAG:1:4'), 200)
        self.assertEqual(vm.get('CFLAG:1:5'), 0)
        self.assertEqual(vm.get('A'), 123)
        self.assertEqual(vm.get('TARGET'), 0)

    def test_copy_to_self_keeps_sparse_entries_and_addcopy_keeps_source(self):
        vm = self.roster()
        commands.execute_command(vm, 'COPYCHARA', '0,0')
        commands.execute_command(vm, 'ADDCOPYCHARA', '0')
        self.assertEqual(vm.get('CFLAG:0:4'), 200)
        self.assertEqual(vm.get('CFLAG:3:4'), 200)
        self.assertEqual(vm.data.character_count, 4)

    def test_command_expression_adapter_preserves_result_type_and_side_effects(self):
        vm = self.make(csv=CSV)
        self.assertTrue(dispatcher.execute(vm, 'CSVNAME', '7'))
        self.assertEqual(vm.get('RESULTS'), 'last')
        self.assertTrue(commands.execute_command(vm, 'CSVBASE', '7,++B,++B'))
        self.assertEqual((vm.get('RESULT'), vm.get('B')), (150, 2))

    def test_mutation_error_keeps_source_file_and_line(self):
        vm = self.make('@MAIN\nADDCHARA 7,99\n', csv=CSV)
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertTrue(caught.exception.location.path.endswith('Main.ERB'))
        self.assertEqual(caught.exception.location.line, 2)
        self.assertEqual(vm.data.character_count, 1)
