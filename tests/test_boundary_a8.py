import io,os,sys,threading,time,unittest
from unittest.mock import patch
from test_core import Harness
from pyemuera.console import Console

class UTF16BoundaryA8(Harness):
    def test_json_keeps_unpaired_surrogate(self):
        vm=self.make();vm.set('SAVESTR','\ud83d');vm.saves.write(2,'\ud83d title')
        vm.set('SAVESTR','');vm.saves.load(2)
        self.assertEqual(vm.get('SAVESTR'),'\ud83d')
        self.assertEqual(vm.get('LASTLOAD_TEXT'),'\ud83d title')
        self.assertIn(b'\\ud83d',vm.saves.path(2).read_bytes())
    def test_raw_utf8_sink_replaces_only_at_boundary(self):
        raw=io.BytesIO();output=io.TextIOWrapper(raw,encoding='utf-8',errors='strict',newline='\n')
        con=Console([],output,no_wait=True,layout='raw');con.write('x\ud83dy',True)
        self.assertEqual(con.lines[-1],'x\ud83dy');self.assertEqual(raw.getvalue(),b'x?y\n')
    def test_terminal_utf8_sink_replaces_only_at_boundary(self):
        raw=io.BytesIO();output=io.TextIOWrapper(raw,encoding='utf-8',errors='strict',newline='\n')
        con=Console([],output,no_wait=True,layout='terminal');con.write('\ud83d',True)
        self.assertEqual(con.lines[-1],'\ud83d');self.assertIn(b'?',raw.getvalue())
    def test_native_binary_retains_surrogate_string(self):
        vm=self.make();vm.set('SAVESTR','\ud83d');vm.saves.format='emuera-binary';vm.saves.write(2)
        vm.set('SAVESTR','');vm.saves.load(2);self.assertEqual(vm.get('SAVESTR'),'\ud83d')

@unittest.skipUnless(os.name=='posix','POSIX pseudo-terminal required')
class PseudoTerminalInputA8(unittest.TestCase):
    def make_pty(self):
        import pty,termios
        master,slave=pty.openpty();self.addCleanup(os.close,master)
        stream=os.fdopen(slave,'r',encoding='utf-8',buffering=1);self.addCleanup(stream.close)
        return master,stream,termios.tcgetattr(slave)
    def test_one_key_needs_no_enter_and_restores_terminal(self):
        import termios
        master,stream,before=self.make_pty();con=Console(output=io.StringIO())
        def writer():
            time.sleep(.06);os.write(master,'界'.encode('utf-8'))
        thread=threading.Thread(target=writer);thread.start()
        with patch.object(sys,'stdin',stream):result=con._read_key(2)
        thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(result,'界')
        self.assertEqual(termios.tcgetattr(stream.fileno()),before)
    def test_single_key_timeout_restores_terminal(self):
        import termios
        _,stream,before=self.make_pty();con=Console(output=io.StringIO())
        with patch.object(sys,'stdin',stream):self.assertIsNone(con._read_key(.02))
        self.assertEqual(termios.tcgetattr(stream.fileno()),before)
    def test_single_key_interrupt_restores_terminal(self):
        import termios
        _,stream,before=self.make_pty();con=Console(output=io.StringIO())
        with patch.object(sys,'stdin',stream),patch('select.select',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            con._read_key(1)
        self.assertEqual(termios.tcgetattr(stream.fileno()),before)

class DiagnosticBoundaryA8(unittest.TestCase):
    def test_missing_game_does_not_raise_unbound_console(self):
        import tempfile
        from pyemuera.cli import main
        with tempfile.TemporaryDirectory() as td,patch.object(sys,'stderr',io.StringIO()):
            self.assertEqual(main([td+'/missing-game']),1)
    def test_report_json_roundtrips_surrogate_without_losing_japanese(self):
        import tempfile,json
        from pathlib import Path
        from pyemuera.cli import write_report
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'report.json';write_report(p,{'text':'日本\ud83d'})
            text=p.read_text(encoding='utf-8');self.assertIn('日本',text);self.assertEqual(json.loads(text)['text'],'日本\ud83d')
