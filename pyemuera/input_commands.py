"""Input family: raw-FORM INPUTS, immediate single-key input, timed variants.

ArgumentBuilder.SP_INPUTS is NOT STR_EXPRESSION. Quotation marks in INPUTS
are literal; TINPUTS uses a string expression. Source TONEINPUT's numeric
fallback formula is retained, including its >=10 -> usually 1 quirk.
"""

import math
from .errors import EraError, Unsupported
from .expr import integer
from .text import split_args


def first_unit(text):
    return text.encode('utf-16-le', errors='surrogatepass')[:2].decode(
        'utf-16-le', errors='surrogatepass'
    )


def execute(vm, spec, arg):
    name = spec['name']
    con = vm.console
    mode = spec['argument_mode']
    if mode == 'raw_form_default':
        default = vm.format(arg) if arg else None
        if spec.get('one') and default is not None:
            default = first_unit(default) or None
        a = []
    else:
        parts = split_args(arg) if arg.strip() else []
        minimum = spec['min_args']
        maximum = spec['max_args']
        if len(parts) < minimum:
            raise EraError(name + ' has too few arguments', code='E_ARGUMENT')
        if len(parts) > maximum:
            if spec.get('extra_arguments') == 'warn_ignore':
                con.warning(
                    'input-extra-' + name,
                    name + ': extra arguments are ignored as in src1824.',
                )
                parts = parts[:maximum]
            else:
                raise EraError(name + ' has too many arguments', code='E_ARGUMENT')
        if any(not p for p in parts):
            raise EraError(name + ' does not allow argument holes', code='E_ARGUMENT')
        a = [vm.eval(p) for p in parts]
        default = None
    if name in ('WAIT', 'FORCEWAIT', 'WAITANYKEY'):
        if name == 'WAITANYKEY':
            con.wait_count += 1
            if con.skip_print:
                return True
            if not con.no_wait:
                con.input(True, kind='key_wait', one=True, any_key=True)
        else:
            con.wait(force=name == 'FORCEWAIT')
        return True
    if name == 'TWAIT':
        ms = integer(a[0])
        force = integer(a[1]) != 0
        if ms > 86400000:
            raise EraError('TWAIT time budget (24 hours)', code='E_LIMIT')
        if ms <= 0:
            if force:
                raise Unsupported(
                    'TWAIT with nonpositive time and input disabled would wait forever'
                )
            con.wait()
        else:
            con.timed_wait(ms, force)
        return True
    timed = spec.get('timed', False)
    string = spec['value_type'] == 'string'
    one = spec.get('one', False)
    if timed:
        ms = integer(a[0])
        default = a[1]
        if ms > 86400000:
            raise EraError('Timed input budget (24 hours)', code='E_LIMIT')
        if string:
            if not isinstance(default, str):
                raise EraError(name + ' default must be a string', code='E_TYPE')
            if one:
                default = first_unit(default)
        else:
            default = integer(default)
            if one:
                if default == -(1 << 63):
                    raise EraError('TONEINPUT absolute-value overflow', code='E_ARITH')
                default = abs(default)
                if default >= 10:
                    denominator = int(math.pow(10.0, math.log10(float(default))))
                    if not 0 < denominator < 1 << 63:
                        raise Unsupported(
                            'TONEINPUT fallback float-to-Int64 overflow in the reference'
                        )
                    default //= denominator
        display = integer(a[2]) if len(a) > 2 else 1
        message = (
            a[3] if len(a) > 3 else vm.data.config.get('タイムアウトの表示', '時間切れ')
        )
        if not isinstance(message, str):
            raise EraError('Timeout message must be a string', code='E_TYPE')
        if display and ms > 0:
            con.warning(
                'countdown',
                'Timed input uses a deadline; graphical countdown updates are not reproduced.',
            )
        kind = 'timed_' + ('one_' if one else '') + ('string' if string else 'integer')
        value = con.input(
            string, default, kind=kind, timeout_ms=ms if ms > 0 else None, one=one
        )
        if con.last_timeout and message:
            con.write(message, True)
    else:
        if not string:
            default = integer(a[0]) if a else None
            if one and default is not None:
                default = None if default < 0 else int(str(default)[0])
        kind = ('one_' if one else '') + ('string' if string else 'integer')
        value = con.input(string, default, kind=kind, one=one)
    if not con.last_timeout:
        con._input_echo(str(value))
    vm.set('RESULTS' if string else 'RESULT', value)
    return True


def execute_direct(vm, op, arg, console):
    """Acquire using the captured console; keep direct input contracts.

    Parse ordinary defaults before acquisition. Timed commands evaluate all
    terms before arity/type checks, preserve countdown registration and timeout
    text before RESULT writes. WAIT/no-wait and exception behavior stay unchanged.
    """
    from .argument_counts import expect

    if op in {'INPUT', 'INPUTS', 'ONEINPUT', 'ONEINPUTS'}:
        parts = split_args(arg) if arg.strip() else []
        expect(parts, 0, 1, op)
        string = op.endswith('S')
        default = vm.eval(parts[0]) if parts else None
        if default is not None and isinstance(default, str) != string:
            raise EraError('INPUT default type mismatch', code='E_TYPE')
        value = console.input(string, default)
        if op.startswith('ONEINPUT') and len(str(value)) != 1:
            raise Unsupported(
                'ONEINPUT multiple-character entry; use one character followed by Enter'
            )
        vm.set('RESULTS' if string else 'RESULT', value)
        return True
    if op in {'TWAIT', 'TINPUT', 'TINPUTS'}:
        a = vm.args(arg)
        expect(a, 2, 2 if op == 'TWAIT' else 4, op)
        ms = integer(a[0])
        if not 0 <= ms <= 86_400_000:
            raise EraError('Timer outside 0..86400000 ms', code='E_ARGUMENT')
        if op == 'TWAIT':
            console.timed_wait(ms, bool(integer(a[1])))
            return True
        string = op == 'TINPUTS'
        default = a[1]
        if isinstance(default, str) != string:
            raise EraError('Timed input default type mismatch', code='E_TYPE')
        display = integer(a[2]) if len(a) > 2 else 1
        message = a[3] if len(a) > 3 else '時間切れ'
        if not isinstance(message, str):
            raise EraError('Timeout message must be a string', code='E_TYPE')
        if display:
            console.warning(
                'countdown',
                'TINPUT enforces its deadline without a graphical countdown.',
            )
        value = console.input(
            string,
            default,
            kind='timed_string' if string else 'timed_integer',
            timeout_ms=ms,
        )
        if console.last_timeout and message:
            console.write(message, True)
        vm.set('RESULTS' if string else 'RESULT', value)
        return True
    if op in {'WAIT', 'WAITANYKEY', 'FORCEWAIT'}:
        if arg:
            raise Unsupported(op + ' arguments')
        console.wait(force=op == 'FORCEWAIT')
        return True
    return False
