"""Neutral regressions extracted from language features, not game text/assets."""
from __future__ import annotations
import io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.data import GameData
from pyemuera.program import Program,command
from pyemuera.console import Console
from pyemuera.journal import RunJournal,load_replay
from pyemuera.audit import audit
from pyemuera.text import split_args,split_printv,load_config

NORMAL='番号,7\n名前,標準,,\n呼び名,通称,,\n基礎,0,120\n素質,2\nCFLAG,0,0\nCSTR,3,note,\n'
SPECIAL='番号,7\n名前,特別\nCFLAG,0,1\n基礎,0,150\n素質,2,5\nCSTR,3,special\n'
def spcsv(extra=None):
    return {'_fixed.config':'SPキャラを使用する:YES\n','Chara7.csv':NORMAL,'Chara7sp.csv':SPECIAL,**(extra or {})}

class SPTemplates(Harness):
    def test_normal_and_special_can_coexist(self):
        v=self.make(csv=spcsv());self.assertEqual((len(v.data.templates),len(v.data.sp_templates)),(1,1))
    def test_addsp_selects_template(self):
        v=self.script('ADDCHARA 7\nADDSPCHARA 7',csv=spcsv())
        self.assertEqual([v.get('NAME:'+str(i)) for i in range(2)],['標準','特別'])
    def test_addsp_missing_is_not_void(self):
        v=self.make('@MAIN\nADDSPCHARA 99',csv=spcsv())
        with self.assertRaises(EraError):v.call('MAIN')
        self.assertEqual(v.data.character_count,0)
    def test_base_initializes_maxbase(self):
        v=self.script('ADDCHARA 7',csv=spcsv());self.assertEqual(v.get('MAXBASE:0:0'),120)
    def test_omitted_numeric_csv_value(self):
        v=self.script('ADDCHARA 7',csv=spcsv());self.assertEqual(v.get('TALENT:0:2'),1)
    def test_blank_numeric_csv_value(self):
        v=self.script('ADDCHARA 7',csv=spcsv({'Chara7.csv':NORMAL.replace('素質,2\n','素質,2,\n')}));self.assertEqual(v.get('TALENT:0:2'),1)
    def test_duplicate_retains_first(self):
        v=self.make(csv=spcsv({'Chara7z.csv':'番号,7\n名前,later\n'}));v.data.add_character(7)
        self.assertEqual(v.get('NAME:0'),'標準');self.assertTrue(any('Duplicate' in x for x in v.data.warnings))
    def test_disabled_sp_uses_first(self):
        v=self.make(csv=spcsv({'_fixed.config':'SPキャラを使用する:NO'}));self.assertFalse(v.data.sp_templates)
    def test_getchara_prefers_normal_when_both(self):
        v=self.script('ADDSPCHARA 7\nADDCHARA 7',csv=spcsv());self.assertEqual(v.eval('GETCHARA(7,1)'),1)
    def test_getchara_second_is_not_start(self):
        v=self.script('ADDCHARA 7',csv=spcsv());self.assertEqual(v.eval('GETCHARA(7,1)'),0)
    def test_getsp_and_all(self):
        v=self.script('ADDSPCHARA 7',csv=spcsv());self.assertEqual((v.eval('GETCHARA(7)'),v.eval('GETCHARA(7,1)'),v.eval('GETSPCHARA(7)')),(-1,0,0))
    def test_save_load_sp_instances(self):
        v=self.script('ADDCHARA 7\nADDSPCHARA 7',csv=spcsv());v.saves.write(0,'neutral');v.data.reorder_characters([0]);self.assertTrue(v.saves.load(0));self.assertEqual(v.get('NAME:1'),'特別')

CSV_CASES=[('exists','EXISTCSV(7)',1),('sp_exists','EXISTCSV(7,1)',1),('absent','EXISTCSV(99,1)',0),('normal_name','CSVNAME(7)','標準'),('sp_name','CSVNAME(7,1)','特別'),('callname','CSVCALLNAME(7)','通称'),('string_array','CSVCSTR(7,3)','note'),('sp_string_array','CSVCSTR(7,3,1)','special'),('trait_default','CSVTALENT(7,2)',1),('sp_trait','CSVTALENT(7,2,1)',5),('sp_base','CSVBASE(7,0,1)',150)]
for name,expr,value in CSV_CASES:
    def run(self,expr=expr,value=value):v=self.make(csv=spcsv());self.assertEqual(v.eval(expr),value)
    setattr(SPTemplates,'test_csv_'+name,run)

class ConfigAndSyntax(Harness):
    def test_config_precedence(self):
        v=self.make(csv={'_default.config':'FontSize:11\n','_fixed.config':'FontSize:13\n'})
        (v.root/'emuera.config').write_text('FontSize:12\nPrintCLength:30\n')
        config=load_config(v.root)
        self.assertEqual((config['FontSize'],config['PrintCLength']),('13','30'))
    def test_config_sources_in_inventory(self):
        v=self.make(csv={'_fixed.config':'X:fixed'});self.assertIn('CSV/_fixed.config',[r['file'] for r in v.data.files])
    def test_rename_expansion(self):
        v=self.script('A=[[VALUE]]\nPRINTFORM {A}',csv={'_fixed.config':'_Rename.csvを利用する:YES','_Rename.csv':'17,VALUE'})
        self.assertEqual(self.output.getvalue(),'17')
    def test_rename_disabled(self):
        v=self.make('@MAIN\nA=[[VALUE]]',csv={'_Rename.csv':'17,VALUE'})
        with self.assertRaises(EraError):v.call('MAIN')
    def test_no_fake_decrement_in_print(self):
        for s in ['PRINT -------','PRINTFORMW --{6}--','PRINT ==','CUSTOMDRAWLINE -=']:
            self.assertNotEqual(command(s)[0],'_ASSIGN')
    def test_raw_string_assignment_ends_in_dashes(self):
        v=self.script('STR = line--');self.assertEqual(v.get('STR'),'line--')
    def test_real_decrement(self):
        v=self.script('A:2=8\nA:2--');self.assertEqual(v.get('A:2'),7)
    def test_printv_old_raw_literal(self):
        self.script("A=3\nPRINTVL 'LV,A,'(,A*2,')");self.assertEqual(self.output.getvalue(),'LV3(6)\n')
    def test_printv_raw_commas_not_parentheses(self):
        self.assertEqual(split_printv("'(,MAX(1,3),')"),[(True,'('),(False,'MAX(1,3)'),(True,')')])
    def test_printv_audit_does_not_parse_literal(self):
        v=self.make("@MAIN\nPRINTVL 'LV,1,'),2\nCUSTOMDRAWLINE -=");self.assertFalse(audit(v.program,v.data)['issues'])
    def test_missing_function_stays_error(self):
        v=self.make('@MAIN\nCALL MISSING_HELPER');r=audit(v.program,v.data)
        self.assertEqual(r['issues'][0]['code'],'E_FUNCTION')
        with self.assertRaises(EraError):v.call('MAIN')
    def test_bare_conditional_string(self):
        v=self.make();self.assertEqual(v.eval(r'\@1?yes#no\@'),'yes')
    def test_conditional_lazy(self):
        v=self.make();self.assertEqual(v.eval(r'\@0?{1/0}#safe\@'),'safe')
    def test_conditional_argument_with_comma(self):
        v=self.make();self.assertEqual(v.eval(r'STRLENS(\@1?a,b#c\@)'),3)
    def test_form_with_nested_quoted_expression(self):
        v=self.make();self.assertEqual(v.eval(' @"%"x"+(" "*3)%" '),'x   ')
    def test_form_quote_placeholder(self):
        v=self.make();self.assertEqual(v.eval('@"%"quoted"%:{MAX(1,3)}"'),'quoted:3')
    def test_nested_form_inside_placeholder(self):
        v=self.make();self.assertEqual(v.eval('@"outer=%@"inner={4}"%"'),'outer=inner=4')
    def test_escaped_form_literal(self):
        v=self.make();self.assertEqual(v.eval(r'@"\{plain\}"'),'{plain}')
    def test_conditional_returnf(self):
        v=self.make('@F\n#FUNCTIONS\nRETURNF \\@1?pass#fail\\@');self.assertEqual(v.eval('F()'),'pass')
    def test_unicode_strlen_alias(self):
        v=self.make();self.assertEqual(v.eval('STRLENSU("日本A")'),3)
    def test_unicode_utf16_surrogate_count(self):
        v=self.make();self.assertEqual(v.eval('STRLENSU("😀")'),2)
    def test_printc_config_and_suffix(self):
        self.script('PRINTCD x\nPRINTFORMCD {4}',csv={'_fixed.config':'PRINTCを並べる数:2\nPRINTCの文字数:5'})
        self.assertEqual(self.output.getvalue(),'    x    4')
    def test_printsingle_empty_newline(self):
        self.script('PRINTSINGLEFORM');self.assertEqual(self.output.getvalue(),'\n')
    def test_printsingle_separate_lines(self):
        self.script('PRINT prefix\nPRINTSINGLEFORM x{4}\nPRINT suffix');self.assertEqual(self.output.getvalue(),'prefix\nx4\nsuffix')
    def test_printsingle_skip_no_eval(self):
        self.script('SKIPDISP 1\nPRINTSINGLEFORM {1/0}');self.assertEqual(self.output.getvalue(),'')
    def test_setfont_state(self):
        v=self.script('SETFONT "Example Font"');self.assertEqual(v.eval('GETFONT()'),'Example Font')
    def test_printc_constant_uses_config(self):
        v=self.make(csv={'_fixed.config':'PRINTCを並べる数:2\nPRINTCの文字数:17'})
        self.assertEqual((v.eval('PRINTCPERLINE'),v.eval('PRINTCLENGTH')),(2,17))
    def test_csv_duplicate_symbol_first_wins(self):
        v=self.make(csv={'Abl.csv':'2,Ability\n4,Ability'})
        self.assertEqual(v.data.index_of('ABL','Ability'),2)
    def test_empty_shop_names_hidden(self):
        self.script('ITEMSALES:3=1\nPRINT_SHOPITEM');self.assertEqual(self.output.getvalue(),'')

class Sorting(Harness):
    def setup_sort(self):
        return self.script('ADDVOIDCHARA\nADDVOIDCHARA\nADDVOIDCHARA\nMASTER=1\nTARGET=0\nASSI=2\nNO:0=20\nNO:1=99\nNO:2=10\nCFLAG:0:4=200\nCFLAG:2:4=100')
    def test_numeric_sort(self):
        v=self.setup_sort()
        from pyemuera.commands import execute_command
        execute_command(v,'SORTCHARA','NO')
        self.assertEqual([v.get('NO:'+str(i)) for i in range(3)],[10,99,20])
        self.assertEqual((v.get('MASTER'),v.get('TARGET'),v.get('ASSI')),(1,2,0))
        self.assertEqual(v.get('CFLAG:2:4'),200)
    def test_sort_back_keyword(self):
        v=self.setup_sort()
        from pyemuera.commands import execute_command
        execute_command(v,'SORTCHARA','BACK');self.assertEqual(v.get('NO:0'),20)
    def test_sort_character_array(self):
        v=self.setup_sort()
        from pyemuera.commands import execute_command
        execute_command(v,'SORTCHARA','CFLAG:4');self.assertEqual(v.get('NO:0'),10)
    def test_sort_invalid_noncharacter(self):
        v=self.setup_sort()
        from pyemuera.commands import execute_command
        with self.assertRaises(EraError):execute_command(v,'SORTCHARA','A')

class Timers(Harness):
    def test_twait_no_wait(self):
        with patch('pyemuera.console.time.sleep') as sleep:self.script('TWAIT 5000,1');sleep.assert_not_called()
    def test_twait_force_duration(self):
        c=Console(output=io.StringIO())
        with patch('pyemuera.console.time.sleep') as sleep:c.timed_wait(250,True);sleep.assert_called_once_with(.25)
    def test_twait_replay_enter(self):
        j=RunJournal(record_inputs=True);c=Console([''],io.StringIO(),journal=j);c.timed_wait(250)
        self.assertEqual(j.records,[{'kind':'timed_wait','text':''}])
    def test_tinput_replay_value(self):
        v=self.script('TINPUT 5000,-1,0\nA=RESULT',inputs=['9']);self.assertEqual(v.get('A'),9)
    def test_tinput_timeout_replay(self):
        v=self.script('TINPUT 500,-7,0,"expired"\nA=RESULT',inputs=[{'kind':'timed_integer','text':'','timeout':True}]);self.assertEqual(v.get('A'),-7);self.assertEqual(self.output.getvalue(),'expired\n')
    def test_tinputs_timeout(self):
        v=self.script('TINPUTS 1,"fallback",0,""',inputs=[{'kind':'timed_string','text':'','timeout':True}]);self.assertEqual(v.get('RESULTS'),'fallback')
    def test_tinput_nonpositive_disables_deadline(self):
        # src1824 starts a timer only for TimeLimit > 0; blank accepts fallback.
        v=self.script('TINPUT 0,-3,0,""\nA=RESULT',inputs=['']);self.assertEqual(v.get('A'),-3)
    def test_tinput_wrong_type(self):
        v=self.make('@MAIN\nTINPUT 0,"bad",0');self.assertRaises(EraError,v.call,'MAIN')
    def test_twait_negative(self):
        v=self.make('@MAIN\nTWAIT -1,1');self.assertRaises(EraError,v.call,'MAIN')
    def test_timeout_rejected_at_untimed_input(self):
        c=Console([{'kind':'integer','text':'','timeout':True}],io.StringIO());self.assertRaises(EraError,c.input)
    def test_record_actual_timeout(self):
        j=RunJournal(record_inputs=True);c=Console(output=io.StringIO(),journal=j)
        self.assertEqual(c.input(default=5,kind='timed_integer',timeout_ms=0),5);self.assertTrue(j.records[0]['timeout'])
