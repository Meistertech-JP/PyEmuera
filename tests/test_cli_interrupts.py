"""CLI signal contracts; mocked Win32 results are not Windows measurements."""
import ctypes
import io
import signal
import unittest
from unittest.mock import MagicMock, patch
from pyemuera.cli_interrupts import CLIInterrupts
from pyemuera.console import Console
from pyemuera.errors import EraError


class InterruptContracts(unittest.TestCase):
    def test_received_sigint_is_distinct_from_eof(self):
        c = CLIInterrupts()
        with self.assertRaises(KeyboardInterrupt):
            c._receive(signal.SIGINT, None)
        self.assertEqual(c.received['signal'], 'SIGINT')

    def test_repeated_signal_during_finishing_does_not_abort_reports(self):
        c = CLIInterrupts()
        c.finishing = True
        c._receive(signal.SIGINT, None)
        self.assertIsNone(c.received)

    def test_handlers_are_restored_after_exception(self):
        original = signal.getsignal(signal.SIGINT)
        with self.assertRaises(RuntimeError):
            with CLIInterrupts() as c:
                self.assertEqual(signal.getsignal(signal.SIGINT), c._receive)
                raise RuntimeError('test')
        self.assertEqual(signal.getsignal(signal.SIGINT), original)

    def test_sigbreak_is_installed_if_available(self):
        c = CLIInterrupts()
        fake = 12345
        with patch.object(signal, 'SIGBREAK', fake, create=True), patch.object(signal, 'signal', return_value='old') as install:
            with c:
                self.assertIn('SIGBREAK', c.setup['handlers'])
            self.assertIn(unittest.mock.call(fake, c._receive), install.call_args_list)
            self.assertIn(unittest.mock.call(fake, 'old'), install.call_args_list)

    def configure(self, mode=0, has_console=True, set_success=True):
        c = CLIInterrupts();api = MagicMock()
        api.GetStdHandle.return_value = 0x100000001
        api.SetConsoleCtrlHandler.return_value = 1
        def get_mode(handle, pointer):
            pointer._obj.value = mode
            return int(has_console)
        api.GetConsoleMode.side_effect = get_mode
        api.SetConsoleMode.return_value = int(set_success)
        with patch.object(ctypes, 'WinDLL', return_value=api, create=True):
            c._configure_windows()
        return c, api

    def test_win32_reenables_process_reception_and_processed_input(self):
        c, api = self.configure(6)
        api.SetConsoleCtrlHandler.assert_called_once_with(None, False)
        api.SetConsoleMode.assert_called_once_with(0x100000001, 7)
        self.assertTrue(c.setup['windows']['processed_input_enabled'])

    def test_win32_existing_processed_mode_is_unchanged(self):
        c, api = self.configure(7)
        api.SetConsoleMode.assert_not_called()
        self.assertFalse(c.setup['windows']['input_mode_changed'])

    def test_win32_owned_input_bit_is_restored(self):
        c, api = self.configure(6)
        c.__exit__(None, None, None)
        self.assertEqual(api.SetConsoleMode.call_args.args, (0x100000001, 6))

    def test_redirected_input_has_no_console_mode_write(self):
        c, api = self.configure(has_console=False)
        api.SetConsoleMode.assert_not_called()
        self.assertFalse(c.setup['windows']['console_input'])

    def test_failed_mode_change_is_reported_and_not_restored(self):
        c, api = self.configure(set_success=False)
        self.assertFalse(c.setup['windows']['processed_input_enabled'])
        c.__exit__(None, None, None)
        self.assertEqual(api.SetConsoleMode.call_count, 1)

    def test_plain_eof_remains_input_eof(self):
        c = Console(inputs=[], output=io.StringIO())
        with self.assertRaises(EraError) as exc:
            c.input()
        self.assertEqual(exc.exception.code, 'E_INPUT_EOF')

    def test_keyboard_interrupt_is_not_coerced_to_eof(self):
        c = Console(output=io.StringIO())
        with patch('builtins.input', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            c.input()
