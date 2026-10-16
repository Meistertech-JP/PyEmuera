"""Additional neutral native array schemas; source/codec regression, not Windows."""
from test_core import Harness, CHARA
from pyemuera import native_save as codec
from pyemuera.errors import EraError


class NativeAdditionalArrays(Harness):
    def test_saved_integer_and_string_multidimensional_arrays(self):
        for fmt in ('emuera-binary',):
            with self.subTest(format=fmt):
                vm = self.make(csv=CHARA, headers='#DIM SAVEDATA I2,2,3\n#DIM SAVEDATA I3,2,2,3\n#DIMS SAVEDATA S2,2,3\n#DIMS SAVEDATA S3,2,2,3')
                vm.saves.format=fmt
                items={'I2:1:2':-(1<<63),'I3:1:1:2':(1<<63)-1,'S2:1:2':'日本語|array','S3:1:1:2':'quoted "string"'}
                for name,value in items.items():vm.set(name,value)
                vm.saves.write(0,'extra arrays')
                state=codec.decode(vm.saves.native_path(0).read_bytes())
                self.assertEqual(state.variables['I3'].dims,(2,2,3))
                self.assertEqual(state.variables['S3'].values[(1,1,2)],'quoted "string"')
                for name,value in items.items():vm.set(name,'' if isinstance(value,str) else 0)
                self.assertEqual(vm.saves.load(0),1)
                self.assertEqual({name:vm.get(name) for name in items},items)

    def test_global_integer_and_string_arrays(self):
        for fmt in ('emuera-text','emuera-binary'):
            with self.subTest(format=fmt):
                vm=self.make(headers='#DIM GLOBAL SAVEDATA GI,2,3\n#DIMS GLOBAL SAVEDATA GS,3')
                vm.saves.format=fmt
                vm.set('GI:1:2',-(1<<63));vm.set('GS:2','global 日本語')
                vm.set('MONEY',22);vm.saves.write('global')
                vm.set('GI:1:2',0);vm.set('GS:2','changed');vm.set('MONEY',33)
                vm.saves.load('global')
                self.assertEqual(vm.get('GI:1:2'),-(1<<63));self.assertEqual(vm.get('GS:2'),'global 日本語')
                self.assertEqual(vm.get('MONEY'),33)

    def test_character_user_arrays_and_character_count(self):
        for fmt in ('emuera-binary',):
            with self.subTest(format=fmt):
                vm=self.script('ADDCHARA 0\nADDCHARA 0',csv=CHARA,headers='#DIM SAVEDATA CHARADATA CI,3\n#DIMS SAVEDATA CHARADATA CS,3')
                vm.saves.format=fmt
                vm.set('CI:1:2',(1<<63)-1);vm.set('CS:0:1','character 日本語')
                vm.saves.write(0)
                vm.set('CI:1:2',0);vm.set('CS:0:1','changed')
                vm.data.character_count=1
                vm.saves.load(0)
                self.assertEqual(vm.data.character_count,2)
                self.assertEqual(vm.get('CI:1:2'),(1<<63)-1);self.assertEqual(vm.get('CS:0:1'),'character 日本語')

    def test_text_integer_multidimensional_and_string_onedimensional(self):
        vm=self.make(headers='#DIM SAVEDATA IA,2,3\n#DIM SAVEDATA IB,2,2,3\n#DIMS SAVEDATA SA,3')
        vm.saves.format='emuera-text'
        items={'IA:1:2':-(1<<63),'IB:1:1:2':(1<<63)-1,'SA:2':'日本語 array'}
        for name,value in items.items():vm.set(name,value)
        vm.saves.write(0)
        for name,value in items.items():vm.set(name,'' if isinstance(value,str) else 0)
        vm.saves.load(0)
        self.assertEqual({name:vm.get(name) for name in items},items)

    def test_text_unsupported_schema_rejected_before_atomic_write(self):
        for headers in ('#DIMS SAVEDATA S2,2,3','#DIM SAVEDATA CHARADATA CI,3'):
            with self.subTest(headers=headers):
                vm=self.make(csv=CHARA,headers=headers)
                vm.data.add_default_character(0)
                vm.saves.format='emuera-binary';vm.saves.write(0)
                path=vm.saves.native_path(0);before=path.read_bytes()
                vm.saves.format='emuera-text'
                with self.assertRaises(EraError) as caught:vm.saves.write(0)
                self.assertEqual(caught.exception.code,'E_SAVE_FORMAT')
                self.assertEqual(path.read_bytes(),before)
                self.assertFalse(list(path.parent.glob('.writing-*')))
