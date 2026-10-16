"""Optional non-executing argument parsing, using the shared expression AST.

v24 ArgumentParser.SetArgumentTo marks failed lines and collects Lv2 warnings;
Process.ScriptProc rejects such a line if it is reached.  This layer never
calls evaluate(), resolves a dynamic reference, or folds an effectful value.
Uncovered handler-specific contracts are recorded, not claimed as checked.
"""

from importlib.resources import files
import json
from pathlib import Path
from types import SimpleNamespace
import re
from .errors import EraError, LoadDiagnostic
from .expr import parse, BP, parse_case_condition
from .program import command
from .registry import FUNCTION_SPECS, command_spec
from .text import split_args, split_printv, find_assignment, split_case_args

TYPE_CONTRACTS = json.loads(
    files('pyemuera')
    .joinpath('specs/argument_types_v24.json')
    .read_text(encoding='utf-8')
)['functions']
INT, STR = 'Int64', 'string'
TYPE_NAMES = {INT: '数値型', STR: '文字列型', None: '不定型'}
COMPARISONS = frozenset(('==', '!=', '<', '>', '<=', '>='))


class StaticContext:
    def __init__(self, vm, function):
        self.vm, self.function = vm, function
        self.types = {n: STR if v.string else INT for n, v in vm.data.variables.items()}
        self.types.update(
            {
                n: STR if v.string else INT
                for n, v in vm.legacy.get(function.name, {}).items()
            }
        )
        self.types.update(
            {
                d.name: STR if d.string else INT
                for d in vm.declarations.get(function.uid, [])
            }
        )
        self.types.update(
            {
                n: INT
                for n in (
                    'RAND',
                    'CHARANUM',
                    'LINECOUNT',
                    '__INT_MAX__',
                    '__INT_MIN__',
                    '__LINE__',
                    'PRINTCPERLINE',
                    'PRINTCLENGTH',
                )
            }
        )
        self.types.update({n: STR for n in ('__FILE__', '__FUNCTION__')})
        self.plans = []
        from .constant_ast import Reducer

        methods = getattr(vm.program, 'load_form_methods', None)
        if methods is not None:
            methods = dict(methods)
            # VarsizeMethod has UniqueRestructure: private lengths are
            # descriptor metadata, while REF lengths remain runtime values.
            # Its generic literal adapter would call VM.lookup outside the
            # private function's frame during load analysis.
            methods.pop('VARSIZE', None)

        def resolver(node):
            return self.static_variable(node)

        resolver.call = self.static_method
        self.reducer = Reducer(
            vm.program.functions, methods=methods, constant_resolver=resolver
        )
        self.runtime = False
        self.line = None

    def reduce(self, node):
        if self.vm.program.analysis_mode:
            node = _analysis_null_terms(
                node, self.vm.program.analysis_expression_missing
            )
        return self.reducer.reduce(node)

    def descriptor(self, name):
        if name in ('__INT_MAX__', '__INT_MIN__'):
            return SimpleNamespace(readonly=True)
        for declaration in self.vm.declarations.get(self.function.uid, []):
            if declaration.name == name:
                variable = self.vm.static.get(self.function.uid, {}).get(name)
                if variable is not None:
                    return variable
                return SimpleNamespace(
                    readonly='CONST' in declaration.flags,
                    dims=declaration.dims,
                    string=declaration.string,
                    character='CHARADATA' in declaration.flags,
                    reference='REF' in declaration.flags,
                )
        if '@' in name:
            base, owner = name.split('@', 1)
            return self.vm.legacy.get(owner, {}).get(base)
        return self.vm.legacy.get(self.function.name, {}).get(
            name
        ) or self.vm.data.variables.get(name)

    def static_variable(self, node):
        """VariableTerm.Restructure: check constant axes without live values.

        Mutable indices, TARGET, REF bindings and character registration are
        runtime state. Only literal/constant indices and immutable storage are
        eligible here; no VM.eval, ref_node, RNG or user method is called.
        """
        name, indices = node[1:]
        if name in ('__INT_MAX__', '__INT_MIN__') and not indices:
            return ('lit', (1 << 63) - 1 if name == '__INT_MAX__' else -(1 << 63))
        descriptor = self.descriptor(name)
        dims = getattr(descriptor, 'dims', None)
        if dims is None:
            return None
        declaration = next(
            (
                d
                for d in self.vm.declarations.get(self.function.uid, [])
                if d.name == name
            ),
            None,
        )
        if getattr(descriptor, 'reference', False) or (
            declaration is not None and 'REF' in declaration.flags
        ):
            return None
        character = getattr(descriptor, 'character', False)
        implicit = bool(character and len(indices) <= len(dims))
        values = [None] if implicit else []
        for position, index in enumerate(indices):
            axis = position + implicit
            if index[0] == 'lit':
                value = index[1]
                if isinstance(value, str):
                    value = self.vm.data.index_of(name, value, axis)
                values.append(value)
            elif index[0] == 'var' and not index[2] and index[1] not in self.types:
                values.append(self.vm.data.index_of(name, index[1], axis))
            else:
                values.append(None)
        sizes = (None,) + tuple(dims) if character else tuple(dims)
        if len(values) > len(sizes):
            raise EraError(f'{name}: too many array indices', code='E_INDEX')
        values.extend((0,) * (len(sizes) - len(values)))
        for axis, (value, size) in enumerate(zip(values, sizes)):
            # Native deliberately excludes ARG/ARGS (resized by signatures)
            # and character axis 0 from the static CheckElement mask.
            if (
                name.split('@', 1)[0] in ('ARG', 'ARGS')
                or size is None
                or value is None
            ):
                continue
            if not isinstance(value, int):
                continue
            if value < 0 or value >= size:
                from .data import Variable

                diagnostic = (
                    descriptor.index_diagnostic(axis, value)
                    if hasattr(descriptor, 'index_diagnostic')
                    else Variable(
                        name, tuple(dims), character=character
                    ).index_diagnostic(axis, value)
                )
                raise EraError(
                    f'{name}: constant array index {value} outside axis {axis}',
                    code='E_INDEX',
                    diagnostic_message=diagnostic,
                )
        if (
            getattr(descriptor, 'readonly', False)
            and not character
            and all(isinstance(x, int) for x in values)
        ):
            stored = getattr(descriptor, 'values', None)
            if stored is not None:
                return ('lit', stored.get(tuple(values), descriptor.default))
        return None

    def static_method(self, node, reducer):
        """Metadata-only VarsizeMethod.UniqueRestructure, without scope reads."""
        if node[1] != 'VARSIZE':
            return None
        args = node[2]
        # Native checks child restructuring but does not assign its returned
        # replacement. Only originally SingleTerm operands allow folding.
        for child in args:
            reducer.reduce(child)
        if not args or args[0][0] != 'lit' or not isinstance(args[0][1], str):
            return node
        if len(args) > 1 and (args[1][0] != 'lit' or not isinstance(args[1][1], int)):
            return node
        name = args[0][1].upper()
        descriptor = self.descriptor(name)
        declaration = next(
            (
                d
                for d in self.vm.declarations.get(self.function.uid, [])
                if d.name == name
            ),
            None,
        )
        if (
            descriptor is None
            or getattr(descriptor, 'reference', False)
            or (declaration is not None and 'REF' in declaration.flags)
        ):
            return node
        dims = getattr(descriptor, 'dims', None)
        if dims is None:
            return node
        dims = dims or (1,)
        axis = args[1][1] if len(args) > 1 else 0
        if axis < 0 or axis >= len(dims):
            raise EraError('VARSIZE axis outside rank', code='E_INDEX')
        return ('lit', dims[axis])

    def warning(self, level, message, category):
        if self.runtime:
            # v24 queues ParserMediator warnings; only loader flushes display them.
            # Lazy runtime ArgumentParser does not flush its warning queue.
            return
        if self.line is not None:
            source = self.vm.program.original_source[self.line.location.path][
                self.line.location.line - 1
            ]
            diagnostic = LoadDiagnostic(
                level,
                category,
                self.line.location,
                source,
                message,
                len(self.vm.program.argument_diagnostics),
            )
            self.vm.program.argument_diagnostics.append(diagnostic)
            events = getattr(self.vm.program, 'load_diagnostic_events', None)
            if events is not None:
                events.append(diagnostic)

    def expression(self, text, expected=None):
        expanded = self.vm.program.expand(text)
        try:
            node = parse(expanded)
        except EraError as exc:
            if exc.code == 'E_SYNTAX' and exc.diagnostic_message is None:
                raise EraError('式が異常です', code='E_SYNTAX') from exc
            raise
        actual = self.infer(node)
        self.require(actual, expected)
        node = self.reduce(node)
        self.plans.append((expanded, node))
        return actual

    @staticmethod
    def require(actual, expected):
        if actual is not None and expected is not None and actual != expected:
            message = (
                '式の結果が数値ではありません'
                if expected == INT
                else '式の結果が文字列ではありません'
            )
            raise EraError(message, code='E_TYPE')

    def infer(self, node):
        kind = node[0]
        if kind == 'missing':
            return None
        if kind == 'lit':
            return STR if isinstance(node[1], str) else INT
        if kind == 'form':
            self.form(node[1])
            return STR
        if kind == 'var':
            name, indices = node[1:]
            if name not in self.types:
                # Function-qualified legacy variables have a statically known
                # descriptor, while the value remains a runtime lookup.
                if '@' in name:
                    base, owner = name.split('@', 1)
                    variable = self.vm.legacy.get(owner, {}).get(base)
                    if variable is not None:
                        actual = STR if variable.string else INT
                    else:
                        raise EraError(
                            '"' + name + '"は解釈できない識別子です', code='E_VARIABLE'
                        )
                else:
                    raise EraError(
                        '"' + name + '"は解釈できない識別子です', code='E_VARIABLE'
                    )
            else:
                actual = self.types[name]
            for index in indices:
                if index[0] == 'var' and not index[2] and index[1] not in self.types:
                    # CSV keyword lookup is descriptor metadata, not evaluation.
                    try:
                        self.vm.data.keyword_number(name, index[1])
                    except EraError:
                        self.require(self.infer(index), INT)
                else:
                    # VariableParser wraps string indexes in VariableStrArgTerm.
                    # Its CSV-key conversion is a runtime decision for dynamic
                    # strings; do not evaluate ARGS or a string method here.
                    actual_index = self.infer(index)
                    if actual_index not in (None, INT, STR):
                        self.require(actual_index, INT)
            return actual
        if kind in ('unary', 'inc'):
            child = node[2] if kind == 'unary' else node[1]
            self.require(self.infer(child), INT)
            return INT
        if kind == 'binary':
            left, right = self.infer(node[2]), self.infer(node[3])
            if left is None or right is None:
                return None
            op = node[1]
            if left == right == INT:
                return INT
            if left == right == STR and op in COMPARISONS | {'+'}:
                return STR if op == '+' else INT
            if {left, right} == {INT, STR} and op == '*':
                return STR
            message = (
                TYPE_NAMES[left]
                + 'と'
                + TYPE_NAMES[right]
                + "の演算に二項演算子'"
                + op
                + "'は適用できません"
            )
            raise EraError(message, code='E_TYPE')
        if kind == 'ternary':
            self.require(self.infer(node[1]), INT)
            yes, no = self.infer(node[2]), self.infer(node[3])
            if yes is not None and no is not None and yes != no:
                raise EraError('三項演算子の使用法が不正です', code='E_TYPE')
            return yes if yes == no else None
        if kind == 'call':
            name, args = node[1:]
            from .function_resolution import resolve_expression_method

            try:
                fn = resolve_expression_method(
                    self.vm.program.functions, name, FUNCTION_SPECS
                )
            except EraError as exc:
                if (
                    self.vm.program.analysis_mode
                    and name not in self.vm.program.functions
                ):
                    # ExpressionParser first parses child terms, then substitutes
                    # an unresolved method with NullTerm(0), without executing it.
                    for child in args:
                        self.infer(child)
                    counts = self.vm.program.analysis_expression_missing
                    counts[name] = counts.get(name, 0) + 1
                    return INT
                from .registry import COMMAND_SPECS

                if name in COMMAND_SPECS and name not in self.vm.program.functions:
                    raise
                if name not in self.vm.program.functions:
                    raise EraError(
                        '"' + name + '"は解釈できない識別子です', code='E_FUNCTION'
                    ) from exc
                raise EraError(
                    '@' + name + 'は式中で呼び出せる関数ではありません',
                    code='E_FUNCTION',
                ) from exc
            if fn is None:
                spec = FUNCTION_SPECS[name]
                from .expression_arguments import (
                    check_count,
                    check_type,
                    check_homogeneous,
                    check_array_descriptor,
                )

                # ExpressionParser resolves nested operands before the method's
                # CheckArgumentType, and Restructure happens only afterwards.
                actuals = [self.infer(child) for child in args]
                check_count(name, spec, args)
                if not spec['min_args'] <= len(args) <= spec['max_args']:
                    raise EraError(name + '関数の引数の数が不正です', code='E_ARGUMENT')
                contract = TYPE_CONTRACTS.get(name, {})
                expected = contract.get('fixed_parameter_types', [])
                check_homogeneous(name, actuals, args)
                check_array_descriptor(name, actuals, args, self)
                from .custom_function_arguments import validate as validate_custom

                validate_custom(name, actuals, args, self)
                for i, child in enumerate(args):
                    actual = actuals[i]
                    if spec.get('argument_diagnostic_policy') or name == 'MONEYSTR':
                        check_type(name, spec, i, actual, child)
                    elif i < len(expected) and expected[i] in (INT, STR):
                        self.require(actual, expected[i])
                return contract.get('return_type')
            if len(args) > len(fn.parameters):
                raise EraError(f'@{name}: too many arguments', code='E_ARGUMENT')
            # Inspect callee descriptors; no callee frame, value/default evaluation.
            from .function_resolution import parameter_type

            for parameter, child in zip(fn.parameters, args):
                assignment = find_assignment(parameter)
                lhs = assignment[0] if assignment else parameter
                target = parse(lhs)
                actual = self.infer(child)
                expected = parameter_type(self.vm, fn, target)
                if (
                    actual == INT
                    and expected == STR
                    and self.vm.program.config.get(
                        'ユーザー関数の引数に自動的にTOSTRを補完する', 'NO'
                    ).upper()
                    == 'YES'
                ):
                    continue
                self.require(actual, expected)
            return STR if 'FUNCTIONS' in fn.attributes else INT
        raise EraError('Unsupported static AST ' + kind, code='E_UNSUPPORTED')

    def form(self, text):
        from .formatting import form_components, type_error

        for expression, expected, role in form_components(text):
            actual = self.expression(expression)
            if actual is not None and actual != expected and role in ('{', '%'):
                raise EraError(type_error(role), code='E_TYPE')
            self.require(actual, expected)

    def assignment(self, text):
        if text.startswith(('++', '--')) or text.rstrip().endswith(('++', '--')):
            # Statement postfix syntax binds to the whole lvalue. Parsing
            # A:1++ as an expression would increment the index literal instead.
            target = text[2:] if text.startswith(('++', '--')) else text.rstrip()[:-2]
            self.expression(target.strip(), INT)
            return
        found = find_assignment(text, legacy=True)
        if not found:
            raise EraError('代入文が不正です', code='E_SYNTAX')
        lhs, op, rhs = found
        target = self.expression(lhs)
        if target == STR and op in ('=', '=='):
            self.form(rhs)
            return
        for value in split_args(rhs):
            actual = self.expression(value)
            if op in ('=', '==', "'="):
                self.require(actual, target)
            elif target is not None and actual is not None:
                self.infer(
                    (
                        'binary',
                        op[:-1],
                        ('lit', '' if target == STR else 0),
                        ('lit', '' if actual == STR else 0),
                    )
                )

    def statement(self, op, arg):
        if op in ('REF', 'REFBYNAME'):
            # v24 SP_REF_ArgumentBuilder's first condition requires both an
            # IdentifierWord and Type==','; ordinary declared REF forms fail
            # here before name binding. DoInstruction is also NotImplCodeEE.
            raise EraError(op + '命令:書式が間違っています', code='E_ARGUMENT')
        if op == 'RETURNF' and not arg.strip(' \t\u3000'):
            from .load_reachability import method_roots

            if self.function.uid in {
                function.uid for function in method_roots(self.vm.program)
            }:
                # Native EXPRESSION_NULLABLE accepts an absent return operand.
                return 'syntax_and_known_types_checked'
        spec = command_spec(op) or {}
        if op == '_ASSIGN':
            self.assignment(arg)
        elif op in (
            'IF',
            'ELSEIF',
            'SIF',
            'WHILE',
            'REPEAT',
            'LOOP',
            'ASSERT',
            'SKIPDISP',
        ):
            self.expression(arg, INT)
        elif op in ('SELECTCASE', 'RETURNF'):
            self.expression(
                arg,
                (
                    STR
                    if op == 'RETURNF' and 'FUNCTIONS' in self.function.attributes
                    else (
                        INT
                        if op == 'RETURNF' and 'FUNCTION' in self.function.attributes
                        else None
                    )
                ),
            )
        elif op == 'FOR':
            for part in split_args(arg):
                self.expression(part, INT)
        elif op == 'CASE':
            for part in split_case_args(arg):
                condition = parse_case_condition(self.vm.program.expand(part))
                nodes = condition[2:] if condition[0] == 'is' else condition[1:]
                for node in nodes:
                    self.infer(node)
                    self.reduce(node)
        elif op in ('SETCOLORBYNAME', 'SETBGCOLORBYNAME'):
            from .display_contracts import color_name

            color_name(self.vm, op, arg)
        elif spec.get('family') == 'print':
            mode = spec['argument_mode']
            if mode == 'values':
                for literal, value in split_printv(arg):
                    if not literal:
                        self.expression(value)
            elif mode in ('string', 'string_form'):
                self.expression(arg, STR)
            elif mode in ('form', 'button_form'):
                self.form(arg)
            elif mode == 'bar':
                parts = split_args(arg)
                if len(parts) < 3:
                    raise EraError('引数が設定されていません', code='E_ARGUMENT')
                for value in parts:
                    self.expression(value, INT)
                if len(parts) > 3:
                    self.warning(1, op + '命令:引数が多すぎます', 'excess_arguments')
            elif mode == 'raw':
                return 'raw_text'
            else:
                return 'handler_contract_pending'
        elif 'FORM' in op and spec.get('family') == 'call':
            # The function name is FORM data. Its substitutions are parsed,
            # but its target and REF/ARG binding remain runtime decisions.
            self.form(split_args(arg)[0])
            return 'dynamic_target_deferred'
        elif spec.get('family') == 'numeric_instruction':
            from .numeric_instructions import compile_instruction

            compile_instruction(self, spec, arg)
        elif op in FUNCTION_SPECS and not spec:
            self.expression(op + '(' + arg + ')')
        elif op in (
            'RETURN',
            'ADDCHARA',
            'DELCHARA',
            'SWAPCHARA',
            'COPYCHARA',
            'PICKUPCHARA',
        ):
            for part in split_args(arg):
                if part:
                    self.expression(part, INT)
        else:
            return 'handler_contract_pending'
        return 'syntax_and_known_types_checked'


def analysis_functions(program):
    """Compatibility entry point; reachability owns selection, not diagnostics."""
    from .load_reachability import select_functions

    return select_functions(program)


def compile_arguments(vm):
    program = vm.program
    program.argument_diagnostics = []
    program.analysis_expression_missing = {}
    program.uncalled_diagnostics = []
    program.load_diagnostic_events = []
    program.argument_coverage = []
    from .load_reachability import prepare_constants

    prepare_constants(vm)
    mode = program.config.get('ロード時に引数を解析する', 'NO').upper()
    if mode not in ('YES', 'NO'):
        program.argument_coverage.append(
            {
                'mode': mode,
                'status': 'config_policy_pending',
                'reason': 'ONCE update-key policy is not implemented',
            }
        )
    ordered, ignored, scope = analysis_functions(program)
    program.argument_analysis_scope = scope
    for fn in ignored:
        program.argument_coverage.append(
            {
                'function': fn.name,
                'status': 'ignored_uncalled_function',
                'trigger': 'IgnoreUncalledFunction:YES',
            }
        )
    from .load_reachability import method_roots

    method_uids = {function.uid for function in method_roots(program)}
    from .load_reachability import uncalled_functions, diagnostic_functions

    uncalled = uncalled_functions(program)
    uncalled_uids = {function.uid for function in uncalled}
    # Native checkScript checks called labels first, then registers each uncalled
    # header before checking that label's body. Keep this traversal order; the
    # projection must not sort by filename or warning category after filtering.
    selected = {function.uid: function for function in ordered}
    traversal = diagnostic_functions(program, ordered, uncalled)
    for fn in traversal:
        deferred_uncalled = None
        if fn.uid in uncalled_uids:
            source = program.original_source[fn.location.path][fn.location.line - 1]
            diagnostic = LoadDiagnostic(
                1,
                'uncalled_function',
                fn.location,
                source,
                '関数@' + fn.name + 'は定義されていますが一度も呼び出されません',
                len(program.load_diagnostic_events),
                phase='uncalled-function',
            )
            program.uncalled_diagnostics.append(diagnostic)
            if getattr(program, 'analysis_driver', False):
                # Analysis checkScript parses this body before its FNC warning.
                deferred_uncalled = diagnostic
            else:
                program.load_diagnostic_events.append(diagnostic)
        if fn.uid not in selected:
            # Embedding APIs may deliberately call a non-system entry. Preserve
            # that default adaptation unless ignoreYES is explicitly requested.
            if (
                getattr(program, 'strict_uncalled_guard', False)
                or program.config.get('呼び出されなかった関数を無視する', '').upper()
                == 'YES'
            ):
                _guard_uncalled_entry(program, fn)
            continue
        context = StaticContext(vm, fn)
        instructions = {}
        for ins in fn.code:
            instructions.setdefault(ins.location, []).append(ins)
            if not any(d.location == ins.location for d in program.lexical_diagnostics):
                ins.argument_error = None
        for line in fn.lines:
            if line.text.startswith('$'):
                continue
            op, arg = command(line.text)
            context.line = line
            contract = command_spec(op) or {}
            if any(d.location == line.location for d in program.lexical_diagnostics):
                continue
            forced = contract.get('force_set_argument', False)
            unsafe_method = (
                fn.uid in method_uids and contract.get('method_safe') is False
            )
            if (
                not unsafe_method
                and mode != 'YES'
                and not program.analysis_mode
                and not forced
            ):
                continue
            before = len(context.plans)
            row = {
                'function': fn.name,
                'file': line.location.path,
                'line': line.location.line,
                'command': op,
                'trigger': (
                    'MethodContext'
                    if unsafe_method
                    else (
                        'AnalysisMode'
                        if program.analysis_mode
                        else 'config:YES' if mode == 'YES' else 'ForceSetArg'
                    )
                ),
                'force_set_argument': forced,
                'analysis_scope': scope,
            }
            try:
                if unsafe_method:
                    raise EraError(
                        op + '命令は#FUNCTION中で使うことはできません',
                        code='E_METHOD_CONTEXT',
                    )
                from .load_builders import dispatch
                from .command_arguments import check

                checked = check(context, op, arg, contract)
                row['status'] = checked or (
                    dispatch(context, op, arg, contract)
                    if contract.get('load_argument_contract')
                    else context.statement(op, arg)
                )
            except EraError as exc:
                if exc.code == 'E_UNSUPPORTED':
                    row.update(status='handler_contract_pending', reason=exc.message)
                else:
                    row['status'] = 'line_error_warning'
                    source = program.original_source[line.location.path][
                        line.location.line - 1
                    ]
                    diagnostic = LoadDiagnostic(
                        2,
                        exc.code,
                        line.location,
                        source,
                        exc.as_dict()['diagnostic_message'],
                        len(program.argument_diagnostics),
                        phase=(
                            'callf-resolution'
                            if getattr(exc, 'call_resolution', None) == 'callf'
                            else (
                                'call-resolution'
                                if getattr(exc, 'call_resolution', None) == 'call'
                                else 'load-time'
                            )
                        ),
                        internal_message=exc.message,
                    )
                    program.argument_diagnostics.append(diagnostic)
                    program.load_diagnostic_events.append(diagnostic)
                    # Native analysis-mode missing CALL records a name/count,
                    # without marking the line. CALLF still uses ParserMediator.
                    if not (
                        program.analysis_mode and diagnostic.phase == 'call-resolution'
                    ):
                        for ins in instructions.get(line.location, []):
                            ins.argument_error = exc
            plans = tuple(context.plans[before:])
            for ins in instructions.get(line.location, []):
                ins.argument_plan = plans
            program.argument_coverage.append(row)
        if deferred_uncalled is not None:
            program.load_diagnostic_events.append(deferred_uncalled)
        # Cache ASTs only. No operand values, scopes or variable references.
        for text, node in context.plans:
            vm._expression_cache[text] = node
    if not any(
        row.get('status') == 'call_terms_checked_dynamic_target'
        for row in program.argument_coverage
    ):
        for line in program.invalid_headers:
            source = program.original_source[line.location.path][line.location.line - 1]
            diagnostic = LoadDiagnostic(
                1,
                'uncalled_function',
                line.location,
                source,
                '関数@<Error>は定義されていますが一度も呼び出されません',
                len(program.load_diagnostic_events),
                phase='uncalled-function',
            )
            program.uncalled_diagnostics.append(diagnostic)
            program.load_diagnostic_events.append(diagnostic)


def _guard_uncalled_entry(program, function):
    """Mark the first represented logical line, without a new warning.

    ErbLoader ignores the body but prevents an unexpected later call, even if
    FNC warnings are hidden. Existing line errors win. Do not mark a later
    instruction when the first source line is a $label (IR has no label row).
    The VM checks the retained entry error before the first body instruction.
    """
    if not function.lines:
        return
    first = function.lines[0]
    instructions = [ins for ins in function.code if ins.location == first.location]
    if first.text.startswith('$'):
        function.entry_error = EraError(
            '呼び出されないはずの関数が呼ばれた', first.location, 'E_UNCALLED'
        )
        return
    # An unknown command is already a lexical/registration defect. Native
    # preserves its InvalidLine; do not replace it with the guard message.
    op, _ = command(first.text)
    if op != '_ASSIGN' and command_spec(op) is None:
        return
    for instruction in instructions:
        if instruction.argument_error is None:
            instruction.argument_error = EraError(
                '呼び出されないはずの関数が呼ばれた', first.location, 'E_UNCALLED'
            )


def display_diagnostics(vm):
    if vm._load_diagnostics_emitted:
        return
    vm._load_diagnostics_emitted = True
    program = vm.program
    from .startup import emit_startup

    emit_startup(vm.console, vm.data.settings, program.config)
    try:
        threshold = int(
            program.config.get(
                '表示する最低警告レベル', program.config.get('表示する警告レベル', '1')
            )
        )
    except ValueError:
        threshold = 1
    from .call_diagnostics import project_missing_calls

    arguments, summaries, policy = project_missing_calls(program, threshold)
    program.call_warning_projection = policy
    early = [
        d
        for d in [
            *vm.data.size_diagnostics,
            *program.lexical_diagnostics,
            *program.definition_diagnostics,
        ]
        if d.severity >= threshold or program.analysis_mode
    ]
    shown = [*early, *arguments]
    vm.emitted_diagnostics = [
        dict(d.as_dict(), display_order=i) for i, d in enumerate(shown)
    ]

    def emit(diagnostic):
        loc = diagnostic.location
        vm.console.write(
            f'警告Lv{diagnostic.severity}:{Path(loc.path).name}:{loc.line}行目:'
            + diagnostic.reference_message,
            newline=True,
        )
        vm.console.write(diagnostic.source_text, newline=True)

    for diagnostic in early:
        emit(diagnostic)
    # ErbLoader prints the ignored-count summary before flushing its warning list.
    for text in summaries:
        vm.console.write(text, newline=True)
    for diagnostic in arguments:
        emit(diagnostic)
    from .name_diagnostics import overload_notice_lines

    for text in overload_notice_lines(program):
        vm.console.write(text, newline=True)


def _analysis_null_terms(node, missing):
    """Native analysis placeholders are integer zero, never runnable callbacks."""
    if not isinstance(node, tuple):
        return node
    if node and node[0] == 'call' and node[1] in missing:
        return ('lit', 0)
    return tuple(_analysis_null_terms(child, missing) for child in node)
