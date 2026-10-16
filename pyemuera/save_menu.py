"""Standard save menus over the existing read-only-original / writable-overlay service.

Reference: src1824 Process.SystemProc.cs 782-1006, Config.cs 153-162.
No game identifier or game-specific slot rules are used.
"""

from __future__ import annotations
from dataclasses import dataclass
import datetime
from .errors import EraError, FlowSignal


@dataclass(frozen=True)
class SlotInfo:
    slot: int
    available: bool
    exists: bool
    description: str
    provider: str | None
    status: int


class SaveRepository:
    """Read-only metadata facade; all mutations stay in Saves / its codecs."""

    def __init__(self, saves):
        self.saves = saves

    def metadata(self, slot: int) -> SlotInfo:
        # Use the exact same provider selection for listing and loading.
        try:
            path = self.saves.candidate(slot)
            if path is None:
                return SlotInfo(slot, False, False, '（データなし）', None, 1)
            status, description = self.saves.check(slot)
            provider = (
                'private-json'
                if path == self.saves.path(slot)
                else (
                    'private-native'
                    if path == self.saves.native_path(slot)
                    else 'original-native'
                )
            )
            return SlotInfo(slot, status == 0, True, str(description), provider, status)
        except (EraError, OSError) as exc:
            return SlotInfo(slot, False, True, '（読込不可） ' + str(exc), None, 4)

    def load(self, slot: int):
        return self.saves.load(slot)

    def write(self, slot: int, description: str):
        return self.saves.write(slot, description)


def save_slot_count(vm) -> int:
    try:
        value = int(vm.data.config.get('表示するセーブデータ数', '20'))
    except (ValueError, TypeError):
        value = 20
    return min(80, max(20, value))


class SaveMenu:
    PAGE_SIZE = 20
    AUTOSAVE = 99
    BACK = 100

    def __init__(self, vm, saving: bool):
        self.vm = vm
        self.console = vm.console
        self.saving = saving
        self.repository = SaveRepository(vm.saves)
        self.count = save_slot_count(vm)
        # Source preserves page between calls; keep it on Saves, not in global UI state.
        self.page = min(getattr(vm.saves, 'menu_page', 0), (self.count - 1) // 20)

    def show(self):
        c = self.console
        c.write(
            '何番にセーブしますか？' if self.saving else '何番をロードしますか？', True
        )
        self.visible = {}
        for page in range((self.count + 19) // 20):
            start, end = page * 20, min(self.count, page * 20 + 20)
            if page != self.page:
                c.write(f'[{start:2d}] セーブデータ{start:2d}～{end-1:2d}を表示', True)
            else:
                for slot in range(start, end):
                    info = self.repository.metadata(slot)
                    self.visible[slot] = info
                    c.write(f'[{slot:2d}] {info.description}', True)
        if not self.saving:
            info = self.repository.metadata(99)
            self.visible[99] = info
            c.write(f'[99] {info.description}', True)
        c.write('[100] 戻る', True)

    def run(self):
        c = self.console
        self.show()
        while True:
            slot = c.input()
            if slot == self.BACK:
                return
            if slot == -1:
                # Documented bridge for older PyEmuera input fixtures, not src1824 UI.
                c.warning(
                    'legacy-save-cancel',
                    '-1 is a legacy PyEmuera cancel alias; standard menu uses 100.',
                )
                return
            if 0 <= slot < self.count and slot // 20 != self.page:
                self.page = slot // 20
                self.vm.saves.menu_page = self.page
                self.show()
                continue
            if not (0 <= slot < self.count or (not self.saving and slot == 99)):
                c.write('無効な値です', True)
                continue
            info = self.repository.metadata(slot)
            if not self.saving:
                if not info.available:
                    c.write(
                        (
                            'データがありません'
                            if not info.exists
                            else 'このデータは読み込めません: ' + info.description
                        ),
                        True,
                    )
                    self.show()
                    continue
                # Metadata is not a substitute for full codec validation.
                # load() validates all state before committing; do not swallow failures.
                if self.repository.load(slot):
                    raise FlowSignal('LOADDATAEND')
                self.show()
                continue
            # A corrupt or foreign overlay still counts as an existing file for
            # preservation: this is an explicitly safer PyEmuera extension.
            if info.exists:
                c.write('既にデータが存在します。上書きしますか？', True)
                c.write('[0] はい    [1] いいえ', True)
                while True:
                    answer = c.input()
                    if answer in (0, 1):
                        break
                    c.write('無効な値です', True)
                if answer == 1:
                    self.show()
                    continue
            self.vm.set(
                'SAVEDATA_TEXT',
                datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S') + ' ',
            )
            self.vm.call('SAVEINFO', optional=True)
            self.repository.write(slot, self.vm.get('SAVEDATA_TEXT'))
            return


def run_save_menu(vm, *, saving=False):
    SaveMenu(vm, saving).run()
