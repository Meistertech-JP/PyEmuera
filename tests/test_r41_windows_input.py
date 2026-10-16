"""Native adapter and concurrent contracts, not Windows hardware acceptance."""
import ctypes
import io
import signal
import sys
import types
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from pyemuera.cli_interrupts import CLIInterrupts
from pyemuera.console import Console
from pyemuera.errors import EraError
from pyemuera.windows_input import Win32ConsoleLine, read_console_line


class SimulatedNativeReader:
    def __init__(self, result='日本語 Ａ😀', error=None):
        self.handle = object()
        self.started = threading.Event()
        self.release = threading.Event()
        self.result, self.error = result, error
        self.cancel_ids = []
    def read_line(self, cancelled):
        self.started.set()
        self.release.wait(2)
        if cancelled.is_set():
            raise KeyboardInterrupt
        if self.error is not None:
            raise self.error
        return self.result
    def cancel(self, native_id):
        self.cancel_ids.append(native_id)
        self.release.set()
        return 0


class WindowsInputR41(unittest.TestCase):
    def select_native(self, mode=7, is_console=True):
        api, status = MagicMock(), {}
        def get_mode(handle, pointer):
            pointer._obj.value = mode
            return is_console
        api.GetConsoleMode.side_effect = get_mode
        msvcrt = types.SimpleNamespace(get_osfhandle=lambda fd: 0x100000001)
        with patch.dict(sys.modules, msvcrt=msvcrt), patch.object(ctypes, 'WinDLL', return_value=api, create=True):
            selected = Win32ConsoleLine.from_stream(types.SimpleNamespace(fileno=lambda: 0), status)
        return selected, status, api

    def test_native_selection_keeps_cooked_ime_and_quickedit_mode_unchanged(self):
        selected, status, api = self.select_native(503)
        self.assertEqual(selected.mode, 503)
        self.assertEqual(selected.handle, 0x100000001)
        self.assertEqual(status['backend'], 'ReadConsoleW/event')
        api.SetConsoleMode.assert_not_called()
        api.CreateFileW.assert_not_called()

    def test_redirected_stdin_is_not_reopened_as_console(self):
        selected, status, api = self.select_native(is_console=False)
        self.assertIsNone(selected)
        api.ReadConsoleW.assert_not_called()
        api.CreateFileW.assert_not_called()

    def test_raw_console_mode_keeps_owner_and_falls_back(self):
        selected, status, api = self.select_native(mode=1)
        self.assertIsNone(selected)
        self.assertIn('not in cooked', status['fallback_reason'])
        api.SetConsoleMode.assert_not_called()

    def test_echo_disabled_is_reported_without_mode_change(self):
        selected, status, api = self.select_native(mode=3)
        self.assertIsNotNone(selected)
        self.assertFalse(status['host_echo'])
        api.SetConsoleMode.assert_not_called()

    def test_delayed_native_line_blocks_without_spinning(self):
        backend, status = SimulatedNativeReader(), {}
        timer = threading.Timer(.2, backend.release.set)
        timer.start()
        start, cpu = time.monotonic(), time.process_time()
        try:
            self.assertEqual(read_console_line(backend, status), '日本語 Ａ😀')
        finally:
            timer.join()
        self.assertGreater(time.monotonic()-start, .1)
        self.assertLess(time.process_time()-cpu, .1)
        self.assertTrue(status['reader_completed'])
        self.assertFalse(status['active'])
        self.assertEqual(backend.cancel_ids, [])

    def test_sigint_during_blocked_reader_reaches_python_and_cancels_reader(self):
        backend, status = SimulatedNativeReader(), {}
        def deliver():
            backend.started.wait(1)
            signal.raise_signal(signal.SIGINT)
        timer = threading.Timer(.05, deliver)
        with CLIInterrupts() as observer:
            timer.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    read_console_line(backend, status)
            finally:
                timer.join()
            self.assertEqual(observer.received['signal'], 'SIGINT')
        self.assertTrue(status['reader_completed'])
        self.assertTrue(status['cancellation_requested'])
        self.assertEqual(status['state_at_interrupt'], 'console_line_wait')
        self.assertTrue(all(isinstance(x, int) for x in backend.cancel_ids))
        self.assertTrue(backend.cancel_ids)

    def test_reader_eof_is_not_signal_or_cancellation(self):
        backend, status = SimulatedNativeReader(error=EOFError()), {}
        backend.release.set()
        with self.assertRaises(EOFError):
            read_console_line(backend, status)
        self.assertTrue(status['reader_completed'])
        self.assertFalse(status['cancellation_requested'])
        self.assertNotIn('state_at_interrupt', status)

    def test_reader_os_error_remains_os_error(self):
        backend, status = SimulatedNativeReader(error=OSError(5, 'fixture')), {}
        backend.release.set()
        with self.assertRaises(OSError) as exc:
            read_console_line(backend, status)
        self.assertEqual(exc.exception.errno, 5)
        self.assertTrue(status['reader_completed'])

    def native(self, chunks):
        api = MagicMock()
        chunks = iter(chunks)
        def read(handle, buffer, length, count, control):
            text = next(chunks)
            for i, char in enumerate(text):
                buffer[i] = char
            count._obj.value = len(text)
            return True
        api.ReadConsoleW.side_effect = read
        return Win32ConsoleLine(api, 123, 7)

    def test_native_unicode_line_preserves_whitespace_and_combines_utf16_pairs(self):
        backend = self.native([' 日本語\tＡ\ud83d\ude00 \r\n'])
        self.assertEqual(backend.read_line(threading.Event()), ' 日本語\tＡ😀 ')
        backend.api.SetConsoleMode.assert_not_called()

    def test_native_long_line_keeps_chunks_and_trims_one_newline(self):
        backend = self.native(['x'*4096, 'tail\r\n'])
        self.assertEqual(backend.read_line(threading.Event()), 'x'*4096+'tail')

    def test_native_empty_enter_is_not_eof(self):
        self.assertEqual(self.native(['\r\n']).read_line(threading.Event()), '')

    def test_native_ctrl_z_at_start_is_eof(self):
        with self.assertRaises(EOFError):
            self.native(['\x1a\r\n']).read_line(threading.Event())

    def test_native_zero_character_read_is_eof(self):
        with self.assertRaises(EOFError):
            self.native(['']).read_line(threading.Event())

    def test_native_aborted_read_is_interrupt_not_eof(self):
        backend = self.native([])
        backend.api.ReadConsoleW.side_effect = None
        backend.api.ReadConsoleW.return_value = False
        with patch.object(ctypes, 'get_last_error', return_value=995, create=True):
            with self.assertRaises(KeyboardInterrupt):
                backend.read_line(threading.Event())

    def test_cancellation_uses_64bit_thread_handle_and_closes_it(self):
        backend = self.native([])
        backend.api.OpenThread.return_value = 0x100000001
        backend.api.CancelSynchronousIo.return_value = True
        self.assertEqual(backend.cancel(1234), 0)
        backend.api.OpenThread.assert_called_once_with(1, False, 1234)
        backend.api.CancelSynchronousIo.assert_called_once_with(0x100000001)
        backend.api.CloseHandle.assert_called_once_with(0x100000001)

    def test_console_native_read_retains_history_and_no_double_echo(self):
        backend = SimulatedNativeReader(result=' 日本語 Ａ😀 ')
        backend.release.set()
        def select(stream, status):
            status.update(backend='ReadConsoleW/event', host_echo=True)
            return backend
        c = Console(output=io.StringIO())
        with patch('pyemuera.console.os.name', 'nt'), patch.object(Win32ConsoleLine, 'from_stream', side_effect=select):
            text = c.input(string=True)
        c._input_echo(text)
        self.assertEqual(list(c.log_lines), [' 日本語 Ａ😀 '])
        self.assertEqual(c.output.getvalue(), '> ')

    def test_console_redirected_input_retains_python_encoding_and_eof(self):
        c = Console(output=io.StringIO())
        with patch('pyemuera.console.os.name', 'nt'), patch.object(Win32ConsoleLine, 'from_stream', return_value=None):
            with patch('builtins.input', return_value=' 7 '):
                self.assertEqual(c.input(), 7)
            with patch('builtins.input', side_effect=EOFError):
                with self.assertRaises(EraError) as exc:
                    c.input()
        self.assertEqual(exc.exception.code, 'E_INPUT_EOF')
        self.assertEqual(c.input_backend_status['backend'], 'Python input')

    def test_replay_and_timed_line_never_select_native_line_adapter(self):
        with patch.object(Win32ConsoleLine, 'from_stream') as select:
            self.assertEqual(Console(inputs=['全角']).input(string=True), '全角')
            c = Console(output=io.StringIO())
            with patch.object(c, '_timed_read', return_value=None):
                self.assertEqual(c.input(default=9, timeout_ms=100), 9)
            select.assert_not_called()
        self.assertFalse(c.input_backend_status['active'])

    def test_cleanup_retries_gap_before_synchronous_request_is_pending(self):
        backend, status = SimulatedNativeReader(), {}
        def cancel(native_id):
            backend.cancel_ids.append(native_id)
            if len(backend.cancel_ids) > 1:
                backend.release.set()
                return 0
            return 1168  # ERROR_NOT_FOUND before kernel read starts.
        backend.cancel = cancel
        timer = threading.Timer(.05, lambda: signal.raise_signal(signal.SIGINT))
        with CLIInterrupts():
            timer.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    read_console_line(backend, status)
            finally:
                timer.join()
        self.assertGreaterEqual(len(backend.cancel_ids), 2)
        self.assertTrue(status['reader_completed'])

    def test_first_python_signal_receipt_time_is_preserved(self):
        observer = CLIInterrupts()
        with patch('pyemuera.cli_interrupts.time.time', side_effect=[10, 20]):
            with self.assertRaises(KeyboardInterrupt):
                observer._receive(signal.SIGINT, None)
            with self.assertRaises(KeyboardInterrupt):
                observer._receive(signal.SIGINT, None)
        self.assertEqual(observer.received['received_at_unix'], 10)

    def test_failed_cancellation_is_reported_and_prevents_second_reader(self):
        backend, status = SimulatedNativeReader(), {}
        backend.cancel = lambda native_id: 5
        timer = threading.Timer(.05, lambda: signal.raise_signal(signal.SIGINT))
        with CLIInterrupts(), patch('pyemuera.windows_input.CANCEL_SECONDS', .1):
            timer.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    read_console_line(backend, status)
                self.assertTrue(status['cleanup_incomplete'])
                with self.assertRaises(EraError) as exc:
                    read_console_line(backend, {})
                self.assertEqual(exc.exception.code, 'E_CONSOLE')
            finally:
                backend.release.set()
                timer.join()


if __name__ == '__main__':
    unittest.main()
