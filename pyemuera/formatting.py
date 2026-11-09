from __future__ import annotations
from functools import lru_cache
from .errors import EraError
from . import text as _lexical_text
from .expr import integer
from .internal_state import successful_validation_cache
from .text import (
    split_args,
    display_width,
    placeholder_end,
    conditional_end,
    quoted_end,
)


_end = placeholder_end


_FORM_PARTS_MAX_TEXT = 4096
_FORM_PARTS_CACHE_SIZE = 1024


def _parse_placeholder_parts(text, start, close):
    end = _end(text, start, close)
    return end, tuple(split_args(text[start:end]))


_cached_placeholder_parts = lru_cache(maxsize=_FORM_PARTS_CACHE_SIZE)(
    _parse_placeholder_parts
)


def _placeholder_parts(text, start, close):
    # Cache only lexical work reached by the existing lazy walk, never an entire
    # FORM pre-scan: without frames, a later parse error must follow earlier
    # operand effects. Failed scans are not retained by lru_cache. The immutable
    # result contains source strings only, with no VM/value/validation state.
    if type(text) is str and len(text) <= _FORM_PARTS_MAX_TEXT:
        return _cached_placeholder_parts(text, start, close)
    return _parse_placeholder_parts(text, start, close)


def form_components(text, level=0):
    """Non-executing FORM walk; uses the same delimiters as render()."""
    if level > 32:
        raise EraError('FORM nesting limit', code='E_LIMIT')
    i = 0
    while i < len(text):
        if text.startswith('\\@', i):
            end, condition, yes, no, _ = _conditional_lexical_parts(text, i)
            yield condition, 'Int64', 'condition'
            yield from form_components(yes, level + 1)
            yield from form_components(no, level + 1)
            i = end + 2
            continue
        c = text[i]
        if c == '\\' and i + 1 < len(text):
            i += 2
            continue
        if c in '{%':
            end, parts = _placeholder_parts(text, i + 1, '}' if c == '{' else '%')
            yield parts[0], 'Int64' if c == '{' else 'string', c
            if len(parts) > 1 and parts[1]:
                yield parts[1], 'Int64', 'width'
            i = end + 1
            continue
        i += 1


def form_expression_sources(text, level=0):
    for expression, expected, role in form_components(text, level):
        yield expression, expected


def type_error(role):
    return (
        '{}の中の式が数式ではありません'
        if role == '{'
        else '%%の中の式が文字列式ではありません'
    )


def validate_types(text, vm):
    """Parse/infer every FORM operand before any substitution side effect."""
    if not getattr(vm, 'frames', None):
        return
    fn = vm.frames[-1].function
    cache = successful_validation_cache(vm, '_form_type_cache')
    key = (fn.uid, text)
    if key in cache:
        return
    from .load_arguments import StaticContext

    context = StaticContext(vm, fn)
    for expression, expected, role in form_components(text):
        actual = context.infer(vm.expression_node(expression))
        if actual is not None and actual != expected:
            if role in ('{', '%'):
                raise EraError(type_error(role), code='E_TYPE')
            context.require(actual, expected)
    if len(cache) >= 131072:
        cache.clear()
    cache.add(key)


def _conditional_parts(body: str):
    # The condition is an expression: '?' inside a quoted value or nested
    # parentheses is not its separator. Branch text is raw FORM: skip complete
    # substitutions and escaped '#' rather than treating their contents as delimiters.
    i = 0
    depth = 0
    q = -1
    while i < len(body):
        if body.startswith('@"', i):
            i = quoted_end(body, i, True)
            continue
        c = body[i]
        if c == '"':
            i = quoted_end(body, i)
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == '?' and depth == 0:
            q = i
            break
        i += 1
    if q < 0:
        raise EraError('FORM conditional needs ?', code='E_FORMAT')
    i = q + 1
    while i < len(body):
        c = body[i]
        if c == '\\':
            i += 2
            continue
        if c in '{%':
            i = placeholder_end(body, i + 1, '}' if c == '{' else '%') + 1
            continue
        if c == '#':
            return body[:q], body[q + 1 : i], body[i + 1 :], True
        i += 1
    return body[:q], body[q + 1 :], '', False


_BASE_CONDITIONAL_END = conditional_end
_BASE_CONDITIONAL_PARTS = _conditional_parts
_BASE_PLACEHOLDER_END = placeholder_end
_BASE_QUOTED_END = quoted_end
_BASE_CONDITIONAL_END_STATE = (conditional_end.__code__, conditional_end.__defaults__, conditional_end.__kwdefaults__)
_BASE_CONDITIONAL_PARTS_STATE = (_conditional_parts.__code__, _conditional_parts.__defaults__, _conditional_parts.__kwdefaults__)
_BASE_PLACEHOLDER_END_STATE = (placeholder_end.__code__, placeholder_end.__defaults__, placeholder_end.__kwdefaults__)
_BASE_QUOTED_END_STATE = (quoted_end.__code__, quoted_end.__defaults__, quoted_end.__kwdefaults__)


def _parse_conditional_lexical_parts(text, start, _render=False):
    end = conditional_end(text, start) - 2
    if _render and end < 0:
        raise EraError('Unclosed FORM conditional', code='E_FORMAT')
    condition, yes, no, has_false = _conditional_parts(text[start + 2 : end])
    return end, condition, yes, no, has_false


_cached_conditional_lexical_parts = lru_cache(maxsize=_FORM_PARTS_CACHE_SIZE)(
    _parse_conditional_lexical_parts
)


def _conditional_lexical_parts(text, start, _render=False):
    # Lexical successes only; helper rebinding and custom strings stay live.
    if (type(text) is str and type(start) is int and len(text) <= _FORM_PARTS_MAX_TEXT
            and conditional_end is _BASE_CONDITIONAL_END
            and _conditional_parts is _BASE_CONDITIONAL_PARTS
            and placeholder_end is _BASE_PLACEHOLDER_END and quoted_end is _BASE_QUOTED_END
            and _lexical_text.conditional_end is _BASE_CONDITIONAL_END
            and _lexical_text.placeholder_end is _BASE_PLACEHOLDER_END
            and _lexical_text.quoted_end is _BASE_QUOTED_END
            and _BASE_CONDITIONAL_END.__code__ is _BASE_CONDITIONAL_END_STATE[0]
            and _BASE_CONDITIONAL_END.__defaults__ is _BASE_CONDITIONAL_END_STATE[1]
            and _BASE_CONDITIONAL_END.__kwdefaults__ is _BASE_CONDITIONAL_END_STATE[2]
            and _BASE_CONDITIONAL_PARTS.__code__ is _BASE_CONDITIONAL_PARTS_STATE[0]
            and _BASE_CONDITIONAL_PARTS.__defaults__ is _BASE_CONDITIONAL_PARTS_STATE[1]
            and _BASE_CONDITIONAL_PARTS.__kwdefaults__ is _BASE_CONDITIONAL_PARTS_STATE[2]
            and _BASE_PLACEHOLDER_END.__code__ is _BASE_PLACEHOLDER_END_STATE[0]
            and _BASE_PLACEHOLDER_END.__defaults__ is _BASE_PLACEHOLDER_END_STATE[1]
            and _BASE_PLACEHOLDER_END.__kwdefaults__ is _BASE_PLACEHOLDER_END_STATE[2]
            and _BASE_QUOTED_END.__code__ is _BASE_QUOTED_END_STATE[0]
            and _BASE_QUOTED_END.__defaults__ is _BASE_QUOTED_END_STATE[1]
            and _BASE_QUOTED_END.__kwdefaults__ is _BASE_QUOTED_END_STATE[2]):
        return _cached_conditional_lexical_parts(text, start)
    return _parse_conditional_lexical_parts(text, start, _render)


def render(text: str, vm, level=0, trim_edges=False) -> str:
    if level > 32:
        raise EraError('FORM nesting limit', code='E_LIMIT')
    validate_types(text, vm)
    out = []
    literal = []
    i = 0

    def flush(final=False):
        value = ''.join(literal)
        literal.clear()
        # AnalyseFormattedString(trim=true) trims only the boundary *literal*
        # segments, not text generated by an expression/placeholder.
        if trim_edges and not out:
            value = value.lstrip(' \t')
        if trim_edges and final:
            value = value.rstrip(' \t')
        out.append(value)

    while i < len(text):
        c = text[i]
        if text.startswith('\\@', i):
            end, condition, yes, no, has_false = _conditional_lexical_parts(text, i, _render=True)
            if not has_false:
                vm.console.warning(
                    'conditional-missing-false',
                    'FORM conditional without # uses an empty false branch.',
                )
            chosen = yes if vm.eval(condition) else no
            flush()
            out.append(render(chosen, vm, level + 1, trim_edges=True))
            i = end + 2
            continue
        if c == '\\' and i + 1 < len(text):
            literal.append(
                {'n': '\n', 'r': '\r', 't': '\t', 's': ' ', 'S': '　'}.get(
                    text[i + 1], text[i + 1]
                )
            )
            i += 2
            continue
        if c in '{%':
            close = '}' if c == '{' else '%'
            end, parts = _placeholder_parts(text, i + 1, close)
            val = vm.eval(parts[0])
            if (c == '{' and not isinstance(val, int)) or (
                c == '%' and not isinstance(val, str)
            ):
                raise EraError(type_error(c), code='E_TYPE')
            val = str(val)
            if len(parts) > 1 and parts[1]:
                # StrForm.FromWordToken -> ReduceIntegerTerm: padding is an
                # integer expression, not Python's permissive int(string).
                width = abs(integer(vm.eval(parts[1])))
                if width > 1_000_000:
                    raise EraError('FORM padding limit', code='E_LIMIT')
                pad = ' ' * max(0, width - display_width(val))
                left = len(parts) > 2 and parts[2].upper() == 'LEFT'
                val = val + pad if left else pad + val
            flush()
            out.append(val)
            i = end + 1
            continue
        literal.append(c)
        i += 1
    flush(final=True)
    result = ''.join(out)
    if len(result) > 10_000_000:
        raise EraError('FORM output limit', code='E_LIMIT')
    return result
