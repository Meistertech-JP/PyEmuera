"""Deterministic fake-Win32 output leases, never Windows acceptance evidence."""

import ctypes
import io
import threading
import types
import unittest
from unittest.mock import MagicMock, patch

from pyemuera.console import BufferedOutput, Console
from pyemuera.windows_console_mode import WindowsOutputMode, _Win32OutputAPI


class FakeAPI:
    def __init__(self, mode=3):
        self.mode = mode
        self.calls = []
        self.get_failure = False
        self.set_failure = False

    def get_mode(self, handle):
        self.calls.append(('get', handle))
        if self.get_failure:
            raise OSError(6, 'neutral GetConsoleMode failure')
        return self.mode

    def set_mode(self, handle, mode):
        self.calls.append(('set', handle, mode))
        if self.set_failure:
            raise OSError(5, 'neutral SetConsoleMode failure')
        self.mode = mode


class Output(io.StringIO):
    fail = None

    def isatty(self):
        return True

    def fileno(self):
        return 91

    def write(self, text):
        if self.fail == 'write':
            raise OSError('neutral cleanup output failure')
        if self.fail == 'interrupt':
            raise KeyboardInterrupt
        return super().write(text)

    def flush(self):
        if self.fail == 'flush':
            raise OSError('neutral cleanup flush failure')


def make_console(mode=3, renderer='stream'):
    api = FakeAPI(mode)
    lease = WindowsOutputMode(api, 0x100000001)
    stream = Output()
    console = Console(output=stream)
    with patch('pyemuera.console.os.name', 'nt'), patch.object(
        WindowsOutputMode, 'for_output', return_value=lease
    ):
        console.enable_color('auto')
    console.configure_renderer(renderer)
    return console, api, lease, stream


class ConsoleModeLifecycle(unittest.TestCase):
    def test_initial_vt_off_normal_exit_restores_exact_original(self):
        console, api, lease, _ = make_console()
        self.assertEqual(api.mode, 7)
        console.write('healthy', True)
        console.close()
        self.assertEqual(api.mode, 3)
        self.assertEqual(lease.status['restore_status'], 'restored')

    def test_initial_vt_off_ctrl_c_cleanup_restores(self):
        import signal
        from pyemuera.cli_interrupts import CLIInterrupts

        console, api, _, _ = make_console()
        owner = CLIInterrupts()
        try:
            owner._receive(signal.SIGINT, None)
        except KeyboardInterrupt:
            console.close()
        self.assertEqual(owner.received['signal'], 'SIGINT')
        self.assertEqual(api.mode, 3)

    def test_initial_vt_off_ctrl_break_cleanup_restores(self):
        from pyemuera.cli_interrupts import CLIInterrupts

        console, api, lease, _ = make_console()
        owner = CLIInterrupts()
        with patch('pyemuera.cli_interrupts.signal.Signals') as name:
            name.return_value.name = 'SIGBREAK'
            try:
                owner._receive(21, None)
            except KeyboardInterrupt:
                console.close()
        self.assertEqual(owner.received['signal'], 'SIGBREAK')
        self.assertEqual(api.mode, 3)
        self.assertEqual(lease.status['events'][-1]['operation'], 'restore')

    def test_initial_vt_on_normal_exit_never_disables_vt(self):
        console, api, lease, _ = make_console(7)
        console.close()
        self.assertEqual(api.mode, 7)
        self.assertFalse(any(call[0] == 'set' for call in api.calls))
        self.assertEqual(lease.status['restore_status'], 'not_required')

    def test_initial_vt_on_interruption_never_disables_vt(self):
        console, api, _, stream = make_console(7)
        console._last_style = (1, 2, 3)
        stream.fail = 'interrupt'
        with self.assertRaises(KeyboardInterrupt):
            console.close()
        self.assertEqual(api.mode, 7)
        self.assertFalse(any(call[0] == 'set' for call in api.calls))

    def test_error_exit_restores_without_changing_logical_history(self):
        console, api, _, _ = make_console()
        console.write('healthy', True)
        before = (list(console.lines), list(console.log_lines), console.line_count)
        with self.assertRaises(ValueError):
            try:
                raise ValueError('neutral VM error')
            finally:
                console.close()
        self.assertEqual(api.mode, 3)
        self.assertEqual(
            (list(console.lines), list(console.log_lines), console.line_count), before
        )

    def test_failed_style_cleanup_still_restores_output_mode(self):
        console, api, lease, stream = make_console()
        console._last_style = (1, 2, 3)
        stream.fail = 'write'
        with self.assertRaises(OSError):
            console.close()
        self.assertEqual(api.mode, 3)
        self.assertEqual(lease.status['restore_status'], 'restored')

    def test_failed_frame_cleanup_still_restores_output_mode(self):
        console, api, lease, stream = make_console(renderer='diff')
        console.write('healthy', True)
        stream.fail = 'write'
        with self.assertRaises(OSError):
            console.close()
        self.assertEqual(api.mode, 3)
        self.assertTrue(console._frame.closed)
        self.assertEqual(lease.status['restore_status'], 'restored')

    def test_failed_cleanup_flush_still_restores_output_mode(self):
        console, api, lease, stream = make_console()
        console._last_style = (1, 2, 3)
        stream.fail = 'flush'
        with self.assertRaises(OSError):
            console.close()
        self.assertEqual(api.mode, 3)
        self.assertEqual(lease.status['restore_status'], 'restored')

    def test_interrupt_during_style_cleanup_still_restores_output_mode(self):
        console, api, _, stream = make_console()
        console._last_style = (1, 2, 3)
        stream.fail = 'interrupt'
        with self.assertRaises(KeyboardInterrupt):
            console.close()
        self.assertEqual(api.mode, 3)

    def test_failed_game_output_does_not_prevent_mode_restore_or_replay(self):
        console, api, _, stream = make_console()
        stream.fail = 'write'
        with self.assertRaises(OSError):
            console.write('broken', True)
        stream.fail = None
        console.close()
        self.assertEqual(api.mode, 3)
        self.assertEqual(stream.getvalue(), '')
        self.assertEqual(list(console.lines), [])

    def test_style_cleanup_is_sent_while_vt_is_still_enabled(self):
        console, api, _, stream = make_console()
        observed = []
        original_write = stream.write

        def writing(text):
            observed.append((text, api.mode))
            return original_write(text)

        stream.write = writing
        console._last_style = (1, 2, 3)
        console.close()
        self.assertEqual(observed, [('\x1b[0m', 7)])
        self.assertEqual(api.mode, 3)

    def test_close_twice_restores_mode_only_once(self):
        console, api, _, _ = make_console()
        console.close()
        console.close()
        self.assertEqual([call[2] for call in api.calls if call[0] == 'set'], [7, 3])

    def test_failed_mode_restore_is_serializable_and_can_be_retried(self):
        console, api, lease, _ = make_console()
        api.set_failure = True
        console.close()
        self.assertEqual(api.mode, 7)
        self.assertTrue(lease.owns_change)
        self.assertEqual(console.output_mode_status['restore_status'], 'failed')
        self.assertEqual(console.output_mode_status['events'][-1]['error_win32'], 5)
        api.set_failure = False
        console.close()
        self.assertEqual(api.mode, 3)
        self.assertEqual(lease.status['restore_status'], 'restored')
        self.assertTrue(any(event['status'] == 'failed' for event in lease.status['events']))

    def test_failed_restore_query_keeps_lease_and_reports_failure(self):
        console, api, lease, _ = make_console()
        api.get_failure = True
        console.close()
        self.assertEqual(api.mode, 7)
        self.assertTrue(lease.owns_change)
        self.assertEqual(lease.status['restore_status'], 'failed')
        self.assertEqual(lease.status['events'][-1]['error_win32'], 6)

    def test_external_mode_change_is_not_overwritten(self):
        console, api, lease, _ = make_console()
        api.mode = 15
        console.close()
        self.assertEqual(api.mode, 15)
        self.assertEqual(lease.status['restore_status'], 'ownership_lost')
        self.assertEqual([call[2] for call in api.calls if call[0] == 'set'], [7])

    def test_ownership_loss_cannot_reenable_or_restore_an_external_mode(self):
        console, api, lease, _ = make_console()
        api.mode = 11
        console.close()
        before = list(api.calls)
        with patch('pyemuera.console.os.name', 'nt'):
            console.enable_color('always')
        console.close()
        self.assertEqual(api.mode, 11)
        self.assertFalse(console.color_enabled)
        self.assertEqual(api.calls, before)
        self.assertEqual(lease.status['restore_status'], 'ownership_lost')

    def test_external_change_synchronized_before_restore_is_preserved(self):
        console, api, lease, _ = make_console()
        query_started = threading.Event()
        host_changed = threading.Event()
        original_get = api.get_mode

        def get_mode(handle):
            query_started.set()
            self.assertTrue(host_changed.wait(5))
            return original_get(handle)

        def external_host():
            if query_started.wait(5):
                api.mode = 11
            host_changed.set()

        api.get_mode = get_mode
        thread = threading.Thread(target=external_host)
        thread.start()
        try:
            console.close()
        finally:
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(api.mode, 11)
        self.assertEqual(lease.status['restore_status'], 'ownership_lost')

    def test_enabling_twice_preserves_first_original_mode(self):
        console, api, lease, _ = make_console()
        with patch('pyemuera.console.os.name', 'nt'):
            console.enable_color('always')
        self.assertEqual(lease.status['original_mode'], 3)
        self.assertEqual([call[2] for call in api.calls if call[0] == 'set'], [7])
        console.close()
        self.assertEqual(api.mode, 3)

    def test_failed_enable_set_never_claims_restoration(self):
        api = FakeAPI()
        api.set_failure = True
        lease = WindowsOutputMode(api, 91)
        self.assertFalse(lease.enable())
        lease.restore()
        self.assertFalse(lease.owns_change)
        self.assertEqual(api.mode, 3)
        self.assertEqual(lease.status['restore_status'], 'not_required')

    def test_failed_enable_query_never_changes_mode(self):
        api = FakeAPI()
        api.get_failure = True
        lease = WindowsOutputMode(api, 91)
        self.assertFalse(lease.enable())
        lease.restore()
        self.assertEqual(api.calls, [('get', 91)])
        self.assertEqual(lease.status['events'][-1]['error_win32'], 6)

    def test_redirected_handle_query_failure_never_changes_console(self):
        api = FakeAPI()
        api.get_failure = True
        lease = WindowsOutputMode(api, 91)
        self.assertFalse(lease.enable())
        self.assertFalse(any(call[0] == 'set' for call in api.calls))

    def test_actual_output_descriptor_selects_handle_not_process_stdout(self):
        api = FakeAPI()
        msvcrt = types.SimpleNamespace(get_osfhandle=MagicMock(return_value=0x100000001))
        with patch.dict('sys.modules', msvcrt=msvcrt), patch(
            'pyemuera.windows_console_mode._Win32OutputAPI', return_value=api
        ):
            lease = WindowsOutputMode.for_output(Output())
        msvcrt.get_osfhandle.assert_called_once_with(91)
        self.assertEqual(lease.handle, 0x100000001)

    def test_buffered_output_preserves_original_descriptor(self):
        api = FakeAPI()
        msvcrt = types.SimpleNamespace(get_osfhandle=MagicMock(return_value=0x100000001))
        with patch.dict('sys.modules', msvcrt=msvcrt), patch(
            'pyemuera.windows_console_mode._Win32OutputAPI', return_value=api
        ):
            lease = WindowsOutputMode.for_output(BufferedOutput(Output()))
        self.assertTrue(lease.enable())
        msvcrt.get_osfhandle.assert_called_once_with(91)

    def test_stringio_without_descriptor_keeps_failure_observable(self):
        msvcrt = types.SimpleNamespace(get_osfhandle=MagicMock())
        with patch.dict('sys.modules', msvcrt=msvcrt):
            lease = WindowsOutputMode.for_output(io.StringIO())
        self.assertFalse(lease.enable())
        self.assertEqual(lease.status['events'][-1]['operation'], 'output_handle')
        msvcrt.get_osfhandle.assert_not_called()

    def test_linux_mode_path_does_not_create_windows_lease(self):
        console = Console(output=Output())
        with patch('pyemuera.console.os.name', 'posix'):
            console.enable_color('auto')
        self.assertNotIn('_output_mode', console.__dict__)
        self.assertNotIn('output_mode_status', console.__dict__)
        console.close()

    def test_never_color_does_not_create_windows_lease(self):
        console = Console(output=Output())
        with patch('pyemuera.console.os.name', 'nt'):
            console.enable_color('never')
        self.assertNotIn('_output_mode', console.__dict__)
        console.close()

    def test_color_never_after_enable_still_restores_owned_mode(self):
        console, api, _, _ = make_console()
        with patch('pyemuera.console.os.name', 'nt'):
            console.enable_color('never')
        console.close()
        self.assertEqual(api.mode, 3)

    def test_interrupt_during_enable_query_remains_observable_and_propagates(self):
        api = FakeAPI()
        interrupted = KeyboardInterrupt()
        api.get_mode = MagicMock(side_effect=interrupted)
        lease = WindowsOutputMode(api, 91)
        with self.assertRaises(KeyboardInterrupt) as caught:
            lease.enable()
        self.assertIs(caught.exception, interrupted)
        self.assertEqual(lease.status['events'][-1], {
            'operation': 'enable', 'phase': 'query', 'status': 'interrupted'
        })
        lease.restore()
        self.assertEqual(api.mode, 3)
        self.assertFalse(lease.owns_change)

    def test_interrupt_before_enable_set_does_not_claim_success_or_restore(self):
        api = FakeAPI()
        interrupted = KeyboardInterrupt()
        api.set_mode = MagicMock(side_effect=interrupted)
        lease = WindowsOutputMode(api, 91)
        with self.assertRaises(KeyboardInterrupt) as caught:
            lease.enable()
        self.assertIs(caught.exception, interrupted)
        self.assertFalse(lease.owns_change)
        self.assertEqual(lease.status['restore_status'], 'pending_confirmation')
        lease.restore()
        self.assertEqual(lease.status['restore_status'], 'unconfirmed_change')
        self.assertEqual(api.set_mode.call_count, 1)

    def test_interrupt_after_enable_set_requeries_then_restores(self):
        api = FakeAPI()
        original_set = api.set_mode
        interrupted = KeyboardInterrupt()

        def change_then_interrupt(handle, mode):
            original_set(handle, mode)
            raise interrupted

        api.set_mode = change_then_interrupt
        lease = WindowsOutputMode(api, 91)
        with self.assertRaises(KeyboardInterrupt) as caught:
            lease.enable()
        self.assertIs(caught.exception, interrupted)
        self.assertIsNone(lease.status['mode_changed'])
        self.assertEqual(api.mode, 7)
        api.set_mode = original_set
        lease.restore()
        self.assertEqual(api.mode, 3)
        self.assertEqual(lease.status['restore_status'], 'restored')
        self.assertEqual(lease.status['events'][0]['status'], 'interrupted')

    def test_repeated_enable_cannot_erase_an_interrupted_attempt_original(self):
        api = FakeAPI()
        original_set = api.set_mode

        def change_then_interrupt(handle, mode):
            original_set(handle, mode)
            raise KeyboardInterrupt

        api.set_mode = change_then_interrupt
        lease = WindowsOutputMode(api, 91)
        with self.assertRaises(KeyboardInterrupt):
            lease.enable()
        api.set_mode = original_set
        self.assertFalse(lease.enable())
        self.assertEqual(lease.status['original_mode'], 3)
        lease.restore()
        self.assertEqual(api.mode, 3)

    def test_interrupt_during_restore_query_preserves_owner_and_propagates(self):
        _, api, lease, _ = make_console()
        original_get = api.get_mode
        interrupted = KeyboardInterrupt()
        api.get_mode = MagicMock(side_effect=interrupted)
        with self.assertRaises(KeyboardInterrupt) as caught:
            lease.restore()
        self.assertIs(caught.exception, interrupted)
        self.assertTrue(lease.owns_change)
        self.assertEqual(lease.status['restore_status'], 'interrupted')
        api.get_mode = original_get
        lease.restore()
        self.assertEqual(api.mode, 3)

    def test_interrupt_before_restore_set_is_not_reported_as_success(self):
        _, api, lease, _ = make_console()
        original_set = api.set_mode
        interrupted = KeyboardInterrupt()
        api.set_mode = MagicMock(side_effect=interrupted)
        with self.assertRaises(KeyboardInterrupt) as caught:
            lease.restore()
        self.assertIs(caught.exception, interrupted)
        self.assertTrue(lease.owns_change)
        self.assertEqual(lease.status['restore_status'], 'interrupted')
        self.assertEqual(api.mode, 7)
        api.set_mode = original_set
        lease.restore()
        self.assertEqual(api.mode, 3)

    def test_interrupt_after_restore_set_preserves_uncertain_result(self):
        _, api, lease, _ = make_console()
        original_set = api.set_mode
        interrupted = KeyboardInterrupt()

        def change_then_interrupt(handle, mode):
            original_set(handle, mode)
            raise interrupted

        api.set_mode = change_then_interrupt
        with self.assertRaises(KeyboardInterrupt) as caught:
            lease.restore()
        self.assertIs(caught.exception, interrupted)
        self.assertEqual(api.mode, 3)
        self.assertEqual(lease.status['restore_status'], 'interrupted')
        api.set_mode = original_set
        before = list(api.calls)
        lease.restore()
        self.assertEqual(lease.status['restore_status'], 'ownership_lost')
        self.assertFalse(any(call[0] == 'set' for call in api.calls[len(before):]))

    def test_typed_api_keeps_large_handle_and_records_getlast_error(self):
        kernel = MagicMock()
        handle = 0x100000001

        def get_mode(selected, pointer):
            self.assertEqual(selected, handle)
            pointer._obj.value = 3
            return 1

        kernel.GetConsoleMode.side_effect = get_mode
        kernel.SetConsoleMode.return_value = 1
        with patch.object(ctypes, 'WinDLL', return_value=kernel, create=True):
            api = _Win32OutputAPI()
        self.assertEqual(api.get_mode(handle), 3)
        api.set_mode(handle, 7)
        kernel.SetConsoleMode.assert_called_once_with(handle, 7)
        kernel.GetConsoleMode.side_effect = None
        kernel.GetConsoleMode.return_value = 0
        with patch.object(ctypes, 'get_last_error', return_value=6, create=True):
            with self.assertRaises(OSError) as caught:
                api.get_mode(handle)
        self.assertEqual(caught.exception.errno, 6)


if __name__ == '__main__':
    unittest.main()
