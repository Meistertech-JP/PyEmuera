"""Interruptible Windows *cooked* line input, separate from game semantics.

ReadConsoleW remains responsible for editing, Unicode and IME composition. A
dedicated native reader avoids the Python stdin buffer lock. The main thread
blocks on an event for at most 50 ms before returning to Python signal checks.
CancelSynchronousIo targets only that reader, never a VM or a pooled thread.
"""

import ctypes
import threading
import time
from ctypes import wintypes

from .errors import EraError


CHECKPOINT_SECONDS = 0.05
CANCEL_SECONDS = 2.0
EOF_CHECKPOINT_SECONDS = CHECKPOINT_SECONDS
_unfinished = {}  # A failed host cancellation must not acquire stdin twice.


def _empty_read_checkpoint(status):
    """Give Python one bounded delivery window; never invent a signal receipt."""
    status['empty_read_signal_checkpoint_seconds'] = EOF_CHECKPOINT_SECONDS
    threading.Event().wait(EOF_CHECKPOINT_SECONDS)


class Win32ConsoleLine:
    def __init__(self, api, handle, mode):
        self.api, self.handle, self.mode = api, handle, mode
        self.read_observation = None
        self.cancel_observation = None

    @classmethod
    def from_stream(cls, stream, status):
        """Select actual console handles only; pipes and replaced stdin fall back."""
        try:
            import msvcrt

            handle = msvcrt.get_osfhandle(stream.fileno())
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            signatures = {
                'GetConsoleMode': (
                    [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)],
                    wintypes.BOOL,
                ),
                'ReadConsoleW': (
                    [
                        wintypes.HANDLE,
                        ctypes.c_void_p,
                        wintypes.DWORD,
                        ctypes.POINTER(wintypes.DWORD),
                        ctypes.c_void_p,
                    ],
                    wintypes.BOOL,
                ),
                'OpenThread': (
                    [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
                    wintypes.HANDLE,
                ),
                'CancelSynchronousIo': ([wintypes.HANDLE], wintypes.BOOL),
                'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
            }
            for name, (args, result) in signatures.items():
                function = getattr(api, name)
                function.argtypes, function.restype = args, result
            mode = wintypes.DWORD()
            if not api.GetConsoleMode(handle, ctypes.byref(mode)):
                status['fallback_reason'] = 'stdin is not a console input handle'
                return None
            status['input_mode'] = mode.value
            if not mode.value & 2:  # ENABLE_LINE_INPUT; do not change an owner's mode.
                status['fallback_reason'] = 'console is not in cooked line mode'
                return None
            status.update(
                backend='ReadConsoleW/event',
                checkpoint_seconds=CHECKPOINT_SECONDS,
                host_echo=bool(mode.value & 4),
                input_mode_changed=False,
            )
            return cls(api, handle, mode.value)
        except (OSError, ValueError, AttributeError, ImportError) as exc:
            status['fallback_reason'] = type(exc).__name__
            return None

    def read_line(self, cancelled):
        parts = []
        while not cancelled.is_set():
            buffer = ctypes.create_unicode_buffer(4096)
            count = wintypes.DWORD()
            # A console control event can complete a read successfully with no
            # characters and ERROR_OPERATION_ABORTED. Clear stale thread-local
            # last-error first; ordinary EOF must not inherit a previous 995.
            # getattr also keeps non-Windows native-adapter test doubles usable.
            getattr(ctypes, 'set_last_error', lambda value: None)(0)
            success = bool(self.api.ReadConsoleW(
                self.handle, buffer, len(buffer), ctypes.byref(count), None
            ))
            error = getattr(ctypes, 'get_last_error', lambda: 0)()
            self.read_observation = {
                'success': success,
                'characters_read': count.value,
                'last_error': error,
            }
            if error == 995 and (not success or not count.value):
                self.read_observation['classification'] = 'operation_aborted'
                raise KeyboardInterrupt
            if not success:
                self.read_observation['classification'] = 'read_error'
                raise OSError(error, 'ReadConsoleW failed')
            text = buffer[: count.value]
            if not text or (not parts and text.startswith('\x1a')):
                self.read_observation['classification'] = (
                    'empty_read' if not text else 'ctrl_z'
                )
                if parts:
                    break
                raise EOFError
            self.read_observation['classification'] = 'text'
            parts.append(text)
            if text.endswith('\n'):
                break
        if cancelled.is_set():
            raise KeyboardInterrupt
        # Windows WCHARs are UTF-16 units; combine pairs, retain lone units.
        text = (
            ''.join(parts)
            .encode('utf-16-le', 'surrogatepass')
            .decode('utf-16-le', 'surrogatepass')
        )
        if text.endswith('\n'):
            text = text[:-1]
            if text.endswith('\r'):
                text = text[:-1]
        return text

    def cancel(self, thread_id):
        handle = self.api.OpenThread(1, False, thread_id)  # THREAD_TERMINATE access
        if not handle:
            error = ctypes.get_last_error()
            self.cancel_observation = {
                'thread_id': thread_id,
                'open_thread': False,
                'api_success': None,
                'last_error': error,
            }
            return error
        self.cancel_observation = {
            'thread_id': thread_id,
            'open_thread': True,
            'api_success': None,
            'last_error': None,
        }
        try:
            success = bool(self.api.CancelSynchronousIo(handle))
            error = 0 if success else ctypes.get_last_error()
            self.cancel_observation.update(api_success=success, last_error=error)
            return error
        finally:
            self.cancel_observation['thread_handle_closed'] = bool(
                self.api.CloseHandle(handle)
            )


def read_console_line(backend, status):
    """Wait without spinning; check cancellation completion before reuse.

    A driver may reject cancellation. In that exceptional case report the
    incomplete native read, preserve KeyboardInterrupt, and prevent a second
    reader on the handle. No stdin Python buffer lock is held by the daemon.
    This failure remains a Windows acceptance failure, never success evidence.
    """
    prior = _unfinished.get(backend.handle)
    if prior is not None and not prior.is_set():
        raise EraError(
            'Previous Windows console input cancellation is incomplete.',
            code='E_CONSOLE',
        )
    done, cancelled = threading.Event(), threading.Event()
    result = {}

    def read():
        try:
            # Thread.start can be interrupted before its main-thread handshake
            # completes. A delayed worker must not acquire stdin after cancel.
            if cancelled.is_set():
                raise KeyboardInterrupt
            result['text'] = backend.read_line(cancelled)
        except BaseException as exc:
            result['error'] = exc
        finally:
            done.set()

    worker = threading.Thread(target=read, name='PyEmuera-console-line', daemon=True)
    _unfinished[backend.handle] = done
    start_completed, start_failed = False, False
    status.update(
        active=True, reader_completed=False, cancellation_requested=False,
        reader_start_completed=False,
    )
    try:
        worker.start()
        start_completed = True
        status['reader_start_completed'] = True
        while not done.wait(CHECKPOINT_SECONDS):
            pass  # Every iteration slept in an event wait; Python checks signals.
        observation = getattr(backend, 'read_observation', None)
        if observation and observation['classification'] == 'empty_read':
            # The last empty read can follow earlier full-size chunks too.
            # Give delivery the same checkpoint before returning partial text;
            # absent a signal, preserve the prior partial-EOF/EOF contract.
            _empty_read_checkpoint(status)
        if 'error' in result:
            raise result['error']
        return result['text']
    except BaseException as exc:
        cancelled.set()
        if not start_completed:
            if isinstance(exc, KeyboardInterrupt):
                status['reader_start_uncertain'] = not done.is_set()
            elif worker.ident is None and not worker.is_alive():
                # A standard fresh Thread.start RuntimeError before creation is
                # different from asynchronous interruption of its handshake.
                start_failed = True
                status['reader_start_failed'] = type(exc).__name__
        if isinstance(exc, KeyboardInterrupt):
            status['state_at_interrupt'] = 'console_line_wait'
        status['cancellation_requested'] = not done.is_set() and not start_failed
        end = time.monotonic() + CANCEL_SECONDS
        while not start_failed and not done.is_set() and time.monotonic() < end:
            try:
                if worker.native_id is None:
                    status['cancellation_waiting_for_reader_start'] = True
                    done.wait(min(CHECKPOINT_SECONDS, max(0, end - time.monotonic())))
                    continue
                # Retrying handles the tiny gap before ReadConsoleW is pending.
                error = backend.cancel(worker.native_id)
                attempt = getattr(backend, 'cancel_observation', None)
                status.setdefault('cancel_attempts', []).append(
                    dict(attempt) if attempt is not None else {
                        'thread_id': worker.native_id,
                        'api_success': None,
                        'adapter_error': error,
                        'source': 'backend.cancel; no Win32 return observation',
                    }
                )
                if error:
                    status['cancel_error'] = error
                done.wait(min(CHECKPOINT_SECONDS, max(0, end - time.monotonic())))
            except KeyboardInterrupt:
                attempt = getattr(backend, 'cancel_observation', None)
                if attempt is not None:
                    status.setdefault('cancel_attempts', []).append(
                        {**attempt, 'interrupted_before_cancel_return': True}
                    )
                continue  # Preserve the first interruption and finish cleanup.
            except OSError as cancel_error:
                status['cancel_failure'] = {
                    'type': type(cancel_error).__name__,
                    'message': str(cancel_error),
                }
                # A host cancellation error must not replace the initial
                # interruption. Wait before another bounded cancellation try.
                try:
                    done.wait(min(CHECKPOINT_SECONDS, max(0, end - time.monotonic())))
                except KeyboardInterrupt:
                    continue
        raise
    finally:
        status.update(active=False, reader_completed=done.is_set())
        observation = getattr(backend, 'read_observation', None)
        if observation is not None:
            status['native_read'] = dict(observation)
        if done.is_set() or start_failed:
            _unfinished.pop(backend.handle, None)
        else:
            status['cleanup_incomplete'] = True
