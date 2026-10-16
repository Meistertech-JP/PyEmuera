"""Source-based native constructors and SP gate/evaluation order."""
from unittest.mock import patch
from test_core import Harness
from pyemuera import commands, dispatcher
from pyemuera.errors import EraError
from pyemuera.data import Variable

SP = {'_fixed.config': 'SPキャラを使用する:YES\n',
      'Chara7.csv': '番号,7\n名前,normal\n基礎,0,40\n',
      'Chara7sp.csv': '番号,7\n名前,special\nCFLAG,0,1\n基礎,0,50\n'}


class DefaultCharacter(Harness):
    def title(self, csv=None, body='ADDDEFCHARA'):
        vm = self.make('@SYSTEM_TITLE\n'+body+'\nRETURN\n', csv=csv)
        vm.call('SYSTEM_TITLE')
        return vm

    def test_no_csv_uses_zero_pseudo_template(self):
        vm = self.title()
        self.assertEqual(vm.data.character_count, 1)
        self.assertEqual(vm.get('NO:0'), 0)
        self.assertEqual(vm.get('NAME:0'), '')
        self.assertEqual(vm.get('CALLNAME:0'), '')
        self.assertEqual(vm.get('STAIN:0:2'), 0)
        self.assertEqual(vm.get('BASE:0:0'), 0)

    def test_direct_API_no_csv_is_debug_constructor(self):
        vm = self.make()
        before = vm.rng.getstate()
        self.assertTrue(commands.execute_command(vm, 'ADDDEFCHARA', ''))
        self.assertEqual(vm.data.character_count, 1)
        self.assertEqual(vm.get('NO:0'), 0)
        self.assertEqual(vm.rng.getstate(), before)

    def test_dispatcher_direct_uses_same_owner(self):
        vm = self.make()
        self.assertTrue(dispatcher.execute(vm, 'ADDDEFCHARA', ''))
        self.assertEqual(vm.data.character_count, 1)

    def test_file_number_is_distinct_from_NO(self):
        vm = self.title({'Chara0.csv': '番号,7\n名前,from-file-zero\n基礎,0,30\n',
                         'Chara7.csv': '番号,0\n名前,from-file-seven\n'})
        self.assertEqual((vm.get('NO:0'),vm.get('NAME:0'),vm.get('BASE:0:0')), (7,'from-file-zero',30))

    def test_missing_zero_file_does_not_use_NO_zero_elsewhere(self):
        vm = self.title({'Chara9.csv': '番号,0\n名前,wrong-file\n'})
        self.assertEqual((vm.get('NO:0'),vm.get('NAME:0')), (0,''))

    def test_configured_second_file_uses_its_csv_number(self):
        vm = self.title({'GameBase.csv':'最初からいるキャラ,7\n',
                         'Chara7.csv':'番号,88\n名前,second\n'})
        self.assertEqual(vm.data.character_count,2)
        self.assertEqual((vm.get('NO:0'),vm.get('NO:1')), (0,88))

    def test_missing_second_file_appends_another_pseudo(self):
        vm = self.title({'GameBase.csv':'最初からいるキャラ,7\n'})
        self.assertEqual((vm.data.character_count,vm.get('NO:1'),vm.get('NAME:1')), (2,0,''))

    def test_nonpositive_default_does_not_append_second(self):
        for number in [0,-1,-9]:
            vm=self.title({'GameBase.csv':f'最初からいるキャラ,{number}\n'})
            self.assertEqual(vm.data.character_count,1)

    def test_wrong_parent_label_rejects_before_append(self):
        vm=self.make('@MAIN\nADDDEFCHARA\nRETURN\n')
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.code,'E_FUNCTION')
        self.assertEqual(caught.exception.location.line,2)
        self.assertEqual(vm.data.character_count,0)

    def test_void_surplus_is_not_evaluated(self):
        vm=self.title(body='ADDDEFCHARA A++, RAND(100), 1/0')
        self.assertEqual(vm.get('A'),0)
        self.assertEqual(vm.data.character_count,1)

    def test_names_use_final_rows_and_callname_switch(self):
        csv={'_fixed.config':'CompatiCALLNAME:YES\n','Chara0.csv':'番号,8\n名前,first\n名前,last\n呼び名,\n'}
        vm=self.title(csv)
        self.assertEqual((vm.get('NAME:0'),vm.get('CALLNAME:0')),('last','last'))
        vm=self.title({'Chara0.csv':csv['Chara0.csv']})
        self.assertEqual(vm.get('CALLNAME:0'),'')

    def test_duplicate_NO_does_not_change_default_template_number(self):
        vm=self.title({'Chara0.csv':'名前,ignored\n番号,7\n名前,kept\n番号,9\n'})
        self.assertEqual((vm.get('NO:0'),vm.get('NAME:0')),(7,'kept'))

    def test_csv_without_NO_uses_pseudo(self):
        vm=self.title({'Chara0.csv':'名前,not-a-template\n'})
        self.assertEqual(vm.get('NAME:0'),'')

    def test_default_does_not_run_reset_stain(self):
        vm=self.title({'_replace.csv':'汚れの初期値,9/8/7/6/5\n'})
        self.assertEqual(vm.get('STAIN:0:2'),0)

    def test_constructor_failure_does_not_append_or_leave_cells(self):
        vm=self.make()
        original=vm.data._populate_character_rows
        def fail(idx,*args):
            original(idx,*args)
            raise EraError('constructor sentinel',code='E_INDEX')
        with patch.object(vm.data,'_populate_character_rows',side_effect=fail):
            with self.assertRaises(EraError):commands.execute_command(vm,'ADDDEFCHARA','')
        self.assertEqual(vm.data.character_count,0)
        self.assertFalse(any(v.values for v in vm.data.variables.values() if v.character))

    def test_second_constructor_failure_keeps_first_commit(self):
        vm=self.make(csv={'GameBase.csv':'最初からいるキャラ,7\n'})
        original=vm.data.add_default_character
        def append(no):
            if no==7:raise EraError('second constructor',code='E_LIMIT')
            return original(no)
        with patch.object(vm.data,'add_default_character',side_effect=append):
            with self.assertRaises(EraError):commands.execute_command(vm,'ADDDEFCHARA','')
        self.assertEqual(vm.data.character_count,1)

    def test_ordinary_add_missing_CSV_still_errors(self):
        vm=self.make()
        with self.assertRaises(EraError) as caught:commands.execute_command(vm,'ADDCHARA','0')
        self.assertEqual(caught.exception.code,'E_CSV')
        self.assertEqual(vm.data.character_count,0)

    def test_addvoid_existing_contract_is_separate(self):
        vm=self.script('ADDVOIDCHARA')
        self.assertEqual(vm.get('NO:0'),0)
        self.assertEqual(vm.get('STAIN:0:2'),0)


class SPCharacter(Harness):
    def test_disabled_direct_rejects_before_side_effect_and_RNG(self):
        vm=self.make(csv={'Chara7.csv':'番号,7\n'})
        before=vm.rng.getstate()
        with self.assertRaises(EraError) as caught:commands.execute_command(vm,'ADDSPCHARA','A++,RAND(100)')
        self.assertEqual(caught.exception.code,'E_ARGUMENT')
        self.assertIn('SPキャラ関係',caught.exception.message)
        self.assertEqual(vm.get('A'),0)
        self.assertEqual(vm.data.character_count,0)
        self.assertEqual(vm.rng.getstate(),before)

    def test_disabled_VM_gate_has_location(self):
        vm=self.make('@MAIN\nADDSPCHARA A++\nRETURN\n')
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertIn('SPキャラ関係',caught.exception.message)
        self.assertEqual(caught.exception.location.line,2)
        self.assertEqual(vm.get('A'),0)

    def test_English_setting_alias_enables_SP(self):
        csv=dict(SP);csv['_fixed.config']='CompatiSPChara:YES\n'
        vm=self.script('ADDSPCHARA 7',csv=csv)
        self.assertEqual((vm.get('NAME:0'),vm.get('CFLAG:0:0')),('special',1))

    def test_enabled_VM_and_direct_select_SP_template(self):
        for entry in ['VM','direct']:
            vm=self.make('@MAIN\nADDSPCHARA 7\nRETURN\n',csv=SP)
            vm.call('MAIN') if entry=='VM' else commands.execute_command(vm,'ADDSPCHARA','7')
            self.assertEqual((vm.get('NAME:0'),vm.get('BASE:0:0')),('special',50))

    def test_first_add_commits_before_later_evaluation_failure(self):
        vm=self.make(csv=SP)
        with self.assertRaises(EraError):commands.execute_command(vm,'ADDSPCHARA','7,RAND(0)')
        self.assertEqual(vm.data.character_count,1)
        self.assertEqual(vm.get('NAME:0'),'special')

    def test_missing_first_does_not_evaluate_second(self):
        vm=self.make(csv=SP);before=vm.rng.getstate()
        with self.assertRaises(EraError):commands.execute_command(vm,'ADDSPCHARA','99,RAND(100)')
        self.assertEqual(vm.rng.getstate(),before)
        self.assertEqual(vm.data.character_count,0)

    def test_no_normal_fallback_when_SP_enabled(self):
        vm=self.make(csv={'_fixed.config':'SPキャラを使用する:YES\n','Chara7.csv':'番号,7\n'})
        with self.assertRaises(EraError) as caught:commands.execute_command(vm,'ADDSPCHARA','7')
        self.assertEqual(caught.exception.code,'E_CSV')

    def test_lazy_type_check_precedes_SP_gate_without_evaluation(self):
        vm=self.make('@MAIN\nADDSPCHARA "bad", A++\nRETURN\n')
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.code,'E_TYPE')
        self.assertEqual(vm.get('A'),0)

    def test_load_type_check_is_also_state_free(self):
        vm=self.make('@MAIN\nADDSPCHARA 7,"bad"\nRETURN\n',csv={**SP,'_fixed.config':SP['_fixed.config']+'ロード時に引数を解析する:YES\n'})
        self.assertTrue(any(d.category=='E_TYPE' for d in vm.program.argument_diagnostics))
        self.assertEqual(vm.data.character_count,0)
