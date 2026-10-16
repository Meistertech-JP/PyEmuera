"""Cases distilled from src1824, not user game text or saves."""
import json,io,re,unittest
from pathlib import Path
from test_core import Harness,CHARA
from pyemuera.errors import EraError
from pyemuera.compat1824 import units,scalar_at

class SourceFunctionsA7(Harness):
    def test_currentalign_returns_string(self):
        vm=self.script('ALIGNMENT RIGHT');self.assertEqual(vm.eval('CURRENTALIGN()'),'RIGHT')
    def test_getstyle(self):
        vm=self.script('FONTSTYLE 5');self.assertEqual(vm.eval('GETSTYLE()'),5)
    def test_named_rgb(self):
        vm=self.make();self.assertEqual(vm.eval('COLOR_FROMRGB(18,52,86)'),0x123456);self.assertEqual(vm.eval('COLOR_FROMNAME("AliceBlue")'),0xf0f8ff)
    def test_named_unknown(self):self.assertEqual(self.make().eval('COLOR_FROMNAME("not a color")'),-1)
    def test_named_transparent_rejected(self):
        with self.assertRaises(EraError):self.make().eval('COLOR_FROMNAME("transparent")')
    def test_named_setcolor_keeps_literal_argument(self):
        vm=self.script('SETCOLORBYNAME DarkSlateBlue');self.assertEqual(vm.ui['color'],0x483d8b)
    def test_rgb_component_rejected(self):
        for text in ['COLOR_FROMRGB(-1,0,0)','COLOR_FROMRGB(0,256,0)']:
            with self.assertRaises(EraError):self.make().eval(text)
    def test_gettimes_shape(self):self.assertRegex(self.make().eval('GETTIMES()'),r'^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d$')
    def test_getlinestr_pattern_not_history(self):
        vm=self.make();vm.console.columns=12;self.assertEqual(vm.eval('GETLINESTR("ab")'),'abababababab')
    def test_getlinestr_empty(self):
        with self.assertRaises(EraError):self.make().eval('GETLINESTR("")')
    def test_text_save_load_isolated(self):
        vm=self.make();self.assertEqual(vm.eval('SAVETEXT("neutral text",3)'),1);self.assertEqual(vm.eval('LOADTEXT(3)'),'neutral text')
        self.assertFalse((vm.data.root/'txt03.txt').exists());self.assertTrue((vm.data.root/'.pyemuera/text-root/txt03.txt').exists())
    def test_text_save_utf8_and_force_sav(self):
        vm=self.make();self.assertEqual(vm.eval_node(('call','SAVETEXT',(('lit','日本😀'),('lit',3),('lit',1),('lit',1)))),1)
        self.assertEqual(vm.eval('LOADTEXT(3,1,1)'),'日本😀')
    def test_text_original_readonly(self):
        vm=self.make();p=vm.data.root/'txt03.txt';p.write_bytes('original'.encode('cp932'));self.assertEqual(vm.eval('LOADTEXT(3)'),'original')
        vm.eval('SAVETEXT("new",3)');self.assertEqual(vm.eval('LOADTEXT(3)'),'new');self.assertEqual(p.read_bytes(),b'original')
    def test_text_missing_returns_empty(self):self.assertEqual(self.make().eval('LOADTEXT(1)'), '')
    def test_text_index_outside_range(self):
        vm=self.make();self.assertEqual(vm.eval('LOADTEXT(-1)'), '');self.assertEqual(vm.eval('SAVETEXT("x",2147483648)'),0)
    def test_text_argument_hole_rejected(self):
        with self.assertRaises(EraError):self.make().eval('LOADTEXT(1,,1)')
    def test_text_output_symlink_rejected(self):
        vm=self.make();folder=vm.data.root/'.pyemuera';folder.mkdir();external=vm.data.root/'target';external.mkdir()
        try:(folder/'text-root').symlink_to(external,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
        with self.assertRaises(EraError):vm.eval('SAVETEXT("x",0)')
    def test_array_msort_rows(self):
        vm=self.make(headers='#DIM KEYS,4\n#DIM ROWS,4,2');vm.set('KEYS',3);vm.set('KEYS:1',1);vm.set('KEYS:2',2)
        for i,value in enumerate((30,10,20,999)):vm.set(f'ROWS:{i}:1',value)
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'),1)
        self.assertEqual([vm.get(f'KEYS:{i}') for i in range(4)],[1,2,3,0]);self.assertEqual([vm.get(f'ROWS:{i}:1') for i in range(4)],[10,20,30,999])
    def test_array_msort_short_target_prior_array_updated(self):
        vm=self.make(headers='#DIM KEYS,3\n#DIM ROWS,1');vm.set('KEYS',2);vm.set('KEYS:1',1)
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'),0);self.assertEqual(vm.get('KEYS'),1)
    def test_arraycopy_intersection_keeps_tail(self):
        vm=self.script('SOURCE_A:0=7,8\nDEST_B:2=99\nARRAYCOPY "SOURCE_A","DEST_B"',headers='#DIM SOURCE_A,2\n#DIM DEST_B,3')
        self.assertEqual([vm.get(f'DEST_B:{i}') for i in range(3)],[7,8,99])
    def test_arraycopy_type_rejected(self):
        vm=self.make(headers='#DIM SOURCE_A,2\n#DIMS DEST_B,3')
        vm.program.functions['MAIN'][0].code.clear()
        from pyemuera.commands import execute_command
        with self.assertRaises(EraError):execute_command(vm,'ARRAYCOPY','"SOURCE_A","DEST_B"')
    def test_find_element_regex(self):
        vm=self.make(headers='#DIMS TEXTS,3');vm.set('TEXTS','abc');vm.set('TEXTS:1','bc');vm.set('TEXTS:2','bcd')
        self.assertEqual(vm.eval('FINDELEMENT(TEXTS,"bc")'),0);self.assertEqual(vm.eval('FINDELEMENT(TEXTS,"bc",,,1)'),1)
        self.assertEqual(vm.eval('FINDLASTELEMENT(TEXTS,"bc")'),2)
    def test_find_element_bad_regex(self):
        vm=self.make(headers='#DIMS TEXTS,3')
        with self.assertRaises(EraError):vm.eval('FINDELEMENT(TEXTS,"[")')
    def test_find_element_numeric_holes(self):
        vm=self.make();vm.set('A:3',7);self.assertEqual(vm.eval('FINDELEMENT(A,7,,5,1)'),3)
    def test_array_range_omitted(self):
        vm=self.make(csv={'VariableSize.csv':'A,5'});vm.set('A:2',7)
        self.assertEqual(vm.eval('SUMARRAY(A,,4)'),7)
    def test_chkdata_updates_results(self):
        vm=self.make();vm.saves.write(2,'neutral');self.assertEqual(vm.eval('CHKDATA(2)'),0);self.assertEqual(vm.get('RESULTS'),'neutral')
    def test_chkdata_missing(self):self.assertEqual(self.make().eval('CHKDATA(3)'),1)
    def test_unicode_unpaired_bmp(self):
        vm=self.make();self.assertEqual(ord(vm.eval('UNICODE(55296)')),55296);self.assertEqual(vm.eval_node(('call','UNICODEBYTE',(('lit','\ud800'),))),0xfffd)
    def test_utf16_scalar_reject_low_surrogate_index(self):
        with self.assertRaises(EraError):scalar_at('😀',1)
    def test_unicodebyte_supplementary(self):self.assertEqual(self.make().eval_node(('call','UNICODEBYTE',(('lit','😀'),))),0x1f600)
    def test_utf16_substring_supplementary(self):
        vm=self.make();vm.set('STR','A😀B');self.assertEqual(vm.eval('STRLENSU(STR)'),4);self.assertEqual(vm.eval('SUBSTRINGU(STR,1,2)'),'😀')
    def test_utf16_substring_half_surrogate_preserved(self):
        vm=self.make();vm.set('STR','😀');self.assertEqual(vm.eval('CHARATU(STR,0)'),'\ud83d');self.assertEqual(vm.eval('CHARATU(STR,1)'),'\ude00')
    def test_utf16_find_index(self):
        vm=self.make();vm.set('STR','😀B');self.assertEqual(vm.eval('STRFINDU(STR,"B")'),2)
    def test_utf16_charat_outside_empty(self):self.assertEqual(self.make().eval('CHARATU("x",-1)'), '')
    def test_encoded_scalar_default_empty(self):self.assertEqual(self.make().eval('ENCODETOUNI("")'),-1)
    def test_awwait_skip_with_no_wait(self):self.script('AWAIT 10000')
    def test_awwait_negative(self):
        with self.assertRaises(EraError):self.script('AWAIT -1')

# Independent expected numeric outcomes for source-reviewed integer functions.
CASES=[('power_negative','POWER(2,-3)',0),('power_fraction','POWER(-2,-1)',0),('square','SQRT(81)',9),('cuberoot','CBRT(27)',3),('ln','LOG(10)',2),('lg','LOG10(1000)',3),('exponent','EXPONENT(1)',2),('decimal','CONVERT(-12,10)','-12'),('hex_twos_complement','CONVERT(-1,16)','ffffffffffffffff'),('bin','CONVERT(6,2)','110'),('oct','CONVERT(15,8)','17'),('int_decimal_fraction','TOINT("-12.34")',-12),('numeric_decimal','ISNUMERIC("12.34")',1),('int_space','TOINT(" 12")',0),('int_fullwidth','TOINT("１２")',0),('numeric_empty','ISNUMERIC("")',0),('int_binary','TOINT("0b110")',6)]
for name,expression,value in CASES:
    def check(self,expression=expression,value=value):self.assertEqual(self.make().eval(expression),value)
    setattr(SourceFunctionsA7,'test_numeric_'+name,check)
for name,expression in [('sqrt_negative','SQRT(-1)'),('cbrt_negative','CBRT(-1)'),('log_zero','LOG(0)'),('power_overflow','POWER(2,63)'),('exponent_overflow','EXPONENT(1000)'),('convert_base','CONVERT(3,3)'),('toint_overflow','TOINT("9223372036854775808")')]:
    def check(self,expression=expression):
        with self.assertRaises(EraError):self.make().eval(expression)
    setattr(SourceFunctionsA7,'test_error_'+name,check)

class EvaluationOrderA7(Harness):
    def test_getnumb_argument_evaluated_once(self):
        vm=self.make('@MAIN\nRETURN\n@F\n#FUNCTIONS\nC+=1\nRETURNF "ABL"',csv={'Abl.csv':'1,技能'})
        self.assertEqual(vm.eval('GETNUMB(F(),"技能")'),1);self.assertEqual(vm.get('C'),1)
