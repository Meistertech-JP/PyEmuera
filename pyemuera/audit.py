"""Non-executing compatibility inventory. A clean scan is NOT gameplay certification."""

from collections import Counter
import re
from . import __version__, builtins
from .errors import EraError, Unsupported
from .expr import parse
from .program import command
from .runtime import supported_command, DISPLAY_OPS, CALL_OPS
from .registry import COMMAND_SPECS, SYNTAX_SPECS, command_spec
from .text import split_args, find_assignment, split_printv

COMPOUNDS = frozenset(SYNTAX_SPECS)
PARTIAL = (
    set(
        'TWAIT TINPUT TINPUTS SORTCHARA PRINTSINGLEFORM CALLTRAIN STOPCALLTRAIN NOSKIP ENDNOSKIP SKIPDISP MESSKIP MOUSESKIP HTML_PRINT HTML_TOPLAINTEXT CLEARLINE REUSELASTLINE ONEINPUT ONEINPUTS SAVEGAME LOADGAME SAVEDATA LOADDATA CHKDATA SAVEGLOBAL LOADGLOBAL PRINT_SHOPITEM PRINT_ITEMSHOP PRINT_ITEM PRINT_ABL PRINT_TALENT PRINT_MARK PRINT_EXP PRINT_PALAM PRINTBUTTON PRINTBUTTONC PRINTBUTTONLC BAR BARL BARSTR TOHALF TOFULL SUBSTRING STRLEN STRFIND REPLACE STRCOUNT ESCAPE GETCONFIG GETCONFIGS PRINTC PRINTLC'.split()
    )
    | DISPLAY_OPS
)


def expression_sources(op, arg, numeric_names=None):
    if (command_spec(op) or {}).get('family') == 'text_length':
        return []
    if (command_spec(op) or {}).get('argument_mode') == 'raw_form_default':
        return []
    if op == '_ASSIGN':
        if arg.startswith(('++', '--')):
            return [arg]
        if arg.endswith(('++', '--')) and find_assignment(arg) is None:
            return [arg[:-2]]
        assignment = find_assignment(arg, legacy=True)
        if not assignment:
            return []
        lhs, sign, rhs = assignment
        if sign == '==':
            sign = '='
        # The RHS of '=' may be raw string content. Runtime type is needed to decide.
        name = parse(lhs)[1]
        return [lhs] + (
            split_args(rhs) if sign != '=' or name in (numeric_names or set()) else []
        )
    if op in {
        'IF',
        'ELSEIF',
        'SIF',
        'WHILE',
        'REPEAT',
        'LOOP',
        'SELECTCASE',
        'ASSERT',
        'RETURNF',
        'CALLTRAIN',
        'DOTRAIN',
        'SKIPDISP',
        'RESET_STAIN',
    }:
        return [arg] if arg.strip() else []
    if op == 'FOR':
        return split_args(arg)
    if (
        op
        in {
            'RETURN',
            'INPUT',
            'INPUTS',
            'ONEINPUT',
            'ONEINPUTS',
            'SAVEDATA',
            'LOADDATA',
            'CHKDATA',
            'ADDCHARA',
            'DELCHARA',
            'SWAPCHARA',
            'COPYCHARA',
            'PICKUPCHARA',
        }
        or op in builtins.NAMES
    ):
        if op == 'VARSIZE':
            return []
        return [x for x in split_args(arg) if x]
    spec = command_spec(op)
    if spec and spec['family'] == 'print':
        mode = spec['argument_mode']
        if mode == 'values':
            return [x for literal, x in split_printv(arg) if not literal]
        if mode in ('string', 'string_form'):
            return [arg] if arg.strip() else []
        if mode in ('button', 'bar'):
            return split_args(arg)

    return []


def calls_in_ast(node):
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == 'call':
        yield node[1]
        for a in node[2]:
            yield from calls_in_ast(a)
    elif node[0] == 'var':
        for a in node[2]:
            yield from calls_in_ast(a)
    elif node[0] == 'binary':
        yield from calls_in_ast(node[2])
        yield from calls_in_ast(node[3])
    elif node[0] == 'unary':
        yield from calls_in_ast(node[2])
    elif node[0] == 'inc':
        yield from calls_in_ast(node[1])
    elif node[0] == 'ternary':
        for a in node[1:]:
            yield from calls_in_ast(a)


def top_level_variables(node):
    """Variable bases in string expressions; CSV symbolic indices are not names
    in the variable namespace and must not be mistaken for missing variables."""
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == 'var':
        yield node[1]
    elif node[0] == 'binary':
        yield from top_level_variables(node[2])
        yield from top_level_variables(node[3])
    elif node[0] == 'unary':
        yield from top_level_variables(node[2])
    elif node[0] == 'inc':
        yield from top_level_variables(node[1])
    elif node[0] == 'ternary':
        for child in node[1:]:
            yield from top_level_variables(child)
    elif node[0] == 'call':
        for child in node[2]:
            yield from top_level_variables(child)


def _numeric_declarations(lines):
    names = set()
    for line in lines:
        if command(line.text)[0] == '#DIM':
            head = (
                line.text.split(',', 1)[0].split('=', 1)[0].strip().split()[-1].upper()
            )
            names.add(head)
    return names


def _declared_variables(program, data, fn):
    """Collect visible names without treating CSV index symbols as variables."""
    declared_names = {'LOCAL', 'LOCALS', 'ARG', 'ARGS'} | set(
        data.variables if data else {}
    )
    for decl in program.globals + fn.declarations:
        try:
            from .expr import IDENT

            bits = command(decl.text)[1].split('=', 1)[0].split(',', 1)[0].split()
            if bits:
                declared_names.add(bits[-1].upper())
        except (ValueError, IndexError):
            pass
    return declared_names


def _audit_call(program, fn, line, op, arg, dynamic, issue):
    """Record a call target; True means expression scanning must be deferred.

    Dynamic FORM targets and malformed argument syntax stop this line's scan in
    r42. A missing static target records an issue and still scans expressions.
    """
    if 'FORM' in op:
        dynamic.append(
            {
                'file': line.location.path,
                'line': line.location.line,
                'kind': op,
            }
        )
        return True
    try:
        parts = split_args(program.expand(arg))
    except EraError as exc:
        # Inventory reports syntax problems; it must not abort
        # normal startup before the loader can mark the line.
        issue(exc.code, exc.message, line.location)
        return True
    name = parts[0].split('(', 1)[0].strip().upper() if parts else ''
    isgoto = 'GOTO' in op
    exists = name in (fn.labels if isgoto else program.functions)
    if not exists and not op.startswith('TRY'):
        issue(
            'E_FUNCTION',
            ('Missing label $' if isgoto else 'Missing function @') + name,
            line.location,
        )
    return False


def _audit_expressions(
    program, data, line, op, arg, spec, numeric_names, declared_names, partial, issue
):
    """Scan expression ASTs in source order; never evaluate values or consume RNG."""
    try:
        for text in expression_sources(op, arg, numeric_names):
            node = parse(program.expand(text))
            if data and spec and spec.get('argument_mode') in ('string', 'string_form'):
                for variable in top_level_variables(node):
                    if variable.split('@')[0] not in declared_names:
                        issue(
                            'E_VARIABLE',
                            'Unknown variable in string expression: ' + variable,
                            line.location,
                        )
            for name in calls_in_ast(node):
                if name not in builtins.NAMES and name not in program.functions:
                    issue(
                        'E_FUNCTION',
                        'Unknown expression function ' + name,
                        line.location,
                    )
                if name in PARTIAL:
                    partial[name] += 1
    except EraError as e:
        issue(e.code, e.message, line.location)


def audit(program, data=None):
    counts = Counter()
    unknown = Counter()
    partial = Counter()
    issues = [e.as_dict() for e in program.load_errors]
    issues.extend(
        EraError(d.reference_message, d.location, d.category).as_dict()
        for d in program.lexical_diagnostics
    )
    functions = sum(len(fs) for fs in program.functions.values())
    dynamic = []

    def issue(code, message, loc):
        key = (code, message, loc.path, loc.line)
        if key not in seen:
            seen.add(key)
            issues.append(EraError(message, loc, code).as_dict())

    seen = set()
    global_numeric = (
        {n for n, v in data.variables.items() if not v.string} if data else set()
    )
    global_numeric |= {'LOCAL', 'ARG'}

    global_numeric |= _numeric_declarations(program.globals)
    for fs in program.functions.values():
        for fn in fs:
            numeric_names = global_numeric | _numeric_declarations(fn.declarations)
            declared_names = _declared_variables(program, data, fn)
            for line in fn.lines:
                if line.text.startswith('$'):
                    continue
                op, arg = command(line.text)
                counts[op] += 1
                spec = command_spec(op)
                if (
                    fn.attributes & {'FUNCTION', 'FUNCTIONS'}
                    and spec
                    and spec.get('method_safe') is False
                ):
                    issue(
                        'E_METHOD_CONTEXT',
                        op + ' is not method-safe in src1824',
                        line.location,
                    )
                if not supported_command(op) and op not in COMPOUNDS:
                    unknown[op] += 1
                    if not any(
                        d.location == line.location for d in program.lexical_diagnostics
                    ):
                        issue('E_UNSUPPORTED', 'Command ' + op, line.location)
                if op in PARTIAL or (command_spec(op) or {}).get('column'):
                    partial[op] += 1
                if op in CALL_OPS and _audit_call(
                    program, fn, line, op, arg, dynamic, issue
                ):
                    continue
                _audit_expressions(
                    program,
                    data,
                    line,
                    op,
                    arg,
                    spec,
                    numeric_names,
                    declared_names,
                    partial,
                    issue,
                )
    warnings = list(program.warnings) + (data.warnings if data else [])
    return {
        'format': 'PyEmuera-Compatibility-1',
        'engine_version': __version__,
        'status': 'known_blockers' if issues else 'no_blockers_in_scanned_subset',
        'gameplay_verified': False,
        'scope_notice': 'Static partial inventory only. Does not execute game code or prove compatibility. String/raw assignment RHS, FORM expressions, dynamic call targets and many command argument variants are deferred to runtime.',
        'functions': functions,
        'instructions': sum(counts.values()),
        'command_counts': dict(sorted(counts.items())),
        'unsupported_command_counts': dict(sorted(unknown.items())),
        'partial_or_adapted_features': dict(sorted(partial.items())),
        'dynamic_calls_deferred': dynamic,
        'issues': issues,
        'warnings': warnings,
        'files': program.files + (data.files if data else []),
    }
