import io,sys,unittest
from unittest.mock import patch
from test_core import Harness
from pyemuera.console import Console
from pyemuera.errors import EraError
from pyemuera import html1824 as h
from pyemuera.journal import RunJournal

class InputA8(Harness):
    def test_inputs_raw_form_default(self):
        vm=self.script('A=3\nINPUTS name,{A}',inputs=['']);self.assertEqual(vm.get('RESULTS'),'name,3')
    def test_inputs_quotes_are_literal_not_expression(self):
        vm=self.script('INPUTS "text"',inputs=['']);self.assertEqual(vm.get('RESULTS'),'"text"')
    def test_oneinputs_default_first_utf16(self):
        vm=self.script('ONEINPUTS 表示',inputs=['']);self.assertEqual(vm.get('RESULTS'),'表')
    def test_oneinputs_truncates_typed_string(self):
        vm=self.script('ONEINPUTS',inputs=['ab']);self.assertEqual(vm.get('RESULTS'),'a')
    def test_oneinputs_supplementary_is_utf16_unit(self):
        vm=self.script('ONEINPUTS',inputs=['😀']);self.assertEqual(vm.get('RESULTS'),'\ud83d')
    def test_oneinput_default_first_decimal_digit(self):
        vm=self.script('ONEINPUT 876\nA=RESULT',inputs=['']);self.assertEqual(vm.get('A'),8)
    def test_oneinput_negative_has_no_default(self):
        with self.assertRaises(EraError):self.script('ONEINPUT -7',inputs=[''])
    def test_oneinput_typed_multiple_takes_first(self):
        vm=self.script('ONEINPUT\nA=RESULT',inputs=['23']);self.assertEqual(vm.get('A'),2)
    def test_toneinput_default_reference_formula(self):
        vm=self.script('TONEINPUT 100,987,0,""\nA=RESULT',inputs=[{'kind':'timed_one_integer','text':'','timeout':True}]);self.assertEqual(vm.get('A'),1)
    def test_toneinput_negative_fallback_abs(self):
        vm=self.script('TONEINPUT 100,-7,0,""\nA=RESULT',inputs=[{'kind':'timed_one_integer','text':'','timeout':True}]);self.assertEqual(vm.get('A'),7)
    def test_toneinputs_expression_default_truncated(self):
        vm=self.script('TONEINPUTS 100,"text",0,"expired"',inputs=[{'kind':'timed_one_string','text':'','timeout':True}]);self.assertEqual(vm.get('RESULTS'),'t');self.assertEqual(self.output.getvalue(),'expired\n')
    def test_tinput_zero_waits_for_input(self):
        vm=self.script('TINPUT 0,-3,0,""\nA=RESULT',inputs=['8']);self.assertEqual(vm.get('A'),8)
    def test_tinput_negative_waits_for_input(self):
        vm=self.script('TINPUT -1,-3,0,""\nA=RESULT',inputs=['']);self.assertEqual(vm.get('A'),-3)
    def test_tinput_extra_expressions_not_evaluated(self):
        vm=self.script('A=3\nTINPUT 10,9,0,"",A++\nB=RESULT',inputs=['2']);self.assertEqual(vm.get('A'),3);self.assertEqual(vm.get('B'),2)
    def test_tinput_hole_rejected_before_wait(self):
        with self.assertRaises(EraError):self.script('TINPUT 10,3,,""',inputs=['2'])
    def test_input_i64_limit(self):
        with self.assertRaises(EraError):self.script('INPUT',inputs=[str(1<<63)])
    def test_input_fullwidth_digits_rejected(self):
        with self.assertRaises(EraError):self.script('INPUT',inputs=['１２３'])
    def test_waitanykey_typed_replay(self):
        vm=self.make('@MAIN\nWAITANYKEY\nRETURN',inputs=[{'kind':'key_wait','text':'x'}]);vm.console.no_wait=False;vm.call('MAIN');self.assertEqual(vm.console.input_count,1)
    def test_oneinput_uses_singlekey_reader(self):
        vm=self.make('@MAIN\nONEINPUT\nA=RESULT\nRETURN');vm.console.inputs=None
        with patch.object(vm.console,'_read_key',return_value='6') as key:vm.call('MAIN');key.assert_called_once()
        self.assertEqual(vm.get('A'),6)
    def test_toneinput_uses_deadline_singlekey_reader(self):
        vm=self.make('@MAIN\nTONEINPUT 100,7,0,""\nA=RESULT\nRETURN');vm.console.inputs=None
        with patch.object(vm.console,'_read_key',return_value=None) as key:vm.call('MAIN');self.assertGreater(key.call_args.args[0],0)
        self.assertEqual(vm.get('A'),7)
    def test_oneinput_record_kind(self):
        vm=self.make('@MAIN\nONEINPUT\nRETURN',inputs=['5']);j=RunJournal(record_inputs=True);vm.console.journal=j;vm.call('MAIN');self.assertEqual(j.records,[{'kind':'one_integer','text':'5'}])
    def test_method_wait_is_rejected(self):
        vm=self.make('@MAIN\nA=FN()\nRETURN\n@FN\n#FUNCTION\nTONEINPUT 10,0\nRETURNF 1')
        with self.assertRaises(EraError):vm.call('MAIN')

class HtmlA8(Harness):
    def test_escape_apostrophe_source_named_entity(self):self.assertEqual(h.escape("<&>'\""),'&lt;&amp;&gt;&apos;&quot;')
    def test_case_insensitive_entities(self):self.assertEqual(h.unescape('&NbSp;&AmP;&LT;&#x41;&#65;'),' &<AA')
    def test_br_to_plain_does_not_insert_line(self):self.assertEqual(h.to_plain('a<br>b'),'ab')
    def test_source_regex_greedy_gt(self):self.assertEqual(h.to_plain('a<x>b>c'),'ac')
    def test_unknown_entity_rejected(self):
        with self.assertRaises(EraError):h.unescape('&copy;')
    def test_missing_semicolon_rejected(self):
        with self.assertRaises(EraError):h.unescape('&amp')
    def test_numeric_entity_surrogate_unit_allowed(self):self.assertEqual(h.unescape('&#xD800;'),'\ud800')
    def test_numeric_entity_supplementary_refused(self):
        with self.assertRaises(EraError):h.unescape('&#x1F600;')
    def test_tagsplit_first_gt_even_in_quotes(self):self.assertEqual(h.tag_split('a<x title=\'>\'>b'),['a',"<x title='>","'>b"])
    def test_tagsplit_no_html(self):self.assertEqual(h.tag_split('text'),['text'])
    def test_tagsplit_empty(self):self.assertEqual(h.tag_split(''),[])
    def test_tagsplit_bad_tag_none(self):self.assertIsNone(h.tag_split('a<bad'))
    def test_tagsplit_command_defaults(self):
        vm=self.script('HTML_TAGSPLIT "x<b>y</b>"\nA=RESULT');self.assertEqual(vm.get('A'),4);self.assertEqual([vm.get(f'RESULTS:{i}') for i in range(4)],['x','<b>','y','</b>'])
    def test_tagsplit_explicit_array_count_and_tail(self):
        vm=self.script('TEXTS:4=tail\nHTML_TAGSPLIT "<b>x</b>",TEXTS,B',headers='#DIMS TEXTS,5');self.assertEqual(vm.get('B'),3);self.assertEqual(vm.get('TEXTS:4'),'tail')
    def test_tagsplit_array_index_ignored_not_evaluated(self):
        vm=self.script('A=1\nHTML_TAGSPLIT "<b>x</b>",TEXTS:(A++),B',headers='#DIMS TEXTS,5');self.assertEqual(vm.get('A'),1);self.assertEqual(vm.get('TEXTS'),'<b>')
    def test_tagsplit_small_array_full_count(self):
        vm=self.script('HTML_TAGSPLIT "<b>x</b>",TEXTS,B',headers='#DIMS TEXTS,1');self.assertEqual(vm.get('B'),3);self.assertEqual(vm.get('TEXTS'),'<b>')
    def test_tagsplit_invalid_preserves_destination(self):
        vm=self.script('RESULTS=keep\nHTML_TAGSPLIT "a<bad"\nA=RESULT');self.assertEqual(vm.get('A'),-1);self.assertEqual(vm.get('RESULTS'),'keep')
    def test_printedstr_excludes_pending_line(self):
        vm=self.script('PRINTL complete\nPRINT pending');self.assertEqual(vm.eval('HTML_GETPRINTEDSTR()'),"<p align='left'><nobr>complete</nobr></p>")
    def test_printedstr_backwards_index(self):
        vm=self.script('PRINTL first\nPRINTL second');self.assertIn('first',vm.eval('HTML_GETPRINTEDSTR(1)'));self.assertEqual(vm.eval('HTML_GETPRINTEDSTR(2)'),'')
    def test_printedstr_negative_error(self):
        with self.assertRaises(EraError):self.make().eval('HTML_GETPRINTEDSTR(-1)')
    def test_pop_pending_buffer_only(self):
        vm=self.script('PRINTL completed\nPRINT pending');self.assertEqual(vm.eval('HTML_POPPRINTINGSTR()'),'pending');self.assertEqual(vm.console.current,'');self.assertEqual(vm.eval('HTML_POPPRINTINGSTR()'),'');self.assertIn('completed',vm.eval('HTML_GETPRINTEDSTR()'))
    def test_pop_terminal_unflushed_bytes_not_printed(self):
        vm=self.make('@MAIN\nPRINT pending\nRETURN');vm.console.layout='terminal';vm.call('MAIN');vm.eval('HTML_POPPRINTINGSTR()');vm.console.flush();self.assertEqual(self.output.getvalue(),'')
    def test_printedstr_captures_color_and_style(self):
        vm=self.script('SETCOLOR 0xff0000\nFONTBOLD\nPRINTL red');s=vm.eval('HTML_GETPRINTEDSTR()');self.assertIn("color='#FF0000'",s);self.assertIn('<b>red</b>',s)
    def test_printbutton_value_roundtrips_in_html_not_plaintext(self):
        vm=self.script('PRINTBUTTON "go",42\nPRINTL');self.assertEqual(self.output.getvalue(),'go\n');self.assertIn("<button value='42'>go</button>",vm.eval('HTML_GETPRINTEDSTR()'))
    def test_html_print_style_applied_and_restored(self):
        vm=self.script('SETCOLOR 0x123456\nHTML_PRINT "<font color=\'red\'><b>R</b></font>"');self.assertEqual(self.output.getvalue(),'R\n');self.assertEqual(vm.ui['color'],0x123456);self.assertIn("color='#FF0000'",vm.eval('HTML_GETPRINTEDSTR()'))
    def test_html_complete_line_markup_reparse(self):
        vm=self.script('HTML_PRINT "<p align=\'right\'><nobr><button value=\'3\'>three</button></nobr></p>"');text=vm.eval('HTML_GETPRINTEDSTR()');runs,alignment,_=h.parse_html(text);self.assertEqual(alignment,'RIGHT');self.assertEqual(runs[0][0],'three')
    def test_invalid_html_atomic_no_partial_output(self):
        vm=self.make('@MAIN\nHTML_PRINT "start<b>bad"\nRETURN')
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertEqual(self.output.getvalue(),'');self.assertEqual(vm.console.current,'')
    def test_skip_html_does_not_evaluate(self):
        vm=self.script('A=0\nSKIPDISP 1\nHTML_PRINT @"{A++}"\nSKIPDISP 0');self.assertEqual(vm.get('A'),0)
    def test_clearline_html_history(self):
        vm=self.script('PRINTL a\nPRINTL b\nCLEARLINE 1');self.assertIn('a',vm.eval('HTML_GETPRINTEDSTR()'));self.assertEqual(h.to_plain(vm.eval('HTML_GETPRINTEDSTR()')),'a')
    def test_reuse_pending_markup(self):
        vm=self.script('PRINT old\nREUSELASTLINE new');self.assertEqual(vm.eval('HTML_POPPRINTINGSTR()'),'new')
    def test_printedstr_plain_escapes_literal_markup(self):
        vm=self.script('PRINTL <b>plain</b>');self.assertIn('&lt;b&gt;plain&lt;/b&gt;',vm.eval('HTML_GETPRINTEDSTR()'))

for token in ['<b>x','<b><b>x</b></b>','<font>x</font>','<bad>x</bad>','<button value="1"><button>x</button></button>','<p align="bad">x</p>','x<p align="left">y</p>','<b>bad</i>','<img src="x">','<button pos="12">x</button>']:
    def case(self,token=token):
        with self.assertRaises(EraError):h.parse_html(token)
    setattr(HtmlA8,'test_rejected_markup_'+str(len([n for n in HtmlA8.__dict__ if n.startswith('test_rejected_markup')])),case)
