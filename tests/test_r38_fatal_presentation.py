import contextlib
import io
import unittest
from test_core import Harness
from pyemuera.errors import EraError, Location
from pyemuera.fatal_presentation import describe, lines


class FatalProjection(unittest.TestCase):
    def test_header_quote_has_native_level_and_order(self):
        error = EraError('Unclosed quoted string', Location('ERB/Vars.ERH', 4), 'E_SYNTAX')
        self.assertEqual(lines(error), ['警告Lv2:Vars.ERH:4行目:"が閉じられていません',
                                       'ERHの読み込み中にエラーが発生したため処理を終了しました'])
        self.assertEqual(describe(error)['phase'], 'header-load')
        self.assertEqual(describe(error)['severity'], 2)

    def test_header_quote_preserves_api_code_and_location(self):
        error = EraError('Unclosed quoted string', Location('ERB/Vars.ERH', 4), 'E_SYNTAX')
        report = error.as_dict()
        self.assertEqual((report['code'], report['message'], report['file'], report['line']),
                         ('E_SYNTAX', 'Unclosed quoted string', 'ERB/Vars.ERH', 4))
        self.assertEqual(report['diagnostic_message'], '"が閉じられていません')

    def test_erb_quote_is_not_classified_as_header_load(self):
        error = EraError('Unclosed quoted string', Location('ERB/Main.ERB', 4), 'E_SYNTAX')
        self.assertIsNone(describe(error))
        self.assertEqual(lines(error), [str(error)])

    def test_system_title_end_is_runtime_and_not_warning(self):
        error = EraError('@SYSTEM_TITLE returned without BEGIN/LOADDATA/QUIT', code='E_FLOW')
        report = error.as_dict()
        self.assertEqual(report['code'], 'E_FLOW')
        self.assertEqual(report['diagnostic_presentation']['phase'], 'runtime-system-flow')
        self.assertEqual(lines(error), ['関数の終端でエラーが発生しました:Emuera', '予期しないスクリプト終端です'])
        self.assertIsNone(report['file'])

    def test_other_flow_errors_keep_their_original_projection(self):
        error = EraError('other flow problem', code='E_FLOW')
        self.assertIsNone(describe(error))
        self.assertNotIn('diagnostic_presentation', error.as_dict())


class FatalConsumers(Harness):
    def run_cli(self, root):
        from pyemuera.cli import main
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main([str(root), '--no-wait'])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_no_bom_erb_prints_before_runtime_error(self):
        vm = self.make('@SYSTEM_TITLE\nPRINTL 日本語\nQUIT\n', encoding='utf-8')
        code, output, diagnostic = self.run_cli(vm.root)
        self.assertEqual(code, 1)
        self.assertIn('譌･', output)
        self.assertIn('予期しないスクリプト終端です', diagnostic)
        self.assertNotIn('警告Lv2', diagnostic)

    def test_header_quote_stops_before_script_side_effect(self):
        vm = self.make('@SYSTEM_TITLE\nPRINTL MUST_NOT_RUN\nQUIT\n')
        (vm.root / 'ERB/Vars.ERH').write_bytes(b'#DIMS S="unclosed\n')
        code, output, diagnostic = self.run_cli(vm.root)
        self.assertEqual(code, 1)
        self.assertNotIn('MUST_NOT_RUN', output)
        self.assertEqual(diagnostic.splitlines(), ['警告Lv2:Vars.ERH:1行目:"が閉じられていません',
                                                   'ERHの読み込み中にエラーが発生したため処理を終了しました'])
