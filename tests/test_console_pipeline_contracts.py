"""Public Console ordering across projection, history, replay and cancellation."""
import io
import unittest
from unittest.mock import Mock, patch
from pyemuera.console import Console
from pyemuera.errors import EraError


class OutputPipeline(unittest.TestCase):
    def test_host_failure_keeps_markup_but_not_completed_logical_history(self):
        class Failing(io.StringIO):
            def write(self, text):
                super().write(text)
                raise OSError('host failed after partial write')
        output = Failing()
        console = Console(output=output)
        with self.assertRaises(OSError):
            console.write('new', True)
        self.assertEqual(output.getvalue(), 'new\n')
        self.assertEqual(''.join(t for t, _ in console.markup_lines[0][0]), 'new')
        self.assertEqual(list(console.lines), [])
        self.assertEqual(list(console.log_lines), [])
        self.assertEqual(console.line_count, 0)

    def test_display_and_outputlog_can_retain_distinct_text(self):
        console = Console(output=io.StringIO())
        console.write('visible', True, log_text='logged')
        self.assertEqual(list(console.lines), ['visible'])
        self.assertEqual(list(console.log_lines), ['logged'])

    def test_blank_log_row_and_blank_display_row_stay_distinct(self):
        console = Console(output=io.StringIO())
        console.write('', True)
        self.assertEqual(list(console.lines), [''])
        self.assertEqual(list(console.log_lines), [' '])

    def test_terminal_size_is_measured_per_completed_logical_row(self):
        console = Console(output=io.StringIO())
        import os
        with patch('shutil.get_terminal_size', side_effect=[os.terminal_size((2, 24)), os.terminal_size((4, 24))]) as size:
            console.write('abc\nabc\n')
        self.assertEqual(size.call_count, 2)
        self.assertEqual(list(console._screen_rows), [2, 1])


class InputPipeline(unittest.TestCase):
    def test_malformed_replay_consumes_record_before_accepted_input_count(self):
        journal = Mock()
        console = Console(inputs=[{'kind':'integer','text':'7','timeout':1}], output=io.StringIO(), journal=journal)
        with self.assertRaises(EraError) as caught:
            console.input()
        self.assertEqual(caught.exception.code, 'E_REPLAY')
        self.assertEqual(console.input_count, 0)
        journal.note.assert_called_once_with('input_request', kind='integer')
        journal.input.assert_not_called()
        with self.assertRaises(EraError) as exhausted:
            console.input()
        self.assertEqual(exhausted.exception.code, 'E_INPUT_EOF')

    def test_one_unit_conversion_follows_full_string_recording(self):
        journal = Mock()
        console = Console(inputs=[{'kind':'key','text':'😀x'}], output=io.StringIO(), journal=journal)
        result = console.input(string=True, one=True, kind='key')
        self.assertEqual(result, '\ud83d')
        journal.input.assert_called_once_with('key', '😀x', False)
        self.assertEqual(list(console.log_lines), [])

    def test_interactive_retry_uses_original_deadline_and_each_clock_read(self):
        console = Console(output=io.StringIO())
        journal = Mock()
        console.journal = journal
        with patch.object(console, '_timed_read', side_effect=['bad','7']) as read, patch('pyemuera.console.time.monotonic', side_effect=[100, 100.2, 100.6]) as clock:
            value = console.input(timeout_ms=1000)
        self.assertEqual(value, 7)
        self.assertEqual(clock.call_count, 3)
        self.assertAlmostEqual(read.call_args_list[0].args[0], .8)
        self.assertAlmostEqual(read.call_args_list[1].args[0], .4)
        self.assertEqual(console.input_count, 2)
        self.assertEqual([c.args for c in journal.input.call_args_list], [('integer','bad',False), ('integer','7',False)])

    def test_timeout_returns_default_before_one_unit_or_integer_conversion(self):
        console = Console(inputs=[{'kind':'integer','text':'bad','timeout':True}], output=io.StringIO())
        self.assertEqual(console.input(default=12, timeout_ms=10, one=True), 12)
        self.assertTrue(console.last_timeout)
        self.assertEqual(console.input_count, 1)

    def test_keyboard_interrupt_finishes_prompt_and_is_not_eof(self):
        console = Console(output=io.StringIO())
        frame = Mock()
        console._frame = frame
        with patch.object(console, '_timed_read', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            console.input(timeout_ms=1000)
        frame.finish_prompt.assert_called_once_with()
        self.assertEqual(console.input_count, 0)

    def test_eof_finishes_key_prompt_before_diagnostic_conversion(self):
        console = Console(output=io.StringIO())
        frame = Mock()
        console._frame = frame
        with patch.object(console, '_read_key', side_effect=EOFError), self.assertRaises(EraError) as caught:
            console.input(one=True)
        self.assertEqual(caught.exception.code, 'E_INPUT_EOF')
        self.assertIsInstance(caught.exception.__cause__, EOFError)
        frame.finish_prompt.assert_called_once_with()
        self.assertEqual(console.input_count, 0)
