"""Long physical warnings wrap without entering or displacing game input state."""
import io
import unittest
from pyemuera.terminal_frame import RetainedFrame


class DiagnosticProjection(unittest.TestCase):
    def make(self):
        return RetainedFrame(io.StringIO(), columns=100, color=False,
                             size_provider=lambda: (20, 5))

    def test_long_warning_reserves_game_row_and_width_safe_cells(self):
        frame = self.make()
        frame.feed('GAME')
        frame.diagnostic_lines.append('warning '*40)
        rows, cursor, size = frame.snapshot()
        self.assertLessEqual(len(rows), size[1])
        self.assertTrue(all(row.width <= 19 for row in rows))
        self.assertEqual(cursor, (1, 5))
        self.assertEqual(rows[0].runs[0][0], 'GAME')

    def test_warning_reprojection_does_not_register_again(self):
        frame = self.make()
        frame.feed('GAME')
        frame.external_diagnostic('warning '*40)
        writes = frame.stats['host_writes']
        frame.present()
        self.assertEqual(frame.stats['host_writes'], writes)
        self.assertEqual(len(frame.diagnostic_lines), 1)

    def test_prompt_overlay_restores_pending_game_text_and_location(self):
        frame = self.make()
        frame.feed('GAME')
        frame.diagnostic_lines.append('warning '*40)
        saved = list(frame.current)
        frame.present_prompt('> ')
        self.assertEqual(frame.current, saved)
        self.assertEqual(frame.last_cursor, (1, 7))
        self.assertEqual(len(frame.diagnostic_lines), 1)
