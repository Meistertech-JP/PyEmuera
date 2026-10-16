"""Console-wide background semantics; synthetic VT tests are not Windows proof."""
import io
import sys
import unittest
from unittest.mock import patch
from test_core import Harness
from pyemuera.console import Console
from pyemuera.terminal_frame import RetainedFrame
from pyemuera.errors import EraError


class TTY(io.StringIO):
    def isatty(self):
        return True


class BackgroundSurface(unittest.TestCase):
    def console(self, mode='diff', layout='terminal'):
        c = Console([''], TTY(), layout=layout, no_wait=True)
        c.ui = {'color': 0xff0000, 'bgcolor': 0, 'style': 5, 'alignment': 'LEFT'}
        c.enable_color('always')
        c.configure_renderer(mode)
        c._retained.size_provider = lambda: (12, 6)
        self.addCleanup(c.close)
        return c

    def test_recolors_existing_text_without_changing_foreground_style_or_history(self):
        c = self.console()
        c.write('old', True)
        history = (list(c.lines), list(c.log_lines), list(c.markup_lines))
        c.set_background(0xff)
        self.assertEqual(c._frame.previous[0].runs, (('old', (0xff0000, 0xff, 5)),))
        c.set_background(0)
        self.assertEqual(c._frame.previous[0].runs, (('old', (0xff0000, 0, 5)),))
        self.assertEqual(history, (list(c.lines), list(c.log_lines), list(c.markup_lines)))

    def test_erase_to_end_of_each_viewport_row_uses_new_background(self):
        c = self.console()
        c.write('x')
        pos = c.output.tell()
        c.set_background(0xff)
        update = c.output.getvalue()[pos:]
        self.assertEqual(update.count('\x1b[K'), 6)
        self.assertIn('48;2;0;0;255m\x1b[K', update)
        self.assertIn('\x1b[6;1H', update)
        self.assertNotIn('\x1b[0m\x1b[K', update)

    def test_empty_screen_still_changes_background(self):
        c = self.console()
        c.flush(force=True)
        pos = c.output.tell()
        c.set_background(0xff)
        self.assertEqual(c.output.getvalue()[pos:].count('\x1b[K'), 6)

    def test_redraw_zero_defers_background_and_forced_wait_presents(self):
        c = self.console()
        c.write('old', True)
        c.set_redraw(0)
        pos = c.output.tell()
        c.set_background(0xff)
        c.write('new', True)
        self.assertEqual(c.output.tell(), pos)
        self.assertEqual(c.ui['bgcolor'], 0xff)
        c.wait()
        self.assertEqual(c._frame.previous[0].runs[0][1][1], 0xff)

    def test_stream_global_repaint_uses_main_screen_and_keeps_history(self):
        c = self.console('stream')
        c.write('old', True)
        self.assertIsNone(c._frame)
        c.set_background(0xff)
        c.write('new', True)
        c.set_background(0)
        self.assertIs(c._frame, c._retained)
        self.assertNotIn('\x1b[?1049h', c.output.getvalue())
        self.assertEqual(list(c.lines), ['old', 'new'])
        self.assertTrue(all(style[1] == 0 for row in c._frame.previous for _, style in row.runs))

    def test_raw_layout_terminal_also_repaints(self):
        c = self.console('stream', 'raw')
        c.write('日本', True)
        c.set_background(0xff)
        self.assertEqual(c._frame.previous[0].runs[0][0], '日本')

    def test_unchanged_default_background_does_not_promote_stream(self):
        c = self.console('stream')
        c.set_background(0)
        self.assertIsNone(c._frame)
        self.assertEqual(c.output.getvalue(), '')

    def test_stream_pending_row_background_change_respects_redraw_zero(self):
        c = self.console('stream')
        c.set_redraw(0); c.write('pending')
        self.assertEqual(c.output.getvalue(), '')
        c.set_background(0xff)
        self.assertEqual(c.output.getvalue(), '')
        c.wait()
        self.assertEqual(c._frame.previous[0].runs[0], ('pending', (0xff0000, 0xff, 5)))

    def test_resize_repaints_new_blank_rows_with_current_background(self):
        c = self.console()
        c.set_background(0xff); c.write('x', True)
        c._frame.size_provider = lambda: (20, 8)
        pos = c.output.tell(); c.flush(force=True)
        update = c.output.getvalue()[pos:]
        self.assertEqual(update.count('\x1b[K'), 8)
        self.assertIn('48;2;0;0;255m\x1b[K', update)

    def test_redirected_output_has_no_viewport_repaint(self):
        c = Console(output=io.StringIO(), layout='terminal')
        c.ui = {'color': 1, 'bgcolor': 0, 'style': 0}
        c.enable_color('auto'); c.configure_renderer('diff')
        c.write('old', True); c.set_background(0xff); c.write('new', True); c.set_background(0)
        self.assertEqual(c.output.getvalue(), 'old\nnew\n')
        self.assertEqual(list(c.log_lines), ['old', 'new'])

    def test_pending_split_print_keeps_foreground_changes_but_not_old_background(self):
        c = self.console()
        c.set_redraw(0)
        c.write('a')
        c.ui['color'] = 0x00ff00
        c.set_background(0xff)
        c.write('b')
        c.set_background(0)
        c.flush(force=True)
        self.assertEqual(c._frame.previous[0].runs, (('a', (0xff0000, 0, 5)), ('b', (0x00ff00, 0, 5))))

    def test_alignment_padding_and_diagnostics_use_surface_background(self):
        c = self.console()
        c.ui['alignment'] = 'RIGHT'; c.columns = c._retained.columns = 6
        c.write('x', True)
        with patch.object(c, '_diagnostic_shares_terminal', return_value=True), patch.object(sys, 'stderr', c.output):
            c.warning('test', 'visible')
        c.set_background(0xff)
        rows, _, _ = c._frame.snapshot()
        self.assertTrue(all(style[1] == 0xff for row in rows for _, style in row.runs))
        self.assertNotIn('visible', ''.join(c.log_lines))

    def test_stream_warning_survives_first_global_repaint(self):
        c = self.console('stream')
        with patch.object(c, '_diagnostic_shares_terminal', return_value=True), patch.object(sys, 'stderr', c.output):
            c.warning('test', 'visible')
        c.set_background(0xff)
        self.assertTrue(c._frame.diagnostic_lines)
        self.assertIn('visible', ''.join(text for row in c._frame.previous for text, _ in row.runs))

    def test_clear_reuse_and_resize_after_reset_do_not_restore_old_blue(self):
        c = self.console()
        c.set_background(0xff); c.write('old', True); c.write('pending')
        c.set_background(0); c.clear_lines(1); c.reuse_line('short')
        c._frame.size_provider = lambda: (5, 8); c.flush(force=True)
        self.assertTrue(all(style[1] == 0 for row in c._frame.previous for _, style in row.runs))

    def test_frame_does_not_retain_background_in_run_storage(self):
        f = RetainedFrame(io.StringIO())
        f.feed('x', (1, 0xff, 2))
        self.assertEqual(f.current, [('x', (1, 0, 2))])
        f.set_background(3)
        self.assertEqual(f.snapshot()[0][0].runs, (('x', (1, 3, 2)),))


class DisplayCommandContracts(Harness):
    def test_named_and_numeric_background_reset_and_default(self):
        v = self.make('@MAIN\nSETBGCOLORBYNAME Blue\nPRINTL old\nSETBGCOLOR 1,2,3\nRESETBGCOLOR')
        v.default_background = 0x102030
        v.call('MAIN')
        self.assertEqual(v.ui['bgcolor'], 0x102030)
        self.assertEqual(list(v.console.log_lines), ['old'])

    def test_invalid_background_does_not_change_surface(self):
        v = self.make('@MAIN\nSETBGCOLORBYNAME Blue\nSETBGCOLOR 1,2,999')
        with self.assertRaises(EraError):
            v.call('MAIN')
        self.assertEqual(v.ui['bgcolor'], 0xff)

    def test_display_family_is_bound_to_dedicated_handler(self):
        from pyemuera.dispatcher import DISPATCH
        from pyemuera.display_commands import execute
        from pyemuera.registry import COMMAND_SPECS
        for name, spec in COMMAND_SPECS.items():
            if spec['family'] == 'display':
                self.assertIs(DISPATCH[name][0], execute)
