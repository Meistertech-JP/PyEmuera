"""Text stream writes at the physical boundary; no Console/VM state lives here.

A returned short count identifies the accepted prefix, so only its remainder is
written. An exception does not identify that prefix and must never be retried.
The caller owns failure latching and terminal cleanup, not this small adapter.
"""

from __future__ import annotations


def write_all(stream, text):
    """Write text in order, accepting legacy file-like objects returning None."""
    remaining = text
    accepted = 0
    while True:
        try:
            written = stream.write(remaining)
        except UnicodeEncodeError as exc:
            # Preserve exception type/body. Only explicit returned counts prove
            # an accepted prefix; an exception alone does not reveal progress.
            exc._pyemuera_written_chars = accepted + getattr(
                exc, '_pyemuera_written_chars', 0
            )
            raise
        # Some observer/test streams do not implement TextIOBase's count return.
        # Keep their existing one-call contract; real short counts are explicit.
        if not isinstance(written, int) or written == len(remaining):
            return
        if written <= 0 or written > len(remaining):
            raise OSError('Host output write made no valid progress')
        accepted += written
        remaining = remaining[written:]
