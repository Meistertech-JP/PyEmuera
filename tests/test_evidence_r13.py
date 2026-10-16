import unittest,io,json,tempfile,pathlib
from test_evidence_r7 import FixtureR7
from pyemuera.text import legacy_substring
from pyemuera.unicode_boundary import units,display_text,json_text
from pyemuera.console import Console
from pyemuera.outputlog import logical_bytes,capture_summary
from pyemuera.cli import write_report
from pyemuera.errors import EraError

class UTF16SubstringR13(unittest.TestCase):
    def test_end_crossing(self):self.assertEqual(legacy_substring('日a',0,1),'日')
    def test_start_crossing(self):self.assertEqual(legacy_substring('日a',1,1),'a')
    def test_negative(self):self.assertEqual(legacy_substring('日a',-1,1),'日')
    def test_surrogate_start(self):self.assertEqual(units(legacy_substring('😀a',1,1)),[0xde00])
    def test_surrogate_end(self):self.assertEqual(units(legacy_substring('😀a',0,1)),[0xd83d])
    def test_surrogate_whole_width(self):self.assertEqual(legacy_substring('😀a',2,1),'a')
    def test_hangul_replacement_width(self):self.assertEqual(legacy_substring('가a',1,1),'a')
    def test_zero(self):self.assertEqual(legacy_substring('日a',0,0),'')
    def test_past_end(self):self.assertEqual(legacy_substring('日a',3,-1),'')
    def test_empty(self):self.assertEqual(legacy_substring('',-1,-1),'')
    def test_no_internal_mutation(self):self.assertEqual(units(legacy_substring('😀a',0,1)),[0xd83d])

class UnicodeBoundariesR13(unittest.TestCase):
    def test_pair(self):self.assertEqual(display_text('\ud83d\ude00'),'😀')
    def test_lone_high(self):self.assertEqual(display_text('日本\ud83d'),'日本�')
    def test_lone_low(self):self.assertEqual(display_text('\ude00'),'�')
    def test_literal_escape(self):self.assertEqual(display_text(r'\ud83d'),r'\ud83d')
    def test_json_roundtrip(self):
        s='日本\ud83d\n ';self.assertEqual(json.loads(json_text({'text':s}))['text'],s)
    def test_log_does_not_mutate(self):
        c=Console(output=io.StringIO());c.write('\ud83d',True);self.assertIn('�',logical_bytes(c).decode());self.assertEqual(units(c.lines[0]),[0xd83d])
    def test_blank_screen_log_separate(self):
        c=Console(output=io.StringIO());c.write('',True);self.assertEqual(list(c.lines),['']);self.assertEqual(logical_bytes(c),b' \n\n')
    def test_trailing_space_preserved(self):
        c=Console(output=io.StringIO());c.write('x ',True);self.assertEqual(logical_bytes(c),b'x \n\n')
    def test_extra_blank_preserved(self):
        c=Console(output=io.StringIO());c.write('',True);c.write('',True);self.assertEqual(logical_bytes(c),b' \n \n\n')

class CommandsR13(FixtureR7):
    def run_source(self,body,mode='NO'):
        v=self.vm('@SYSTEM_TITLE\n'+body+'\nQUIT\n',mode);v.run();return v
    def test_semicolon_raw(self):
        v=self.run_source('PRINT a;b\nPRINTL c ;d');self.assertIn('a;bc ;d',self.out.getvalue())
    def test_semicolon_form(self):
        v=self.run_source('PRINTFORML e;f{1}');self.assertIn('e;f1',self.out.getvalue())
    def test_semicolon_expr(self):
        v=self.run_source('OR_A=1 ; comment\nPRINTVL OR_A');self.assertEqual(v.eval('OR_A'),1)
    def test_semicolon_string(self):self.run_source('PRINTSL "g;h"');self.assertIn('g;h',self.out.getvalue())
    def test_reuse_chain(self):
        v=self.run_source('PRINTL a\nREUSELASTLINE b\nREUSELASTLINE c\nPRINTL d');self.assertEqual(list(v.console.lines)[-2:],['a','d'])
    def test_clearline_negative_no_deletion(self):
        v=self.run_source('PRINTL a\nCLEARLINE -1\nPRINTL b');self.assertEqual(list(v.console.lines)[-2:],['a','b'])
    def test_color_bare(self):self.assertEqual(self.run_source('SETCOLORBYNAME Red').ui['color'],0xff0000)
    def test_color_quoted(self):
        with self.assertRaises(EraError)as e:self.run_source('SETCOLORBYNAME "Red"')
        self.assertEqual(e.exception.message,'指定された色名""Red""は無効な色名です')
    def test_color_quoted_load_yes(self):
        v=self.vm('@SYSTEM_TITLE\nSETCOLORBYNAME "Red"\nQUIT','YES');self.assertEqual(v.program.argument_diagnostics[0].severity,2)
    def test_space_model_log_not_screen_tag(self):
        v=self.run_source('PRINT L\nPRINT_SPACE 40\nPRINT R\nPRINTL');self.assertEqual(v.console.display_elements[-1]['kind'],'space');self.assertNotIn('<shape',self.out.getvalue());self.assertIn("<shape type='space' param='40'>",logical_bytes(v.console).decode())
    def test_rect_model(self):
        v=self.run_source('PRINT_RECT 40');self.assertEqual(v.console.display_elements[-1]['kind'],'rect');self.assertFalse(v.console.display_elements[-1]['pixel_rendered'])
    def test_tooltip_config(self):
        v=self.run_source('TOOLTIP_SETDELAY 100\nTOOLTIP_SETDURATION 99999\nTOOLTIP_SETCOLOR 255,256');self.assertEqual(v.ui['tooltip'],dict(delay=100,duration=32767,foreground=255,background=256))
    def test_cleartextbox_model(self):
        v=self.run_source('CLEARTEXTBOX');self.assertEqual(v.console.input_buffer,'')
    def test_bar_zero_rejected(self):
        with self.assertRaises(EraError)as e:self.run_source('BAR 1,2,0')
        self.assertEqual(e.exception.message,'BARの長さが正の値ではありません')
    def test_bar_extra_side_effect_not_evaluated(self):
        v=self.run_source('OR_A=1\nBAR 1,2,3,OR_A++');self.assertEqual(v.eval('OR_A'),1)
    def test_redraw_noarg(self):self.assertEqual(self.run_source('REDRAW').ui['redraw'],0)
    def test_outputlog_and_report_surrogate(self):
        v=self.run_source('PRINTSL SUBSTRINGU("😀",0,1)\nOUTPUTLOG');r=capture_summary(v);self.assertEqual(len(r['records']),1);self.assertTrue(r['lossy_code_units']);self.assertEqual(units(v.console.lines[-2]),[0xd83d])
    def test_status_exp(self):
        v=self.run_source('ADDVOIDCHARA\nEXP:0:0=3\nPRINT_EXP 0');self.assertNotIn(': 3',self.out.getvalue())
