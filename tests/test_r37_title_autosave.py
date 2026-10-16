import datetime, hashlib, json
from unittest.mock import patch
from test_core import Harness
from pyemuera.default_title import show, version_text
from pyemuera.autosave import run as autosave
from pyemuera.flow import shop
from pyemuera.errors import EraError, FlowSignal, QuitSignal
from pyemuera.save_menu import SaveRepository

class Title(Harness):
    def test_all_gamebase_fields_in_order(self):
        vm=self.make('@EVENTFIRST\nQUIT',csv={'GameBase.csv':'タイトル,日本\nバージョン,1055\n作者,作者\n製作年,2026\n追加情報,情報\n'})
        show(vm);lines=list(vm.console.log_lines)
        self.assertEqual(lines,['-'*100,'日本','1.055','作者','(2026)',' ','情報','-'*100,'[0] 最初からはじめる','[1] ロードしてはじめる'])
        self.assertEqual(vm.ui['alignment'],'LEFT')
        self.assertEqual([alignment for _,alignment in vm.console.markup_lines][1:7],['CENTER']*6)

    def test_empty_title_is_omitted_and_year_is_parenthesized(self):
        vm=self.make();show(vm)
        self.assertEqual(list(vm.console.log_lines),['-'*100,'()',' ','-'*100,'[0] 最初からはじめる','[1] ロードしてはじめる'])
        self.assertNotIn('PyEmuera',self.output.getvalue())

    def test_new_game_uses_csv_filename_and_pseudo_fallback(self):
        vm=self.make('@EVENTFIRST\nQUIT',csv={'GameBase.csv':'最初からいるキャラ,9\n','Chara0.csv':'NO,7\nNAME,master\n'},inputs=['0'])
        vm.run();self.assertEqual(vm.data.character_count,2)
        self.assertEqual((vm.get('NO:0'),vm.get('NAME:0'),vm.get('NO:1')),(7,'master',0))
        self.assertEqual(vm.exit_reason,'quit')

    def test_nine_is_invalid_and_does_not_exit(self):
        vm=self.make('@EVENTFIRST\nQUIT',inputs=['9','77','0']);vm.run()
        self.assertEqual(self.output.getvalue().count('無効な値です'),2)
        self.assertEqual(self.output.getvalue().count('[0]'),1)
        self.assertEqual(vm.console.input_count,3)

    def test_custom_title_remains_separate(self):
        vm=self.make('@SYSTEM_TITLE\nPRINTL CUSTOM\nQUIT');vm.run()
        self.assertEqual(list(vm.console.log_lines),['Now Loading...','CUSTOM'])

    def test_load_override_is_called(self):
        vm=self.make('@TITLE_LOADGAME\nA=7\nQUIT',inputs=['1']);vm.run()
        self.assertEqual(vm.get('A'),7);self.assertEqual(vm.data.character_count,0)

    def test_long_strings_are_kept_in_logical_lines(self):
        vm=self.make(csv={'GameBase.csv':'タイトル,'+'長'*250+'\n'});show(vm)
        self.assertEqual(list(vm.console.log_lines)[1],'長'*250)

for version, expected in [(1,'0.001'),(10,'0.01'),(100,'0.10'),(1000,'1.00'),(1050,'1.05'),(1055,'1.055'),(-1001,'-1.-001'),(-1010,'-1.-01'),(9223372036854775807,'9223372036854775.807')]:
    def check(self,version=version,expected=expected):self.assertEqual(version_text(version),expected)
    setattr(Title,'test_version_'+str(version).replace('-','minus_'),check)

class Autosave(Harness):
    SOURCE='@SYSTEM_TITLE\nBEGIN SHOP\n@EVENTSHOP\nA+=1\nRETURN\n@SAVEINFO\nPUTFORM autosave A={A}\nRETURN\n@SHOW_SHOP\nA+=10\nQUIT\n'
    def game(self,config='',source=None):
        return self.make(source or self.SOURCE,csv={'_fixed.config':config})

    def test_normal_shop_saves_after_event_before_show(self):
        vm=self.game();before=vm.rng.getstate();vm.run();p=vm.saves.path(99)
        data=json.loads(p.read_bytes());self.assertEqual(data['variables']['A']['values'],[[[0],1]])
        self.assertTrue(data['description'].endswith(' autosave A=1'));self.assertEqual(vm.get('A'),11)
        self.assertEqual(vm.rng.getstate(),before);self.assertEqual(data['random_state'],before)
        self.assertEqual(SaveRepository(vm.saves).metadata(99).available,True)
        vm.saves.load(99);self.assertEqual(vm.get('A'),1)
        self.assertEqual(vm.rng.getstate(),before)

    def test_custom_autosave_replaces_standard_writer(self):
        source=self.SOURCE+'@SYSTEM_AUTOSAVE\nSAVEDATA 7,"custom"\nRETURN\n'
        vm=self.game(source=source);vm.run()
        self.assertTrue(vm.saves.path(7).exists());self.assertFalse(vm.saves.path(99).exists())

    def test_custom_without_write_does_not_trigger_fallback(self):
        vm=self.game(source=self.SOURCE+'@SYSTEM_AUTOSAVE\nB++\nRETURN\n');vm.run()
        self.assertEqual(vm.get('B'),1);self.assertFalse(vm.saves.path(99).exists())

    def test_load_entry_does_not_autosave_or_eventshop(self):
        vm=self.game()
        with self.assertRaises(QuitSignal):shop(vm,loaded=True)
        self.assertEqual(vm.get('A'),10);self.assertFalse(vm.saves.path(99).exists())

    def test_disabled_source_has_no_callbacks(self):
        vm=self.game('AutoSave:NO');vm.run()
        self.assertEqual(vm.get('SAVEDATA_TEXT'),'');self.assertFalse(vm.saves.path(99).exists())

    def test_invalid_auto_save_preserves_last_valid_value(self):
        vm=self.game();(vm.root/'emuera.config').write_text('AutoSave:NO\nAutoSave:invalid\nAutoSave:YES\n',encoding='utf-8-sig')
        from pyemuera.program import Program
        from pyemuera.data import GameData
        from pyemuera.runtime import VM
        vm=VM(Program(vm.root),GameData(vm.root),vm.console,seed=123);vm.run()
        self.assertFalse(vm.saves.path(99).exists());self.assertEqual(vm.eval('GETCONFIG("AutoSave")'),0)

    def test_fixed_auto_save_alias_is_locked(self):
        vm=self.game('AutoSave:NO\nオートセーブを行なう:YES\n');vm.run()
        self.assertFalse(vm.saves.path(99).exists())

    def test_unfixed_auto_save_alias_last_valid_value_wins(self):
        vm=self.game();(vm.root/'emuera.config').write_text('AutoSave:NO\nオートセーブを行なう:YES\n',encoding='utf-8-sig')
        from pyemuera.program import Program
        from pyemuera.data import GameData
        from pyemuera.runtime import VM
        vm=VM(Program(vm.root),GameData(vm.root),vm.console,seed=123);vm.run()
        self.assertTrue(vm.saves.path(99).exists())

    def test_auto_save_query_default_and_type(self):
        vm=self.game();self.assertEqual(vm.eval('GETCONFIG("AutoSave")'),1)
        with self.assertRaises(EraError) as error:vm.eval('GETCONFIGS("AutoSave")')
        self.assertEqual(error.exception.code,'E_TYPE')

    def test_native_self_roundtrip_is_preserved(self):
        for format in ['emuera-text','emuera-binary']:
            with self.subTest(format=format):
                vm=self.game();vm.saves.format=format;vm.run();self.assertTrue(vm.saves.native_path(99).is_file())
                vm.saves.load(99);self.assertEqual(vm.get('A'),1)

    def test_failure_preserves_existing_save_and_game_state(self):
        vm=self.game();vm.set('A',44);vm.saves.write(99,'old');p=vm.saves.path(99);old=p.read_bytes()
        vm.set('A',55);before=vm.rng.getstate()
        with patch('pyemuera.persistence.os.replace',side_effect=OSError('disk failure')):autosave(vm)
        self.assertEqual(p.read_bytes(),old);self.assertEqual(vm.get('A'),55);self.assertEqual(vm.rng.getstate(),before)
        self.assertIn('オートセーブをスキップします',self.output.getvalue());self.assertEqual(vm.console.wait_count,1)
        self.assertEqual(list(p.parent.glob('.writing-*')),[])

    def test_return_false_is_not_reported_as_saved(self):
        vm=self.game()
        with patch.object(vm.saves,'write',return_value=0):autosave(vm)
        self.assertIn('予期しないエラー',self.output.getvalue())
        self.assertFalse(vm.saves.path(99).exists())

    def test_corrupt_slot_is_rejected_without_partial_state(self):
        vm=self.game();vm.run();p=vm.saves.path(99);p.write_bytes(b'{bad')
        before=vm.rng.getstate();value=vm.get('A')
        with self.assertRaises(EraError) as error:vm.saves.load(99)
        self.assertEqual(error.exception.code,'E_SAVE');self.assertEqual(vm.get('A'),value);self.assertEqual(vm.rng.getstate(),before)

    def test_existing_original_native_file_is_not_overwritten(self):
        vm=self.game();p=vm.root/'save99.sav';p.write_bytes(b'original-user-bytes');vm.run()
        self.assertEqual(p.read_bytes(),b'original-user-bytes');self.assertTrue(vm.saves.path(99).exists())

    def test_pending_saveinfo_begin_is_applied_after_save(self):
        vm=self.game(source=self.SOURCE.replace('PUTFORM autosave A={A}\nRETURN','PUTFORM before title\nBEGIN TITLE'))
        with self.assertRaises(FlowSignal) as error:autosave(vm)
        # Keep the historical ID; the r37 expectation contradicted ProcessState.Return.
        self.assertEqual(error.exception.state,'TITLE');self.assertFalse(vm.saves.path(99).exists())

    def test_show_shop_reentry_does_not_repeat_automatic_save(self):
        source='@SYSTEM_TITLE\nBEGIN SHOP\n@SHOW_SHOP\nA++\nIF A==1\nBEGIN SHOP\nENDIF\nQUIT\n'
        vm=self.game(source=source)
        # Process.State: Shop_CallShowShop lacks __CAN_BEGIN__; TITLE alone is exempt.
        with patch.object(vm.saves,'write',wraps=vm.saves.write) as write:
            with self.assertRaises(EraError) as caught:vm.run()
        self.assertEqual(caught.exception.code,'E_FLOW')
        self.assertEqual(caught.exception.location.line,6)
        self.assertEqual(write.call_count,1);self.assertEqual(vm.get('A'),1)

for key in ['AutoSave','オートセーブを行なう']:
    for value,expected in [('YES',True),('NO',False),('1',True),('0',False),('false',False)]:
        def check(self,key=key,value=value,expected=expected):
            vm=self.game(key+':'+value);vm.run();self.assertEqual(vm.saves.path(99).exists(),expected)
        setattr(Autosave,'test_gate_'+str(['AutoSave','オートセーブを行なう'].index(key))+'_'+value,check)
