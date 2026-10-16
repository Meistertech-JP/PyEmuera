"""Regression tests distilled from source syntax; no game story/assets."""
import json
from test_core import Harness, CHARA
from pyemuera.errors import EraError
from pyemuera.native_store import export_randdata
from pyemuera import native_save as codec
from pyemuera.audit import audit

class CompatA4(Harness):
    def test_tab_dims(self):
        vm=self.make(headers='#DIMS\tWORDS,100');vm.set('WORDS:99','ok');self.assertEqual(vm.get('WORDS:99'),'ok')
    def test_tab_dim_saved(self):
        vm=self.make(headers='#DIM\tSAVEDATA\tNUMBERS,100');vm.set('NUMBERS:99',42);self.assertTrue(vm.data.variables['NUMBERS'].saved)
    def test_tab_define(self):
        vm=self.script('A=TOKEN',headers='#DEFINE\tTOKEN\t42');self.assertEqual(vm.get('A'),42)
    def test_tab_private_declaration(self):
        vm=self.make('@MAIN\n#DIMS\tDYNAMIC\tWORDS,2\nWORDS=ok\nPRINTSL WORDS\nRETURN');vm.call('MAIN');self.assertEqual(self.output.getvalue(),'ok\n')
    def test_post_increment(self):
        vm=self.script('A=5\nB=A++\nC=A');self.assertEqual((vm.get('A'),vm.get('B'),vm.get('C')),(6,5,6))
    def test_pre_increment(self):
        vm=self.script('A=5\nB=++A');self.assertEqual((vm.get('A'),vm.get('B')),(6,6))
    def test_post_decrement(self):
        vm=self.script('A=5\nB=A--');self.assertEqual((vm.get('A'),vm.get('B')),(4,5))
    def test_pre_decrement(self):
        vm=self.script('A=5\nB=--A');self.assertEqual((vm.get('A'),vm.get('B')),(4,4))
    def test_post_increment_in_index(self):
        vm=self.script('A=2\nB:(A++)=9');self.assertEqual((vm.get('A'),vm.get('B:2')),(3,9))
    def test_post_increment_ref_evaluated_once(self):
        vm=self.script('A=2\nB:2=9\nC=(B:(A++))++');self.assertEqual((vm.get('A'),vm.get('B:2'),vm.get('C')),(3,10,9))
    def test_increment_short_circuit(self):
        vm=self.script('A=2\nB=0&&A++\nC=1||++A');self.assertEqual(vm.get('A'),2)
    def test_increment_i64_wrap(self):
        vm=self.script('A=9223372036854775807\nB=++A');self.assertEqual(vm.get('B'),-(1<<63))
    def test_increment_const_rejected(self):
        vm=self.make(headers='#DIM CONST FIXED=1')
        with self.assertRaises(EraError):vm.eval('FIXED++')
    def test_increment_string_rejected(self):
        vm=self.make()
        with self.assertRaises(EraError):vm.eval('STR++')
    def test_increment_literal_rejected(self):
        vm=self.make()
        with self.assertRaises(EraError):vm.eval('1++')
    def test_increment_initializer_rejected(self):
        with self.assertRaises(EraError):self.make(headers='#DIM CUSTOM=A++')
    def test_duplicate_first_definition_selected(self):
        vm=self.make('@MAIN\nRETURN 11\n@MAIN\nRETURN 22');self.assertEqual(vm.call('MAIN'),11);self.assertTrue(vm.program.warnings)
    def test_savenos_function_default_and_clamp(self):
        vm=self.make();self.assertEqual(vm.eval('SAVENOS()'),20)
        for n,expected in [('1',20),('40',40),('99',80)]:
            vm.data.config['表示するセーブデータ数']=n;self.assertEqual(vm.eval('SAVENOS()'),expected)
    def test_savenos_statement_dest(self):
        vm=self.script('SAVENOS A');self.assertEqual(vm.get('A'),20)
    def test_savenos_statement_result(self):
        vm=self.script('SAVENOS\nA=RESULT');self.assertEqual(vm.get('A'),20)
    def test_form_space_escape(self):
        vm=self.make();self.assertEqual(vm.format(r'a\sb\Sc'),'a b　c');self.assertEqual(vm.eval(r'"a\sb\Sc"'),'a b　c')
    def test_strlenform(self):
        vm=self.script('STRLENFORM 日本{2+3}\nA=RESULT');self.assertEqual(vm.get('A'),5)
    def test_strlenformu(self):
        vm=self.script('STRLENFORMU 日本😀{2+3}\nA=RESULT');self.assertEqual(vm.get('A'),5)
    def test_printplainform(self):
        self.script('PRINTPLAINFORM 日本{2+3}');self.assertEqual(self.output.getvalue(),'日本5')
    def test_drawlineform(self):
        self.script('DRAWLINEFORM --{2+3}--');self.assertIn('--5--',self.output.getvalue())
    def test_chkfont_explicit_cli_fallback(self):
        vm=self.make();self.assertEqual(vm.eval('CHKFONT("not an installed font")'),0)
    def test_outputlog_sandbox_location(self):
        vm=self.script('PRINTL neutral output\nOUTPUTLOG');paths=list((vm.data.root/'.pyemuera/logs').glob('*.txt'));self.assertEqual(len(paths),1);self.assertIn('neutral output',paths[0].read_text())
    def test_defaultchara_negative_one(self):
        vm=self.make();self.assertEqual(vm.get('GAMEBASE_DEFAULTCHARA'),-1)
    def test_adddefchara_adds_zero(self):
        vm=self.make('@SYSTEM_TITLE\nADDDEFCHARA\nRETURN\n',csv=CHARA);vm.call('SYSTEM_TITLE');self.assertEqual(vm.data.character_count,1);self.assertEqual(vm.get('NO:0'),0)
        invalid=self.make('@MAIN\nADDDEFCHARA\nRETURN\n',csv=CHARA)
        with self.assertRaises(EraError):invalid.call('MAIN')
        self.assertEqual(invalid.data.character_count,0)
    def test_putform_is_save_description(self):
        vm=self.script('PUTFORM neutral {2+3}');self.assertEqual(vm.get('SAVEDATA_TEXT'),'neutral 5');self.assertEqual(vm.get('SAVESTR'),'')
    def test_savegame_saveinfo_description(self):
        vm=self.make('@MAIN\nSAVEGAME\nRETURN\n@SAVEINFO\nPUTFORM desc {7}\nRETURN',inputs=['1']);vm.call('MAIN');self.assertRegex(vm.saves.inspect(1)['description'],r'^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} desc 7$') # src1824 SystemProc initializes timestamp before SAVEINFO
    def test_tab_header_audit_no_issue(self):
        vm=self.make('@MAIN\nA=TOKEN\nRETURN',headers='#DIMS\tWORDS,2\n#DIM\tNUMBERS,2\n#DEFINE\tTOKEN\t3');self.assertFalse(audit(vm.program,vm.data)['issues'])
    def test_export_sfmt_state_is_valid(self):
        vm=self.make();state=vm.rng.getstate();rec=export_randdata(state)
        self.assertEqual(rec.dims,(625,));self.assertEqual(rec.values[(624,)],624)
        self.assertTrue(any(rec.values.get((i,),0) for i in range(624)))
        parity=(rec.values.get((0,),0)&1)^(rec.values.get((3,),0)&0x13c9e684)
        self.assertEqual(parity.bit_count()%2,1);self.assertEqual(vm.rng.getstate(),state)
        self.assertEqual(rec,export_randdata(state))
    def test_export_new_game_no_all_zero_native_rng(self):
        vm=self.make();vm.saves.format='emuera-binary';vm.saves.native_rng='restore';vm.saves.write(0)
        rec=codec.decode(vm.saves.native_path(0).read_bytes()).variables['RANDDATA']
        self.assertEqual(rec.values[(624,)],624);self.assertGreater(len(rec.values),600)

class DynamicCallA4(Harness):
    def test_parenthesized_callform(self):
        vm=self.make('@MAIN\nA=7\nCALLFORM F{A}(8)\nB=RESULT\nRETURN\n@F7(ARG)\nRETURN ARG+1');vm.call('MAIN');self.assertEqual(vm.get('B'),9)
    def test_tryccallform_parentheses_existing(self):
        vm=self.make('@MAIN\nA=7\nTRYCCALLFORM F{A}(8)\nB=RESULT\nCATCH\nB=-1\nENDCATCH\nRETURN\n@F7(ARG)\nRETURN ARG+1');vm.call('MAIN');self.assertEqual(vm.get('B'),9)
    def test_tryccallform_parentheses_missing(self):
        vm=self.script('TRYCCALLFORM F{7}(8)\nB=1\nCATCH\nB=2\nENDCATCH');self.assertEqual(vm.get('B'),2)
    def test_callform_does_not_format_argument_literals(self):
        vm=self.make('@MAIN\nCALLFORM F{7}("literal{4},100%")\nRETURN\n@F7(ARGS)\nSTR \'= ARGS\nRETURN');vm.call('MAIN');self.assertEqual(vm.get('STR'),'literal{4},100%')
    def test_callform_parentheses_in_name_placeholder(self):
        vm=self.make('@MAIN\nCALLFORM F{MAX(2,7)}(8)\nB=RESULT\nRETURN\n@F7(ARG)\nRETURN ARG+1');vm.call('MAIN');self.assertEqual(vm.get('B'),9)
    def test_callform_empty_parentheses(self):
        vm=self.make('@MAIN\nCALLFORM F{7}()\nB=RESULT\nRETURN\n@F7\nRETURN 9');vm.call('MAIN');self.assertEqual(vm.get('B'),9)
    def test_callform_percent_target_and_comma_arguments(self):
        vm=self.make('@MAIN\nSTR=F7\nCALLFORM %STR%,8\nB=RESULT\nRETURN\n@F7(ARG)\nRETURN ARG+1');vm.call('MAIN');self.assertEqual(vm.get('B'),9)
