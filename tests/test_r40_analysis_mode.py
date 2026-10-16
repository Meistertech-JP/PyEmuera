"""Native r34 transcript acceptance and non-executing analysis contracts."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pyemuera.analysis_mode import analyze, enumerate_targets
from pyemuera.call_syntax import constant_form_name
from pyemuera.cli import main, parser
from pyemuera.errors import EraError
from pyemuera.runtime import VM
from test_core import Harness, ROOT

class AnalysisMode(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'ERB').mkdir(); (self.root/'CSV').mkdir()
    def source(self,text,name='Main.ERB'):
        path=self.root/'ERB'/name; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(text,encoding='utf-8-sig'); return path
    def config(self,text):
        (self.root/'CSV/_fixed.config').write_text(text,encoding='utf-8-sig')
    def analyze(self): return analyze([self.root/'ERB'])
    def test_received_r34_bytes_except_host_path(self):
        evidence=ROOT/'verification/r35/received_r34'
        for name in ['ERB/Main.ERB','CSV/_fixed.config']:
            (self.root/name).write_bytes((evidence/'fixtures/fx/warnings-analysis'/(name+'.txt')).read_bytes())
        native=(evidence/'evidence/ana5/warnings-analysis/Analysis.log').read_bytes()
        native_path=native.decode('utf-16').split('\r\n')[1].removesuffix('読み込み中・・・')
        result=self.analyze(); actual=result.log_path.read_bytes()
        self.assertEqual(actual[:2],b'\xff\xfe')
        normalized=actual.decode('utf-16').replace(str(self.root/'ERB/Main.ERB'),native_path)
        self.assertEqual(b'\xff\xfe'+normalized.encode('utf-16le'),native)
        self.assertEqual(result.report['undefined_calls'],{'FIRST':2,'SECOND':1})
        self.assertEqual(len(result.report['undefined_callf']),1)
    def test_no_game_events_or_rng_consumption(self):
        self.source('@SYSTEM_TITLE\nA = RAND:100\nCALL EVENTFIRST\nQUIT\n@EVENTFIRST\nA = 77\nRETURN\n')
        with patch.object(VM,'run',side_effect=AssertionError('game')),patch.object(VM,'call',side_effect=AssertionError('callback')):
            result=self.analyze()
        self.assertEqual(result.vm.steps,0); self.assertEqual(result.vm.frames,[]); self.assertEqual(result.vm.get('A'),0)
        from pyemuera.random1824 import EngineRandom
        self.assertEqual(result.vm.rng.getstate(),EngineRandom(0).getstate())
    def test_expression_callf_and_call_distinct(self):
        self.source('@SYSTEM_TITLE\nCALL MISSING\nCALLF METHOD\nA = UNKNOWN(1) + UNKNOWN(2)\nQUIT\n')
        result=self.analyze()
        self.assertEqual(result.report['undefined_calls'],{'MISSING':1})
        self.assertEqual(result.report['undefined_expression_calls'],{'UNKNOWN':2})
        self.assertIn('　○文中関数:',result.lines)
        self.assertTrue(any(line.endswith(':METHOD') for line in result.lines))
    def test_null_term_zero_division(self):
        self.source('@SYSTEM_TITLE\nA = 1 / ABSENT()\nQUIT\n'); result=self.analyze()
        self.assertEqual(result.report['undefined_expression_calls'],{'ABSENT':1})
        self.assertTrue(any('0による除算' in line for line in result.lines))
    def test_unknown_expression_children_first(self):
        self.source('@SYSTEM_TITLE\nA = ABSENT(NOT_A_VARIABLE)\nQUIT\n'); result=self.analyze()
        self.assertEqual(result.report['undefined_expression_calls'],{})
        self.assertTrue(any('NOT_A_VARIABLE' in line for line in result.lines))
    def test_uncalled_without_system_root(self):
        self.source('@UNUSED\nCALL ABSENT\nRETURN\n'); self.config('FunctionNotCalledWarning:DISPLAY\nDisplayWarningLevel:3\n')
        result=self.analyze(); self.assertEqual(len(result.report['uncalled_functions']),1)
        self.assertTrue(any('一度も呼び出されません' in line for line in result.lines))
        self.assertEqual(result.report['undefined_calls'],{'ABSENT':1})
    def test_analysis_uncalled_body_warning_precedes_header(self):
        self.source('@SYSTEM_TITLE\nQUIT\n@UNUSED\nA = "bad"\n')
        self.config('FunctionNotCalledWarning:DISPLAY\n')
        result = self.analyze()
        diagnostics = result.report['diagnostics']
        self.assertEqual([d['line'] for d in diagnostics], [4, 3])

    def test_uncalled_ignore_policy(self):
        self.source('@SYSTEM_TITLE\nQUIT\n@UNUSED\nCALL ABSENT\n');self.config('FunctionNotCalledWarning:IGNORE\n')
        result=self.analyze();self.assertFalse(any('一度も呼び出されません' in line for line in result.lines))
        self.assertEqual(result.report['undefined_calls'],{'ABSENT':1})
    def test_replace_bypassed(self):
        self.source('@SYSTEM_TITLE\nQUIT\n');(self.root/'CSV/_Replace.csv').write_text('LoadLabel,REPLACED\n',encoding='utf-8-sig')
        result=self.analyze();self.assertEqual(result.lines[0],'Now Loading...')
    def test_single_file_limits_targets(self):
        first=self.source('@FIRST\nRETURN\n');self.source('@OTHER\nRETURN\n','Other.ERB')
        result=analyze([first]);self.assertEqual([f['name'] for f in result.report['functions']],['FIRST'])
    def test_multiple_target_order(self):
        a=self.source('@FIRST\nRETURN\n','A.ERB');b=self.source('@SECOND\nRETURN\n','B.ERB')
        self.assertEqual(analyze([b,a]).report['files'],[str(b),str(a)])
    def test_subdirectory_first_sorted_policy(self):
        a=self.source('@TOP\nRETURN\n','A.ERB');b=self.source('@SUB\nRETURN\n','sub/Z.ERB')
        self.assertEqual(enumerate_targets([self.root/'ERB'],{'サブディレクトリを検索する':'YES','読み込み順をファイル名順にソートする':'YES'}),[b,a])
        self.assertEqual(enumerate_targets([self.root/'ERB'],{}),[a])
    def test_lexical_error_continues(self):
        self.source('@SYSTEM_TITLE\nTHIS_IS_INVALID\nCALL OTHER\nQUIT\n');result=self.analyze()
        self.assertTrue(any('解釈できない行' in line for line in result.lines))
        self.assertEqual(result.report['undefined_calls'],{'OTHER':1})
        self.assertTrue(result.lines[-1].startswith('ファイル解析終了'))
    def test_structural_error_retained(self):
        self.source('@SYSTEM_TITLE\nIF 1\nQUIT\n');result=self.analyze()
        self.assertTrue(result.report['load_errors']);self.assertEqual(result.vm.steps,0)
    def test_cli_and_json(self):
        self.source('@SYSTEM_TITLE\nQUIT\n');report=self.root/'analysis.json'
        with contextlib.redirect_stdout(io.StringIO()):code=main(['--analysis',str(self.root/'ERB'),'--report',str(report)])
        self.assertEqual(code,0);self.assertEqual(json.loads(report.read_text())['format'],'PyEmuera-Analysis-1')
    def test_check_remains_distinct(self):
        self.source('@SYSTEM_TITLE\nQUIT\n')
        with contextlib.redirect_stdout(io.StringIO()):code=main([str(self.root),'--check'])
        self.assertEqual(code,0);self.assertFalse((self.root/'Analysis.log').exists())
        self.assertFalse(parser().parse_args(['--check']).analysis)
    def test_rand_declaration_rejected_without_consumption(self):
        self.source('@SYSTEM_TITLE\n#DIM X = RAND:100\nQUIT\n')
        from pyemuera.random1824 import EngineRandom
        with patch.object(EngineRandom, 'randrange', side_effect=AssertionError('RNG consumed')):
            result = self.analyze()
        self.assertEqual(result.report['diagnostics'][0]['category'], 'E_DECLARATION')
        self.assertEqual(result.report['diagnostics'][0]['severity'], 2)
        self.assertNotIn('X', result.vm.static[result.program.functions['SYSTEM_TITLE'][0].uid])
        self.assertTrue(result.report['analysis_complete'])
    def test_constant_declaration_initialization(self):
        self.source('@SYSTEM_TITLE\n#DIM CONST TESTCONST = 2 + 3\n#DIM TESTVALUE = MAX(TESTCONST, 4)\nQUIT\n')
        result = self.analyze()
        function = result.program.functions['SYSTEM_TITLE'][0]
        self.assertEqual(result.vm.static[function.uid]['TESTVALUE'].get((0,)), 5)
        self.assertEqual(result.vm.steps, 0)
    def test_config_and_constant_array_method_initialization(self):
        self.source('@SYSTEM_TITLE\n#DIMS CONST TESTNAMES, 2 = "one", "two"\n#DIM TESTFOUND = FINDELEMENT(TESTNAMES, "two")\n#DIM TESTSIZE = VARSIZE("A")\n#DIMS TESTCONFIG = GETCONFIGS("フォント名")\nQUIT\n')
        self.config('FontName:AnalysisTitle\n')
        result = self.analyze()
        values = result.vm.static[result.program.functions['SYSTEM_TITLE'][0].uid]
        self.assertEqual(values['TESTFOUND'].get((0,)), 1)
        self.assertEqual(values['TESTSIZE'].get((0,)), 1000)
        self.assertEqual(values['TESTCONFIG'].get((0,)), 'AnalysisTitle')

    def test_strform_declaration_refuses_hidden_rng(self):
        self.source('@SYSTEM_TITLE\n#DIMS TESTVALUE = STRFORM("{RAND:100}")\nQUIT\n')
        from pyemuera.random1824 import EngineRandom
        with patch.object(EngineRandom, 'randrange', side_effect=AssertionError('RNG consumed')):
            result = self.analyze()
        self.assertEqual(result.report['diagnostics'][0]['category'], 'E_DECLARATION')
        self.assertNotIn('TESTVALUE', result.vm.static[result.program.functions['SYSTEM_TITLE'][0].uid])
        self.assertTrue(result.report['analysis_complete'])

    def test_csv_and_header_progress_and_report_totals(self):
        self.source('@SYSTEM_TITLE\nCALL CHILD\nQUIT\n@CHILD\nRETURN\n@UNUSED\nRETURN\n')
        (self.root/'CSV/ABL.csv').write_text('0,Skill\n', encoding='utf-8-sig')
        (self.root/'CSV/Chara0.csv').write_text('NO,0\nNAME,Test\n', encoding='utf-8-sig')
        (self.root/'ERB/Vars.ERH').write_text('#DIM CONST TESTCONSTANT = 3\n', encoding='utf-8-sig')
        self.config('DisplayReport:YES\n')
        result = self.analyze()
        self.assertIn('ABL.CSV読み込み中・・・', result.lines)
        self.assertIn('Chara0.csv読み込み中・・・', result.lines)
        self.assertIn('Vars.ERH読み込み中・・・', result.lines)
        self.assertIn('非コメント行数:8, 全関数合計:3, 被呼出関数合計:2', result.lines)
        self.assertNotIn('Now Loading...', result.lines)

    def test_name_csv_progress_even_without_display_report(self):
        self.source('@SYSTEM_TITLE\nQUIT\n')
        (self.root/'CSV/ABL.csv').write_text('0,Skill\n', encoding='utf-8-sig')
        self.assertIn('ABL.CSV読み込み中・・・', self.analyze().lines)

    def test_history_uses_source_default_and_analysis_override(self):
        from pyemuera.analysis_mode import _loading_lines
        self.source('@SYSTEM_TITLE\nQUIT\n')
        with patch('pyemuera.analysis_mode._loading_lines', return_value=iter(['line']*5010)):
            result = self.analyze()
        self.assertEqual(result.report['history_limit'], 5000)
        self.assertEqual(len(result.lines), 5000)
        self.config('MaxLog:invalid\nDisplayReport:YES\n')
        result = self.analyze()
        self.assertEqual(result.report['history_limit'], 10000)
        self.assertTrue(any('非コメント行数' in line for line in result.lines))

    def test_cli_conflict_rejected(self):
        self.source('@SYSTEM_TITLE\nQUIT\n')
        with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(main(['--analysis',str(self.root/'ERB'),'--check']),1)
        self.assertFalse((self.root/'Analysis.log').exists())

class ConstantFormAndLabelGuard(Harness):
    def test_operator_constant_form(self):
        self.assertEqual(constant_form_name('%"CHI" + "LD"%'),'CHILD')
        self.assertEqual(constant_form_name('FUNC{1+2}'),'FUNC3')
        self.assertEqual(constant_form_name('FUNC%TOSTR(MAX(2,3))%'),'FUNC3')
        self.assertEqual(constant_form_name('\\@1?CHILD#OTHER\\@'),'CHILD')
    def test_effectful_form_dynamic(self):
        for text in ['FUNC{RAND:10}','FUNC{A++}','%CUSTOM()%']:self.assertIsNone(constant_form_name(text))
    def test_constant_form_reachability(self):
        vm=self.make('@SYSTEM_TITLE\nCALLFORM %"CHI"+"LD"%\nQUIT\n@CHILD\nRETURN\n@UNUSED\nRETURN\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertEqual(vm.program.argument_analysis_scope,'reference_system_call_graph')
        self.assertEqual([d.source_text for d in vm.program.uncalled_diagnostics],['@UNUSED'])
    def test_const_array_form_reachability_without_dynamic_reads(self):
        vm=self.make('@SYSTEM_TITLE\n#DIMS CONST DESTINATIONS, 2 = "OTHER", "CHILD"\nCALLFORM %DESTINATIONS:1%\nQUIT\n@CHILD\nRETURN\n@OTHER\nA++\nRETURN\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertEqual(vm.program.argument_analysis_scope,'reference_system_call_graph')
        self.assertEqual([d.source_text for d in vm.program.uncalled_diagnostics],['@OTHER'])
        self.assertEqual(vm.get('A'),0)

    def test_config_constant_form_target(self):
        vm=self.make('@SYSTEM_TITLE\nCALLFORM FUNC{GETCONFIG("PrintCPerLine")}\nQUIT\n@FUNC3\nRETURN\n@UNUSED\nRETURN\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertEqual(vm.program.argument_analysis_scope,'reference_system_call_graph')
        self.assertEqual([d.source_text for d in vm.program.uncalled_diagnostics],['@UNUSED'])

    def test_const_reference_methods_form_target(self):
        vm=self.make('@SYSTEM_TITLE\n#DIMS CONST TESTPARTS, 2 = "CHI", "LD"\nCALLFORM %STRJOIN(TESTPARTS, "")%\nQUIT\n@CHILD\nRETURN\n@UNUSED\nRETURN\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertEqual(vm.program.argument_analysis_scope,'reference_system_call_graph')
        self.assertEqual([d.source_text for d in vm.program.uncalled_diagnostics],['@UNUSED'])

    def test_strform_constant_nested_target(self):
        vm=self.make('@SYSTEM_TITLE\nCALLFORM %STRFORM("CHILD")%\nQUIT\n@CHILD\nRETURN\n@UNUSED\nRETURN\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertEqual(vm.program.argument_analysis_scope,'reference_system_call_graph')
        self.assertEqual([d.source_text for d in vm.program.uncalled_diagnostics],['@UNUSED'])

    def test_keyword_metadata_form_without_reading_index(self):
        vm=self.make('@SYSTEM_TITLE\nCALLFORM FUNC{GETNUM(ABL:RAND:10,"Skill")}\nQUIT\n@FUNC0\nRETURN\n@UNUSED\nRETURN\n',csv={'ABL.csv':'0,Skill\n','_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertEqual(vm.program.argument_analysis_scope,'reference_system_call_graph')
        self.assertEqual([d.source_text for d in vm.program.uncalled_diagnostics],['@UNUSED'])

    def test_tostr_optional_null_constant_form(self):
        self.assertEqual(constant_form_name('FUNC%TOSTR(1,)%'), 'FUNC1')
        vm=self.make('@SYSTEM_TITLE\nCALLFORM FUNC%TOSTR(1,)%\nQUIT\n@FUNC1\nRETURN\n@UNUSED\nA=RAND:100\nRETURN\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        self.assertEqual(vm.program.argument_analysis_scope,'reference_system_call_graph')
        self.assertEqual([d.source_text for d in vm.program.uncalled_diagnostics],['@UNUSED'])
        self.assertEqual(vm.steps, 0)

    def test_optional_null_fix_does_not_fold_default_reducer_or_effects(self):
        from pyemuera.constant_ast import Reducer
        from pyemuera.expr import parse
        self.assertEqual(Reducer().reduce(parse('TOSTR(1,)'))[0], 'call')
        self.assertIsNone(constant_form_name('FUNC%TOSTR(RAND:100,)%'))
        self.assertIsNone(constant_form_name('FUNC%TOSTR(A++,)%'))
        self.assertIsNone(constant_form_name('FUNC%TOSTR(,)%'))

    def test_first_label_guard(self):
        vm=self.make('@SYSTEM_TITLE\nQUIT\n@UNUSED\n$START\nA = 42\nRETURN\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        with self.assertRaises(EraError) as caught:vm.call('UNUSED')
        self.assertEqual(caught.exception.code,'E_UNCALLED');self.assertEqual(caught.exception.location.line,4);self.assertEqual(vm.get('A'),0)
    def test_label_only_guard(self):
        vm=self.make('@SYSTEM_TITLE\nQUIT\n@UNUSED\n$START\n',csv={'_fixed.config':'IgnoreUncalledFunction:YES\n'})
        with self.assertRaises(EraError) as caught:vm.call('UNUSED')
        self.assertEqual(caught.exception.code,'E_UNCALLED')
    def test_user_override_not_constant(self):
        from pyemuera.program import Function
        from pyemuera.errors import Location
        functions={'POWER':[Function('POWER',[],Location('x',1),attributes={'FUNCTION'})]}
        self.assertIsNone(constant_form_name('X{POWER(2,3)}',functions))
