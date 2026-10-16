"""Validated, immutable declarative contracts shared by compiler/runtime/audit.

Only bundled data is loaded. JSON names are NOT Python import paths, expressions,
or executable snippets. Implementations are bound by a hard-coded dispatcher.
"""

from __future__ import annotations
from functools import lru_cache
from importlib.resources import files
import json
from types import MappingProxyType
from .errors import EraError

PRINT_MODES = frozenset(
    {
        'raw',
        'form',
        'values',
        'string',
        'string_form',
        'button',
        'bar',
        'rule',
        'rule_raw',
        'rule_default',
    }
)
FAMILIES = frozenset(
    {
        'print',
        'text_length',
        'vm_control',
        'runtime_effect',
        'decimal_instruction',
        'unicode_instruction',
        'console_history',
        'shop_display',
        'status_display',
        'train',
        'call',
        'display',
        'expression',
        'structural',
        'random',
        'input',
        'save',
        'character',
        'array',
        'html',
        'platform',
        'source_unimplemented',
        'numeric_instruction',
        'display_element',
        'scalar_numeric',
        'character_operation',
        'parameter_update',
        'state_operation',
    }
)


def _error(message):
    return EraError('Invalid bundled specification: ' + message, code='E_SPEC')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _error('duplicate key ' + key)
        result[key] = value
    return result


def _freeze(x):
    if isinstance(x, dict):
        return MappingProxyType({k: _freeze(v) for k, v in x.items()})
    if isinstance(x, list):
        return tuple(_freeze(v) for v in x)
    return x


def _validate_schema(document, kind):
    if (
        not isinstance(document, dict)
        or document.get('schema_version') != 1
        or kind not in document
        or not isinstance(document[kind], dict)
    ):
        raise _error('schema/version for ' + kind)


def _validate_entry(name, spec):
    if (
        not name
        or not name.isascii()
        or not all(c.isupper() or c.isdigit() or c == '_' for c in name)
        or not isinstance(spec, dict)
    ):
        raise _error('entry name/type')


def _validate_command(name, spec):
    """Check shared flags first, then the selected command family in r42 order."""
    if spec.get('family') not in FAMILIES:
        raise _error('unknown family for ' + name)
    if 'force_set_argument' in spec and type(spec['force_set_argument']) is not bool:
        raise _error('force-set-argument flag ' + name)
    if 'load_argument_contract' in spec and spec['load_argument_contract'].get(
        'handler'
    ) not in (
        'call_terms',
        'integer_terms',
        'any_terms',
        'case_terms',
        'void_terms',
        'parameter_terms',
        'character_terms',
        'times_terms',
        'nullable_terms',
    ):
        raise _error('load argument handler ' + name)
    if spec.get('load_argument_contract', {}).get(
        'handler'
    ) == 'character_terms' and name not in ('ADDCHARA', 'ADDSPCHARA'):
        raise _error('character argument binding ' + name)
    if spec.get('load_argument_contract', {}).get(
        'handler'
    ) == 'parameter_terms' and name not in ('UPCHECK', 'CUPCHECK'):
        raise _error('parameter argument binding ' + name)
    if 'method_safe' in spec and type(spec['method_safe']) is not bool:
        raise _error('method-safe flag ' + name)
    if spec['family'] == 'state_operation' and name not in (
        'RESET_STAIN',
        'RESETGLOBAL',
        'PUTFORM',
        'RESETDATA',
        'SKIPDISP',
        'NOSKIP',
        'ENDNOSKIP',
    ):
        raise _error('closed state operation ' + name)
    if spec['family'] == 'scalar_numeric':
        from .scalar_numeric import COMMAND_NAMES

        if name not in COMMAND_NAMES:
            raise _error('scalar numeric command ' + name)
    if spec['family'] == 'numeric_instruction':
        _validate_numeric_instruction_command(name, spec)
    if spec['family'] == 'input':
        _validate_input_command(name, spec)
    if spec['family'] == 'print':
        _validate_print_command(name, spec)
    elif spec['family'] == 'text_length':
        _validate_text_length_command(name, spec)


def _validate_numeric_instruction_command(name, spec):
    if spec.get('argument_builder') not in ('power_int64_destination',) or spec.get(
        'instruction_handler'
    ) not in ('power_int64_destination',):
        raise _error('closed instruction handler ' + name)
    if (
        spec.get('min_args') != 3
        or spec.get('max_args') != 3
        or spec.get('extra_argument_policy') != 'warn_ignore'
    ):
        raise _error('numeric instruction arguments ' + name)


def _validate_input_command(name, spec):
    lo, hi = spec.get('min_args'), spec.get('max_args')
    if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= 4:
        raise _error('input arity ' + name)
    if spec.get('argument_mode') not in (
        'expression_list',
        'raw_form_default',
    ):
        raise _error('input argument mode ' + name)
    for key in ('timed', 'one'):
        if key in spec and type(spec[key]) is not bool:
            raise _error('input flag ' + name + '.' + key)


def _validate_print_command(name, spec):
    if spec.get('argument_mode') not in PRINT_MODES or spec.get('column') not in (
        None,
        'left',
        'right',
    ):
        raise _error('print mode for ' + name)
    for flag in (
        'newline',
        'wait',
        'single',
        'kana',
        'default_color',
        'skip_before_eval',
    ):
        if type(spec.get(flag)) is not bool:
            raise _error('print flag ' + name + '.' + flag)
    if spec['wait'] and not spec['newline']:
        raise _error('wait without line break ' + name)


def _validate_text_length_command(name, spec):
    if spec.get('argument_mode') not in ('raw', 'form') or spec.get(
        'length_unit'
    ) not in ('cp932', 'utf16'):
        raise _error('text length mode ' + name)


def _validate_function(name, spec):
    """Validate arity, handler and diagnostic policy without reordering faults."""
    lo, hi = spec.get('min_args'), spec.get('max_args')
    if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= 100000:
        raise _error('function arity ' + name)
    if (
        spec.get('handler')
        not in (
            'legacy',
            'compat1824',
            'character',
            'html',
            'platform',
            'regex1824',
            'resource',
            'scalar_numeric',
        )
        or type(spec.get('reference_first')) is not bool
    ):
        raise _error('function handler ' + name)
    if spec.get('handler') == 'scalar_numeric':
        from .scalar_numeric import FUNCTION_NAMES

        if name not in FUNCTION_NAMES or spec['reference_first']:
            raise _error('scalar numeric function ' + name)
    if 'argument_diagnostic_policy' in spec:
        _validate_function_diagnostic_policy(name, spec, lo, hi)


def _validate_function_diagnostic_policy(name, spec, lo, hi):
    policy = spec['argument_diagnostic_policy']
    if policy == 'v24_default_fixed':
        if (
            lo != hi
            or len(spec.get('argument_diagnostic_types', [])) != lo
            or any(
                t not in ('Int64', 'string') for t in spec['argument_diagnostic_types']
            )
        ):
            raise _error('function diagnostic policy ' + name)
    elif policy == 'v24_substring':
        if (
            lo != 1
            or hi != 3
            or spec.get('argument_diagnostic_types') != ['string', 'Int64', 'Int64']
        ):
            raise _error('substring diagnostic contract ' + name)
    elif policy == 'v24_numeric_variadic':
        if lo != 1 or hi <= 1 or spec.get('argument_diagnostic_types') != ['Int64']:
            raise _error('variadic diagnostic contract ' + name)
    else:
        raise _error('function diagnostic policy ' + name)


def _validate_variable(name, spec):
    for key in ('dimensions', 'legacy_a9_dimensions'):
        dims = spec.get(key)
        if (
            not isinstance(dims, list)
            or not 1 <= len(dims) <= 3
            or any(type(n) is not int or not 1 <= n <= 1000000 for n in dims)
        ):
            raise _error('variable dimensions ' + name)
    if len(spec['dimensions']) != len(spec['legacy_a9_dimensions']):
        raise _error('variable rank migration ' + name)


def _validate_syntax(name, spec):
    if spec.get('kind') not in (
        'conditional',
        'single_if',
        'loop',
        'select',
        'data',
        'try_list',
        'try_catch',
        'display_guard',
        'marker',
        'loop_transfer',
    ):
        raise _error('syntax kind ' + name)
    if spec['kind'] == 'loop' and spec.get('primitive') not in (
        '_IF',
        '_FOR',
        '_REPEAT',
        '_DO',
    ):
        raise _error('loop lowering ' + name)


def validate_document(document, kind):
    """Validate entries in insertion order, then freeze only after full success.

    Each helper keeps the r42 order of property reads and first-error checks.
    Unknown JSON keys and an explicitly supplied unknown kind retain the old
    behavior; this function does not tighten the bundled schema while refactoring.
    """
    _validate_schema(document, kind)
    for name, spec in document[kind].items():
        _validate_entry(name, spec)
        if kind == 'commands':
            _validate_command(name, spec)
        elif kind == 'functions':
            _validate_function(name, spec)
        elif kind == 'variables':
            _validate_variable(name, spec)
        elif kind == 'syntax':
            _validate_syntax(name, spec)
    return _freeze(document[kind])


@lru_cache(maxsize=4)
def load(kind):
    if kind not in ('commands', 'functions', 'syntax', 'variables'):
        raise _error('unknown specification kind')
    try:
        text = (
            files('pyemuera')
            .joinpath('specs', kind + '.json')
            .read_text(encoding='utf-8')
        )
        document = json.loads(text, object_pairs_hook=_unique)
        return validate_document(document, kind)
    except (OSError, ValueError) as exc:
        raise _error(kind + ': ' + str(exc)) from exc


COMMAND_SPECS = load('commands')
FUNCTION_SPECS = load('functions')
SYNTAX_SPECS = load('syntax')
VARIABLE_SPECS = load('variables')


def _validate_cross_references(syntax_specs, command_specs, function_specs):
    """Check closers before expression bindings, in original insertion order."""
    for name, spec in syntax_specs.items():
        end = spec.get('closes_with')
        if end is not None and (
            end not in syntax_specs or syntax_specs[end]['kind'] != 'marker'
        ):
            raise _error('missing closer ' + name)
    for name, spec in command_specs.items():
        if spec['family'] == 'expression' and name not in function_specs:
            raise _error('missing function ' + name)


_validate_cross_references(SYNTAX_SPECS, COMMAND_SPECS, FUNCTION_SPECS)


def command_spec(name):
    return COMMAND_SPECS.get(name)


@lru_cache(maxsize=1)
def fingerprint():
    import hashlib

    h = hashlib.sha256()
    for kind in ('commands', 'functions', 'syntax', 'variables'):
        h.update(kind.encode('ascii') + b'\0')
        h.update(files('pyemuera').joinpath('specs', kind + '.json').read_bytes())
    return h.hexdigest()


def describe(name):
    def thaw(value):
        if isinstance(value, MappingProxyType):
            return {k: thaw(v) for k, v in value.items()}
        if isinstance(value, tuple):
            return [thaw(v) for v in value]
        return value

    name = name.upper()
    return {
        'name': name,
        'specs_sha256': fingerprint(),
        **{
            k: thaw(table[name])
            for k, table in [
                ('command', COMMAND_SPECS),
                ('function', FUNCTION_SPECS),
                ('syntax', SYNTAX_SPECS),
                ('variable', VARIABLE_SPECS),
            ]
            if name in table
        },
    }
