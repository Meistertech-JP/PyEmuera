import io
import json
from test_core import Harness
from pyemuera.console import Console
from pyemuera.runtime import VM
from pyemuera.data import GameData
from pyemuera.errors import EraError
from pyemuera.journal import RunJournal
from pyemuera.diagnostics_c2 import VMProfiler,VariableTrace
from pyemuera.commands import execute_command

class Plans(Harness):
    def test_assignment_plan_rhs_precedes_dynamic_index(self):
        v=self.script('B=0\nREPEAT 3\nA:(B++)=B\nREND')
        # v24 SET_Instruction (Instraction.Child.cs:492-496): RHS first.
        # The original left-first assertion is retained under verification/historical_tests_r1.
        self.assertEqual([v.get('A:'+str(i)) for i in range(3)],[0,1,2]);self.assertEqual(v.get('B'),3)
    def test_rhs_remains_dynamic(self):
        v=self.script('A=0\nREPEAT 10\nA=A+1\nREND');self.assertEqual(v.get('A'),10)
    def test_short_circuit_remains_lazy(self):
        v=self.script('A=0\nB=0\nREPEAT 5\nA=0&&(++B)\nREND');self.assertEqual(v.get('B'),0)
    def test_string_form_remains_dynamic(self):
        v=self.script('REPEAT 3\nA=COUNT\nSTR = value={A}\nREND');self.assertEqual(v.get('STR'),'value=2')
    def test_cached_assignment_uses_current_private_scope(self):
        v=self.make('@MAIN\nCALL F\nCALL G\nRETURN\n@F\n#DIM DYNAMIC TEMP\nTEMP=10\nA=TEMP\nRETURN\n@G\n#DIM DYNAMIC TEMP\nTEMP=20\nB=TEMP\nRETURN')
        v.call('MAIN');self.assertEqual((v.get('A'),v.get('B')),(10,20))
    def test_multi_assignment_preserves_rhs_error_order(self):
        v=self.make('@MAIN\nRETURN\n@SIDE\n#FUNCTION\nB+=1\nRETURNF 5')
        with self.assertRaises(EraError):v._assignment('A=SIDE(),1+')
        self.assertEqual(v.get('B'),1);self.assertEqual(v.get('A'),0)
    def test_unreached_invalid_expression_not_forced(self):
        v=self.make('@MAIN\nIF 0\nA=1+\nENDIF\nRETURN');v.call('MAIN');self.assertEqual(v.get('A'),0)
    def test_cache_invalidation_for_embedding_macro_change(self):
        v=self.make();v.program.macros['TEST']='4';self.assertEqual(v.eval('TEST'),4)
        v.program.macros['TEST']='8';v.invalidate_execution_cache();self.assertEqual(v.eval('TEST'),8)
    def test_overflow_and_negative_shift(self):
        v=self.script('A=__INT_MAX__\nA+=1\nB=1<<-1');self.assertEqual(v.get('A'),-(1<<63));self.assertEqual(v.get('B'),-(1<<63))
    def test_jumps_and_loop_end_state(self):
        v=self.script('A=0\n$L\nA+=1\nSIF A<4\nGOTO L\nFOR B,3,-1,-1\nC+=B\nNEXT');self.assertEqual((v.get('A'),v.get('B'),v.get('C')),(4,-1,6))

class Diagnostics(Harness):
    def test_profile_does_not_change_fixed_input_result(self):
        v=self.make('@MAIN\nA=0\nFOR B,0,8\nA+=B\nNEXT\nPRINTFORML {A}\nRETURN')
        prof=VMProfiler(v).install()
        try:v.call('MAIN')
        finally:prof.stop()
        result=prof.report();self.assertEqual(v.get('A'),28);self.assertEqual(self.output.getvalue(),'28\n')
        self.assertTrue(result['back_edges']);self.assertTrue(result['opcodes']);self.assertTrue(result['categories'])
    def test_profile_nested_call_time_not_double_counted_as_self(self):
        v=self.make('@MAIN\nCALL F\nRETURN\n@F\nA+=1\nRETURN')
        p=VMProfiler(v).install();v.call('MAIN');p.stop();rows={a['name']:a for a in p.report()['functions']}
        self.assertEqual(rows['F']['count'],1);self.assertGreaterEqual(rows['MAIN']['inclusive_seconds'],rows['MAIN']['self_seconds'])
    def test_profile_report_after_error(self):
        v=self.make('@MAIN\nA=1/0');p=VMProfiler(v).install()
        with self.assertRaises(EraError):v.call('MAIN')
        p.stop();self.assertEqual(p.report()['vm_steps'],1)
    def test_watch_records_equal_writes_and_bulk_changes(self):
        v=self.make();t=VariableTrace(v,['TARGET']).install();v.set('TARGET',1);v.set('TARGET',1)
        v.data.variables['TARGET'].values[(0,)]=2;t.scan();t.stop();events=t.report()['events']
        writes=[x for x in events if x['event']=='write'];self.assertEqual(len(writes),2)
        self.assertTrue(any(x['event']=='bulk_change_detected' and x['new']==2 for x in events))
    def test_trace_limited_without_stopping_game(self):
        v=self.make('@MAIN\nREPEAT 10\nTARGET=COUNT\nREND\nRETURN');t=VariableTrace(v,['TARGET'],limit=3).install();v.call('MAIN');t.stop()
        self.assertEqual(len(t.events),3);self.assertGreater(t.dropped,0);self.assertEqual(v.get('TARGET'),9)
    def test_normal_journal_keeps_no_values(self):
        b=self.make('@MAIN\nSTR=private_unique_string\nPRINTSL STR\nRETURN')
        j=RunJournal(trace_limit=2);v=VM(b.program,GameData(b.root),Console(output=io.StringIO(),no_wait=True,journal=j),journal=j);v.call('MAIN')
        report=j.report('returned');self.assertNotIn('private_unique_string',json.dumps(report));self.assertEqual(len(report['recent_execution']),2)
        self.assertEqual(report['source_instructions_visited'],3)
    def test_journal_on_off_state_and_output_equality(self):
        base=self.make('@MAIN\nA=0\nREPEAT 20\nA+=COUNT\nPRINTFORM {A}\nREND\nRETURN');outputs=[];states=[]
        for enabled in (False,True):
            out=io.StringIO();j=RunJournal() if enabled else None;v=VM(base.program,GameData(base.root),Console(output=out,no_wait=True,journal=j),seed=1,journal=j);v.call('MAIN');outputs.append(out.getvalue());states.append(v.get('A'))
        self.assertEqual(outputs[0],outputs[1]);self.assertEqual(states,[190,190])
    def test_trace_unknown_variable_rejected(self):
        with self.assertRaises(EraError):VariableTrace(self.make(),['NOT_REAL'])

class Buffering(Harness):
    def test_raw_batch_flush_preserves_bytes(self):
        out=io.StringIO();c=Console(output=out);c.enable_batching();c.write('a');c.write('b');c.flush();self.assertEqual(out.getvalue(),'ab');self.assertEqual(c.current,'ab')
    def test_input_flushes_pending_text(self):
        out=io.StringIO();c=Console(['2'],out);c.enable_batching();c.write('choose');self.assertEqual(c.input(),2);self.assertEqual(out.getvalue(),'choose\n')
    def test_terminal_batch_preserves_styles_and_projection(self):
        outputs=[];histories=[]
        for enabled in (False,True):
            out=io.StringIO();c=Console(output=out,layout='terminal');c.enable_color('always')
            if enabled:c.enable_batching()
            c.ui={'color':0xc0c0c0,'bgcolor':0,'style':0,'font':'mono','alignment':'LEFT'}
            c.write('┌─');c.ui['color']=0xff0000;c.write('┐',True);c.write('　│x│');c.flush();c.reset_style();outputs.append(out.getvalue());histories.append([list(c.lines),c.current])
        self.assertEqual(outputs[0],outputs[1]);self.assertEqual(histories[0],histories[1])
    def test_no_wait_also_flushes(self):
        out=io.StringIO();c=Console(output=out,no_wait=True);c.enable_batching();c.write('pending');c.wait();self.assertEqual(out.getvalue(),'pending')

class CharacterRoles(Harness):
    def setup_chars(self):
        return self.script('ADDVOIDCHARA\nADDVOIDCHARA\nADDVOIDCHARA\nNO:0=20\nNO:1=10\nNO:2=30\nTARGET=2\nMASTER=0\nASSI=1\nPLAYER=2')
    def test_delete_does_not_remap_roles(self):
        v=self.setup_chars();execute_command(v,'DELCHARA','1');self.assertEqual([v.get(x) for x in ('TARGET','MASTER','ASSI','PLAYER')],[2,0,1,2]);self.assertEqual(v.get('NO:1'),30)
    def test_delete_duplicate_is_error(self):
        v=self.setup_chars()
        with self.assertRaises(EraError):execute_command(v,'DELCHARA','1,1')
        self.assertEqual(v.data.character_count,3)
    def test_swap_leaves_numeric_roles(self):
        v=self.setup_chars();execute_command(v,'SWAPCHARA','0,2');self.assertEqual(v.get('TARGET'),2);self.assertEqual(v.get('NO:0'),30);self.assertEqual(v.get('MASTER'),0)
    def test_sort_remaps_three_roles_not_player(self):
        v=self.setup_chars();v.set('MASTER',-1);execute_command(v,'SORTCHARA','NO');self.assertEqual(v.get('ASSI'),0);self.assertEqual(v.get('PLAYER'),2);self.assertEqual(v.get('MASTER'),-1)
    def test_pickup_filters_negative_and_duplicate_indices(self):
        v=self.setup_chars();execute_command(v,'PICKUPCHARA','-1,2,2,1');self.assertEqual(v.data.character_count,2);self.assertEqual([v.get('NO:'+str(i)) for i in range(2)],[30,10]);self.assertEqual(v.get('PLAYER'),2)
    def test_pickup_retains_source_swap_bookkeeping(self):
        v=self.setup_chars();execute_command(v,'PICKUPCHARA','2,0');self.assertEqual([v.get('NO:'+str(i)) for i in range(2)],[30,20]);self.assertEqual((v.get('TARGET'),v.get('MASTER'),v.get('ASSI')),(0,-1,-1))
    def test_delall_leaves_roles(self):
        v=self.setup_chars();execute_command(v,'DELALLCHARA','');self.assertEqual(v.data.character_count,0);self.assertEqual(v.get('TARGET'),2)
    def test_copy_and_addcopy_leave_roles(self):
        v=self.setup_chars();execute_command(v,'COPYCHARA','0,1');execute_command(v,'ADDCOPYCHARA','0');self.assertEqual(v.get('TARGET'),2);self.assertEqual(v.get('PLAYER'),2);self.assertEqual(v.get('NO:3'),20)
