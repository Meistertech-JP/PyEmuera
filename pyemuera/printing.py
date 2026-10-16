"""One implementation for declarative PRINT variants, not suffix guessing."""

from __future__ import annotations
from contextlib import contextmanager
import re
import unicodedata
from .errors import EraError, Unsupported
from .text import split_printv, split_args, display_width
from .expr import parse, integer


def string(value):
    if not isinstance(value, str):
        raise EraError('PRINT requires a string expression', code='E_TYPE')
    return value


def kana(text, mode):
    if mode == 0:
        return text
    if mode not in (1, 2, 3):
        raise EraError('FORCEKANA requires 0..3', code='E_ARGUMENT')
    # Only normalize half-width kana, not the whole string: global NFKC changes
    # unrelated compatibility characters and therefore is not a StrConv clone.
    if mode in (2, 3):
        text = re.sub(
            '[\uff61-\uff9f]+', lambda m: unicodedata.normalize('NFKC', m[0]), text
        )
        text = ''.join(
            (
                chr(ord(c) - 0x60)
                if '\u30a1' <= c <= '\u30f6' or c in '\u30fd\u30fe'
                else c
            )
            for c in text
        )
    else:
        text = ''.join(
            (
                chr(ord(c) + 0x60)
                if '\u3041' <= c <= '\u3096' or c in '\u309d\u309e'
                else c
            )
            for c in text
        )
    if mode == 3:
        text = ''.join(
            chr(ord(c) + 0xFEE0) if '!' <= c <= '~' else '\u3000' if c == ' ' else c
            for c in text
        )
    return text


def forms_input(text):
    """ExpressionMediator.CheckEscape: second-pass FORM leaves non-FORM
    escape sequences literal (e.g. a backslash before n in a stored string)."""
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        i += 1
        if c != '\\':
            out.append(c)
            continue
        following = text[i] if i < len(text) else ''
        i += bool(following)
        if following in ('{', '}', '%', '@'):
            out.append('\\' + following)
        elif following == '\\':
            out.append('\\\\')
        else:
            out.append('\\\\' + following)
    return ''.join(out)


def column_text(vm, text, column):
    from .builtins import call

    width = call(vm, 'PRINTCLENGTH', ())
    used = display_width(text)
    if column == 'right':
        return ' ' * max(0, width - used) + text
    return text + ' ' * max(0, width + 1 - used)


@contextmanager
def print_style(vm, spec):
    old = getattr(vm.console, 'style_override', None)
    if spec.get('default_color'):
        vm.console.style_override = (
            getattr(vm, 'default_color', 0xC0C0C0),
            vm.ui['bgcolor'],
            vm.ui['style'],
        )
    if spec.get('argument_mode') in ('rule', 'rule_raw', 'rule_default'):
        fg, bg, _ = vm.console.style_override or (
            vm.ui['color'],
            vm.ui['bgcolor'],
            vm.ui['style'],
        )
        vm.console.style_override = (fg, bg, 0)
    try:
        yield
    finally:
        vm.console.style_override = old


def execute(vm, spec, arg):
    console = vm.console
    if spec.get('debug'):
        if vm.program.debug:
            # Debug text is diagnostic output, never part of the game buffer.
            # Debug output binds sys only after the debug gate; embedders may
            # replace that module between calls, so retain the lazy boundary.
            import sys

            text = vm.format(arg) if spec['argument_mode'] == 'form' else arg
            sys.stderr.write(text + ('\n' if spec['newline'] else ''))
            sys.stderr.flush()
        return True
    if spec['skip_before_eval'] and console.skip_print:
        return True
    mode = spec['argument_mode']
    if mode == 'raw':
        text = arg
    elif mode == 'form':
        text = vm.format(arg)
    elif mode == 'string':
        text = string(vm.eval(arg))
    elif mode == 'string_form':
        text = vm.format(forms_input(string(vm.eval(arg))))
    elif mode == 'values':
        text = ''.join(
            x if literal else str(vm.eval(x)) for literal, x in split_printv(arg)
        )
    elif mode == 'button':
        a = vm.args(arg)
        if len(a) != 2:
            raise EraError('PRINTBUTTON requires label,input-value', code='E_ARGUMENT')
        text = string(a[0]).replace('\n', '').replace('\r', '')
        if type(a[1]) not in (int, str):
            raise EraError('Button value must be integer or string', code='E_TYPE')
    elif mode == 'bar':
        from .builtins import call

        parts = split_args(arg)
        if len(parts) < 3:
            raise EraError('引数が設定されていません', code='E_ARGUMENT')
        text = call(vm, 'BARSTR', [parse(vm.program.expand(x)) for x in parts[:3]])
    elif mode in ('rule', 'rule_raw', 'rule_default'):
        from .compat1824 import rule_string

        # DRAWLINE/CUSTOMDRAWLINE always start on a fresh logical line.
        if console.current:
            console.write('', True)
        pattern = (
            vm.get('DRAWLINESTR')
            if mode == 'rule_default'
            else arg if mode == 'rule_raw' else vm.format(arg)
        )
        text = rule_string(vm, pattern)
    else:
        raise EraError('Unbound print mode ' + mode, code='E_SPEC')
    if spec['column'] and not text:
        return True
    if spec['kana']:
        text = kana(text, vm.ui['kana'])
    if spec['column']:
        text = column_text(vm, text, spec['column'])
    if spec['single']:
        console.warning(
            'single',
            'PRINTSINGLE is a logical single line; pixel clipping is not reproduced.',
        )
        if console.current:
            console.write('', True)
    previous_button = console.button_context
    if mode == 'button':
        console.button_context = (a[1], None, None)
    try:
        with print_style(vm, spec):
            if mode in ('rule', 'rule_raw', 'rule_default'):
                console.write_rule(text)
            else:
                console.write(
                    console.print_buffer_text(text), spec['newline'] or spec['single']
                )
    finally:
        console.button_context = previous_button
    if spec['wait']:
        console.wait()
    return True


def output_data(vm, spec, lines):
    # Selection and data-variable assignment are VM primitives. PRINT flags are
    # interpreted here from the same syntax table used to compile the block.
    with print_style(vm, spec):
        for i, text in enumerate(lines):
            if spec.get('kana'):
                text = kana(text, vm.ui['kana'])
            vm.console.write(text, i < len(lines) - 1 or spec['newline'])
    if spec['wait']:
        vm.console.wait()


def text_length(vm, spec, arg):
    text = vm.format(arg) if spec['argument_mode'] == 'form' else arg
    value = (
        len(text.encode('utf-16-le', errors='surrogatepass')) // 2
        if spec['length_unit'] == 'utf16'
        else display_width(text)
    )
    vm.set('RESULT', value)
    return True
