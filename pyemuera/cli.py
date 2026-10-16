from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import traceback
from . import __version__
from .audit import audit
from .console import Console
from .data import GameData
from .errors import EraError, InternalError
from .journal import RunJournal, load_replay
from .program import Program
from .runtime import VM


def resolve_game(value):
    if value:
        p = Path(value).expanduser().resolve()
        if p.is_file() and p.suffix.lower() == '.erb':
            root = p.parent.parent if p.parent.name.upper() == 'ERB' else p.parent
            return root, p
        if not p.is_dir():
            raise EraError(f'Game directory not found: {p}', code='E_PATH')
        return (p.parent if p.name.upper() == 'ERB' else p), None
    for root in (Path.cwd(), Path(sys.argv[0]).resolve().parent):
        if root.is_dir() and any(
            p.is_dir() and p.name.upper() == 'ERB' for p in root.iterdir()
        ):
            return root.resolve(), None
    raise EraError(
        'Game directory not found. Pass the folder containing ERB and CSV, or place the .pyz beside those folders.',
        code='E_NO_ERB',
    )


def report_path(path, root=None, *, overwrite=False):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != '.json':
        raise EraError('Diagnostic filenames must end in .json', code='E_PATH')
    if root and path.is_relative_to(root):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0].upper() in {'ERB', 'CSV', '.PYEMUERA'}:
            raise EraError(
                'Reports cannot be saved inside ERB, CSV or .pyemuera', code='E_PATH'
            )
    if path.exists() and not overwrite:
        raise EraError(
            'Report already exists: '
            + str(path)
            + '. Choose another name or use --overwrite-reports.',
            code='E_PATH',
        )
    return path


def write_report(path, obj, root=None, *, overwrite=False):
    path = report_path(path, root, overwrite=overwrite)
    path.parent.mkdir(parents=True, exist_ok=True)
    from .unicode_boundary import json_text

    text = json_text(obj)
    if not overwrite:
        # Exclusive creation also handles a race after report_path().
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            'w',
            encoding='utf-8',
            newline='\n',
            dir=path.parent,
            prefix='.pyemuera-report-',
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def parser():
    p = argparse.ArgumentParser(
        prog='PyEmuera',
        description='ぱみゅーら - experimental text-only Python ERB interpreter. Real-game compatibility is not certified.',
    )
    p.add_argument(
        'game', nargs='?', help='Game folder with ERB/CSV, ERB folder, or one ERB file'
    )
    p.add_argument('--version', action='version', version='PyEmuera ' + __version__)
    p.add_argument(
        '--describe',
        metavar='NAME',
        help='Print the bundled command/function/syntax/variable contract without loading a game',
    )
    p.add_argument(
        '--analysis',
        nargs='+',
        metavar='ERB_OR_FOLDER',
        help='Native-style analysis only; writes UTF-16 Analysis.log without game flow',
    )
    p.add_argument(
        '--analysis-root',
        metavar='GAME',
        help='Configuration/CSV root for --analysis (default inferred from first target)',
    )
    p.add_argument(
        '--analysis-log',
        metavar='FILE.log',
        help='Analysis transcript destination (default GAME/Analysis.log)',
    )
    p.add_argument(
        '--check',
        action='store_true',
        help='Static inventory and declaration validation; no game flow',
    )
    p.add_argument(
        '--report', metavar='FILE.json', help='Write static compatibility report'
    )
    p.add_argument(
        '--error-report',
        metavar='FILE.json',
        help='Write error details if the run fails',
    )
    p.add_argument(
        '--session-report',
        metavar='FILE.json',
        help='Record source hashes, reached functions, bounded instruction history and outcome',
    )
    p.add_argument(
        '--record-inputs',
        metavar='FILE.json',
        help='Opt in to recording actual input text for replay; review before sharing',
    )
    p.add_argument(
        '--profile-vm',
        metavar='FILE.json',
        help='Opt-in instrumented VM time/back-edge report; affects real-time speed',
    )
    p.add_argument(
        '--trace-vars',
        help='Comma-separated watched variables; requires --trace-report',
    )
    p.add_argument(
        '--trace-functions', help='Comma-separated function-entry watchpoints'
    )
    p.add_argument(
        '--trace-report',
        metavar='FILE.json',
        help='Opt-in variable values/character names; review before sharing',
    )
    p.add_argument(
        '--unbuffered-output',
        action='store_true',
        help='Disable terminal write coalescing for diagnostics',
    )
    p.add_argument(
        '--overwrite-reports',
        action='store_true',
        help='Explicitly allow replacing existing JSON reports (never ERB/CSV/save files)',
    )
    p.add_argument(
        '--save-format',
        choices=('json', 'emuera-text', 'emuera-binary'),
        help='Writable format in .pyemuera only; existing native .sav files are read automatically',
    )
    p.add_argument(
        '--native-rng',
        choices=('source', 'restore'),
        default=None,
        help='source: only ERB INITRAND/DUMPRAND synchronizes native RANDDATA; restore: automatically roundtrip it',
    )
    p.add_argument(
        '--allow-rng-reseed',
        action='store_true',
        help='Explicitly allow a fresh SFMT state when exporting a legacy Python-RNG JSON save',
    )
    p.add_argument(
        '--color',
        choices=('auto', 'always', 'never'),
        default='auto',
        help='ANSI text color/style; auto enables it only on a terminal',
    )
    p.add_argument(
        '--renderer',
        choices=('auto', 'diff', 'stream'),
        default='auto',
        help='auto: retained frame when repaint is needed; diff: force; stream: append until a global background repaint, then retain the main-screen viewport',
    )
    p.add_argument(
        '--columns',
        type=int,
        default=100,
        help='Logical text width for rule strings; default 100',
    )
    p.add_argument(
        '--layout',
        choices=('terminal', 'raw'),
        default='terminal',
        help='Project CP932 logical cells for a modern terminal (default), or emit original characters',
    )
    p.add_argument(
        '--ambiguous-width',
        type=int,
        choices=(1, 2),
        default=1,
        help='Actual terminal width of Unicode ambiguous characters, normally 1',
    )
    p.add_argument(
        '--encoding',
        default='auto',
        help='auto: Emuera BOM/CP932 contract; explicit cp932/utf-8/etc. is a strict override',
    )
    p.add_argument(
        '--entry',
        help='Run one @function first; BEGIN/LOADDATA still enter system flow',
    )
    p.add_argument(
        '--inputs', type=Path, help='UTF-8 lines or a PyEmueraInput1 JSON replay'
    )
    waits = p.add_mutually_exclusive_group()
    waits.add_argument(
        '--no-wait',
        dest='no_wait',
        action='store_const',
        const=True,
        default=None,
        help='WAIT does not consume input',
    )
    waits.add_argument(
        '--wait',
        dest='no_wait',
        action='store_const',
        const=False,
        help='WAIT consumes input (default for a new session)',
    )
    p.add_argument(
        '--seed',
        type=int,
        help='Emuera SFMT seed (low 32 bits); old Python JSON retains its old RNG stream',
    )
    p.add_argument(
        '--allow-replay-mismatch',
        action='store_true',
        help='Allow changed source/engine/settings for diagnostics; prints a warning',
    )
    p.add_argument(
        '--max-steps',
        type=int,
        default=0,
        help='Cumulative instruction limit; default 0 is unlimited, N > 0 stops at the configured limit',
    )
    p.add_argument('--max-frames', type=int, default=4096, help='ERB call-stack budget')
    p.add_argument('--debug', action='store_true', help='Enable [IF_DEBUG] blocks')
    p.add_argument(
        '--traceback',
        action='store_true',
        help='Show Python tracebacks for engine debugging',
    )
    return p


def normalize_error(exc):
    if isinstance(exc, EraError):
        return exc
    if isinstance(exc, RecursionError):
        return EraError('Python recursion limit', code='E_LIMIT')
    if isinstance(exc, (OSError, UnicodeError)):
        return EraError(f'{type(exc).__name__}: {exc}', code='E_HOST')
    return InternalError(exc)


def _mark_interrupted_reports(outputs, receipt):
    """Correct shutdown snapshots only after an actual Python signal receipt."""
    for name in ('session_report', 'record_inputs', 'error_report'):
        report = outputs.get(name)
        if report is None:
            continue
        if name != 'error_report':
            report['outcome'] = 'interrupted'
        if name != 'record_inputs':
            report['interruption'] = receipt
            if (report.get('error') or {}).get('code') == 'E_INPUT_EOF':
                report['superseded_input_eof'], report['error'] = report['error'], None


def _shutdown_report_signature(report):
    """Fields affected by the single transition from no receipt to receipt."""
    return (
        report.get('outcome'),
        (report.get('error') or {}).get('code'),
        (report.get('interruption') or {}).get('number'),
    )


def _print_host_notice(text):
    """Best-effort host notice; callers retain the failure in their reports."""
    try:
        print(text, file=sys.stderr)
    except (OSError, ValueError) as exc:
        return {'type': type(exc).__name__, 'message': str(exc)}
    return None


def main(argv=None, *, interrupts=None):
    options = parser().parse_args(argv)
    if options.describe:
        from .registry import describe

        details = describe(options.describe)
        print(json.dumps(details, ensure_ascii=False, indent=2))
        return 0 if len(details) > 2 else 2
    if options.analysis:
        from .analysis_mode import cli_analysis

        return cli_analysis(options)
    if options.analysis_root or options.analysis_log:
        parser().error('--analysis-root/--analysis-log require --analysis')
    root = None
    vm = None
    console = None
    journal = None
    err = None
    result = 1
    outcome = 'not_started'
    destinations = {}
    report_written = False
    static_report = None
    presentation_failure = None
    profiler = watcher = None
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(errors='backslashreplace')
            except (OSError, ValueError):
                pass
    try:
        if options.max_steps < 0 or not 1 <= options.max_frames <= 100000:
            raise EraError('Invalid runtime budget', code='E_ARGUMENT')
        root, single = resolve_game(options.game)
        if not any(p.is_dir() and p.name.upper() == 'CSV' for p in root.iterdir()):
            raise EraError('csvフォルダが見つかりません', code='E_NO_CSV')
        names = (
            'report',
            'error_report',
            'session_report',
            'record_inputs',
            'profile_vm',
            'trace_report',
        )
        if (options.trace_vars or options.trace_functions) and not options.trace_report:
            raise EraError(
                '--trace-vars/functions requires --trace-report', code='E_ARGUMENT'
            )
        resolved_inputs = (
            options.inputs.expanduser().resolve() if options.inputs else None
        )
        for name in names:
            raw = getattr(options, name)
            if raw:
                path = report_path(raw, root, overwrite=options.overwrite_reports)
                if path == resolved_inputs or path in destinations.values():
                    raise EraError(
                        'Input and output reports must have distinct paths.',
                        code='E_PATH',
                    )
                destinations[name] = path
        replay, metadata = (
            load_replay(resolved_inputs) if resolved_inputs else (None, None)
        )
        no_wait = bool(options.no_wait)
        seed = options.seed
        if metadata:
            if options.no_wait is None:
                no_wait = metadata['no_wait']
            if seed is None:
                seed = metadata.get('seed')
            if options.entry is None:
                options.entry = metadata.get('entry')
            if metadata.get('debug'):
                options.debug = True
        if options.record_inputs and seed is None:
            seed = secrets.randbits(64)
        if options.save_format is None:
            options.save_format = (
                metadata.get('save_format', 'json') if metadata else 'json'
            )
        if options.native_rng is None:
            options.native_rng = (
                metadata.get('native_rng', 'source') if metadata else 'source'
            )
        need_journal = options.session_report or options.record_inputs or metadata
        if need_journal:
            journal = RunJournal(seed, no_wait, bool(options.record_inputs))
        console = Console(
            replay,
            no_wait=no_wait,
            journal=journal,
            layout=options.layout,
            ambiguous_width=options.ambiguous_width,
        )
        if not 1 <= options.columns <= 10000:
            raise EraError('--columns must be 1..10000', code='E_ARGUMENT')
        console.columns = options.columns
        console.enable_color(options.color)
        if not options.unbuffered_output:
            console.enable_batching()
        if not options.check:
            from .startup import read_startup, emit_startup

            startup_settings, startup_config = read_startup(root, options.encoding)
            emit_startup(console, startup_settings, startup_config)
        program = Program(root, options.encoding, options.debug, single)
        # CLI normal flow uses native uncalled guarding; --entry retains the
        # explicit Python/CLI entry adaptation rather than inventing a root.
        program.strict_uncalled_guard = options.entry is None and not options.check
        data = GameData(root, options.encoding)
        static_report = audit(program, data)
        static_report['initialization_checked'] = False
        try:
            vm = VM(
                program,
                data,
                console,
                seed,
                options.max_steps,
                options.max_frames,
                journal=journal,
            )
            console.ui = vm.ui
            vm.saves.format = options.save_format
            vm.saves.native_rng = options.native_rng
            vm.saves.allow_rng_reseed = options.allow_rng_reseed
            static_report['initialization_checked'] = True
            static_report['csv_size_diagnostics'] = [
                d.as_dict() for d in data.size_diagnostics
            ]
            static_report['load_argument_diagnostics'] = [
                d.as_dict() for d in program.argument_diagnostics
            ]
            static_report['load_argument_coverage'] = program.argument_coverage
        except EraError as exc:
            issue = exc.as_dict()
            if not any(
                (i['code'], i['message'], i.get('file'), i.get('line'))
                == (
                    issue['code'],
                    issue['message'],
                    issue.get('file'),
                    issue.get('line'),
                )
                for i in static_report['issues']
            ):
                static_report['issues'].append(issue)
            static_report['status'] = 'known_blockers'
            if not options.check:
                err = exc
        if 'report' in destinations:
            write_report(
                destinations['report'],
                static_report,
                root,
                overwrite=options.overwrite_reports,
            )
            report_written = True
        if options.check:
            outcome = 'check_only'
            print(
                f'PyEmuera {__version__} | static scan + declarations only; gameplay NOT verified'
            )
            print(
                f'{len(static_report["files"])} files, {static_report["functions"]} functions, {static_report["instructions"]} source instructions'
            )
            print(
                f'{len(static_report["issues"])} known issue(s); {len(static_report["dynamic_calls_deferred"])} dynamic calls deferred'
            )
            for issue in static_report['issues'][:40]:
                print(
                    f'{issue["file"]}:{issue["line"]}: {issue["code"]}: {issue["message"]}'
                )
            for warning in static_report['warnings'][:10]:
                print('Warning: ' + str(warning))
            if len(static_report['issues']) > 40:
                print('Additional issues omitted from console; see --report.')
            print(static_report['scope_notice'])
            result = 2 if static_report['issues'] else 0
        else:
            if err:
                raise err
            if metadata:
                mismatches = []
                if (
                    metadata.get('native_rng', 'source') != options.native_rng
                    or bool(metadata.get('allow_rng_reseed', False))
                    != options.allow_rng_reseed
                ):
                    mismatches.append('native RNG policy')
                from .registry import fingerprint

                if metadata.get('language_specs_sha256') not in (None, fingerprint()):
                    mismatches.append('language specification fingerprint')
                if metadata['sources_sha256'] != journal.source_digest:
                    mismatches.append('game source fingerprint')
                if metadata.get('save_format', 'json') != options.save_format:
                    mismatches.append('save format')
                if metadata.get('engine_version') != __version__:
                    mismatches.append('engine version')
                if (
                    metadata.get('seed') != seed
                    or metadata['no_wait'] != no_wait
                    or metadata.get('entry') != options.entry
                ):
                    mismatches.append('replay settings')
                if mismatches and not options.allow_replay_mismatch:
                    raise EraError(
                        'Replay mismatch: '
                        + ', '.join(mismatches)
                        + '. Use --allow-replay-mismatch only for a deliberate comparison.',
                        code='E_REPLAY',
                    )
                if mismatches:
                    console.warning(
                        'replay', 'Deliberate replay mismatch: ' + ', '.join(mismatches)
                    )
            for warning in (program.warnings + data.warnings)[:10]:
                if warning not in getattr(data, 'size_warning_texts', ()):
                    console.warning(str(warning), str(warning))
            if options.record_inputs:
                console.warning(
                    'record',
                    'Input recording is enabled. The replay file contains typed text.',
                )
            from .diagnostics_c2 import VMProfiler, VariableTrace

            if options.trace_report:
                names = [
                    n.strip()
                    for n in (options.trace_vars or 'TARGET,MASTER,ASSI,PLAYER').split(
                        ','
                    )
                    if n.strip()
                ]
                functions = [
                    n.strip()
                    for n in (options.trace_functions or '').split(',')
                    if n.strip()
                ]
                watcher = VariableTrace(vm, names, functions).install()
                console.warning(
                    'trace',
                    'Variable tracing includes character names and values. Review before sharing.',
                )
            if options.profile_vm:
                profiler = VMProfiler(vm).install()
            console.configure_renderer(options.renderer)
            vm.run(options.entry)
            outcome = vm.exit_reason
            result = 0
    except KeyboardInterrupt:
        if interrupts is not None:
            interrupts.begin_shutdown('interrupt_received')
        outcome = 'interrupted'
        result = 130
    except Exception as exc:
        if interrupts is not None:
            interrupts.begin_shutdown('fatal_presentation')
        err = normalize_error(exc)
        outcome = 'input_exhausted' if err.code == 'E_INPUT_EOF' else 'error'
        try:
            from .fatal_presentation import lines

            for line in lines(err):
                print(line, file=sys.stderr)
            for frame in err.era_stack:
                print(
                    '  at @'
                    + frame.get('function', '?')
                    + ' '
                    + str(frame.get('file', ''))
                    + ':'
                    + str(frame.get('line', '')),
                    file=sys.stderr,
                )
            if options.traceback:
                if isinstance(err, InternalError):
                    for frame in err.developer_frames:
                        print(
                            '  python '
                            + frame['file']
                            + ':'
                            + str(frame['line'])
                            + ' '
                            + frame['function'],
                            file=sys.stderr,
                        )
                else:
                    traceback.print_exc()
            result = 1
        except KeyboardInterrupt:
            # Also cover embedded main() callers with no CLI signal observer.
            outcome, result = 'interrupted', 130
            presentation_failure = {'type': 'KeyboardInterrupt', 'stage': 'fatal_presentation'}
        except (OSError, ValueError) as presentation_error:
            result = 1
            presentation_failure = {
                'type': type(presentation_error).__name__,
                'message': str(presentation_error),
                'stage': 'fatal_presentation',
            }
    finally:
        if interrupts is not None:
            if interrupts.received is not None:
                outcome, result = 'interrupted', 130
            interrupts.begin_shutdown('report_capture')
        superseded_eof = None
        if outcome == 'interrupted' and err is not None and err.code == 'E_INPUT_EOF':
            superseded_eof, err = err.as_dict(), None
        outputs = {}
        capture_failures = []
        if profiler:
            try:
                profiler.stop()
                outputs['profile_vm'] = profiler.report()
            except KeyboardInterrupt:
                outcome, result = 'interrupted', 130
                capture_failures.append({'stage': 'VMProfiler', 'type': 'KeyboardInterrupt'})
        if watcher:
            try:
                watcher.stop()
                outputs['trace_report'] = watcher.report()
            except KeyboardInterrupt:
                outcome, result = 'interrupted', 130
                capture_failures.append({'stage': 'VariableTrace', 'type': 'KeyboardInterrupt'})
        if err and 'error_report' in destinations:
            outputs['error_report'] = {
                'engine_version': __version__,
                'error': err.as_dict(),
            }
        if err and 'report' in destinations and not report_written:
            outputs['report'] = static_report or {
                'format': 'PyEmuera-Compatibility-1',
                'engine_version': __version__,
                'status': 'load_failed',
                'gameplay_verified': False,
                'issues': [err.as_dict()],
            }
        if journal and 'session_report' in destinations:
            try:
                outputs['session_report'] = journal.report(outcome, err)
            except KeyboardInterrupt:
                outcome, result = 'interrupted', 130
                outputs['session_report'] = {
                    'engine_version': __version__,
                    'outcome': outcome,
                    'error': err.as_dict() if err else None,
                    'secondary_capture_failure': {
                        'type': 'KeyboardInterrupt',
                        'stage': 'RunJournal.report',
                    },
                    'capture_complete': False,
                }
            except Exception as report_error:
                outputs['session_report'] = {
                    'engine_version': __version__,
                    'outcome': outcome,
                    'error': err.as_dict() if err else None,
                    'secondary_capture_failure': {
                        'type': type(report_error).__name__,
                        'message': str(report_error),
                    },
                    'capture_complete': False,
                }
                _print_host_notice('Session collection failed: ' + type(report_error).__name__)
                if result != 130:
                    result = 1
            if interrupts is not None:
                outputs['session_report']['interrupt_support'] = interrupts.setup
                outputs['session_report']['interruption'] = (
                    interrupts.received if outcome == 'interrupted' else None
                )
            elif outcome == 'interrupted':
                outputs['session_report']['interruption'] = {
                    'signal': None,
                    'source': 'KeyboardInterrupt; no CLI signal observer',
                }
            if superseded_eof is not None:
                outputs['session_report']['superseded_input_eof'] = superseded_eof
            if capture_failures:
                outputs['session_report']['secondary_capture_failures'] = capture_failures
            if presentation_failure is not None:
                outputs['session_report']['diagnostic_presentation_failure'] = presentation_failure
            if console is not None:
                outputs['session_report']['host_input'] = console.input_backend_status
        if journal and 'record_inputs' in destinations:
            outputs['record_inputs'] = journal.replay()
            outputs['record_inputs'].update(
                {
                    'entry': options.entry,
                    'debug': options.debug,
                    'outcome': outcome,
                    'save_format': options.save_format,
                    'native_rng': options.native_rng,
                    'allow_rng_reseed': options.allow_rng_reseed,
                }
            )
        # Preserve r44's pre-cleanup logical snapshot. close(force=True) may
        # commit pending PRINT text; only host restoration evidence is merged
        # into the report after that cleanup has finished.
        if interrupts is not None:
            interrupts.begin_shutdown('console_cleanup')
        cleanup_failure = None
        if console is not None:
            try:
                console.close()
            except KeyboardInterrupt:
                outcome, result = 'interrupted', 130
                cleanup_failure = {'type': 'KeyboardInterrupt', 'stage': 'Console.close'}
            except Exception as cleanup_error:
                cleanup_failure = {
                    'type': type(cleanup_error).__name__,
                    'message': str(cleanup_error),
                    'stage': 'Console.close',
                }
                if result == 0:
                    result = 1
        if interrupts is not None:
            interrupts.restore_input_mode()
        if 'session_report' in outputs:
            if cleanup_failure is not None:
                outputs['session_report']['cleanup_failure'] = cleanup_failure
            if console is not None and hasattr(console, 'output_mode_status'):
                outputs['session_report']['host_output_mode'] = console.output_mode_status
            if outcome == 'interrupted':
                outputs['session_report']['outcome'] = outcome
        if interrupts is not None:
            interrupts.begin_shutdown('report_write')
        # Persist the session last so it observes signals delivered while other
        # reports are written. A late first delivery during its own write gets
        # one bounded rewrite, never a new game run or reader.
        ordered = [name for name in outputs if name != 'session_report']
        if 'session_report' in outputs:
            ordered.append('session_report')
        written = {}
        direct_report_interrupt = False
        for name in ordered:
            obj = outputs[name]
            if interrupts is not None and interrupts.received is not None:
                outcome, result = 'interrupted', 130
                _mark_interrupted_reports(outputs, interrupts.received)
            try:
                signature = _shutdown_report_signature(obj)
                write_report(
                    destinations[name], obj, root, overwrite=options.overwrite_reports
                )
                written[name] = signature
            except KeyboardInterrupt:
                outcome, result = 'interrupted', 130
                direct_report_interrupt = True
                _mark_interrupted_reports(
                    outputs, interrupts.received if interrupts is not None else None
                )
                if 'session_report' in outputs:
                    outputs['session_report'].setdefault('secondary_report_failures', []).append(
                        {'type': 'KeyboardInterrupt', 'stage': name}
                    )
            except (EraError, OSError) as exc:
                failure = {'type': type(exc).__name__, 'stage': name, 'message': str(exc)}
                if 'session_report' in outputs:
                    outputs['session_report'].setdefault('secondary_report_failures', []).append(failure)
                _print_host_notice('Cannot write ' + name + ': ' + str(exc))
                if result == 0:
                    result = 1
        if interrupts is not None:
            if interrupts.received is not None or direct_report_interrupt:
                outcome, result = 'interrupted', 130
                _mark_interrupted_reports(outputs, interrupts.received)
                for name, signature in written.items():
                    if signature == _shutdown_report_signature(outputs[name]):
                        continue
                    try:
                        write_report(destinations[name], outputs[name], root, overwrite=True)
                    except KeyboardInterrupt:
                        # Keep the first interruption; report persistence is
                        # incomplete, never silently counted as a successful write.
                        _print_host_notice('Cannot update ' + name + ': KeyboardInterrupt')
                    except (EraError, OSError) as exc:
                        _print_host_notice('Cannot update ' + name + ': ' + str(exc))
            interrupts.begin_shutdown('exit_notice')
    # Leaving the alternate screen restores earlier host content. Emit the
    # interruption notice afterward so cleanup cannot erase it. This is a host
    # diagnostic, not ERB output/history or a new game instruction.
    if outcome == 'interrupted':
        try:
            _print_host_notice('\nPyEmuera interrupted.')
        except KeyboardInterrupt:
            # A failed host notice must not change the cancellation exit code.
            pass
    return result


def entrypoint():
    from .cli_interrupts import CLIInterrupts

    interrupts = CLIInterrupts()
    try:
        with interrupts:
            result = main(interrupts=interrupts)
    except KeyboardInterrupt:
        result = 130
    # Include a receipt during input-mode or Python-handler restoration. After
    # this owner exits, the caller's original handlers own subsequent events.
    if interrupts.received is not None:
        result = 130
    raise SystemExit(result)


if __name__ == '__main__':
    entrypoint()
