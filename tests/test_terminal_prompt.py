import io
import unittest
from unittest.mock import patch
from pyemuera.console import Console
from pyemuera.terminal_frame import RetainedFrame


class PromptContracts(unittest.TestCase):
    def test_prompt_cursor_is_visible_and_overlay_is_not_history(self):
        out = io.StringIO();f = RetainedFrame(out, size_provider=lambda: (20, 8))
        f.feed('game\n');before = (list(f.rows), list(f.current))
        f.present_prompt()
        self.assertTrue(out.getvalue().endswith('\x1b[?25h'))
        self.assertEqual(before, (list(f.rows), list(f.current)))
        self.assertEqual(f.previous[-1].runs[0][0], '> ')

    def test_warning_region_keeps_prompt_and_input_cursor(self):
        out = io.StringIO();f = RetainedFrame(out, size_provider=lambda: (40, 8))
        f.feed('game\n');f.external_diagnostic('warning')
        f.present_prompt()
        self.assertEqual(f.previous[-2].runs[0][0], '> ')
        self.assertEqual(f.previous[-1].runs[0][0], 'warning')
        self.assertEqual(f.last_cursor, (2, 3))

    def test_finish_invalidates_host_echo_and_hides_cursor(self):
        out = io.StringIO();f = RetainedFrame(out, size_provider=lambda: (20, 8))
        f.present_prompt();f.finish_prompt()
        self.assertIsNone(f.previous)
        self.assertTrue(out.getvalue().endswith('\x1b[?25l'))
        f.close();self.assertIn('\x1b[?25h', out.getvalue())

    def test_cli_line_cancel_finishes_prompt(self):
        c = Console(output=io.StringIO())
        c._frame = RetainedFrame(c.output, size_provider=lambda: (20, 8))
        with patch('builtins.input', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            c.input()
        self.assertTrue(c.output.getvalue().endswith('\x1b[?25l'))
        self.assertEqual(list(c.log_lines), [])

    def test_single_key_cancel_finishes_prompt(self):
        c = Console(output=io.StringIO());c._frame = RetainedFrame(c.output)
        with patch.object(c, '_read_key', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            c.input(one=True)
        self.assertIsNone(c._frame.previous)

    def test_timed_input_cancel_finishes_prompt(self):
        c = Console(output=io.StringIO());c._frame = RetainedFrame(c.output)
        with patch.object(c, '_timed_read', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            c.input(timeout_ms=10)
        self.assertIsNone(c._frame.previous)
