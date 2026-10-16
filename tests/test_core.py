from __future__ import annotations
import io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from pyemuera.program import Program
from pyemuera.data import GameData
from pyemuera.runtime import VM
from pyemuera.console import Console
from pyemuera.errors import EraError
from pyemuera.audit import audit
from pyemuera.text import read_text,split_args,find_assignment,strip_comment

ROOT=Path(__file__).resolve().parents[1]

class Harness(unittest.TestCase):
    def make(self,source='@MAIN\nRETURN\n',headers='',csv=None,encoding='utf-8-sig',inputs=None,**kw):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        (root/'ERB').mkdir();(root/'CSV').mkdir()
        (root/'ERB'/'Main.ERB').write_text(source,encoding=encoding,newline='\n')
        if headers:(root/'ERB'/'Header.ERH').write_text(headers,encoding=encoding,newline='\n')
        for name,content in (csv or {}).items():(root/'CSV'/name).write_text(content,encoding=encoding,newline='\n')
        self.output=io.StringIO();console=Console(inputs,self.output,no_wait=True)
        vm=VM(Program(root),GameData(root),console,seed=123,**kw)
        self.vm=vm;return vm
    def script(self,body,**kw):
        vm=self.make('@MAIN\n'+body+'\n',**kw);vm.call('MAIN');return vm
    def error(self,text,code):
        with self.assertRaises(EraError) as cm:self.vm.eval(text)
        self.assertEqual(cm.exception.code,code)

EXPR_CASES=[
('multiplication','2+3*4',14),('parentheses','(2+3)*4',20),('unary','~-1',0),
('hex_binary','0xFF+0b10',257),('p_literal','3p4',48),('e_literal','13e3',13000),
('decimal_leadingzero','012',12),('integer64','9007199254740993+2',9007199254740995),
('overflow','9223372036854775807+1',-9223372036854775808),
('negative_div','-7/3',-2),('negative_mod','-7%3',-1),('negative_denominator','7%-3',1),
('bitwise_group','1|2&4',0),('logical_group','1||0&&0',0),
('short_and','0&&(1/0)',0),('short_or','1||(1/0)',1),('short_nand','0!&(1/0)',1),
('short_nor','1!|(1/0)',0),('ternary_lazy','1?9#(1/0)',9),('ternary_nested','0?4#1?5#6',5),
('xor','1^^1',0),('string_concat','"hello"+" world"','hello world'),
('string_repeat','"ab"*3','ababab'),('string_compare','"b">"a"',1),
('japanese_length','STRLENS("日本A")',5),('unicode_length','STRLENSU("日本A")',3),
('max','MAX(1,8,4)',8),('sqrt','SQRT(81)',9),('bits','GETBIT(8,3)',1),
('format','@"num={2+3}"','num=5'),('formatstring','@"%TOSTR(4)%"','4'),
('empty_arguments','RAND(1)',0),('clamp','LIMIT(100,2,5)',5),('range','INRANGE(2,2,4)',1),
('replace','REPLACE("abcabc","b","B")','aBcaBc'),('toint','TOINT("0xff")',255)]
class Expressions(Harness):
    def test_type_error(self):self.make();self.error('1+"x"','E_TYPE')
    def test_div_zero(self):self.make();self.error('1/0','E_ARITH')
    def test_bad_syntax(self):self.make();self.error('1 +','E_SYNTAX')
    def test_undefined_is_not_zero(self):self.make();self.error('MISSING','E_VARIABLE')
    def test_injection(self):self.make();self.error('__import__("os")','E_FUNCTION')
    def test_negative_index(self):self.make();self.error('A:(-1)','E_INDEX')
    def test_out_of_bounds(self):self.make();self.error('A:1000','E_INDEX')
for name,expr,expected in EXPR_CASES:
    def run(self,expr=expr,expected=expected):self.make();self.assertEqual(self.vm.eval(expr),expected)
    setattr(Expressions,'test_'+name,run)

class Runtime(Harness):
    def test_assignment_arrays(self):
        vm=self.script('A:3 = 4,5,6\nA:4 += 2\nA:5--');self.assertEqual([vm.get('A:'+str(i)) for i in range(3,6)],[4,7,5])
    def test_array_write_preserves_prefix_before_bounds_error(self):
        vm=self.make('@MAIN\nA:999 = 1,2\nRETURN')
        with self.assertRaises(EraError):vm.call('MAIN')
        # v24 Int1DVariableToken.SetValue loops before catching bounds errors.
        self.assertEqual(vm.get('A:999'),1)
    def test_strings(self):
        vm=self.script('STR = 日本{2+3}\nSTR:1 \'= "語"+"です"\nPRINTFORML %STR%:%STR:1%')
        self.assertEqual(self.output.getvalue(),'日本5:語です\n')
    def test_if_branches(self):
        vm=self.script('IF 0\nA=1\nELSEIF 1\nA=2\nELSE\nA=3\nENDIF');self.assertEqual(vm.get('A'),2)
    def test_sif(self):
        vm=self.script('SIF 0\nA=4\nSIF 1\nB=3');self.assertEqual((vm.get('A'),vm.get('B')),(0,3))
    def test_for_both_directions(self):
        vm=self.script('FOR A,0,5\nB+=A\nNEXT\nFOR A,5,0,-2\nC+=A\nNEXT')
        self.assertEqual((vm.get('B'),vm.get('C')),(10,9))
    def test_repeat_count_doc(self):
        self.script('REPEAT 5\nSIF COUNT==2\nCONTINUE\nSIF COUNT==4\nBREAK\nPRINTFORML {COUNT}\nREND\nPRINTFORML {COUNT}')
        self.assertEqual(self.output.getvalue(),'0\n1\n3\n5\n')
    def test_while_and_do(self):
        vm=self.script('WHILE A<3\nA++\nWEND\nDO\nB++\nLOOP B<2');self.assertEqual((vm.get('A'),vm.get('B')),(3,2))
    def test_nested_break(self):
        vm=self.script('FOR A,0,3\nFOR B,0,9\nC++\nBREAK\nNEXT\nNEXT');self.assertEqual(vm.get('C'),3)
    def test_select_range(self):
        vm=self.script('SELECTCASE 7\nCASE 0,2\nA=1\nCASE 5 TO 8\nA=2\nCASE IS >= 9\nA=3\nCASEELSE\nA=4\nENDSELECT');self.assertEqual(vm.get('A'),2)
    def test_select_default(self):
        vm=self.script('SELECTCASE "x"\nCASE "y"\nA=1\nCASEELSE\nA=9\nENDSELECT');self.assertEqual(vm.get('A'),9)
    def test_call_defaults(self):
        vm=self.make('@MAIN\nCALL F,5\nA=RESULT\nRETURN\n@F(ARG,ARGS="text")\nPRINTSL ARGS\nRETURN ARG+1')
        vm.call('MAIN');self.assertEqual(vm.get('A'),6);self.assertEqual(self.output.getvalue(),'text\n')
    def test_call_missing_optional(self):
        vm=self.make('@MAIN\nCALL F,,8\nRETURN\n@F(ARG=3,ARG:1=4)\nRETURN ARG+ARG:1');self.assertEqual(vm.call('MAIN'),0)
        self.assertEqual(vm.get('ARG@F'),3)
    def test_static_local(self):
        vm=self.make('@MAIN\nCALL F\nCALL F\nRETURN RESULT\n@F\nLOCAL++\nRETURN LOCAL');self.assertEqual(vm.call('MAIN'),2)
    def test_dynamic_private(self):
        vm=self.make('@MAIN\nCALL F\nCALL F\nRETURN RESULT\n@F\n#DIM DYNAMIC TEMP\nTEMP++\nRETURN TEMP');self.assertEqual(vm.call('MAIN'),1)
    def test_static_private(self):
        vm=self.make('@MAIN\nCALL F\nCALL F\nRETURN RESULT\n@F\n#DIM TEMP\nTEMP++\nRETURN TEMP');self.assertEqual(vm.call('MAIN'),2)
    def test_expression_method(self):
        vm=self.make('@MAIN\nA=DOUBLE(6)\nRETURN\n@DOUBLE(ARG)\n#FUNCTION\nRETURNF ARG*2');vm.call('MAIN');self.assertEqual(vm.get('A'),12)
    def test_string_method(self):
        vm=self.make('@MAIN\nSTR \'= WORD("a")\nRETURN\n@WORD(ARGS)\n#FUNCTIONS\nRETURNF ARGS+"b"');vm.call('MAIN');self.assertEqual(vm.get('STR'),'ab')
    def test_expression_short_circuit_side_effect(self):
        vm=self.make('@MAIN\nA=1||TOUCH()\nRETURN\n@TOUCH\n#FUNCTION\nB++\nRETURNF 1');vm.call('MAIN');self.assertEqual(vm.get('B'),0)
    def test_callf_keeps_result(self):
        vm=self.make('@MAIN\nRESULT=77\nCALLF TOUCH,4\nA=RESULT\nRETURN\n@TOUCH(ARG)\n#FUNCTION\nB=ARG\nRETURNF 999');vm.call('MAIN');self.assertEqual((vm.get('A'),vm.get('B')),(77,4))
    def test_ref_parameter(self):
        vm=self.make('@MAIN\nCALL F,A\nRETURN\n@F(DEST)\n#DIM REF DEST\nDEST:2=42\nRETURN');vm.call('MAIN');self.assertEqual(vm.get('A:2'),42)
    def test_multidimensional(self):
        vm=self.script('GRID:2:3=19',headers='#DIM GRID,3,4');self.assertEqual(vm.get('GRID:2:3'),19)
    def test_callform(self):
        vm=self.make('@MAIN\nA=7\nCALLFORM F{A}, 9\nRETURN RESULT\n@F7(ARG)\nRETURN ARG+1');self.assertEqual(vm.call('MAIN'),10)
    def test_trycall_catch(self):
        vm=self.script('TRYCCALL ABSENT\nA=1\nCATCH\nA=2\nENDCATCH');self.assertEqual(vm.get('A'),2)
    def test_trycall_missing(self):
        vm=self.script('TRYCALL NOTHING\nA=1');self.assertEqual(vm.get('A'),1)
    def test_goto(self):
        vm=self.script('GOTO END\nA=9\n$END\nB=4');self.assertEqual((vm.get('A'),vm.get('B')),(0,4))
    def test_tail_jump_result(self):
        vm=self.make('@MAIN\nJUMP F\n@F\nRETURN 99');self.assertEqual(vm.call('MAIN'),99)
    def test_deep_iterative_call(self):
        vm=self.make('@MAIN\nCALL F\nRETURN\n@F\nA++\nIF A<1200\nCALL F\nENDIF\nRETURN');vm.call('MAIN');self.assertEqual(vm.get('A'),1200)
    def test_instruction_budget(self):
        vm=self.make('@MAIN\nWHILE 1\nWEND',max_steps=20)
        with self.assertRaises(EraError) as cm:vm.call('MAIN')
        self.assertEqual(cm.exception.code,'E_LIMIT')
    def test_unknown_command_location(self):
        vm=self.make('@MAIN\nSOMEUNKNOWNCOMMAND 1')
        with self.assertRaises(EraError) as cm:vm.call('MAIN')
        self.assertEqual(cm.exception.location.line,2);self.assertTrue(cm.exception.era_stack)
    def test_input_replay(self):
        vm=self.script('INPUT\nA=RESULT\nINPUTS\nSTR \'= RESULTS',inputs=['42','日本語']);self.assertEqual((vm.get('A'),vm.get('STR')),(42,'日本語'))
    def test_input_eof_not_zero(self):
        vm=self.make('@MAIN\nINPUT',inputs=[])
        with self.assertRaises(EraError) as cm:vm.call('MAIN')
        self.assertEqual(cm.exception.code,'E_INPUT_EOF')
    def test_printdata(self):
        self.script('PRINTDATAL\nDATALIST\nDATA first\nDATAFORM {2+3}\nENDLIST\nENDDATA');self.assertEqual(self.output.getvalue(),'first\n5\n')
    def test_macro_precedence(self):
        vm=self.script('A=TOKEN*3',headers='#DEFINE TOKEN 1+2');self.assertEqual(vm.get('A'),7)
    def test_preprocessor_macro(self):
        vm=self.make('@MAIN\n[IF EXIST]\nA=7\n[ELSE]\nA=8\n[ENDIF]\nRETURN',headers='#DEFINE EXIST 1');vm.call('MAIN');self.assertEqual(vm.get('A'),7)
    def test_preprocessor_skip(self):
        vm=self.script('[SKIPSTART]\ninvalid code ???\n[SKIPEND]\nA=3');self.assertEqual(vm.get('A'),3)
    def test_const_and_initializer(self):
        vm=self.script('A=CAP',headers='#DIM CONST CAP=12\n#DIMS WORDS,2="a","b"');self.assertEqual(vm.get('A'),12)
        with self.assertRaises(EraError):vm.set('CAP',4)
    def test_const_dependency(self):
        vm=self.script('A=TOTAL',headers='#DIM CONST TOTAL=OTHER+1\n#DIM CONST OTHER=9');self.assertEqual(vm.get('A'),10)
    def test_multiple_event_order(self):
        vm=self.make('@MAIN\nCALLEVENT EVENTX\nRETURN\n@EVENTX\n#LATER\nPRINT later\nRETURN\n@EVENTX\nPRINT normal\nRETURN\n@EVENTX\n#PRI\nPRINT first\nRETURN')
        vm.call('MAIN');self.assertEqual(self.output.getvalue(),'firstnormallater')
    def test_event_only(self):
        vm=self.make('@MAIN\nCALLEVENT EVENTX\nRETURN\n@EVENTX\n#ONLY\nA=1\nRETURN\n@EVENTX\nA=2\nRETURN');vm.call('MAIN');self.assertEqual(vm.get('A'),1)
    def test_sort_and_sum(self):
        vm=self.script('A=5,1,3\nARRAYSORT A,FORWARD,0,3\nB=SUMARRAY(A,0,3)');self.assertEqual([vm.get('A:'+str(i)) for i in range(3)],[1,3,5]);self.assertEqual(vm.get('B'),9)
    def test_shift(self):
        vm=self.script('A=1,2,3,4\nARRAYSHIFT A,1,0,0,4');self.assertEqual([vm.get('A:'+str(i)) for i in range(4)],[0,1,2,3])
    def test_split_join(self):
        vm=self.script('SPLIT "a/b/c","/",STR\nSTRJOIN STR,"-",0,3\nSTR:10 \'= RESULTS');self.assertEqual(vm.get('STR:10'),'a-b-c')

CHARA={'Chara0.csv':'番号,0\n名前,旅人\n基礎,0,100\n能力,0,3\n','Chara5.csv':'番号,5\n名前,商人\n','ABL.csv':'0,技術\n','BASE.csv':'0,体力\n','PALAM.csv':'0,練習\n','Item.csv':'0,道具,25\n','StrName.csv':'0,挨拶\n','Str.csv':'0,ようこそ\n','GameBase.csv':'タイトル,試験\nコード,123\nバージョン,1\n'}
class DataPersistence(Harness):
    def test_cp932_csv_symbols(self):
        vm=self.script('ADDCHARA 0\nTARGET=0\nA=ABL:技術\nPRINTFORML %NAME% %STR:挨拶%',csv=CHARA,encoding='cp932')
        self.assertEqual(vm.get('A'),3);self.assertEqual(self.output.getvalue(),'旅人 ようこそ\n')
    def test_character_base(self):
        vm=self.script('ADDCHARA 0\nTARGET=0',csv=CHARA);self.assertEqual(vm.get('MAXBASE:体力'),100)
    def test_character_varset_target_only(self):
        vm=self.script('ADDCHARA 0,5\nTARGET=0\nCFLAG:0:1=8\nCFLAG:1:1=9\nVARSET CFLAG',csv=CHARA)
        self.assertEqual((vm.get('CFLAG:0:1'),vm.get('CFLAG:1:1')),(0,9))
    def test_character_remove_reindex(self):
        vm=self.script('ADDCHARA 0,5\nTARGET=1\nDELCHARA 0',csv=CHARA)
        # src1824 DelCharacter removes a record; it does not remap TARGET.
        self.assertEqual((vm.get('TARGET'),vm.get('NAME:0')),(1,'商人'))
        with self.assertRaises(EraError):vm.get('NAME')
    def test_character_copy(self):
        vm=self.script('ADDCHARA 0\nADDCOPYCHARA 0\nTARGET=1',csv=CHARA);self.assertEqual(vm.get('NAME'),'旅人')
    def test_invalid_character(self):
        vm=self.make(csv=CHARA)
        with self.assertRaises(EraError) as cm:vm.get('NAME:0')
        self.assertEqual(cm.exception.code,'E_CHARACTER')
    def test_empty_character_aggregate(self):
        vm=self.make(csv=CHARA)
        # src1824 requires the start position to select an existing character.
        with self.assertRaises(EraError):vm.eval('SUMCARRAY(CFLAG:0:0)')
    def test_save_roundtrip_rng(self):
        vm=self.script('ADDCHARA 0\nTARGET=0\nMONEY=777\nSTR \'= "hello"',csv=CHARA)
        vm.saves.write(2,'test');expected=vm.rng.randrange(100000)
        vm.set('MONEY',1);vm.set('STR','bad');vm.saves.load(2)
        self.assertEqual((vm.get('MONEY'),vm.get('STR')),(777,'hello'));self.assertEqual(vm.rng.randrange(100000),expected)
    def test_global_save_separate(self):
        vm=self.make();vm.set('GLOBAL',99);vm.saves.write('global');vm.saves.write(0);vm.set('GLOBAL',33);vm.saves.load(0)
        self.assertEqual(vm.get('GLOBAL'),33);vm.saves.load('global');self.assertEqual(vm.get('GLOBAL'),99)
    def test_saveglobal_command(self):
        vm=self.script('GLOBAL=55\nSAVEGLOBAL\nGLOBAL=0\nLOADGLOBAL');self.assertEqual(vm.get('GLOBAL'),55)
    def test_load_missing(self):
        vm=self.make();self.assertEqual(vm.saves.load(4),0)
    def test_malformed_save_atomic(self):
        vm=self.make();vm.set('A',7);vm.saves.write(0);p=vm.saves.path(0);raw=json.loads(p.read_text());raw['variables']['A']['values']=[[[0],999],[[2000],1]];p.write_text(json.dumps(raw))
        with self.assertRaises(EraError):vm.saves.load(0)
        self.assertEqual(vm.get('A'),7)
    def test_missing_variable_atomic(self):
        vm=self.make();vm.saves.write(0);p=vm.saves.path(0);raw=json.loads(p.read_text());del raw['variables']['A'];p.write_text(json.dumps(raw))
        with self.assertRaises(EraError):vm.saves.load(0)
    def test_native_save_untouched(self):
        vm=self.make();p=vm.root/'save00.sav';p.write_bytes(b'native');vm.saves.write(0);self.assertEqual(p.read_bytes(),b'native')
    def test_save_traversal(self):
        vm=self.make()
        with self.assertRaises(EraError):vm.saves.path(-1)
    def test_csv_quote_not_rfc(self):
        vm=self.make(csv={'ABL.csv':'0,"Quoted name"\n'});self.assertEqual(vm.get('ABLNAME:0'),'"Quoted name"')
    def test_size_and_readonly(self):
        vm=self.make(csv={'VariableSize.csv':'A,3\nABL,150\n','ABL.csv':'149,大きい添字\n'})
        self.assertEqual(vm.eval('VARSIZE("A")'),1000);self.assertEqual(vm.get('ABLNAME:149'),'大きい添字')
        with self.assertRaises(EraError):vm.set('ABLNAME:0','bad')

class FlowAndCLI(Harness):
    def test_system_title_return_error(self):
        vm=self.make('@SYSTEM_TITLE\nRETURN')
        with self.assertRaises(EraError) as cm:vm.run()
        self.assertEqual(cm.exception.code,'E_FLOW')
    def test_begin_unwinds_stack(self):
        vm=self.make('@SYSTEM_TITLE\nCALL F\nA=9\nQUIT\n@F\nBEGIN FIRST\n@EVENTFIRST\nA=3\nQUIT');vm.run();self.assertEqual(vm.get('A'),9)
    def test_shop_purchase_and_exit(self):
        vm=self.make('@SYSTEM_TITLE\nMONEY=50\nITEMSALES:0=1\nBEGIN SHOP\n@SHOW_SHOP\nPRINT_SHOPITEM\nRETURN\n@USERSHOP\nQUIT',csv=CHARA,inputs=['0','100']);vm.run()
        self.assertEqual((vm.get('MONEY'),vm.get('ITEM:0')),(25,1))
    def test_train_basic(self):
        vm=self.make('@SYSTEM_TITLE\nADDCHARA 0\nTARGET=0\nBEGIN TRAIN\n@COM0\nUP:0=12\nUPCHECK\nRETURN 1\n@USERCOM\nQUIT',csv={**CHARA,'Train.csv':'0,練習\n'},inputs=['0','100']);vm.run();self.assertEqual(vm.get('PALAM:0'),12)
    def test_audit_unknown(self):
        vm=self.make('@MAIN\nNOT_IMPLEMENTED\nCALL MISSING\nRETURN');r=audit(vm.program,vm.data);self.assertEqual(len(r['issues']),2);self.assertFalse(r['gameplay_verified'])
    def test_audit_does_not_execute(self):
        vm=self.make('@MAIN\nA=999\nQUIT');audit(vm.program,vm.data);self.assertEqual(vm.get('A'),0)
    def test_cli_run(self):
        vm=self.make('@SYSTEM_TITLE\nPRINTL hello-cli\nQUIT')
        p=subprocess.run([sys.executable,'-m','pyemuera',str(vm.root)],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('hello-cli',p.stdout)
    def test_cli_report(self):
        vm=self.make('@MAIN\nNOT_YET\nRETURN');report=vm.root/'report.json'
        p=subprocess.run([sys.executable,'-m','pyemuera',str(vm.root),'--check','--report',str(report)],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,2,p.stderr);self.assertTrue(report.exists());self.assertIn('NOT_YET',report.read_text())
    def test_cli_single_erb(self):
        vm=self.make('@MAIN\nPRINTL single\nRETURN')
        p=subprocess.run([sys.executable,'-m','pyemuera',str(vm.root/'ERB/Main.ERB'),'--entry','MAIN'],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('single',p.stdout)
    def test_cli_error_report(self):
        vm=self.make('@MAIN\nA=1/0');p=vm.root/'error.json'
        r=subprocess.run([sys.executable,'-m','pyemuera',str(vm.root),'--entry','MAIN','--error-report',str(p)],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(r.returncode,1,r.stderr);self.assertEqual(json.loads(p.read_text())['error']['line'],2)
    def test_terminal_control_sanitization(self):
        out=io.StringIO();con=Console(output=out);con.write('\x1b]0;bad\x07hello\n');self.assertNotIn('\x1b',out.getvalue());self.assertNotIn('\x07',out.getvalue())
    def test_lexer_comments(self):
        self.assertEqual(strip_comment('STR \'= "a;b" ;comment'),'STR \'= "a;b" ')
        self.assertEqual(split_args('A:(1+2),"a,b",F(1,2)'),['A:(1+2)','"a,b"','F(1,2)'])

if __name__=='__main__':unittest.main()
