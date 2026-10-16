"""Read-only character template and roster queries over evaluated arguments.

AST validation/evaluation remains in builtins.call; its value-handler boundary
also owns Python-to-E_ARGUMENT translation. These queries do not write state,
evaluate expressions or draw RNG values. Templates are distinct from live
character variables: indexed defaults/duplicate rows live here, while scalar
CALLNAME is resolved once by GameData when templates are loaded.
"""

from .data import CHAR_KEYS, character_csv_integer
from .errors import EraError, Unsupported
from .expr import integer

SCALAR_FIELDS = frozenset({'NAME', 'CALLNAME', 'NICKNAME', 'MASTERNAME'})


def function(vm, name: str, values: list) -> int | str:
    if name == 'EXISTCSV':
        number = integer(values[0])
        special = _special_flag(vm.data, values, 1)
        return int(vm.data.template(number, special) is not None)
    if name.startswith('CSV'):
        return _template_value(vm.data, name[3:], values)
    if name in {'GETCHARA', 'GETSPCHARA'}:
        return _character_index(vm.data, name, values)
    raise Unsupported(f'Expression function {name}')


def _template_value(data, field: str, values: list) -> int | str:
    """Convert supplied positions before lookup, then scan rows in file order.

    Indexed duplicate rows overwrite earlier values. CALLNAME uses the frozen
    template value shared with live initialization; its option and final NAME
    were resolved during loading, never from the current live character state.
    """
    number = integer(values[0])
    scalar = field in SCALAR_FIELDS
    index = 0 if scalar else integer(values[1])
    special_position = 1 if scalar else 2
    special = _special_flag(data, values, special_position)
    rows = data.template(number, special)
    if rows is None:
        raise EraError(
            f'No Chara CSV for ID {number} (SP={int(special)})', code='E_CSV'
        )
    if field == 'CALLNAME':
        return data.template_callname(number, special)

    wanted = 'CSTR' if field == 'STR' else field
    if not scalar:
        index = _checked_template_index(data, wanted, index)
    string = scalar or wanted == 'CSTR'
    # Template dictionaries default to zero, independently of live RELATION.
    result = '' if string else 0
    for row in rows:
        if CHAR_KEYS.get(row[0], row[0].upper()) != wanted or len(row) < 2:
            continue
        if scalar:
            result = row[1]
            continue
        numeric, row_index = character_csv_integer(row[1])
        if not numeric:
            row_index = data.index_of(wanted, row[1])
        if row_index != index:
            continue
        if string:
            result = row[2] if len(row) > 2 else ''
        else:
            numeric, result = character_csv_integer(row[2] if len(row) > 2 else '')
            if not numeric:
                result = 1
    return result


def _special_flag(data, values: list, position: int) -> bool:
    """Optional SP is a flag, not an index; omission means zero.

    Native CSV methods reject a nonzero flag with SP disabled before looking
    for the template. Negative flags remain valid when SP is enabled.
    """
    value = values[position] if len(values) > position else None
    special = value is not None and integer(value) != 0
    if special and not data.use_sp:
        raise EraError(
            'SPキャラ関係の機能は標準では使用できません'
            '(互換性オプション「SPキャラを使用する」をONにしてください)',
            code='E_ARGUMENT',
        )
    return special


def _checked_template_index(data, field: str, index: int) -> int:
    """Check configured template extent after template existence is known.

    BASE uses the larger BASE/MAXBASE extent. Numeric queries check Int64;
    CSTR follows the source's unchecked Int32 cast *before* bounds checking.
    CSVSTR keeps its existing local alias to CSTR; it is not a native name.
    """
    if field == 'CSTR':
        index = (index + (1 << 31)) % (1 << 32) - (1 << 31)
    fields = ('BASE', 'MAXBASE') if field == 'BASE' else (field,)
    lengths = [
        0 if data.variables[name].forbidden else data.variables[name].dims[0]
        for name in fields
    ]
    if not 0 <= index < max(lengths):
        message = (
            'CSTRの参照可能範囲外を参照しました'
            if field == 'CSTR'
            else '参照可能範囲外を参照しました'
        )
        raise EraError(message, code='E_INDEX')
    return index


def _character_index(data, name: str, values: list) -> int:
    """Return the first matching live index, with the existing SP preference.

    Keep NO reads and both CFLAG passes in order. In particular, conversion of
    the requested ID happens inside the scan, and the optional fallback flag
    is converted only when GETCHARA has no normal match in SP mode.
    """
    matches = [
        index
        for index in range(data.character_count)
        if data.variables['NO'].get((index,)) == integer(values[0])
    ]
    if not data.use_sp:
        return matches[0] if matches else -1
    normal = [index for index in matches if not data.variables['CFLAG'].get((index, 0))]
    special = [index for index in matches if data.variables['CFLAG'].get((index, 0))]
    if name == 'GETSPCHARA':
        choices = special
    else:
        choices = normal or (special if len(values) > 1 and integer(values[1]) else [])
    return choices[0] if choices else -1
