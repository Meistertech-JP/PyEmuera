"""Host faults must not change the logical commit boundary between renderers.

These neutral streams model VT/append-only, partial-write and flush boundaries;
none of these tests is an execution on a Windows terminal or an Emuera oracle.
"""
import io
import os
import unittest
from unittest.mock import patch

from pyemuera.console import BufferedOutput, Console
from pyemuera.host_output import write_all
from pyemuera.terminal_frame import RetainedFrame


class FaultStream(io.StringIO):
    def __init__(self, fault=None, *, tty=False):
        super().__init__()
        self.fault = fault
        self.tty = tty
        self.writes = []
        self.flushes = 0
        self.armed = True

    def isatty(self):
        return self.tty

    def write(self, text):
        self.writes.append(text)
        if self.armed and self.fault == 'before_write':
            raise OSError('neutral before write')
        if self.armed and self.fault == 'partial_write':
            super().write(text[:max(1, len(text) // 2)])
            raise OSError('neutral partial write')
        return super().write(text)

    def flush(self):
        self.flushes += 1
        if self.armed and self.fault == 'flush':
            raise OSError('neutral during flush')


def make_console(stream, backend='stream', layout='terminal'):
    console = Console(output=stream, layout=layout, ambiguous_width=2)
    console.ui = {'color': 0xc0c0c0, 'bgcolor': 0, 'style': 0,
                  'font': 'mono', 'alignment': 'LEFT', 'redraw': 1}
    console.vt_enabled = backend == 'diff'
    console.configure_renderer(backend)
    return console


def logical(console):
    return (list(console.lines), console.current, list(console.log_lines),
            console.log_current, console.line_count, list(console._rule_lines),
            list(console._screen_rows))


class ConsoleFailureContract(unittest.TestCase):
    def assert_failed_line(self, backend, fault):
        output = FaultStream(fault, tty=backend == 'diff')
        console = make_console(output, backend)
        before = logical(console)
        with self.assertRaises(OSError) as caught:
            console.write('broken', True)
        self.assertEqual(logical(console), before)
        self.assertEqual(console._pending, [])
        self.assertIs(console._output_failure, caught.exception)
        # Capture raw markup is deliberately earlier than the failed boundary.
        self.assertEqual(''.join(t for t, _ in console.markup_lines[0][0]), 'broken')
        written = list(output.writes)
        for operation in (lambda: console.write('later', True), console.flush,
                          lambda: console.reuse_line('later'),
                          lambda: console.clear_lines(1)):
            with self.assertRaises(OSError) as retried:
                operation()
            self.assertIs(retried.exception, caught.exception)
        self.assertEqual(output.writes, written)
        self.assertEqual(logical(console), before)
        output.armed = False
        console.close()
        self.assertEqual(logical(console), before)
        self.assertFalse(any('broken' in text for text in output.writes[len(written):]))

    def test_stream_before_write_has_no_logical_commit(self):
        self.assert_failed_line('stream', 'before_write')

    def test_diff_before_write_has_no_logical_commit(self):
        self.assert_failed_line('diff', 'before_write')

    def test_stream_partial_write_does_not_retry_game_text(self):
        self.assert_failed_line('stream', 'partial_write')

    def test_diff_partial_write_does_not_retry_game_text(self):
        self.assert_failed_line('diff', 'partial_write')

    def test_stream_flush_failure_precedes_logical_commit(self):
        self.assert_failed_line('stream', 'flush')

    def test_diff_flush_failure_precedes_logical_commit(self):
        self.assert_failed_line('diff', 'flush')

    def test_raw_partial_write_preserves_existing_contract(self):
        output = FaultStream('partial_write')
        console = make_console(output, layout='raw')
        with self.assertRaises(OSError):
            console.write('broken', True)
        self.assertEqual(console.line_count, 0)
        self.assertEqual(list(console.lines), [])
        self.assertEqual(list(console.log_lines), [])
        self.assertEqual(output.getvalue(), 'bro')

    def test_failed_flush_keeps_previously_committed_current_and_logs(self):
        output = FaultStream('partial_write')
        output.armed = False
        console = make_console(output)
        console.write('prior')
        before = logical(console)
        output.armed = True
        with self.assertRaises(OSError):
            console.write('broken', True)
        self.assertEqual(logical(console), before)
        self.assertEqual(console.current, 'prior')
        self.assertEqual(console.log_current, 'prior')
        self.assertEqual(console._pending, [])

    def test_fault_after_suppressed_commit_keeps_completed_history(self):
        output = FaultStream('before_write', tty=True)
        console = make_console(output, 'diff')
        console.set_redraw(0)
        console.write('completed', True)
        before = logical(console)
        with self.assertRaises(OSError):
            console.flush(force=True)
        self.assertEqual(logical(console), before)
        self.assertEqual(list(console.lines), ['completed'])

    def test_fault_during_resize_redraw_keeps_history_and_background(self):
        output = FaultStream('partial_write', tty=True)
        output.armed = False
        console = make_console(output, 'diff')
        with patch('shutil.get_terminal_size', return_value=os.terminal_size((84, 24))):
            console.write('healthy', True)
        before = logical(console)
        console.ui['bgcolor'] = 255
        output.armed = True
        with patch('shutil.get_terminal_size', return_value=os.terminal_size((120, 24))):
            with self.assertRaises(OSError):
                console.flush(force=True)
        self.assertEqual(logical(console), before)
        self.assertEqual(console._frame.background, 255)
        self.assertEqual(console._frame.previous_size, (84, 24))

    def test_flushed_prefix_fault_before_newline_does_not_commit_line(self):
        class NewlineFault(FaultStream):
            def write(self, text):
                if text == '\n':
                    raise OSError('neutral before newline')
                return super().write(text)
        output = NewlineFault()
        console = make_console(output)
        with self.assertRaises(OSError):
            console.write('broken', True)
        self.assertEqual(output.getvalue(), 'broken')
        self.assertEqual(list(console.lines), [])
        self.assertEqual(console.line_count, 0)
        console.close()
        self.assertEqual(output.getvalue(), 'broken')

    def test_flush_after_newline_fault_has_no_commit_or_duplicate(self):
        class NewlineFlushFault(FaultStream):
            def flush(self):
                self.flushes += 1
                if self.getvalue().endswith('\n'):
                    raise OSError('neutral newline flush')
        output = NewlineFlushFault()
        console = make_console(output)
        with self.assertRaises(OSError):
            console.write('broken', True)
        self.assertEqual(output.getvalue(), 'broken\n')
        self.assertEqual(console.line_count, 0)
        console.close()
        self.assertEqual(output.getvalue(), 'broken\n')

    def test_closed_stream_valueerror_has_same_commit_boundary(self):
        output = io.StringIO()
        console = make_console(output, layout='raw')
        output.close()
        with self.assertRaises(ValueError) as caught:
            console.write('broken', True)
        self.assertIs(console._output_failure, caught.exception)
        self.assertEqual(console.line_count, 0)

    def test_skipdisp_returns_before_failed_host_check(self):
        output = FaultStream('before_write')
        console = make_console(output, layout='raw')
        with self.assertRaises(OSError):
            console.write('broken', True)
        console.skip_print = True
        console.write('skipped', True)
        self.assertEqual(console.line_count, 0)

    def test_batch_limit_failure_leaves_no_later_replay(self):
        output = FaultStream('partial_write')
        console = make_console(output, layout='raw')
        console.output = BufferedOutput(output, limit=3)
        console.batch_output = True
        with self.assertRaises(OSError):
            console.write('broken', True)
        self.assertEqual(console.output.parts, [])
        self.assertEqual(console.line_count, 0)
        previous = output.getvalue()
        console.close()
        self.assertEqual(output.getvalue(), previous)

    def test_cleanup_restores_cursor_after_failed_frame_without_game_repaint(self):
        output = FaultStream('partial_write', tty=True)
        console = make_console(output, 'diff')
        with self.assertRaises(OSError):
            console.write('broken', True)
        self.assertTrue(console._frame.active)
        output.armed = False
        before = len(output.writes)
        console.close()
        self.assertEqual(output.writes[before:], ['\x1b[0m\x1b[?25h\x1b[?1049l'])
        self.assertFalse(console._frame.active)
        self.assertTrue(console._frame.closed)

    def test_failed_cleanup_still_marks_frame_closed(self):
        output = FaultStream('before_write', tty=True)
        console = make_console(output, 'diff')
        with self.assertRaises(OSError):
            console.write('broken', True)
        with self.assertRaises(OSError):
            console.close()
        self.assertTrue(console._frame.closed)
        self.assertFalse(console._frame.active)
        self.assertEqual(console.line_count, 0)

    def test_direct_background_failure_blocks_mutation_and_cleanup_repaint(self):
        output = FaultStream('partial_write', tty=True)
        output.armed = False
        console = make_console(output, 'diff')
        console.color_enabled = True
        console.write('healthy', True)
        before = logical(console)
        markup = list(console.markup_lines)
        output.armed = True
        with self.assertRaises(OSError) as caught:
            console.set_background(255)
        with self.assertRaises(OSError) as retried:
            console.write('later', True)
        self.assertIs(retried.exception, caught.exception)
        self.assertEqual(logical(console), before)
        self.assertEqual(list(console.markup_lines), markup)
        output.armed = False
        writes = len(output.writes)
        console.close()
        self.assertEqual(output.writes[writes:], ['\x1b[0m\x1b[?25h\x1b[?1049l'])

    def test_renderer_switch_cannot_discard_failure_or_resume_output(self):
        output = FaultStream('partial_write', tty=True)
        console = make_console(output, 'diff')
        with self.assertRaises(OSError) as caught:
            console.write('broken', True)
        frame = console._frame
        retained = console._retained
        writes = len(output.writes)
        for mode in ('stream', 'auto', 'diff'):
            with self.assertRaises(OSError) as switch:
                console.configure_renderer(mode)
            self.assertIs(switch.exception, caught.exception)
            self.assertEqual(console.renderer_mode, 'diff')
            self.assertIs(console._frame, frame)
            self.assertIs(console._retained, retained)
        with self.assertRaisesRegex(ValueError, 'Invalid renderer'):
            console.configure_renderer('invalid')
        output.armed = False
        with self.assertRaises(OSError):
            console.write('later', True)
        self.assertEqual(len(output.writes), writes)
        self.assertEqual(console.line_count, 0)
        console.close()

    def test_standalone_frame_failure_latches_and_keeps_last_present(self):
        output = FaultStream('partial_write', tty=True)
        output.armed = False
        frame = RetainedFrame(output)
        frame.feed('healthy\n')
        frame.present()
        before = (frame.previous, frame.previous_size, frame.last_cursor)
        output.armed = True
        frame.feed('broken\n')
        with self.assertRaises(OSError) as caught:
            frame.present()
        self.assertEqual((frame.previous, frame.previous_size, frame.last_cursor), before)
        writes = len(output.writes)
        with self.assertRaises(OSError) as retried:
            frame.present()
        self.assertIs(retried.exception, caught.exception)
        self.assertEqual(len(output.writes), writes)


class ShortWriteContract(unittest.TestCase):
    def test_short_text_writes_emit_only_the_remaining_suffix(self):
        class Short(FaultStream):
            def write(self, text):
                self.writes.append(text)
                return io.StringIO.write(self, text[:2])
        output = Short()
        write_all(output, 'abcdefg')
        self.assertEqual(output.getvalue(), 'abcdefg')
        self.assertEqual(output.writes, ['abcdefg', 'cdefg', 'efg', 'g'])

    def test_short_frame_writes_do_not_duplicate_runs(self):
        class Short(FaultStream):
            def write(self, text):
                return io.StringIO.write(self, text[:7])
        output = Short(tty=True)
        console = make_console(output, 'diff')
        console.write('once', True)
        self.assertEqual(output.getvalue().count('once'), 1)
        self.assertEqual(list(console.lines), ['once'])
        console.close()

    def test_zero_progress_fails_before_history_commit(self):
        class Zero(FaultStream):
            def write(self, text):
                return 0
        output = Zero()
        console = make_console(output, layout='raw')
        with self.assertRaisesRegex(OSError, 'no valid progress'):
            console.write('broken', True)
        self.assertEqual(console.line_count, 0)

    def test_none_returning_observer_keeps_single_call_contract(self):
        class NoneWriter(FaultStream):
            def write(self, text):
                super().write(text)
                return None
        output = NoneWriter()
        write_all(output, 'once')
        self.assertEqual(output.getvalue(), 'once')
        self.assertEqual(output.writes, ['once'])

    def test_buffered_short_write_preserves_text_order(self):
        class Short(FaultStream):
            def write(self, text):
                return io.StringIO.write(self, text[:2])
        output = Short()
        buffered = BufferedOutput(output)
        buffered.write('one')
        buffered.write('two')
        buffered.flush()
        self.assertEqual(output.getvalue(), 'onetwo')
        self.assertEqual(buffered.parts, [])


class EncodingProgressContract(unittest.TestCase):
    def make_progress_failure(self):
        class ShortThenEncoding(FaultStream):
            @property
            def encoding(self):
                return 'cp932'

            def write(self, text):
                self.writes.append(text)
                if len(self.writes) == 1:
                    return io.StringIO.write(self, text[:2])
                raise UnicodeEncodeError('cp932', text, 0, 1,
                                         'neutral encoding failure after progress')
        return ShortThenEncoding()

    def test_short_progress_then_encoding_error_never_replays_prefix(self):
        output = self.make_progress_failure()
        console = make_console(output, layout='raw')
        with self.assertRaises(UnicodeEncodeError) as caught:
            console.write('broken', True)
        self.assertEqual(caught.exception.reason, 'neutral encoding failure after progress')
        self.assertEqual(caught.exception._pyemuera_written_chars, 2)
        self.assertEqual(output.getvalue(), 'br')
        self.assertEqual(output.writes, ['broken\n', 'oken\n'])
        self.assertEqual(console.line_count, 0)
        with self.assertRaises(UnicodeEncodeError) as retried:
            console.flush()
        self.assertIs(retried.exception, caught.exception)
        console.close()
        self.assertEqual(output.getvalue(), 'br')

    def test_buffered_short_progress_encoding_error_does_not_fallback_full_batch(self):
        output = self.make_progress_failure()
        console = make_console(output, layout='raw')
        console.output = BufferedOutput(output, limit=3)
        console.batch_output = True
        with self.assertRaises(UnicodeEncodeError) as caught:
            console.write('broken', True)
        self.assertEqual(caught.exception._pyemuera_written_chars, 2)
        self.assertEqual(output.getvalue(), 'br')
        self.assertEqual(output.writes, ['broken\n', 'oken\n'])
        self.assertEqual(console.output.parts, [])
        self.assertEqual(console.line_count, 0)
        console.close()
        self.assertEqual(output.getvalue(), 'br')

    def test_initial_atomic_encoding_rejection_keeps_existing_replacement_fallback(self):
        class AtomicEncoding(FaultStream):
            @property
            def encoding(self):
                return 'ascii'

            def write(self, text):
                text.encode('ascii')
                return super().write(text)
        output = AtomicEncoding()
        console = make_console(output, layout='raw')
        console.write('a\ud800b', True)
        self.assertEqual(output.getvalue(), 'a?b\n')
        self.assertEqual(list(console.lines), ['a\ud800b'])
        self.assertIsNone(console._output_failure)
