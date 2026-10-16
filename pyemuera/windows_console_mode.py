"""Own only the Windows stdout VT change made by this Console instance.

The handle belongs to the supplied output stream, not necessarily process
STDOUT. Input modes are owned by cli_interrupts/windows_input separately. No
CONOUT$ handle is opened, and no borrowed handle is closed here. A changed mode
is restored only while its current value still equals our applied value; a
different value is an observable ownership conflict rather than permission to
overwrite a host or another application's change.
"""

ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


class _Win32OutputAPI:
    """Small typed adapter; importing the module itself never loads kernel32."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.mode_type = wintypes.DWORD
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.GetConsoleMode.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.api.GetConsoleMode.restype = wintypes.BOOL
        self.api.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.SetConsoleMode.restype = wintypes.BOOL

    def get_mode(self, handle):
        mode = self.mode_type()
        if not self.api.GetConsoleMode(handle, self.ctypes.byref(mode)):
            raise OSError(self.ctypes.get_last_error(), 'GetConsoleMode failed')
        return mode.value

    def set_mode(self, handle, mode):
        if not self.api.SetConsoleMode(handle, mode):
            raise OSError(self.ctypes.get_last_error(), 'SetConsoleMode failed')


class WindowsOutputMode:
    """A per-Console lease with serializable failure and restoration evidence.

    API failures never write diagnostics to the possibly broken game stream.
    The caller exposes status in its session report. Restoration may be retried
    explicitly after an API failure. Restoration is idempotent; ownership loss
    forbids subsequent changes through this lease. The compare/read/set
    sequence is not an atomic Win32 operation,
    so unobservable concurrent changes to the same mode word remain outside the
    locally verified ownership guarantee.
    """

    def __init__(self, api=None, handle=None):
        self.api = api
        self.handle = handle
        self.owns_change = False
        self._enable_interrupted = False
        self.status = {
            'backend': 'win32_console_output',
            'handle': handle,
            'original_mode': None,
            'applied_mode': None,
            'current_mode': None,
            'mode_changed': False,
            'owns_change': False,
            'restore_status': 'not_required',
            'events': [],
        }

    @classmethod
    def for_output(cls, output):
        lease = cls()
        try:
            import msvcrt

            handle = msvcrt.get_osfhandle(output.fileno())
            if handle in (None, -1, 0):
                raise OSError('Output stream has no valid Windows handle')
            lease.handle = handle
            lease.status['handle'] = handle
            lease.api = _Win32OutputAPI()
        except (ImportError, OSError, ValueError, AttributeError) as exc:
            lease._failure('output_handle', exc)
        return lease

    def _failure(self, operation, exc):
        self.status['events'].append(
            {
                'operation': operation,
                'status': 'failed',
                'exception': type(exc).__name__,
                'message': str(exc),
                'error_win32': getattr(exc, 'winerror', None)
                or getattr(exc, 'errno', None),
            }
        )

    def enable(self):
        """Enable VT, retaining the original mode only for a successful change."""
        if self.api is None or self.handle is None:
            return False
        if self.status['restore_status'] == 'ownership_lost':
            return False
        if self._enable_interrupted:
            # Resolve the recorded attempt through restore(), rather than
            # replacing its original mode with the possibly applied one.
            return False
        phase = 'query'
        try:
            current = self.api.get_mode(self.handle)
            self.status['current_mode'] = current
            if self.owns_change:
                if current == self.status['applied_mode']:
                    return True
                self._ownership_lost(current, operation='enable')
                return False
            original = current
            applied = original | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            self.status['original_mode'] = original
            self.status['applied_mode'] = applied
            if original == applied:
                self.status['restore_status'] = 'not_required'
                self.status['events'].append(
                    {'operation': 'enable', 'status': 'already_enabled', 'mode': current}
                )
                return True
            phase = 'set'
            self.api.set_mode(self.handle, applied)
            self.owns_change = True
            self.status.update(
                mode_changed=True,
                owns_change=True,
                current_mode=applied,
                restore_status='pending',
            )
            self.status['events'].append(
                {'operation': 'enable', 'status': 'changed', 'mode': applied}
            )
            return True
        except KeyboardInterrupt:
            # The Win32 call may have returned before Python delivers a signal.
            # Keep the attempted original/applied pair without claiming Set
            # succeeded; close must re-query before making any restoration.
            if phase == 'set':
                self._enable_interrupted = True
                self.status['mode_changed'] = None
                self.status['restore_status'] = 'pending_confirmation'
            self.status['events'].append(
                {'operation': 'enable', 'phase': phase, 'status': 'interrupted'}
            )
            raise
        except (OSError, ValueError, AttributeError) as exc:
            self._failure('enable', exc)
            return False

    def _ownership_lost(self, current, *, operation='restore'):
        self.owns_change = False
        self._enable_interrupted = False
        self.status.update(
            owns_change=False,
            current_mode=current,
            restore_status='ownership_lost',
        )
        self.status['events'].append(
            {'operation': operation, 'status': 'ownership_lost', 'mode': current}
        )

    def restore(self):
        """Restore our exact original mode after style/cursor cleanup finishes."""
        if not self.owns_change and not self._enable_interrupted:
            return
        phase = 'query'
        try:
            current = self.api.get_mode(self.handle)
            self.status['current_mode'] = current
            if current != self.status['applied_mode']:
                if self._enable_interrupted and current == self.status['original_mode']:
                    self._enable_interrupted = False
                    self.status['restore_status'] = 'unconfirmed_change'
                    self.status['events'].append(
                        {'operation': 'restore', 'status': 'unconfirmed_change', 'mode': current}
                    )
                    return
                self._ownership_lost(current)
                return
            original = self.status['original_mode']
            phase = 'set'
            self.api.set_mode(self.handle, original)
            self.owns_change = False
            self._enable_interrupted = False
            self.status.update(
                owns_change=False,
                current_mode=original,
                restore_status='restored',
            )
            self.status['events'].append(
                {'operation': 'restore', 'status': 'restored', 'mode': original}
            )
        except KeyboardInterrupt:
            self.status['restore_status'] = 'interrupted'
            self.status['events'].append(
                {'operation': 'restore', 'phase': phase, 'status': 'interrupted'}
            )
            raise
        except (OSError, ValueError, AttributeError) as exc:
            self.status['restore_status'] = 'failed'
            self._failure('restore', exc)
