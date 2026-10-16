"""Non-game regression fixtures for candidate1, derived from supplied src1824.
Source anchors and tested limits are recorded in verification/a10_source_evidence.json.
"""
import copy,json
from test_core import Harness,CHARA
from pyemuera.errors import EraError
from pyemuera.expr import parse
from pyemuera.program import command
from pyemuera.data import gamebase_integer,GameData
from pyemuera.registry import validate_document,VARIABLE_SPECS,describe
from pyemuera.audit import audit

class MethodEnds(Harness):
    def test_empty_numeric_default(self):
        vm=self.make('@FN\n#FUNCTION');self.assertEqual(vm.eval('FN()'),0)
    def test_empty_string_default(self):
        vm=self.make('@FN\n#FUNCTIONS');self.assertEqual(vm.eval('FN()'),'')
    def test_numeric_end_preserves_result(self):
        vm=self.make('@FN\n#FUNCTION\nA=17');vm.set('RESULT',44);self.assertEqual(vm.eval('FN()'),0);self.assertEqual((vm.get('A'),vm.get('RESULT')),(17,44))
    def test_string_end_preserves_results(self):
        vm=self.make('@FN\n#FUNCTIONS\nA=17');vm.set('RESULTS','old');self.assertEqual(vm.eval('FN()'),'');self.assertEqual(vm.get('RESULTS'),'old')
    def test_conditional_default_vs_explicit_numeric(self):
        vm=self.make('@FN(ARG)\n#FUNCTION\nSIF ARG\nRETURNF 42')
        self.assertEqual((vm.eval('FN(0)'),vm.eval('FN(1)')),(0,42))
    def test_conditional_default_vs_explicit_string(self):
        vm=self.make('@FN(ARG)\n#FUNCTIONS\nSIF ARG\nRETURNF "answer"')
        self.assertEqual((vm.eval('FN(0)'),vm.eval('FN(1)')),('','answer'))
    def test_callf_side_effect_and_continuation(self):
        vm=self.make('@MAIN\nRESULT=77\nCALLF FN,"CALC"\nA=RESULT\nB=FN("GET")\nRETURN\n@FN(ARGS)\n#FUNCTION\nSIF ARGS=="GET"\nRETURNF LOCAL\nLOCAL=19')
        vm.call('MAIN');self.assertEqual((vm.get('A'),vm.get('B')),(77,19))
    def test_callformf_string_default(self):
        vm=self.script('CALLFORMF FN{1}\nB=A\nRETURN\n@FN1\n#FUNCTIONS\nA=17');self.assertEqual(vm.get('B'),17)
    def test_default_does_not_run_next_function(self):
        vm=self.make('@F\n#FUNCTION\n@G\n#FUNCTION\nA=99\nRETURNF 12');self.assertEqual(vm.eval('F()'),0);self.assertEqual(vm.get('A'),0)
    def test_nested_default_result(self):
        vm=self.make('@F\n#FUNCTION\nRETURNF G()+7\n@G\n#FUNCTION');self.assertEqual(vm.eval('F()'),7)
    def test_loop_ends_without_return(self):
        vm=self.make('@F\n#FUNCTION\nFOR LOCAL,0,3\nA++\nNEXT');self.assertEqual(vm.eval('F()'),0);self.assertEqual(vm.get('A'),3)
    def test_bare_returnf_default(self):
        for attr,expected in [('FUNCTION',0),('FUNCTIONS','')]:
            vm=self.make('@F\n#'+attr+'\nRETURNF');self.assertEqual(vm.eval('F()'),expected)
    def test_explicit_return_is_still_not_method_safe(self):
        # ProcessState.Return has a fallback, but ErbLoader marks RETURN invalid
        # inside a method. Do not turn that internal path into legal ERB syntax.
        vm=self.make('@F\n#FUNCTION\nRETURN 5')
        with self.assertRaises(EraError) as cm:vm.eval('F()')
        self.assertEqual(cm.exception.code,'E_METHOD_CONTEXT')
    def test_normal_fallthrough_sets_result_zero(self):
        vm=self.make('@MAIN\nA=1');vm.set('RESULT',55);self.assertEqual(vm.call('MAIN'),0);self.assertEqual(vm.get('RESULT'),0)
    def test_returnf_wrong_type_remains_error(self):
        for attr,expr in [('FUNCTION','"text"'),('FUNCTIONS','22')]:
            vm=self.make('@F\n#'+attr+'\nRETURNF '+expr)
            with self.assertRaises(EraError) as cm:vm.eval('F()')
            self.assertEqual(cm.exception.code,'E_TYPE')

class LexicalA10(Harness):
    def test_fullwidth_slash_csv_index(self):
        vm=self.script('ADDCHARA 0\nTARGET=0\nTALENT:区分／別名=1\nA=TALENT:区分／別名',csv={**CHARA,'Talent.csv':'171,区分／別名'});self.assertEqual(vm.get('A'),1)
    def test_fullwidth_slash_is_not_ascii_division(self):
        vm=self.make(headers='#DIM 区分／別名=30');self.assertEqual(vm.eval('区分／別名/3'),10)
    def test_no_nfkc_normalization(self):
        vm=self.make(headers='#DIM 表Ａ=17\n#DIM 表A=24');self.assertEqual(vm.eval('表Ａ+表A'),41)
    def test_unicode_punctuation_variable(self):
        vm=self.script('値・別=9\nA=値・別',headers='#DIM 値・別');self.assertEqual(vm.get('A'),9)
    def test_unicode_function_name(self):
        vm=self.make('@計算／別(ARG)\n#FUNCTION\nRETURNF ARG+1');self.assertEqual(vm.eval('計算／別(5)'),6)
    def test_unicode_macro(self):
        vm=self.script('A=定数／別',headers='#DEFINE 定数／別 19');self.assertEqual(vm.get('A'),19)
    def test_ascii_division_unchanged(self):
        self.assertEqual(parse('A/B')[0:2],('binary','/'))
    def test_prefix_decrement(self):
        vm=self.script('A=3\n--A\n++A:1\nB=A+A:1');self.assertEqual(vm.get('B'),3)
    def test_prefix_whitespace_and_trailing_comment(self):
        vm=self.script('A=1\n  ++ A  ; note\nB=A');self.assertEqual(vm.get('B'),2)
    def test_prefix_local_index(self):
        vm=self.script('LOCAL:1=8\n++LOCAL:1\nA=LOCAL:1');self.assertEqual(vm.get('A'),9)
    def test_prefix_character_index(self):
        vm=self.script('ADDCHARA 0\nTARGET=0\n++CFLAG:(5+2)\nA=CFLAG:7',csv=CHARA);self.assertEqual(vm.get('A'),1)
    def test_prefix_index_evaluated_once(self):
        vm=self.script('++A:(B++)\nC=A:0');self.assertEqual((vm.get('B'),vm.get('C')),(1,1))
    def test_prefix_overflow(self):
        vm=self.script('A=9223372036854775807\n++A');self.assertEqual(vm.get('A'),-(1<<63))
    def test_prefix_literal_rejected(self):
        with self.assertRaises(EraError):command('++123')
    def test_prefix_string_rejected(self):
        vm=self.make('@MAIN\n++STR')
        with self.assertRaises(EraError):vm.call('MAIN')
    def test_print_payload_prefix_not_reinterpreted(self):
        self.script('PRINTL ++A');self.assertEqual(self.output.getvalue(),'++A\n')
    def test_prefix_audit_visits_index_calls(self):
        vm=self.make('@MAIN\n++A:(MISSING())');issues=audit(vm.program,vm.data)['issues'];self.assertTrue(any(i['code']=='E_FUNCTION' and 'MISSING' in i['message'] for i in issues))
    def test_unquoted_print_string_is_variable_not_raw(self):
        vm=self.make('@MAIN\nPRINTFORMSW 未定義。');issues=audit(vm.program,vm.data)['issues'];self.assertTrue(any(i['code']=='E_VARIABLE' for i in issues))

class CSVAndMigration(Harness):
    def test_time_four_elements(self):
        vm=self.script('TIME:2=10\nTIME:3=20\nFOR LOCAL,0,4\nTIME:LOCAL=MAX(0,TIME:LOCAL-1)\nNEXT');self.assertEqual([vm.get('TIME:'+str(i)) for i in range(4)],[0,0,9,19])
    def test_explicit_size_still_wins(self):
        vm=self.make(csv={'VariableSize.csv':'TIME,3'});self.assertEqual(vm.eval('VARSIZE("TIME")'),1000);self.assertTrue(any(d.severity == 1 for d in vm.data.size_diagnostics))
        self.assertEqual(vm.get('TIME:3'),0)
        with self.assertRaises(EraError):vm.get('TIME:1000')
    def test_size_profile_describe(self):self.assertEqual(describe('TIME')['variable']['dimensions'],[1000])
    def test_size_profile_rejects_bools(self):
        with self.assertRaises(EraError):validate_document({'schema_version':1,'variables':{'TIME':{'dimensions':[True],'legacy_a9_dimensions':[1]}}},'variables')
    def test_out_of_range_csv_name_rows_warn_and_skip(self):
        vm=self.make(csv={'VariableSize.csv':'ABL,2\nABLNAME,2','Abl.csv':'0,ok\n2,outside\n-1,negative'});self.assertEqual(vm.get('ABLNAME:0'),'ok');self.assertIn('OUTSIDE',vm.data.symbols['ABL']);self.assertTrue(any('index -1' in w for w in vm.data.warnings));self.assertEqual(vm.get('ABLNAME:2'),'outside')
    def test_both_name_and_value_sizes_use_max(self):
        vm=self.make(csv={'VariableSize.csv':'EQUIP,5\nEQUIPNAME,10'});self.assertEqual(vm.eval('VARSIZE("EQUIP")'),100);self.assertEqual(vm.eval('VARSIZE("EQUIPNAME")'),100)
    def test_only_name_changes_data_size(self):
        vm=self.make(csv={'VariableSize.csv':'SOURCENAME,1500'});self.assertEqual(vm.eval('VARSIZE("SOURCE")'),1500)
    def test_item_inventory_independent_from_name_price(self):
        vm=self.make(csv={'VariableSize.csv':'ITEM,3\nITEMNAME,100','Item.csv':'99,item,17'});self.assertEqual((vm.eval('VARSIZE("ITEM")'),vm.eval('VARSIZE("ITEMPRICE")'),vm.get('ITEMPRICE:99')),(1000,100,17))
    def test_chara_csv_overflow_warns_without_auto_growth(self):
        vm=self.script('ADDCHARA 0',csv={'VariableSize.csv':'ABL,2','Chara0.csv':'番号,0\n能力,5,10'});self.assertEqual(vm.data.variables['ABL'].dims,(100,));self.assertEqual(vm.get('ABL:0:5'),10);self.assertTrue(vm.data.size_diagnostics)
    def test_version_decimal_prefix(self):
        vm=self.make(csv={'GameBase.csv':'コード,123\nバージョン,0.00'});self.assertEqual(vm.get('GAMEBASE_VERSION'),0);self.assertIn('VERSION',vm.data.gamebase)
    def test_invalid_version_undefined_not_fatal(self):
        vm=self.make(csv={'GameBase.csv':'バージョン,bogus'});self.assertEqual(vm.get('GAMEBASE_VERSION'),0);self.assertNotIn('VERSION',vm.data.gamebase)
    def test_gamebase_text_second_field_only(self):
        vm=self.make(csv={'GameBase.csv':'タイトル,Hello,ignored'});self.assertEqual(vm.get('GAMEBASE_TITLE'),'Hello')
    def test_gamebase_does_not_strip_fallback_leading_space(self):
        vm=self.make(csv={'GameBase.csv':'バージョン, 1.23'});self.assertNotIn('VERSION',vm.data.gamebase)
    def test_json_old_time_default_migration(self):
        vm=self.make();vm.set('TIME',77);vm.saves.write(0);p=vm.saves.path(0);d=json.loads(p.read_text());d.pop('builtin_defaults_profile');d['variables']['TIME']['dims']=[1];p.write_text(json.dumps(d));vm.set('TIME',0);vm.saves.load(0);self.assertEqual(vm.get('TIME'),77);self.assertEqual(vm.get('TIME:999'),0)
    def test_json_does_not_migrate_explicit_override(self):
        vm=self.make(csv={'VariableSize.csv':'TIME,1000'});vm.saves.write(0);p=vm.saves.path(0);d=json.loads(p.read_text());d.pop('builtin_defaults_profile');d['variables']['TIME']['dims']=[1];p.write_text(json.dumps(d))
        with self.assertRaises(EraError):vm.saves.load(0)
    def test_json_new_profile_not_legacy_migrated(self):
        vm=self.make();vm.saves.write(0);p=vm.saves.path(0);d=json.loads(p.read_text());d['variables']['TIME']['dims']=[1];p.write_text(json.dumps(d))
        with self.assertRaises(EraError):vm.saves.load(0)
    def test_json_legacy_shrink_rejects_outside_data_atomically(self):
        vm=self.script('ADDCHARA 0',csv=CHARA);vm.saves.write(0);p=vm.saves.path(0);d=json.loads(p.read_text());d.pop('builtin_defaults_profile');d['variables']['RELATION']['dims']=[1000];d['variables']['RELATION']['values'].append([[0,999],10]);p.write_text(json.dumps(d));vm.set('MONEY',888)
        with self.assertRaises(EraError):vm.saves.load(0)
        self.assertEqual(vm.get('MONEY'),888)
    def test_json_index_outside_old_shape_rejected(self):
        vm=self.make();vm.saves.write(0);p=vm.saves.path(0);d=json.loads(p.read_text());d.pop('builtin_defaults_profile');d['variables']['TIME']['dims']=[1];d['variables']['TIME']['values']=[[[2],44]];p.write_text(json.dumps(d))
        with self.assertRaises(EraError):vm.saves.load(0)

# Independent golden constants from ConstantData; each boundary is a named test.
_DEFAULTS={n:1000 for n in 'DAY MONEY TIME COUNT RESULT TARGET MASTER ASSI PLAYER ASSIPLAY PREVCOM NEXTCOM BOUGHT NOITEM PBAND UP DOWN LOSEBASE PALAMLV EXPLV'.split()}
_DEFAULTS.update(SOURCE=1000,JUEL=200,GOTJUEL=200,RELATION=100)
for _name,_size in _DEFAULTS.items():
    def test(self,name=_name,size=_size):
        vm=self.make();v=vm.data.variables[name];self.assertEqual(v.dims,(size,));key=((0,) if v.character else ())+ (size-1,);v.set(key,7);self.assertEqual(v.get(key),7)
        with self.assertRaises(EraError):v.get(key[:-1]+(size,))
    setattr(CSVAndMigration,'test_boundary_'+_name,test)

_CASES=[('0.00',(True,0)),('1.23',(True,1)),('123abc',(True,123)),('-42',(True,-42)),('+42',(True,42)),(' 42 ',(True,42)),(' 42x',(False,0)),('-42x',(False,0)),('+42x',(False,0)),('',(False,0)),('abc',(False,0)),('9223372036854775807',(True,(1<<63)-1)),('-9223372036854775808',(True,-(1<<63))),('9223372036854775808',(False,0)),('９９',(False,0)),('12²',(False,0)),('1_000',(True,1))]
for _i,(_text,_expected) in enumerate(_CASES):
    def test(self,text=_text,expected=_expected):self.assertEqual(gamebase_integer(text),expected)
    setattr(CSVAndMigration,f'test_gamebase_tryatoi_{_i:02}',test)

class ConditionalFormBoundary(Harness):
    def test_true_literal_ascii_spaces_trimmed(self):
        v=self.make();self.assertEqual(v.format(r'\@ 1 ?  X  # Y \@'),'X')
    def test_false_literal_spaces_trimmed(self):
        v=self.make();self.assertEqual(v.format(r'\@ 0 ? X #  Y  \@'),'Y')
    def test_fullwidth_spaces_not_trimmed(self):
        v=self.make();self.assertEqual(v.format(r'\@ 1 ? 　X　 # Y \@'),'　X　')
    def test_substitution_value_spaces_preserved(self):
        v=self.make();v.set('STR','  X  ');self.assertEqual(v.format(r'\@ 1 ? %STR% # Y \@'),'  X  ')
    def test_raw_form_outer_spaces_preserved(self):
        v=self.make();self.assertEqual(v.format(r'  \@1? X #Y\@  '),'  X  ')
    def test_escaped_literal_space_trimmed_like_source(self):
        v=self.make();self.assertEqual(v.format(r'\@1?\sX\s#Y\@'),'X')
    def test_conditional_quoted_question(self):
        v=self.make();self.assertEqual(v.format(r'\@ "?" == "?" ? X # Y \@'),'X')
    def test_condition_nested_ternary(self):
        v=self.make();self.assertEqual(v.format(r'\@ (1 ? 1 # 0) ? X # Y \@'),'X')
    def test_branch_nested_numeric_ternary_not_separator(self):
        v=self.make();self.assertEqual(v.format(r'\@ 1 ? {1 ? 7 # 8} # Y \@'),'7')
    def test_branch_escaped_hash_not_separator(self):
        v=self.make();self.assertEqual(v.format(r'\@1? X\#Y # Z\@'),'X#Y')
    def test_missing_false_uses_empty(self):
        v=self.make();self.assertEqual(v.format(r'\@0? X \@'),'')
    def test_missing_false_true_value(self):
        v=self.make();self.assertEqual(v.format(r'\@1? X \@'),'X')
    def test_repeated_fixed_grid_patch_does_not_grow(self):
        v=self.make();v.set('STR',' '*100)
        for k in range(30):
            v.set('A',k*2);v.set('B',k*2+2)
            left=v.format(r'\@ A > 0 ? %SUBSTRING(STR,0,A),A,LEFT% # \@')
            right=v.format(r'\@ B < 100 ? %SUBSTRING(STR,B)% # \@')
            v.set('STR',left+'XY'+right)
            self.assertEqual(v.eval('STRLENS(STR)'),100)

class StringExpressionAudit(Harness):
    def test_bare_prose_in_expression_is_still_reported_after_unicode_change(self):
        from pyemuera.audit import audit
        v=self.make('@MAIN\nPRINTFORMSW 不明な名前%STR%末尾\nRETURN')
        issues=audit(v.program,v.data)['issues']
        self.assertTrue(any(x['code']=='E_VARIABLE' for x in issues))
    def test_csv_symbol_is_not_reported_as_missing_variable(self):
        from pyemuera.audit import audit
        v=self.make('@MAIN\nPRINTS TOSTR(ABL:特殊／能力)\nRETURN',csv={'Abl.csv':'1,特殊／能力\n'})
        self.assertFalse(audit(v.program,v.data)['issues'])
