"""Source-backed input/history and physical diagnostic regressions.
These tests do not certify Windows conhost rendering.
"""
import io,sys,types,unittest
from unittest.mock import patch
from test_core import Harness
from pyemuera.console import Console
from pyemuera.errors import EraError

class TTY(io.StringIO):
 def isatty(self):return True

class InputBoundaryR14(Harness):
 def test_backend_events_are_exported_separately(self):
  from pyemuera.journal import RunJournal
  j=RunJournal();v=self.make('@MAIN\nPRINTL body',journal=j)
  with patch.object(sys,'stderr',io.StringIO()):v.console.warning('fixture','backend warning')
  r=j.report('quit');self.assertEqual(r['backend_diagnostics'][0]['layer'],'physical_diagnostic');self.assertEqual(list(v.console.log_lines),[])
 def test_observed_INPUT_button_WAITANYKEY_history(self):
  v=self.make('@MAIN\nPRINTL ORACLE|begin\nPRINTBUTTON "choose",2\nINPUT\nPRINTFORML ORACLE|result|int|{RESULT}\nWAITANYKEY\nPRINTL ORACLE|end',inputs=['2',{'kind':'key_wait','text':' '}]);v.console.no_wait=False;v.call('MAIN')
  self.assertEqual(list(v.console.log_lines),['ORACLE|begin','choose','2','ORACLE|result|int|2','ORACLE|end'])
  self.assertIn('ORACLE|result|int|2',v.console.log_lines)
 def test_continuous_inputs_separate_rows(self):
  v=self.script('PRINT first\nINPUT\nPRINT second\nINPUTS',inputs=['2','text'])
  self.assertEqual(list(v.console.log_lines),['first','2','second','text'])
 def test_empty_string_does_not_invent_blank_echo(self):
  v=self.script('PRINT prompt\nINPUTS\nPRINTL after',inputs=[''])
  self.assertEqual(list(v.console.log_lines),['prompt','after'])
 def test_default_input_echo_uses_accepted_value(self):
  v=self.script('PRINT prompt\nINPUT 7',inputs=['']);self.assertEqual(list(v.console.log_lines),['prompt','7'])
 def test_wait_flushes_pending_without_key_echo(self):
  v=self.make('@MAIN\nPRINT pending\nWAIT\nPRINTL after',inputs=['']);v.console.no_wait=False;v.call('MAIN')
  self.assertEqual(list(v.console.log_lines),['pending','after'])
 def test_input_EOF_retains_flushed_prompt(self):
  v=self.make('@MAIN\nPRINT pending\nINPUT',inputs=[])
  with self.assertRaises(EraError):v.call('MAIN')
  self.assertEqual(list(v.console.log_lines),['pending'])
 def test_error_after_input_keeps_echo(self):
  v=self.make('@MAIN\nPRINT pending\nINPUT\nA=1/0',inputs=['2'])
  with self.assertRaises(EraError):v.call('MAIN')
  self.assertEqual(list(v.console.log_lines),['pending','2'])
 def test_native_oneinput_does_not_double_echo(self):
  v=self.make('@MAIN\nONEINPUTS');v.console.inputs=None
  fake=types.SimpleNamespace(kbhit=lambda:True,getwch=lambda:'x')
  with patch('pyemuera.console.os.name','nt'),patch.dict(sys.modules,msvcrt=fake),patch.object(sys,'stdin',TTY()):v.call('MAIN')
  self.assertEqual(list(v.console.log_lines),['x']);self.assertEqual(self.output.getvalue().count('x'),1)
 def test_native_timed_prompt_is_not_logical(self):
  c=Console(output=TTY());keys=iter(['a','\r']);fake=types.SimpleNamespace(kbhit=lambda:True,getwch=lambda:next(keys))
  with patch('pyemuera.console.os.name','nt'),patch.dict(sys.modules,msvcrt=fake),patch.object(sys,'stdin',TTY()):
   x=c.input(string=True,timeout_ms=100);c._input_echo(x)
  self.assertEqual(list(c.log_lines),['a']);self.assertNotIn('>', ''.join(c.log_lines))
 def test_native_host_echo_recorded_without_second_write(self):
  c=Console(output=TTY());c.write('pending')
  with patch('builtins.input',return_value='7'),patch.object(sys,'stdin',TTY()):x=c.input();c._input_echo(str(x))
  self.assertEqual(list(c.log_lines),['pending','7']);self.assertEqual(c.output.getvalue(),'pending\n')

class PhysicalDiagnosticsR14(unittest.TestCase):
 def exercise(self,renderer,columns,warning):
  out=TTY();c=Console(output=out,layout='terminal');c.columns=columns;c.enable_color('always');c.configure_renderer(renderer)
  if c._frame:c._frame.size_provider=lambda:(columns,24)
  c.write('LR',True);c.write('after')
  history=(list(c.log_lines),c.log_current,list(c.lines),c.current,list(c.markup_lines),list(c.markup_current))
  with patch.object(c,'_diagnostic_shares_terminal',return_value=True),patch.object(sys,'stderr',out):
   if warning:c.warning('fixture','visible warning')
  self.assertEqual(history,(list(c.log_lines),c.log_current,list(c.lines),c.current,list(c.markup_lines),list(c.markup_current)))
  if warning:
   self.assertIn('visible warning',out.getvalue());self.assertFalse(c.diagnostic_events[-1]['logical_history_changed'])
   if c._frame:
    self.assertEqual(c._frame.last_cursor,(2,6));self.assertTrue(c._frame.diagnostic_lines)
    self.assertIn('\x1b[24;1H',out.getvalue())
   else:self.assertIn('after\n[PyEmuera warning]',out.getvalue().replace('\x1b[0m',''))
  c.write('tail',True)
  self.assertEqual(c.last_line(),'aftertail');self.assertEqual(c.log_lines[-1],'aftertail');c.close()
 def test_redirected_stderr_leaves_frame_projection_alone(self):
  out=TTY();c=Console(output=out);c.enable_color('always');c.configure_renderer('diff');c.write('x',True);old=c._frame.previous
  with patch.object(sys,'stderr',io.StringIO()):c.warning('fixture','warning')
  self.assertEqual(c._frame.previous,old);self.assertFalse(c.diagnostic_events[-1]['shared_terminal']);c.close()
for renderer in ['stream','diff']:
 for columns in [84,86,100]:
  for warning in [False,True]:
   def test(self,r=renderer,n=columns,w=warning):self.exercise(r,n,w)
   setattr(PhysicalDiagnosticsR14,f'test_{renderer}_{columns}_warning_{warning}',test)
if __name__=='__main__':unittest.main()
