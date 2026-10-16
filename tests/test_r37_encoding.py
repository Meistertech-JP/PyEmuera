"""Fixed bytes test decoded strings, before parsing and host projection."""
import codecs, io, tempfile, unittest
from pathlib import Path
from test_core import Harness
from pyemuera.source_encoding import decode_source
from pyemuera.text import read_text, load_config
from pyemuera.program import Program
from pyemuera.data import GameData
from pyemuera.runtime import VM
from pyemuera.console import Console
from pyemuera.errors import EraError

CASES = [
    ('empty', b'', '', 'cp932'),
    ('ascii', b'ABC,1:2\r\n', 'ABC,1:2\r\n', 'cp932'),
    ('cp932', bytes.fromhex('93fa967b'), '日本', 'cp932'),
    ('utf8_no_bom', bytes.fromhex('e697a5e69cac'), '譌･譛ｬ', 'cp932'),
    ('utf8_bom', bytes.fromhex('efbbbfe697a5e69cac'), '日本', 'utf-8-sig'),
    ('utf16_le', bytes.fromhex('fffee5652c67'), '日本', 'utf-16-le'),
    ('utf16_be', bytes.fromhex('feff65e5672c'), '日本', 'utf-16-be'),
    ('utf32_le', bytes.fromhex('fffe0000e56500002c670000'), '日本', 'utf-32-le'),
    ('utf32_be', bytes.fromhex('0000feff000065e50000672c'), '日本', 'utf-32-be'),
    ('dangling_lead', b'A\x81', 'A', 'cp932'),
    ('invalid_pair_consumes_ascii', b'A\x81 B', 'A・B', 'cp932'),
    ('invalid_pair_consumes_delimiter', b'X\x81,Y', 'X・Y', 'cp932'),
    ('invalid_pair_consumes_linefeed', b'X\x81\nY', 'X・Y', 'cp932'),
    ('undefined_pair', b'\x81\xad!', '・!', 'cp932'),
    ('cp932_extensions', b'\x80\xa0\xfd\xfe\xff', '\x80\uf8f0\uf8f1\uf8f2\uf8f3', 'cp932'),
    ('bestfit_duplicates', bytes.fromhex('8790ed40'), '≒纊', 'cp932'),
    ('utf8_invalid', b'\xef\xbb\xbfA\xffB', 'A\ufffdB', 'utf-8-sig'),
    ('utf8_truncated', b'\xef\xbb\xbfA\xe3\x81', 'A', 'utf-8-sig'),
    ('utf16_invalid', b'\xff\xfe\x00\xd8A\x00', '\ufffdA', 'utf-16-le'),
    ('utf16_odd_byte', b'\xff\xfeA\x00B', 'A', 'utf-16-le'),
    ('utf32_invalid', b'\x00\x00\xfe\xff\x00\x11\x00\x00', '\ufffd', 'utf-32-be'),
    ('second_bom_is_data', codecs.BOM_UTF8 * 2 + b'A', '\ufeffA', 'utf-8-sig'),
    ('utf16_no_bom', b'A\x00B\x00', 'A\x00B\x00', 'cp932'),
]

class SourceBytes(unittest.TestCase):
    def test_explicit_utf8_is_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'source.csv';path.write_bytes(bytes.fromhex('e697a5e69cac'))
            self.assertEqual(read_text(path), ('譌･譛ｬ', 'cp932'))
            self.assertEqual(read_text(path, 'utf-8'), ('日本', 'utf-8'))

    def test_explicit_decode_is_strict(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.csv';path.write_bytes(b'\xff')
            with self.assertRaises(EraError) as error:read_text(path,'utf-8')
            self.assertEqual(error.exception.code,'E_ENCODING')

    def test_open_error_is_not_a_decode_error(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):read_text(Path(folder)/'missing')

    def test_native_text_save_uses_shared_no_bom_contract(self):
        from pyemuera.native_save import TextReader
        reader=TextReader(bytes.fromhex('e697a5e69cac')+b'\n')
        self.assertEqual(reader.encoding,'cp932');self.assertEqual(reader.lines[0],'譌･譛ｬ')

    def test_native_text_bom_preserves_unicode(self):
        from pyemuera.native_save import TextReader
        reader=TextReader(bytes.fromhex('efbbbfe697a5e69cac')+b'\n')
        self.assertEqual(reader.encoding,'utf-8-sig');self.assertEqual(reader.lines[0],'日本')

for name, raw, expected, encoding in CASES:
    def check(self,raw=raw,expected=expected,encoding=encoding):
        self.assertEqual(decode_source(raw),(expected,encoding))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sample.csv';path.write_bytes(raw)
            self.assertEqual(read_text(path),(expected,encoding))
    setattr(SourceBytes,'test_bytes_'+name,check)

class SourceConsumers(Harness):
    def load(self, root):
        return VM(Program(root),GameData(root),Console([],io.StringIO(),no_wait=True),seed=123)

    def test_japanese_replace_key_without_bom_is_unknown(self):
        vm=self.make(csv={'_Replace.csv':'起動時簡略表示,少女純愛中...'},encoding='utf-8')
        self.assertEqual(vm.data.settings.load_label,'Now Loading...')
        self.assertEqual(vm.data.warnings,[])
        self.assertNotIn('起動時簡略表示',vm.data.replacements)

    def test_ascii_replace_key_preserves_mojibake_value(self):
        vm=self.make(csv={'_Replace.csv':'LoadLabel,日本'},encoding='utf-8')
        self.assertEqual(vm.data.settings.load_label,'譌･譛ｬ')
        self.assertEqual(vm.eval('GETCONFIGS("LoadLabel")'),'譌･譛ｬ')

    def test_csv_and_erb_names_resolve_from_same_bytes(self):
        vm=self.make('@MAIN\nADDCHARA 0\nTARGET=0\nA=TALENT:TARGET:日本\nRETURN',
                     csv={'Chara0.csv':'NO,0\nNAME,日本\nTALENT,0,3\n','Talent.csv':'0,日本\n'},encoding='utf-8')
        vm.call('MAIN');self.assertEqual(vm.get('A'),3);self.assertEqual(vm.get('NAME:0'),'譌･譛ｬ')
        self.assertIn('譌･譛ｬ',vm.data.symbols['TALENT'])

    def test_different_name_encodings_do_not_silently_match(self):
        vm=self.make('@MAIN\nADDCHARA 0\nTARGET=0\nA=TALENT:TARGET:日本\nRETURN',
                     csv={'Chara0.csv':'NO,0\nTALENT,0,3\n','Talent.csv':'0,日本\n'})
        root=vm.root;(root/'CSV/Talent.csv').write_bytes('0,日本\n'.encode('utf-8'))
        vm=self.load(root)
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertEqual(vm.get('A'),0)

    def test_gamebase_no_bom_key_is_not_recognized(self):
        vm=self.make(csv={'GameBase.csv':'タイトル,日本\n'},encoding='utf-8')
        self.assertEqual(vm.get('GAMEBASE_TITLE'),'')

    def test_config_no_bom_key_is_not_recognized(self):
        vm=self.make(csv={'_fixed.config':'呼び出されなかった関数を無視する:NO\n'},encoding='utf-8')
        self.assertNotIn('呼び出されなかった関数を無視する',vm.data.config)

    def test_erh_declaration_uses_the_same_decoder(self):
        vm=self.make('@MAIN\n日本=7\nRETURN\n',headers='#DIM 日本\n',encoding='utf-8')
        vm.call('MAIN');self.assertEqual(vm.get('譌･譛ｬ'),7)
        self.assertNotIn('日本',vm.data.variables)

for codec in ['cp932','utf-8-sig','utf-16','utf-16-be','utf-32']:
    def check(self,codec=codec):
        vm=self.make(csv={'_Replace.csv':'LoadLabel,日本,値:続行\n'},encoding='utf-8-sig')
        path=vm.root/'CSV/_Replace.csv';raw='LoadLabel,日本,値:続行\n'.encode(codec)
        if codec=='utf-16-be':raw=codecs.BOM_UTF16_BE+raw
        path.write_bytes(raw);vm=self.load(vm.root)
        self.assertEqual(vm.data.settings.load_label,'日本,値:続行')
    setattr(SourceConsumers,'test_replace_'+codec.replace('-','_'),check)
