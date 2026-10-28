"""Launcher .cmd shims must return control and preserve engine exit codes."""
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
NAMES = ('Start_PyEmuera.bat', 'Check_PyEmuera.bat', 'Diagnose_PyEmuera.bat')


@unittest.skipUnless(os.name == 'nt', 'Windows cmd.exe batch acceptance')
class BatchLauncherB2(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='b2 launcher ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / 'shim bin'
        self.bin.mkdir()
        for name in NAMES:
            shutil.copyfile(ROOT / 'packaging/public' / name, self.root / name)
        with zipfile.ZipFile(self.root / 'PyEmuera.pyz', 'w') as archive:
            archive.writestr('__main__.py', '''import json,sys
from pathlib import Path
a=sys.argv[1:]
Path('received.json').write_text(json.dumps(a), encoding='utf8')
for flag in ('--report','--session-report'):
 if flag in a: Path(a[a.index(flag)+1]).write_text('{}', encoding='utf8')
raise SystemExit(37)
''')
        self.env = os.environ.copy()
        self.env.update(PYEMUERA_NO_PAUSE='1', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        self.env.pop('PYTHONPATH', None)
        self.env['PATH'] = os.pathsep.join((str(self.bin), str(Path(sys.executable).parent),
                                           str(Path(os.environ['SystemRoot']) / 'System32')))

    def run_batch(self, name):
        command = 'call ' + subprocess.list2cmdline([str(self.root / name), 'argument with space'])
        return subprocess.run(subprocess.list2cmdline([os.environ['COMSPEC']]) + ' /d /c ' + command,
                              cwd=self.root, env=self.env, input='', encoding='utf8', errors='replace',
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)

    def test_failing_py_cmd_falls_back_and_preserves_arguments_and_exit(self):
        (self.bin / 'py.cmd').write_bytes(b'@echo off\r\nexit /b 7\r\n')
        for name in NAMES:
            with self.subTest(name=name):
                result = self.run_batch(name)
                self.assertEqual(result.returncode, 37, result.stdout)
                args = json.loads((self.root / 'received.json').read_text(encoding='utf8'))
                self.assertEqual(args[0], 'argument with space')
                if name.startswith('Diagnose'):
                    self.assertIn('Only some reports', result.stdout)

    def test_successful_py_cmd_uses_interpreter_without_losing_control(self):
        shim = '@echo off\r\nif "%~1"=="-3" shift\r\n"' + sys.executable + '" %*\r\n'
        (self.bin / 'py.cmd').write_bytes(shim.encode('oem'))
        for name in NAMES:
            with self.subTest(name=name):
                result = self.run_batch(name)
                self.assertEqual(result.returncode, 37, result.stdout)
                self.assertEqual(json.loads((self.root / 'received.json').read_text(encoding='utf8'))[0],
                                 'argument with space')


if __name__ == '__main__':
    unittest.main()
