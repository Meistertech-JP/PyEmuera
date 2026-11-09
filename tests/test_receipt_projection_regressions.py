"""New source-review regressions; authoring only during formal48 quiet HOLD.

Do not execute before parent release. These test renderer state and acquisition
ownership without creating a game VM, Native window or OS terminal.
"""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera.console import Console
from pyemuera.system_input import AcceptedInteger, acquire, echo, reject
from pyemuera.terminal_frame import RetainedFrame


def retained_texts(frame):
    return [''.join(text for text, style in runs) for runs, alignment in frame.rows]


class QuietConsole(Console):
    def __init__(self, entries):
        super().__init__(entries, output=io.StringIO())
        self.warning_events = []

    def warning(self, *args):
        self.warning_events.append(args)


class ProjectionProbe(RetainedFrame):
    def __init__(self, output):
        super().__init__(output, columns=40, color=False,
                         size_provider=lambda: SimpleNamespace(columns=40, lines=12))
        self.before_feeds = []

    def feed(self, text, *args, **kwargs):
        self.before_feeds.append((text, retained_texts(self), tuple(self.current)))
        return super().feed(text, *args, **kwargs)


class ReceiptProjectionRegressions(unittest.TestCase):
    def with_temporary_row(self):
        console = QuietConsole(['2'])
        console._retained = ProjectionProbe(console.output)
        reject(console, echo(console, acquire(console)), 'invalid', title=True)
        self.assertEqual((list(console.lines), retained_texts(console._retained)),
                         (['invalid'], ['invalid']))
        console._retained.before_feeds.clear()
        return console

    def test_temporary_removed_before_new_completed_projection(self):
        console = self.with_temporary_row()
        console.write('next', True)
        self.assertEqual(list(console.lines), ['next'])
        self.assertEqual(retained_texts(console._retained), ['next'])
        self.assertEqual(console._retained.before_feeds[0][1], [])

    def test_pending_styled_prefix_survives_temporary_row_removal(self):
        console = self.with_temporary_row()
        console.style_override = (0x123456, 0, 1)
        console.write('prefix')
        pending = tuple(console._retained.current)
        self.assertEqual(''.join(text for text, style in pending), 'prefix')
        console._retained.before_feeds.clear()
        console.style_override = (0x654321, 0, 2)
        console.write('suffix', True)
        self.assertEqual(list(console.lines), ['prefixsuffix'])
        self.assertEqual(retained_texts(console._retained), ['prefixsuffix'])
        self.assertEqual(console._retained.before_feeds[0][1], [])
        self.assertEqual(console._retained.before_feeds[0][2], pending)
        self.assertEqual(console._retained.rows[-1][0][0], pending[0])

    def test_host_echo_rejection_preserves_previous_projection_metadata(self):
        console = QuietConsole(None)
        with patch('shutil.get_terminal_size',
                   return_value=SimpleNamespace(columns=8, lines=12)):
            console.write('ABCDEFGHIJKL', True)
            previous_markup = tuple(console.markup_lines)
            previous_screen_rows = tuple(console._screen_rows)
            previous_rule_rows = tuple(console._rule_lines)
            owner = echo(console, AcceptedInteger('2', 2, True))
            reject(console, owner, 'invalid', title=True)
        self.assertEqual(list(console.lines), ['ABCDEFGHIJKL', 'invalid'])
        self.assertEqual(tuple(console.markup_lines)[:-1], previous_markup)
        self.assertEqual(tuple(console._screen_rows)[:-1], previous_screen_rows)
        self.assertEqual(tuple(console._rule_lines)[:-1], previous_rule_rows)
        self.assertEqual(len(console.markup_lines), 2)
        self.assertEqual(len(console._screen_rows), 2)

    def test_journal_reentry_cannot_overwrite_outer_host_echo_disposition(self):
        class HostRead(QuietConsole):
            def _read_input_entry(self, *args):
                text, timeout = super()._read_input_entry(*args)
                self._host_line_echo = text == '+00'
                return text, timeout

        console = HostRead(['+00', '7'])
        observed = []
        inner = []

        def record(kind, text, timed_out):
            observed.append((kind, text, timed_out))
            if text == '+00':
                inner.append(acquire(console))

        console.journal = SimpleNamespace(note=lambda *a, **kw: None, input=record)
        outer = acquire(console)
        self.assertEqual(inner, [AcceptedInteger('7', 7, False)])
        self.assertEqual(outer, AcceptedInteger('+00', 0, True))
        self.assertEqual(console.input_count, 2)
        self.assertEqual(observed, [('integer', '+00', False),
                                    ('integer', '7', False)])
        echo(console, outer)
        self.assertEqual(console.output.getvalue(), '')
        self.assertEqual(list(console.lines), ['+00'])
        self.assertNotIn('_system_integer_acceptance', console.__dict__)