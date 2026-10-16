from test_core import Harness,CHARA
from pyemuera.errors import EraError
from pyemuera.regex1824 import Pattern,escape
from pyemuera.audit import audit

class RegexA8(Harness):
    def test_dotnet_escape_minimum_metacharacters(self):self.assertEqual(escape('a-b]c} &~#\n'),r'a-b]c}\ &~\#\n')
    def test_dollar_group_and_literal(self):self.assertEqual(Pattern('(a)(b)').replace('ab','$2$1$$'),'ba$')
    def test_dollar_entire_match(self):self.assertEqual(Pattern('b').replace('abc','[$&]'),'a[b]c')
    def test_dollar_whole_input(self):self.assertEqual(Pattern('b').replace('abc','$_'),'aabcc')
    def test_dollar_prefix_suffix(self):self.assertEqual(Pattern('b').replace('abc',"$`-$'"),'aa-cc')
    def test_dollar_unknown_group_stays_literal(self):self.assertEqual(Pattern('(a)').replace('a','$10/${missing}'),'$10/${missing}')
    def test_dotnet_numbering_puts_named_after_unnamed(self):self.assertEqual(Pattern('(?<n>a)(b)').replace('ab','$1$2/${n}'),'ba/a')
    def test_named_backreference(self):self.assertEqual(Pattern(r'(?<n>a)\k<n>').replace('aab','${n}'),'ab')
    def test_quote_named_group(self):self.assertEqual(Pattern("(?'n'a)").replace('a','${n}'),'a')
    def test_dollar_last_participating_group(self):self.assertEqual(Pattern('(a)(b)?').replace('a','$+'),'a')
    def test_replacement_backslash_is_literal(self):self.assertEqual(Pattern('a').replace('a',r'\n'),r'\n')
    def test_utf16_dot_two_surrogates(self):self.assertEqual(Pattern('.').count('😀'),2)
    def test_utf16_replace_both_units(self):self.assertEqual(Pattern('.').replace('😀','x'),'xx')
    def test_utf16_identity_replacement_recombines(self):self.assertEqual(Pattern('(.)').replace('😀','$1'),'😀')
    def test_unicode_categories_fail_closed(self):
        with self.assertRaises(EraError):Pattern(r'\p{L}')
    def test_balancing_groups_fail_closed(self):
        with self.assertRaises(EraError):Pattern('(?<a-b>x)')
    def test_duplicate_group_names_fail_closed(self):
        with self.assertRaises(EraError):Pattern('(?<n>a)(?<n>b)')
    def test_python_only_group_fail_closed(self):
        with self.assertRaises(EraError):Pattern('(?P<n>a)')
    def test_dotnet_regex_vm_function(self):
        v=self.make();self.assertEqual(v.eval('REPLACE("abc", "(?<x>b)", "${x}${x}")'),'abbc')
    def test_regex_find_element_uses_same_adapter(self):
        vm=self.script('STR:1=abc');self.assertEqual(vm.eval('FINDELEMENT(STR,"(?<x>b)",0,2)'),1)

class ScopeArrayA8(Harness):
    def test_splits_full_count_and_truncates_output(self):
        vm=self.script('SPLIT "a,b,c",",",ARR\nA=RESULT',headers='#DIMS ARR,2');self.assertEqual(vm.get('A'),3);self.assertEqual(vm.get('ARR:1'),'b')
    def test_split_ignores_reference_index_without_sideeffect(self):
        vm=self.script('A=1\nSPLIT "x,y",",",ARR:(A++),B',headers='#DIMS ARR,3');self.assertEqual(vm.get('A'),1);self.assertEqual(vm.get('ARR'),'x');self.assertEqual(vm.get('B'),2)
    def test_split_empty_delimiter_does_not_split(self):
        vm=self.script('SPLIT "abc","",STR\nA=RESULT');self.assertEqual(vm.get('STR'),'abc');self.assertEqual(vm.get('A'),1)
    def test_split_tail_not_cleared(self):
        vm=self.script('STR:2=tail\nSPLIT "a,b",",",STR');self.assertEqual(vm.get('STR:2'),'tail')
    def test_split_bad_count_ref_does_not_mutate(self):
        vm=self.make('@MAIN\nSTR=old\nSPLIT "a,b",",",STR,RESULTS\nRETURN')
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertEqual(vm.get('STR'),'old')
    def test_varsize_statement_writes_all_dimensions(self):
        vm=self.script('VARSIZE ARR\nA=RESULT\nB=RESULT:1\nC=RESULT:2',headers='#DIM ARR,2,3,4');self.assertEqual((vm.get('A'),vm.get('B'),vm.get('C')),(2,3,4))
    def test_varsize_expression_rejects_negative_axis(self):
        with self.assertRaises(EraError):self.make().eval('VARSIZE("A",-1)')
    def test_varsize_omitted_axis(self):self.assertEqual(self.make().eval('VARSIZE("A",)'),1000)
    def test_cvarset_csv_named_index(self):
        vm=self.script('ADDCHARA 0\nADDCHARA 0\nCVARSET ABL,"会話",7',csv={**CHARA,'ABL.csv':'2,会話\n'});self.assertEqual(vm.get('ABL:0:2'),7);self.assertEqual(vm.get('ABL:1:2'),7)
    def test_cvarset_array_descriptor(self):
        vm=self.script('ADDCHARA 0\nCVARSET ABL:0:0,2,7',csv=CHARA);self.assertEqual(vm.get('ABL:0:2'),7)
    def test_cvarset_badtype_atomic(self):
        vm=self.make('@MAIN\nADDCHARA 0\nCVARSET ABL,2,"bad"',csv=CHARA)
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertEqual(vm.get('ABL:0:2'),0)
    def test_reversed_varset_source_empty_range(self):
        vm=self.script('A=1,2,3\nVARSET A,9,2,1');self.assertEqual([vm.get(f'A:{i}') for i in range(3)],[1,2,3])
    def test_varset_end_evaluated_before_start(self):
        vm=self.script('A=3\nVARSET B,A++,A++,A++');self.assertEqual(vm.get('A'),6);self.assertEqual(vm.get('B:3'),0)
    def test_strjoin_default_comma(self):
        vm=self.script('A=1,2,3');self.assertEqual(vm.eval('STRJOIN(A,,0,3)'),'1,2,3')
    def test_strjoin_last_argument_is_end_not_count(self):
        vm=self.script('A=1,2,3,4');self.assertEqual(vm.eval('STRJOIN(A,"-",1,3)'),'2-3-4')
    def test_groupmatch_type_consistency(self):
        with self.assertRaises(EraError):self.make().eval('GROUPMATCH(1,"1")')
    def test_numeric_aggregate_rejects_strings(self):
        with self.assertRaises(EraError):self.make().eval('SUMARRAY(STR)')
    def test_match_type_consistency(self):
        with self.assertRaises(EraError):self.make().eval('MATCH(A,"1")')
    def test_rand_omitted_lower_bound(self):
        vm=self.make();vm.rng.seed(5);a=vm.eval('RAND(,99)');vm.rng.seed(5);self.assertEqual(a,vm.eval('RAND(99)'))
    def test_tostr_negative_hex_twos_complement(self):self.assertEqual(self.make().eval('TOSTR(-1,"X")'),'FFFFFFFFFFFFFFFF')
    def test_local_forbid_without_usage_starts(self):
        vm=self.script('A=5',csv={'VariableSize.csv':'LOCAL,-1\nLOCALS,-1\n'});self.assertEqual(vm.get('A'),5)
    def test_local_forbid_reference_rejected(self):
        with self.assertRaises(EraError) as cm:self.script('A=LOCAL',csv={'VariableSize.csv':'LOCAL,-1'})
        self.assertEqual(cm.exception.code,'E_VARIABLE_FORBIDDEN')
    def test_local_qualified_forbid_rejected(self):
        with self.assertRaises(EraError):self.script('A=LOCAL@MAIN',csv={'VariableSize.csv':'LOCAL,-1'})
    def test_call_in_method_rejected_before_side_effect(self):
        vm=self.make('@MAIN\nB=FN()\nRETURN\n@FN\n#FUNCTION\nCALL WORK\nRETURNF 0\n@WORK\nA=55\nRETURN')
        with self.assertRaises(EraError) as cm:vm.call('MAIN')
        self.assertEqual(cm.exception.code,'E_METHOD_CONTEXT');self.assertEqual(vm.get('A'),0)
    def test_method_unsafe_static_audit(self):
        vm=self.make('@MAIN\nRETURN\n@FN\n#FUNCTION\nINPUT\nRETURNF 0');self.assertIn('E_METHOD_CONTEXT',[i['code'] for i in audit(vm.program,vm.data)['issues']])
    def test_raw_input_default_not_parsed_as_expression_in_audit(self):
        vm=self.make('@MAIN\nINPUTS default,string\nRETURN');self.assertFalse(audit(vm.program,vm.data)['issues'])
    def test_method_can_dump_rng(self):
        vm=self.script('A=FN()\nRETURN\n@FN\n#FUNCTION\nDUMPRAND\nRETURNF RANDDATA:624');self.assertEqual(vm.get('A'),624)
