"""Apply UPCHECK/CUPCHECK as one ordered Emuera1824+v24 operation.

Argument analysis belongs to the loader. This runtime boundary selects one
character, applies each eligible PALAM change and its notification, then clears
complete delta arrays. A failure leaves earlier commits and output intact; it
must not trigger rollback or unconditional cleanup.
"""

from __future__ import annotations

from .data import Variable
from .errors import EraError, Unsupported
from .expr import i64, integer
from .text import split_args


def _array_length(variable: Variable) -> int:
    # Variable keeps fallback dimensions for forbidden ERB descriptors, while
    # native internal arrays are allocated with zero length in that condition.
    return 0 if variable.forbidden else variable.dims[0]


def _read_array(variable: Variable, key: tuple[int, ...]):
    """Read native internal arrays without the public forbidden-name lookup.

    A zero-length forbidden array can still be reached by the two native loop
    length checks. Report that access using the existing E_INDEX convention;
    native CLR exception wording is a separately unmeasured diagnostic detail.
    """
    if variable.forbidden:
        dimensions = (None, 0) if variable.character else (0,)
        diagnostic = None
        if not variable.character:
            diagnostic = (
                f'配列型変数{variable.name}の第１引数({key[0]})は配列の範囲外です'
            )
        raise EraError(
            f'{variable.name}{key}: array index outside {dimensions}',
            code='E_INDEX',
            diagnostic_message=diagnostic,
        )
    return variable.get(key)


def _notification_prefix(
    parameter_names: Variable,
    palam: Variable,
    up: Variable,
    down: Variable,
    parameter_key: tuple[int, int],
    delta_key: tuple[int, ...],
) -> str:
    """Build the pre-update part using the source's name/value access order.

    Negative deltas still enter the arithmetic, but only positive components
    appear as +UP/-DOWN. Reading the name precedes the PALAM commit, so a name
    bound failure preserves the current parameter and all pending deltas.
    """
    text = (
        _read_array(parameter_names, (parameter_key[1],))
        + ' '
        + str(_read_array(palam, parameter_key))
    )
    if _read_array(up, delta_key) > 0:
        text += '+' + str(_read_array(up, delta_key))
    if _read_array(down, delta_key) > 0:
        text += '-' + str(_read_array(down, delta_key))
    return text


def _update_character(
    vm,
    character: int,
    up: Variable,
    down: Variable,
    character_local: bool,
    skip_print: bool,
) -> None:
    """Commit eligible cells, then Print and NewLine with the current style.

    The two native length checks both compare with the original PALAM length.
    They are not a three-way minimum: a later DOWN check can enlarge the loop
    beyond UP. Arrays retain their allocated sizes and a later access may fail.
    All accesses use normal Variable methods so diagnostics and write observers
    see the committed prefix. Signed arithmetic wraps without a zero clamp.
    """
    palam = vm.data.variables['PALAM']
    parameter_names = vm.data.variables['PALAMNAME']
    parameter_length = _array_length(palam)
    length = parameter_length
    if parameter_length > _array_length(up):
        length = _array_length(up)
    if parameter_length > _array_length(down):
        length = _array_length(down)

    for index in range(length):
        parameter_key = (character, index)
        delta_key = parameter_key if character_local else (index,)
        # Preserve the native && short circuit before any PALAM/name access.
        if _read_array(up, delta_key) <= 0 and _read_array(down, delta_key) <= 0:
            continue
        if not skip_print:
            text = _notification_prefix(
                parameter_names,
                palam,
                up,
                down,
                parameter_key,
                delta_key,
            )
        previous = _read_array(palam, parameter_key)
        change = i64(_read_array(up, delta_key) - _read_array(down, delta_key))
        palam.set(parameter_key, i64(previous + change))
        if not skip_print:
            text += '=' + str(_read_array(palam, parameter_key))
            # Separate calls preserve a Print failure versus a NewLine failure.
            # Console owns both logical history and physical terminal projection.
            vm.console.write(text)
            vm.console.write('', True)


def _clear_delta_arrays(up: Variable, down: Variable, character: int | None) -> None:
    """Clear all of UP/CUP first, then all of DOWN/CDOWN on normal completion.

    Character-local arrays clear only the selected character's complete slice.
    Clearing deliberately uses setters, including zero cells, and is not in a
    finally block: a failure preserves completed writes and the uncleared suffix.
    """
    for variable in (up, down):
        for index in range(_array_length(variable)):
            key = (index,) if character is None else (character, index)
            variable.set(key, 0)


def execute(vm, name: str, argument: str) -> bool:
    """Select and update one target without evaluating ignored expressions.

    UPCHECK ignores its argument text and uses TARGET. CUPCHECK evaluates only
    its first term; omission selects 0. The loader owns warnings and static
    analysis of extra CUPCHECK terms. Targets stay Int64 through validation.
    Invalid UP targets still clear global deltas; invalid CUP targets change
    nothing. RESULT, roles and RNG are unchanged except by the first CUP term.
    """
    if name not in {'UPCHECK', 'CUPCHECK'}:
        raise Unsupported('Parameter update command ' + name)
    from .parameter_arguments import lazy

    lazy(vm, name, argument)
    character_local = name == 'CUPCHECK'
    if character_local:
        terms = split_args(argument) if argument.strip() else []
        first_term = terms[0] if terms else ''
        character = integer(vm.eval(first_term)) if first_term else 0
        if not 0 <= character < vm.data.character_count:
            return True
    else:
        character = vm.get('TARGET')
    up = vm.data.variables['CUP' if character_local else 'UP']
    down = vm.data.variables['CDOWN' if character_local else 'DOWN']
    if 0 <= character < vm.data.character_count:
        _update_character(
            vm, character, up, down, character_local, vm.console.skip_print
        )
    _clear_delta_arrays(up, down, character if character_local else None)
    return True
