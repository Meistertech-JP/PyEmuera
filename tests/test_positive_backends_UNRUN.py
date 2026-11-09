"""Positive backend drafts, UNRUN. Review before executing after HOLD release.

Use actual retained/prompt methods and the existing bounded CellSurface fixture.
No real TTY, Windows API, VM, game or timing/performance run is constructed.
"""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera.console import Console
from pyemuera.system_input import acquire, echo, reject
from bounded_terminal_suffix_fixture import CellSurface


class TerminalBuffer(io.StringIO):
    def isatty(self):
        return True


class HostReadConsole(Console):
    def __init__(self, entries, *, layout='raw'):
        super().__init__(output=TerminalBuffer(), layout=layout)
        self.entries = iter(entries)
        self.reads = []
        self.notes = []

    def warning(self, *args):
        self.notes.append(args)

    def _read_line(self, prompt):
        raw = next(self.entries)
        self.reads.append((raw, prompt))
        # Model physical host echo outside the engine's output/projection.
        # Existing _read_input_entry still owns present_prompt/finish_prompt.
        if prompt:
            self.output.write(prompt)
        if self._host_line_echo:
            self.output.write(raw + '\r\n')
        return raw


def make(mode, entries, *, layout='raw'):
    console = HostReadConsole(entries, layout=layout)
    console.vt_enabled = True  # fixture capability; never enable an OS mode
    console.configure_renderer(mode)
    console._retained.size_provider = lambda: (40, 5)
    return console


def texts(frame):
    return [''.join(t for t, style in runs) for runs, alignment in frame.rows]


class PositiveBackendContracts(unittest.TestCase):
    def test_auto_normal_host_retry_uses_existing_alternate_frame_and_prompt(self):
        console = make('auto', ['2', '+00'])
        console.output.write('prior shell text\n')
        console.write('game', True)
        self.assertIsNone(console._frame)
        retained = console._retained
        with patch('sys.stdin', SimpleNamespace(isatty=lambda: True)):
            bad = acquire(console)
            self.assertIs(console._frame, retained)
            self.assertTrue(console._frame.alternate_screen)
            self.assertIsNone(console._frame.previous)  # finish_prompt invalidates host echo
            reject(console, echo(console, bad), 'invalid', title=True)
            self.assertEqual(texts(retained), ['game', 'invalid'])
            accepted = acquire(console)
            self.assertEqual((accepted.raw, accepted.value, accepted.host_echo), ('+00', 0, True))
            self.assertIsNone(retained.previous)
            offset = len(console.output.getvalue())
            echo(console, accepted)
        self.assertEqual(console.reads, [('2', ''), ('+00', '')])
        self.assertEqual(list(console.lines), ['game', '+00'])
        self.assertEqual(texts(retained), ['game', '+00'])
        self.assertEqual(console.input_count, 2)
        self.assertTrue(console.system_input_display_status['physical_retry_row_replacement'])
        physical = CellSurface()
        # The final present is a full existing-frame repaint after invalidation.
        # This fixture covers non-wrapping cells only, not OS input or scrolling.
        physical.apply(console.output.getvalue()[offset:])
        self.assertEqual(''.join(physical.cells[0]).rstrip(), 'game')
        self.assertEqual(''.join(physical.cells[1]).rstrip(), '+00')
        data = console.output.getvalue()
        enter = data.index('\x1b[?1049h')
        self.assertNotIn('\x1b[K', data[:enter])
        console.close()
        self.assertIn('\x1b[?1049l', console.output.getvalue())

    def test_auto_transfers_pending_terminal_projection_without_losing_style(self):
        console = make('auto', ['0'], layout='terminal')
        console.style_override = (0x123456, 0, 1)
        console.write('prefix')
        pending = tuple(console._retained.current)
        self.assertTrue(console._pending)
        with patch('sys.stdin', SimpleNamespace(isatty=lambda: True)):
            echo(console, acquire(console))
        self.assertIs(console._frame, console._retained)
        self.assertEqual(list(console.lines), ['prefix', '0'])
        self.assertEqual(console._retained.rows[0][0], pending)
        self.assertEqual(console._pending, [])

    def test_auto_temporary_replacement_keeps_two_pending_styles(self):
        console = make('auto', ['2'])
        with patch('sys.stdin', SimpleNamespace(isatty=lambda: True)):
            reject(console, echo(console, acquire(console)), 'invalid', title=True)
        console.style_override = (0x123456, 0, 1)
        console.write('prefix')
        pending = tuple(console._retained.current)
        console.style_override = (0x654321, 0, 2)
        console.write('suffix', True)
        self.assertEqual(list(console.lines), ['prefixsuffix'])
        self.assertEqual(texts(console._retained), ['prefixsuffix'])
        self.assertEqual(console._retained.rows[0][0][0], pending[0])
        self.assertEqual(console._retained.rows[0][0][-1], ('suffix', (0x654321, 0, 2)))

    def test_explicit_stream_host_retry_keeps_append_only_bytes_without_cursor_erase(self):
        console = make('stream', ['2', '0'])
        console.output.write('prior shell text\n')
        console.write('game', True)
        with patch('sys.stdin', SimpleNamespace(isatty=lambda: True)):
            reject(console, echo(console, acquire(console)), 'invalid', title=True)
            echo(console, acquire(console))
        self.assertEqual(console.renderer_mode, 'stream')
        self.assertIsNone(console._frame)
        self.assertFalse(console._retained.alternate_screen)
        self.assertEqual(list(console.lines), ['game', '0'])
        self.assertEqual(texts(console._retained), ['game', '0'])
        self.assertEqual(console.output.getvalue(),
                         'prior shell text\ngame\n> 2\r\ninvalid\n> 0\r\n')
        self.assertFalse(console.system_input_display_status['physical_retry_row_replacement'])
        self.assertTrue(console.system_input_display_status['system_retry_transcript_preserved'])

    def test_explicit_stream_already_physical_prefix_is_not_erased_or_replayed(self):
        console = make('stream', ['2'])
        with patch('sys.stdin', SimpleNamespace(isatty=lambda: True)):
            reject(console, echo(console, acquire(console)), 'invalid', title=True)
        console.style_override = (0x123456, 0, 1)
        console.write('prefix')
        before = console.output.getvalue()
        console.style_override = (0x654321, 0, 2)
        console.write('suffix', True)
        self.assertEqual(console.output.getvalue(), before + 'suffix\n')
        self.assertEqual(console.output.getvalue().count('prefix'), 1)
        self.assertEqual(list(console.lines), ['prefixsuffix'])
        self.assertEqual(texts(console._retained), ['prefixsuffix'])
        self.assertNotIn('\x1b[', console.output.getvalue())

    def test_explicit_stream_does_not_initiate_a_main_screen_repaint(self):
        console = make('stream', ['0'])
        original_model = console._retained
        with patch.object(console, '_activate_frame', wraps=console._activate_frame) as activate:
            with patch('sys.stdin', SimpleNamespace(isatty=lambda: True)):
                echo(console, acquire(console))
        activate.assert_not_called()
        self.assertIs(console._retained, original_model)
        self.assertIsNone(console._frame)

    def test_existing_active_frame_is_reused_without_renderer_preference_change(self):
        console = make('stream', ['0'])
        console._activate_frame(flush_pending=False)  # existing background/repaint capability
        original = console._frame
        with patch('sys.stdin', SimpleNamespace(isatty=lambda: True)):
            echo(console, acquire(console))
        self.assertIs(console._frame, original)
        self.assertEqual(console.renderer_mode, 'stream')
        self.assertFalse(original.alternate_screen)

    def test_nontty_canonical_retry_keeps_transcript_and_native_logical_rows(self):
        console = Console(['2', '0'], output=io.StringIO())
        console.configure_renderer('auto')
        reject(console, echo(console, acquire(console)), 'invalid', title=True)
        echo(console, acquire(console))
        self.assertIsNone(console._frame)
        self.assertIsNone(console._retained)
        self.assertEqual(console.output.getvalue(), '2\ninvalid\n0\n')
        self.assertEqual((list(console.lines), console.line_count), (['0'], 1))
        self.assertEqual(console.input_count, 2)

    def test_existing_frame_output_failure_latch_prevents_retry(self):
        console = make('auto', ['2'])
        with patch('sys.stdin', SimpleNamespace(isatty=lambda: True)):
            owner = echo(console, acquire(console))
        before_inputs = console.input_count
        with patch.object(console.output, 'write', side_effect=OSError('host fail')) as writes:
            with self.assertRaises(OSError):
                reject(console, owner, 'invalid', title=True)
            calls = writes.call_count
            with self.assertRaises(OSError):
                console.write('do not retry', True)
            self.assertEqual(writes.call_count, calls)
        self.assertEqual(console.input_count, before_inputs)
        self.assertIsNotNone(console._output_failure)
