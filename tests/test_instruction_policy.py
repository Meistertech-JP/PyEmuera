"""Normal play has no cumulative instruction budget; tests can opt into one."""
import contextlib
import io
import json
from pathlib import Path

from test_core import Harness
from pyemuera.cli import main, parser
from pyemuera.errors import EraError


class InstructionPolicy(Harness):
    def test_cli_default_is_unlimited(self):
        self.assertEqual(parser().parse_args([]).max_steps, 0)

    def test_cli_explicit_zero_is_unlimited(self):
        self.assertEqual(parser().parse_args(['--max-steps', '0']).max_steps, 0)

    def test_cli_explicit_positive_limit(self):
        self.assertEqual(parser().parse_args(['--max-steps', '19']).max_steps, 19)

    def test_embedding_default_is_unlimited(self):
        vm = self.make('@MAIN\nA++\nRETURN\n')
        self.assertEqual(vm.max_steps, 0)
        vm.steps = 10_000_000
        vm.call('MAIN')
        self.assertGreater(vm.steps, 10_000_000)
        self.assertEqual(vm.get('A'), 1)

    def test_explicit_zero_keeps_counting(self):
        vm = self.make('@MAIN\nA++\nRETURN\n', max_steps=0)
        vm.steps = 10_000_000
        vm.call('MAIN')
        self.assertEqual(vm.steps, 10_000_002)

    def test_limit_preserves_boundary_and_prior_side_effects(self):
        vm = self.make('@MAIN\nA++\nA++\nA++\nRETURN\n', max_steps=2)
        with self.assertRaises(EraError) as cm:
            vm.call('MAIN')
        self.assertEqual(vm.steps, 3)
        self.assertEqual(vm.get('A'), 2)
        self.assertEqual(cm.exception.code, 'E_LIMIT')
        self.assertEqual(cm.exception.location.line, 4)
        self.assertIn('Configured instruction limit', str(cm.exception))
        self.assertNotIn('infinite loop', str(cm.exception).lower())

    def test_limit_is_cumulative_across_calls(self):
        vm = self.make('@MAIN\nA++\nRETURN\n', max_steps=3)
        vm.call('MAIN')
        with self.assertRaises(EraError):
            vm.call('MAIN')
        self.assertEqual(vm.get('A'), 2)
        self.assertEqual(vm.steps, 4)

    def test_explicit_limit_stops_an_unbounded_program(self):
        vm = self.make('@MAIN\nWHILE 1\nWEND\n', max_steps=17)
        with self.assertRaises(EraError) as cm:
            vm.call('MAIN')
        self.assertEqual(cm.exception.code, 'E_LIMIT')
        self.assertEqual(vm.steps, 18)

    def _cli_run(self, extra):
        vm = self.make('@MAIN\nREPEAT 20\nA++\nREND\nQUIT\n')
        root = vm.program.root
        report = root.parent / (root.name + '-session.json')
        self.addCleanup(lambda: report.unlink(missing_ok=True))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main([str(root), '--entry', 'MAIN', '--no-wait', '--color', 'never',
                           '--session-report', str(report), *extra])
        return result, json.loads(report.read_text(encoding='utf-8'))

    def test_default_cli_completes_finite_program(self):
        code, report = self._cli_run([])
        self.assertEqual(code, 0)
        self.assertEqual(report['outcome'], 'quit')
        self.assertIsNone(report['error'])

    def test_explicit_cli_zero_completes_finite_program(self):
        code, report = self._cli_run(['--max-steps', '0'])
        self.assertEqual(code, 0)
        self.assertGreater(report['steps'], 20)

    def test_explicit_cli_limit_reports_stop(self):
        code, report = self._cli_run(['--max-steps', '7'])
        self.assertEqual(code, 1)
        self.assertEqual(report['error']['code'], 'E_LIMIT')
        self.assertEqual(report['steps'], 8)
        self.assertNotIn('infinite loop', report['error']['message'].lower())

    def test_negative_cli_limit_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--max-steps', '-1']), 1)
