"""Explicit-culture Windows NLS comparison; no locale or ordinal fallback.

Reference Source CompareInfo maps CompareOptions.None to linguistic casing,
and forwards String.Length (UTF-16 units), not null-terminated lengths. This
module binds those native operations. NLS/Framework equivalence remains a
sampled validation question: neither these bindings nor mock tests prove it.
"""

from __future__ import annotations

import ctypes
from functools import lru_cache
import os
import sys
import uuid


NORM_LINGUISTIC_CASING = 0x08000000
COMPARE_STRING = 1
LOCALE_NAME_MAX_LENGTH = 85
_U16 = ctypes.c_uint16
_DWORD = ctypes.c_uint32
_INT = ctypes.c_int32
_TEXT = ctypes.POINTER(_U16)


class WindowsNLSUnavailable(OSError):
    """The host cannot provide this Windows-only backend."""


class WindowsNLSError(OSError):
    def __init__(self, api, code, *, result=None):
        super().__init__(code, f'{api} failed (Windows error {code})')
        # OSError.__init__ clears winerror on Windows. Set it afterwards so
        # injected mock codes stay visible to callers.
        self.api = api
        self.winerror = code
        self.result = result


class _NLSVersionInfoEx(ctypes.Structure):
    # Fixed Win32 widths also keep the mocked ABI exact on LP64 hosts.
    _fields_ = [
        ('dwNLSVersionInfoSize', _DWORD),
        ('dwNLSVersion', _DWORD),
        ('dwDefinedVersion', _DWORD),
        ('dwEffectiveId', _DWORD),
        ('guidCustomVersion', ctypes.c_uint8 * 16),
    ]


def _utf16(text):
    if not isinstance(text, str):
        raise TypeError('Windows NLS comparison requires strings')
    raw = text.encode('utf-16-le', 'surrogatepass')
    count = len(raw) // 2
    if count > 0x7FFFFFFF:
        raise OverflowError('Windows NLS string exceeds signed Int32 length')
    buffer = (_U16 * (count + 1))()
    if raw:
        ctypes.memmove(buffer, raw, len(raw))
    return buffer, count


def _locale(culture):
    if not isinstance(culture, str):
        raise TypeError('An explicit culture name is required')
    if '\0' in culture:
        raise ValueError('Culture name contains an embedded null')
    buffer, count = _utf16(culture)
    if count >= LOCALE_NAME_MAX_LENGTH:
        raise ValueError('Culture name exceeds the Windows locale-name limit')
    # Empty string explicitly selects the NLS invariant locale. None would
    # select an implicit user locale and is intentionally rejected above.
    return buffer


def _load_api():
    if os.name != 'nt':
        raise WindowsNLSUnavailable('Windows NLS is unavailable on this host')
    api = ctypes.WinDLL('kernel32.dll', use_last_error=True, winmode=0x00000800)
    api.CompareStringEx.argtypes = [
        _TEXT,
        _DWORD,
        _TEXT,
        _INT,
        _TEXT,
        _INT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ssize_t,
    ]
    api.CompareStringEx.restype = _INT
    api.GetNLSVersionEx.argtypes = [_INT, _TEXT, ctypes.POINTER(_NLSVersionInfoEx)]
    api.GetNLSVersionEx.restype = _INT
    api.GetUserDefaultLocaleName.argtypes = [_TEXT, _INT]
    api.GetUserDefaultLocaleName.restype = _INT
    return api


class WindowsNLSBackend:
    """CompareStringEx with injectable API transport for non-Windows tests."""

    def __init__(self, api=None, *, last_error=None):
        self._injected = api is not None
        self._api = _load_api() if api is None else api
        self._last_error = last_error or getattr(ctypes, 'get_last_error', lambda: 0)
        self._validation = {}

    def compare(self, left, right, culture):
        locale = _locale(culture)
        first, first_count = _utf16(left)
        second, second_count = _utf16(right)
        result = self._api.CompareStringEx(
            locale,
            NORM_LINGUISTIC_CASING,
            first,
            first_count,
            second,
            second_count,
            None,
            None,
            0,
        )
        # 0 is an API error, not equality. Other undocumented returns also
        # fail explicitly rather than falling back to Python ordering.
        if result not in (1, 2, 3):
            code = self._last_error() if result == 0 else 87
            raise WindowsNLSError('CompareStringEx', code, result=result)
        return result - 2

    def user_default_culture(self):
        buffer = (_U16 * LOCALE_NAME_MAX_LENGTH)()
        count = self._api.GetUserDefaultLocaleName(buffer, LOCALE_NAME_MAX_LENGTH)
        if count < 1 or count > LOCALE_NAME_MAX_LENGTH:
            code = self._last_error() if count == 0 else 87
            raise WindowsNLSError('GetUserDefaultLocaleName', code, result=count)
        if buffer[count - 1] != 0:
            raise WindowsNLSError('GetUserDefaultLocaleName', 87, result=count)
        raw = ctypes.string_at(buffer, (count - 1) * 2)
        name = raw.decode('utf-16-le', 'surrogatepass')
        _locale(name)
        return name

    def identity(self, culture):
        locale = _locale(culture)
        version = _NLSVersionInfoEx()
        version.dwNLSVersionInfoSize = ctypes.sizeof(version)
        if not self._api.GetNLSVersionEx(COMPARE_STRING, locale, ctypes.byref(version)):
            raise WindowsNLSError('GetNLSVersionEx', self._last_error())
        windows_version = None
        if os.name == 'nt':
            current = sys.getwindowsversion()
            windows_version = {
                'major': current.major,
                'minor': current.minor,
                'build': current.build,
                'platform': current.platform,
            }
        return {
            'backend': 'windows-nls',
            'api': 'CompareStringEx',
            'culture': culture,
            'culture_source': 'explicit_argument',
            'framework_compare_options': 'None',
            'native_flags': NORM_LINGUISTIC_CASING,
            'utf16_lengths': 'explicit_code_units',
            'normalization': None,
            'execution': 'injected_api' if self._injected else 'windows_api',
            'host_platform': sys.platform,
            'windows_version': windows_version,
            'windows_version_source': 'sys.getwindowsversion',
            'nls_version': {
                'dwNLSVersion': version.dwNLSVersion,
                'dwDefinedVersion': version.dwDefinedVersion,
                'dwEffectiveId': version.dwEffectiveId,
                'guidCustomVersion': str(
                    uuid.UUID(bytes_le=bytes(version.guidCustomVersion))
                ),
            },
            'framework_equivalence': dict(
                self._validation.get(
                    culture,
                    {
                        'status': 'UNOBSERVED',
                        'scope': 'No Framework pair oracle validated by this instance',
                    },
                )
            ),
        }

    def validate_pairs(self, pairs, culture):
        """Compare a supplied independent oracle; never manufacture results."""
        _locale(culture)
        rows = list(pairs)
        # Reject malformed oracle data before making any native calls.
        for row in rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get('left'), str)
                or not isinstance(row.get('right'), str)
                or type(row.get('sign')) is not int
                or row['sign'] not in (-1, 0, 1)
            ):
                raise ValueError(
                    'Pair oracle requires left/right strings and sign -1, 0 or 1'
                )
        if not rows:
            raise ValueError('An empty pair oracle cannot validate a backend')
        metadata = self.identity(culture)
        mismatches = []
        for index, row in enumerate(rows):
            actual = self.compare(row['left'], row['right'], culture)
            if actual != row['sign']:
                mismatches.append(
                    {
                        'index': index,
                        'left': row['left'],
                        'right': row['right'],
                        'expected': row['sign'],
                        'actual': actual,
                    }
                )
        if self._injected:
            status = 'MOCK_API_ONLY'
        else:
            status = 'DOTNET_PROBE_MATCH' if not mismatches else 'UNRESOLVED'
        validation = {
            'status': status,
            'scope': 'Supplied pair oracle only; no full-culture proof',
            'pairs': len(rows),
            'matches': len(rows) - len(mismatches),
            'mismatches': len(mismatches),
            'culture': culture,
        }
        self._validation[culture] = validation
        metadata['framework_equivalence'] = dict(validation)
        return {**validation, 'differences': mismatches, 'identity': metadata}


@lru_cache(maxsize=1)
def _backend():
    return WindowsNLSBackend()


def compare(left, right, culture):
    return _backend().compare(left, right, culture)


def identity(culture):
    return _backend().identity(culture)


def user_default_culture():
    """Windows user locale; this does not inspect Framework thread overrides/UI."""
    return _backend().user_default_culture()


def verify_pairs(pairs, culture):
    return _backend().validate_pairs(pairs, culture)
