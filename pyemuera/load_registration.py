"""Non-executing lexical/registration defects precede reachability analysis."""

from .errors import EraError, LoadDiagnostic
from .registry import command_spec, SYNTAX_SPECS
from .text import quoted_end


def header_delimiters(text):
    counts = {'(': 0, '[': 0}
    i = 0
    while i < len(text):
        if text.startswith('@"', i):
            i = quoted_end(text, i, True)
            continue
        if text[i] == '"':
            i = quoted_end(text, i)
            continue
        char = text[i]
        if char in counts:
            counts[char] += 1
        elif char in ')]':
            opening = '(' if char == ')' else '['
            counts[opening] -= 1
        i += 1
    for opening, closing in [('(', ')'), ('[', ']')]:
        number = counts[opening]
        if number:
            left, right = (closing, opening) if number > 0 else (opening, closing)
            raise EraError(
                "字句解析中に対応する'" + left + "'のない'" + right + "'を発見しました",
                code='E_SYNTAX',
            )


def register(program, line, error):
    error.location = error.location or line.location
    source = program.original_source[line.location.path][line.location.line - 1]
    program.lexical_diagnostics.append(
        LoadDiagnostic(
            2,
            error.code,
            line.location,
            source,
            error.as_dict()['diagnostic_message'],
            len(program.lexical_diagnostics),
            phase='lexical-registration',
        )
    )


def check_lines(program):
    from .program import command

    for group in program.functions.values():
        for function in group:
            for line in function.lines:
                if line.text.startswith('$'):
                    continue
                op, _ = command(line.text)
                spec = command_spec(op)
                if (
                    op == '_ASSIGN'
                    or (spec is not None and spec.get('native_registered', True))
                    or op in SYNTAX_SPECS
                ):
                    continue
                error = EraError('解釈できない行です', line.location, 'E_SYNTAX')
                register(program, line, error)
                for instruction in function.code:
                    if instruction.location == line.location:
                        instruction.argument_error = error


def require_executable(vm):
    if not vm.program.lexical_diagnostics:
        return
    allowed = (
        vm.program.config.get('解釈不可能な行があっても実行する', 'NO').upper() == 'YES'
    )
    if allowed:
        return
    message = 'ERBコードに解釈不可能な行があるためEmueraを終了します'
    vm.console.write(message, True)
    raise EraError(message, vm.program.lexical_diagnostics[0].location, 'E_LOAD')
