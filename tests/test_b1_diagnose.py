"""Execute the distributed Diagnose batch with real cmd.exe, including failures."""
import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'packaging/public/Diagnose_PyEmuera.bat'
RUN_HISTORY = []  # Optional raw evidence sink for the release acceptance runner.


@unittest.skipUnless(os.name == 'nt', 'Windows cmd.exe batch acceptance')
class DiagnoseBatchB1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.build_temp.cleanup)
        cls.engine = Path(cls.build_temp.name) / 'engine.pyz'
        # Build current source once, then execute only the copied archive. The
        # batch's working directory and PYTHONPATH never contain the source tree.
        from tools.build_pyz import build
        build(ROOT, cls.engine)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='diagnose b1 ')
        self.addCleanup(temp.cleanup)
        self.stage = Path(temp.name)
        self.batch = self.stage / BATCH.name
        shutil.copyfile(BATCH, self.batch)
        shutil.copyfile(self.engine, self.stage / 'PyEmuera.pyz')
        self.variant = self.stage / 'variant'
        (self.variant / 'ERB').mkdir(parents=True)
        (self.variant / 'CSV').mkdir()
        (self.variant / 'ERB/main.erb').write_text(
            '@START\nPRINTL DIAGNOSE_OK\nQUIT\n', encoding='utf-8')

    def run_batch(self, *args, env_updates=None):
        env = os.environ.copy()
        # Force the interpreter running this test, without the Python launcher
        # choosing a different installation or downloading an interpreter.
        env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + str(
            Path(os.environ['SystemRoot']) / 'System32')
        env['PYEMUERA_NO_PAUSE'] = '1'
        env['PYTHONUTF8'] = '1'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.pop('PYTHONPATH', None)
        env.pop('RANDOM', None)
        if env_updates:
            env.update(env_updates)
        command = 'call ' + subprocess.list2cmdline([str(self.batch), *map(str, args)])
        result = subprocess.run(
            subprocess.list2cmdline([os.environ.get('COMSPEC', 'cmd.exe')])
            + ' /d /c ' + command,
            cwd=self.stage, env=env, input='', encoding='utf-8', errors='replace',
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        RUN_HISTORY.append({'test': self.id(), 'exit_code': result.returncode,
                            'output': result.stdout,
                            'reports': sorted(p.relative_to(self.stage).as_posix()
                                              for p in self.stage.glob('reports/**/*.json'))})
        return result

    def fixture_engine(self, names, exit_code):
        # Deterministic process fixture exercises partial writes/exit codes
        # independently of the real CLI, which normally writes both base reports.
        text = (
            'from pathlib import Path\nimport sys\n'
            'args = sys.argv[1:]\n'
            'for flag in ' + repr(tuple(names)) + ':\n'
            '    p = Path(args[args.index(flag) + 1])\n'
            '    p.parent.mkdir(parents=True, exist_ok=True)\n'
            '    p.write_text("{}", encoding="utf-8")\n'
            'raise SystemExit(' + repr(exit_code) + ')\n')
        with zipfile.ZipFile(self.stage / 'PyEmuera.pyz', 'w') as archive:
            archive.writestr('__main__.py', text)

    def damaged_report_engine(self, payloads, exit_code):
        text = (
            'from pathlib import Path\nimport sys\n'
            'args = sys.argv[1:]\n'
            'for flag, payload in ' + repr(tuple(payloads.items())) + ':\n'
            '    Path(args[args.index(flag) + 1]).write_bytes(payload)\n'
            'raise SystemExit(' + repr(exit_code) + ')\n')
        with zipfile.ZipFile(self.stage / 'PyEmuera.pyz', 'w') as archive:
            archive.writestr('__main__.py', text)

    def test_empty_reports_are_incomplete_not_complete_or_absent(self):
        self.damaged_report_engine(
            {'--report': b'', '--session-report': b'', '--error-report': b''}, 37)
        result = self.run_batch(self.variant)
        self.assertEqual(result.returncode, 37, result.stdout)
        self.assertIn('Incomplete or unreadable reports were found', result.stdout)
        self.assertIn('No complete JSON object reports were generated', result.stdout)
        self.assertNotIn('No reports were generated in this run.', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)
        self.assertEqual(len(list(self.stage.glob('reports/**/*.json'))), 3)

    def test_truncated_session_with_other_valid_reports_is_not_complete(self):
        self.damaged_report_engine(
            {'--report': b'{}', '--session-report': b'{"outcome":',
             '--error-report': b'{}'}, 1)
        result = self.run_batch(self.variant)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('Incomplete or unreadable JSON object: session.json', result.stdout)
        self.assertIn('  check.json', result.stdout)
        self.assertIn('  error.json', result.stdout)
        self.assertNotIn('  session.json', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)

    def test_corrupt_optional_error_report_prevents_complete_claim_on_exit_0(self):
        self.damaged_report_engine(
            {'--report': b'{}', '--session-report': b'{}', '--error-report': b'{oops'}, 0)
        result = self.run_batch(self.variant)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('Incomplete or unreadable JSON object: error.json', result.stdout)
        self.assertIn('  check.json', result.stdout)
        self.assertIn('  session.json', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)

    def test_non_object_json_reports_are_not_complete(self):
        self.damaged_report_engine(
            {'--report': b'[]', '--session-report': b'null', '--error-report': b'42'}, 130)
        result = self.run_batch(self.variant)
        self.assertEqual(result.returncode, 130, result.stdout)
        self.assertIn('No complete JSON object reports were generated', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)

    def test_trailing_garbage_and_invalid_utf8_are_not_complete(self):
        self.damaged_report_engine(
            {'--report': b'{} trailing', '--session-report': b'{"value":"\xff"}'}, 2)
        result = self.run_batch(self.variant)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('Incomplete or unreadable JSON object: check.json', result.stdout)
        self.assertIn('Incomplete or unreadable JSON object: session.json', result.stdout)
        self.assertIn('No complete JSON object reports were generated', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)

    def test_missing_variant_has_no_saved_claim_and_preserves_engine_exit(self):
        result = self.run_batch(self.stage / 'missing')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('E_PATH', result.stdout)
        self.assertIn('No reports were generated in this run.', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)
        self.assertNotIn('Only some reports', result.stdout)
        self.assertEqual(list(self.stage.glob('reports/**/*.json')), [])

    def test_normal_run_has_check_session_and_no_required_error_report(self):
        result = self.run_batch(self.variant, '--entry', 'START', '--no-wait')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('DIAGNOSE_OK', result.stdout)
        self.assertIn('Reports were written to:', result.stdout)
        self.assertNotIn('Only some reports', result.stdout)
        files = sorted(p.name for p in self.stage.glob('reports/**/*.json'))
        self.assertEqual(files, ['check.json', 'session.json'])
        session = next(self.stage.glob('reports/**/session.json'))
        self.assertIsNone(json.loads(session.read_text(encoding='utf-8'))['error'])

    def test_runtime_failure_with_all_applicable_reports_preserves_exit(self):
        (self.variant / 'ERB/main.erb').write_text(
            '@START\nTHROW diagnose failure\n', encoding='utf-8')
        result = self.run_batch(self.variant, '--entry', 'START', '--no-wait')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('Reports were written to:', result.stdout)
        self.assertEqual(sorted(p.name for p in self.stage.glob('reports/**/*.json')),
                         ['check.json', 'error.json', 'session.json'])

    def test_partial_report_write_is_explicit_and_exit_37_survives_display(self):
        self.fixture_engine(('--report', '--error-report'), 37)
        result = self.run_batch(self.variant)
        self.assertEqual(result.returncode, 37, result.stdout)
        self.assertIn('Only some reports were generated in this run:', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)
        self.assertIn('  check.json', result.stdout)
        self.assertIn('  error.json', result.stdout)
        self.assertNotIn('  session.json', result.stdout)

    def test_no_report_exit_130_survives_display(self):
        self.fixture_engine((), 130)
        result = self.run_batch(self.variant)
        self.assertEqual(result.returncode, 130, result.stdout)
        self.assertIn('No reports were generated in this run.', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)

    def test_real_cli_session_write_collision_reports_partial_and_exit_1(self):
        # Let CLI validate the destinations normally. Only at write time create
        # a real directory collision; the original writer then raises OSError.
        # This covers a real CLI partial failure without changing the engine.
        text = (
            'from pathlib import Path\nimport sys\n'
            'sys.path.insert(0, ' + repr(str(self.engine)) + ')\n'
            'import pyemuera.cli as cli\n'
            'original = cli.write_report\n'
            'def write_report(path, obj, *args, **kwargs):\n'
            '    if Path(path).name == "session.json":\n'
            '        Path(path).mkdir()\n'
            '    return original(path, obj, *args, **kwargs)\n'
            'cli.write_report = write_report\n'
            'cli.entrypoint()\n')
        with zipfile.ZipFile(self.stage / 'PyEmuera.pyz', 'w') as archive:
            archive.writestr('__main__.py', text)
        result = self.run_batch(self.variant, '--entry', 'START', '--no-wait')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('Only some reports were generated in this run:', result.stdout)
        self.assertIn('  check.json', result.stdout)
        self.assertNotIn('  session.json', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)
        self.assertEqual(len(list(self.stage.glob('reports/**/check.json'))), 1)

    def test_old_reports_are_preserved_and_not_counted_after_early_failure(self):
        old = self.stage / 'reports/run-old'
        old.mkdir(parents=True)
        originals = {}
        for filename in ('check-old.json', 'session-old.json', 'error-old.json'):
            path = self.stage / 'reports' / filename
            path.write_bytes(b'{"old":true}\n')
            originals[path] = path.read_bytes()
        for filename in ('check.json', 'session.json', 'error.json'):
            path = old / filename
            path.write_bytes(b'{"old":true}\n')
            originals[path] = path.read_bytes()
        result = self.run_batch(self.stage / 'missing')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('No reports were generated in this run.', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)
        for path, raw in originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_existing_run_directory_is_never_reused_even_when_random_collides(self):
        old = self.stage / 'reports/run-1936-1936-1936'
        old.mkdir(parents=True)
        path = old / 'check.json'
        path.write_bytes(b'old report')
        result = self.run_batch(self.variant, env_updates={'RANDOM': '1936'})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('A new report folder could not be created', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)
        self.assertEqual(path.read_bytes(), b'old report')

    def test_reports_path_blocked_by_file_fails_without_saved_claim(self):
        path = self.stage / 'reports'
        path.write_bytes(b'preserve this user file')
        result = self.run_batch(self.variant)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('No reports were generated.', result.stdout)
        self.assertNotIn('Reports were written to:', result.stdout)
        self.assertEqual(path.read_bytes(), b'preserve this user file')

    def test_write_denied_report_directory_fails_without_saved_claim(self):
        reports = self.stage / 'reports'
        reports.mkdir()
        raw = subprocess.check_output(
            ['whoami', '/user', '/fo', 'csv', '/nh'], encoding='utf-8')
        sid = next(csv.reader(io.StringIO(raw.strip())))[1]
        deny = subprocess.run(
            ['icacls', str(reports), '/deny', '*' + sid + ':(WD,AD)'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        try:
            result = self.run_batch(self.variant)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn('A new report folder could not be created', result.stdout)
            self.assertNotIn('Reports were written to:', result.stdout)
            self.assertEqual(list(reports.iterdir()), [])
        finally:
            subprocess.run(['icacls', str(reports), '/remove:d', '*' + sid],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)


if __name__ == '__main__':
    unittest.main()
