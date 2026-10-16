"""CP932 logical text and rendered terminal cells are intentionally distinct."""
import io,unittest
from test_core import Harness
from pyemuera.layout import project,terminal_width
from pyemuera.console import Console
from pyemuera.printing import kana
from pyemuera.errors import EraError

class ProjectionA7(unittest.TestCase):
    def test_each_encodable_character_preserves_cp932_cells(self):
        for c in ' abcXYZ123　日本語┌─┐│└┘┏━┓┃┗┛↑↓←→…①②■◆【】ｱｲｳ':
            for ambiguous in (1,2):
                self.assertEqual(terminal_width(project(c,ambiguous),ambiguous),max(terminal_width(c,ambiguous),len(c.encode('cp932'))),(c,ambiguous))
    def test_room_outline_matches_two_digit_number(self):
        expected=['┌───┐ ','│ 11│ ','└───┘ ']
        self.assertEqual([project(t) for t in ['┌─┐','│11│','└─┘']],expected)
        self.assertEqual({terminal_width(t) for t in expected},{6})
    def test_corridor_continuous(self):
        self.assertEqual(project('│11│─│12│'),'│ 11│───│ 12│ ')
    def test_unexplored_blank_equals_frame_width(self):
        self.assertEqual(terminal_width(project('　　　')),terminal_width(project('┌─┐')))
    def test_sidebar_constant_column(self):
        parts=['　'+'　'.join(['┌─┐']*5)+'　　　','　'+'─'.join(['│11│']*5)+'　　　','　'+'　'.join(['　　　']*5)+'　　　']
        self.assertEqual({terminal_width(project(s)) for s in parts},{46})
    def test_projection_only_at_output_history_raw(self):
        out=io.StringIO();c=Console(output=out,layout='terminal');c.write('┌─┐',True)
        self.assertEqual(c.last_line(),'┌─┐');self.assertEqual(out.getvalue(),'┌───┐ \n')
    def test_split_prints_same_as_whole_line(self):
        text='　│11│─│12│　　　INFO';out=io.StringIO();c=Console(output=out,layout='terminal')
        for ch in text:c.write(ch)
        c.write('',True);self.assertEqual(out.getvalue(),project(text)+'\n')
    def test_style_change_does_not_break_corridor_lookahead(self):
        out=io.StringIO();c=Console(output=out,layout='terminal');c.ui={'color':1,'bgcolor':0,'style':0}
        c.write('│11│');c.ui['color']=2;c.write('─│12│',True);self.assertEqual(out.getvalue(),project('│11│─│12│')+'\n')
    def test_flush_before_input(self):
        out=io.StringIO();c=Console(['7'],out,layout='terminal');c.write('┌─┐');self.assertEqual(out.getvalue(),'');self.assertEqual(c.input(),7);self.assertEqual(out.getvalue(),project('┌─┐')+'\n')
    def test_wide_ambiguous_mode_no_double_padding(self):
        self.assertEqual(project('┌─┐　',2),'┌─┐　')
    def test_raw_mode_no_projection(self):
        out=io.StringIO();c=Console(output=out,layout='raw');c.write('┌─┐');self.assertEqual(out.getvalue(),'┌─┐')
    def test_no_ansi_from_game_text(self):
        out=io.StringIO();c=Console(output=out,layout='terminal');c.write('\x1b[31mX\x1b]2;title\x07',True);self.assertNotIn('\x1b',out.getvalue())
    def test_ideographic_space_not_replaced(self):self.assertEqual(project('　'),'　')
    def test_no_fake_clear_marker_in_transcript(self):
        out=io.StringIO();c=Console(output=out);c.write('x',True);c.clear_lines(1);self.assertEqual(out.getvalue(),'x\n');self.assertEqual(c.line_count,0)

class PrintA7(Harness):
    def test_forcekana_basic(self):
        self.assertEqual(kana('あいうABC',1),'アイウABC');self.assertEqual(kana('アイウABC',2),'あいうABC');self.assertEqual(kana('ｶﾞ A1',3),'が　Ａ１')
    def test_forcekana_not_global_nfkc(self):self.assertEqual(kana('①あ',1),'①ア')
    def test_forcekana_invalid(self):
        with self.assertRaises(EraError):self.script('FORCEKANA 4')
    def test_printk_respects_forcekana(self):self.script('FORCEKANA 1\nPRINTKL あ');self.assertEqual(self.output.getvalue(),'ア\n')
    def test_print_non_k_unchanged(self):self.script('FORCEKANA 1\nPRINTL あ');self.assertEqual(self.output.getvalue(),'あ\n')
    def test_printdata_k(self):self.script('FORCEKANA 1\nPRINTDATAKL\nDATA あ\nENDDATA');self.assertEqual(self.output.getvalue(),'ア\n')
    def test_skip_does_not_evaluate_new_print_modes(self):
        self.script('SKIPDISP 1\nPRINTBUTTON @"{1/0}",1\nPRINTDATAKW\nDATAFORM {1/0}\nENDDATA\nSKIPDISP 0');self.assertEqual(self.output.getvalue(),'')
    def test_printd_default_foreground_but_keeps_state(self):
        vm=self.make('@MAIN\nSETCOLOR 0x112233\nPRINTDL x\nRETURN');vm.console.layout='terminal';vm.console.enable_color('always');vm.call('MAIN')
        self.assertIn('38;2;192;192;192',self.output.getvalue());self.assertEqual(vm.ui['color'],0x112233)
    def test_registry_default_different_for_each_vm(self):
        vm=self.make('@MAIN\nPRINTDL x\nRETURN');vm.default_color=0x123456;vm.console.layout='terminal';vm.console.enable_color('always');vm.call('MAIN');self.assertIn('38;2;18;52;86',self.output.getvalue())

class FormsEscapesA7(Harness):
    def test_stored_nonform_escape_stays_literal(self):
        vm=self.make('@MAIN\nPRINTFORMS STR\nRETURN');vm.set('STR',r'A\nB');vm.call('MAIN');self.assertEqual(self.output.getvalue(),r'A\nB')
    def test_stored_form_escape_remains_escape(self):
        vm=self.make('@MAIN\nPRINTFORMS STR\nRETURN');vm.set('STR',r'\{3\} {4}');vm.call('MAIN');self.assertEqual(self.output.getvalue(),'{3} 4')

class AlignmentA7(Harness):
    def test_center_cell_alignment(self):
        vm=self.make('@MAIN\nALIGNMENT CENTER\nPRINTL 日本\nRETURN');vm.console.layout='terminal';vm.console.columns=10;vm.call('MAIN');self.assertEqual(self.output.getvalue(),'   日本\n')
    def test_right_cell_alignment(self):
        vm=self.make('@MAIN\nALIGNMENT RIGHT\nPRINTL 日本\nRETURN');vm.console.layout='terminal';vm.console.columns=10;vm.call('MAIN');self.assertEqual(self.output.getvalue(),'      日本\n')
    def test_raw_alignment_does_not_mutate_transcript(self):
        self.script('ALIGNMENT RIGHT\nPRINTL x');self.assertEqual(self.output.getvalue(),'x\n')
    def test_html_plain_does_not_add_hidden_button_value(self):
        vm=self.make();self.assertEqual(vm.html_plain('<button value="7">Next</button>'),'Next')
