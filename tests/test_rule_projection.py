"""Rule command provenance is independent of logical strings and plain PRINT."""
import io,os,unittest
from unittest.mock import patch
from test_core import Harness
from pyemuera.terminal_frame import RetainedFrame,RuleRow
from pyemuera.layout import project_rule,terminal_width
from pyemuera.errors import EraError

class Rules(Harness):
    def terminal(self,body,cols=100,physical=100,mode='diff',layout='terminal'):
        vm=self.make('@MAIN\n'+body+'\nRETURN');c=vm.console
        c.columns=cols;c.layout=layout;c.is_terminal=lambda:True;c.vt_enabled=True
        self.size=[physical,40]
        c.configure_renderer(mode);c._retained.size_provider=lambda:tuple(self.size)
        with patch('shutil.get_terminal_size',return_value=os.terminal_size(self.size)):vm.call('MAIN')
        return c,c._retained
    def texts(self,f):return [''.join(t for t,_ in r.runs) for r in f.snapshot()[0]]
    def test_drawline_respects_safe_width_matrix(self):
        for logical in (80,100,120):
            for physical in (2,60,84,100,120,160):
                with self.subTest(logical=logical,physical=physical):
                    c,f=self.terminal('DRAWLINE',logical,physical)
                    self.assertEqual(self.texts(f),['-'*min(logical,physical-1),''])
                    self.assertEqual(list(c.lines),['-'*logical]);self.assertEqual(list(c.log_lines),['-'*logical])
    def test_getlinestr_not_shortened(self):
        c,f=self.terminal('STR = %GETLINESTR("-")%\nDRAWLINE',physical=60)
        self.assertEqual(self.vm.get('STR'),'-'*100);self.assertEqual(self.texts(f)[0],'-'*59)
    def test_plain_print_of_getlinestr_still_wraps(self):
        c,f=self.terminal('PRINTSL GETLINESTR("-")')
        self.assertEqual(self.texts(f),['-'*99,'-',''])
    def test_plain_print_placeholder_remains(self):
        c,f=self.terminal('PRINTFORM ----\nPRINTL\nDRAWLINE',physical=120)
        self.assertEqual(self.texts(f),['----','-'*100,''])
    def test_custom_literal_is_not_form(self):
        c,f=self.terminal('A=2\nCUSTOMDRAWLINE {A++}\nDRAWLINEFORM {A++}')
        self.assertTrue(c.lines[0].startswith('{A++}'));self.assertEqual(c.lines[1],'2'*100)
        self.assertEqual(self.vm.get('A'),3)
    def test_custom_unknown_form_syntax_remains_literal(self):
        c,f=self.terminal('CUSTOMDRAWLINE %NOT_A_VAR%')
        self.assertTrue(c.lines[0].startswith('%NOT_A_VAR%'))
    def test_multiglyph_patterns_no_partial_wide_cell(self):
        for pattern in ('あ-','…','─','ab'):
            with self.subTest(pattern=pattern):
                c,f=self.terminal('DRAWLINEFORM '+pattern,physical=84)
                rows=f.snapshot()[0];self.assertEqual(len(rows),2)
                self.assertLessEqual(terminal_width(self.texts(f)[0],2),83)
    def test_ambiguous_glyph_budget_both_projection_modes(self):
        for layout in ('raw','terminal'):
            for ambiguous in (1,2):
                s,n=project_rule('…'*100,99,layout=layout,ambiguous=ambiguous)
                self.assertEqual(n,terminal_width(s,2));self.assertLessEqual(n,99)
    def test_resize_restores_rule_from_full_text(self):
        c,f=self.terminal('DRAWLINE',physical=60)
        self.size[0]=120
        self.assertEqual(self.texts(f),['-'*100,'']);self.assertEqual(c.lines[0],'-'*100)
        self.size[0]=84;self.assertEqual(self.texts(f),['-'*83,''])
    def test_clear_removes_rule_provenance(self):
        c,f=self.terminal('DRAWLINE\nCLEARLINE 1\nPRINTL short')
        self.assertEqual(self.texts(f),['short','']);self.assertEqual(list(c._rule_lines),[None])
    def test_late_renderer_reconstructs_rule(self):
        vm=self.script('DRAWLINE\nPRINTL ----');c=vm.console
        c.is_terminal=lambda:True;c.vt_enabled=True;c.configure_renderer('diff');f=c._retained;f.size_provider=lambda:(100,40)
        self.assertEqual(self.texts(f),['-'*99,'----',''])
    def test_stream_terminal_rule_only_is_fitted(self):
        c,f=self.terminal('DRAWLINE\nPRINTL '+('-'*100),mode='stream')
        self.assertEqual(self.output.getvalue(),'-'*99+'\n'+'-'*100+'\n')
        self.assertEqual(list(c.lines),['-'*100,'-'*100])
    def test_redirected_output_not_fitted(self):
        vm=self.script('DRAWLINE\nCUSTOMDRAWLINE ab\nDRAWLINEFORM =')
        self.assertEqual(self.output.getvalue(),'-'*100+'\n'+'ab'*50+'\n'+'='*100+'\n')
    def test_alignment_cannot_push_rule_outside_safe_width(self):
        for alignment in ('LEFT','CENTER','RIGHT'):
            vm=self.make('@MAIN\nDRAWLINE\nRETURN');c=vm.console;c.ui['alignment']=alignment;c.columns=100
            c.is_terminal=lambda:True;c.vt_enabled=True;c.configure_renderer('diff');c._retained.size_provider=lambda:(84,20);vm.call('MAIN')
            self.assertEqual(self.texts(c._retained)[0],'-'*83)
    def test_regular_rule_style_and_user_style_restoration(self):
        vm=self.make('@MAIN\nDRAWLINE\nPRINTL x\nRETURN');c=vm.console;c.ui['style']=7
        c.is_terminal=lambda:True;c.vt_enabled=True;c.configure_renderer('diff');c._retained.size_provider=lambda:(100,20);vm.call('MAIN')
        self.assertEqual(c.markup_lines[0][0][0][1].bits,0);self.assertEqual(c.markup_lines[1][0][0][1].bits,7);self.assertEqual(c.ui['style'],7)
    def test_skip_rule_does_not_evaluate_form(self):
        vm=self.script('A=1\nSKIPDISP 1\nDRAWLINEFORM {A++}\nSKIPDISP 0')
        self.assertEqual(vm.get('A'),1);self.assertEqual(list(vm.console.lines),[])
    def test_existing_current_line_boundary_preserved(self):
        c,f=self.terminal('PRINT before\nDRAWLINE\nPRINTL after')
        self.assertEqual(list(c.lines),['before','-'*100,'after']);self.assertEqual(self.texts(f),['before','-'*99,'after',''])
    def test_rule_error_does_not_change_user_style(self):
        vm=self.make('@MAIN\nDRAWLINEFORM %""%');vm.console.ui['style']=7
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertEqual(vm.console.ui['style'],7);self.assertIsNone(vm.console.style_override)
    def test_unchanged_rule_does_not_force_full_repaint(self):
        c,f=self.terminal('DRAWLINE');f.present();before=f.stats['host_writes'];f.present()
        self.assertEqual(f.stats['host_writes'],before)
    def test_rule_after_background_change_retains_provenance(self):
        c,f=self.terminal('DRAWLINE',mode='stream');c.color_enabled=True;c.set_background(255)
        self.assertIs(c._frame,f);self.assertEqual(self.texts(f),['-'*99,''])
        self.assertEqual(f.snapshot()[0][0].runs[0][1][1],255)

    def test_late_rule_after_host_echo_keeps_provenance_and_style(self):
        vm=self.make('@MAIN\nDRAWLINE\nRETURN');c=vm.console
        c._host_line_echo=True;c._input_echo('7');c.ui['color']=0x123456
        vm.call('MAIN');c.is_terminal=lambda:True;c.vt_enabled=True;c.configure_renderer('diff')
        f=c._retained;f.size_provider=lambda:(84,20)
        self.assertEqual(self.texts(f),['7','-'*83,''])
        self.assertEqual(f.snapshot()[0][1].runs[0][1][0],0x123456)
        self.assertEqual(list(c.lines),['7','-'*100])
