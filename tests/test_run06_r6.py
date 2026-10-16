"""r6 contracts: run05 archived observations and explicitly source-only edges.

No expectation is synthesized from PyEmuera. Extra boundary cases are not a
claim of new Windows execution; their source contract is in verification/r6.
"""
from pathlib import Path
import unittest,io,tempfile,json,hashlib,copy
from unittest.mock import patch
from pyemuera.runtime import VM
from pyemuera.program import Program
from pyemuera.data import GameData
from pyemuera.console import Console
from pyemuera.errors import EraError
from pyemuera.registry import COMMAND_SPECS,FUNCTION_SPECS,validate_document
from pyemuera.constant_ast import Reducer
from pyemuera.expr import parse
from pyemuera.width1824 import convert
from pyemuera.journal import RunJournal
from tools.oracle_capture_r6 import select_capture,write_json

DECL='#DIM OR_A\n#DIM OR_B\n#DIM OR_IDX\n#DIM OR_TRACE\n#DIM OR_ARR,4\n#DIMS OR_STR\n#DIM CONST OR_CONST=3\n'
FUNCS='''@BASE
#FUNCTION
OR_TRACE=OR_TRACE*10+1
RETURNF 2
@EXP
#FUNCTION
OR_TRACE=OR_TRACE*10+2
RETURNF 3
@INDEX
#FUNCTION
OR_TRACE=OR_TRACE*10+3
RETURNF OR_IDX
@FAIL
#FUNCTION
OR_TRACE=OR_TRACE*10+4
RETURNF 1/OR_B
'''

class Neutral(unittest.TestCase):
    def make(self,body,mode='NO',ignore='YES',extra='',headers=DECL,journal=False):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);self.root=Path(td.name)
        (self.root/'ERB').mkdir();(self.root/'CSV').mkdir()
        (self.root/'ERB/Oracle.ERB').write_text('@SYSTEM_TITLE\n'+body+extra,encoding='utf-8-sig')
        (self.root/'ERB/Oracle.ERH').write_text(headers,encoding='utf-8-sig')
        (self.root/'emuera.config').write_text('ロード時に引数を解析する:'+mode+'\n呼び出されなかった関数を無視する:'+ignore+'\n',encoding='utf-8-sig')
        self.output=io.StringIO();j=RunJournal(seed=42) if journal else None
        vm=VM(Program(self.root),GameData(self.root),Console([],self.output,no_wait=True),seed=42,journal=j);self.vm=vm;return vm
    def run_error(self,vm,code):
        with self.assertRaises(EraError) as caught:vm.run()
        self.assertEqual(caught.exception.code,code);return caught.exception


class PowerInstructionR6(Neutral):
    def test_supplement_declared_command_eight(self):
        vm=self.make('POWER OR_A,2,3\nQUIT\n');vm.run();self.assertEqual(vm.eval('OR_A'),8)
    def test_function_eight_unchanged(self):
        vm=self.make('OR_A=POWER(2,3)\nQUIT\n');vm.run();self.assertEqual(vm.eval('OR_A'),8)
    def test_same_name_registration_separates_contexts(self):
        self.assertEqual(COMMAND_SPECS['POWER']['argument_builder'],'power_int64_destination')
        self.assertEqual((FUNCTION_SPECS['POWER']['min_args'],FUNCTION_SPECS['POWER']['max_args']),(2,2))
        vm=self.make('RESULT=97\nPOWER OR_A,2,3\nOR_B=POWER(3,2)\nQUIT\n');vm.run()
        self.assertEqual((vm.eval('OR_A'),vm.eval('OR_B'),vm.eval('RESULT')),(8,9,97))
    def test_target_index_after_both_sources_once(self):
        vm=self.make('OR_IDX=1\nPOWER OR_ARR:INDEX(),BASE(),EXP()\nQUIT\n',extra=FUNCS);vm.run()
        self.assertEqual((vm.eval('OR_TRACE'),vm.eval('OR_ARR:1')),(123,8))
    def test_dynamic_index_reads_state_after_source_effects(self):
        vm=self.make('POWER OR_ARR:OR_IDX,CHANGE(),3\nQUIT\n',extra='@CHANGE\n#FUNCTION\nOR_IDX=2\nRETURNF 2\n');vm.run()
        self.assertEqual((vm.eval('OR_ARR:0'),vm.eval('OR_ARR:2')),(0,8))
    def test_base_error_prevents_exponent_and_target_effects(self):
        vm=self.make('POWER OR_ARR:INDEX(),FAIL(),EXP()\nQUIT\n',extra=FUNCS);e=self.run_error(vm,'E_ARITH')
        expected_line=(self.root/'ERB/Oracle.ERB').read_text(encoding='utf-8-sig').splitlines().index('RETURNF 1/OR_B')+1
        self.assertEqual((vm.eval('OR_TRACE'),e.location.line),(4,expected_line))
    def test_exponent_error_preserves_only_prior_source_effects(self):
        vm=self.make('POWER OR_ARR:INDEX(),BASE(),FAIL()\nQUIT\n',extra=FUNCS);self.run_error(vm,'E_ARITH');self.assertEqual(vm.eval('OR_TRACE'),14)
    def test_target_bounds_failure_preserves_both_sources(self):
        vm=self.make('OR_IDX=4\nPOWER OR_ARR:INDEX(),BASE(),EXP()\nQUIT\n',extra=FUNCS);e=self.run_error(vm,'E_INDEX')
        self.assertEqual((vm.eval('OR_TRACE'),e.location.line),(123,3))
        self.assertEqual([vm.eval('OR_ARR:'+str(i)) for i in range(4)],[0]*4)
    def test_power_error_prevents_target_index_evaluation(self):
        vm=self.make('POWER OR_ARR:INDEX(),2,63\nQUIT\n',extra=FUNCS);self.run_error(vm,'E_ARITH');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_wrong_type_is_checked_before_sources(self):
        vm=self.make('POWER OR_STR,BASE(),EXP()\nQUIT\n',extra=FUNCS);self.run_error(vm,'E_TYPE');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_readonly_destination_rejected_without_sources(self):
        vm=self.make('POWER OR_CONST,BASE(),EXP()\nQUIT\n',extra=FUNCS);self.run_error(vm,'E_REFERENCE');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_numeric_expression_cannot_be_destination(self):
        vm=self.make('POWER 1+2,BASE(),EXP()\nQUIT\n',extra=FUNCS);self.run_error(vm,'E_REFERENCE');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_unknown_destination_rejected_before_source_effects(self):
        vm=self.make('POWER UNDECLARED,BASE(),EXP()\nQUIT\n',extra=FUNCS);self.run_error(vm,'E_VARIABLE');self.assertEqual(vm.eval('OR_TRACE'),0)
    def test_extra_expression_not_executed_and_lv1_warning(self):
        vm=self.make('POWER OR_A,2,3,BASE()\nQUIT\n',extra=FUNCS);vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_TRACE')),(8,0));self.assertNotIn('POWER命令:引数が多すぎます',self.output.getvalue())
    def test_extra_constant_is_still_restructured(self):
        vm=self.make('POWER OR_A,2,3,1/0\nQUIT\n',mode='YES');self.assertEqual([x.severity for x in vm.program.argument_diagnostics],[1,2]);self.run_error(vm,'E_ARITH')
    def test_closed_dispatch_rejects_arbitrary_json_handler(self):
        spec=dict(COMMAND_SPECS['POWER']);spec['instruction_handler']='os.system'
        with self.assertRaises(EraError):validate_document({'schema_version':1,'commands':{'POWER':spec}},'commands')
    def test_extra_unknown_method_is_parse_error_before_ignored_execution(self):
        vm=self.make('POWER OR_A,2,3,UNKNOWN_METHOD()\nQUIT\n');self.run_error(vm,'E_FUNCTION');self.assertEqual(vm.eval('OR_A'),0)
    def test_virtual_constant_destination_rejected_before_sources(self):
        vm=self.make('POWER __INT_MIN__,BASE(),EXP()\nQUIT\n',extra=FUNCS);self.run_error(vm,'E_REFERENCE');self.assertEqual(vm.eval('OR_TRACE'),0)

for i,text in enumerate(['','OR_A','OR_A,2','OR_A,,3']):
    def test(self,text=text):self.run_error(self.make('POWER '+text+'\nQUIT\n'),'E_ARGUMENT')
    setattr(PowerInstructionR6,'test_bad_arity_'+str(i),test)
for i,(x,y,expected) in enumerate([(0,0,1),(0,1,0),(1,9223372036854775807,1),(-2,3,-8),(-2,4,16),(2,-1,0),(-2,-3,0),(2,62,4611686018427387904)]):
    def test(self,x=x,y=y,expected=expected):
        vm=self.make(f'POWER OR_A,{x},{y}\nOR_B=POWER({x},{y})\nQUIT\n');vm.run();self.assertEqual((vm.eval('OR_A'),vm.eval('OR_B')),(expected,expected))
    setattr(PowerInstructionR6,'test_source_only_numeric_boundary_'+str(i),test)
for i,(x,y) in enumerate([(0,-1),(2,63),(-2,63),(9223372036854775807,1),(2,1024)]):
    def test(self,x=x,y=y):self.run_error(self.make(f'POWER OR_A,{x},{y}\nQUIT\n'),'E_ARITH')
    setattr(PowerInstructionR6,'test_source_only_overflow_'+str(i),test)


class ConstantRestructureR6(Neutral):
    def test_archived_after_quit_warning_raw_location_and_continuation(self):
        vm=self.make('PRINTL ORACLE|end\nOUTPUTLOG\nQUIT\nOR_A=1/0\n',mode='YES');d=vm.program.argument_diagnostics
        self.assertEqual((d[0].severity,d[0].location.line,d[0].source_text,d[0].reference_message),(2,5,'OR_A=1/0','0による除算が行なわれました'))
        vm.run();self.assertEqual(vm.eval('OR_A'),0);self.assertLess(self.output.getvalue().index('警告Lv2'),self.output.getvalue().index('ORACLE|end'))
    def test_archived_conditional_reference_warns_even_when_false(self):
        vm=self.make('IF OR_A\nCALL UNREACHED\nENDIF\nPRINTL ORACLE|end\nOUTPUTLOG\nQUIT\n',mode='YES',extra='@UNREACHED\nOR_A=1/0\nRETURN\n')
        self.assertEqual(vm.program.argument_diagnostics[0].location.line,9);vm.run();self.assertEqual(vm.eval('OR_A'),0)
    def test_unreferenced_yes_ignore_yes_retains_old_no_warning(self):
        vm=self.make('QUIT\n',mode='YES',extra='@UNREACHED\nOR_A=1/0\nRETURN\n');self.assertEqual(vm.program.argument_diagnostics,[])
        self.assertTrue(any(x['status']=='ignored_uncalled_function' for x in vm.program.argument_coverage));vm.run()
    def test_unreferenced_yes_ignore_no_warns(self):
        vm=self.make('QUIT\n',mode='YES',ignore='NO',extra='@UNREACHED\nOR_A=1/0\nRETURN\n');self.assertEqual(len(vm.program.argument_diagnostics),1);vm.run()
    def test_analysis_mode_overrides_ignore(self):
        self.make('QUIT\n',mode='NO',extra='@UNREACHED\nOR_A=1/0\nRETURN\n');p=Program(self.root,analysis_mode=True);vm=VM(p,GameData(self.root),Console([],io.StringIO(),no_wait=True));self.assertEqual(len(p.argument_diagnostics),1)
    def test_no_mode_no_constant_load_warning(self):
        for ignore in ['YES','NO']:
            vm=self.make('QUIT\nOR_A=1/0\n',ignore=ignore);self.assertEqual(vm.program.argument_diagnostics,[]);vm.run()
    def test_reached_constant_error_retains_prior_state_location(self):
        vm=self.make('OR_A=7\nOR_B=1/0\nQUIT\n',mode='YES');e=self.run_error(vm,'E_ARITH');self.assertEqual((e.location.line,vm.eval('OR_A'),vm.eval('OR_B')),(3,7,0))
    def test_no_mode_reached_error_runtime_only(self):
        vm=self.make('OR_A=7\nOR_B=1/0\nQUIT\n');self.assertEqual(vm.program.argument_diagnostics,[]);self.run_error(vm,'E_ARITH');self.assertEqual(vm.eval('OR_A'),7)
    def test_pure_tree_reduction_and_constant_child_of_runtime_node(self):
        reducer=Reducer();self.assertEqual(reducer.reduce(parse('(2+3)*4')),('lit',20))
        self.assertEqual(reducer.reduce(parse('OR_A+(2*3)')),('binary','+',('var','OR_A',()),('lit',6)))
    def test_short_circuit_children_are_restructured_not_executed(self):
        vm=self.make('QUIT\nOR_A=0&&(1/0)\n',mode='YES');self.assertEqual(len(vm.program.argument_diagnostics),1);vm.run()
    def test_pure_function_adapter_no_vm_evaluation(self):
        with patch.object(VM,'eval',side_effect=AssertionError('static eval')),patch.object(VM,'call_expr',side_effect=AssertionError('static call')):
            vm=self.make('OR_A=POWER(2,3)\nQUIT\n',mode='YES',headers='#DIM OR_A\n')
        self.assertEqual(vm._expression_cache['POWER(2,3)'],('lit',8))
    def test_runtime_rng_user_dynamic_arg_ref_not_evaluated(self):
        src='QUIT\nOR_ARR:INDEX()=BASE()+RAND:100+LOCAL+ARG\n'
        yes=self.make(src,mode='YES',extra=FUNCS);no=self.make(src,extra=FUNCS)
        self.assertEqual(yes.rng.getstate(),no.rng.getstate());self.assertEqual(yes.eval('OR_TRACE'),0)
        self.assertEqual(yes.program.argument_diagnostics,[])
    def test_dynamic_index_reduced_only_literal_children(self):
        node=Reducer().reduce(parse('OR_ARR:INDEX()'))
        self.assertEqual(node,parse('OR_ARR:INDEX()'))
    def test_nested_conditional_call_graph_handles_cycles(self):
        vm=self.make('IF 0\nCALL FIRST\nENDIF\nQUIT\n',mode='YES',extra='@FIRST\nCALL SECOND\nRETURN\n@SECOND\nIF 0\nCALL FIRST\nENDIF\nOR_A=1/0\nRETURN\n');self.assertEqual(len(vm.program.argument_diagnostics),1);vm.run()
    def test_warning_threshold_reference_config_does_not_unmark_error(self):
        vm=self.make('OR_A=1/0\n',mode='YES');vm.program.config['表示する最低警告レベル']='3';self.run_error(vm,'E_ARITH');self.assertNotIn('警告',self.output.getvalue())


class WidthBestfitR6(unittest.TestCase):
    def test_archived_acute_narrow(self):self.assertEqual(convert('Á',False,{}),'A')
    def test_archived_acute_wide(self):self.assertEqual(convert('Á',True,{}),'Ａ')
    def test_vendor_table_accents_not_general_normalization(self):
        self.assertEqual(convert('ÀÂÄÉÈÊËÍÓÚÇÑ',False,{}),'AAAEEEEIOUCN')
        self.assertEqual(convert('áàâäéèêëíóúçñ',False,{}),'aaaaeeeeioucn')
    def test_decomposed_mark_not_silently_composed(self):
        self.assertEqual(convert('A\u0301Á',False,{}),'A?A');self.assertEqual(convert('A\u0301Á',True,{}),'Ａ？Ａ')
    def test_compatibility_characters_preserved(self):
        self.assertEqual(convert('①㍑㎏',False,{}),'①㍑㎏')
    def test_bestfit_is_generic_for_nonaccent_characters(self):
        self.assertEqual(convert('©',False,{}),'c')


class OutputlogCaptureR6(Neutral):
    def evidence(self,vm,error=None):
        e=Path(tempfile.mkdtemp());self.addCleanup(__import__('shutil').rmtree,e)
        __import__('shutil').copytree(self.root,e/'py-run')
        write_json(e/'py-session.json',vm.journal.report('error' if error else 'quit',error));return e
    def test_single_log_exact_final_history(self):
        vm=self.make('PRINTL ORACLE|end\nOUTPUTLOG\nQUIT\n',journal=True);vm.run();r=select_capture(self.evidence(vm));self.assertEqual((r['count'],r['status']),(1,'capture_complete'))
    def test_multiple_logs_select_by_digest_and_generation(self):
        vm=self.make('PRINTL ORACLE|first\nOUTPUTLOG\nPRINTL ORACLE|end\nOUTPUTLOG\nQUIT\n',journal=True);vm.run();r=select_capture(self.evidence(vm));self.assertEqual((r['count'],r['selected_generation'],r['status']),(2,2,'capture_complete'));self.assertFalse(r['files_concatenated'])
    def test_collision_never_overwrites_intermediate_snapshot(self):
        from datetime import datetime
        with patch('pyemuera.outputlog.datetime') as clock:
            clock.now.return_value=datetime(2026,1,1)
            vm=self.make('PRINTL first\nOUTPUTLOG\nPRINTL last\nOUTPUTLOG\nQUIT\n',journal=True);vm.run()
        paths=sorted((self.root/'.pyemuera/logs').glob('*.txt'));self.assertEqual(len(paths),2);self.assertNotEqual(paths[0].read_bytes(),paths[1].read_bytes())
        self.assertEqual(select_capture(self.evidence(vm))['status'],'capture_complete')
    def test_output_after_last_snapshot_is_incomplete(self):
        vm=self.make('PRINTL first\nOUTPUTLOG\nPRINTL final\nQUIT\n',journal=True);vm.run();r=select_capture(self.evidence(vm));self.assertEqual(r['reason'],'no_snapshot_represents_final_history')
    def test_no_outputlog_files_not_marker_shortage(self):
        vm=self.make('PRINTL ORACLE|end\nQUIT\n',journal=True);vm.run();self.assertEqual(select_capture(self.evidence(vm))['reason'],'no_OUTPUTLOG_files')
    def test_error_after_snapshot_retains_prior_capture(self):
        vm=self.make('PRINTL ORACLE|prior\nOUTPUTLOG\nOR_A=1/0\n',journal=True);error=self.run_error(vm,'E_ARITH');r=select_capture(self.evidence(vm,error));self.assertEqual(r['status'],'capture_complete');self.assertEqual(r['error']['code'],'E_ARITH')
    def test_corrupt_log_not_selected(self):
        vm=self.make('OUTPUTLOG\nQUIT\n',journal=True);vm.run();e=self.evidence(vm);p=next((e/'py-run/.pyemuera/logs').glob('*.txt'));p.write_text('different',encoding='utf-8');self.assertEqual(select_capture(e)['reason'],'OUTPUTLOG_content_changed')
    def test_missing_session_is_explicit(self):
        vm=self.make('OUTPUTLOG\nQUIT\n',journal=True);vm.run();e=self.evidence(vm);(e/'py-session.json').unlink();self.assertEqual(select_capture(e)['reason'],'missing_final_session_report')
    def test_utf8_json_under_cp932_locale_remains_lossless(self):
        vm=self.make('PRINTL Áカ\u3099Ａ\u0301\nOUTPUTLOG\nQUIT\n',journal=True);vm.run();e=self.evidence(vm);write_json(e/'check.json',{'value':'Áカ\u3099Ａ\u0301 '});self.assertEqual(json.loads((e/'check.json').read_bytes().decode('utf-8'))['value'],'Áカ\u3099Ａ\u0301 ')
        self.assertEqual(select_capture(e)['status'],'capture_complete')
    def test_duplicate_generation_is_incomplete(self):
        vm=self.make('OUTPUTLOG\nOUTPUTLOG\nQUIT\n',journal=True);vm.run();e=self.evidence(vm);p=e/'py-session.json';d=json.loads(p.read_text());d['logical_output_capture']['records'][1]['generation']=1;p.write_text(json.dumps(d));self.assertEqual(select_capture(e)['reason'],'invalid_generation_order')
    def test_name_order_is_not_generation_order(self):
        vm=self.make('PRINTL first\nOUTPUTLOG\nPRINTL last\nOUTPUTLOG\nQUIT\n',journal=True);vm.run();e=self.evidence(vm);folder=e/'py-run/.pyemuera/logs';p=e/'py-session.json';session=json.loads(p.read_text());records=session['logical_output_capture']['records']
        for rec,new in zip(records,['zzz.txt','aaa.txt']):(folder/rec['file']).rename(folder/new);rec['file']=new
        p.write_text(json.dumps(session));(folder/'outputlog-manifest.json').write_text(json.dumps({'records':records}))
        self.assertEqual(select_capture(e)['selected']['file'],'aaa.txt')
    def test_nonprefix_snapshots_follow_final_digest_after_clearline(self):
        vm=self.make('PRINTL first\nOUTPUTLOG\nCLEARLINE 1\nPRINTL last\nOUTPUTLOG\nQUIT\n',journal=True);vm.run();r=select_capture(self.evidence(vm));self.assertEqual((r['status'],r['selected_generation']),('capture_complete',2))


class ComparatorClassificationR6(Neutral):
    evidence=OutputlogCaptureR6.evidence
    # Synthetic comparator inputs; no binary execution or Windows claim.
    def setUp(self):
        import importlib.util,sys
        kit=Path(__file__).resolve().parent.parent/'verification/oracle_v24/run06'
        sys.path.insert(0,str(kit));self.addCleanup(sys.path.remove,str(kit))
        spec=importlib.util.spec_from_file_location('unit_run06_comparator',kit/'compare_oracle.py')
        self.comparator=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.comparator)
    def comparison_fixture(self,error=False,reference='ORACLE|end\r\n'):
        vm=self.make('PRINTL ORACLE|end\nOUTPUTLOG\nQUIT\n',journal=True);vm.run();e=self.evidence(vm)
        case=e/'unit-case';case.mkdir();exe=e/'reference-run/Emuera1824+v24.exe';exe.parent.mkdir();exe.write_bytes(b'synthetic unit file; NEVER executed')
        defs={'case_id':'synthetic_unittest','run_id':'synthetic/unit','reference_id':'synthetic/unit','source_tree_sha256':'unit','fixture_manifest':[], 'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'pyz_sha256':'unit','source_reference':[],'expected_ids':['end'],'error_probe':error}
        write_json(case/'oracle_definitions.json',defs)
        write_json(e/'reference-meta.json',{**defs,'execution_id':'unit','runtime_executed':False})
        write_json(e/'py-meta.json',{**defs,'execution_id':'unit','exit_code':0})
        write_json(e/'gui-observation.json',{'observer':'unit','warnings_and_errors_reviewed':False,'user_confirmed':False,'execution_id':'unit','error_dialogs_observed':0})
        raw=reference.encode('utf-16');(e/'reference-output.txt').write_bytes(raw);(exe.parent/'emuera.log').write_bytes(raw)
        logs=list((e/'py-run/.pyemuera/logs').glob('*.txt'));(e/'py-logical-output.txt').write_bytes(logs[0].read_bytes());(e/'py-output.txt').write_bytes(b'ORACLE|end\n')
        return case,e
    def test_missing_evidence_file_separate_from_expected_marker(self):
        c,e=self.comparison_fixture();(e/'reference-output.txt').unlink();j=self.comparator.compare(c,e);self.assertEqual((j['status'],j['reason']),('capture_incomplete','evidence_file_missing'))
    def test_present_logs_with_missing_marker_are_not_missing_file(self):
        c,e=self.comparison_fixture(reference='no end\r\n');j=self.comparator.compare(c,e);self.assertEqual(j['status'],'expected_markers_incomplete');self.assertEqual(j['missing_evidence_files'],[])
    def test_error_probe_never_promoted_by_equal_prior_markers(self):
        c,e=self.comparison_fixture(error=True);j=self.comparator.compare(c,e);self.assertTrue(j['marker_observations_equal']);self.assertEqual(j['status'],'error_observation_pending')
    def test_runtime_not_executed_meta_prevents_promotion(self):
        c,e=self.comparison_fixture();j=self.comparator.compare(c,e);self.assertNotEqual(j['status'],'verified_equal');self.assertFalse(j['user_confirmed_gui_observation'])
        # Synthetic metadata only; no reference program is executed in this test.
        p=e/'reference-meta.json';r=json.loads(p.read_text());r['runtime_executed']=True;p.write_text(json.dumps(r))
        p=e/'gui-observation.json';g=json.loads(p.read_text());g.update(warnings_and_errors_reviewed=True,error_dialogs_observed=1);p.write_text(json.dumps(g));self.assertEqual(self.comparator.compare(c,e)['status'],'mismatch_open')
        g.update(error_dialogs_observed=0);g.pop('execution_id');p.write_text(json.dumps(g));self.assertEqual(self.comparator.compare(c,e)['status'],'warning_review_pending')
    def test_executable_identity_change_rejected(self):
        c,e=self.comparison_fixture();p=e/'gui-observation.json';g=json.loads(p.read_text());g['execution_id']='different-unit-run';p.write_text(json.dumps(g))
        with self.assertRaises(ValueError):self.comparator.compare(c,e)
        g['execution_id']='unit';p.write_text(json.dumps(g));(e/'reference-run/Emuera1824+v24.exe').write_bytes(b'changed');
        with self.assertRaises(ValueError):self.comparator.compare(c,e)
