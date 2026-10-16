"""Iterative text-mode system flow and the TRAIN command scheduler.

The command queue stores CSV ids, whereas the menu uses ordinal positions of
TRAINNAME entries. These number spaces must not be interchanged. See SOURCES.md
for the documented contracts and the pinned reference inspected for edge cases.
"""

from __future__ import annotations
from collections import deque
from .errors import EraError, Unsupported, FlowSignal, TrainRequest, QuitSignal
from .expr import integer

STATES = {
    'TITLE',
    'FIRST',
    'SHOP',
    'TRAIN',
    'ABLUP',
    'AFTERTRAIN',
    'TURNEND',
    'LOADDATAEND',
}
DOTRAIN_PHASES = {'EVENTTRAIN', 'SHOW_STATUS', 'SHOW_USERCOM', 'USERCOM', 'EVENTCOMEND'}


def phase_call(vm, name, *, event=False, optional=True):
    previous = vm.train_phase
    vm.train_phase = name
    if vm.journal:
        vm.journal.phase = name
        vm.journal.note('system_call', function=name)
    try:
        return vm.event(name) if event else vm.call(name, optional=optional)
    finally:
        vm.train_phase = previous
        if vm.journal:
            vm.journal.phase = previous


def finish_queue(vm, *, skip_callback=False):
    """Clear before invoking the callback: STOPCALLTRAIN inside it is a no-op."""
    if vm.train_queue is None:
        return
    vm.train_queue = None
    vm.train_queue_index = 0
    vm.console.skip_print = skip_callback
    # CALLTRAINEND is not an event and runs inline for STOPCALLTRAIN.
    if vm.train_context and vm.train_phase is None:
        previous = vm.train_phase
        vm.train_phase = 'EVENTCOMEND'
        try:
            vm.call('CALLTRAINEND', optional=True)
        finally:
            vm.train_phase = previous
    else:
        vm.call('CALLTRAINEND', optional=True)


def request_begin(vm, keyword):
    # Keywords have the function case policy; Program currently normalizes
    # function names in its standard (case-insensitive) registration mode.
    from .config1824 import boolean

    config = vm.data.config
    if boolean(
        config.get('大文字小文字の違いを無視する', config.get('IgnoreCase', 'YES'))
    ) and not boolean(
        config.get(
            '関数・属性については大文字小文字を無視しない',
            config.get('CompatiFunctionNoignoreCase', 'NO'),
        )
    ):
        keyword = keyword.upper()
    if keyword not in STATES - {'LOADDATAEND'}:
        raise EraError(
            'BEGINのキーワード"' + keyword + '"は未定義です', code='E_ARGUMENT'
        )
    phase = vm.train_phase
    prohibited = phase in {
        'EVENTTRAIN',
        'SHOW_STATUS',
        'SHOW_USERCOM',
        'SHOW_SHOP',
        'SHOW_JUEL',
        'SHOW_ABLUP_SELECT',
        'AUTOSAVE',
        'TITLE_LOADGAME',
    } or bool(phase and phase.startswith('COM_ABLE'))
    if keyword != 'TITLE' and prohibited:
        root = vm.frames[0].function.name if vm.frames else (phase or '')
        raise EraError(
            '@' + root + '中でBEGIN命令を実行することはできません', code='E_FLOW'
        )
    vm.pending_begin = keyword
    try:
        vm._finish([0])
    finally:
        vm.ui.update(
            color=vm.default_color,
            style=0,
            alignment='LEFT',
            font=vm.data.config.get('フォント名', 'ＭＳ ゴシック'),
        )
        vm.console.reset_style()


def native_train_phase(vm):
    """DOTRAIN's PrintSystemLine(SystemState.ToString()) diagnostic."""
    names = {
        'EVENTTRAIN': 'Train_CallEventTrain',
        'SHOW_STATUS': 'Train_CallShowStatus',
        'SHOW_USERCOM': 'Train_CallShowUserCom',
        'EVENTCOM': 'Train_CallEventCom',
        'SOURCE_CHECK': 'Train_CallSourceCheck',
        'EVENTCOMEND': 'Train_CallEventComEnd',
        'USERCOM': 'Train_CallEventComEnd',
        'EVENTSHOP': 'Shop_CallEventShop',
        'SHOW_SHOP': 'Shop_CallShowShop',
        'USERSHOP': 'Shop_CallEventBuy',
        'EVENTBUY': 'Shop_CallEventBuy',
        'SHOW_JUEL': 'Ablup_CallShowJuel',
        'SHOW_ABLUP_SELECT': 'Ablup_CallShowAblupSelect',
    }
    phase = vm.train_phase or ''
    if phase in names:
        return names[phase]
    if phase.startswith('COM_ABLE'):
        return 'Train_CallComAbleXX'
    if phase.startswith('COM'):
        return 'Train_CallComXX'
    return 'Normal'


def train_command(vm, op, arg):
    if vm.method_depth:
        raise EraError(op + ' cannot run inside an expression function', code='E_FLOW')
    if op == 'STOPCALLTRAIN':
        # VOID argument builder discards any text without evaluating it.
        finish_queue(vm)
        return
    # Native ArgumentBuilder runs before DoInstruction, even when the VM
    # lazily constructs a first-used instruction. It may reject types or
    # constant arithmetic without executing any dynamic term.
    from .load_arguments import StaticContext
    from .load_builders import integer_terms

    function = (
        vm.frames[-1].function
        if vm.frames
        else vm.function(next(iter(vm.program.functions)))
    )
    context = StaticContext(vm, function)
    context.runtime = True
    integer_terms(context, op, arg)
    if op == 'DOTRAIN':
        if vm.train_context is None or vm.train_phase not in DOTRAIN_PHASES:
            vm.console.write(native_train_phase(vm), True)
            raise EraError(
                'DOTRAIN命令をこの位置で実行することはできません', code='E_FLOW'
            )
        # Process.ScriptProc clears these before GetIntValue, including when
        # that evaluation or its bounds check subsequently fails.
        vm.train_queue = None
        vm.train_queue_index = 0
    from .text import split_args

    parts = split_args(arg) if arg.strip() else []
    value = integer(vm.eval(parts[0])) if parts else 0
    if op == 'CALLTRAIN':
        # List<long>((int)count) occurs before assignment and can reject a
        # negative Int32 capacity without replacing the previous list.
        capacity = ((value + (1 << 31)) % (1 << 32)) - (1 << 31)
        if capacity < 0:
            raise EraError(
                'CALLTRAIN命令のキュー容量に負の値が指定されました', code='E_ARGUMENT'
            )
        vm.train_queue = deque()
        vm.train_queue_total = 0
        size = vm.data.variables['SELECTCOM'].dims[0]
        if value >= size:
            raise EraError(
                'CALLTRAIN命令の引数の値がSELECTCOMの要素数を超えています',
                code='E_ARGUMENT',
            )
        for i in range(1, capacity + 1):
            command = vm.get('SELECTCOM:' + str(i))
            vm.train_queue_total += 1
            if i > vm.train_queue_index:
                vm.train_queue.append(command)
        # Native SetCommnds does not reset its consumption index on replacement.
        return
    if value < 0:
        raise EraError('DOTRAIN命令に0未満の値が渡されました', code='E_INDEX')
    if value >= vm.data.variables['TRAINNAME'].dims[0]:
        raise EraError(
            'DOTRAIN命令にTRAINNAMEの配列数以上の値が渡されました', code='E_INDEX'
        )
    raise TrainRequest(value)


def transition_required(vm, event):
    phase_call(vm, event, event=True)
    raise EraError(f'@{event} returned without BEGIN', code='E_FLOW')


def run_flow(vm, initial='TITLE'):
    state = initial
    shop_from_normal = True
    while True:
        vm.tick()
        vm.flow_state = state
        if vm.journal:
            vm.journal.phase = state
            vm.journal.note('state', state=state)
        try:
            if state not in STATES:
                raise Unsupported('Engine state ' + state)
            if state in {'TITLE', 'SHOP'}:
                finish_queue(vm, skip_callback=True)
                vm.console.skip_print = False
            if state == 'TITLE':
                if 'SYSTEM_TITLE' in vm.program.functions:
                    vm.call('SYSTEM_TITLE')
                    raise EraError(
                        '@SYSTEM_TITLE returned without BEGIN/LOADDATA/QUIT',
                        code='E_FLOW',
                    )
                from .default_title import show, select, divider

                show(vm)
                choice = select(vm)
                if choice == 0:
                    vm.reset()
                    vm.data.add_default_character(0)
                    number = vm.get('GAMEBASE_DEFAULTCHARA')
                    if number > 0:
                        vm.data.add_default_character(number)
                    divider(vm)
                    state = 'FIRST'
                elif choice == 1:
                    if 'TITLE_LOADGAME' in vm.program.functions:
                        phase_call(vm, 'TITLE_LOADGAME', optional=False)
                    else:
                        from .save_commands import execute

                        execute(vm, {'name': 'LOADGAME'}, '')
            elif state == 'FIRST':
                transition_required(vm, 'EVENTFIRST')
            elif state == 'AFTERTRAIN':
                transition_required(vm, 'EVENTEND')
            elif state == 'TURNEND':
                transition_required(vm, 'EVENTTURNEND')
            elif state == 'LOADDATAEND':
                vm.call('SYSTEM_LOADEND', optional=True)
                vm.event('EVENTLOAD')
                shop(vm, loaded=True)
            elif state == 'SHOP':
                shop(vm, autosave=shop_from_normal)
            elif state == 'TRAIN':
                train(vm)
            elif state == 'ABLUP':
                ablup(vm)
        except FlowSignal as signal:
            vm.clear_frames()
            if signal.state == 'SHOP':
                shop_from_normal = state in {'TITLE', 'FIRST', 'AFTERTRAIN', 'TURNEND'}
            state = signal.state


def shop(vm, loaded=False, *, autosave=True):
    from .shop_purchase import item_on_sale, buy_item, callback_keeps_input

    if not loaded:
        phase_call(vm, 'EVENTSHOP', event=True)
        from .autosave import enabled, run

        if autosave and enabled(vm.data.config):
            previous = vm.train_phase
            vm.train_phase = 'AUTOSAVE'
            try:
                run(vm)
            finally:
                vm.train_phase = previous
        vm.complete_begin()
    while True:
        vm.tick()
        phase_call(vm, 'SHOW_SHOP', optional=False)
        while True:
            choice = vm.console.input()
            if not 0 <= choice < vm.data.settings.shop_limit:
                vm.set('RESULT', choice)
                phase_call(vm, 'USERSHOP', optional=False)
                if callback_keeps_input(vm.console):
                    continue
                break
            if not item_on_sale(vm.data, choice):
                vm.console.reuse_line('売っていません。')
                continue
            if not buy_item(vm, choice):
                vm.console.reuse_line('お金が足りません。')
                continue
            phase_call(vm, 'EVENTBUY', event=True)
            if callback_keeps_input(vm.console):
                continue
            break


def clear_selection_temporaries(vm):
    for name in ('UP', 'DOWN', 'LOSEBASE'):
        vm.data.variables[name].values.clear()


def select_from_menu(vm):
    if vm.train_queue is not None:
        vm.console.skip_print = True
    phase_call(vm, 'SHOW_STATUS')
    names = vm.data.variables['TRAINNAME']
    ids = vm.data.train_ids
    menu = {}
    available_csv = set()
    for ordinal, csv_id in enumerate(ids):
        test = 'COM_ABLE' + str(csv_id)
        enabled = (
            phase_call(vm, test) != 0
            if test in vm.program.functions
            else vm.data.settings.com_able_default != 0
        )
        if enabled:
            menu[ordinal] = csv_id
            available_csv.add(csv_id)
            if vm.train_queue is None:
                vm.console.write(f'[{ordinal}] {names.get((csv_id,))}  ')
    if vm.train_queue is None:
        vm.console.write('', True)
    phase_call(vm, 'SHOW_USERCOM')
    # The legacy flow turns suppression off after SHOW_USERCOM.
    vm.console.skip_print = False
    clear_selection_temporaries(vm)
    if vm.train_queue is not None:
        # Empty initial/replaced queues leave native Train_CallShowUserCom
        # pending without input or callback. Retain a VM safepoint in this
        # otherwise idle engine state (explicit instruction budgets still work).
        while not vm.train_queue:
            vm.tick()
        choice = vm.train_queue.popleft()
        vm.train_queue_index += 1
        vm.console.write(
            f'＜コマンド連続実行：{vm.train_queue_index}/{vm.train_queue_total}＞', True
        )
        selected = choice if choice in available_csv else None
    else:
        choice = vm.console.input()
        selected = menu.get(choice)
    if selected is None:
        vm.set('RESULT', choice)
        if vm.train_queue is not None:
            vm.console.write('コマンドを実行できませんでした', True)
        phase_call(vm, 'USERCOM')
    return selected


def execute_selected(vm, csv_id):
    vm.set('SELECTCOM', csv_id)
    vm.data.variables['NOWEX'].values.clear()
    phase_call(vm, 'EVENTCOM', event=True)
    # EVENTCOM may deliberately change SELECTCOM.
    result = phase_call(vm, 'COM' + str(vm.get('SELECTCOM')), optional=False)
    if not result:
        return False
    phase_call(vm, 'SOURCE_CHECK')
    vm.data.variables['SOURCE'].values.clear()
    waited = vm.console.wait_count
    phase_call(vm, 'EVENTCOMEND', event=True)
    return vm.console.wait_count == waited


def train(vm):
    for name, value in [('ASSIPLAY', 0), ('PREVCOM', -1), ('NEXTCOM', -1)]:
        vm.set(name, value)
    for name in ('TFLAG', 'GOTJUEL', 'TEQUIP', 'EX', 'PALAM', 'SOURCE'):
        vm.data.variables[name].values.clear()
    for character in range(vm.data.character_count):
        vm.data.reset_stain(character)
    vm.train_context = True
    pending = None
    first = True
    try:
        while True:
            try:
                vm.tick()
                if first:
                    first = False
                    phase_call(vm, 'EVENTTRAIN', event=True)
                if pending is not None:
                    selected, pending = pending, None
                    clear_selection_temporaries(vm)
                elif vm.get('NEXTCOM') >= 0:
                    selected = vm.get('NEXTCOM')
                    # This surprising reset to ZERO is the historical behavior,
                    # not -1. Scripts must clear it; the instruction budget still applies.
                    vm.set('NEXTCOM', 0)
                else:
                    selected = select_from_menu(vm)
                needs_wait = (
                    execute_selected(vm, selected) if selected is not None else False
                )
                if (
                    vm.train_queue is not None
                    and vm.train_queue_index == vm.train_queue_total
                ):
                    finish_queue(vm)
                if needs_wait:
                    vm.console.wait()
                # PREVCOM is script-managed, apart from its BEGIN TRAIN reset.
            except TrainRequest as request:
                vm.clear_frames()
                vm.train_queue = None  # DOTRAIN cancels without CALLTRAINEND.
                vm.train_queue_index = 0
                pending = request.command
    finally:
        vm.train_context = None
        vm.train_phase = None


def ablup(vm):
    while True:
        vm.tick()
        phase_call(vm, 'SHOW_JUEL')
        phase_call(vm, 'SHOW_ABLUP_SELECT')
        while True:
            choice = vm.console.input()
            vm.set('RESULT', choice)
            if not 0 <= choice < 100:
                vm.call('USERABLUP', optional=True)
                break
            name = 'ABLUP' + str(choice)
            if name in vm.program.functions:
                vm.call(name)
                break


def execute_train(vm, spec, arg):
    """Command binding; TRAIN state and transitions stay owned by this module."""
    train_command(vm, spec['name'], arg)
    return True
