import copy,json,struct,unittest
from unittest.mock import patch
from test_core import Harness,CHARA
from pyemuera import native_save as c,character_data as d
from pyemuera.errors import EraError

class DatCodec(unittest.TestCase):
    def test_golden_empty_header(self):
        # Explicit reference CharVar3 header (UTF16LE .NET length prefix).
        raw=c.MAGIC+struct.pack('<IIBqq',1808,0,3,123,1)+b'\x02X\x00'+struct.pack('<q',0)+b'\xff'
        x=d.decode(raw);self.assertEqual(x.description,'X');self.assertEqual(d.encode(x),raw)
    def test_golden_character_field(self):
        raw=c.MAGIC+struct.pack('<IIBqq',1808,0,3,123,1)+b'\x00'+struct.pack('<q',1)+b'\x00\x04N\x00O\x00\x07\xfe\xff'
        x=d.decode(raw);self.assertEqual(x.characters[0]['NO'].values,{():7});self.assertEqual(d.encode(x),raw)
    def test_header_only_metadata_valid(self):
        raw=c.MAGIC+struct.pack('<IIBqq',1808,0,3,123,1)+b'\x00'
        self.assertEqual(d.decode(raw,True).gamecode,123)
        with self.assertRaises(EraError):d.decode(raw)
    def test_wrong_native_type(self):
        raw=c.MAGIC+struct.pack('<IIBqq',1808,0,0,123,1)+b'\x00'
        with self.assertRaises(EraError):d.decode(raw,True)
    def test_truncated_every_byte(self):
        raw=d.encode(d.CharaData(123,1,'note',[{'NAME':c.Record((),True,{():'Neutral'})}]))
        for i in range(len(raw)):
            with self.subTest(i=i),self.assertRaises(EraError):d.decode(raw[:i])
    def test_no_trailing_data(self):
        with self.assertRaises(EraError):d.decode(d.encode(d.CharaData(1,1,'',[]))+b'junk')
    def test_user_character_arrays(self):
        state=d.CharaData(1,1,'desc',[{'CUSTOM':c.Record((2,3),True,{(1,2):'neutral'},True)}]);self.assertEqual(d.decode(d.encode(state)),state)

class CharacterDataVM(Harness):
    def test_save_order_is_registration_order_not_csv_no(self):
        vm=self.script('ADDCHARA 0\nADDCHARA 0\nNAME:0=First\nNAME:1=Second\nSAVECHARA "set","info",1,0',csv=CHARA)
        state=d.read(vm,'set');self.assertEqual([x['NAME'].values[()] for x in state.characters],['Second','First'])
    def test_save_does_not_clobber_result(self):
        vm=self.script('ADDCHARA 0\nRESULT=77\nSAVECHARA "a","",0\nA=RESULT',csv=CHARA);self.assertEqual(vm.get('A'),77)
    def test_duplicate_indices_rejected(self):
        vm=self.make('@MAIN\nADDCHARA 0\nSAVECHARA "x","",0,0',csv=CHARA)
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertFalse(d.paths(vm,'x')[0].exists())
    def test_bad_index_rejected(self):
        vm=self.make('@MAIN\nSAVECHARA "x","",0',csv=CHARA)
        with self.assertRaises(EraError):vm.call('MAIN')
    def test_load_appends_without_reset(self):
        vm=self.make('@MAIN\nADDCHARA 0\nTARGET=0\nNAME=First\nSAVECHARA "x","desc",0\nNAME=Keep\nMONEY=88\nGLOBAL=77\nLOADCHARA "x"\nB=RESULT\nRETURN',csv=CHARA)
        state=vm.rng.getstate();vm.call('MAIN');self.assertEqual(vm.data.character_count,2);self.assertEqual([vm.get('NAME:0'),vm.get('NAME:1')],['Keep','First']);self.assertEqual((vm.get('MONEY'),vm.get('GLOBAL'),vm.get('B')),(88,77,1));self.assertEqual(vm.rng.getstate(),state)
    def test_load_missing_returns_zero(self):
        vm=self.script('RESULT=7\nLOADCHARA "missing"\nA=RESULT');self.assertEqual(vm.get('A'),0)
    def test_zero_length_character_file_success(self):
        vm=self.make('@MAIN\nLOADCHARA "zero"\nA=RESULT\nRETURN',csv=CHARA);p=d.paths(vm,'zero')[0];vm.saves.atomic_write(p,d.encode(d.CharaData(123,1,'',[])));vm.call('MAIN');self.assertEqual(vm.get('A'),1);self.assertEqual(vm.data.character_count,0)
    def test_load_wrong_game_returns_zero(self):
        vm=self.make('@MAIN\nLOADCHARA "x"\nA=RESULT\nRETURN',csv=CHARA);vm.saves.atomic_write(d.paths(vm,'x')[0],d.encode(d.CharaData(999,1,'',[])));vm.call('MAIN');self.assertEqual(vm.get('A'),0)
    def test_unknown_field_load_is_atomic(self):
        vm=self.script('ADDCHARA 0',csv=CHARA);before=copy.deepcopy(vm.data.variables['NAME'].values);state=d.CharaData(123,1,'',[{'NO':c.Record((),False,{():99}),'UNKNOWN':c.Record((1,),False,{(0,):1},True)}])
        with self.assertRaises(EraError):d.append(vm,state)
        self.assertEqual(vm.data.character_count,1);self.assertEqual(before,vm.data.variables['NAME'].values)
    def test_original_character_file_read_only(self):
        vm=self.make('@MAIN\nLOADCHARA "x"\nSAVECHARA "x","new",0\nRETURN',csv=CHARA);folder=vm.root/'dat';folder.mkdir();p=folder/'chara_x.dat';raw=d.encode(d.CharaData(123,1,'old',[{'NAME':c.Record((),True,{():'Original'})}]));p.write_bytes(raw);vm.call('MAIN');self.assertEqual(p.read_bytes(),raw);self.assertEqual(d.read(vm,'x').description,'new')
    def test_find_pattern_and_tail_preservation(self):
        vm=self.script('ADDCHARA 0\nSAVECHARA "Alpha","",0\nSAVECHARA "beta","",0\nRESULTS:3=tail',csv=CHARA)
        self.assertEqual(vm.eval('FIND_CHARADATA("a*")'),1);self.assertEqual(vm.get('RESULTS'),'Alpha');self.assertEqual(vm.get('RESULTS:3'),'tail')
    def test_find_no_argument_all(self):
        vm=self.script('ADDCHARA 0\nSAVECHARA "beta","",0\nSAVECHARA "Alpha","",0',csv=CHARA)
        self.assertEqual(vm.eval('FIND_CHARADATA()'),2);self.assertEqual(vm.get('RESULTS'),'Alpha')
    def test_chkchara_description(self):
        vm=self.script('ADDCHARA 0\nSAVECHARA "x","desc",0',csv=CHARA);self.assertEqual(vm.eval('CHKCHARADATA("x")'),0);self.assertEqual(vm.get('RESULTS'),'desc')
    def test_chkchara_missing(self):
        vm=self.make();self.assertEqual(vm.eval('CHKCHARADATA("nothing")'),1)
    def test_chkchara_invalid_header(self):
        vm=self.make();vm.saves.atomic_write(d.paths(vm,'x')[0],b'not a dat');self.assertEqual(vm.eval('CHKCHARADATA("x")'),4)
    def test_append_user_charadata(self):
        vm=self.script('ADDCHARA 0\nCUSTOM:0:1=77\nSAVECHARA "x","",0\nLOADCHARA "x"',csv=CHARA,headers='#DIM SAVEDATA CHARADATA CUSTOM,3');self.assertEqual(vm.get('CUSTOM:1:1'),77)
    def test_save_atomic_failure_preserves_file(self):
        vm=self.script('ADDCHARA 0\nSAVECHARA "x","old",0',csv=CHARA);p=d.paths(vm,'x')[0];before=p.read_bytes()
        with patch('pyemuera.persistence.os.replace',side_effect=OSError('failure')),self.assertRaises(EraError) as error:vm.saves.atomic_write(p,b'new')
        self.assertEqual(error.exception.code,'E_SAVE_IO')
        self.assertEqual(p.read_bytes(),before)

for value in ['../out','a/b','x\\y','bad*name','bad?name','a:b','x\x00z','x.','x ','']:
    def test(self,value=value):
        with self.assertRaises(EraError):d.name_check(value)
    setattr(DatCodec,'test_reject_path_'+str(len([x for x in DatCodec.__dict__ if x.startswith('test_reject_path')])),test)

class DeleteData(Harness):
    def test_deletion_masks_original_and_keeps_bytes(self):
        vm=self.make();path=vm.root/'save00.sav';raw=c.encode_binary(c.NativeSave(0,1));path.write_bytes(raw);self.assertIsNotNone(vm.saves.candidate(0));vm.saves.delete(0)
        self.assertIsNone(vm.saves.candidate(0));self.assertEqual(path.read_bytes(),raw);self.assertEqual(vm.saves.check(0)[0],1)
    def test_deletion_removes_both_overlays(self):
        vm=self.make();vm.saves.write(1);vm.saves.format='emuera-binary';vm.saves.write(1);vm.saves.delete(1)
        self.assertFalse(vm.saves.path(1).exists());self.assertFalse(vm.saves.native_path(1).exists())
    def test_new_save_unmasks(self):
        vm=self.make();vm.saves.delete(0);vm.saves.write(0);self.assertEqual(vm.saves.check(0)[0],0)
    def test_delete_instruction_does_not_change_result(self):
        vm=self.script('RESULT=88\nDELDATA 99\nA=RESULT');self.assertEqual(vm.get('A'),88)
    def test_delete_negative_rejected(self):
        vm=self.make()
        with self.assertRaises(EraError):vm.saves.delete(-1)
