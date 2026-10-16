"""The text/buffer portion of Emuera's HtmlManager, not browser HTML.

Escape and tag-splitting reproduce the supplied source's restricted grammar.
Buffer roundtrip is a logical-line projection: GDI wrapping, images and absolute
pixel-positioned buttons are deliberately outside this adapter.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from .expr import evaluate, integer, parse
from .errors import EraError, Unsupported
from .text import split_args


def error(message):
    return EraError(message, code='E_HTML')


def escape(text):
    if not isinstance(text, str):
        raise EraError('HTML string required', code='E_TYPE')
    return ''.join(
        {'&': '&amp;', '>': '&gt;', '<': '&lt;', '"': '&quot;', "'": '&apos;'}.get(c, c)
        for c in text
    )


def unescape(text):
    out = []
    i = 0
    entities = {'nbsp': ' ', 'amp': '&', 'gt': '>', 'lt': '<', 'quot': '"', 'apos': "'"}
    while i < len(text):
        j = text.find('&', i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        end = text.find(';', j + 1)
        if end < 0:
            raise error("Missing ';' after '&'")
        name = text[j + 1 : end].lower()
        if name in entities:
            out.append(entities[name])
        elif name.startswith('#'):
            digits = name[2:] if name.startswith('#x') else name[1:]
            try:
                if (
                    not digits
                    or re.fullmatch(
                        r'[+-]?[0-9a-f]+' if name.startswith('#x') else r'[+-]?[0-9]+',
                        digits,
                    )
                    is None
                ):
                    raise ValueError()
                n = int(digits, 16 if name.startswith('#x') else 10)
            except ValueError as exc:
                raise error('Invalid HTML numeric entity') from exc
            if not 0 <= n <= 0xFFFF:
                raise error('HTML entity is outside UTF-16 unit range')
            out.append(chr(n))
        else:
            raise error('Unknown HTML entity &' + name + ';')
        i = end + 1
    return ''.join(out)


def to_plain(text):
    if not isinstance(text, str):
        raise EraError('HTML string required', code='E_TYPE')
    return unescape(re.sub(r'<[^<]*>', '', text))


def tag_split(text):
    """Intentionally split at the FIRST >, even in a quoted attribute (1824)."""
    values = []
    i = 0
    while i < len(text):
        j = text.find('<', i)
        if j < 0:
            values.append(text[i:])
            break
        if j > i:
            values.append(text[i:j])
        end = text.find('>', j)
        if end < 0:
            return None
        values.append(text[j : end + 1])
        i = end + 1
    return values


@dataclass(frozen=True)
class MarkupStyle:
    color: int = 0xC0C0C0
    bits: int = 0
    font: str = 'monospace'
    focus: int = 0xFFFF00
    button: tuple | None = None


def serialize(runs, alignment=None, default_color=0xC0C0C0, default_font='monospace'):
    out = []
    if alignment is not None:
        out.append("<p align='" + alignment.lower() + "'><nobr>")
    for text, style in runs:
        begin = []
        end = []
        if style.button is not None:
            value, title, pos = style.button
            tag = 'button' if value is not None else 'nonbutton'
            attrs = (" value='" + escape(str(value)) + "'") if value is not None else ''
            if title:
                attrs += " title='" + escape(title) + "'"
            if pos is not None:
                attrs += " pos='" + str(pos) + "'"
            begin.append('<' + tag + attrs + '>')
            end.insert(0, '</' + tag + '>')
        attrs = ''
        if style.font != default_font:
            attrs += " face='" + escape(style.font) + "'"
        if style.color != default_color:
            attrs += f" color='#{style.color:06X}'"
        if style.focus != 0xFFFF00:
            attrs += f" bcolor='#{style.focus:06X}'"
        if attrs:
            begin.append('<font' + attrs + '>')
            end.insert(0, '</font>')
        for bit, tag in [(8, 's'), (4, 'u'), (2, 'i'), (1, 'b')]:
            if style.bits & bit:
                begin.append('<' + tag + '>')
                end.insert(0, '</' + tag + '>')
        out.append(''.join(begin) + escape(text) + ''.join(end))
    if alignment is not None:
        out.append('</nobr></p>')
    return ''.join(out)


_ATTR = re.compile(r"\s+([A-Za-z][A-Za-z0-9_]*)\s*=\s*(['\"])(.*?)\2", re.S)
_TOKEN = re.compile(r"<!--.*?-->|<(?:[^>'\"]|'[^']*'|\"[^\"]*\")*>|[^<]+", re.S)


def parse_html(text, default_color=0xC0C0C0, default_font='monospace'):
    """Parse fully before display; no partial rendering on bad markup."""
    if not isinstance(text, str):
        raise EraError('HTML_PRINT needs a string', code='E_TYPE')
    if len(text) > 1_000_000:
        raise error('HTML text limit')
    runs = []
    bits = 0
    fonts = []
    button = None
    p = False
    nobr = False
    alignment = 'LEFT'
    closed_p = False
    closed_n = False
    seen_text = False
    position = 0

    def emit(value):
        nonlocal seen_text
        if not value:
            return
        f = fonts[-1] if fonts else {}
        st = MarkupStyle(
            f.get('color', default_color),
            bits,
            f.get('face', default_font),
            f.get('bcolor', 0xFFFF00),
            button,
        )
        runs.append((value, st))
        seen_text = True

    for match in _TOKEN.finditer(text):
        if match.start() != position:
            raise error('Unclosed HTML tag')
        position = match.end()
        token = match.group()
        if token.startswith('<!--'):
            continue
        if not token.startswith('<'):
            if closed_p or closed_n:
                raise error('Text after closing p/nobr')
            emit(unescape(token))
            continue
        content = token[1:-1].strip()
        closing = content.startswith('/')
        if closing:
            content = content[1:].strip()
        m = re.match(r'[A-Za-z][A-Za-z0-9_]*', content)
        if not m:
            raise error('Invalid HTML tag')
        tag = m.group().lower()
        tail = content[m.end() :]
        attrs = {}
        cursor = 0
        for a in _ATTR.finditer(tail):
            if tail[cursor : a.start()].strip():
                raise error('Invalid HTML attribute syntax')
            key = a[1].lower()
            if key in attrs:
                raise error('Duplicate HTML attribute ' + key)
            attrs[key] = unescape(a[3])
            cursor = a.end()
        if tail[cursor:].strip():
            raise error('Invalid HTML attribute syntax')
        if closing and attrs:
            raise error('Closing tags have no attributes')
        if tag in ('img', 'shape'):
            raise Unsupported('HTML ' + tag + ' graphics are excluded')
        if tag in ('b', 'i', 'u', 's'):
            if attrs:
                raise error('Style tags have no attributes')
            bit = {'b': 1, 'i': 2, 'u': 4, 's': 8}[tag]
            if closing:
                if not bits & bit:
                    raise error('Closing unopened style ' + tag)
                bits ^= bit
            else:
                if bits & bit:
                    raise error('Duplicate style ' + tag)
                bits |= bit
        elif tag == 'font':
            if closing:
                if not fonts:
                    raise error('Closing unopened font')
                fonts.pop()
            else:
                if not attrs or set(attrs) - {'face', 'color', 'bcolor'}:
                    raise error('Unsupported font attributes')
                current = dict(fonts[-1]) if fonts else {}
                for key, value in attrs.items():
                    if key != 'face':
                        from .named_colors import COLORS

                        try:
                            value = (
                                int(value[1:], 16)
                                if value.startswith('#')
                                else COLORS.get(value.lower(), -1)
                            )
                        except ValueError as exc:
                            raise error('Invalid HTML color') from exc
                        if not 0 <= value <= 0xFFFFFF:
                            raise error('Invalid HTML color')
                    current[key] = value
                fonts.append(current)
        elif tag in ('button', 'nonbutton'):
            if closing:
                if button is None or active_button != tag:
                    raise error('Closing unopened button')
                button = None
            else:
                if button is not None:
                    raise error('Nested button tags')
                if set(attrs) - (
                    {'title', 'pos', 'value'} if tag == 'button' else {'title', 'pos'}
                ):
                    raise error('Unsupported button attribute')
                if 'pos' in attrs:
                    raise Unsupported('HTML pos requires pixel-positioned rendering')
                button = (
                    attrs.get('value') if tag == 'button' else None,
                    attrs.get('title'),
                    None,
                )
                active_button = tag
        elif tag == 'br':
            if closing or attrs:
                raise error('Invalid br tag')
            emit('\n')
        elif tag in ('p', 'nobr'):
            if closing:
                if tag == 'p':
                    if not p or closed_p:
                        raise error('Closing unopened p')
                    closed_p = True
                else:
                    if not nobr or closed_n:
                        raise error('Closing unopened nobr')
                    closed_n = True
            else:
                if seen_text:
                    raise error(tag + ' must occur at line head')
                if tag == 'p':
                    if (
                        p
                        or nobr
                        or set(attrs) != {'align'}
                        or attrs['align'].upper() not in ('LEFT', 'CENTER', 'RIGHT')
                    ):
                        raise error('Invalid p alignment or position')
                    p = True
                    alignment = attrs['align'].upper()
                else:
                    if nobr or attrs:
                        raise error('Invalid nobr tag')
                    nobr = True
        else:
            raise error('Unsupported HTML tag ' + tag)
    if position != len(text):
        raise error('Unclosed HTML tag')
    if bits or fonts or button is not None:
        raise error('Unclosed style/font/button tag')
    return runs, alignment, nobr


def execute(vm, spec, arg):
    name = spec['name']
    con = vm.console
    if name == 'HTML_TAGSPLIT':
        parts = split_args(arg)
        if not 1 <= len(parts) <= 3 or any(not p for p in parts):
            raise EraError(
                'HTML_TAGSPLIT expects text [,string-array [,integer-ref]]',
                code='E_ARGUMENT',
            )
        text = vm.eval(parts[0])
        if not isinstance(text, str):
            raise EraError('HTML_TAGSPLIT needs a string', code='E_TYPE')
        if len(parts) > 1:
            node = parse(vm.program.expand(parts[1]))
            if node[0] != 'var':
                raise EraError(
                    'HTML_TAGSPLIT destination must be an array', code='E_REFERENCE'
                )
            dest = vm.lookup(node[1])
        else:
            dest = vm.lookup('RESULTS')
        if not dest.string or dest.readonly or dest.character or len(dest.dims) != 1:
            raise EraError(
                'HTML_TAGSPLIT destination must be writable non-character 1D string array',
                code='E_TYPE',
            )
        count = vm.ref(parts[2] if len(parts) > 2 else 'RESULT')
        if count.variable.string or count.variable.readonly:
            raise EraError(
                'HTML_TAGSPLIT count must be writable integer', code='E_TYPE'
            )
        values = tag_split(text)
        count.set(-1 if values is None else len(values))
        if values is not None:
            for i, value in enumerate(values[: dest.dims[0]]):
                dest.set((i,), value)
        return True
    if name == 'HTML_PRINT':
        if con.skip_print:
            return True
        parts = split_args(arg)
        if not parts:
            raise EraError('HTML_PRINT命令:引数が足りません', code='E_ARGUMENT')
        runs, alignment, nobr = parse_html(
            vm.eval(parts[0]), vm.default_color, vm.ui['font']
        )
        if con.current:
            con.write('', True)
        old = dict(vm.ui)
        old_button = con.button_context
        old_style = con.style_override
        old_focus = con.html_focus
        try:
            vm.ui['alignment'] = alignment
            for text, st in runs:
                con.style_override = (st.color, old['bgcolor'], st.bits)
                vm.ui['font'] = st.font
                con.html_focus = st.focus
                con.button_context = st.button
                con.write(text)
            if con.current or not runs:
                con.write('', True)
        finally:
            vm.ui.update(old)
            con.style_override = old_style
            con.button_context = old_button
            con.html_focus = old_focus
        return True
    return False


def function(vm, name, nodes):
    values = [evaluate(n, vm) for n in nodes]
    if name == 'HTML_ESCAPE':
        return escape(values[0])
    if name == 'HTML_TOPLAINTEXT':
        return to_plain(values[0])
    if name == 'HTML_GETPRINTEDSTR':
        index = integer(values[0]) if values and values[0] is not None else 0
        if index < 0:
            raise EraError(
                'HTML_GETPRINTEDSTR index must be nonnegative', code='E_ARGUMENT'
            )
        if index >= len(vm.console.markup_lines):
            return ''
        runs, alignment = vm.console.markup_lines[-1 - index]
        return serialize(
            runs,
            alignment,
            vm.default_color,
            vm.data.config.get('フォント名', 'ＭＳ ゴシック'),
        )
    if name == 'HTML_POPPRINTINGSTR':
        result = serialize(
            vm.console.markup_current,
            None,
            vm.default_color,
            vm.data.config.get('フォント名', 'ＭＳ ゴシック'),
        )
        vm.console.discard_current()
        if vm.console.layout == 'raw' and vm.console._frame is None and result:
            vm.console.warning(
                'html-pop-output',
                'HTML_POPPRINTINGSTR removes the logical buffer; append-only raw stdout cannot retract already-emitted bytes.',
            )
        return result
    raise Unsupported('HTML function ' + name)


def execute_direct(vm, spec, arg):
    """Historical direct API: flat HTML text, no layout state contract."""
    op = spec['name']
    from .argument_counts import expect
    from .plain_html import html_plain

    console = vm.console
    if console.skip_print:
        return True
    a = vm.args(arg)
    expect(a, 1, 2, op)
    if len(a) > 1 and a[1] not in (0, 1):
        raise Unsupported('HTML_PRINT extended options')
    if not isinstance(a[0], str):
        raise EraError('HTML_PRINT requires string', code='E_TYPE')
    console.warning(
        'html', 'HTML_PRINT uses text-only rendering; layout and styles differ.'
    )
    console.write(html_plain(a[0]), not (len(a) > 1 and a[1]))
    return True
