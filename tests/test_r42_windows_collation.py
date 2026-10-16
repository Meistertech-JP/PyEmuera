"""Mocked Win32 ABI checks; these are not new Windows/NLS observations."""
import ctypes
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera import collation_windows as nls


def units(buffer, count):
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint16))
    return tuple(pointer[i] for i in range(count))


def text(buffer, count):
    return ctypes.string_at(buffer, count * 2).decode('utf-16-le', 'surrogatepass')


def locale_name(buffer):
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint16))
    count = 0
    while pointer[count]:
        count += 1
    return text(buffer, count)


class MockNLS:
    """Scripted API return values; no alternate collation implementation."""
    def __init__(self, result=2):
        self.result = result
        self.calls = []
        self.version_ok = True
        self.locale_result = 'ja-JP'

    def CompareStringEx(self, culture, flags, left, nl, right, nr, version, reserved, param):
        self.calls.append({'culture': locale_name(culture), 'flags': flags,
                           'left': units(left, nl), 'right': units(right, nr),
                           'counts': (nl, nr), 'version': version,
                           'reserved': reserved, 'param': param})
        if callable(self.result):
            return self.result(text(left, nl), text(right, nr))
        return self.result

    def GetNLSVersionEx(self, function, culture, out):
        if not self.version_ok:
            return 0
        value = ctypes.cast(out, ctypes.POINTER(nls._NLSVersionInfoEx)).contents
        assert function == nls.COMPARE_STRING
        assert value.dwNLSVersionInfoSize == 32
        value.dwNLSVersion = 0x60101
        value.dwDefinedVersion = 0x60101
        value.dwEffectiveId = 0x411
        value.guidCustomVersion[:] = bytes.fromhex('78563412341278569abcdef012345678')
        return 1

    def GetUserDefaultLocaleName(self, buffer, size):
        assert size == 85
        if self.locale_result is None:
            return 0
        raw = self.locale_result.encode('utf-16-le') + b'\0\0'
        ctypes.memmove(buffer, raw, len(raw))
        return len(raw) // 2


class WindowsCollationR42(unittest.TestCase):
    def backend(self, result=2):
        api = MockNLS(result)
        return nls.WindowsNLSBackend(api, last_error=lambda: 87), api

    def test_compare_maps_native_three_way_returns_to_signs(self):
        for result, expected in ((1, -1), (2, 0), (3, 1)):
            backend, _ = self.backend(result)
            with self.subTest(result=result):
                self.assertEqual(backend.compare('a', 'A', 'ja-JP'), expected)

    def test_compare_passes_framework_none_linguistic_casing_flag(self):
        backend, api = self.backend()
        backend.compare('あ', 'ア', 'ja-JP')
        self.assertEqual(api.calls[0]['flags'], 0x08000000)
        self.assertEqual(api.calls[0]['culture'], 'ja-JP')
        self.assertEqual((api.calls[0]['version'], api.calls[0]['reserved'], api.calls[0]['param']),
                         (None, None, 0))

    def test_compare_keeps_embedded_null_and_explicit_lengths(self):
        backend, api = self.backend()
        backend.compare('a\0b', 'ab', 'ja-JP')
        self.assertEqual(api.calls[0]['left'], (0x61, 0, 0x62))
        self.assertEqual(api.calls[0]['counts'], (3, 2))

    def test_compare_counts_supplementary_characters_as_two_utf16_units(self):
        backend, api = self.backend()
        backend.compare('😀', '𐐀', 'ja-JP')
        self.assertEqual(api.calls[0]['left'], (0xD83D, 0xDE00))
        self.assertEqual(api.calls[0]['right'], (0xD801, 0xDC00))
        self.assertEqual(api.calls[0]['counts'], (2, 2))

    def test_compare_preserves_isolated_surrogates_without_repair(self):
        backend, api = self.backend()
        backend.compare('\ud800X', '\udc00', 'ja-JP')
        self.assertEqual(api.calls[0]['left'], (0xD800, 0x58))
        self.assertEqual(api.calls[0]['right'], (0xDC00,))

    def test_compare_passes_empty_strings_with_zero_explicit_counts(self):
        backend, api = self.backend()
        backend.compare('', 'x', 'ja-JP')
        self.assertEqual(api.calls[0]['counts'], (0, 1))

    def test_compare_does_not_normalize_composed_or_decomposed_text(self):
        backend, api = self.backend()
        backend.compare('é', 'e\u0301', 'ja-JP')
        self.assertEqual(api.calls[0]['left'], (0xE9,))
        self.assertEqual(api.calls[0]['right'], (0x65, 0x301))

    def test_compare_zero_return_raises_api_error_not_equality(self):
        backend, api = self.backend(0)
        with self.assertRaises(nls.WindowsNLSError) as caught:
            backend.compare('a', 'b', 'ja-JP')
        self.assertEqual((caught.exception.api, caught.exception.winerror), ('CompareStringEx', 87))
        self.assertEqual(len(api.calls), 1)

    def test_compare_undocumented_return_does_not_become_arbitrary_sign(self):
        backend, _ = self.backend(4)
        with self.assertRaises(nls.WindowsNLSError):
            backend.compare('a', 'b', 'ja-JP')

    def test_explicit_culture_validation_precedes_native_calls(self):
        backend, api = self.backend()
        for culture, error in ((None, TypeError), ('ja-JP\0en-US', ValueError), ('x' * 85, ValueError)):
            with self.subTest(culture=culture), self.assertRaises(error):
                backend.compare('a', 'b', culture)
        self.assertEqual(api.calls, [])

    def test_invariant_locale_is_an_explicit_empty_name(self):
        backend, api = self.backend()
        backend.compare('a', 'b', '')
        self.assertEqual(api.calls[0]['culture'], '')

    def test_string_type_errors_do_not_enter_native_api(self):
        backend, api = self.backend()
        for value in (None, 3, b'abc'):
            with self.subTest(value=value), self.assertRaises(TypeError):
                backend.compare(value, 'a', 'ja-JP')
        self.assertEqual(api.calls, [])

    def test_nls_version_structure_has_win32_widths_on_all_hosts(self):
        self.assertEqual(ctypes.sizeof(nls._NLSVersionInfoEx), 32)
        self.assertEqual(nls._NLSVersionInfoEx.guidCustomVersion.offset, 16)

    def test_identity_records_locale_sort_version_and_no_framework_claim(self):
        backend, _ = self.backend()
        identity = backend.identity('ja-JP')
        self.assertEqual(identity['culture_source'], 'explicit_argument')
        self.assertEqual(identity['native_flags'], 0x08000000)
        self.assertEqual(identity['nls_version']['dwNLSVersion'], 0x60101)
        self.assertEqual(identity['nls_version']['guidCustomVersion'], '12345678-1234-5678-9abc-def012345678')
        self.assertEqual(identity['execution'], 'injected_api')
        self.assertEqual(identity['framework_equivalence']['status'], 'UNOBSERVED')

    def test_version_api_failure_is_reported(self):
        backend, api = self.backend()
        api.version_ok = False
        with self.assertRaises(nls.WindowsNLSError) as caught:
            backend.identity('ja-JP')
        self.assertEqual(caught.exception.api, 'GetNLSVersionEx')

    def test_user_default_culture_uses_user_locale_api(self):
        backend, api = self.backend()
        self.assertEqual(backend.user_default_culture(), 'ja-JP')
        api.locale_result = 'tr-TR'
        self.assertEqual(backend.user_default_culture(), 'tr-TR')

    def test_user_locale_api_failure_is_reported(self):
        backend, api = self.backend()
        api.locale_result = None
        with self.assertRaises(nls.WindowsNLSError) as caught:
            backend.user_default_culture()
        self.assertEqual(caught.exception.api, 'GetUserDefaultLocaleName')

    def test_nonwindows_native_loader_explicitly_rejects_without_fallback(self):
        with patch.object(nls.os, 'name', 'posix'), self.assertRaises(nls.WindowsNLSUnavailable):
            nls._load_api()

    def test_loader_binds_unicode_api_widths_and_system_library(self):
        dll = SimpleNamespace(CompareStringEx=lambda *args: 2,
                              GetNLSVersionEx=lambda *args: 1,
                              GetUserDefaultLocaleName=lambda *args: 6)
        with patch.object(nls.os, 'name', 'nt'), patch.object(nls.ctypes, 'WinDLL',
                return_value=dll, create=True) as loader:
            self.assertIs(nls._load_api(), dll)
        loader.assert_called_once_with('kernel32.dll', use_last_error=True, winmode=0x800)
        self.assertEqual(dll.CompareStringEx.argtypes[3], ctypes.c_int32)
        self.assertEqual(dll.CompareStringEx.argtypes[5], ctypes.c_int32)
        self.assertEqual(dll.CompareStringEx.restype, ctypes.c_int32)
        self.assertEqual(dll.GetNLSVersionEx.argtypes[0], ctypes.c_int32)

    def test_module_facade_forwards_explicit_culture_without_ui_lookup(self):
        backend, api = self.backend(1)
        with patch.object(nls, '_backend', return_value=backend):
            self.assertEqual(nls.compare('a', 'b', 'tr-TR'), -1)
            self.assertEqual(nls.identity('tr-TR')['culture'], 'tr-TR')
            self.assertEqual(nls.user_default_culture(), 'ja-JP')
        self.assertEqual(api.calls[0]['culture'], 'tr-TR')

    def test_archived_300_pair_oracle_checks_only_mock_transport(self):
        path = Path(__file__).parent / 'fixtures/r42_framework_string_probe.json'
        oracle = json.loads(path.read_text(encoding='utf-8-sig'))
        expected = {(row['left'], row['right']): row['sign'] for row in oracle['comparisons']}
        backend, api = self.backend(lambda left, right: expected[(left, right)] + 2)
        report = backend.validate_pairs(oracle['comparisons'], oracle['CurrentCulture'])
        self.assertEqual((report['pairs'], report['matches'], report['mismatches']), (300, 300, 0))
        self.assertEqual(report['status'], 'MOCK_API_ONLY')
        self.assertEqual(len(api.calls), 300)
        for call, row in zip(api.calls, oracle['comparisons']):
            self.assertEqual(text((ctypes.c_uint16 * len(call['left']))(*call['left']), len(call['left'])), row['left'])
            self.assertEqual(text((ctypes.c_uint16 * len(call['right']))(*call['right']), len(call['right'])), row['right'])

    def test_oracle_mismatch_is_explicit_and_not_a_match_claim(self):
        backend, _ = self.backend(2)
        report = backend.validate_pairs([{'left': 'a', 'right': 'b', 'sign': -1}], 'ja-JP')
        self.assertEqual(report['mismatches'], 1)
        self.assertEqual(report['differences'][0]['actual'], 0)
        self.assertEqual(report['identity']['framework_equivalence']['status'], 'MOCK_API_ONLY')

    def test_malformed_or_empty_oracle_cannot_be_accepted(self):
        backend, api = self.backend()
        for rows in ([], [{'left': 'a', 'right': 'b', 'sign': True}], [{'left': 'a', 'right': 'b', 'sign': 2}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                backend.validate_pairs(rows, 'ja-JP')
        self.assertEqual(api.calls, [])

    def test_validation_cannot_claim_success_after_version_api_failure(self):
        backend, api = self.backend()
        api.version_ok = False
        with self.assertRaises(nls.WindowsNLSError):
            backend.validate_pairs([{'left': 'a', 'right': 'b', 'sign': 0}], 'ja-JP')
        self.assertEqual(api.calls, [])
        self.assertEqual(backend._validation, {})


if __name__ == '__main__':
    unittest.main()
