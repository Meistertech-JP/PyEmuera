"""Host interruption notice must outlive terminal teardown, unlike ERB output."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pyemuera.cli import main
from pyemuera.console import Console
from pyemuera.runtime import VM
from pyemuera.errors import EraError


class ExitNoticeContracts(unittest.TestCase):
    def run_cli(self, error):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'ERB').mkdir()
            (root/'CSV').mkdir()
            (root/'ERB/Main.ERB').write_text('@MAIN\nRETURN\n')
            events = []
            class ErrorOutput(io.StringIO):
                def write(self, value):
                    if 'PyEmuera interrupted.' in value:
                        events.append('notice')
                    return super().write(value)
            output = ErrorOutput()
            original_close = Console.close
            def close(console):
                original_close(console)
                events.append('closed')
            with patch.object(VM, 'run', side_effect=error), patch.object(Console, 'close', close), patch('sys.stderr', output):
                code = main([str(root), '--entry', 'MAIN', '--session-report', str(root/'session.json')])
            return code, events, output.getvalue(), json.loads((root/'session.json').read_text())

    def test_interrupt_notice_after_cleanup_exactly_once_and_130(self):
        code, events, text, session = self.run_cli(KeyboardInterrupt())
        self.assertEqual((code, events), (130, ['closed', 'notice']))
        self.assertEqual(text.count('PyEmuera interrupted.'), 1)
        self.assertEqual(session['outcome'], 'interrupted')
        self.assertIsNone(session['error'])

    def test_plain_eof_does_not_get_interrupt_notice(self):
        code, events, text, session = self.run_cli(EraError('closed input', code='E_INPUT_EOF'))
        self.assertEqual((code, events), (1, ['closed']))
        self.assertNotIn('PyEmuera interrupted.', text)
        self.assertEqual(session['outcome'], 'input_exhausted')

    def test_other_error_does_not_get_interrupt_notice(self):
        code, events, text, session = self.run_cli(EraError('script failure', code='E_SCRIPT'))
        self.assertEqual((code, events), (1, ['closed']))
        self.assertNotIn('PyEmuera interrupted.', text)
        self.assertEqual(session['outcome'], 'error')
