"""Iterative ERB VM. ERB text is never passed to Python eval/exec.

This is an explicit, fail-closed subset, not a claim of complete Emuera compatibility.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import copy
import random
import re
from . import builtins
from .console import Console
from .data import GameData, Variable, Ref
from .errors import (
    EraError,
    InternalError,
    Unsupported,
    FlowSignal,
    QuitSignal,
    TrainRequest,
    Location,
)
from .expr import (
    parse,
    parse_case_condition,
    evaluate,
    integer,
    i64,
    apply_binary,
    IDENT,
)
from .formatting import render
from .program import Program, Function, Instruction
from .text import split_args, split_form_args, split_dynamic_call, find_assignment
from .persistence import Saves

from .registry import COMMAND_SPECS, SYNTAX_SPECS
from .select_flow import skip_search_error, exit_target, case_match
from .internal_state import clear_syntax_caches, clear_validation_caches

CALL_OPS = frozenset(n for n, s in COMMAND_SPECS.items() if s['family'] == 'call')
DISPLAY_OPS = frozenset(n for n, s in COMMAND_SPECS.items() if s['family'] == 'display')
COMMANDS = frozenset(COMMAND_SPECS)
INTERNAL_OPS = frozenset(
    '_ASSIGN _IF _JMP _FOR _REPEAT _STEP _BREAK _DO _LOOP _SELECT _CASE _ENDSELECT _DATA _TRYLIST'.split()
)

_SPECIAL_NAMES = frozenset(
    (
        'CHARANUM',
        'LINECOUNT',
        '__INT_MAX__',
        '__INT_MIN__',
        '__LINE__',
        '__FILE__',
        '__FUNCTION__',
        'PRINTCPERLINE',
        'PRINTCLENGTH',
    )
)


def supported_command(op):
    return op in COMMAND_SPECS or op in INTERNAL_OPS


@dataclass
class Declaration:
    name: str
    dims: tuple[int, ...]
    string: bool
    flags: set[str]
    values: list[int | str]

    def make(self):
        var = Variable(
            self.name,
            self.dims,
            self.string,
            'CHARADATA' in self.flags,
            'CONST' in self.flags,
            'SAVEDATA' in self.flags,
            'GLOBAL' in self.flags,
        )
        if var.character and self.values:
            raise Unsupported('CHARADATA initializers')
        for i, v in enumerate(self.values):
            var.set((i,), v, True)
        return var


@dataclass
class Frame:
    function: Function
    scope: dict[str, Variable | Ref | None]
    pc: int = 0
    loops: dict = field(default_factory=dict)
    selects: dict = field(default_factory=dict)
    select_searches: set = field(default_factory=set)
    result: int | str = 0
    finished: bool = False
    entry_checked: bool = False
    method: bool = False
    skip_marks: list = field(default_factory=list)
    call_site_location: Location | None = None
    instruction_location: Location | None = None


class VM:
    """Execution state with explicitly owned, per-instance syntax caches.

    ``internal_state.VM_CACHE_CONTRACTS`` records the additional lazy caches
    attached by argument/FORM/resource adapters. They are intentionally not
    precreated here: absence, a created empty set and a scanned-empty catalog
    are different states. Reset/save-load restore values, not loaded metadata.
    Cached plans never retain live indices, REF bindings or evaluated values.
    """
    def __init__(
        self,
        program: Program,
        data: GameData,
        console: Console | None = None,
        seed: int | None = None,
        max_steps=0,
        max_frames=4096,
        journal=None,
    ):
        if program.load_errors and not getattr(program, "analysis_driver", False):
            raise program.load_errors[0]
        self.program = program
        self.data = data
        self.root = data.root
        self.console = console or Console()
        from .random1824 import EngineRandom

        self.rng = EngineRandom(seed)
        self.frames: list[Frame] = []
        self.steps = 0
        self.max_steps = max_steps
        self.max_frames = max_frames
        self.method_depth = 0
        self.location = None
        self.static = {}
        self.legacy = {}
        self.declarations = {}
        self.active_init = {}
        # Per-VM syntax plans: never cache values, character indices or bindings.
        self._expression_cache = {}
        self._assignment_cache = {}
        self._loop_cache = {}
        self.ui = {
            'color': 0xC0C0C0,
            'bgcolor': 0,
            'font': data.config.get('フォント名', 'ＭＳ ゴシック'),
            'alignment': 'LEFT',
            'redraw': 1,
            'style': 0,
            'kana': 0,
        }
        self.console.ui = self.ui
        self.default_color = 0xC0C0C0
        self.default_background = 0
        self.journal = journal
        self.train_context = None
        self.train_phase = None
        self.flow_state = None
        self.pending_begin = None
        self._event_depth = 0
        self.train_queue = None
        self.train_queue_index = 0
        self.train_queue_total = 0
        self.exit_reason = None
        self.saves = Saves(self)
        self.initializing_declarations = True
        try:
            self._initialize_declarations()
        except EraError as e:
            e.location = e.location or self.location
            raise
        finally:
            self.initializing_declarations = False
        from .load_arguments import compile_arguments

        compile_arguments(self)
        self._load_diagnostics_emitted = False
        self.initial = copy.deepcopy(self.data.variables)
        self.static_initial = copy.deepcopy(self.static)
        self.legacy_initial = copy.deepcopy(self.legacy)
        if journal:
            journal.bind(self)

    def tick(self):
        self.steps += 1
        if self.max_steps and self.steps > self.max_steps:
            raise EraError(
                f'Configured instruction limit exceeded ({self.max_steps}); execution stopped by --max-steps',
                self.location,
                'E_LIMIT',
            )

    def expression_node(self, text):
        node = self._expression_cache.get(text)
        if node is None:
            node = parse(self.program.expand(text))
            if len(self._expression_cache) >= 131072:
                self._expression_cache.clear()
            self._expression_cache[text] = node
        return node

    def invalidate_execution_cache(self):
        """Recheck runtime syntax/types after an embedder changes metadata.

        A changed FORM macro can invalidate a successful type check even if
        its raw text/function UID is unchanged. Recheck all operands before
        any substitution effects, matching StrForm.FromWordToken's ordering.
        This does not reload compiled instructions or resource CSV snapshots;
        a complete reload still needs a fresh Program/GameData/VM pair.
        """
        clear_syntax_caches(self)
        clear_validation_caches(self)

    def eval(self, text):
        return self.eval_node(self.expression_node(text))

    def eval_node(self, node):
        return evaluate(node, self)

    def format(self, text):
        return render(text, self)

    def html_plain(self, text):
        from .plain_html import html_plain

        return html_plain(text)

    def args(self, text):
        return (
            [self.eval(s) if s else None for s in split_args(text)]
            if text.strip()
            else []
        )

    def lookup(self, name):
        name = name.upper()
        if '@' in name:
            base, fn = name.split('@', 1)
            if base not in {'LOCAL', 'LOCALS', 'ARG', 'ARGS'}:
                raise Unsupported(
                    'Qualified private variables other than LOCAL/LOCALS/ARG/ARGS'
                )
            if fn not in self.legacy:
                raise EraError(f'Unknown qualified function @{fn}', code='E_VARIABLE')
            var = self.legacy[fn][base]
            if var.forbidden:
                raise EraError(
                    f'{name} is disabled by VariableSize.csv',
                    code='E_VARIABLE_FORBIDDEN',
                )
            return var
        if name in self.active_init:
            var = self.active_init[name]
            if var is not None and var.forbidden:
                raise EraError(
                    f'{name} is disabled by VariableSize.csv',
                    code='E_VARIABLE_FORBIDDEN',
                )
            return var
        if self.frames and name in self.frames[-1].scope:
            v = self.frames[-1].scope[name]
            if v is None:
                raise EraError(f'Unbound REF variable {name}', code='E_REFERENCE')
            var = v.variable if isinstance(v, Ref) else v
            if var.forbidden:
                raise EraError(
                    f'{name} is disabled by VariableSize.csv',
                    code='E_VARIABLE_FORBIDDEN',
                )
            return var
        if name not in self.data.variables:
            raise EraError(f'Unknown variable {name}', code='E_VARIABLE')
        var = self.data.variables[name]
        if var.forbidden:
            raise EraError(
                f'Variable {name} is disabled by VariableSize.csv',
                code='E_VARIABLE_FORBIDDEN',
            )
        return var

    def _resolve_ref(self, node, allow_character_descriptor=False):
        if node[0] != 'var':
            raise EraError('Expected a variable reference', code='E_REFERENCE')
        name, indices = node[1], node[2]
        var = self.lookup(name)
        alias = self.frames[-1].scope.get(name) if self.frames else None
        if isinstance(alias, Ref):
            if var.character:
                raise Unsupported('REF to a character array')
            if any(alias.key):
                raise Unsupported('REF with a nonzero base index')
        rank = len(var.dims)
        total = rank + bool(var.character)
        implicit = bool(var.character and len(indices) <= rank)
        if len(indices) + implicit > total:
            raise EraError(f'{name}: too many array indices', code='E_INDEX')
        values = []
        if implicit:
            values.append(
                0 if allow_character_descriptor else self.lookup('TARGET').get((0,))
            )
        for position, node_index in enumerate(indices):
            axis = position + implicit
            if node_index[0] == 'lit':
                value = node_index[1]
            elif node_index[0] == 'var' and not node_index[2]:
                try:
                    value = self.eval_node(node_index)
                except EraError as e:
                    if e.code != 'E_VARIABLE':
                        raise
                    value = self.data.index_of(name, node_index[1], axis)
            else:
                value = self.eval_node(node_index)
            if isinstance(value, str):
                value = self.data.index_of(name, value, axis)
            values.append(integer(value))
        if len(values) < total:
            values.extend((0,) * (total - len(values)))
        key = tuple(values)
        var.validate(key)
        if (
            var.character
            and not allow_character_descriptor
            and not 0 <= key[0] < self.data.character_count
        ):
            raise EraError(
                f'{name}: character index {key[0]} outside 0..{self.data.character_count-1}',
                code='E_CHARACTER',
            )
        return var, key

    def ref_node(self, node, allow_character_descriptor=False):
        var, key = self._resolve_ref(node, allow_character_descriptor)
        return Ref(var, key)

    def ref(self, text):
        return self.ref_node(self.expression_node(text))

    def get(self, name):
        return self.ref(name).get()

    def set(self, name, value):
        self.ref(name).set(value)

    def read_node(self, node):
        name = node[1]
        indices = node[2]
        if name == 'RAND':
            a = [integer(self.eval_node(x)) for x in indices]
            if len(a) != 1 or a[0] <= 0:
                raise EraError('RAND:n requires n > 0', code='E_ARGUMENT')
            return self.rng.randrange(a[0])
        if name in _SPECIAL_NAMES:
            if indices:
                raise EraError(f'{name} is scalar', code='E_INDEX')
            if name == 'CHARANUM':
                return self.data.character_count
            if name == 'LINECOUNT':
                return self.console.line_count
            if name == '__INT_MAX__':
                return (1 << 63) - 1
            if name == '__INT_MIN__':
                return -(1 << 63)
            if name == '__LINE__':
                return self.location.line if self.location and self.program.debug else 0
            if name == '__FILE__':
                return (
                    self.location.path if self.location and self.program.debug else ''
                )
            if name == '__FUNCTION__':
                return (
                    self.frames[-1].function.name
                    if self.frames and self.program.debug
                    else ''
                )
            if name == 'PRINTCPERLINE':
                return max(1, int(self.data.config.get('PRINTCを並べる数', '3')))
            return max(1, int(self.data.config.get('PRINTCの文字数', '25')))
        # A read has no Ref lifetime. Validate once, then read sparse storage.
        var, key = self._resolve_ref(node)
        return var.values.get(key, var.default)

    def _declaration(self, text, private=False):
        directive = text.split(None, 1)
        if len(directive) != 2:
            raise EraError('Missing declaration name', code='E_DECLARATION')
        string = directive[0].upper() == '#DIMS'
        rest = directive[1].strip()
        flags = set()
        known = {'CONST', 'DYNAMIC', 'REF', 'SAVEDATA', 'GLOBAL', 'CHARADATA'}
        while rest.split(None, 1)[0].upper() in known:
            parts = rest.split(None, 1)
            flag = parts[0]
            rest = parts[1] if len(parts) > 1 else ''
            flags.add(flag.upper())
            rest = rest.lstrip()
            if not rest:
                raise EraError('Missing declaration name', code='E_DECLARATION')
        assign = find_assignment(rest)
        if assign:
            head, op, value = assign
            if op != '=':
                raise EraError(
                    'Declaration initializer requires =', code='E_DECLARATION'
                )
            # ReduceArguments stops at EOL after a final comma. Interior
            # missing operands are still rejected by UserDefinedVariable.
            initializers = split_args(value)
            if initializers and not initializers[-1]:
                initializers.pop()
            if not initializers or any(not x for x in initializers):
                raise EraError(
                    'Array initializer cannot be omitted', code='E_DECLARATION'
                )
            vals = [self.eval(x) for x in initializers]
        else:
            head = rest
            vals = []
        parts = split_args(head)
        name = parts[0].upper()
        if not IDENT.fullmatch(name) or '@' in name:
            raise EraError(f'Invalid variable name {name}', code='E_DECLARATION')
        if private and flags & {'GLOBAL', 'SAVEDATA', 'CHARADATA'}:
            raise EraError(
                'Storage flag not valid for a private variable', code='E_DECLARATION'
            )
        if not private and flags & {'DYNAMIC', 'REF'}:
            raise Unsupported('Global DYNAMIC / REF declarations')
        if 'REF' in flags:
            if vals:
                raise EraError('REF cannot have an initializer', code='E_DECLARATION')
            dims = tuple(0 for x in parts[1:]) or (0,)
        else:
            dims = (
                tuple(integer(self.eval(x)) for x in parts[1:])
                if len(parts) > 1
                else (max(1, len(vals)),)
            )
            if not 1 <= len(dims) <= 3 or any(x < 1 or x > 1_000_000 for x in dims):
                raise EraError(
                    f'Invalid dimensions of {name}: {dims}', code='E_DECLARATION'
                )
        if vals and (len(dims) != 1 or len(vals) > dims[0]):
            raise EraError('Initializer does not fit a 1D array', code='E_DECLARATION')
        if any(isinstance(v, str) != string for v in vals):
            raise EraError('Initializer type mismatch', code='E_TYPE')
        if 'CONST' in flags and (not vals or len(vals) != dims[0]):
            raise EraError(
                'CONST requires a complete initializer', code='E_DECLARATION'
            )
        if 'CONST' in flags and flags & {'DYNAMIC', 'REF', 'GLOBAL', 'CHARADATA'}:
            raise EraError('Invalid CONST flags', code='E_DECLARATION')
        return Declaration(name, dims, string, flags, vals)

    def _private_declaration(self, line):
        """Parse before registration; the analysis loader may discard a bad # line."""
        declaration = self._declaration(line.text, True)
        if (
            declaration.name in self.active_init
            or declaration.name in self.data.variables
        ):
            raise EraError(
                f'Variable collision {declaration.name}', line.location, 'E_DUPLICATE'
            )
        return declaration

    def _initialize_declarations(self):
        # Resolve declarations in stable passes so cross-header constants need not be ordered.
        pending = list(self.program.globals)
        while pending:
            later = []
            errors = []
            progress = False
            for line in pending:
                self.location = line.location
                try:
                    d = self._declaration(line.text)
                except EraError as e:
                    if e.code in {'E_VARIABLE', 'E_SYMBOL'}:
                        later.append(line)
                        errors.append(e)
                        continue
                    e.location = e.location or line.location
                    raise
                if d.name in self.data.variables:
                    raise EraError(
                        f'Duplicate variable {d.name}', line.location, 'E_DUPLICATE'
                    )
                self.data.variables[d.name] = d.make()
                progress = True
            if later and not progress:
                errors[0].location = later[0].location
                raise errors[0]
            pending = later
        for funcs in self.program.functions.values():
            for f in funcs:
                self.location = f.location
                if f.name not in self.legacy:
                    scope = {}
                    for name, size in [
                        ('LOCAL', 1000),
                        ('LOCALS', 100),
                        ('ARG', 1000),
                        ('ARGS', 100),
                    ]:
                        dim = self.data.sizes.get(name, (size,))[0]
                        custom = (
                            f.local_size
                            if name == 'LOCAL'
                            else f.locals_size if name == 'LOCALS' else ''
                        )
                        if custom:
                            dim = integer(self.eval(custom))
                        disabled = self.data.sizes.get(name, (size,))[0] < 0
                        if disabled:
                            dim = 0
                        if not disabled and not 1 <= dim <= 1_000_000:
                            raise EraError(
                                f'Invalid {name} size', f.location, 'E_DECLARATION'
                            )
                        scope[name] = Variable(
                            name, (dim,), name in {'LOCALS', 'ARGS'}, forbidden=disabled
                        )
                    for parameter in f.parameters:
                        ass = find_assignment(parameter)
                        lhs = ass[0] if ass else parameter
                        m = re.fullmatch(r'(ARGS?)\s*:\s*(\d+)', lhs.strip(), re.I)
                        if m:
                            v = scope[m[1].upper()]
                            needed = int(m[2]) + 1
                            if needed > 1_000_000:
                                raise EraError('ARG size limit', f.location, 'E_LIMIT')
                            if not v.forbidden:
                                v.dims = (max(v.dims[0], needed),)
                    self.legacy[f.name] = scope
                self.static[f.uid] = {}
                self.declarations[f.uid] = []
                self.active_init = {**self.legacy[f.name]}
                try:
                    for line in f.declarations:
                        self.location = line.location
                        d = self._private_declaration(line)
                        if d is None:
                            continue
                        self.declarations[f.uid].append(d)
                        if 'REF' in d.flags:
                            v = None
                        else:
                            v = d.make()
                        self.active_init[d.name] = v
                        if not d.flags & {'DYNAMIC', 'REF'}:
                            self.static[f.uid][d.name] = v
                finally:
                    self.active_init = {}
        self.location = None

    def _capture_arguments(self, f, actuals, declmap):
        """Resolve actuals left to right in caller scope, before a frame exists.

        REF parameters capture a live array descriptor; others capture values.
        A failed actual evaluation preserves prior effects and caller location.
        Defaults are deliberately deferred until the callee scope is active.
        """
        captured = []
        for p, node in zip(f.parameters, actuals):
            ass = find_assignment(p)
            lhs = ass[0] if ass else p
            target = parse(lhs)
            d = declmap.get(target[1]) if target[0] == 'var' else None
            if node is None or node[0] == 'missing':
                captured.append(None)
            elif d and 'REF' in d.flags:
                ref = self.ref_node(node)
                if ref.variable.character or any(ref.key):
                    raise Unsupported('REF requires a complete non-character array')
                if ref.variable.string != d.string or len(ref.variable.dims) != len(
                    d.dims
                ):
                    raise EraError('REF type/rank mismatch', code='E_REFERENCE')
                captured.append(ref)
            else:
                captured.append(self.eval_node(node))
        return captured

    def _bind_parameters(self, frame, declmap, captured):
        """Bind captured actuals/defaults in the installed callee scope.

        Writes are sequential and are not rolled back on a later error. The
        owning _new_frame removes only the failed frame, not earlier writes.
        """
        f = frame.function
        scope = frame.scope
        for i, p in enumerate(f.parameters):
            ass = find_assignment(p)
            lhs = ass[0] if ass else p
            default = ass[2] if ass else None
            target = parse(lhs)
            d = declmap.get(target[1]) if target[0] == 'var' else None
            value = captured[i] if i < len(captured) else None
            if d and 'REF' in d.flags:
                if not isinstance(value, Ref):
                    raise EraError(f'Missing REF argument {d.name}', code='E_REFERENCE')
                scope[d.name] = value
                continue
            ref = self.ref_node(target)
            if value is None:
                if default is not None:
                    value = self.eval(default)
                elif (
                    target[0] == 'var' and target[1] in {'ARG', 'ARGS'}
                ) or d is not None:
                    # src1824 assigns implicit 0/"" defaults to ARG/ARGS
                    # and private-variable parameters at function-load time.
                    value = '' if ref.variable.string else 0
                elif (
                    self.program.config.get(
                        'ユーザー関数の全ての引数の省略を許可する', 'NO'
                    ).upper()
                    == 'YES'
                ):
                    value = '' if ref.variable.string else 0
                else:
                    raise EraError(
                        f'@{f.name}: argument {i+1} cannot be omitted',
                        code='E_ARGUMENT',
                    )
            if ref.variable.string and isinstance(value, int):
                if (
                    self.program.config.get(
                        'ユーザー関数の引数に自動的にTOSTRを補完する', 'NO'
                    ).upper()
                    == 'YES'
                ):
                    value = str(value)
                else:
                    raise EraError(
                        f'@{f.name}: integer argument {i+1} cannot be converted to string',
                        code='E_TYPE',
                    )
            ref.set(value)

    def _new_frame(self, f, actuals=None, method=False):
        """Capture caller arguments, install scope, bind, then notify journal.

        Frame-limit checks stay after actual evaluation and scope allocation.
        Binding failure pops this frame while keeping prior storage effects.
        """
        actuals = actuals or []
        if len(actuals) > len(f.parameters):
            raise EraError(f'@{f.name}: too many arguments', code='E_ARGUMENT')
        # Capture caller values / references before switching the active frame.
        declmap = {d.name: d for d in self.declarations[f.uid]}
        captured = self._capture_arguments(f, actuals, declmap)
        scope = {**self.legacy[f.name], **self.static[f.uid]}
        for d in self.declarations[f.uid]:
            if 'DYNAMIC' in d.flags:
                scope[d.name] = d.make()
            if 'REF' in d.flags:
                scope[d.name] = None
        frame = Frame(
            f,
            scope,
            method=method,
            result='' if 'FUNCTIONS' in f.attributes else 0,
            call_site_location=self.location,
        )
        if len(self.frames) >= self.max_frames:
            raise EraError('Call-stack budget exceeded', code='E_LIMIT')
        self.frames.append(frame)
        try:
            self._bind_parameters(frame, declmap, captured)
        except BaseException:
            self.frames.pop()
            raise
        if self.journal:
            self.journal.enter(frame)
        return frame

    def function(self, name):
        fs = self.program.functions.get(name.upper())
        if not fs:
            raise EraError(f'Unknown function @{name}', code='E_FUNCTION')
        return fs[0]

    def call(self, name, values=None, optional=False):
        if name.upper() not in self.program.functions:
            if optional:
                return 0
            raise EraError(f'Unknown function @{name}', self.location, 'E_FUNCTION')
        f = self.function(name)
        depth = len(self.frames)
        frame = self._new_frame(f, [('lit', v) for v in (values or [])])
        self._run_until(depth)
        return frame.result

    def event(self, name):
        result = 0
        self._event_depth += 1
        try:
            for group in self.program.event_groups(name):
                for f in group:
                    depth = len(self.frames)
                    frame = self._new_frame(f)
                    self._run_until(depth)
                    result = frame.result
                    if 'SINGLE' in f.attributes and result == 1:
                        break
        finally:
            self._event_depth -= 1
        self.complete_begin()
        return result

    def complete_begin(self):
        # ProcessState.Return applies a pending BEGIN only at the outermost
        # return address. EVENTSHOP defers it through the autosave dispatch.
        if (
            self.pending_begin is not None
            and not self.frames
            and not self._event_depth
            and self.train_phase != 'EVENTSHOP'
        ):
            state, self.pending_begin = self.pending_begin, None
            raise FlowSignal(state)

    def call_expr(self, name, nodes):
        from .function_resolution import resolve_expression_method

        f = resolve_expression_method(self.program.functions, name, builtins.NAMES)
        if f is None:
            return builtins.call(self, name, nodes)
        if self.initializing_declarations:
            raise Unsupported(
                'User-defined functions in declaration initializers; only built-in expressions are supported'
            )
        if not f.attributes & {'FUNCTION', 'FUNCTIONS'}:
            raise EraError(f'@{name} is not #FUNCTION/#FUNCTIONS', code='E_FUNCTION')
        self.method_depth += 1
        depth = len(self.frames)
        try:
            if self.method_depth > 64:
                raise EraError(
                    'Expression-function nesting budget exceeded', code='E_LIMIT'
                )
            frame = self._new_frame(f, list(nodes), method=True)
            self._run_until(depth)
            return frame.result
        except BaseException:
            # _run_until has already captured the callee's position and stack.
            # Process.GetValue's finally releases private dynamic scope; never
            # restore the caller position on this exceptional path.
            self._unwind_frames(depth)
            raise
        finally:
            self.method_depth -= 1

    def _finish(self, values=None, method=False):
        frame = self.frames[-1]
        ismethod = bool(frame.function.attributes & {'FUNCTION', 'FUNCTIONS'})
        if method != ismethod:
            raise EraError(
                'RETURNF required in methods; RETURN required in normal functions',
                code='E_RETURN',
            )
        if method:
            value = (
                values[0]
                if values
                else '' if 'FUNCTIONS' in frame.function.attributes else 0
            )
            if isinstance(value, str) != ('FUNCTIONS' in frame.function.attributes):
                raise EraError('RETURNF type mismatch', code='E_TYPE')
        else:
            values = values or [0]
            for i, v in enumerate(values):
                self.data.variables['RESULT'].set((i,), integer(v))
            value = values[0]
        frame.result = value
        frame.finished = True
        if hasattr(frame, 'tail_parent'):
            frame.tail_parent.result = value
            frame.tail_parent.finished = True
        while frame.skip_marks:
            self.console.skip_print = frame.skip_marks.pop()
        self.frames.pop()
        # Process.State.Return/ReturnF restore the saved return address only on
        # successful return. Exceptions inside the callee keep its instruction.
        self.location = frame.call_site_location
        self.complete_begin()

    def _run_until(self, depth):
        """Run frames to depth, capturing ERB diagnostics before unwinding.

        Advance PC before ticking/journaling/execution. EraError uses the
        advanced PC for its stack; unexpected Python errors use the recorded
        instruction location. Restore the caller location only after success.
        """
        return_location = self.location
        try:
            while len(self.frames) > depth:
                frame = self.frames[-1]
                if not frame.entry_checked:
                    frame.entry_checked = True
                    entry_error = getattr(frame.function, 'entry_error', None)
                    if entry_error is not None:
                        raise EraError(
                            entry_error.message,
                            entry_error.location,
                            entry_error.code,
                            diagnostic_message=entry_error.diagnostic_message,
                        )
                if frame.pc >= len(frame.function.code):
                    # Source NullLine / next function label -> ReturnF(null)
                    # in a method: default 0/empty string, preserving RESULT.
                    self._finish(
                        method=bool(
                            frame.function.attributes & {'FUNCTION', 'FUNCTIONS'}
                        )
                    )
                    continue
                ins = frame.function.code[frame.pc]
                pc = frame.pc
                frame.pc += 1
                frame.instruction_location = ins.location
                self.location = ins.location
                self.tick()
                if self.journal:
                    self.journal.instruction(frame, ins)
                if ins.argument_error is not None:
                    if skip_search_error(frame, ins):
                        continue
                    # ArgumentParser marks the line, not the whole game, as
                    # erroneous.  Entering it later raises before side effects.
                    error = ins.argument_error
                    raise EraError(
                        error.message,
                        ins.location,
                        error.code,
                        diagnostic_message=error.diagnostic_message,
                    )
                self.execute(frame, ins, pc)
        except EraError as e:
            if e.location is None:
                e.location = self.location
            if not e.era_stack:
                e.era_stack = [
                    {
                        'function': f.function.name,
                        'file': f.function.location.path,
                        'line': (
                            f.function.code[
                                max(0, min(f.pc - 1, len(f.function.code) - 1))
                            ].location.line
                            if f.function.code
                            else f.function.location.line
                        ),
                    }
                    for f in self.frames[-32:]
                ]
            raise
        except (FlowSignal, QuitSignal, TrainRequest):
            raise
        except Exception as e:
            err = InternalError(e, self.location)
            err.era_stack = [
                {
                    'function': f.function.name,
                    'file': f.function.location.path,
                    'line': (
                        f.instruction_location.line
                        if f.instruction_location
                        else f.function.location.line
                    ),
                }
                for f in self.frames[-32:]
            ]
            raise err from e
        else:
            # Also covers host-level calls/events with no remaining caller frame.
            self.location = return_location

    def _end_loop(self, frame, start):
        loop = frame.loops.pop(start, None)
        # COUNT is the ordinary shared counter. It is not restored after a REPEAT.

    def _case(self, value, text):
        from .text import split_case_args

        for condition in split_case_args(text):
            plan = parse_case_condition(self.program.expand(condition))
            if plan[0] == 'is':
                if apply_binary(plan[1], value, self.eval_node(plan[2])):
                    return True
            elif plan[0] == 'range':
                if apply_binary('<=', self.eval_node(plan[1]), value) and apply_binary(
                    '<=', value, self.eval_node(plan[2])
                ):
                    return True
            elif apply_binary('==', value, self.eval_node(plan[1])):
                return True
        return False

    def _call_instruction(self, frame, op, text, jump=-1):
        from .call_syntax import parse_call, is_statement_call

        form = 'FORM' in op
        expanded = text if form else self.program.expand(text)
        if is_statement_call(op):

            def bind_subname(node):
                # Only invalid identifier subnames need descriptor binding.
                # Normal CALL arguments retain their existing evaluation path.
                from .load_arguments import StaticContext

                return StaticContext(self, frame.function).infer(node)

            syntax = parse_call(expanded, form, bind_subname)
            name = (
                (self.format(syntax.target) if form else syntax.target).strip().upper()
            )
            nodes = [
                parse(self.program.expand(term)) if term else ('missing',)
                for term in syntax.arguments
            ]
        else:
            parts = split_dynamic_call(text) if form else split_args(expanded)
            if not parts:
                raise EraError('Missing call target', code='E_ARGUMENT')
            name = (self.format(parts[0]) if form else parts[0]).strip().upper()
            nodes = [
                parse(self.program.expand(term)) if term else ('missing',)
                for term in parts[1:]
            ]
        isgoto = 'GOTO' in op
        exists = name in (frame.function.labels if isgoto else self.program.functions)
        if not exists:
            if op.startswith('TRY'):
                if jump >= 0:
                    frame.pc = jump
                return False
            raise EraError(
                f'Unknown {"label $" if isgoto else "function @"}{name}',
                code='E_FUNCTION',
                diagnostic_message=(
                    None
                    if isgoto
                    else ('式中関数' if op.endswith('F') else '関数')
                    + '"@'
                    + name
                    + '"が見つかりません'
                ),
            )
        if isgoto:
            if nodes:
                raise EraError('GOTO does not take arguments', code='E_ARGUMENT')
            frame.pc = frame.function.labels[name]
            return True
        iscallf = op.endswith('F')
        f = self.function(name)
        ismethod = bool(f.attributes & {'FUNCTION', 'FUNCTIONS'})
        if iscallf:
            if not ismethod:
                raise EraError('CALLF requires #FUNCTION/#FUNCTIONS', code='E_FUNCTION')
            self.call_expr(name, nodes)
            return True
        if ismethod:
            raise EraError('Use CALLF for #FUNCTION/#FUNCTIONS', code='E_FUNCTION')
        child = self._new_frame(f, nodes)
        if 'JUMP' in op:
            # Tail call: transfer the result back to the same caller.
            frame.finished = True
            # Carry the lexical display guard to the tail-called frame so it is
            # restored when that logical call returns, not lost on JUMP.
            child.skip_marks[:0] = frame.skip_marks
            frame.skip_marks = []
            del self.frames[-2]
            child.tail_parent = getattr(frame, 'tail_parent', frame)
            child.call_site_location = frame.call_site_location
        return True

    def _assignment(self, text):
        plan = self._assignment_cache.get(text)
        if plan is None:
            raw = text.rstrip()
            if raw.startswith(('++', '--')):
                node = self.expression_node(raw)
                if node[0] != 'inc':
                    raise EraError('Invalid prefix assignment', code='E_SYNTAX')
                plan = ['inc', node, None, None]
            elif raw.endswith(('++', '--')) and find_assignment(raw) is None:
                plan = [
                    'post',
                    self.expression_node(raw[:-2]),
                    1 if raw.endswith('++') else -1,
                    None,
                ]
            else:
                found = find_assignment(raw)
                if not found:
                    raise EraError('Invalid assignment', code='E_SYNTAX')
                lhs, op, rhs = found
                plan = [op, self.expression_node(lhs), rhs, None]
            if len(self._assignment_cache) >= 65536:
                self._assignment_cache.clear()
            self._assignment_cache[text] = plan
        op, lhs, rhs, nodes = plan
        if op == 'inc':
            self.eval_node(lhs)
            return
        if op == 'post':
            ref = self.ref_node(lhs)
            ref.set(i64(integer(ref.get()) + rhs))
            return
        # SP_SET knows the destination's type without evaluating its indices.
        # SET_Instruction evaluates its source term before SetValue resolves LHS.
        if lhs[0] != 'var':
            raise EraError('Expected a variable reference', code='E_REFERENCE')
        variable = self.lookup(lhs[1])
        if op == '=' and variable.string:
            value = self.format(rhs)
            self.ref_node(lhs).set(value)
            return
        if op in ('=', "'="):
            if nodes is None:
                nodes = tuple(split_args(rhs))
                plan[3] = nodes
            if len(nodes) == 1:
                value = self.eval(nodes[0])
                ref = self.ref_node(lhs)
                ref.variable.validate(ref.key)
                if ref.variable.readonly or ref.variable.string != isinstance(
                    value, str
                ):
                    raise EraError(
                        'Invalid assignment type/readonly destination', code='E_TYPE'
                    )
                ref.set(value)
                return
            vals = [self.eval(x) for x in nodes]
            ref = self.ref_node(lhs)
            refs = [ref.shifted(i) if i else ref for i in range(len(vals))]
            for rr, value in zip(refs, vals):
                if rr.variable.readonly or rr.variable.string != isinstance(value, str):
                    raise EraError(
                        'Invalid assignment type/readonly destination', code='E_TYPE'
                    )
            # VariableToken.SetValue(array) writes sequentially. If a later
            # element exceeds the array, earlier writes survive the exception.
            from .array_diagnostics import write_many

            write_many(refs, vals)
        else:
            source = self.expression_node(rhs)
            if not variable.string and op in ('+=', '-='):
                from .assignment1824 import restructure

                source = restructure(source, self)
                if source[0] == 'lit':
                    # ArgumentBuilder AddConst -> VariableTerm.PlusValue: one
                    # index resolution shared by the read and write.
                    delta = integer(source[1])
                    delta = delta if op == '+=' else i64(-delta)
                    ref = self.ref_node(lhs)
                    ref.set(i64(integer(ref.get()) + delta))
                    return
            # All other compound paths are lowered to a binary source term.
            # Its read resolves LHS once; SetValue resolves it again afterward.
            # / and % retain OperatorMethod's RHS-first/zero-check behavior.
            value = self.eval_node(('binary', op[:-1], lhs, source))
            self.ref_node(lhs).set(value)

    def _execute_loop(self, frame, ins, pc):
        """Execute compiler loop primitives; mutate counters before control PC.

        FOR resolves its destination before start/end/step. REPEAT reads shared
        COUNT before evaluating its bound. BREAK increments the active counter;
        ending a loop does not restore COUNT. Int64 step wrapping is preserved.
        """
        op, arg = ins.op, ins.arg
        if op in {'_FOR', '_REPEAT'}:
            if op == '_FOR':
                args = self._loop_cache.get(arg)
                if args is None:
                    parts = split_args(arg)
                    if not 3 <= len(parts) <= 4:
                        raise EraError(
                            'FOR variable, start, end [,step]', code='E_ARGUMENT'
                        )
                    args = tuple(parts)
                    self._loop_cache[arg] = args
                ref = self.ref(args[0])
                start = integer(self.eval(args[1]))
                end = integer(self.eval(args[2]))
                step = integer(self.eval(args[3])) if len(args) > 3 else 1
                old = 0
                kind = 'for'
            else:
                ref = self.ref('COUNT')
                old = ref.get()
                start = 0
                end = integer(self.eval(arg))
                step = 1
                kind = 'repeat'
            if step == 0:
                raise EraError('FOR step cannot be zero', code='E_ARGUMENT')
            ref.set(start)
            frame.loops[pc] = {
                'ref': ref,
                'end': end,
                'step': step,
                'old': old,
                'kind': kind,
            }
            if (step > 0 and start >= end) or (step < 0 and start <= end):
                self._end_loop(frame, pc)
                frame.pc = ins.jump
            return
        if op == '_STEP':
            loop = frame.loops.get(ins.data)
            if loop is None:
                raise EraError('Jump entered an inactive loop', code='E_CONTROL')
            v = i64(loop['ref'].get() + loop['step'])
            loop['ref'].set(v)
            if (loop['step'] > 0 and v < loop['end']) or (
                loop['step'] < 0 and v > loop['end']
            ):
                frame.pc = ins.jump
            else:
                self._end_loop(frame, ins.data)
            return
        if op == '_BREAK':
            loop = frame.loops.get(ins.data)
            if loop:
                loop['ref'].set(i64(loop['ref'].get() + loop['step']))
            self._end_loop(frame, ins.data)
            frame.pc = ins.jump
            return
        if op == '_DO':
            return
        if op == '_LOOP':
            if integer(self.eval(arg)):
                frame.pc = ins.jump
            return

    def execute(self, frame, ins, pc):
        op, arg = ins.op, ins.arg
        if frame.method:
            spec = COMMAND_SPECS.get(op)
            if spec and spec.get('method_safe') is False:
                raise EraError(
                    'This command is not method-safe in src1824 (#FUNCTION/#FUNCTIONS)',
                    code='E_METHOD_CONTEXT',
                )
            if op == '_DATA' and SYNTAX_SPECS[ins.data[0]].get('wait'):
                raise EraError(
                    'Data-print wait is not permitted inside a method',
                    code='E_METHOD_CONTEXT',
                )
        if op == '_ASSIGN':
            self._assignment(arg)
            return
        if op == '_IF':
            if not integer(self.eval(arg)):
                frame.pc = ins.jump
            return
        if op == '_JMP':
            frame.pc = exit_target(frame, ins)
            return
        if op in {'_FOR', '_REPEAT', '_STEP', '_BREAK', '_DO', '_LOOP'}:
            self._execute_loop(frame, ins, pc)
            return
        if op == '_SELECT':
            frame.selects[pc] = self.eval(arg)
            frame.select_searches.add(pc)
            return
        if op == '_CASE':
            case_match(self, frame, ins, pc)
            return
        if op == '_ENDSELECT':
            frame.selects.pop(ins.data, None)
            frame.select_searches.discard(ins.data)
            return
        if op == '_DATA':
            if self.console.skip_print and ins.data[0].startswith('PRINT'):
                return
            source, alternatives = ins.data
            if not alternatives:
                return
            n = self.rng.randrange(len(alternatives))
            if arg and not source.startswith('STRDATA'):
                self.ref(arg).set(n)
            lines = [
                self.format(s) if o == 'DATAFORM' else s for o, s in alternatives[n]
            ]
            if source.startswith('STRDATA'):
                self.ref(arg or 'RESULTS').set('\n'.join(lines))
            else:
                from .printing import output_data

                output_data(self, SYNTAX_SPECS[source], lines)
            return
        if op == '_TRYLIST':
            callop = {
                'TRYCALLLIST': 'TRYCALLFORM',
                'TRYJUMPLIST': 'TRYJUMPFORM',
                'TRYGOTOLIST': 'TRYGOTOFORM',
            }[arg]
            for choice in ins.data:
                if self._call_instruction(frame, callop, choice):
                    break
            return
        if op in CALL_OPS:
            self._call_instruction(frame, op, arg, ins.jump)
            return
        if op == 'CALLEVENT':
            self.event(self.program.expand(arg).strip())
            return
        if op in {'RETURN', 'RETURNFORM', 'RETURNF'}:
            text = self.format(arg) if op == 'RETURNFORM' else arg
            values = self.args(text)
            if op == 'RETURNF' and len(values) > 1:
                raise EraError('RETURNF takes one value', code='E_ARGUMENT')
            self._finish(values, op == 'RETURNF')
            return
        if op == 'RESTART':
            for k in list(frame.loops):
                self._end_loop(frame, k)
            frame.pc = 0
            frame.selects.clear()
            return
        if op == 'BEGIN':
            from .flow import request_begin

            request_begin(self, self.program.expand(arg).strip())
            return
        if op == 'QUIT':
            raise QuitSignal()
        if op == 'THROW':
            raise EraError(self.format(arg), code='E_SCRIPT')
        if op == 'ASSERT':
            if not self.program.debug:
                return
            if not integer(self.eval(arg)):
                raise EraError('ASSERT failed: ' + arg, code='E_ASSERT')
            return
        # Commands are kept separately so the VM/control layer remains auditable.
        from .dispatcher import execute

        if execute(self, op, arg):
            return
        raise Unsupported(f'Command {op}', ins.location)

    def reset(self, global_only=False):
        for name, var in self.data.variables.items():
            if var.global_save != global_only or var.readonly:
                continue
            var.values = copy.deepcopy(self.initial[name].values)
        if not global_only:
            self.data.character_count = 0
            for uid, vs in self.static.items():
                for n, v in vs.items():
                    v.values = copy.deepcopy(self.static_initial[uid][n].values)
            for fn, vs in self.legacy.items():
                for n, v in vs.items():
                    v.values = copy.deepcopy(self.legacy_initial[fn][n].values)

    def _unwind_frames(self, depth):
        for frame in reversed(self.frames[depth:]):
            while frame.skip_marks:
                self.console.skip_print = frame.skip_marks.pop()
        del self.frames[depth:]

    def clear_frames(self):
        self._unwind_frames(0)

    def run(self, entry=None):
        from .load_arguments import display_diagnostics

        display_diagnostics(self)
        from .flow import run_flow

        self.exit_reason = 'running'
        try:
            from .load_registration import require_executable

            require_executable(self)
            if entry:
                try:
                    self.call(entry)
                except FlowSignal as signal:
                    self.clear_frames()
                    run_flow(self, signal.state)
            else:
                run_flow(self)
            self.exit_reason = 'returned'
        except QuitSignal:
            self.exit_reason = 'quit'
        except BaseException:
            self.exit_reason = 'error'
            raise
        finally:
            self.clear_frames()
