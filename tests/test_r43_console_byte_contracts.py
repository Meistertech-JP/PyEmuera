"""Neutral raw-byte/Console tests keep source decoding separate from log encoding."""
from pathlib import Path
import hashlib
import io
import json
import shutil
import tempfile
import unittest

from pyemuera.console import Console
from pyemuera.data import GameData
from pyemuera.errors import InternalError
from pyemuera.program import Program
from pyemuera.runtime import VM
from pyemuera.text import read_text

FIXTURES = Path(__file__).parent / 'fixtures/r43_console_bytes'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text())


class ConsoleByteContract(unittest.TestCase):
    def test_cp932_and_bom_utf8_both_line_endings_keep_raw_sources(self):
        for row in MANIFEST['rows']:
            if row['encoding_at_creation'] == 'utf-8':
                continue
            with self.subTest(file=row['file']), tempfile.TemporaryDirectory() as temporary:
                game = Path(temporary)
                (game / 'ERB').mkdir()
                (game / 'CSV').mkdir()
                source = FIXTURES / row['file']
                target = game / 'ERB/Main.ERB'
                shutil.copyfile(source, target)
                raw = source.read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
                decoded, encoding = read_text(target)
                self.assertEqual(encoding, row['expected_auto_decoder'])
                self.assertEqual(decoded.replace('\r\n', '\n'), '@MAIN\nPRINTL 日本語…\nRETURN\n')
                output = io.StringIO()
                console = Console(output=output, no_wait=True)
                vm = VM(Program(game), GameData(game), console, seed=42, max_steps=10)
                vm.call('MAIN')
                self.assertEqual(output.getvalue(), '日本語…\n')
                self.assertEqual(list(console.lines), ['日本語…'])
                self.assertEqual(list(console.log_lines), ['日本語…'])
                # The diagnostic/log serialization is explicitly UTF-8. It does
                # not choose how Program reads ERB, nor mutate the source.
                log = game / 'neutral_log.txt'
                log.write_text(output.getvalue(), encoding='utf-8', newline='\n')
                self.assertEqual(log.read_bytes(), '日本語…\n'.encode('utf-8'))
                self.assertEqual(source.read_bytes(), raw)
                self.assertEqual(target.read_bytes(), raw)

    def test_utf8_without_bom_is_not_silently_promoted_from_cp932(self):
        source = FIXTURES / 'utf_8_lf.ERB'
        raw = source.read_bytes()
        automatic, chosen = read_text(source)
        explicit, explicit_encoding = read_text(source, encoding='utf-8')
        self.assertEqual(chosen, 'cp932')
        self.assertNotEqual(automatic, explicit)
        self.assertEqual(explicit_encoding, 'utf-8')
        self.assertEqual(explicit, '@MAIN\nPRINTL 日本語…\nRETURN\n')
        self.assertEqual(source.read_bytes(), raw)

    def test_print_host_failure_stops_later_vm_assignments_without_rng_consumption(self):
        class Fault(io.StringIO):
            def isatty(self):
                return True

            def write(self, text):
                raise OSError('neutral print host failure')
        for backend in ('stream', 'diff'):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as temporary:
                game = Path(temporary)
                (game / 'ERB').mkdir()
                (game / 'CSV').mkdir()
                (game / 'ERB/Main.ERB').write_bytes('@MAIN\nPRINTL broken\nA=99\nRETURN\n'.encode('cp932'))
                console = Console(output=Fault(), layout='terminal', no_wait=True)
                console.vt_enabled = backend == 'diff'
                console.configure_renderer(backend)
                vm = VM(Program(game), GameData(game), console, seed=42, max_steps=10)
                before = vm.rng.getstate()
                before_result = vm.get('RESULT')
                with self.assertRaises(InternalError) as caught:
                    vm.call('MAIN')
                self.assertEqual(caught.exception.code, 'E_INTERNAL')
                self.assertIsInstance(caught.exception.__cause__, OSError)
                self.assertEqual(str(caught.exception.__cause__), 'neutral print host failure')
                self.assertEqual(vm.get('A'), 0)
                self.assertEqual(vm.get('RESULT'), before_result)
                self.assertEqual(vm.rng.getstate(), before)
                self.assertEqual(console.line_count, 0)
                self.assertEqual(list(console.lines), [])
                self.assertEqual(console.input_count, 0)
