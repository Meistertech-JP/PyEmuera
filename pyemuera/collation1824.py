"""The culture-aware string comparison used by v24 ARRAYMSORT.

Framework String.CompareTo uses CurrentCulture/CompareOptions.None, rather
than identifier/ordinal equality. On Windows the process-default culture is
the user's default locale; outside Windows an explicit, frozen ja-JP NLS
profile provides reproducible comparison without borrowing libc's locale.
Backend identity is separate from claims about captured/native equivalence.
"""

from functools import lru_cache
import sys


@lru_cache(maxsize=1)
def _backend():
    if sys.platform == 'win32':
        from .collation_windows import WindowsNLSBackend

        return WindowsNLSBackend()
    from .collation_portable import PortableNLSBackend

    return PortableNLSBackend()


def _culture(backend, culture):
    if culture is not None:
        return culture
    if sys.platform == 'win32':
        return backend.user_default_culture()
    return 'ja-JP'


def compare_strings(left: str, right: str, culture: str | None = None) -> int:
    backend = _backend()
    return backend.compare(left, right, _culture(backend, culture))


def comparison_identity(culture: str | None = None) -> dict:
    backend = _backend()
    return backend.identity(_culture(backend, culture))
