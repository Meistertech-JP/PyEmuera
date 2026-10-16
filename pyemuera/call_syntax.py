"""Split a raw CALL target from expression arguments without evaluating ERB.

SP_CALL reads a string up to (, [, comma or semicolon and trims ASCII space;
it does not parse the whole instruction argument as a function expression.
FORM targets use the existing FORM-aware splitter. Syntax objects contain only
text, never live refs, cached values, clocks or RNG state.
"""

from dataclasses import dataclass
from .errors import EraError, Unsupported
from .expr import parse, tokenize
from .text import (
    split_args,
    split_dynamic_call,
    placeholder_end,
    conditional_end,
    quoted_end,
)


@dataclass(frozen=True)
class CallSyntax:
    target: str
    arguments: tuple[str, ...]
    empty_subnames: bool = False


def _literal_name(text):
    out = []
    index = 0
    while index < len(text):
        if text[index] == '\\':
            index += 1
            if index >= len(text):
                raise EraError(
                    'エスケープ文字\\の後に文字がありません', code='E_SYNTAX'
                )
            ch = text[index]
            if ch != '\n':
                out.append({'s': ' ', 'S': '　', 't': '\t', 'n': '\n'}.get(ch, ch))
        else:
            out.append(text[index])
        index += 1
    return ''.join(out).strip(' \t')


def parse_call(text, form=False, validate_subname=None):
    """Split the target and arguments; never evaluate subname expressions.

    v24 ReduceArguments has its nonempty RightBracket terminator disabled.
    Empty [] is accepted but does not change the target. Nonempty [...] fails
    during expression parsing, before restructuring/evaluation. Its apparent
    syntax must not be implemented as a function-name suffix.
    """
    index = 0
    while index < len(text):
        if text[index] == '\\':
            if form and text.startswith('\\@', index):
                index = conditional_end(text, index)
            else:
                index += 2
            continue
        if form and text[index] in '{%':
            index = (
                placeholder_end(text, index + 1, '}' if text[index] == '{' else '%') + 1
            )
            continue
        if text[index] in '([,;':
            break
        index += 1
    target = text[:index].strip(' \t') if form else _literal_name(text[:index])
    tail = text[index:]
    empty_subnames = False
    # SP_CALL lexes the entire tail before parsing subnames/arguments. The lexer
    # checks parentheses before square brackets and ignores delimiters in strings.
    delimiters = []
    cursor = 0
    while cursor < len(tail):
        # FORM strings may contain quoted operands inside their placeholders.
        # Use the same reader as the expression lexer, not a quote-toggle scan.
        if tail.startswith('@"', cursor):
            cursor = quoted_end(tail, cursor, True)
            continue
        if tail[cursor] == '"':
            cursor = quoted_end(tail, cursor)
            continue
        if tail.startswith('\\@', cursor):
            cursor = conditional_end(tail, cursor)
            continue
        if tail[cursor] in '()[]':
            delimiters.append(tail[cursor])
        cursor += 1
    for opening, closing in [('(', ')'), ('[', ']')]:
        balance = delimiters.count(opening) - delimiters.count(closing)
        if balance:
            absent, present = (closing, opening) if balance > 0 else (opening, closing)
            raise EraError(
                "字句解析中に対応する'"
                + absent
                + "'のない'"
                + present
                + "'を発見しました",
                code='E_SYNTAX',
            )
    if tail.startswith('['):
        closing = tail.find(']')
        if closing < 0:
            raise EraError("'['に対応する']'が見つかりません", code='E_SYNTAX')
        inner = tail[1:closing]
        if inner.strip():
            # Pure lexical/AST checks can reproduce the disabled terminator.
            # Identifier binding has earlier native errors; do not guess their
            # priority or reduce/evaluate live values in this syntax splitter.
            first = split_args(inner)[0]
            node = parse(first) if first else None
            if any(t.kind == 'ID' for t in tokenize(first)):
                if validate_subname is None:
                    raise Unsupported('CALL nonempty subname identifier binding')
                # Binding is static only. Native encounters the unexpected
                # terminator after binding the first operand, before restructure
                # or evaluation. Never execute ++, functions, or RNG here.
                validate_subname(node)
            separator = ',' if len(split_args(inner)) > 1 else ']'
            raise EraError(
                "構文解釈中に予期しない記号'" + separator + "'を発見しました",
                code='E_SYNTAX',
            )
        empty_subnames = True
        tail = tail[closing + 1 :].strip(' \t')
        # Source branch does not advance an opening '(' after ]. Do not accept
        # this conventional-looking notation as though the native parser did.
        if tail.startswith('('):
            raise EraError("'('に対応する')'が見つかりません", code='E_SYNTAX')
        if tail:
            raise Unsupported('CALL empty subname followed by argument tokens')
    if tail.startswith('('):
        if not tail.rstrip().endswith(')'):
            raise EraError('Unclosed parenthesized call', code='E_SYNTAX')
        inner = tail.rstrip()[1:-1]
        arguments = split_args(inner) if inner.strip() else []
    elif tail.startswith(','):
        arguments = split_args(tail[1:])
    else:
        arguments = []
    if not target.strip(' \t'):
        raise EraError('関数名が指定されていません', code='E_ARGUMENT')
    return CallSyntax(target, tuple(arguments), empty_subnames)


def constant_form_name(
    target, user_methods=(), constant_resolver=None, methods=None, *, trim_edges=True
):
    """Pure FORM restructure: operators/literals only, never live VM evaluation.

    Check every branch/width before rendering. Unknown or effectful AST nodes
    stay dynamic; user method overrides are not treated as pure builtins.
    """
    from .constant_ast import Reducer, FORM_METHODS
    from .formatting import form_expression_sources, render
    from .expr import parse
    from types import SimpleNamespace

    values = {}
    reducer = Reducer(
        user_methods,
        methods=FORM_METHODS if methods is None else methods,
        constant_resolver=constant_resolver,
    )
    for expression, expected in form_expression_sources(target):
        node = reducer.reduce(parse(expression))
        if node[0] != 'lit':
            return None
        value = node[1]
        if (expected == 'string') != isinstance(value, str):
            return None
        values[expression] = value
    # render uses only this closed literal mapping; no variables, RNG, callbacks
    # or game state can be read by this deliberately minimal adapter.
    adapter = SimpleNamespace(
        eval=values.__getitem__, console=SimpleNamespace(warning=lambda *args: None)
    )
    return render(target, adapter, trim_edges=trim_edges)


def is_statement_call(op):
    return op.startswith(
        ('CALL', 'JUMP', 'TRYCALL', 'TRYJUMP', 'TRYCCALL', 'TRYCJUMP')
    ) and op not in {'CALLEVENT', 'CALLTRAIN'}
