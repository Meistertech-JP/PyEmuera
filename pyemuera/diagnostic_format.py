"""Source-backed presentation only; exception code/location/stack stay intact."""


def reference_message(message, code):
    if code == 'E_ARITH' and message == 'Division by zero':
        return '0による除算が行なわれました'
    if code == 'E_TYPE' and message == 'Integer required, got str':
        return '式の結果が数値ではありません'
    if code == 'E_SYNTAX' and message.startswith(('Expected expression at column ',)):
        return '式が異常です'
    return message
