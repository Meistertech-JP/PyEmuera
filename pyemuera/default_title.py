"""Process.SystemProc.beginTitle's standard GameBase screen and selection."""

from .compat1824 import rule_string


def version_text(version: int) -> str:
    # C# integer division truncates toward zero, including negative versions.
    major = abs(version) // 1000 * (-1 if version < 0 else 1)
    remainder = version - major * 1000
    if version % 10 == 0:
        minor = abs(remainder) // 10 * (-1 if remainder < 0 else 1)
        width = 2
    else:
        minor, width = remainder, 3
    return str(major) + '.' + ('-' if minor < 0 else '') + str(abs(minor)).zfill(width)


def divider(vm):
    previous = vm.ui['style']
    vm.ui['style'] = 0
    try:
        vm.console.write_rule(rule_string(vm, vm.get('DRAWLINESTR')))
    finally:
        vm.ui['style'] = previous


def show(vm):
    console = vm.console
    divider(vm)
    vm.ui['alignment'] = 'CENTER'
    title = vm.get('GAMEBASE_TITLE')
    version = vm.get('GAMEBASE_VERSION')
    rows = [title]
    if version:
        rows.append(version_text(version))
    rows.extend([vm.get('GAMEBASE_AUTHOR'), '(' + vm.get('GAMEBASE_YEAR') + ')'])
    for text in rows:
        # PrintSingleLine omits null/empty strings, but the year is always ().
        if text:
            console.write(text, True)
    console.write('', True)
    information = vm.get('GAMEBASE_INFO')
    if information:
        console.write(information, True)
    vm.ui['alignment'] = 'LEFT'
    divider(vm)
    console.write('[0] ' + vm.data.settings.menu_new, True)
    console.write('[1] ' + vm.data.settings.menu_load, True)


def select(vm):
    while True:
        value = vm.console.input()
        vm.set('RESULT', value)
        if value in (0, 1):
            return value
        vm.console.write('無効な値です', True)
