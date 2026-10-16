"""Interrupt ownership for the standalone CLI, not the embedded interpreter.

An observed Python signal is evidence of delivery. An EOF or a key sent by an
external observer is not. Windows setup enables processed Ctrl+C and removes
the process's inherited Ctrl+C-ignore attribute; it cannot fix host selection
mode, focus, or a control event that never reaches this process.
"""

import os
import signal
import time


class CLIInterrupts:
    def __init__(self):
        self.received = None
        self.finishing = False
        self.previous = {}
        self.setup = {'platform': os.name, 'handlers': [], 'windows': None}
        self._restore_input = None
        self.shutdown_stage = None

    def _receive(self, number, frame):
        if self.finishing:
            return  # Let reports and terminal restoration finish after cancellation.
        if self.received is None:
            self.received = {
                'signal': signal.Signals(number).name,
                'number': number,
                'received_at_unix': time.time(),
            }
        if self.shutdown_stage is not None:
            # Keep actual delivery visible while the standalone CLI finishes
            # diagnostics/reports/restoration. Handlers remain installed and
            # are restored on context exit; this is not SIG_IGN or a global
            # policy for embedded VM callers.
            deferred = self.setup.setdefault('shutdown_signals', {})
            deferred['count'] = deferred.get('count', 0) + 1
            deferred['last_signal'] = signal.Signals(number).name
            deferred['last_stage'] = self.shutdown_stage
            return
        raise KeyboardInterrupt

    def begin_shutdown(self, stage):
        """Defer raising, but continue recording, until this CLI owner exits."""
        self.shutdown_stage = stage

    def __enter__(self):
        try:
            for name in ('SIGINT', 'SIGBREAK'):
                number = getattr(signal, name, None)
                if number is not None:
                    self.previous[number] = signal.signal(number, self._receive)
                    self.setup['handlers'].append(name)
            if os.name == 'nt':
                self._configure_windows()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _configure_windows(self):
        import ctypes
        from ctypes import wintypes

        status = self.setup['windows'] = {}
        try:
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
            api.SetConsoleCtrlHandler.restype = wintypes.BOOL
            api.GetStdHandle.argtypes = [wintypes.DWORD]
            api.GetStdHandle.restype = wintypes.HANDLE
            api.GetConsoleMode.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            api.GetConsoleMode.restype = wintypes.BOOL
            api.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            api.SetConsoleMode.restype = wintypes.BOOL
            # Windows offers no query for the inherited ignore attribute. This
            # process-local policy belongs to entrypoint(), never CLI main().
            status['ctrl_c_ignore_disabled'] = bool(
                api.SetConsoleCtrlHandler(None, False)
            )
            handle = api.GetStdHandle(0xFFFFFFF6)  # STD_INPUT_HANDLE
            mode = wintypes.DWORD()
            status['console_input'] = bool(
                api.GetConsoleMode(handle, ctypes.byref(mode))
            )
            if status['console_input']:
                status['input_mode_before'] = mode.value
                status['processed_input_enabled'] = bool(mode.value & 1)
                if not mode.value & 1:
                    status['processed_input_enabled'] = bool(
                        api.SetConsoleMode(handle, mode.value | 1)
                    )
                    if status['processed_input_enabled']:
                        self._restore_input = api, handle
                status['input_mode_changed'] = self._restore_input is not None
        except (OSError, AttributeError) as exc:
            status['setup_error'] = type(exc).__name__ + ': ' + str(exc)

    def restore_input_mode(self):
        """Release only the processed-input bit this owner enabled, once."""
        restore, self._restore_input = self._restore_input, None
        if restore is None:
            return
        import ctypes
        from ctypes import wintypes

        api, handle = restore
        status = self.setup['windows']
        try:
            current = wintypes.DWORD()
            if not api.GetConsoleMode(handle, ctypes.byref(current)):
                status['input_restore_success'] = False
                status['input_restore_error'] = ctypes.get_last_error()
                return
            target = current.value & ~1
            status['input_mode_at_restore'] = current.value
            status['input_restore_success'] = bool(api.SetConsoleMode(handle, target))
            if status['input_restore_success']:
                status['input_mode_restored'] = target
            else:
                status['input_restore_error'] = ctypes.get_last_error()
        except (OSError, AttributeError) as exc:
            status['input_restore_success'] = False
            status['input_restore_failure'] = type(exc).__name__ + ': ' + str(exc)

    def __exit__(self, *args):
        self.begin_shutdown('handler_restoration')
        restore_interrupt = None
        try:
            self.restore_input_mode()
        except KeyboardInterrupt as exc:
            restore_interrupt = exc
        finally:
            status = self.setup['handler_restoration'] = {
                'max_attempts_per_handler': 2,
                'handlers': [],
                'keyboard_interruptions': 0,
                'completed': False,
            }
            rows = {}
            # A restored caller handler can raise between restoring SIGINT and
            # SIGBREAK. Two bounded passes cover the remaining handlers without
            # an unbounded retry loop. Remove only confirmed restored numbers.
            for _ in range(2):
                try:
                    for number, handler in list(self.previous.items()):
                        row = rows.setdefault(number, {
                            'number': number, 'attempts': 0, 'restored': False,
                        })
                        if row['attempts'] >= 2:
                            continue
                        row['attempts'] += 1
                        try:
                            signal.signal(number, handler)
                        except KeyboardInterrupt as exc:
                            restore_interrupt = restore_interrupt or exc
                            status['keyboard_interruptions'] += 1
                            try:
                                restored = signal.getsignal(number) == handler
                            except (ValueError, OSError) as confirmation_error:
                                row['confirmation_failure'] = type(confirmation_error).__name__
                            else:
                                if restored:
                                    row['restored'] = True
                                    row['confirmed_after_interrupt'] = True
                                    self.previous.pop(number, None)
                        except (ValueError, OSError, TypeError) as restore_error:
                            row['failure'] = type(restore_error).__name__ + ': ' + str(restore_error)
                        else:
                            row['restored'] = True
                            self.previous.pop(number, None)
                except KeyboardInterrupt as exc:
                    # Covers the transition between individual API attempts.
                    restore_interrupt = restore_interrupt or exc
                    status['keyboard_interruptions'] += 1
                if not self.previous:
                    break
            status['handlers'] = list(rows.values())
            status['completed'] = not self.previous
            self.finishing = not self.previous
            if self.previous:
                # If an API cannot restore ownership, do not leave our handler
                # silently suppressing future interruption in an embedded user.
                self.shutdown_stage = None
        if restore_interrupt is not None:
            raise restore_interrupt
