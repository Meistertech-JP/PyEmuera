"""Received r34 diagnostic gaps; static checks must not evaluate operands."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from test_core import Harness, ROOT
from pyemuera.call_syntax import parse_call
from pyemuera.errors import EraError
from pyemuera.load_arguments import display_diagnostics
from pyemuera.audit import audit
from pyemuera import __version__

class Order(Harness):
    def policy(self, missing, uncalled, level=1, ignore='NO'):
        config=f'IgnoreUncalledFunction:{ignore}\nFunctionNotFoundWarning:{missing}\nFunctionNotCalledWarning:{uncalled}\nDisplayWarningLevel:{level}\n'
        return self.make('@SYSTEM_TITLE\nRETURN\n@UNUSED\nCALL FIRST\nCALL SECOND\nRETURN\n@ALSO_UNUSED\nCALL THIRD\nRETURN\n',csv={'_fixed.config':config})

    def test_called_body_diagnostics_precede_uncalled_pass(self):
        vm=self.make('@UNUSED\nCALL SECOND\nRETURN\n@SYSTEM_TITLE\nCALL FIRST\nRETURN\n',csv={'_fixed.config':'IgnoreUncalledFunction:NO\nFunctionNotFoundWarning:DISPLAY\nFunctionNotCalledWarning:DISPLAY\n'})
        display_diagnostics(vm)
        self.assertEqual([d['line'] for d in vm.emitted_diagnostics],[5,1,2])

    def test_hidden_missing_error_is_retained_at_execution(self):
        vm=self.policy('IGNORE','IGNORE',3)
        display_diagnostics(vm)
        self.assertEqual(vm.emitted_diagnostics,[])
        with self.assertRaises(EraError) as e:vm.call('UNUSED')
        self.assertEqual(e.exception.code,'E_FUNCTION')
        self.assertEqual(e.exception.location.line,4)

    def test_ordered_events_do_not_duplicate_registration(self):
        vm=self.policy('DISPLAY','DISPLAY')
        events=vm.program.load_diagnostic_events
        self.assertEqual(len(events),len(vm.program.argument_diagnostics)+len(vm.program.uncalled_diagnostics))
        self.assertEqual(len({id(d) for d in events}),len(events))
        display_diagnostics(vm);before=self.output.getvalue();display_diagnostics(vm)
        self.assertEqual(before,self.output.getvalue())

    def test_ignoreYES_headers_without_body_execution(self):
        vm=self.policy('DISPLAY','DISPLAY',ignore='YES');display_diagnostics(vm)
        self.assertEqual([d['line'] for d in vm.emitted_diagnostics],[3,7])
        self.assertEqual(vm.get('A'),0)

class Syntax(Harness):
    def test_cli_inventory_does_not_abort_before_loader(self):
        vm=self.make('@SYSTEM_TITLE\nCALL CHILD[](\nQUIT\n@CHILD\nRETURN\n')
        result=audit(vm.program,vm.data)
        self.assertTrue(result['issues'])
        display_diagnostics(vm)
        self.assertEqual(len(vm.emitted_diagnostics),1)
        self.assertIn('字句解析中',vm.emitted_diagnostics[0]['reference_message'])
        with self.assertRaises(EraError) as e:vm.call('SYSTEM_TITLE')
        self.assertEqual(e.exception.location.line,2)

    def test_unknown_subname_binding_precedes_unexpected_terminator(self):
        vm=self.make('@MAIN\nCALL CHILD[NOT_DEFINED]\nRETURN\n@CHILD\nRETURN\n')
        with self.assertRaises(EraError) as e:vm.call('MAIN')
        self.assertEqual(e.exception.code,'E_VARIABLE')
        self.assertIn('NOT_DEFINED',e.exception.message)

    def test_tail_strings_do_not_count_delimiters(self):
        self.assertEqual(parse_call('CHILD("](")').arguments,('"]("',))

    def test_normal_CALL_does_not_construct_subname_binding_context(self):
        from unittest.mock import patch
        vm=self.make('@MAIN\nCALL CHILD\nRETURN\n@CHILD\nB++\nRETURN\n')
        with patch('pyemuera.load_arguments.StaticContext', side_effect=AssertionError('unneeded binding')):
            vm.call('MAIN')
        self.assertEqual(vm.get('B'),1)

    def test_FORM_quoted_closing_bracket_is_inside_string(self):
        argument = 'CHILD(@"{STRLENS(")")}")'
        self.assertEqual(parse_call(argument).arguments, ('@"{STRLENS(")")}"',))

    def test_FORM_inner_quotes_preserve_runtime_side_effect(self):
        vm=self.script('CALL CHILD(@"{A++}{STRLENS(")")}")\nRETURN\n@CHILD(ARGS:0)\nSTR \'= ARGS:0\nRETURN')
        self.assertEqual(vm.get('A'),1)
        self.assertEqual(vm.get('STR'),'01')

class Encoding(Harness):
    def run_cli(self,arguments,encoding):
        env=dict(os.environ,PYTHONIOENCODING=encoding+':strict',PYTHONUTF8='0')
        return subprocess.run([sys.executable,str(ROOT/'PyEmuera.pyz'),*arguments],env=env,capture_output=True,timeout=30)

    def test_cp932_help_is_complete_and_matches_UTF8(self):
        cp=self.run_cli(['--help'],'cp932');utf=self.run_cli(['--help'],'utf-8')
        self.assertEqual(cp.returncode,0,cp.stderr)
        self.assertEqual(cp.stdout.decode('cp932'),utf.stdout.decode('utf-8'))
        self.assertIn('--max-steps',cp.stdout.decode('cp932'))
        self.assertNotIn('—',cp.stdout.decode('cp932'))
        self.assertEqual(cp.stderr,b'')

    def test_cp932_version(self):
        result=self.run_cli(['--version'],'cp932')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual('PyEmuera ' + __version__, result.stdout.decode('cp932').strip())

    def test_cp932_describe(self):
        result=self.run_cli(['--describe','UPCHECK'],'cp932')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('UPCHECK',result.stdout.decode('cp932'))

    def test_cp932_invalid_option_stderr(self):
        result=self.run_cli(['--not-an-option'],'cp932')
        self.assertEqual(result.returncode,2)
        self.assertIn('unrecognized arguments',result.stderr.decode('cp932'))

    def test_cp932_japanese_game_and_report(self):
        vm=self.make('@SYSTEM_TITLE\nPRINTL 日本語の表示\nQUIT\n')
        path=vm.program.root
        report=path/'check.json'
        result=self.run_cli([str(path),'--check','--report',str(report)],'cp932')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(report.is_file())
        result=self.run_cli([str(path),'--no-wait'],'cp932')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('日本語の表示',result.stdout.decode('cp932'))

for missing in ['IGNORE','DISPLAY','ONCE','LATER']:
    for uncalled in ['IGNORE','DISPLAY','ONCE','LATER']:
        def run(self,missing=missing,uncalled=uncalled):
            vm=self.policy(missing,uncalled);display_diagnostics(vm)
            expected=[]
            if uncalled in ['DISPLAY','ONCE']:expected+=[3]
            if missing in ['DISPLAY','ONCE','LATER']:expected+=[4]
            if missing in ['DISPLAY','LATER']:expected+=[5]
            if uncalled=='DISPLAY':expected+=[7]
            if missing in ['DISPLAY','LATER']:expected+=[8]
            self.assertEqual([d['line'] for d in vm.emitted_diagnostics],expected)
            self.assertEqual(len(vm.program.argument_diagnostics),3)
            self.assertEqual(len(vm.program.uncalled_diagnostics),2)
        setattr(Order,'test_order_'+missing+'_'+uncalled,run)
for level in [0,1,2,3]:
    def run(self,level=level):
        vm=self.policy('DISPLAY','DISPLAY',level);display_diagnostics(vm)
        expected=[3,4,5,7,8] if level<=1 else [4,5,8] if level==2 else []
        self.assertEqual([d['line'] for d in vm.emitted_diagnostics],expected)
    setattr(Order,'test_level_'+str(level),run)
for text in ['CHILD[](','CHILD(','CHILD[(']:
    def run(self,text=text):
        with self.assertRaises(EraError) as e:parse_call(text)
        self.assertEqual(e.exception.code,'E_SYNTAX')
        self.assertEqual(e.exception.message,"字句解析中に対応する')'のない'('を発見しました")
    setattr(Syntax,'test_lexical_'+str(len(text))+'_'+str(text.count('[')),run)
for text in ['A++','A','A,B','1','RAND(10)+A++']:
    def run(self,text=text):
        vm=self.make('@MAIN\nCALL CHILD['+text+']\nRETURN\n@CHILD\nB++\nRETURN\n')
        rng=vm.rng.getstate()
        with self.assertRaises(EraError) as e:vm.call('MAIN')
        self.assertEqual(e.exception.code,'E_SYNTAX')
        self.assertIn("記号','" if ',' in text else "記号']'",e.exception.message)
        self.assertEqual((vm.get('A'),vm.get('B')),(0,0))
        self.assertEqual(vm.rng.getstate(),rng)
    setattr(Syntax,'test_subname_'+str(['A++','A','A,B','1','RAND(10)+A++'].index(text)),run)
