"""Narrow native fatal-diagnostic projections; internal error codes stay intact.

HeaderFileLoader catches an unclosed quote as a level-2 header warning, then
Process.Initialize stops. endNormal is instead a runtime system-flow error.
Do not infer the same phase from the error code alone or run script expressions.
"""


def describe(error):
    location = error.location
    if (
        error.code == 'E_SYNTAX'
        and error.message == 'Unclosed quoted string'
        and location is not None
        and location.path.lower().endswith('.erh')
    ):
        filename = location.path.replace('\\', '/').rsplit('/', 1)[-1]
        message = '"が閉じられていません'
        return {
            'phase': 'header-load',
            'severity': 2,
            'stops_execution': True,
            'file': location.path,
            'line': location.line,
            'message': message,
            'lines': [
                f'警告Lv2:{filename}:{location.line}行目:{message}',
                'ERHの読み込み中にエラーが発生したため処理を終了しました',
            ],
        }
    if (
        error.code == 'E_FLOW'
        and error.message == '@SYSTEM_TITLE returned without BEGIN/LOADDATA/QUIT'
    ):
        message = '予期しないスクリプト終端です'
        return {
            'phase': 'runtime-system-flow',
            'severity': 'error',
            'stops_execution': True,
            'file': None,
            'line': None,
            'message': message,
            'lines': ['関数の終端でエラーが発生しました:Emuera', message],
        }
    return None


def lines(error):
    presentation = describe(error)
    return presentation['lines'] if presentation is not None else [str(error)]
