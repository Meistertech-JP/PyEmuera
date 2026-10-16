"""Sequential character evaluation and constructor-before-commit contracts."""
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.commands import execute_command

CSV={'Chara0.csv':'NO,0\nNAME,zero\nBASE,0,100\n', 'Chara1.csv':'NO,1\nNAME,one\nBASE,0,50\n'}

class CharacterConstruction(Harness):
    def test_later_arguments_observe_earlier_character_count(self):
        vm=self.script('ADDCHARA 0,CHARANUM',csv=CSV)
        self.assertEqual([vm.get(f'NO:{i}') for i in range(2)],[0,1])

    def test_later_divide_error_keeps_first_character(self):
        vm=self.make('@MAIN\nADDCHARA A++,1/B\nRETURN\n',csv=CSV)
        with self.assertRaises(EraError) as e:vm.call('MAIN')
        self.assertEqual(e.exception.code,'E_ARITH')
        self.assertEqual((vm.get('A'),vm.data.character_count),(1,1))
        self.assertEqual(vm.get('NAME:0'),'zero')

    def test_missing_first_template_prevents_second_RNG_consumption(self):
        vm=self.make('@MAIN\nADDCHARA 9,RAND(2)\nRETURN\n',csv=CSV);before=vm.rng.getstate()
        with self.assertRaises(EraError) as e:vm.call('MAIN')
        self.assertEqual(e.exception.code,'E_CSV')
        self.assertEqual(e.exception.as_dict()['diagnostic_message'],'定義していないキャラクタを作成しようとしました')
        self.assertEqual(vm.rng.getstate(),before)
        self.assertEqual(vm.data.character_count,0)

    def test_missing_later_template_keeps_prefix_and_effect(self):
        vm=self.make('@MAIN\nADDCHARA A++,9+A++\nRETURN\n',csv=CSV)
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertEqual((vm.get('A'),vm.data.character_count),(2,1))

    def test_all_types_checked_before_first_add(self):
        vm=self.make('@MAIN\nADDCHARA 0,"bad"\nRETURN\n',csv=CSV)
        with self.assertRaises(EraError) as e:vm.call('MAIN')
        self.assertEqual(e.exception.code,'E_TYPE');self.assertEqual(vm.data.character_count,0)

    def test_direct_API_adds_sequentially(self):
        vm=self.make(csv=CSV)
        execute_command(vm,'ADDCHARA','0,CHARANUM')
        self.assertEqual(vm.data.character_count,2)

    def test_constructor_failure_does_not_commit_current_record(self):
        vm=self.make(csv={**CSV,'Chara2.csv':'NO,2\nBASE,1000,7\n'})
        vm.data.add_character(0)
        # Fault injection tests commit boundary; this is not a native CSV case.
        vm.data.variables['BASE'].readonly=True
        with self.assertRaises(EraError):vm.data.add_character(1)
        self.assertEqual(vm.data.character_count,1)
        self.assertFalse(any(k[0]==1 for v in vm.data.variables.values() if v.character for k in v.values))

    def test_normal_and_SP_stain_are_zero_until_RESET_STAIN(self):
        vm=self.make(csv={**CSV,'Chara0sp.csv':'NO,0\nNAME,special\nCFLAG,0,1\n','_fixed.config':'SPキャラを使用する:YES\n'})
        vm.data.add_character(0)
        self.assertEqual([vm.get(f'STAIN:0:{i}') for i in range(5)],[0]*5)
        vm.data.add_character(0,sp=True)
        self.assertEqual([vm.get(f'STAIN:1:{i}') for i in range(5)],[0]*5)
        self.assertEqual(vm.get('NAME:1'),'special')
        execute_command(vm,'RESET_STAIN','0')
        self.assertEqual([vm.get(f'STAIN:0:{i}') for i in range(5)],[0,0,2,1,8])

    def test_void_pseudo_NO0_names_empty_and_stain_zero(self):
        vm=self.script('ADDVOIDCHARA',csv=CSV)
        self.assertEqual(vm.get('NO:0'),0)
        self.assertEqual([vm.get(f'{n}:0') for n in ['NAME','CALLNAME','NICKNAME','MASTERNAME']],['']*4)
        self.assertEqual(vm.get('BASE:0:0'),0)
        self.assertEqual(vm.get('STAIN:0:2'),0)

    def test_void_extra_text_is_discarded_without_effects(self):
        vm=self.script('ADDVOIDCHARA A++,RAND(10),invalid syntax')
        self.assertEqual(vm.get('A'),0);self.assertEqual(vm.data.character_count,1)
        self.assertEqual(vm.get('NO:0'),0)

    def test_direct_void_API_ignores_extra_expression(self):
        vm=self.make();before=vm.rng.getstate()
        execute_command(vm,'ADDVOIDCHARA','RAND(10),A++')
        self.assertEqual(vm.rng.getstate(),before);self.assertEqual(vm.get('A'),0)

    def test_relation_default_is_constructor_setting_not_zero(self):
        vm=self.make(csv={'_replace.csv':'RELATIONの初期値,17\n'})
        vm.data.add_pseudo_character()
        self.assertEqual(vm.get('RELATION:0:0'),17)

    def test_existing_default_character_contract_preserved(self):
        vm=self.make('@SYSTEM_TITLE\nADDDEFCHARA\nRETURN\n',csv={'Chara0.csv':'NO,7\nNAME,csv\n'})
        vm.call('SYSTEM_TITLE');self.assertEqual((vm.get('NO:0'),vm.get('NAME:0')),(7,'csv'))

    def test_direct_add_character_void_flag_uses_same_pseudo_owner(self):
        vm=self.make();vm.data.add_character(-1,void=True)
        self.assertEqual(vm.get('NO:0'),0)
