"""Native-style analysis loading and Analysis.log projection, never game flow.

The log is a UTF-16LE BOM/CRLF transcript. Native Process.beginTitle writes it
before its GUI 'press Enter' prompt; the CLI likewise needs no input to finish.
"""

from dataclasses import dataclass
from pathlib import Path

from .errors import EraError
from .program import Program
from .data import GameData
from .text import display_width, load_config
from .startup import _flag


@dataclass
class AnalysisResult:
    program: Program
    data: GameData
    vm: object
    lines: list[str]
    report: dict
    log_path: Path


def resolve_root(targets, root=None):
    if root is not None:
        candidate = Path(root).expanduser().resolve()
    else:
        first = Path(targets[0]).expanduser().resolve()
        candidate = first.parent if first.is_file() else first
        for ancestor in [candidate, *candidate.parents]:
            if ancestor.name.upper() == 'ERB':
                candidate = ancestor.parent
                break
            if ancestor.is_dir() and any(
                p.is_dir() and p.name.upper() == 'CSV' for p in ancestor.iterdir()
            ):
                candidate = ancestor
                break
    if not candidate.is_dir():
        raise EraError('Game directory not found: ' + str(candidate), code='E_PATH')
    if not any(p.is_dir() and p.name.upper() == 'CSV' for p in candidate.iterdir()):
        raise EraError('csvフォルダが見つかりません', code='E_NO_CSV')
    return candidate


def directory_files(path, config, suffix, prefix=''):
    """Config.GetFiles: subdirectories first, optional ordinal-insensitive sort."""
    entries = list(path.iterdir())
    if _flag(config, '読み込み順をファイル名順にソートする', False):
        entries.sort(key=lambda p: p.name.upper())
    if _flag(config, 'サブディレクトリを検索する', False):
        for entry in entries:
            if entry.is_dir() and not entry.is_symlink():
                yield from directory_files(entry, config, suffix, prefix)
    yield from (
        entry.resolve()
        for entry in entries
        if entry.is_file()
        and entry.suffix.lower() == suffix
        and entry.name.upper().startswith(prefix)
    )


def enumerate_targets(targets, config):
    """Keep explicit argument order and duplicate inputs, as native Program.cs."""
    paths = []
    for value in targets:
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            paths.extend(directory_files(path, config, '.erb'))
        elif path.is_file() and path.suffix.lower() == '.erb':
            paths.append(path)
        elif path.exists():
            raise EraError('ドロップ可能なファイルはERBファイルのみです', code='E_PATH')
        else:
            raise EraError(
                '与えられたファイル・フォルダは存在しません: ' + str(path),
                code='E_PATH',
            )
    if not paths:
        raise EraError('No .ERB files found', code='E_NO_ERB')
    return paths


_NAME_CSV_ORDER = """ABL EXP TALENT PALAM TRAIN MARK ITEM BASE SOURCE EX STR EQUIP
TEQUIP FLAG TFLAG CFLAG TCVAR CSTR STAIN CDFLAG1 CDFLAG2 STRNAME TSTR SAVESTR GLOBAL
GLOBALS""".split()

# IdentifierDictionary.IsEventLabelName is an exact list, not an EVENT prefix.
_EVENT_LABELS = frozenset(
    'EVENTFIRST EVENTTRAIN EVENTSHOP EVENTBUY EVENTCOM '
    'EVENTTURNEND EVENTCOMEND EVENTEND EVENTLOAD'.split()
)


def _data_progress(root, program, data):
    csv = next(p for p in root.iterdir() if p.is_dir() and p.name.upper() == 'CSV')
    present = {p.name.upper(): p for p in csv.iterdir() if p.is_file()}
    report = _flag(program.config, 'ロード時にレポートを表示する', False)
    if report and 'VARIABLESIZE.CSV' in present:
        yield 'VariableSize.CSV読み込み中・・・'
    for diagnostic in data.size_diagnostics:
        yield (
            f'警告Lv{diagnostic.severity}:{Path(diagnostic.location.path).name}:'
            f'{diagnostic.location.line}行目:{diagnostic.reference_message}'
        )
        if diagnostic.source_text:
            yield diagnostic.source_text
    # Name CSV readers always display progress in AnalysisMode, even report NO.
    for name in _NAME_CSV_ORDER:
        if name + '.CSV' in present:
            yield name + '.CSV読み込み中・・・'
    if report:
        for path in directory_files(csv, program.config, '.csv', 'CHARA'):
            yield str(path.relative_to(csv)) + '読み込み中・・・'
        erb = next(
            (p for p in root.iterdir() if p.is_dir() and p.name.upper() == 'ERB'), None
        )
        if erb:
            for path in directory_files(erb, program.config, '.erh'):
                yield str(path.relative_to(erb)) + '読み込み中・・・'


def _called_count(program):
    from .load_reachability import _system_roots, method_roots, _function_references
    from importlib.resources import files
    import json

    policy = json.loads(
        files('pyemuera')
        .joinpath('specs/load_roots_v24.json')
        .read_text(encoding='utf-8')
    )
    ordered = sorted(
        (f for group in program.functions.values() for f in group), key=lambda f: f.uid
    )
    methods = method_roots(program)
    method_uids = {f.uid for f in methods}
    pending = [*_system_roots(ordered, policy), *methods]
    seen = set()
    while pending:
        function = pending.pop(0)
        if function.uid in seen:
            continue
        seen.add(function.uid)
        names, _ = _function_references(program, function, method_uids)
        pending.extend(child for name in names for child in program.functions[name])
    return len(seen)


def _warning(diagnostic, root):
    location = diagnostic.location
    path = Path(location.path)
    filename = str(path if path.is_absolute() else root / path)
    return f'警告Lv{diagnostic.severity}:{filename}:{location.line}行目:{diagnostic.reference_message}'


def _loading_lines(program, paths):
    """Project PRINTC buffering, including loadErbs' final forced NewLine.

    A full column group has already flushed, leaving the buffer empty. Native
    PrintFlush(true) then creates exactly one ASCII space. A partial last group
    is flushed as its function row instead, regardless of later warnings.
    """
    width = max(0, int(program.config.get('PRINTCの文字数', '25')))
    columns = int(program.config.get('PRINTCを並べる数', '3'))
    seen = set()
    row = ''
    for path, functions in zip(paths, program.function_file_batches):
        yield str(path) + '読み込み中・・・'
        yield '　'
        row = ''
        count = 0
        for function in functions:
            name = '@' + function.name
            row += name + ' ' * max(0, width + 1 - display_width(name))
            # ErbLoader resets funcCount for normal-function overloads before
            # incrementing it. This also changes the PRINTC flush boundary.
            if function.name in seen and function.name not in _EVENT_LABELS:
                count = -1
            seen.add(function.name)
            count += 1
            if columns > 0 and count % columns == 0:
                yield row
                yield '　'
                row = ''
        if row:
            yield row
    if not row:
        yield ' '


from .constant_ast import LOAD_CONSTANT_METHODS as _CONSTANT_METHODS


def _analysis_vm_class():
    from .runtime import VM
    from .errors import Unsupported
    from .function_resolution import expression_user_method

    class AnalysisVM(VM):
        def _private_declaration(self, line):
            # ParseSharpLine catches a failed ERB #DIM/#DIMS, queues Lv2, and
            # keeps reading. Create() failed before AddPrivateVariable(), so
            # there is no default variable to register. ERH failures retain
            # their separate fatal initialization contract.
            try:
                return super()._private_declaration(line)
            except EraError as error:
                from .load_registration import register

                register(self.program, line, error)
                return None

        def eval_node(self, node):
            if self.initializing_declarations:
                self._constant_declaration(node)
            return super().eval_node(node)

        def _constant_declaration(self, node):
            kind = node[0]
            if kind == 'lit':
                return
            if kind == 'var':
                name, indices = node[1:]
                for index in indices:
                    self._constant_declaration(index)
                if name in {'__INT_MAX__', '__INT_MIN__'}:
                    return
                variable = self.active_init.get(name) or self.data.variables.get(name)
                if variable is not None and variable.readonly:
                    return
                raise EraError(
                    '配列の初期値には定数のみ指定できます', code='E_DECLARATION'
                )
            if kind == 'call':
                name, args = node[1:]
                if name == 'RAND' or expression_user_method(
                    self.program.functions, name
                ):
                    raise EraError(
                        '配列の初期値には定数のみ指定できます', code='E_DECLARATION'
                    )
                if name not in _CONSTANT_METHODS:
                    raise EraError(
                        '配列の初期値には定数のみ指定できます', code='E_DECLARATION'
                    )
                for i, child in enumerate(args):
                    if child[0] == 'missing':
                        continue
                    if name == 'GETNUM' and i == 0 and child[0] == 'var':
                        # Getnum.UniqueRestructure only reduces its keyword;
                        # the first descriptor contributes its immutable CSV code.
                        continue
                    self._constant_declaration(child)
                if name == 'STRFORM' and args:
                    from .expr import parse
                    from .formatting import form_expression_sources

                    text = super().eval_node(args[0])
                    for expression, _ in form_expression_sources(text):
                        self._constant_declaration(parse(expression))
                return
            if kind in {'unary', 'binary', 'ternary'}:
                children = node[2:] if kind != 'ternary' else node[1:]
                for child in children:
                    self._constant_declaration(child)
                return
            if kind == 'form':
                from .expr import parse
                from .formatting import form_expression_sources

                for expression, _ in form_expression_sources(node[1]):
                    self._constant_declaration(parse(expression))
                return
            raise EraError('配列の初期値には定数のみ指定できます', code='E_DECLARATION')

    return AnalysisVM


def analyze(targets, *, root=None, encoding='auto', debug=False, output=None):
    root = resolve_root(targets, root)
    config = load_config(root, encoding, analysis_mode=True)
    paths = enumerate_targets(targets, config)
    # _Replace.csv is explicitly bypassed; no key macro or normal startup flow.
    data = GameData(root, encoding, analysis_mode=True)
    program = Program(root, encoding, debug, analysis_mode=True, analysis_files=paths)
    from .runtime import VM
    from .console import Console
    import io

    console = Console(output=io.StringIO())
    vm = _analysis_vm_class()(program, data, console, seed=0)
    from .call_diagnostics import project_missing_calls

    threshold = int(program.config.get('表示する最低警告レベル', '1'))
    warnings, summaries, projection = project_missing_calls(program, threshold)
    expression_missing = program.analysis_expression_missing
    if expression_missing:
        if not projection['analysis_missing_names']:
            summaries = [
                '・定義が見つからなかった関数: 他のファイルで定義されている場合はこの警告は無視できます'
            ]
        summaries += ['　○文中関数:']
        summaries += [
            f'　　{name}: {count}回' for name, count in expression_missing.items()
        ]
    lines = []
    if _flag(program.config, '_Rename.csvを利用する', False):
        csv = next(p for p in root.iterdir() if p.is_dir() and p.name.upper() == 'CSV')
        rename = next(
            (p for p in csv.iterdir() if p.name.upper() == '_RENAME.CSV'), None
        )
        lines.append(
            '_Rename.csv読み込み中・・・'
            if rename
            else 'csv\\_Rename.csvが見つかりません'
        )
    if not _flag(program.config, 'ロード時にレポートを表示する', False):
        lines.append(data.settings.load_label)
    lines.extend(_data_progress(root, program, data))
    lines.extend(_loading_lines(program, paths))
    file_order = {str(path): i for i, path in enumerate(paths)}
    early = sorted(
        [*program.lexical_diagnostics, *program.definition_diagnostics],
        key=lambda d: (file_order.get(d.location.path, -1), d.location.line),
    )
    lines.extend(_warning(d, root) for d in early)
    for error in program.load_errors:
        location = error.location
        position = f'{location.path}:{location.line}行目:' if location else ''
        lines.append('警告Lv2:' + position + error.as_dict()['diagnostic_message'])
    if any(
        row.get('status') == 'call_terms_checked_dynamic_target'
        for row in program.argument_coverage
    ):
        lines.append(
            'CALLFORM系命令が使われたため、呼び出されない関数のチェックは行われません。'
        )
    lines.extend(summaries)
    lines.extend(_warning(d, root) for d in warnings)
    if _flag(program.config, 'ロード時にレポートを表示する', False):
        function_count = sum(len(group) for group in program.functions.values())
        lines.append(
            f'非コメント行数:{program.enabled_line_count}, 全関数合計:{function_count}, 被呼出関数合計:{_called_count(program)}'
        )
    from .name_diagnostics import overload_notice_lines

    lines.extend(overload_notice_lines(program))
    lines.append('ファイル解析終了：Analysis.logに出力します')
    destination = (
        Path(output).expanduser().resolve() if output else root / 'Analysis.log'
    )
    if destination.suffix.lower() != '.log':
        raise EraError('Analysis output must end in .log', code='E_PATH')
    if destination in paths:
        raise EraError('Analysis output cannot overwrite a source file', code='E_PATH')
    # ConfigData overrides an explicitly supplied MaxLog to 10000 in analysis;
    # absent MaxLog retains the source default of 5000. Console retains newest.
    max_log = int(program.config.get('履歴ログの行数', '5000'))
    lines = lines[-max(500, max_log) :]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16le')
    )
    functions = sorted(
        (f for group in program.functions.values() for f in group), key=lambda f: f.uid
    )
    report = {
        'format': 'PyEmuera-Analysis-1',
        'analysis_complete': True,
        'game_flow_executed': False,
        'vm_steps': vm.steps,
        'files': [str(p) for p in paths],
        'functions': [
            {'name': f.name, 'file': f.location.path, 'line': f.location.line}
            for f in functions
        ],
        'uncalled_functions': [d.as_dict() for d in program.uncalled_diagnostics],
        'undefined_calls': projection['analysis_missing_names'],
        'undefined_expression_calls': dict(expression_missing),
        'undefined_callf': [
            d.as_dict()
            for d in program.argument_diagnostics
            if d.phase == 'callf-resolution'
        ],
        'diagnostics': [
            d.as_dict() for d in [*data.size_diagnostics, *early, *warnings]
        ],
        'load_errors': [e.as_dict() for e in program.load_errors],
        'coverage': program.argument_coverage,
        'enabled_line_count': program.enabled_line_count,
        'called_function_count': _called_count(program),
        'history_limit': max_log,
        'log': str(destination),
        'encoding': 'UTF-16LE-BOM',
        'newline': 'CRLF',
        'native_windows_acceptance': 'pending',
    }
    return AnalysisResult(program, data, vm, lines, report, destination)


def cli_analysis(options):
    """Separate CLI branch; --check retains its existing partial audit contract."""
    import sys
    from .cli import write_report, normalize_error

    try:
        if options.game or options.check or options.entry or options.inputs:
            raise EraError(
                '--analysis cannot be combined with game, --check, --entry or --inputs',
                code='E_ARGUMENT',
            )
        if any(
            (
                options.session_report,
                options.record_inputs,
                options.profile_vm,
                options.trace_report,
            )
        ):
            raise EraError(
                '--analysis supports --report and --error-report; gameplay recording options are not applicable',
                code='E_ARGUMENT',
            )
        result = analyze(
            options.analysis,
            root=options.analysis_root,
            encoding=options.encoding,
            debug=options.debug,
            output=options.analysis_log,
        )
        if options.report:
            write_report(
                options.report,
                result.report,
                result.program.root,
                overwrite=options.overwrite_reports,
            )
        print('\n'.join(result.lines))
        return 0
    except Exception as exc:
        error = normalize_error(exc)
        print(str(error), file=sys.stderr)
        if options.error_report:
            write_report(
                options.error_report,
                {'error': error.as_dict()},
                overwrite=options.overwrite_reports,
            )
        return 1
