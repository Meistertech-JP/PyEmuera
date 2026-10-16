"""ERH/ERB preprocessing, function loading, and structured-control compilation."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
from functools import lru_cache
from .errors import EraError, Location, Unsupported
from .text import read_text, strip_comment, split_args, find_assignment, load_config
from .source_lines import source_lines
from .expr import IDENT
from .registry import command_spec, SYNTAX_SPECS


@dataclass
class SourceLine:
    text: str
    location: Location


@dataclass
class Instruction:
    op: str
    arg: str
    location: Location
    jump: int = -1
    data: object = None
    evidence_id: int = -1
    argument_plan: tuple = ()
    argument_error: EraError | None = None


@dataclass
class Function:
    name: str
    parameters: list[str]
    location: Location
    attributes: set[str] = field(default_factory=set)
    declarations: list[SourceLine] = field(default_factory=list)
    lines: list[SourceLine] = field(default_factory=list)
    code: list[Instruction] = field(default_factory=list)
    labels: dict[str, int] = field(default_factory=dict)
    local_size: str = ''
    locals_size: str = ''
    uid: int = 0
    entry_error: EraError | None = None


@lru_cache(maxsize=65536)
def command(text: str) -> tuple[str, str]:
    # Emuera consumes exactly one separator character after an instruction name.
    # Any following spaces are part of raw-string arguments.  This matters for
    # constructs such as `PRINT 　`: the ASCII space separates PRINT from its
    # argument, while the following U+3000 ideographic space must be printed.
    m = re.match(r'([^\s]+)', text)
    if not m:
        return '', ''
    first = m.group(1)
    pos = m.end()
    if pos < len(text):
        if text[pos] not in ' \t\u3000':
            return '', ''
        rest = text[pos + 1 :]
    else:
        rest = ''
    # Raw-text command arguments may begin/end with assignment operators.
    if first.upper() in {
        'CUSTOMDRAWLINE',
        'DRAWLINEFORM',
        'REUSELASTLINE',
        'PUTFORM',
        'THROW',
        'DATA',
        'DATAFORM',
    } or (command_spec(first.upper()) or {}).get('family') in ('print', 'text_length'):
        return first.upper(), rest
    if command_spec(first.upper()) is not None or first.upper() in SYNTAX_SPECS:
        return first.upper(), rest
    # Prefix increment/decrement is a complete assignment statement in src1824.
    if text.startswith(('++', '--')):
        from .expr import parse

        node = parse(text)
        if node[0] == 'inc' and not node[3]:
            return '_ASSIGN', text
    # When no space separates a variable and '=', inspect its leading identifier.
    lead = IDENT.match(text)
    if lead:
        after = text[lead.end() :].lstrip()
        if (
            after.startswith(
                (
                    ':',
                    '=',
                    "'=",
                    '+=',
                    '-=',
                    '*=',
                    '/=',
                    '%=',
                    '&=',
                    '|=',
                    '^=',
                    '<<=',
                    '>>=',
                )
            )
            and find_assignment(text, legacy=True) is not None
        ):
            return '_ASSIGN', text
    if text.rstrip().endswith(('++', '--')):
        lhs = text.rstrip()[:-2].strip()
        try:
            from .expr import parse

            if parse(lhs)[0] == 'var':
                return '_ASSIGN', text
        except EraError:
            pass
    return first.upper(), rest


def parse_signature(text: str):
    # ParseLabelLine removes one @, then LexicalAnalyzer skips ERB whitespace.
    text = text.strip(' \t\u3000')
    if text.startswith('@'):
        text = text[1:].lstrip(' \t\u3000')
    m = re.match(r'([^\s,(]+)\s*(.*)$', text)
    if not m:
        raise EraError('Invalid function header', code='E_SYNTAX')
    name, tail = m.group(1).upper(), m.group(2).strip()
    if not IDENT.fullmatch(name) or '@' in name:
        raise EraError('Invalid function header', code='E_SYNTAX')
    if tail.startswith('('):
        if not tail.endswith(')'):
            raise EraError('Unclosed parameter list', code='E_SYNTAX')
        tail = tail[1:-1]
    elif tail.startswith(','):
        tail = tail[1:]
    elif tail:
        raise EraError(
            'Expected comma or parentheses after function name', code='E_SYNTAX'
        )
    return name, split_args(tail) if tail.strip() else []


class Program:
    def __init__(
        self,
        root: Path,
        encoding='auto',
        debug=False,
        single_file: Path | None = None,
        analysis_mode=False,
        *,
        analysis_files=None,
    ):
        self.root = root.resolve()
        self.encoding = encoding
        self.debug = debug
        self.functions: dict[str, list[Function]] = {}
        self.globals: list[SourceLine] = []
        self.macros: dict[str, str] = {}
        self.files = []
        self.function_file_batches = []
        self.enabled_line_count = 0
        self.warnings = []
        self.analysis_mode = analysis_mode
        self.analysis_driver = analysis_mode and analysis_files is not None
        self.argument_diagnostics = []
        self.definition_diagnostics = []
        self.lexical_diagnostics = []
        self.invalid_headers = []
        self.argument_coverage = []
        self.original_source = {}
        self.config = load_config(self.root, encoding, analysis_mode=analysis_mode)
        self.renames = {}
        csv = next(
            (p for p in self.root.iterdir() if p.is_dir() and p.name.upper() == 'CSV'),
            None,
        )
        if csv and self.config.get('_Rename.csvを利用する', 'NO').upper() == 'YES':
            rename = next(
                (
                    p
                    for p in csv.iterdir()
                    if p.is_file() and p.name.upper() == '_RENAME.CSV'
                ),
                None,
            )
            if rename:
                if not rename.resolve().is_relative_to(self.root):
                    raise EraError('Rename leaves root', code='E_PATH')
                for line in source_lines(read_text(rename, encoding)[0]):
                    if not line.strip() or line.lstrip().startswith(';'):
                        continue
                    parts = line.split(',')
                    if len(parts) >= 2:
                        self.renames[parts[1].strip()] = parts[0].strip()
        self.load_errors: list[EraError] = []
        folder = next(
            (p for p in self.root.iterdir() if p.is_dir() and p.name.upper() == 'ERB'),
            None,
        )
        if analysis_files is not None:
            if not analysis_mode:
                raise EraError(
                    'analysis_files requires analysis_mode', code='E_ARGUMENT'
                )
            erb = [Path(path).resolve() for path in analysis_files]
            from .analysis_mode import directory_files, _EVENT_LABELS

            erh = list(directory_files(folder, self.config, '.erh')) if folder else []
        elif single_file:
            erb = [single_file.resolve()]
            erh = sorted(
                (
                    p
                    for p in single_file.parent.iterdir()
                    if p.is_file() and p.suffix.lower() == '.erh'
                ),
                key=lambda p: str(p).casefold(),
            )
        elif folder:
            allpaths = sorted(
                (p for p in folder.rglob('*') if p.is_file()),
                key=lambda p: str(p).casefold(),
            )
            erb = [p for p in allpaths if p.suffix.lower() == '.erb']
            erh = [p for p in allpaths if p.suffix.lower() == '.erh']
        else:
            raise EraError(f'ERB directory not found in {self.root}', code='E_NO_ERB')
        if not erb:
            raise EraError('No .ERB files found', code='E_NO_ERB')
        headers = []
        for path in erh:
            try:
                headers.extend(self._lines(path))
            except EraError as e:
                self.load_errors.append(e)
        for line in headers:
            if command(line.text)[0] == '#DEFINE':
                rest = command(line.text)[1].strip()
                m = IDENT.match(rest)
                if not m:
                    self.load_errors.append(
                        EraError('Invalid #DEFINE', line.location, 'E_SYNTAX')
                    )
                    continue
                name = m.group().upper()
                tail = rest[m.end() :]
                if tail.startswith('('):
                    self.load_errors.append(
                        Unsupported(
                            'Parameterized #DEFINE is not implemented', line.location
                        )
                    )
                    continue
                self.macros[name] = tail.strip()
        for line in headers:
            if command(line.text)[0] in ('#DIM', '#DIMS'):
                self.globals.append(SourceLine(self.expand(line.text), line.location))
            elif command(line.text)[0] != '#DEFINE':
                self.load_errors.append(
                    Unsupported(f'ERH directive {line.text.split()[0]}', line.location)
                )
        uid = 0
        for path in erb:
            batch = []
            self.function_file_batches.append(batch)
            self.enabled_line_count += 1  # Native trailing NullLine per ERB.
            try:
                current = None
                for raw in self._lines(path):
                    if not raw.text.startswith('#'):
                        self.enabled_line_count += 1
                    if raw.text.startswith('@'):
                        try:
                            from .load_registration import header_delimiters

                            header_delimiters(self.expand(raw.text))
                            name, params = parse_signature(self.expand(raw.text))
                        except EraError as e:
                            from .load_registration import register

                            register(self, raw, e)
                            # InvalidLabelLine is retained for the native uncalled
                            # warning pass; it is never an executable function.
                            self.invalid_headers.append(raw)
                            current = Function('<Error>', [], raw.location, uid=uid)
                            uid += 1
                            continue
                        from .name_diagnostics import function_definition_warning

                        function_definition_warning(self, name, raw.location)
                        if (
                            self.analysis_driver
                            and name in self.functions
                            and name not in _EVENT_LABELS
                        ):
                            from .errors import LoadDiagnostic

                            senior = self.functions[name][0]
                            message = (
                                '関数@'
                                + name
                                + 'は既に定義('
                                + senior.location.path
                                + 'の'
                                + str(senior.location.line)
                                + '行目)されています'
                            )
                            self.definition_diagnostics.append(
                                LoadDiagnostic(
                                    1,
                                    'duplicate_function',
                                    raw.location,
                                    raw.text,
                                    message,
                                    len(self.definition_diagnostics),
                                    phase='lexical-registration',
                                )
                            )
                        current = Function(name, params, raw.location, uid=uid)
                        batch.append(current)
                        uid += 1
                        self.functions.setdefault(name, []).append(current)
                    elif current is None:
                        raise EraError(
                            'Statement before first @function', raw.location, 'E_SYNTAX'
                        )
                    elif raw.text.startswith('#'):
                        line = SourceLine(self.expand(raw.text), raw.location)
                        op, arg = command(line.text)
                        if current.lines:
                            raise EraError(
                                'Function directive after executable statements',
                                raw.location,
                                'E_SYNTAX',
                            )
                        if op in ('#DIM', '#DIMS'):
                            current.declarations.append(line)
                        elif op in (
                            '#FUNCTION',
                            '#FUNCTIONS',
                            '#PRI',
                            '#LATER',
                            '#ONLY',
                            '#SINGLE',
                        ):
                            attr = op[1:]
                            if attr == 'ONLY':
                                current.attributes.discard('PRI')
                                current.attributes.discard('LATER')
                                current.attributes.discard('SINGLE')
                                current.attributes.add('ONLY')
                            elif 'ONLY' in current.attributes and attr in {
                                'PRI',
                                'LATER',
                                'SINGLE',
                            }:
                                self.warnings.append(
                                    f'{raw.location}: #{attr} ignored because #ONLY is already set'
                                )
                            elif attr in {'FUNCTION', 'FUNCTIONS'}:
                                current.attributes.discard('PRI')
                                current.attributes.discard('LATER')
                                current.attributes.discard('SINGLE')
                                current.attributes.discard('ONLY')
                                current.attributes.add(attr)
                            else:
                                current.attributes.add(attr)
                        elif op == '#LOCALSIZE':
                            current.local_size = arg
                        elif op == '#LOCALSSIZE':
                            current.locals_size = arg
                        else:
                            raise Unsupported(f'Function directive {op}', raw.location)
                    else:
                        first = IDENT.match(raw.text)
                        if first and first.group().upper() in self.macros:
                            expanded = (
                                self.expand(first.group()) + raw.text[first.end() :]
                            )
                            raw = SourceLine(expanded, raw.location)
                        current.lines.append(raw)
            except EraError as e:
                self.load_errors.append(e)
        for name, funcs in self.functions.items():
            if len(funcs) > 1 and not name.startswith('EVENT'):
                self.warnings.append(
                    f'Duplicate non-event function @{name}; using first definition at {funcs[0].location}; later definitions retained for diagnostics.'
                )
            for func in funcs:
                compiler = Compiler(func, self.warnings)
                try:
                    compiler.compile()
                except EraError as e:
                    e.location = e.location or compiler.location
                    self.load_errors.append(e)
        from .load_registration import check_lines

        check_lines(self)

    def _lines(self, path):
        if not self.analysis_driver and not path.resolve().is_relative_to(self.root):
            raise EraError(f'Source leaves root: {path}', code='E_PATH')
        text, encoding = read_text(path, self.encoding)
        source_file = (
            str(path.resolve())
            if self.analysis_driver
            else path.relative_to(self.root).as_posix()
        )
        physical_lines = source_lines(text)
        self.original_source[source_file] = physical_lines
        self.files.append(
            {'file': source_file, 'encoding': encoding, 'bytes': path.stat().st_size}
        )
        conditions = []
        skipping = 0
        continued = []
        begin = None
        for no, raw in enumerate(physical_lines, 1):
            if '[[' in raw and self.renames:
                raw = re.sub(
                    r'\[\[([^\]]+)\]\]', lambda m: self.renames.get(m[1], m[0]), raw
                )
            # Reference Emuera skips leading whitespace but keeps the rest of
            # the physical line intact.  Do not `.strip()` here: PRINT/PRINTFORM
            # can intentionally use trailing or full-width spaces as display data.
            from .registry import command_spec

            raw_line = raw.lstrip(' \t\u3000')
            if raw_line.startswith(';!;'):
                raw_line = raw_line[3:].lstrip(' \t\u3000')
            raw_match = re.match(r'[A-Za-z_][A-Za-z_0-9]*', raw_line)
            raw_op = raw_match[0].upper() if raw_match else ''
            raw_spec = command_spec(raw_op) or {}
            line = (
                raw_line
                if raw_spec.get('preserve_raw_semicolons')
                else strip_comment(raw_line)
            )
            loc = Location(source_file, no)
            up = line.rstrip(' \t\u3000').upper()
            if up == '[SKIPSTART]':
                skipping += 1
                continue
            if up == '[SKIPEND]':
                if not skipping:
                    raise EraError('Unmatched SKIPEND', loc, 'E_SYNTAX')
                skipping -= 1
                continue
            if skipping:
                continue
            cond = re.fullmatch(r'\[IF\s+([^\]]+)\]', up)
            if up in ('[IF_DEBUG]', '[IF_NDEBUG]') or cond:
                active = (
                    (cond[1].strip() in self.macros)
                    if cond
                    else self.debug if up == '[IF_DEBUG]' else not self.debug
                )
                conditions.append([active, active, False])
                continue
            elseif = re.fullmatch(r'\[ELSEIF\s+([^\]]+)\]', up)
            if up == '[ELSE]' or elseif:
                if not conditions:
                    raise EraError(
                        'Unmatched preprocessor ELSE/ELSEIF', loc, 'E_SYNTAX'
                    )
                top = conditions[-1]
                if top[2]:
                    raise EraError('Duplicate preprocessor ELSE', loc, 'E_SYNTAX')
                active = not top[1] and (
                    True if not elseif else elseif[1].strip() in self.macros
                )
                top[0] = active
                top[1] |= active
                top[2] = not bool(elseif)
                continue
            if up == '[ENDIF]':
                if not conditions:
                    raise EraError('Unmatched preprocessor ENDIF', loc, 'E_SYNTAX')
                conditions.pop()
                continue
            if not all(c[0] for c in conditions):
                continue
            try:
                line_op, line_arg = command(line)
            except EraError as e:
                e.location = e.location or loc
                raise
            if line_op == '#DEFINE':
                rest = line_arg.strip()
                m = IDENT.match(rest)
                if m and not rest[m.end() :].startswith('('):
                    self.macros[m.group().upper()] = rest[m.end() :].strip()
            if not line.rstrip(' \t\u3000'):
                continue
            structural = line.rstrip(' \t\u3000')
            if structural == '{':
                if continued:
                    raise EraError('Nested line-continuation block', loc, 'E_SYNTAX')
                begin = loc
                continued = ['']
                continue
            if structural == '}' and continued:
                yield SourceLine(' '.join(continued).strip(), begin)
                continued = []
                begin = None
                continue
            if continued:
                continued.append(line)
                continue
            if structural.startswith('['):
                raise Unsupported(f'Preprocessor {structural}', loc)
            yield SourceLine(line, loc)
        if conditions or skipping or continued:
            raise EraError(
                'Unclosed preprocessor/continuation block',
                Location(source_file, len(physical_lines)),
                'E_SYNTAX',
            )

    def expand(self, text: str) -> str:
        """Object-like macros outside quoted strings; FORMs expand their expressions at runtime."""
        if not self.macros:
            return text
        for _ in range(64):
            output = []
            i = 0
            changed = False
            quote = False
            escape = False
            while i < len(text):
                c = text[i]
                if escape:
                    output.append(c)
                    escape = False
                    i += 1
                    continue
                if c == '\\':
                    output.append(c)
                    escape = True
                    i += 1
                    continue
                if c == '"':
                    quote = not quote
                    output.append(c)
                    i += 1
                    continue
                if not quote:
                    m = IDENT.match(text, i)
                    if m:
                        word = m.group()
                        replacement = self.macros.get(word.upper(), word)
                        output.append(replacement)
                        changed |= replacement != word
                        i = m.end()
                        continue
                output.append(c)
                i += 1
            result = ''.join(output)
            if not changed:
                return result
            if len(result) > 1_000_000:
                raise EraError('Macro expansion size limit', code='E_MACRO')
            text = result
        raise EraError('Recursive macro expansion', code='E_MACRO')

    def event_groups(self, name):
        fs = self.functions.get(name.upper(), [])
        only = [f for f in fs if 'ONLY' in f.attributes]
        if only:
            return [only[:1]]
        pri = [f for f in fs if 'PRI' in f.attributes]
        normal = [f for f in fs if not ({'PRI', 'LATER'} & f.attributes)]
        later = [f for f in fs if 'LATER' in f.attributes]
        return [group for group in (pri, normal, later) if group]

    def event_functions(self, name):
        return [f for group in self.event_groups(name) for f in group]


class Compiler:
    def __init__(self, func, warnings=None):
        self.warnings = warnings if warnings is not None else []
        self.func = func
        self.lines = func.lines
        self.i = 0
        self.code = func.code
        self.loops = []
        self.location = func.location

    def emit(self, op, arg, loc, jump=-1, data=None):
        n = len(self.code)
        self.code.append(Instruction(op, arg, loc, jump, data))
        return n

    def compile(self):
        noskip = None
        for line in self.lines:
            self.location = line.location
            op, arg = command(line.text)
            if op == 'NOSKIP':
                if noskip:
                    raise Unsupported('Nested NOSKIP blocks', line.location)
                noskip = line.location
            elif op == 'ENDNOSKIP':
                if noskip is None:
                    raise EraError(
                        'ENDNOSKIP without NOSKIP', line.location, 'E_SYNTAX'
                    )
                noskip = None
        if noskip:
            raise EraError('NOSKIP without ENDNOSKIP', noskip, 'E_SYNTAX')
        self.block(set())

    def _compile_conditional(self, line, arg):
        """Consume IF arms and patch condition/exits in their original order.

        The opening line is already consumed. Recursive block calls leave their
        stop marker unconsumed; this construct consumes it at the existing point.
        Generated code/labels and compiler position are retained on failure.
        """
        exits = []
        cond = self.emit('_IF', arg, line.location)
        while True:
            stop = self.block({'ELSEIF', 'ELSE', 'ENDIF'})
            if stop is None:
                raise EraError('Unclosed IF', line.location, 'E_SYNTAX')
            marker = self.lines[self.i]
            _, tail = command(marker.text)
            self.i += 1
            if stop == 'ENDIF':
                self.code[cond].jump = len(self.code)
                break
            exits.append(self.emit('_JMP', '', marker.location))
            self.code[cond].jump = len(self.code)
            if stop == 'ELSE':
                end = self.block({'ENDIF'})
                if end is None:
                    raise EraError('Unclosed ELSE', marker.location, 'E_SYNTAX')
                self.i += 1
                break
            cond = self.emit('_IF', tail, marker.location)
        for n in exits:
            self.code[n].jump = len(self.code)

    def _compile_loop(self, line, op, arg, construct):
        """Lower loop body, then closer/step, then break and continue targets.

        The opening line is already consumed. Recursive block calls leave their
        stop marker unconsumed; this construct consumes it at the existing point.
        Generated code/labels and compiler position are retained on failure.
        """
        start = len(self.code)
        begin = self.emit(construct['primitive'], arg, line.location)
        self.loops.append({'break': [], 'continue': []})
        ending = construct['closes_with']
        stop = self.block({ending})
        if stop is None:
            raise EraError(f'Unclosed {op}', line.location, 'E_SYNTAX')
        endline = self.lines[self.i]
        self.i += 1
        _, test = command(endline.text)
        step = len(self.code)
        if op == 'WHILE':
            self.emit('_JMP', '', endline.location, start)
        elif op == 'DO':
            self.emit('_LOOP', test, endline.location, start + 1, data=start)
        else:
            self.emit('_STEP', '', endline.location, start + 1, data=start)
        end = len(self.code)
        self.code[begin].jump = end
        self.code[begin].data = step
        loop = self.loops.pop()
        for p in loop['break']:
            self.code[p].jump = end
            self.code[p].data = start
        for p in loop['continue']:
            self.code[p].jump = step

    def _compile_select(self, line, arg):
        """Build CASE search links and select-exit markers before ENDSELECT.

        The opening line is already consumed. Recursive block calls leave their
        stop marker unconsumed; this construct consumes it at the existing point.
        Generated code/labels and compiler position are retained on failure.
        """
        select = self.emit('_SELECT', arg, line.location)
        exits = []
        previous = None
        while True:
            if self.i >= len(self.lines):
                raise EraError('Unclosed SELECTCASE', line.location, 'E_SYNTAX')
            mark = self.lines[self.i]
            case, val = command(mark.text)
            self.i += 1
            if case == 'ENDSELECT':
                break
            if case not in ('CASE', 'CASEELSE'):
                raise EraError('Expected CASE', mark.location, 'E_SYNTAX')
            if previous is not None:
                self.code[previous].jump = len(self.code)
                self.code[exits[-1]].data = ('select_exit', len(self.code))
            previous = self.emit(
                '_CASE', val, mark.location, data=(select, case == 'CASEELSE')
            )
            stop = self.block({'CASE', 'CASEELSE', 'ENDSELECT'})
            if stop is None:
                raise EraError('Unclosed SELECTCASE', mark.location, 'E_SYNTAX')
            exits.append(self.emit('_JMP', '', mark.location))
        end = len(self.code)
        if previous is not None:
            self.code[previous].jump = end
        for p in exits:
            self.code[p].jump = end
        self.emit('_ENDSELECT', '', line.location, data=select)

    def _compile_data(self, line, op, arg):
        """Collect DATA alternatives/groups without evaluation or RNG consumption.

        The opening line is already consumed. Recursive block calls leave their
        stop marker unconsumed; this construct consumes it at the existing point.
        Generated code/labels and compiler position are retained on failure.
        """
        alternatives = []
        group = None
        while self.i < len(self.lines):
            d = self.lines[self.i]
            self.i += 1
            dop, darg = command(d.text)
            if dop == 'ENDDATA':
                break
            if dop == 'DATALIST':
                if group is not None:
                    raise EraError('Nested DATALIST', d.location, 'E_SYNTAX')
                group = []
            elif dop == 'ENDLIST':
                if group is None:
                    raise EraError('Unmatched ENDLIST', d.location, 'E_SYNTAX')
                alternatives.append(group)
                group = None
            elif dop in ('DATA', 'DATAFORM'):
                item = (dop, darg)
                if group is None:
                    alternatives.append([item])
                else:
                    group.append(item)
            else:
                raise Unsupported(f'{dop} inside {op}', d.location)
        else:
            raise EraError('Unclosed PRINTDATA/STRDATA', line.location, 'E_SYNTAX')
        if group is not None:
            raise EraError('Unclosed DATALIST', line.location, 'E_SYNTAX')
        self.emit('_DATA', arg, line.location, data=(op, alternatives))

    def block(self, stops):
        """Consume source lines until an unconsumed stop marker or EOF.

        Source index advances before label/construct handling. Each lowering
        helper owns its full nested construct, code emission and jump patching.
        No ERB values are evaluated here: emitted expressions run later in VM.
        """
        while self.i < len(self.lines):
            line = self.lines[self.i]
            self.location = line.location
            op, arg = command(line.text)
            if op in stops:
                return op
            self.i += 1
            if line.text.startswith('$'):
                label = line.text[1:].strip().upper()
                if label in self.func.labels:
                    raise EraError(
                        f'Duplicate label ${label}', line.location, 'E_DUPLICATE'
                    )
                self.func.labels[label] = len(self.code)
                continue
            construct = SYNTAX_SPECS.get(op)
            kind = construct['kind'] if construct else None
            if kind == 'conditional':
                self._compile_conditional(line, arg)
                continue
            if kind == 'single_if':
                cond = self.emit('_IF', arg, line.location)
                if self.i >= len(self.lines):
                    raise EraError('SIF without statement', line.location, 'E_SYNTAX')
                n = self.lines[self.i]
                self.i += 1
                nop, narg = command(n.text)
                if (SYNTAX_SPECS.get(nop) or {}).get('kind') in {
                    'conditional',
                    'single_if',
                    'loop',
                    'select',
                    'data',
                    'try_list',
                    'try_catch',
                    'marker',
                }:
                    raise Unsupported(
                        'Structured statement immediately after SIF', n.location
                    )
                self.simple(nop, narg, n.location)
                self.code[cond].jump = len(self.code)
                continue
            if kind == 'loop':
                self._compile_loop(line, op, arg, construct)
                continue
            if kind == 'select':
                self._compile_select(line, arg)
                continue
            if kind == 'data':
                self._compile_data(line, op, arg)
                continue
            if kind == 'try_catch':
                n = self.emit(op, arg, line.location)
                stop = self.block({'CATCH'})
                if stop is None:
                    raise EraError('TRYC without CATCH', line.location, 'E_SYNTAX')
                self.i += 1
                skip = self.emit('_JMP', '', line.location)
                self.code[n].jump = len(self.code)
                if self.block({'ENDCATCH'}) is None:
                    raise EraError('Unclosed CATCH', line.location, 'E_SYNTAX')
                self.i += 1
                self.code[skip].jump = len(self.code)
                continue
            if kind == 'try_list':
                choices = []
                while self.i < len(self.lines):
                    d = self.lines[self.i]
                    self.i += 1
                    dop, darg = command(d.text)
                    if dop == 'ENDFUNC':
                        break
                    if dop != 'FUNC':
                        raise EraError(
                            'Expected FUNC or ENDFUNC', d.location, 'E_SYNTAX'
                        )
                    choices.append(darg)
                else:
                    raise EraError('Unclosed TRYLIST', line.location, 'E_SYNTAX')
                self.emit('_TRYLIST', op, line.location, data=choices)
                continue
            if op in {
                'ELSEIF',
                'ELSE',
                'ENDIF',
                'WEND',
                'NEXT',
                'REND',
                'LOOP',
                'CASE',
                'CASEELSE',
                'ENDSELECT',
                'CATCH',
                'ENDCATCH',
                'ENDDATA',
                'ENDFUNC',
            }:
                raise EraError(f'Unmatched {op}', line.location, 'E_SYNTAX')
            self.simple(op, arg, line.location)
        return None

    def simple(self, op, arg, loc):
        if op == '_ASSIGN':
            found = find_assignment(arg, legacy=True)
            if found and found[1] == '==':
                # Parse the destination, not an arbitrary comparison expression.
                # Only this statement category accepts the old spelling.
                from .expr import parse

                if parse(found[0])[0] != 'var':
                    raise EraError(
                        'Legacy assignment requires a variable destination',
                        loc,
                        'E_SYNTAX',
                    )
                self.warnings.append(
                    f'{loc}: 代入演算子に"=="が使われています（eramaker互換として代入）'
                )
                arg = found[0] + ' = ' + found[2]
        if op in ('BREAK', 'CONTINUE'):
            if not self.loops:
                raise EraError(f'{op} outside loop', loc, 'E_SYNTAX')
            p = self.emit('_BREAK' if op == 'BREAK' else '_JMP', '', loc)
            self.loops[-1]['break' if op == 'BREAK' else 'continue'].append(p)
        else:
            self.emit(op, arg, loc)
