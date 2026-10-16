"""Explicit platform adapter, not simulated global keyboard state.

Windows classic console: foreground check/GetKeyState/client pixels. A hidden
ConPTY window, redirected streams or POSIX has no compatible GUI key state and
raises E_PLATFORM. Single-key INPUT uses its separate terminal reader everywhere.
No hooks, background polling, event collection, or recording of inactive keys.
"""

import os
from .expr import integer, evaluate
from .errors import EraError


def unavailable(what):
    return EraError(
        what
        + ' requires a visible classic Windows console; no invented host state is returned',
        code='E_PLATFORM',
    )


class WindowsHost:
    def __init__(self, console):
        if os.name != 'nt' or not console.is_terminal():
            raise unavailable('Window/key API')
        import ctypes
        from ctypes import wintypes

        self.c = ctypes
        self.w = wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel.GetConsoleWindow.restype = wintypes.HWND
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsWindowVisible.restype = wintypes.BOOL
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetKeyState.argtypes = [ctypes.c_int]
        self.user.GetKeyState.restype = ctypes.c_short
        self.user.GetClientRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        self.user.GetClientRect.restype = wintypes.BOOL
        self.hwnd = self.kernel.GetConsoleWindow()
        if not self.hwnd or not self.user.IsWindowVisible(self.hwnd):
            raise unavailable('ConPTY/hidden console window')

    def active(self):
        return self.user.GetForegroundWindow() == self.hwnd

    def key_state(self, key):
        return int(self.user.GetKeyState(key))

    def client_size(self):
        rect = self.w.RECT()
        if not self.user.GetClientRect(self.hwnd, self.c.byref(rect)):
            raise unavailable('GetClientRect')
        return rect.right - rect.left, rect.bottom - rect.top

    def clear_input(self):
        # The line reader has no persistent edit box. Clear pending terminal
        # input events, not display history or unrelated process input.
        self.kernel.GetStdHandle.argtypes = [self.w.DWORD]
        self.kernel.GetStdHandle.restype = self.w.HANDLE
        self.kernel.FlushConsoleInputBuffer.argtypes = [self.w.HANDLE]
        self.kernel.FlushConsoleInputBuffer.restype = self.w.BOOL
        if not self.kernel.FlushConsoleInputBuffer(self.kernel.GetStdHandle(-10)):
            raise unavailable('FlushConsoleInputBuffer')


def host(vm):
    if not hasattr(vm, 'host_adapter'):
        vm.host_adapter = WindowsHost(vm.console)
    return vm.host_adapter


def function(vm, name, nodes):
    h = host(vm)
    if name == 'ISACTIVE':
        return int(h.active())
    if name in ('CLIENTWIDTH', 'CLIENTHEIGHT'):
        return integer(h.client_size()[0 if name == 'CLIENTWIDTH' else 1])
    # Reference checks focus before evaluating the key argument.
    if not h.active():
        return 0
    key = integer(evaluate(nodes[0], vm))
    if not 0 <= key <= 255:
        return 0
    value = h.key_state(key)
    previous = getattr(vm, 'key_toggles', {}).get(key, 0)
    if not hasattr(vm, 'key_toggles'):
        vm.key_toggles = {}
    current = (value & 1) + 1
    vm.key_toggles[key] = current
    return int(value < 0 and (name == 'GETKEY' or previous != current))


def execute(vm, spec, arg):
    name = spec['name']
    if name == 'PRINT_SPACE':
        if vm.console.skip_print:
            return True
        args = vm.args(arg)
        if len(args) != 1:
            raise EraError('PRINT_SPACE requires one integer', code='E_ARGUMENT')
        n = integer(args[0])
        if n < 0:
            raise EraError(
                'PRINT_SPACEの第1引数に負の値(' + str(n) + ')が指定されました',
                code='E_ARGUMENT',
            )
        if n > 0x7FFFFFFF:
            raise EraError(
                'PRINT_SPACE argument outside Int32 range', code='E_ARGUMENT'
            )
        if n > 50000000:
            raise EraError('PRINT_SPACE cell budget', code='E_LIMIT')
        con = vm.console
        # One em (100 units) is two legacy cells. Fractional spaces are carried
        # along a logical row; no font-size-dependent pixels are fabricated.
        prior = getattr(con, 'shape_remainder', (None, 0))
        remainder = prior[1] if prior[0] == con.line_count else 0
        cells, remainder = divmod(n + remainder, 50)
        con.shape_remainder = (con.line_count, remainder)
        con.warning(
            'print-space-cells',
            'PRINT_SPACE is quantized to logical cells (100 units = 2 cells); pixel positioning/shape HTML is not reproduced.',
        )
        con.display_elements.append(
            {
                'kind': 'space',
                'param': [n],
                'line': con.line_count,
                'cell_projection': cells,
                'pixel_rendered': False,
            }
        )
        con.write(' ' * cells, log_text="<shape type='space' param='" + str(n) + "'>")
        return True
    if name == 'CLEARTEXTBOX':
        if arg.strip():
            raise EraError('CLEARTEXTBOX takes no arguments', code='E_ARGUMENT')
        vm.console.input_buffer = ''
        if hasattr(vm, 'host_adapter'):
            vm.host_adapter.clear_input()
        elif os.name == 'nt' and vm.console.is_terminal():
            host(vm).clear_input()
        elif vm.console.is_terminal():
            import termios, sys

            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        vm.console.warning(
            'clear-textbox-terminal',
            'CLEARTEXTBOX clears pending terminal input; there is no retained GUI edit box.',
        )
        return True
    return False


def source_unimplemented(vm, spec, arg):
    raise EraError(
        spec['name']
        + ' is NotImplCodeEE in the supplied src1824; no fake success implementation',
        code='E_SOURCE_UNIMPLEMENTED',
    )
