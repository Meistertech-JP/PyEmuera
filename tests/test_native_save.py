"""Synthetic, non-game fixtures for the Emuera 1824 wire format and migration."""
from __future__ import annotations
import copy, json, struct, unittest
from unittest.mock import patch
from pathlib import Path
from test_core import Harness, CHARA
from pyemuera.errors import EraError
from pyemuera import native_save as c
from pyemuera.native_store import snapshot, load_file


def nstr(s):
    data=s.encode('utf-16-le');n=len(data);out=bytearray()
    while n>=128:out.append((n&127)|128);n>>=7
    out.append(n);return bytes(out)+data


def header(global_save=False, chars=0, code=123, version=1, description=''):
    # Independent golden header, laid out directly from the supplied C# source.
    return (b'\x89ERA\r\n\x1a\n'+struct.pack('<IIBqq',1808,0,int(global_save),code,version)
            +nstr(description)+(b'' if global_save else struct.pack('<q',chars)))


def sparse(records):
    return {name:(rec.string,{k:v for k,v in rec.values.items() if v!=rec.default()})
            for name,rec in records.items() if any(v!=rec.default() for v in rec.values.values())}


class NativeCodec(unittest.TestCase):
    def test_binary_header_golden(self):
        raw=header(description='日本語 😀')+b'\xff'
        x=c.decode(raw);self.assertEqual((x.gamecode,x.game_version,x.description),(123,1,'日本語 😀'))
        self.assertEqual(c.encode_binary(x),raw)
    def test_binary_scalar_golden(self):
        raw=header()+b'\x00'+nstr('TARGET')+b'\xd0\xff\xff'+b'\x10'+nstr('TEXT')+nstr('日本')+b'\xff'
        x=c.decode(raw);self.assertEqual(x.variables['TARGET'].values,{():-1});self.assertEqual(x.variables['TEXT'].values,{():'日本'})
        self.assertEqual(c.encode_binary(x),raw)
    def test_binary_int_boundaries(self):
        ns=[-(1<<63),-32769,-32768,-1,0,207,208,32767,32768,(1<<31)-1,1<<31,(1<<63)-1]
        for n in ns:
            with self.subTest(n=n):
                w=c.BinaryWriter();w.number(n);self.assertEqual(c.BinaryReader(w.stream.getvalue()).number(),n)
    def test_binary_packed_golden(self):
        for n,raw in [(207,b'\xcf'),(208,b'\xd0\xd0\x00'),(-1,b'\xd0\xff\xff'),(32768,b'\xd1\x00\x80\x00\x00'),(1<<31,b'\xd2\x00\x00\x00\x80\x00\x00\x00\x00')]:
            with self.subTest(n=n):
                w=c.BinaryWriter();w.number(n);self.assertEqual(w.stream.getvalue(),raw)
    def test_binary_zero_runs_golden_1d(self):
        raw=header()+b'\x01'+nstr('DAY')+struct.pack('<i',10)+b'\xf0\x02\x05\xf0\x03\xd0\xff\xff\xff\xff'
        self.assertEqual(c.decode(raw).variables['DAY'].values,{(2,):5,(6,):-1})
    def test_binary_rows_golden(self):
        body=b'\xf1\x01\xf0\x02\x09\xe0\xf1\x01\x07\xe0\xff'
        raw=header()+b'\x02'+nstr('DA')+struct.pack('<ii',4,5)+body+b'\xff'
        self.assertEqual(c.decode(raw).variables['DA'].values,{(1,2):9,(3,0):7})
        self.assertEqual(c.encode_binary(c.decode(raw)),raw)
    def test_binary_planes_golden(self):
        body=b'\xf2\x01\xf1\x01\xf0\x02\x09\xe0\xe1\xf2\x01\x07\xe0\xe1\xff'
        raw=header()+b'\x03'+nstr('TA')+struct.pack('<iii',4,3,5)+body+b'\xff'
        self.assertEqual(c.decode(raw).variables['TA'].values,{(1,1,2):9,(3,0,0):7})
        self.assertEqual(c.encode_binary(c.decode(raw)),raw)
    def test_binary_string_array_golden(self):
        raw=header()+b'\x11'+nstr('SAVESTR')+struct.pack('<i',3)+b'\xf0\x01\xd8'+nstr('文字')+b'\xff\xff'
        self.assertEqual(c.decode(raw).variables['SAVESTR'].values,{(1,):'文字'})
        self.assertEqual(c.encode_binary(c.decode(raw)),raw)
    def test_binary_unicode_7bit_length(self):
        s='日本😀'*150;raw=header(description=s)+b'\xff'
        self.assertEqual(c.decode(raw).description,s)
    def test_binary_user_character_segment(self):
        x=c.NativeSave(123,1,characters=[{'NAME':c.Record((),True,{():'Synthetic'}),'CUSTOM':c.Record((2,3),False,{(1,2):7},True)}])
        raw=c.encode_binary(x);y=c.decode(raw)
        self.assertIn(b'\xfd',raw);self.assertEqual(y.characters,x.characters)
    def test_binary_missing_separator_no_user(self):
        raw=header(chars=1)+b'\x10'+nstr('NAME')+nstr('Test')+b'\xfe\xff'
        self.assertEqual(c.decode(raw).characters[0]['NAME'].values,{():'Test'})
    def test_binary_global(self):
        x=c.NativeSave(123,1,global_save=True,variables={'GLOBAL':c.Record((5,),False,{(4,):999})})
        raw=c.encode_binary(x);self.assertEqual(c.decode(raw,True).variables,x.variables)
        with self.assertRaises(EraError):c.decode(raw,False)
    def test_binary_unknown_wire_version(self):
        raw=bytearray(header()+b'\xff');raw[8:12]=struct.pack('<I',9999)
        with self.assertRaises(EraError):c.decode(bytes(raw))
    def test_binary_truncated_at_every_byte(self):
        x=c.NativeSave(123,1,'X',variables={'A':c.Record((2,),False,{(1,):999})});raw=c.encode_binary(x)
        for i in range(8,len(raw)):
            with self.subTest(offset=i),self.assertRaises(EraError):c.decode(raw[:i])
    def test_binary_zero_run_overflow(self):
        raw=header()+b'\x01'+nstr('A')+struct.pack('<i',2)+b'\xf0\x03\xff\xff'
        with self.assertRaises(EraError):c.decode(raw)
    def test_binary_negative_dimension(self):
        raw=header()+b'\x01'+nstr('A')+struct.pack('<i',-1)+b'\xff\xff'
        with self.assertRaises(EraError):c.decode(raw)
    def test_binary_duplicate(self):
        block=b'\x00'+nstr('A')+b'\x01'
        with self.assertRaises(EraError):c.decode(header()+block+block+b'\xff')
    def test_binary_trailing_junk(self):
        with self.assertRaises(EraError):c.decode(header()+b'\xffx')
    def test_binary_bad_array_marker(self):
        raw=header()+b'\x01'+nstr('A')+struct.pack('<i',2)+b'\xe0\xff\xff'
        with self.assertRaises(EraError):c.decode(raw)
    def test_binary_type_dat_rejected(self):
        raw=bytearray(header()+b'\xff');raw[16]=2
        with self.assertRaises(EraError):c.decode(bytes(raw))
    def test_text_legacy_without_extension(self):
        raw=('123\r\n1\r\nTest\r\n0\r\n'+(c.FIN+'\r\n')*61).encode()
        x=c.decode(raw);self.assertEqual((x.extension,len(x.variables)),(0,61))
    def test_text_extension_versions(self):
        base='123\n1\nTest\n0\n'+(c.FIN+'\n')*61
        for marker,v in c.MARKERS.items():
            groups=4+(2 if v>=1708 else 0)+(2 if v>=1729 else 0)+(6 if v>=1808 else 0)
            with self.subTest(version=v):
                x=c.decode((base+marker+'\n'+(c.SEP+'\n')*groups).encode());self.assertEqual(x.extension,v)
    def test_text_extension_char_versions(self):
        base='123\n1\nTest\n1\nName\nCall\n0\n7\n'+(c.FIN+'\n')*(17+61)
        for marker,v in c.MARKERS.items():
            groups=4+(2 if v>=1803 else 0)+4+(2 if v>=1708 else 0)+(2 if v>=1729 else 0)+(6 if v>=1808 else 0)
            x=c.decode((base+marker+'\n'+(c.SEP+'\n')*groups).encode());self.assertEqual(x.characters[0]['NO'].values,{():7})
    def test_text_cp932_utf8_utf16(self):
        x=c.NativeSave(123,1,'日本語',variables={'A':c.Record((5,),False,{(4,):-123})})
        for encoding in ['cp932','utf-8-sig','utf-16']:
            with self.subTest(encoding=encoding):
                y=c.decode(c.encode_text(x,encoding));self.assertEqual(y.description,x.description);self.assertEqual(y.variables['A'].values,x.variables['A'].values)
    def test_text_global_custom_arrays(self):
        x=c.NativeSave(123,1,global_save=True,variables={'GLOBAL':c.Record((3,),False,{(2,):10}), 'USER':c.Record((2,),True,{(1,):'text'},True)})
        y=c.decode(c.encode_text(x),True);self.assertEqual(sparse(y.variables),sparse(x.variables))
    def test_text_2d_3d_custom(self):
        x=c.NativeSave(123,1,variables={'CUSTOM':c.Record((2,3,4),False,{(1,2,3):42},True)})
        y=c.decode(c.encode_text(x));self.assertEqual(sparse(y.variables),sparse(x.variables));self.assertEqual(len(y.variables['CUSTOM'].values),24)
    def test_text_custom_all_zero_preserved(self):
        x=c.NativeSave(123,1,variables={'CUSTOM':c.Record((3,),False,{},True)})
        y=c.decode(c.encode_text(x));self.assertEqual(y.variables['CUSTOM'].values,{(0,):0,(1,):0,(2,):0})
    def test_text_unsupported_string_matrix(self):
        x=c.NativeSave(123,1,variables={'CUSTOM':c.Record((2,2),True,{},True)})
        with self.assertRaises(EraError):c.encode_text(x)
        self.assertEqual(c.decode(c.encode_binary(x)).variables,x.variables)
    def test_text_user_chara_rejects(self):
        x=c.NativeSave(123,1,characters=[{'CUSTOM':c.Record((2,),False,{},True)}])
        with self.assertRaises(EraError):c.encode_text(x)
    def test_text_newline_in_string_rejects(self):
        for s in ['a\nb','a\rb',c.FIN,c.SEP]:
            with self.subTest(s=s),self.assertRaises(EraError):c.encode_text(c.NativeSave(123,1,s))
    def test_text_truncation(self):
        raw=c.encode_text(c.NativeSave(123,1))
        with self.assertRaises(EraError):c.decode(raw[:-30])
    def test_text_trailing_empty_separator(self):
        raw=c.encode_text(c.NativeSave(123,1))
        c.decode(raw+(c.SEP+'\r\n').encode())
        with self.assertRaises(EraError):c.decode(raw+b'unexpected\r\n')
    def test_text_int64_limit(self):
        with self.assertRaises(EraError):c.decode(b'9223372036854775808\n1\nTest\n0\n')
    def test_resource_limit(self):
        with patch.object(c,'MAX_BYTES',8),self.assertRaises(EraError):c.decode_binary(header()+b'\xff')
    def test_bad_output_index(self):
        with self.assertRaises(EraError):c.encode_binary(c.NativeSave(1,1,variables={'A':c.Record((1,),False,{(1,):2})}))


class NativeIntegration(Harness):
    def create_original(self,vm,state,slot=0,binary=True):
        p=vm.data.root/(f'save{slot:02d}.sav' if slot!='global' else 'global.sav')
        p.write_bytes(c.encode_binary(state) if binary else c.encode_text(state));return p
    def test_original_fallback_and_overlay_safety(self):
        vm=self.make(csv=CHARA);p=self.create_original(vm,c.NativeSave(123,1,variables={'MONEY':c.Record((1,),False,{(0,):88})}))
        original=p.read_bytes();self.assertEqual(vm.saves.load(0),1);self.assertEqual(vm.get('MONEY'),88)
        vm.set('MONEY',99);vm.saves.write(0);vm.saves.load(0)
        self.assertEqual(vm.get('MONEY'),99);self.assertEqual(p.read_bytes(),original)
    def test_native_text_overlay_write_load(self):
        vm=self.script('ADDCHARA 0\nTARGET=0\nMONEY=56',csv=CHARA);vm.saves.format='emuera-text';vm.saves.write(2,'text')
        self.assertFalse((vm.data.root/'save02.sav').exists());self.assertTrue(vm.saves.native_path(2).exists())
        vm.set('MONEY',1);vm.saves.load(2);self.assertEqual(vm.get('MONEY'),56);self.assertEqual(vm.get('NAME'),'旅人')
    def test_native_binary_overlay_write_load(self):
        vm=self.script('ADDCHARA 0\nTARGET=0\nMONEY=56',csv=CHARA);vm.saves.format='emuera-binary';vm.saves.write(2,'binary')
        vm.set('MONEY',1);vm.saves.load(2);self.assertEqual(vm.get('MONEY'),56);self.assertTrue(vm.saves.native_path(2).read_bytes().startswith(c.MAGIC))
    def test_missing_native_returns_zero(self):
        vm=self.make();self.assertEqual(vm.saves.load(0),0);self.assertEqual(vm.saves.check(0)[0],1)
    def test_wrong_game_is_transactional(self):
        vm=self.make(csv=CHARA);vm.set('MONEY',777);p=self.create_original(vm,c.NativeSave(999,1,variables={'MONEY':c.Record((1,),False,{(0,):88})}))
        with self.assertRaises(EraError):vm.saves.load(0)
        self.assertEqual(vm.get('MONEY'),777);self.assertEqual(vm.saves.check(0)[0],2)
    def test_version_range(self):
        vm=self.make(csv={'GameBase.csv':'コード,123\nバージョン,30\nバージョン違い認める,20\n'})
        self.create_original(vm,c.NativeSave(123,19))
        self.assertEqual(vm.saves.check(0)[0],3)
        with self.assertRaises(EraError):vm.saves.load(0)
        self.create_original(vm,c.NativeSave(123,20));self.assertEqual(vm.saves.load(0),1)
    def test_wildcard_gamecode(self):
        vm=self.make(csv=CHARA);self.create_original(vm,c.NativeSave(0,1));self.assertEqual(vm.saves.load(0),1)
    def test_unknown_variable_is_transactional(self):
        vm=self.make(csv=CHARA);vm.set('MONEY',7)
        self.create_original(vm,c.NativeSave(123,1,variables={'MONEY':c.Record((1,),False,{(0,):10}),'UNKNOWN':c.Record((1,),False,{(0,):1},True)}))
        before={n:copy.deepcopy(v.values) for n,v in vm.data.variables.items()}
        with self.assertRaises(EraError):vm.saves.load(0)
        self.assertEqual(before,{n:v.values for n,v in vm.data.variables.items()})
    def test_truncated_is_transactional(self):
        vm=self.make(csv=CHARA);p=self.create_original(vm,c.NativeSave(123,1));p.write_bytes(p.read_bytes()[:-1]);vm.set('MONEY',33)
        with self.assertRaises(EraError):vm.saves.load(0)
        self.assertEqual(vm.get('MONEY'),33)
    def test_global_preserved_on_normal_load(self):
        vm=self.make(csv=CHARA);vm.set('GLOBAL',77);self.create_original(vm,c.NativeSave(123,1));vm.saves.load(0);self.assertEqual(vm.get('GLOBAL'),77)
    def test_global_load_does_not_reset_game(self):
        vm=self.make(csv=CHARA);vm.set('MONEY',99);vm.set('GLOBAL',7)
        self.create_original(vm,c.NativeSave(123,1,global_save=True,variables={'GLOBAL':c.Record((2,),False,{(1,):8})}),'global')
        vm.saves.load('global');self.assertEqual(vm.get('MONEY'),99);self.assertEqual(vm.get('GLOBAL'),0);self.assertEqual(vm.get('GLOBAL:1'),8)
    def test_binary_user_charadata(self):
        vm=self.script('ADDCHARA 0\nTARGET=0\nCUSTOM:0:1=19',csv=CHARA,headers='#DIM SAVEDATA CHARADATA CUSTOM,3')
        vm.saves.format='emuera-binary';vm.saves.write(1);vm.set('CUSTOM:0:1',0);vm.saves.load(1);self.assertEqual(vm.get('CUSTOM:0:1'),19)
    def test_native_text_user_zero_overrides_initializer(self):
        vm=self.make(csv=CHARA,headers='#DIM SAVEDATA CUSTOM,3=7,8,9');vm.set('CUSTOM:1',0);vm.set('CUSTOM:2',0)
        vm.saves.format='emuera-text';vm.saves.write(0);vm.set('CUSTOM:1',99);vm.saves.load(0)
        self.assertEqual([vm.get(f'CUSTOM:{i}') for i in range(3)],[7,0,0])
    def test_native_text_user_missing_tail_preserves_initializer(self):
        vm=self.make(csv=CHARA,headers='#DIM SAVEDATA CUSTOM,3=7,8,9')
        self.create_original(vm,c.NativeSave(123,1,variables={'CUSTOM':c.Record((1,),False,{(0,):0},True)}),binary=False)
        vm.saves.load(0);self.assertEqual([vm.get(f'CUSTOM:{i}') for i in range(3)],[0,8,9])
    def test_native_binary_user_missing_tail_clears_initializer(self):
        vm=self.make(csv=CHARA,headers='#DIM SAVEDATA CUSTOM,3=7,8,9')
        self.create_original(vm,c.NativeSave(123,1,variables={'CUSTOM':c.Record((1,),False,{},True)}))
        vm.saves.load(0);self.assertEqual([vm.get(f'CUSTOM:{i}') for i in range(3)],[0,0,0])
    def test_global_text_missing_user_preserves_live(self):
        vm=self.make(csv=CHARA,headers='#DIM GLOBAL SAVEDATA CUSTOM,3=7,8,9');vm.set('CUSTOM',22);vm.set('CUSTOM:2',33)
        self.create_original(vm,c.NativeSave(123,1,global_save=True),'global',False);vm.saves.load('global')
        self.assertEqual([vm.get(f'CUSTOM:{i}') for i in range(3)],[22,8,33])
    def test_global_text_user_tail_preserves_live(self):
        vm=self.make(csv=CHARA,headers='#DIM GLOBAL SAVEDATA CUSTOM,3=7,8,9');vm.set('CUSTOM:2',33)
        self.create_original(vm,c.NativeSave(123,1,global_save=True,variables={'CUSTOM':c.Record((1,),False,{(0,):0},True)}),'global',False);vm.saves.load('global')
        self.assertEqual([vm.get(f'CUSTOM:{i}') for i in range(3)],[0,8,33])
    def test_native_clips_with_report(self):
        vm=self.make(csv=CHARA,headers='#DIM SAVEDATA CUSTOM,2')
        self.create_original(vm,c.NativeSave(123,1,variables={'CUSTOM':c.Record((3,),False,{(0,):1,(2,):7},True)}));vm.saves.load(0)
        self.assertEqual(vm.get('CUSTOM'),1);self.assertEqual(vm.last_native_import['clipped_nondefault_values'],{'CUSTOM':1})
    def test_original_sav_folder_case_insensitive(self):
        vm=self.make(csv=CHARA);vm.data.config['セーブデータをsavフォルダ内に作成する']='YES';folder=vm.data.root/'SAV';folder.mkdir()
        (folder/'SAVE00.SAV').write_bytes(c.encode_binary(c.NativeSave(123,1)))
        self.assertEqual(vm.saves.load(0),1)
    def test_symlink_overlay_is_denied(self):
        vm=self.make()
        try:(vm.data.root/'.pyemuera').symlink_to(vm.data.root,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
        with self.assertRaises(EraError):vm.saves.write(0)
    def test_symlink_native_destination_is_denied(self):
        vm=self.make();p=vm.saves.native_path(0);p.parent.mkdir(parents=True)
        try:p.symlink_to(vm.data.root/'save00.sav')
        except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
        vm.saves.format='emuera-binary'
        with self.assertRaises(EraError):vm.saves.write(0)
    def test_atomic_failure_preserves_previous(self):
        vm=self.make();vm.saves.format='emuera-binary';vm.saves.write(0);p=vm.saves.native_path(0);old=p.read_bytes();vm.set('MONEY',100)
        with patch('pyemuera.persistence.os.replace',side_effect=OSError('test failure')),self.assertRaises(EraError) as error:vm.saves.write(0)
        self.assertEqual(error.exception.code,'E_SAVE_IO')
        self.assertEqual(p.read_bytes(),old);self.assertFalse(list(p.parent.glob('.writing-*')))
    def test_json_a3_schema_migration(self):
        vm=self.make();vm.set('MONEY',44);vm.saves.write(0);p=vm.saves.path(0);s=json.loads(p.read_text())
        for n in list(s['variables']):
            if n=='EJAC' or n=='DITEMTYPE' or n.startswith('NOTUSE_'):s['variables'].pop(n)
        p.write_text(json.dumps(s));vm.set('MONEY',1);vm.saves.load(0);self.assertEqual(vm.get('MONEY'),44)
    def test_native_load_metadata(self):
        vm=self.make(csv=CHARA);self.create_original(vm,c.NativeSave(123,1,'metadata'),4);vm.saves.load(4)
        self.assertEqual((vm.get('LASTLOAD_NO'),vm.get('LASTLOAD_VERSION'),vm.get('LASTLOAD_TEXT')),(4,1,'metadata'))
    def test_native_rng_not_claimed_identical(self):
        vm=self.make(csv=CHARA);before=vm.rng.getstate();self.create_original(vm,c.NativeSave(123,1));vm.saves.load(0)
        self.assertEqual(vm.rng.getstate(),before)


# Exercise each rank/type and sparse coordinate independently.
for rank in (1,2,3):
    for is_string in (False,True):
        def check(self,rank=rank,is_string=is_string):
            dims=(3,)*rank;key=(2,)*rank;v='test😀' if is_string else -(1<<40)
            x=c.NativeSave(1,1,variables={'CUSTOM':c.Record(dims,is_string,{key:v},True)})
            y=c.decode(c.encode_binary(x));self.assertEqual(x.variables,y.variables)
        setattr(NativeCodec,f'test_binary_sparse_rank{rank}_{"str" if is_string else "int"}',check)

if __name__=='__main__':unittest.main()
