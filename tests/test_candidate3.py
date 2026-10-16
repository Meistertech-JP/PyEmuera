"""Neutral regressions derived from src1824 contracts, not game identifiers."""
import io
import re
import unittest
from unittest.mock import patch
from test_core import Harness
from pyemuera.errors import EraError, FlowSignal
from pyemuera.program import command
from pyemuera.save_menu import SaveMenu,SaveRepository,save_slot_count
from pyemuera.terminal_frame import RetainedFrame
from pyemuera.console import Console
from pyemuera.text import find_assignment


class StatementContracts(Harness):
    def test_legacy_statements(self):
        v=self.script('A == 5\nRESULT == A+1\nB:2 == RESULT\nIF A == 5\nC = A == 5\nENDIF')
        self.assertEqual((v.get('A'),v.get('B:2'),v.get('C')),(5,6,1))
        self.assertEqual(len([w for w in v.program.warnings if '代入演算子' in w]),3)
    def test_lhs_side_effect_once(self):
        v=self.script('B:(A++) == 7\nC = A')
        with self.assertRaises(EraError) as caught:
            self.make('@MAIN\nB:A++ == 7\nRETURN\n')
        self.assertEqual(caught.exception.code,'E_SYNTAX')
        self.assertEqual((v.get('A'),v.get('B:0'),v.get('C')),(1,7,1))
    def test_comparison_rhs(self):
        v=self.script('A = 2\nB == A == 2')
        self.assertEqual(v.get('B'),1)
    def test_string_legacy_retains_form(self):
        v=self.script('STR == text {4+5}')
        self.assertEqual(v.get('STR'),'text 9')
    def test_expression_stays_comparison(self):
        v=self.make('@MAIN\nRETURN\n@F\n#FUNCTION\nRETURNF 4 == 4')
        self.assertEqual(v.eval('F()'),1)
        self.assertEqual(v.eval('2 == 3'),0)
    def test_generic_assignment_scanner_no_recovery_default(self):
        self.assertIsNone(find_assignment('A == 5'))
        self.assertEqual(find_assignment('A == 5',legacy=True),('A','==','5'))
    def test_print_not_reclassified(self):
        self.script('PRINTL == A')
        self.assertEqual(self.output.getvalue(),'== A\n')
    def test_registered_expression_command_precedes_assignment(self):
        self.assertEqual(command('EVAL A == 5'),('EVAL','A == 5'))
        self.assertEqual(command('IF A == 5'),('IF','A == 5'))
    def test_nested_index_comparison(self):
        v=self.script('A = 5\nB:(A == 5) == 9')
        self.assertEqual(v.get('B:1'),9)
    def test_no_triple_equals_recovery(self):
        self.assertNotEqual(command('A === 5')[0],'_ASSIGN')
    def test_failed_rhs_does_not_mutate(self):
        v=self.make('@MAIN\nA == 1/0')
        with self.assertRaises(EraError):v.call('MAIN')
        self.assertEqual(v.get('A'),0)
    def test_sif_legacy_branch(self):
        v=self.script('SIF 0\nA == 5\nSIF 1\nB == 9')
        self.assertEqual((v.get('A'),v.get('B')),(0,9))


class SaveContracts(Harness):
    def menu(self,inputs,saving=False):
        self.vm.console.inputs=iter(map(str,inputs));return SaveMenu(self.vm,saving).run()
    def test_empty_back(self):
        self.make();self.menu([100])
        self.assertIn('[ 0] （データなし）',self.output.getvalue())
        self.assertIn('[99]',self.output.getvalue())
        self.assertFalse(self.vm.saves.directory.exists())
    def test_save_default_description_timestamp(self):
        self.make();self.menu([0],True)
        self.assertRegex(self.vm.saves.inspect(0)['description'],r'^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} ')
    def test_saveinfo_appends_timestamp(self):
        v=self.make('@MAIN\nRETURN\n@SAVEINFO\nPUTFORM Test')
        self.menu([0],True);self.assertTrue(v.saves.inspect(0)['description'].endswith(' Test'))
    def test_second_page_requires_selection(self):
        v=self.make(csv={'_fixed.config':'表示するセーブデータ数:40\n'})
        self.menu([20,20],True);self.assertIsNotNone(v.saves.inspect(20))
        self.assertIn('セーブデータ20～39を表示',self.output.getvalue())
        self.assertIn('[20] （データなし）',self.output.getvalue())
    def test_page_boundary19(self):
        self.make();self.menu([19],True);self.assertIsNotNone(self.vm.saves.inspect(19))
    def test_cancel_after_switch_no_write(self):
        self.make(csv={'_fixed.config':'表示するセーブデータ数:80\n'})
        self.menu([60,100],True);self.assertFalse(self.vm.saves.directory.exists())
    def test_reject_auto_save_write(self):
        self.make();self.menu([99,100],True)
        self.assertIsNone(self.vm.saves.inspect(99))
        self.assertIn('無効な値',self.output.getvalue())
    def test_load_auto_save(self):
        v=self.make();v.set('A',42);v.saves.write(99,'auto');v.set('A',0)
        with self.assertRaises(FlowSignal) as e:self.menu([99])
        self.assertEqual(e.exception.state,'LOADDATAEND');self.assertEqual(v.get('A'),42)
    def test_overwrite_no(self):
        v=self.make();v.saves.write(0,'old');before=v.saves.path(0).read_bytes()
        self.menu([0,1,100],True);self.assertEqual(v.saves.path(0).read_bytes(),before)
    def test_overwrite_yes(self):
        v=self.make();v.saves.write(0,'old');self.menu([0,0],True)
        self.assertNotEqual(v.saves.inspect(0)['description'],'old')
    def test_corrupt_kept_until_explicit_confirm(self):
        v=self.make();p=v.saves.path(0);p.parent.mkdir(parents=True);p.write_text('{bad')
        self.menu([0,1,100],True);self.assertEqual(p.read_text(),'{bad')
    def test_broken_load_returns_menu_without_mutation(self):
        v=self.make();v.set('A',77);p=v.saves.path(0);p.parent.mkdir(parents=True);p.write_text('{bad')
        self.menu([0,100]);self.assertEqual(v.get('A'),77)
    def test_absent_load_returns_menu(self):
        self.make();self.menu([0,100]);self.assertIn('データがありません',self.output.getvalue())
    def test_native_and_private_same_slot(self):
        from pyemuera.native_store import original_path
        v=self.make();v.saves.format='emuera-text';v.saves.write(0,'original')
        original=original_path(v,0);original.write_bytes(v.saves.native_path(0).read_bytes());v.saves.native_path(0).unlink()
        before=original.read_bytes();v.saves.format='json';v.saves.write(0,'private')
        info=SaveRepository(v.saves).metadata(0)
        self.assertEqual((info.provider,info.description),('private-json','private'))
        self.assertEqual(original.read_bytes(),before)
    def test_no_auto_in_save_listing(self):
        self.make();self.menu([100],True);self.assertNotIn('[99]',self.output.getvalue())
    def test_metadata_does_not_mutate_result(self):
        v=self.make();v.set('RESULT',123);v.saves.write(0,'test');SaveRepository(v.saves).metadata(0)
        self.assertEqual(v.get('RESULT'),123)


class TerminalContracts(unittest.TestCase):
    def make(self,**kw):
        self.sink=io.StringIO();self.f=RetainedFrame(self.sink,size_provider=lambda:(41,10),**kw);return self.f
    def test_identical_frame_zero_physical_bytes(self):
        f=self.make();f.feed('A\nB');f.present();pos=self.sink.tell();f.present()
        self.assertEqual(self.sink.tell(),pos);self.assertEqual(f.stats['unchanged'],1)
    def test_clear_refill_identical_does_not_blank(self):
        f=self.make();f.feed('A\nB\n');f.present();pos=self.sink.tell()
        f.clear(2);f.feed('A\nB\n');f.present();self.assertEqual(self.sink.tell(),pos)
    def test_shorter_line_suffix_clear(self):
        f=self.make();f.feed('abcdef');f.present();pos=self.sink.tell()
        f.reuse('abc');f.present();patch=self.sink.getvalue()[pos:]
        self.assertIn('abc',patch);self.assertIn('\x1b[K',patch)
        self.assertNotIn('\x1b[2K',patch);self.assertNotIn('\x1b[2J',patch)
    def test_one_changed_row(self):
        f=self.make();f.feed('A\nB\n');f.present();before=f.stats['changed_rows'];pos=self.sink.tell()
        f.clear(1);f.feed('C\n');f.present()
        self.assertEqual(f.stats['changed_rows']-before,1);self.assertNotIn('A',self.sink.getvalue()[pos:])
    def test_color_only_difference(self):
        f=self.make();f.feed('x',(1,2,0));f.present();pos=self.sink.tell()
        f.reuse('x',(3,2,0));f.present();self.assertGreater(self.sink.tell(),pos)
    def test_wide_characters_wrap_at_boundaries(self):
        f=self.make();f.size_provider=lambda:(6,10);f.feed('日本語A');rows,_,_=f.snapshot()
        self.assertEqual([r.width for r in rows],[4,3])
        self.assertEqual(''.join(t for r in rows for t,_ in r.runs),'日本語A')
    def test_resize_no_full_screen_blank(self):
        f=self.make();f.feed('123456789');f.present();pos=self.sink.tell()
        f.size_provider=lambda:(6,10);f.present()
        self.assertEqual(f.stats['resizes'],1);self.assertNotIn('\x1b[2J',self.sink.getvalue()[pos:])
    def test_close_restores_cursor_and_screen_idempotently(self):
        f=self.make();f.feed('x');f.present();f.close();pos=self.sink.tell();f.close()
        self.assertEqual(pos,self.sink.tell());self.assertTrue(self.sink.getvalue().endswith('\x1b[?1049l'))
        self.assertIn('\x1b[?25h',self.sink.getvalue())
    def test_redirect_never_diff(self):
        c=Console(output=io.StringIO());c.enable_color('auto');c.configure_renderer('diff');c.set_redraw(0)
        self.assertIsNone(c._frame);c.write('text',True);self.assertEqual(c.output.getvalue(),'text\n')
    def test_redraw0_defers_and_forced_input_presents(self):
        class TTY(io.StringIO):
            def isatty(self):return True
        sink=TTY();c=Console(['0'],sink,layout='terminal');c.vt_enabled=True
        c.configure_renderer('auto');c.set_redraw(0);c.write('old',True);c.flush()
        self.assertEqual(sink.getvalue(),'');c.input();self.assertIn('old',sink.getvalue())
        pos=sink.tell();c.clear_lines(1);c.write('old',True);c.flush(force=True)
        self.assertEqual(sink.tell(),pos);c.close()
    def test_redraw2_forces_snapshot_while_suppressed(self):
        class TTY(io.StringIO):
            def isatty(self):return True
        c=Console(output=TTY(),layout='terminal');c.vt_enabled=True;c.configure_renderer('auto')
        c.set_redraw(0);c.write('x');self.assertEqual(c.output.getvalue(),'')
        c.set_redraw(2);self.assertIn('x',c.output.getvalue());self.assertEqual(c._redraw,2);c.close()
    def test_tty_stream_same_logical_history(self):
        class TTY(io.StringIO):
            def isatty(self):return True
        a=Console(output=io.StringIO(),layout='terminal');b=Console(output=TTY(),layout='terminal')
        b.vt_enabled=True;b.configure_renderer('auto');b.set_redraw(0)
        for c in (a,b):
            c.write('first\nlong');c.clear_lines(1);c.write('日本\nlast');c.flush(force=True)
        self.assertEqual((list(a.lines),a.current),(list(b.lines),b.current));b.close()

class CrossSubsystemContracts(Harness):
    def test_html_pop_discards_retained_current(self):
        class TTY(io.StringIO):
            def isatty(self):return True
        v=self.make();c=v.console;c.output=TTY();c.vt_enabled=True;c.configure_renderer('diff')
        c.write('prefix',True);c.write('temporary');c.flush(force=True)
        self.assertIn('temporary',v.eval('HTML_POPPRINTINGSTR()'))
        c.flush(force=True)
        self.assertEqual(c.current,'');self.assertEqual(c._frame.current,[])
        self.assertEqual(c._frame.previous[-1].width,0);c.close()
    def test_retains_background_written_before_redraw0(self):
        class TTY(io.StringIO):
            def isatty(self):return True
        v=self.make();c=v.console;c.output=TTY();c.vt_enabled=True;c.configure_renderer('auto')
        v.ui['bgcolor']=0x112233;c.write('text',True)
        c.set_redraw(0);c.flush(force=True)
        self.assertEqual(c._frame.previous[0].runs[0][1][1],0x112233);c.close()
    def test_static_legacy_rhs_is_checked(self):
        from pyemuera.audit import audit
        v=self.make('@MAIN\nA == ABS(1)\nB == DOES_NOT_EXIST(1)')
        messages=[x['message'] for x in audit(v.program,v.data)['issues']]
        self.assertTrue(any('DOES_NOT_EXIST' in x for x in messages))
        self.assertFalse(any('Command A' in x or 'Command B' in x for x in messages))

if __name__=='__main__':unittest.main()


class InputOverlayC3(unittest.TestCase):
    def test_native_input_prompt_not_game_history(self):
        from unittest.mock import patch
        import io
        from pyemuera.console import Console
        class TTY(io.StringIO):
            def isatty(self): return True
        c=Console(output=TTY());c.enable_color('always');c.configure_renderer('diff')
        c.write('pending')
        with patch('builtins.input',return_value='7'):
            self.assertEqual(c.input(),7)
        self.assertEqual(c.current,'')
        self.assertEqual(c.last_line(),'pending')
        self.assertEqual(c._frame.current,[])
        c.close()

    def test_prompt_exception_restores_projection(self):
        from unittest.mock import patch
        import io
        from pyemuera.console import Console
        class TTY(io.StringIO):
            def isatty(self): return True
        c=Console(output=TTY());c.enable_color('always');c.configure_renderer('diff')
        c.write('pending')
        with patch('builtins.input',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):c.input()
        self.assertEqual(c.current,'')
        self.assertEqual(c.last_line(),'pending')
        self.assertEqual(c._frame.current,[])
        c.close()
