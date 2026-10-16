"""Source-reviewed SHOP entry autosave; codecs and atomic writes stay in Saves."""

import datetime
from .errors import EraError


def enabled(config):
    value = config.get('オートセーブを行なう', config.get('AutoSave', 'YES'))
    from .data import _callname_config_bool

    try:
        return _callname_config_bool(value)
    except ValueError:
        # Invalid ConfigItem<bool> does not replace the true source default.
        return True


def run(vm):
    # A custom routine completely replaces the engine's slot-99 writer.
    if 'SYSTEM_AUTOSAVE' in vm.program.functions:
        vm.call('SYSTEM_AUTOSAVE')
        return
    vm.set('SAVEDATA_TEXT', datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S') + ' ')
    # ProcessState.Return applies pending BEGIN at the outermost callback
    # return, changing SystemState before endAutoSaveCallSaveInfo is reached.
    # A transferred SAVEINFO must therefore leave the existing save untouched.
    vm.call('SAVEINFO', optional=True)
    try:
        saved = bool(vm.saves.write(99, vm.get('SAVEDATA_TEXT')))
    except (EraError, OSError) as exc:
        if isinstance(exc, EraError) and exc.code == 'E_SAVE_IO':
            vm.console.write(exc.message, True)
        saved = False
    if not saved:
        vm.console.write('オートセーブ中に予期しないエラーが発生しました', True)
        vm.console.write('オートセーブをスキップします', True)
        vm.console.wait()
