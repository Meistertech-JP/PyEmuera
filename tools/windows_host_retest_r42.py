"""Owned classic ConsoleHost manual retest; never sends keys or captures a screen.

Run with --pyz FINAL.pyz --output NEW_DIRECTORY --mode ime (or interactive-w
--game ORIGINAL_GAME). Manually foreground the new console. Windows Terminal
pseudo/hidden console HWNDs fail closed. Engine input code is never patched.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import time
import uuid


def write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def read(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def game_manifest(root):
    """Hashes only: never copy game text/save payloads into a public report."""
    paths = set()
    for folder in ('ERB', 'CSV', '.pyemuera', 'sav'):
        directory = root/folder
        if directory.exists():
            paths.update(path for path in directory.rglob('*') if path.is_file())
    paths.update(root.glob('*.sav'))
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(paths)}


def guard(identity, observation, *, pid, nonce, alive):
    """No PID/HWND discovered outside our live child's nonce-bound identity."""
    return bool(alive and identity.get('pid') == pid and identity.get('nonce') == nonce
                and identity.get('hwnd', 0) != 0 and identity.get('host_pid', 0) != 0
                and observation.get('hwnd') == identity['hwnd']
                and observation.get('host_pid') == identity['host_pid']
                and observation.get('visible') is True
                and observation.get('foreground_hwnd') == identity['hwnd'])


def projection(session, restoration, *, exit_code, elapsed, guard_started, forced=False):
    host = session.get('host_input') or {}
    interruption = session.get('interruption') or {}
    return dict(status='OBSERVED_NOT_ACCEPTED' if guard_started and not forced else 'BLOCKED',
                evidence_type='WINDOWS_MANUAL_CONTROLLER', event_sent=None,
                event_sent_reason='No event API or key injection; physical action requires operator evidence',
                signal_received=bool(interruption.get('signal')) if session else None,
                signal=interruption or None, reader_completed=host.get('reader_completed'),
                cancel_requested=host.get('cancellation_requested'), cancel_api_result=None,
                cancel_api_result_reason='Sealed engine does not expose each CancelSynchronousIo return; completion is not API success',
                cancel_error_reported=host.get('cancel_error'), console_mode_restored=restoration.get('console_mode_restored'),
                console_mode_before=restoration.get('mode_before'), console_mode_after=restoration.get('mode_after'),
                exit_code=exit_code, elapsed_seconds=elapsed, elapsed_origin='owned child launch to observed exit',
                forced_cleanup=forced, backend=host.get('backend'),
                IME_composition='UNOBSERVED_PENDING_OPERATOR_REVIEW', exact_race_overlap='UNOBSERVED',
                physical_key_source='UNOBSERVED_PENDING_OPERATOR_REVIEW', full_windows_acceptance=False)


def window_state(hwnd):
    from ctypes import wintypes as w
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = w.HWND
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.IsWindowVisible.argtypes = [w.HWND]
    owner = w.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    return dict(hwnd=int(hwnd), host_pid=owner.value, visible=bool(user.IsWindowVisible(hwnd)),
                foreground_hwnd=int(user.GetForegroundWindow() or 0))


def child(args):
    from ctypes import wintypes as w
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.GetConsoleWindow.restype = w.HWND
    api.GetStdHandle.argtypes = [w.DWORD]
    api.GetStdHandle.restype = w.HANDLE
    api.GetConsoleMode.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    api.SetConsoleTitleW.argtypes = [w.LPCWSTR]
    handle = api.GetStdHandle(-10 & 0xffffffff)
    def mode():
        value = w.DWORD()
        return value.value if api.GetConsoleMode(handle, ctypes.byref(value)) else None
    before = mode()
    hwnd = int(api.GetConsoleWindow() or 0)
    identity = dict(pid=os.getpid(), nonce=args.nonce, mode_before=before, **window_state(hwnd))
    write(args.output/'identity.json', identity)
    api.SetConsoleTitleW('PyEmuera r42 owned manual test ' + args.nonce[:8])
    print('Manually activate THIS window. No automated keys or screenshots are used.', flush=True)
    print('IME: compose Japanese, edit with Backspace, confirm; record steps manually.', flush=True)
    print('Physical Ctrl+C / QuickEdit require separate runs and operator notes.', flush=True)
    deadline = time.monotonic() + 90
    while not (args.output/'start.json').exists():
        if time.monotonic() > deadline:
            return 2
        time.sleep(.1)
    start = read(args.output/'start.json')
    if start.get('nonce') != args.nonce or not guard(identity, window_state(hwnd), pid=os.getpid(), nonce=args.nonce, alive=True):
        return 2
    exit_code = 1
    try:
        sys.argv = [str(args.pyz), str(args.output/'game'), '--session-report', str(args.output/'session.json'),
                    '--error-report', str(args.output/'error.json'), '--record-inputs', str(args.output/'inputs-private.json')]
        try:
            write(args.output/'engine-start.json', dict(pid=os.getpid(), nonce=args.nonce,
                  pyz_sha256=sha(args.pyz)))
            runpy.run_path(str(args.pyz), run_name='__main__')
            exit_code = 0
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1 if exc.code else 0
        return exit_code
    finally:
        after = mode()
        write(args.output/'restoration.json', dict(pid=os.getpid(), nonce=args.nonce, mode_before=before,
              mode_after=after, console_mode_restored=None if before is None or after is None else before == after,
              exit_code=exit_code))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pyz', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('ime', 'interactive-w'), default='ime')
    parser.add_argument('--game', type=Path)
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--nonce', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.error('Windows hardware required; unit checks are not Windows acceptance')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    args.pyz = args.pyz.resolve(strict=True)
    args.output = args.output.resolve()
    if args.child:
        return child(args)
    pyz_before = sha(args.pyz)
    if args.mode == 'interactive-w' and args.game is None:
        parser.error('interactive-w requires --game; only a disposable copy is run')
    if args.game and (args.output == args.game.resolve() or args.game.resolve() in args.output.parents):
        parser.error('--output must be outside the original game directory')
    original_before = game_manifest(args.game.resolve(strict=True)) if args.game else None
    args.output.mkdir(parents=True, exist_ok=False)
    if args.game:
        shutil.copytree(args.game.resolve(strict=True), args.output/'game',
                        ignore=shutil.ignore_patterns('*.exe', '__pycache__', '.git'))
    else:
        (args.output/'game/ERB').mkdir(parents=True)
        (args.output/'game/CSV').mkdir()
        (args.output/'game/ERB/Main.ERB').write_text('@SYSTEM_TITLE\nPRINTL R42_IME_READY\nINPUTS\nPRINTFORML R42_ACCEPTED|%RESULTS%\nPRINTL R42_SECOND_READ\nINPUTS\nQUIT\n', encoding='utf-8-sig')
    args.nonce = uuid.uuid4().hex
    cmd = [sys.executable, str(Path(__file__).resolve()), '--child', '--nonce', args.nonce,
           '--pyz', str(args.pyz), '--output', str(args.output)]
    started = time.monotonic()
    process = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
    print('Owned child PID:', process.pid, 'Switch to its classic ConsoleHost manually.', flush=True)
    observations = []
    activated = False
    forced = False
    last = None
    try:
        while process.poll() is None and time.monotonic()-started < args.timeout:
            identity = read(args.output/'identity.json')
            current = window_state(identity.get('hwnd', 0)) if identity else {}
            valid = guard(identity, current, pid=process.pid, nonce=args.nonce, alive=True)
            if current != last:
                observations.append(dict(elapsed_seconds=time.monotonic()-started, guard_ok=valid, **current))
                write(args.output/'foreground.json', observations)
                last = current
            if valid and not activated:
                write(args.output/'start.json', dict(nonce=args.nonce, pid=process.pid))
                activated = True
            # No actuation happens on focus loss; preserve the timeline for review.
            time.sleep(.1)
    finally:
        if process.poll() is None:
            forced = True
            process.kill()  # Only the Popen handle created above; never HWND owner/PID search.
        process.wait(timeout=10)
        result = projection(read(args.output/'session.json'), read(args.output/'restoration.json'),
                            exit_code=process.returncode, elapsed=time.monotonic()-started,
                            guard_started=activated, forced=forced)
        if args.game:
            original_after = game_manifest(args.game.resolve())
            result['original_source_and_saves_unchanged'] = original_before == original_after
            write(args.output/'original-hashes.json', dict(before=original_before, after=original_after))
        engine_start = read(args.output/'engine-start.json')
        pyz_after = sha(args.pyz)
        execution_observed = engine_start.get('pid') == process.pid and engine_start.get('nonce') == args.nonce
        result.update(pid=process.pid, nonce=args.nonce, pyz_sha256=pyz_after, pyz_sha256_before=pyz_before, mode=args.mode,
                      foreground_timeline='foreground.json', capture='NONE', injected_input=False,
                      engine_start_observed=execution_observed,
                      final_pyz_executed_unchanged=execution_observed and pyz_before == engine_start.get('pyz_sha256') == pyz_after)
        write(args.output/'result.json', result)
        write(args.output/'operator-review-template.json', dict(composition=None, editing=None, confirmation=None,
              physical_ctrl=None, quickedit=None, focus_loss_notes='', expected_text='', actual_text='',
              decision='UNOBSERVED', note='Fill manually; input text alone does not prove IME composition.'))
    return 0 if activated and not forced else 2


if __name__ == '__main__':
    raise SystemExit(main())
