"""Physical warning summaries must preserve full storage and logical output."""
import io
import sys
import unittest
from unittest.mock import patch
from pyemuera.console import Console
from pyemuera.terminal_frame import RetainedFrame, DEFAULT_STYLE
from pyemuera.layout import terminal_width


class TTY(io.StringIO):
    def isatty(self):
        return True


def text(rows):
    return [''.join(part for part, style in row.runs) for row in rows]


class DiagnosticProjectionContracts(unittest.TestCase):
    def frame(self, width=84, height=24, ambiguous=1):
        f = RetainedFrame(TTY(), columns=100, layout='terminal', ambiguous_width=ambiguous)
        f.size_provider = lambda: (width, height)
        for index in range(30):
            f.feed('game-' + str(index) + '\n')
        f.feed('INPUT> ')
        return f

    def test_long_warning_retains_head_and_reserves_game_context(self):
        f = self.frame()
        warning = '[PyEmuera warning] E_EXAMPLE Main.ERB:42 ' + 'detail ' * 100
        f.diagnostic_lines = [warning]
        rows, cursor, size = f.snapshot()
        shown = text(rows)
        self.assertIn('E_EXAMPLE Main.ERB:42', '\n'.join(shown))
        self.assertTrue(shown[-1].endswith('...'))
        self.assertEqual(f.diagnostic_lines, [warning])
        self.assertGreaterEqual(cursor[0], 16)
        self.assertEqual(shown[cursor[0] - 1], 'INPUT> ')
        self.assertEqual(cursor[1], 8)
        self.assertTrue(all(row.width <= 83 for row in rows))

    def test_short_warning_projection_is_unchanged(self):
        f = self.frame()
        f.diagnostic_lines = ['short warning']
        self.assertEqual(text(f.snapshot()[0])[-1], 'short warning')

    def test_product_label_is_compact_only_during_overflow(self):
        f = self.frame(12, 6)
        warning = '[PyEmuera warning] visible'
        f.diagnostic_lines = [warning]
        self.assertIn('[!] visible', text(f.snapshot()[0]))
        f.size_provider = lambda: (120, 24)
        self.assertEqual(text(f.snapshot()[0])[-1], warning)

    def test_multiple_warnings_keep_newest_heads(self):
        f = self.frame(20, 9)
        f.diagnostic_lines = [f'warning-{i} ' + 'long ' * 30 for i in range(6)]
        shown = '\n'.join(text(f.snapshot()[0]))
        self.assertNotIn('warning-0', shown)
        for i in (3, 4, 5):
            self.assertIn(f'warning-{i}', shown)
        self.assertEqual(len(f.diagnostic_lines), 6)

    def test_tiny_viewport_keeps_input_without_mutating_messages(self):
        for height in (2, 3, 4):
            f = self.frame(2, height)
            f.diagnostic_lines = ['long message' * 100]
            rows, cursor, size = f.snapshot()
            self.assertLessEqual(len(rows), height)
            self.assertTrue(all(row.width <= 1 for row in rows))
            self.assertLessEqual(cursor[0], len(rows))
            self.assertEqual(f.diagnostic_lines, ['long message' * 100])

    def test_wide_summary_marker_never_exceeds_safe_width(self):
        for ambiguous in (1, 2):
            f = self.frame(14, 9, ambiguous)
            f.diagnostic_lines = ['日本…診断 ' * 50]
            rows, cursor, size = f.snapshot()
            self.assertTrue(all(row.width <= 13 for row in rows))
            self.assertTrue(text(rows)[-1].endswith('...'))
            self.assertIn('INPUT> ', text(rows))

    def test_repeated_projection_does_not_write_or_register_again(self):
        f = self.frame()
        f.diagnostic_lines = ['warning ' * 200]
        f.present()
        before = f.output.getvalue()
        f.present()
        self.assertEqual(f.output.getvalue(), before)
        self.assertEqual(len(f.diagnostic_lines), 1)
        self.assertEqual(f.stats['unchanged'], 1)

    def test_resize_and_background_do_not_change_full_messages(self):
        f = self.frame()
        f.diagnostic_lines = ['warning ' * 100]
        saved = list(f.diagnostic_lines)
        f.present()
        f.size_provider = lambda: (100, 30)
        f.set_background(255)
        f.present()
        self.assertEqual(f.diagnostic_lines, saved)
        self.assertEqual(f.stats['resizes'], 1)
        self.assertTrue(all(style[1] == 255 for row in f.previous for _, style in row.runs))
        self.assertIn('\x1b[K', f.output.getvalue())

    def test_warning_full_stderr_and_registration_are_unchanged(self):
        output = TTY()
        c = Console([''], output, no_wait=True)
        c.enable_color('always')
        c.configure_renderer('diff')
        c._retained.size_provider = lambda: (30, 12)
        message = 'Main.ERB:42 ' + 'detail ' * 100
        stderr = TTY()
        with patch.object(c, '_diagnostic_shares_terminal', return_value=True), patch.object(sys, 'stderr', stderr):
            c.write('game', True)
            history = (list(c.lines), list(c.log_lines))
            c.warning('long', message)
            c.warning('long', message)
        self.assertEqual(stderr.getvalue().count(message), 1)
        self.assertEqual((list(c.lines), list(c.log_lines)), history)
        self.assertEqual(len(c._frame.diagnostic_lines), 1)
        self.assertIn(message, c._frame.diagnostic_lines[0])
        c.close()
