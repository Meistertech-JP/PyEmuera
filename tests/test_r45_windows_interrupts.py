"""Controlled host races, not Windows hardware or physical-key acceptance.

Event barriers establish input/cancellation order. The real local SIGINT tests
exercise Python main-thread delivery; SIGBREAK uses an explicit fake number on
Linux. No original game, test, received log, or Oracle is rewritten.
"""

import ctypes
import io
import json
import signal
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pyemuera import cli, windows_input
from pyemuera.cli_interrupts import CLIInterrupts
from pyemuera.console import Console
from pyemuera.errors import EraError
from pyemuera.journal import RunJournal
from pyemuera.outputlog import capture_summary
from pyemuera.runtime import VM
from pyemuera.windows_input import Win32ConsoleLine, read_console_line


OBSERVATIONS = []


class NativeScript:
    """Thread-local last-error API plus an explicitly released cooked read."""

    def __init__(self, text='', success=True, error=0, *, pending=False):
        self.api = MagicMock()
        self.last_error = threading.local()
        self.text, self.success, self.error = text, success, error
        self.started, self.release = threading.Event(), threading.Event()
        if not pending:
            self.release.set()
        self.api.ReadConsoleW.side_effect = self.read
        self.api.OpenThread.return_value = 0x100000001
        self.api.CloseHandle.return_value = True
        self.api.CancelSynchronousIo.side_effect = self.cancel
        self.cancel_calls = 0
        self.backend = Win32ConsoleLine(self.api, object(), 503)

    def set_error(self, value):
        self.last_error.value = value

    def get_error(self):
        return getattr(self.last_error, 'value', 0)

    def read(self, handle, buffer, length, count, control):
        self.started.set()
        if not self.release.wait(2):
            raise AssertionError('test fixture did not release native read')
        for index, char in enumerate(self.text):
            buffer[index] = char
        count._obj.value = len(self.text)
        self.set_error(self.error)
        return self.success

    def cancel(self, handle):
        self.cancel_calls += 1
        self.release.set()
        return True

    def errors(self):
        return (
            patch.object(ctypes, 'get_last_error', self.get_error, create=True),
            patch.object(ctypes, 'set_last_error', self.set_error, create=True),
        )


class WindowsInterruptR45(unittest.TestCase):
    def observe(self, **values):
        OBSERVATIONS.append({'test_id': self.id(), **values})

    def native_result(self, script, expected):
        status = {}
        get_error, set_error = script.errors()
        with get_error, set_error:
            if isinstance(expected, type) and issubclass(expected, BaseException):
                with self.assertRaises(expected):
                    read_console_line(script.backend, status)
            else:
                self.assertEqual(read_console_line(script.backend, status), expected)
        self.assertTrue(status['reader_completed'])
        self.assertFalse(status['active'])
        self.assertNotIn(script.backend.handle, windows_input._unfinished)
        self.observe(host_input=status, signal_receipt=None)
        return status

    def pending_signal(self, *, cancel_hook=None, cancel_failure=False):
        script, status = NativeScript(pending=True), {}
        observer = CLIInterrupts()
        original_cancel = script.backend.cancel
        cancel_entered = threading.Event()

        def cancel(thread_id):
            cancel_entered.set()
            if cancel_hook is not None:
                cancel_hook(observer, script)
            if cancel_failure:
                return 5
            return original_cancel(thread_id)

        script.backend.cancel = cancel

        def deliver():
            if not script.started.wait(2):
                raise AssertionError('reader did not start')
            signal.raise_signal(signal.SIGINT)

        sender = threading.Thread(target=deliver)
        get_error, set_error = script.errors()
        with get_error, set_error, observer:
            sender.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    read_console_line(script.backend, status)
            finally:
                sender.join(2)
                self.assertFalse(sender.is_alive())
                if not cancel_failure:
                    script.release.set()
        self.assertTrue(cancel_entered.is_set())
        self.assertEqual(observer.received['signal'], 'SIGINT')
        self.observe(host_input=status, signal_receipt=observer.received)
        return script, status, observer

    def run_cli(
        self,
        run=None,
        *,
        stage=None,
        fail_write=False,
        fail_capture=False,
        close_error=None,
        use_error_report=False,
        repeated=False,
        record_inputs=False,
        capture_error=None,
        profiler_error=None,
        watcher_error=None,
        direct_write_interrupt=False,
        diagnostic_error=None,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ERB').mkdir()
            (root / 'CSV').mkdir()
            (root / 'ERB/Main.ERB').write_bytes(b'@MAIN\nRETURN\n')
            session_path, error_path = root / 'session.json', root / 'error.json'
            options = [
                str(root),
                '--entry',
                'MAIN',
                '--session-report',
                str(session_path),
            ]
            if use_error_report:
                options += ['--error-report', str(error_path)]
            replay_path = root / 'replay.json'
            if record_inputs:
                options += ['--record-inputs', str(replay_path), '--seed', '42']
            if profiler_error is not None:
                options += ['--profile-vm', str(root / 'profile.json')]
            if watcher_error is not None:
                options += ['--trace-report', str(root / 'trace.json')]
            observer = CLIInterrupts()
            out, errout = io.StringIO(), io.StringIO()
            writes = []
            captured = {}
            active_vm = []
            original_write, original_close = cli.write_report, Console.close
            original_report = RunJournal.report
            delivered = False
            write_interrupted = False

            def receive_once(target):
                nonlocal delivered
                if stage == target and not delivered:
                    delivered = True
                    observer._receive(signal.SIGINT, None)
                    if repeated:
                        observer._receive(signal.SIGINT, None)

            def write(path, obj, game, **kwargs):
                nonlocal write_interrupted
                writes.append(Path(path).name)
                # Deliver after serialization/write: a rewrite is required to
                # correct a session that initially described ordinary EOF.
                if fail_write:
                    receive_once('report_write')
                    raise OSError(5, 'neutral report write failure')
                if direct_write_interrupt and not write_interrupted:
                    write_interrupted = True
                    raise KeyboardInterrupt
                result = original_write(path, obj, game, **kwargs)
                receive_once('report_write')
                return result

            def close(console):
                receive_once('console_cleanup')
                original_close(console)
                if close_error is not None:
                    raise close_error

            class DiagnosticOutput(io.StringIO):
                def write(self, text):
                    receive_once('fatal_presentation')
                    if diagnostic_error is not None:
                        raise diagnostic_error
                    return super().write(text)

            if stage == 'fatal_presentation' or diagnostic_error is not None:
                errout = DiagnosticOutput()
            run = (lambda vm: None) if run is None else run

            def vm_run(vm, entry):
                active_vm.append(vm)
                return run(vm)

            def report(journal, outcome, error=None):
                if capture_error is not None:
                    raise capture_error
                if fail_capture:
                    raise RuntimeError('capture fixture')
                result = original_report(journal, outcome, error)
                captured['logical_output_capture'] = dict(
                    result['logical_output_capture']
                )
                captured['pending'] = list(journal.vm.console._pending)
                captured['lines'] = list(journal.vm.console.lines)
                return result

            patches = [
                patch.object(VM, 'run', vm_run),
                patch.object(cli, 'write_report', write),
                patch.object(Console, 'close', close),
                patch('sys.stdout', out),
                patch('sys.stderr', errout),
            ]
            fake_profiler, fake_watcher = MagicMock(), MagicMock()
            fake_profiler.install.return_value = fake_profiler
            fake_watcher.install.return_value = fake_watcher
            fake_profiler.stop.side_effect = profiler_error
            fake_watcher.stop.side_effect = watcher_error
            with (
                observer,
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patch.object(RunJournal, 'report', report),
                patch('pyemuera.diagnostics_c2.VMProfiler', return_value=fake_profiler),
                patch(
                    'pyemuera.diagnostics_c2.VariableTrace', return_value=fake_watcher
                ),
            ):
                code = cli.main(options, interrupts=observer)
            session = (
                json.loads(session_path.read_text()) if session_path.exists() else None
            )
            error = json.loads(error_path.read_text()) if error_path.exists() else None
            replay = (
                json.loads(replay_path.read_text()) if replay_path.exists() else None
            )
            observation = {
                'exit_code': code,
                'session': session,
                'error_report': error,
                'replay': replay,
                'report_writes': writes,
                'signal_receipt': observer.received,
                'stderr': errout.getvalue(),
                'handlers_restored': not observer.previous,
                'interrupt_support_after_owner_exit': observer.setup,
                'pre_cleanup_snapshot': captured,
                'post_cleanup_logical_output_capture': (
                    capture_summary(active_vm[0]) if active_vm else None
                ),
                'post_cleanup_pending': (
                    list(active_vm[0].console._pending) if active_vm else None
                ),
            }
            self.observe(**observation)
            return observation

    def test_successful_zero_read_with_fresh_abort_is_interrupt(self):
        status = self.native_result(NativeScript(error=995), KeyboardInterrupt)
        self.assertEqual(
            status['native_read'],
            {
                'success': True,
                'characters_read': 0,
                'last_error': 995,
                'classification': 'operation_aborted',
            },
        )
        self.assertNotIn('empty_read_signal_checkpoint_seconds', status)

    def test_failed_abort_is_interrupt(self):
        self.native_result(NativeScript(success=False, error=995), KeyboardInterrupt)

    def test_failed_access_denied_is_os_error(self):
        status = self.native_result(NativeScript(success=False, error=5), OSError)
        self.assertEqual(status['native_read']['classification'], 'read_error')

    def test_legitimate_empty_read_without_signal_remains_eof(self):
        status = self.native_result(NativeScript(), EOFError)
        self.assertEqual(status['native_read']['classification'], 'empty_read')
        self.assertEqual(status['empty_read_signal_checkpoint_seconds'], 0.05)
        self.assertFalse(status['cancellation_requested'])

    def test_stale_abort_last_error_is_cleared_before_eof(self):
        script = NativeScript()
        original_read = script.read

        def read(*args):
            self.assertEqual(script.get_error(), 0)
            return original_read(*args)

        script.api.ReadConsoleW.side_effect = read
        script.set_error(995)
        self.native_result(script, EOFError)

    def test_ctrl_z_is_eof_without_signal_checkpoint(self):
        status = self.native_result(NativeScript('\x1a\r\n'), EOFError)
        self.assertEqual(status['native_read']['classification'], 'ctrl_z')
        self.assertNotIn('empty_read_signal_checkpoint_seconds', status)

    def test_empty_enter_is_empty_string(self):
        self.native_result(NativeScript('\r\n'), '')

    def test_unicode_cooked_line_keeps_spaces_and_surrogate_pair(self):
        self.native_result(
            NativeScript(' 日本語\tＡ\ud83d\ude00 \r\n'), ' 日本語\tＡ😀 '
        )

    def test_lone_utf16_surrogate_is_preserved(self):
        self.native_result(NativeScript('\ud800\r\n'), '\ud800')

    def test_nonempty_success_does_not_treat_last_error_as_abort(self):
        self.native_result(NativeScript('ok\r\n', error=995), 'ok')

    def test_signal_before_read_starts_no_native_reader(self):
        script, observer = NativeScript(), CLIInterrupts()
        with observer, self.assertRaises(KeyboardInterrupt):
            observer._receive(signal.SIGINT, None)
            read_console_line(script.backend, {})
        script.api.ReadConsoleW.assert_not_called()
        self.observe(signal_receipt=observer.received, native_reader_started=False)

    def test_interrupted_thread_start_keeps_tombstone_until_delayed_worker_finishes(
        self,
    ):
        script, status = NativeScript(), {}
        release_start = threading.Event()
        actual_thread = threading.Thread
        created = []

        class UncertainStart:
            native_id = None
            ident = None

            def __init__(self, *, target, name, daemon):
                self.target = target
                created.append(self)

            def is_alive(self):
                # Model the unacknowledged start handshake. No completion may
                # be inferred from this false result.
                return False

            def start(self):
                def later():
                    if release_start.wait(2):
                        self.target()

                self.actual = actual_thread(target=later)
                self.actual.start()
                raise KeyboardInterrupt

        with (
            patch.object(windows_input.threading, 'Thread', UncertainStart),
            patch.object(windows_input, 'CANCEL_SECONDS', 0.02),
        ):
            with self.assertRaises(KeyboardInterrupt):
                read_console_line(script.backend, status)
            self.assertTrue(status['reader_start_uncertain'])
            self.assertTrue(status['cleanup_incomplete'])
            self.assertFalse(status['reader_completed'])
            with self.assertRaises(EraError) as exc:
                read_console_line(script.backend, {})
            self.assertEqual(exc.exception.code, 'E_CONSOLE')
            self.assertEqual(len(created), 1)
        done = windows_input._unfinished[script.backend.handle]
        release_start.set()
        self.assertTrue(done.wait(2))
        created[0].actual.join(2)
        # The read() entry guard prevents the delayed thread acquiring stdin.
        script.api.ReadConsoleW.assert_not_called()
        script.api.CancelSynchronousIo.assert_not_called()
        get_error, set_error = script.errors()
        with get_error, set_error, self.assertRaises(EOFError):
            read_console_line(script.backend, {})
        self.assertNotIn(script.backend.handle, windows_input._unfinished)
        self.observe(
            host_input=status,
            delayed_backend_reads=0,
            readers_started=1,
            event_order=[
                'start_uncertain',
                'KeyboardInterrupt',
                'second_read_rejected',
                'delayed_worker_done',
            ],
        )

    def test_definite_thread_start_runtime_error_releases_unused_handle(self):
        script, status = NativeScript(), {}
        failed = MagicMock()
        failed.ident = None
        failed.is_alive.return_value = False
        failed.start.side_effect = RuntimeError('cannot create thread')
        with patch.object(windows_input.threading, 'Thread', return_value=failed):
            with self.assertRaises(RuntimeError):
                read_console_line(script.backend, status)
        self.assertEqual(status['reader_start_failed'], 'RuntimeError')
        self.assertFalse(status['cancellation_requested'])
        self.assertNotIn('cleanup_incomplete', status)
        self.assertNotIn(script.backend.handle, windows_input._unfinished)
        script.api.ReadConsoleW.assert_not_called()
        self.observe(host_input=status, backend_reads=0)

    def test_signal_while_read_pending_cancels_and_completes(self):
        script, status, observer = self.pending_signal()
        self.assertTrue(status['reader_completed'])
        self.assertTrue(status['cancellation_requested'])
        self.assertTrue(status['cancel_attempts'][-1]['api_success'])
        self.assertTrue(status['cancel_attempts'][-1]['thread_handle_closed'])
        self.assertNotIn(script.backend.handle, windows_input._unfinished)

    def test_empty_before_signal_is_resolved_at_event_checkpoint(self):
        script, status, observer = NativeScript(), {}, CLIInterrupts()
        checkpoint_entered, signal_sent = threading.Event(), threading.Event()
        original_checkpoint = windows_input._empty_read_checkpoint

        def checkpoint(state):
            checkpoint_entered.set()
            self.assertTrue(signal_sent.wait(2))
            original_checkpoint(state)

        def deliver():
            self.assertTrue(checkpoint_entered.wait(2))
            signal.raise_signal(signal.SIGINT)
            signal_sent.set()

        sender = threading.Thread(target=deliver)
        get_error, set_error = script.errors()
        with (
            get_error,
            set_error,
            observer,
            patch.object(windows_input, '_empty_read_checkpoint', checkpoint),
        ):
            sender.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    read_console_line(script.backend, status)
            finally:
                sender.join(2)
        self.assertEqual(status['native_read']['classification'], 'empty_read')
        self.assertFalse(status['cancellation_requested'])
        self.assertTrue(status['reader_completed'])
        self.observe(
            host_input=status,
            signal_receipt=observer.received,
            event_order=['native_empty', 'checkpoint_entered', 'SIGINT'],
        )

    def test_signal_immediately_after_empty_without_fabricated_read_error(self):
        script, status, observer = NativeScript(), {}, CLIInterrupts()

        def checkpoint(state):
            observer._receive(signal.SIGINT, None)

        get_error, set_error = script.errors()
        with (
            get_error,
            set_error,
            patch.object(windows_input, '_empty_read_checkpoint', checkpoint),
        ):
            with self.assertRaises(KeyboardInterrupt):
                read_console_line(script.backend, status)
        self.assertEqual(status['native_read']['last_error'], 0)
        self.assertEqual(observer.received['signal'], 'SIGINT')
        self.observe(
            host_input=status,
            signal_receipt=observer.received,
            event_order=['native_empty', 'fake_main_thread_SIGINT'],
        )

    def partial_native_script(self):
        script = NativeScript()
        chunks = iter(('x' * 4096, ''))
        original_read = script.read

        def read(*args):
            script.text = next(chunks)
            return original_read(*args)

        script.api.ReadConsoleW.side_effect = read
        return script

    def test_partial_cooked_read_followed_by_empty_keeps_text_without_signal(self):
        status = self.native_result(self.partial_native_script(), 'x' * 4096)
        self.assertEqual(status['native_read']['classification'], 'empty_read')
        self.assertEqual(status['empty_read_signal_checkpoint_seconds'], 0.05)

    def test_partial_read_then_empty_signal_prevents_vm_input_side_effect(self):
        script, observer = self.partial_native_script(), CLIInterrupts()
        status, accepted = {}, []
        entered, sent = threading.Event(), threading.Event()

        def checkpoint(state):
            entered.set()
            self.assertTrue(sent.wait(2))

        def deliver():
            self.assertTrue(entered.wait(2))
            signal.raise_signal(signal.SIGINT)
            sent.set()

        sender = threading.Thread(target=deliver)
        get_error, set_error = script.errors()
        with (
            get_error,
            set_error,
            observer,
            patch.object(windows_input, '_empty_read_checkpoint', checkpoint),
        ):
            sender.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    accepted.append(read_console_line(script.backend, status))
            finally:
                sender.join(2)
        self.assertEqual(accepted, [])
        self.assertTrue(status['reader_completed'])
        self.assertEqual(status['native_read']['classification'], 'empty_read')
        self.observe(
            host_input=status,
            accepted_input_count=0,
            signal_receipt=observer.received,
            event_order=['full_4096_chunk', 'empty_read', 'SIGINT'],
        )

    def test_partial_empty_interrupt_leaves_vm_rng_and_accepted_input_count_unchanged(
        self,
    ):
        script = self.partial_native_script()
        accepted, states = [], {}
        get_error, set_error = script.errors()

        def checkpoint(status):
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)

        def select(stream, status):
            status.update(backend='ReadConsoleW/event', host_echo=True)
            return script.backend

        def run(vm):
            states['before_rng'] = vm.rng.getstate()
            try:
                with (
                    patch.object(Win32ConsoleLine, 'from_stream', side_effect=select),
                    patch('pyemuera.console.os.name', 'nt'),
                ):
                    accepted.append(vm.console.input(string=True))
            finally:
                states['after_rng'] = vm.rng.getstate()
                states['input_count'] = vm.console.input_count

        with (
            get_error,
            set_error,
            patch.object(windows_input, '_empty_read_checkpoint', checkpoint),
        ):
            got = self.run_cli(run)
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(accepted, [])
        self.assertEqual(states['before_rng'], states['after_rng'])
        self.assertEqual(states['input_count'], 0)
        self.assertEqual(got['session']['input_responses'], 0)
        self.assertTrue(got['session']['host_input']['reader_completed'])

    def test_repeated_signal_during_cancellation_preserves_first_receipt(self):
        repeated = threading.Event()

        def hook(observer, script):
            if not repeated.is_set():
                repeated.set()
                observer._receive(signal.SIGINT, None)

        script, status, observer = self.pending_signal(cancel_hook=hook)
        self.assertTrue(repeated.is_set())
        self.assertTrue(status['reader_completed'])
        self.assertTrue(status['cancellation_requested'])

    def test_uncancellable_reader_blocks_second_reader_until_actual_completion(self):
        with patch.object(windows_input, 'CANCEL_SECONDS', 0.02):
            script, status, observer = self.pending_signal(cancel_failure=True)
        try:
            self.assertTrue(status['cleanup_incomplete'])
            self.assertFalse(status['reader_completed'])
            with self.assertRaises(EraError) as exc:
                read_console_line(script.backend, {})
            self.assertEqual(exc.exception.code, 'E_CONSOLE')
        finally:
            script.release.set()
            done = windows_input._unfinished[script.backend.handle]
            self.assertTrue(done.wait(2))
        get_error, set_error = script.errors()
        with get_error, set_error, self.assertRaises(EOFError):
            read_console_line(script.backend, {})
        self.assertNotIn(script.backend.handle, windows_input._unfinished)

    def test_cancel_os_error_does_not_mask_first_keyboard_interrupt(self):
        def hook(observer, script):
            script.release.set()
            raise OSError(5, 'cancel fixture')

        script, status, observer = self.pending_signal(cancel_hook=hook)
        self.assertEqual(status['cancel_failure']['type'], 'OSError')
        self.assertTrue(status['reader_completed'])

    def test_cancel_api_false_records_not_found_and_closes_thread_handle(self):
        script = NativeScript()

        def cancel(handle):
            script.set_error(1168)
            return False

        script.api.CancelSynchronousIo.side_effect = cancel
        get_error, set_error = script.errors()
        with get_error, set_error:
            self.assertEqual(script.backend.cancel(123), 1168)
        self.assertFalse(script.backend.cancel_observation['api_success'])
        self.assertTrue(script.backend.cancel_observation['thread_handle_closed'])
        self.observe(cancel_observation=script.backend.cancel_observation)

    def test_cancel_open_thread_failure_keeps_api_return_unobserved(self):
        script = NativeScript()
        script.api.OpenThread.return_value = None
        get_error, set_error = script.errors()
        with get_error, set_error:
            script.set_error(5)
            self.assertEqual(script.backend.cancel(123), 5)
        self.assertFalse(script.backend.cancel_observation['open_thread'])
        self.assertIsNone(script.backend.cancel_observation['api_success'])
        script.api.CancelSynchronousIo.assert_not_called()
        script.api.CloseHandle.assert_not_called()
        self.observe(cancel_observation=script.backend.cancel_observation)

    def test_cancel_api_exception_still_closes_thread_handle(self):
        script = NativeScript()
        script.api.CancelSynchronousIo.side_effect = OSError(5, 'neutral API failure')
        with self.assertRaises(OSError):
            script.backend.cancel(123)
        self.assertIsNone(script.backend.cancel_observation['api_success'])
        self.assertTrue(script.backend.cancel_observation['thread_handle_closed'])
        self.observe(cancel_observation=script.backend.cancel_observation)

    def test_thread_handle_close_failure_is_retained_without_false_cancel_failure(self):
        script = NativeScript()
        script.api.CloseHandle.return_value = False
        self.assertEqual(script.backend.cancel(123), 0)
        self.assertTrue(script.backend.cancel_observation['api_success'])
        self.assertFalse(script.backend.cancel_observation['thread_handle_closed'])
        self.observe(cancel_observation=script.backend.cancel_observation)

    def test_ctrl_break_number_is_recorded_by_fake_windows_handler(self):
        observer = CLIInterrupts()
        with patch(
            'pyemuera.cli_interrupts.signal.Signals',
            return_value=SimpleNamespace(name='SIGBREAK'),
        ):
            with self.assertRaises(KeyboardInterrupt):
                observer._receive(21, None)
        self.assertEqual(observer.received['number'], 21)
        self.assertEqual(observer.received['signal'], 'SIGBREAK')
        self.observe(signal_receipt=observer.received, backend='fake Windows SIGBREAK')

    def test_late_first_signal_during_fatal_presentation_becomes_130(self):
        def run(vm):
            raise EraError('neutral EOF', code='E_INPUT_EOF')

        got = self.run_cli(run, stage='fatal_presentation', use_error_report=True)
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['outcome'], 'interrupted')
        self.assertEqual(got['session']['interruption']['signal'], 'SIGINT')
        self.assertIsNone(got['session']['error'])
        self.assertEqual(got['session']['superseded_input_eof']['code'], 'E_INPUT_EOF')
        self.assertIsNone(got['error_report'])

    def test_fatal_stderr_failure_does_not_mask_received_signal_exit_130(self):
        def run(vm):
            raise EraError('neutral EOF', code='E_INPUT_EOF')

        got = self.run_cli(
            run,
            stage='fatal_presentation',
            diagnostic_error=OSError(5, 'neutral stderr failure'),
        )
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['outcome'], 'interrupted')
        self.assertEqual(got['session']['interruption']['signal'], 'SIGINT')
        self.assertEqual(
            got['session']['diagnostic_presentation_failure']['type'], 'OSError'
        )
        self.assertIsNone(got['session']['error'])

    def test_closed_stderr_preserves_original_error_and_failure_exit(self):
        def run(vm):
            raise EraError('neutral script failure', code='E_SCRIPT')

        got = self.run_cli(run, diagnostic_error=ValueError('closed neutral stderr'))
        self.assertEqual(got['exit_code'], 1)
        self.assertEqual(got['session']['error']['code'], 'E_SCRIPT')
        self.assertEqual(
            got['session']['diagnostic_presentation_failure']['type'], 'ValueError'
        )
        self.assertIsNone(got['signal_receipt'])

    def test_signal_during_cleanup_is_in_final_session(self):
        got = self.run_cli(stage='console_cleanup')
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['outcome'], 'interrupted')
        self.assertEqual(
            got['session']['interrupt_support']['shutdown_signals']['last_stage'],
            'console_cleanup',
        )

    def test_signal_during_session_write_gets_one_correcting_rewrite(self):
        got = self.run_cli(stage='report_write')
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['outcome'], 'interrupted')
        self.assertEqual(got['report_writes'].count('session.json'), 2)
        self.assertEqual(got['session']['interruption']['signal'], 'SIGINT')

    def test_repeated_signal_during_reports_is_counted_without_extra_rewrite(self):
        got = self.run_cli(stage='report_write', repeated=True)
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(
            got['session']['interrupt_support']['shutdown_signals']['count'], 2
        )
        self.assertEqual(got['report_writes'].count('session.json'), 2)

    def test_late_signal_reconciles_eof_error_and_session_reports(self):
        def run(vm):
            raise EraError('neutral EOF', code='E_INPUT_EOF')

        got = self.run_cli(run, stage='report_write', use_error_report=True)
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['outcome'], 'interrupted')
        self.assertIsNone(got['session']['error'])
        self.assertIsNone(got['error_report']['error'])
        self.assertEqual(
            got['error_report']['superseded_input_eof']['code'], 'E_INPUT_EOF'
        )
        self.assertEqual(got['error_report']['interruption']['signal'], 'SIGINT')
        self.assertEqual(got['report_writes'].count('error.json'), 2)

    def test_late_signal_keeps_recorded_replay_outcome_consistent(self):
        got = self.run_cli(stage='report_write', record_inputs=True)
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['outcome'], got['replay']['outcome'])
        self.assertEqual(got['replay']['outcome'], 'interrupted')
        self.assertEqual(got['report_writes'].count('replay.json'), 2)

    def test_report_write_failure_keeps_exit_130_and_observed_receipt(self):
        got = self.run_cli(stage='report_write', fail_write=True)
        self.assertEqual(got['exit_code'], 130)
        self.assertIsNone(got['session'])
        self.assertIn('Cannot write session_report', got['stderr'])

    def test_report_capture_failure_keeps_exit_130(self):
        def run(vm):
            raise KeyboardInterrupt

        got = self.run_cli(run, fail_capture=True)
        self.assertEqual(got['exit_code'], 130)
        self.assertFalse(got['session']['capture_complete'])
        self.assertEqual(got['session']['outcome'], 'interrupted')

    def test_direct_keyboard_interrupt_during_journal_capture_reports_incomplete(self):
        got = self.run_cli(capture_error=KeyboardInterrupt())
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['outcome'], 'interrupted')
        self.assertFalse(got['session']['capture_complete'])
        self.assertEqual(
            got['session']['secondary_capture_failure']['type'], 'KeyboardInterrupt'
        )
        self.assertIsNone(got['signal_receipt'])

    def test_direct_keyboard_interrupt_during_profiler_capture_is_reported(self):
        got = self.run_cli(profiler_error=KeyboardInterrupt())
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(
            got['session']['secondary_capture_failures'],
            [{'stage': 'VMProfiler', 'type': 'KeyboardInterrupt'}],
        )
        self.assertEqual(got['session']['outcome'], 'interrupted')
        self.assertIsNone(got['signal_receipt'])

    def test_direct_keyboard_interrupt_during_trace_capture_is_reported(self):
        got = self.run_cli(watcher_error=KeyboardInterrupt())
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(
            got['session']['secondary_capture_failures'],
            [{'stage': 'VariableTrace', 'type': 'KeyboardInterrupt'}],
        )
        self.assertEqual(got['session']['outcome'], 'interrupted')

    def test_direct_keyboard_interrupt_during_error_write_is_separate_from_signal_receipt(
        self,
    ):
        def run(vm):
            raise EraError('neutral EOF', code='E_INPUT_EOF')

        got = self.run_cli(run, use_error_report=True, direct_write_interrupt=True)
        self.assertEqual(got['exit_code'], 130)
        self.assertIsNone(got['error_report'])
        self.assertIsNone(got['signal_receipt'])
        self.assertEqual(got['session']['outcome'], 'interrupted')
        self.assertEqual(
            got['session']['secondary_report_failures'],
            [{'type': 'KeyboardInterrupt', 'stage': 'error_report'}],
        )

    def assert_pending_snapshot(self, ending):
        def run(vm):
            vm.console.write('neutral pending PRINT')
            if ending is not None:
                raise ending

        got = self.run_cli(run)
        self.assertEqual(
            got['session']['logical_output_capture'],
            got['pre_cleanup_snapshot']['logical_output_capture'],
        )
        self.assertTrue(got['pre_cleanup_snapshot']['pending'])
        self.assertEqual(got['post_cleanup_pending'], [])

    def test_pending_print_normal_session_keeps_pre_cleanup_snapshot(self):
        self.assert_pending_snapshot(None)

    def test_pending_print_error_session_keeps_pre_cleanup_snapshot(self):
        self.assert_pending_snapshot(EraError('neutral error', code='E_SCRIPT'))

    def test_pending_print_eof_session_keeps_pre_cleanup_snapshot(self):
        self.assert_pending_snapshot(EraError('neutral EOF', code='E_INPUT_EOF'))

    def test_cleanup_failure_is_reported_and_does_not_change_130(self):
        def run(vm):
            raise KeyboardInterrupt

        got = self.run_cli(run, close_error=OSError(5, 'cleanup fixture'))
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['cleanup_failure']['type'], 'OSError')

    def test_cleanup_failure_turns_normal_success_into_failure(self):
        got = self.run_cli(close_error=OSError(5, 'cleanup fixture'))
        self.assertEqual(got['exit_code'], 1)
        self.assertEqual(got['session']['cleanup_failure']['stage'], 'Console.close')

    def test_normal_eof_is_never_turned_into_signal(self):
        def run(vm):
            raise EraError('neutral EOF', code='E_INPUT_EOF')

        got = self.run_cli(run, use_error_report=True)
        self.assertEqual(got['exit_code'], 1)
        self.assertEqual(got['session']['outcome'], 'input_exhausted')
        self.assertIsNone(got['session']['interruption'])
        self.assertEqual(got['error_report']['error']['code'], 'E_INPUT_EOF')

    def test_native_abort_exits_130_without_inventing_sigint_receipt(self):
        script = NativeScript(error=995)
        get_error, set_error = script.errors()

        def run(vm):
            read_console_line(script.backend, vm.console.input_backend_status)

        with get_error, set_error:
            got = self.run_cli(run)
        self.assertEqual(got['exit_code'], 130)
        self.assertIsNone(got['signal_receipt'])
        self.assertIsNone(got['session']['interruption'])
        self.assertEqual(got['session']['host_input']['native_read']['last_error'], 995)

    def test_fake_ctrl_break_cli_path_exits_130_and_records_break(self):
        def run(vm):
            handler = signal.getsignal(signal.SIGINT)
            with patch(
                'pyemuera.cli_interrupts.signal.Signals',
                return_value=SimpleNamespace(name='SIGBREAK'),
            ):
                handler(21, None)

        got = self.run_cli(run)
        self.assertEqual(got['exit_code'], 130)
        self.assertEqual(got['session']['interruption']['signal'], 'SIGBREAK')
        self.assertEqual(got['session']['interruption']['number'], 21)

    def test_native_ctrl_z_cli_path_is_input_eof_without_sigint(self):
        script = NativeScript('\x1a\r\n')
        get_error, set_error = script.errors()

        # The Console owner translates native EOF at _acquire_input_text, not
        # _read_line. Exercise that owner to preserve the E_INPUT_EOF contract.
        def acquire(vm):
            def select(stream, status):
                status.update(host_echo=True)
                return script.backend

            with (
                patch.object(Win32ConsoleLine, 'from_stream', side_effect=select),
                patch('pyemuera.console.os.name', 'nt'),
            ):
                vm.console.input(string=True)

        with get_error, set_error:
            got = self.run_cli(acquire, use_error_report=True)
        self.assertEqual(got['exit_code'], 1)
        self.assertEqual(got['session']['outcome'], 'input_exhausted')
        self.assertIsNone(got['signal_receipt'])
        self.assertEqual(
            got['session']['host_input']['native_read']['classification'], 'ctrl_z'
        )

    def test_stdout_mode_status_is_captured_after_cleanup(self):
        original_close = Console.close

        def close(console):
            original_close(console)
            console.output_mode_status = {
                'status': 'restoration_failed',
                'error_win32': 5,
            }

        with patch.object(Console, 'close', close):
            got = self.run_cli()
        self.assertEqual(
            got['session']['host_output_mode']['status'], 'restoration_failed'
        )

    def test_shutdown_observes_signal_without_changing_legacy_finishing_policy(self):
        observer = CLIInterrupts()
        observer.begin_shutdown('test report')
        observer._receive(signal.SIGINT, None)
        self.assertEqual(observer.received['signal'], 'SIGINT')
        self.assertEqual(observer.setup['shutdown_signals']['count'], 1)
        legacy = CLIInterrupts()
        legacy.finishing = True
        legacy._receive(signal.SIGINT, None)
        self.assertIsNone(legacy.received)
        self.observe(
            signal_receipt=observer.received, legacy_finishing_receipt=legacy.received
        )

    def test_entrypoint_receipt_during_handler_restore_changes_system_exit(self):
        class RestoreObserver(CLIInterrupts):
            def __exit__(self, *args):
                self.begin_shutdown('handler_restoration')
                self._receive(signal.SIGINT, None)
                return super().__exit__(*args)

        original = signal.getsignal(signal.SIGINT)
        with (
            patch('pyemuera.cli_interrupts.CLIInterrupts', RestoreObserver),
            patch.object(cli, 'main', return_value=0),
        ):
            with self.assertRaises(SystemExit) as exc:
                cli.entrypoint()
        self.assertEqual(exc.exception.code, 130)
        self.assertEqual(signal.getsignal(signal.SIGINT), original)
        self.observe(
            exit_code=exc.exception.code,
            handlers_restored=True,
            stage='handler_restoration',
        )

    def test_keyboard_interrupt_after_one_handler_restore_finishes_remaining_handlers(
        self,
    ):
        observer = CLIInterrupts()
        observer.previous = {2: 'original_int', 21: 'original_break'}
        current = {2: observer._receive, 21: observer._receive}
        calls = []

        def restore(number, handler):
            calls.append(number)
            current[number] = handler
            if number == 2:
                raise KeyboardInterrupt

        with (
            patch('pyemuera.cli_interrupts.signal.signal', side_effect=restore),
            patch(
                'pyemuera.cli_interrupts.signal.getsignal',
                side_effect=lambda number: current[number],
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            observer.__exit__(None, None, None)
        self.assertEqual(current, {2: 'original_int', 21: 'original_break'})
        self.assertEqual(calls, [2, 21])
        self.assertFalse(observer.previous)
        self.assertIsNone(observer.received)
        self.assertTrue(observer.setup['handler_restoration']['completed'])
        self.assertTrue(
            observer.setup['handler_restoration']['handlers'][0][
                'confirmed_after_interrupt'
            ]
        )
        self.observe(interrupt_support=observer.setup, signal_receipt=None)

    def test_repeated_restore_keyboard_interrupt_has_bounded_attempts_and_no_silent_ignore(
        self,
    ):
        observer = CLIInterrupts()
        observer.previous = {2: 'original_int', 21: 'original_break'}
        calls = []

        def restore(number, handler):
            calls.append(number)
            if number == 2:
                raise KeyboardInterrupt

        with (
            patch('pyemuera.cli_interrupts.signal.signal', side_effect=restore),
            patch(
                'pyemuera.cli_interrupts.signal.getsignal',
                return_value=observer._receive,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            observer.__exit__(None, None, None)
        self.assertEqual(calls.count(2), 2)
        self.assertEqual(calls.count(21), 1)
        self.assertFalse(observer.setup['handler_restoration']['completed'])
        self.assertEqual(observer.previous, {2: 'original_int'})
        self.assertFalse(observer.finishing)
        self.assertIsNone(observer.shutdown_stage)
        self.assertIsNone(observer.received)
        with self.assertRaises(KeyboardInterrupt):
            observer._receive(signal.SIGINT, None)
        self.observe(
            interrupt_support=observer.setup,
            signal_receipt=observer.received,
            api_attempts=calls,
            residual_handler='unconfirmed; not silently ignored',
        )

    def test_redirected_input_retains_original_python_eof_path(self):
        console = Console(output=io.StringIO())
        with (
            patch('pyemuera.console.os.name', 'nt'),
            patch.object(Win32ConsoleLine, 'from_stream', return_value=None),
        ):
            with (
                patch('builtins.input', side_effect=EOFError),
                self.assertRaises(EraError) as exc,
            ):
                console.input()
        self.assertEqual(exc.exception.code, 'E_INPUT_EOF')
        self.assertEqual(console.input_backend_status['backend'], 'Python input')
        self.observe(
            host_input=console.input_backend_status, error_code=exc.exception.code
        )


if __name__ == '__main__':
    unittest.main()
