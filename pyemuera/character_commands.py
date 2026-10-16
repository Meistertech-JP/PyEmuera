"""Roster mutations, separate from template queries and character file I/O.

commands.execute_command delegates here at its historical branch position.
Argument expressions are evaluated before mutation; conversion timing differs
between addition and indexed operations and is intentionally preserved. Data
owns storage/reordering, while these commands own role-variable bookkeeping.
No transactional rollback is added: an error can retain earlier additions.
"""

from .errors import EraError, Unsupported
from .expr import integer, parse
from .text import split_args

COMMANDS = frozenset(
    {
        'SORTCHARA',
        'ADDCHARA',
        'ADDSPCHARA',
        'ADDDEFCHARA',
        'ADDVOIDCHARA',
        'DELCHARA',
        'DELALLCHARA',
        'PICKUPCHARA',
        'SWAPCHARA',
        'COPYCHARA',
        'ADDCOPYCHARA',
    }
)
ROLE_NAMES = ('TARGET', 'MASTER', 'ASSI')


def _expect(values, minimum: int, maximum: int, name: str) -> None:
    if not minimum <= len(values) <= maximum:
        raise EraError(
            f'{name}: expected {minimum}..{maximum} arguments, got {len(values)}',
            code='E_ARGUMENT',
        )


def execute(vm, name: str, argument: str) -> bool:
    """Apply one roster command without changing the legacy dispatch contract."""
    if name == 'SORTCHARA':
        _sort(vm, argument)
    elif name in {'ADDCHARA', 'ADDSPCHARA', 'ADDDEFCHARA', 'ADDVOIDCHARA'}:
        _add(vm, name, argument)
    elif name in COMMANDS:
        _indexed(vm, name, argument)
    else:
        raise Unsupported(f'Character command {name}')
    return True


def _sort(vm, argument: str) -> None:
    """Sort around a pinned MASTER, then remap TARGET/MASTER/ASSI only.

    Resolve the variable descriptor once before reading the roster. Stable
    sorting and role writes follow the original order; PLAYER stays numeric.
    """
    parts = split_args(argument) if argument.strip() else []
    _expect(parts, 0, 2, 'SORTCHARA')
    target = parts[0] if parts else 'NO'
    order = parts[1].upper() if len(parts) > 1 else 'FORWARD'
    if target.upper() in ('BACK', 'FORWARD') and len(parts) == 1:
        order = target.upper()
        target = 'NO'
    if order not in ('BACK', 'FORWARD'):
        raise EraError('Invalid SORTCHARA order', code='E_ARGUMENT')
    target = target or 'NO'
    reference = vm.ref_node(
        parse(vm.program.expand(target)), allow_character_descriptor=True
    )
    if not reference.variable.character:
        raise EraError('SORTCHARA needs character variable', code='E_TYPE')

    master = vm.get('MASTER')
    indices = list(range(vm.data.character_count))
    remaining = [index for index in indices if index != master]
    remaining.sort(
        key=lambda index: reference.variable.get((index,) + reference.key[1:]),
        reverse=order == 'BACK',
    )
    if 0 <= master < len(indices):
        remaining.insert(master, master)
    old_roles = {name: vm.get(name) for name in ROLE_NAMES}
    vm.data.reorder_characters(remaining, remap_roles=False)
    mapping = {old: new for new, old in enumerate(remaining)}
    for name, value in old_roles.items():
        if value in mapping:
            vm.set(name, mapping[value])


def _add(vm, name: str, argument: str) -> None:
    """Check the SP gate, then evaluate/add each term without rollback."""
    if name in {'ADDCHARA', 'ADDSPCHARA'}:
        if name == 'ADDSPCHARA' and not vm.data.use_sp:
            raise EraError(
                'SPキャラ関係の機能は標準では使用できません'
                '(互換性オプション「SPキャラを使用する」をONにしてください)',
                code='E_ARGUMENT',
            )
        parts = split_args(argument) if argument.strip() else []
        _expect(parts, 1, 100000, name)
        for part in parts:
            vm.data.add_character(integer(vm.eval(part)), sp=name == 'ADDSPCHARA')
        return
    if name == 'ADDDEFCHARA':
        # Null ParentLabelLine is the native debug/direct-API exception.
        if vm.frames and vm.frames[-1].function.name != 'SYSTEM_TITLE':
            raise EraError(
                '@SYSTEM_TITLE以外でこの命令を使うことはできません', code='E_FUNCTION'
            )
        # VOID arguments were discarded by native ArgumentBuilder, not evaluated.
        vm.data.add_default_character(0)
        if vm.get('GAMEBASE_DEFAULTCHARA') > 0:
            vm.data.add_default_character(vm.get('GAMEBASE_DEFAULTCHARA'))
        return
    # ADDVOIDCHARA is VOID: even malformed/excess text is discarded.
    vm.data.add_pseudo_character()


def _indexed(vm, name: str, argument: str) -> None:
    """Convert every index before checking count/bounds or writing state."""
    indices = [integer(value) for value in vm.args(argument)]
    count = vm.data.character_count
    if name == 'DELALLCHARA':
        _expect(indices, 0, 0, name)
        vm.data.reorder_characters([], remap_roles=False)
    elif name == 'DELCHARA':
        if any(not 0 <= index < count for index in indices) or len(set(indices)) != len(
            indices
        ):
            raise EraError('Invalid/duplicate character index', code='E_CHARACTER')
        remaining = [index for index in range(count) if index not in set(indices)]
        vm.data.reorder_characters(remaining, remap_roles=False)
    elif name == 'PICKUPCHARA':
        _pickup(vm, indices, count)
    elif name == 'SWAPCHARA':
        _expect(indices, 2, 2, name)
        _validate_indices(indices, count)
        order = list(range(count))
        order[indices[0]], order[indices[1]] = order[indices[1]], order[indices[0]]
        vm.data.reorder_characters(order, remap_roles=False)
    else:
        expected = 1 if name == 'ADDCOPYCHARA' else 2
        _expect(indices, expected, expected, name)
        _validate_indices(indices, count)
        source = indices[0]
        destination = (
            vm.data.add_character(-1, void=True)
            if name == 'ADDCOPYCHARA'
            else indices[1]
        )
        _copy_character(vm.data, source, destination)


def _validate_indices(indices: list[int], count: int) -> None:
    if any(not 0 <= index < count for index in indices):
        raise EraError('Invalid character index', code='E_CHARACTER')


def _pickup(vm, indices: list[int], count: int) -> None:
    """Preserve VariableEvaluator.PickUpChara's evolving swap-list algorithm.

    This is not direct selection by original indices. Swaps adjust later picks;
    role matching uses that adjusted list, including its historical quirks.
    Negative indices are ignored, duplicates removed, PLAYER left untouched.
    """
    picks = list(dict.fromkeys(index for index in indices if index >= 0))
    if any(index >= count for index in picks):
        raise EraError('Invalid character index', code='E_CHARACTER')
    old_roles = {name: vm.get(name) for name in ROLE_NAMES}
    roles = {name: -1 for name in old_roles}
    order = list(range(count))
    for position in range(len(picks)):
        if position != picks[position]:
            other = picks[position]
            order[position], order[other] = order[other], order[position]
            if position in picks and picks.index(position) > position:
                picks[picks.index(position)] = other
        for name, value in old_roles.items():
            if roles[name] < 0 and picks[position] == value:
                roles[name] = position
    vm.data.reorder_characters(order[: len(picks)], remap_roles=False)
    for name, value in roles.items():
        vm.set(name, value)


def _copy_character(data, source: int, destination: int) -> None:
    """Replace destination's sparse character entries, including self-copy.

    Collect source entries before removing destination entries. Preserve the
    existing variable iteration/write order and leave non-character storage
    and role variables untouched. Missing source entries erase destination.
    """
    for variable in data.variables.values():
        if variable.character:
            copied = {
                (destination,) + key[1:]: value
                for key, value in variable.values.items()
                if key[0] == source
            }
            variable.values = {
                key: value
                for key, value in variable.values.items()
                if key[0] != destination
            }
            variable.values.update(copied)
