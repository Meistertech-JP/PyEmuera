"""Ordinary TITLE/SHOP acquisition; no ERB-wide echo or last-value cache."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptedInteger:
    raw: str
    value: int
    host_echo: bool


@dataclass(frozen=True)
class LegacyInteger:
    value: int


@dataclass
class _Acceptance:
    claimed: bool = False
    receipt: object = None


@dataclass
class _EchoCall:
    commits: int = 0
    owner: object = None


@dataclass(frozen=True)
class _Row:
    console_key: object
    row: str
    count: int
    temporary: bool = False
    host_echo: bool = False


def acquire(console):
    """An explicit protocol; old input-only hosts keep their old behavior."""
    protocol = getattr(console, 'input_system_integer', None)
    result = LegacyInteger(console.input()) if protocol is None else protocol()
    if not isinstance(result, (AcceptedInteger, LegacyInteger)):
        raise TypeError('input_system_integer must return an accepted or legacy receipt')
    return result


def echo(console, receipt):
    if isinstance(receipt, LegacyInteger):
        return None
    return console.echo_system_integer(receipt)


def reject(console, owner, message, *, title=False):
    if owner is None:
        # Explicit old-host policy: no guessed raw text or new history erasure.
        if title:
            console.write(message, True)
        else:
            console.reuse_line(message)
        return
    from .errors import Unsupported

    if (console.__dict__.get('_system_input_row') is not owner
            or console.current or console.log_current):
        raise Unsupported('System menu feedback no longer owns the input echo row')
    console._remove_system_input_row(owner)
    before = console.line_count
    console.write(message, True)
    if console.line_count != before + 1 or console.current or console.log_current:
        raise Unsupported('System menu temporary feedback was changed by an output hook')
    console._system_input_row = _Row(
        console._system_input_console_key, console.lines[-1], console.line_count, True)
