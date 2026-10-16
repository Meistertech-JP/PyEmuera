"""Received Windows byte oracles plus independently source-derived boundaries."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from pyemuera.analysis_mode import analyze
from pyemuera.cli import main
from pyemuera.console import Console
from pyemuera.data import GameData
from pyemuera.errors import EraError
from pyemuera.program import Program
from pyemuera.random1824 import EngineRandom
from pyemuera.runtime import VM

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/r41_analysis_native'
CATALOG = json.loads((FIXTURES / 'catalog.json').read_text(encoding='utf-8'))
spec = importlib.util.spec_from_file_location('strict_r41_analysis_compare', ROOT / 'verification/r41/analysis_compare.py')
COMPARATOR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(COMPARATOR)


class NativeCaptures(unittest.TestCase):
    def compare_case(self, case):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / case['case_id']
            shutil.copytree(FIXTURES / case['case_id'], root)
            (root / 'CSV').mkdir(exist_ok=True)
            for relative, digest in case['fixture_sha256'].items():
                self.assertEqual(hashlib.sha256((root / relative).read_bytes()).hexdigest(), digest)
            native = FIXTURES / case['case_id'] / 'native.log'
            self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest(), case['native_sha256'])
            with patch.object(VM, 'run', side_effect=AssertionError('game flow')):
                result = analyze([root / 'ERB'], root=root)
            comparison = COMPARATOR.compare(native, result.log_path,
                native_root=case['native_source_root'], python_root=root,
                source_files=[p for p in case['fixture_sha256'] if Path(p).suffix.lower() in ('.erb', '.erh')])
            self.assertTrue(comparison['path_normalized_bytes_equal'], comparison)
            for key in ['native_utf16le_bom', 'python_utf16le_bom', 'native_crlf_only', 'python_crlf_only',
                        'native_trailing_crlf', 'python_trailing_crlf']:
                self.assertTrue(comparison[key], key)
            self.assertEqual(result.vm.steps, 0)
            self.assertEqual(result.vm.frames, [])
            self.assertEqual(result.vm.rng.getstate(), EngineRandom(0).getstate())


def native_test(case):
    def test(self):
        self.compare_case(case)
    return test


for _case in CATALOG['cases']:
    setattr(NativeCaptures, 'test_received_windows_' + _case['case_id'].replace('-', '_'), native_test(_case))


class LoaderBoundaries(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'CSV').mkdir()
        (self.root / 'ERB').mkdir()
        self.config('FunctionNotCalledWarning:IGNORE\n')

    def config(self, text):
        (self.root / 'CSV/_fixed.config').write_text(text, encoding='utf-8-sig')

    def source(self, text, name='Main.ERB'):
        path = self.root / 'ERB' / name
        path.write_text(text, encoding='utf-8-sig')
        return path

    def analyze(self, paths=None):
        return analyze(paths or [self.root / 'ERB'], root=self.root)

    def test_no_functions_forced_flush_is_ascii_space(self):
        path = self.source('; no function\n')
        result = self.analyze()
        self.assertEqual(result.lines, ['Now Loading...', str(path) + '読み込み中・・・', '　', ' ',
                                        'ファイル解析終了：Analysis.logに出力します'])

    def test_full_group_without_warning_still_has_ascii_space(self):
        self.source('@SYSTEM_TITLE\nQUIT\n@ONE\nRETURN\n@TWO\nRETURN\n')
        result = self.analyze()
        self.assertEqual(result.lines[-3:], ['　', ' ', 'ファイル解析終了：Analysis.logに出力します'])
        self.assertFalse(any(line.startswith('警告') for line in result.lines))

    def test_partial_group_without_warning_has_no_ascii_space(self):
        self.source('@SYSTEM_TITLE\nQUIT\n@ONE\nRETURN\n')
        result = self.analyze()
        self.assertNotIn(' ', result.lines)
        self.assertTrue(result.lines[-2].startswith('@SYSTEM_TITLE'))

    def test_partial_group_with_warning_has_no_ascii_space(self):
        self.source('@SYSTEM_TITLE\nCALL ABSENT\nQUIT\n')
        result = self.analyze()
        self.assertNotIn(' ', result.lines)
        self.assertEqual(result.report['undefined_calls'], {'ABSENT': 1})

    def test_multiple_full_groups_only_final_forced_space(self):
        self.source('@SYSTEM_TITLE\nQUIT\n' + ''.join('@F' + str(i) + '\nRETURN\n' for i in range(5)))
        result = self.analyze()
        self.assertEqual(result.lines.count(' '), 1)
        self.assertEqual(result.lines.count('　'), 3)

    def test_multiple_files_last_partial_buffer_controls_space(self):
        first = self.source('@SYSTEM_TITLE\nQUIT\n@ONE\nRETURN\n@TWO\nRETURN\n', 'A.ERB')
        last = self.source('@LAST\nRETURN\n', 'Z.ERB')
        result = self.analyze([first, last])
        self.assertNotIn(' ', result.lines)
        self.assertTrue(result.lines[-2].startswith('@LAST'))

    def test_multiple_files_last_empty_buffer_controls_space(self):
        first = self.source('@SYSTEM_TITLE\nQUIT\n', 'A.ERB')
        last = self.source('; no functions\n', 'Z.ERB')
        result = self.analyze([first, last])
        self.assertEqual(result.lines[-3:], ['　', ' ', 'ファイル解析終了：Analysis.logに出力します'])

    def test_columns_zero_leaves_function_row_buffered(self):
        self.config('FunctionNotCalledWarning:IGNORE\nPrintCPerLine:0\n')
        self.source('@SYSTEM_TITLE\nQUIT\n@ONE\nRETURN\n@TWO\nRETURN\n')
        result = self.analyze()
        self.assertNotIn(' ', result.lines)
        self.assertIn('@TWO', result.lines[-2])

    def test_duplicate_counter_reset_forces_flush(self):
        self.source('@SYSTEM_TITLE\nQUIT\n@ONE\nRETURN\n@ONE\nRETURN\n')
        result = self.analyze()
        self.assertEqual(result.lines.count(' '), 1)
        self.assertTrue(any('既に定義' in line for line in result.lines))

    def test_event_prefix_does_not_suppress_normal_duplicate_reset(self):
        self.source('@EVENTCUSTOM\nRETURN\n@EVENTCUSTOM\nRETURN\n')
        result = self.analyze()
        self.assertEqual(result.lines.count(' '), 1)
        self.assertTrue(any('既に定義' in line for line in result.lines))

    def test_actual_event_duplicate_leaves_partial_buffer(self):
        self.source('@EVENTFIRST\nRETURN\n@EVENTFIRST\nRETURN\n')
        result = self.analyze()
        self.assertNotIn(' ', result.lines)
        self.assertFalse(any('既に定義' in line for line in result.lines))

    def test_display_report_follows_forced_flush(self):
        self.config('FunctionNotCalledWarning:IGNORE\nDisplayReport:YES\n')
        self.source('@SYSTEM_TITLE\nQUIT\n@ONE\nRETURN\n@TWO\nRETURN\n')
        result = self.analyze()
        index = result.lines.index(' ')
        self.assertTrue(result.lines[index + 1].startswith('非コメント行数:'))

    def test_history_deletion_keeps_one_final_forced_space(self):
        # 5001 retained source rows exceed the native default history of 5000.
        self.source(''.join('@F' + str(i) + '\nRETURN\n' for i in range(7500)))
        result = self.analyze()
        self.assertEqual(len(result.lines), 5000)
        self.assertTrue(result.lines[0].startswith('@F3 '))
        self.assertFalse(any(line.startswith('@F0 ') for line in result.lines))
        self.assertEqual(result.lines[-3:], ['　', ' ', 'ファイル解析終了：Analysis.logに出力します'])

    def test_bad_declaration_unregistered_valid_reuse_and_later_function(self):
        self.source('@SYSTEM_TITLE\n#DIM TESTVALUE = RAND:100\n#DIM TESTVALUE = 7\nCALL AFTER\nQUIT\n'
                    '@AFTER\n#DIM TESTAFTER = 9\nCALL ABSENT\nRETURN\n')
        with patch.object(EngineRandom, 'randrange', side_effect=AssertionError('RNG consumed')):
            result = self.analyze()
        function = result.program.functions['SYSTEM_TITLE'][0]
        self.assertEqual([d.name for d in result.vm.declarations[function.uid]], ['TESTVALUE'])
        self.assertEqual(result.vm.static[function.uid]['TESTVALUE'].get((0,)), 7)
        after = result.program.functions['AFTER'][0]
        self.assertEqual(result.vm.static[after.uid]['TESTAFTER'].get((0,)), 9)
        self.assertEqual(result.report['undefined_calls'], {'ABSENT': 1})
        declaration = next(d for d in result.report['diagnostics'] if d['category'] == 'E_DECLARATION')
        self.assertEqual((declaration['severity'], declaration['line']), (2, 2))
        self.assertEqual(declaration['reference_message'], '配列の初期値には定数のみ指定できます')
        self.assertTrue(result.log_path.exists())

    def test_nonconstant_declaration_forms_never_evaluate_game_state(self):
        for text in ['A', 'A++', 'RAND:100', 'METHOD()', 'STRFORM("{RAND:100}")']:
            with self.subTest(initializer=text):
                string = '#DIMS' if text.startswith('STRFORM') else '#DIM'
                self.source('@SYSTEM_TITLE\n' + string + ' TESTVALUE = ' + text + '\nQUIT\n'
                            '@METHOD\n#FUNCTION\nRETURNF 1\n')
                with patch.object(EngineRandom, 'randrange', side_effect=AssertionError('RNG consumed')):
                    result = self.analyze()
                function = result.program.functions['SYSTEM_TITLE'][0]
                self.assertNotIn('TESTVALUE', result.vm.static[function.uid])
                self.assertEqual(result.vm.get('A'), 0)
                self.assertEqual(result.vm.steps, 0)
                self.assertEqual(result.report['diagnostics'][0]['severity'], 2)

    def test_warning_threshold_does_not_hide_declaration_error(self):
        self.config('DisplayWarningLevel:3\nFunctionNotCalledWarning:IGNORE\n')
        self.source('@SYSTEM_TITLE\n#DIM TESTVALUE = RAND:100\nQUIT\n')
        self.assertTrue(any(line.startswith('警告Lv2:') for line in self.analyze().lines))

    def test_cli_continues_declaration_error_with_exit_zero(self):
        self.source('@SYSTEM_TITLE\n#DIM TESTVALUE = RAND:100\nQUIT\n')
        report = self.root / 'analysis.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(['--analysis', str(self.root / 'ERB'), '--report', str(report)])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / 'Analysis.log').exists())
        self.assertTrue(json.loads(report.read_text())['analysis_complete'])

    def test_global_nonconstant_header_remains_fatal(self):
        self.source('@SYSTEM_TITLE\nQUIT\n')
        self.source('#DIM GLOBALVALUE = RAND:100\n', 'Vars.ERH')
        with self.assertRaises(EraError) as caught:
            self.analyze()
        self.assertEqual(caught.exception.code, 'E_DECLARATION')
        self.assertFalse((self.root / 'Analysis.log').exists())

    def test_normal_mode_declaration_error_still_aborts(self):
        self.source('@SYSTEM_TITLE\n#DIM TESTVALUE = UNKNOWNVALUE\nQUIT\n')
        with self.assertRaises(EraError):
            VM(Program(self.root), GameData(self.root), Console(output=io.StringIO()))
        self.assertFalse((self.root / 'Analysis.log').exists())

    def test_comparator_rejects_whitespace_bom_and_newline_changes(self):
        source = FIXTURES / 'functions/native.log'
        original = source.read_bytes()
        candidate = self.root / 'altered.log'
        for value in [original[2:], original.replace(b' \x00\r\x00\n\x00', b'\r\x00\n\x00', 1),
                      original.replace(b'\r\x00\n\x00', b'\n\x00', 1)]:
            with self.subTest(change=hashlib.sha256(value).hexdigest()):
                candidate.write_bytes(value)
                comparison = COMPARATOR.compare(source, candidate, native_root='unused', python_root=self.root, source_files=[])
                self.assertFalse(comparison['path_normalized_bytes_equal'])
