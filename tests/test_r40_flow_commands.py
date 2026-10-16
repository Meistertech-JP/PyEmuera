"""r40 native source contracts; these are not new Windows observations."""
import datetime
import types
from collections import deque
from unittest.mock import patch
from test_core import Harness
from pyemuera.errors import EraError, FlowSignal
from pyemuera.flow import train_command
from pyemuera import builtins, commands


class R40FlowCommands(Harness):
    def test_begin_title_callee_returns_to_system_title(self):
        vm = self.make('@SYSTEM_TITLE\nA=1\nRESULT=77\nCALL PROBE\nB=RESULT\nA+=10\nQUIT\n@PROBE\nBEGIN TITLE\nA=999', max_steps=40)
        vm.run()
        self.assertEqual((vm.get('A'), vm.get('B'), vm.exit_reason), (11, 0, 'quit'))
        self.assertEqual(vm.frames, [])

    def test_begin_nested_calls_continue_until_outer_return(self):
        vm = self.make('@SYSTEM_TITLE\nCALL FIRSTCALL\nA=A*10+4\nRETURN\n@FIRSTCALL\nCALL SECOND\nA=A*10+3\nRETURN\n@SECOND\nA=1\nBEGIN SHOP\nA=999\n@SHOW_SHOP\nA=A*10+5\nQUIT', max_steps=80)
        vm.data.config['オートセーブを行なう']='NO'
        vm.run()
        self.assertEqual(vm.get('A'), 1345)

    def test_begin_eventshop_finishes_all_event_handlers_before_transition(self):
        vm = self.make('@SYSTEM_TITLE\nBEGIN SHOP\n@EVENTSHOP\nA=1\nBEGIN TRAIN\nA=999\n@EVENTSHOP\nA=A*10+2\nRETURN\n@SHOW_SHOP\nTHROW should not run\n@EVENTTRAIN\nA=A*10+3\nQUIT', max_steps=60)
        vm.data.config['オートセーブを行なう']='NO'
        vm.run()
        self.assertEqual(vm.get('A'), 123)

    def test_begin_eventshop_runs_custom_autosave_before_transition(self):
        vm = self.make('@SYSTEM_TITLE\nBEGIN SHOP\n@EVENTSHOP\nA=1\nBEGIN TRAIN\n@SYSTEM_AUTOSAVE\nA=A*10+2\nRETURN\n@EVENTTRAIN\nA=A*10+3\nQUIT', max_steps=60)
        vm.run()
        self.assertEqual(vm.get('A'), 123)

    def test_begin_unknown_keyword_error_retains_source(self):
        vm = self.make('@SYSTEM_TITLE\nCALL HELPER\nQUIT\n@HELPER\nBEGIN 1/0')
        with self.assertRaises(EraError) as caught: vm.run()
        self.assertEqual(caught.exception.location.line, 5)
        self.assertIn('BEGINのキーワード"1/0"は未定義です', caught.exception.message)

    def test_begin_prohibited_show_shop_retains_source(self):
        vm = self.make('@SYSTEM_TITLE\nBEGIN SHOP\n@SHOW_SHOP\nBEGIN TRAIN')
        vm.data.config['オートセーブを行なう']='NO'
        with self.assertRaises(EraError) as caught: vm.run()
        self.assertEqual(caught.exception.location.line, 4)
        self.assertIn('@SHOW_SHOP中でBEGIN命令', caught.exception.message)

    def test_begin_restart_keeps_pending_request(self):
        vm = self.make('@SYSTEM_TITLE\nA++\nIF A==1\nCALL HELPER\nRESTART\nENDIF\nQUIT\n@HELPER\nBEGIN TITLE', max_steps=50)
        vm.run()
        self.assertEqual(vm.get('A'), 2)

    def test_begin_eventturnend_continues_later_handlers(self):
        vm = self.make('@SYSTEM_TITLE\nBEGIN TURNEND\n@EVENTTURNEND\n#PRI\nA=1\nBEGIN SHOP\n@EVENTTURNEND\n#LATER\nA=A*10+2\nRETURN\n@SHOW_SHOP\nA=A*10+3\nQUIT', max_steps=60)
        vm.data.config['オートセーブを行なう']='NO'
        vm.run()
        self.assertEqual(vm.get('A'),123)

    def test_begin_resets_logical_style_before_caller_continues(self):
        vm = self.make('@MAIN\nCALL HELPER\nA=GETSTYLE()\nQUIT\n@HELPER\nFONTBOLD\nBEGIN TITLE')
        vm.run('MAIN')
        self.assertEqual(vm.get('A'),0)
        self.assertEqual(vm.ui['alignment'],'LEFT')

    def test_begin_returnf_method_caller_is_preserved(self):
        vm = self.make('@SYSTEM_TITLE\nA=METHOD()\nQUIT\n@METHOD\n#FUNCTION\nCALL HELPER\nRETURNF 9\n@HELPER\nBEGIN TITLE')
        # BEGIN is a non-method-safe instruction: loader rejects entering it
        # through a method when method-call policy checks apply.
        with self.assertRaises(EraError): vm.run()

    def test_calltrain_zero_normal_continues(self):
        vm = self.script('CALLTRAIN 0\nA=7')
        self.assertEqual(vm.get('A'), 7)
        self.assertEqual(list(vm.train_queue), [])

    def test_calltrain_replacement_preserves_consumption_index(self):
        vm = self.make()
        vm.train_queue = deque([9]);vm.train_queue_index = 1
        vm.set('SELECTCOM:1', 4);vm.set('SELECTCOM:2', 7)
        train_command(vm, 'CALLTRAIN', '2')
        self.assertEqual((list(vm.train_queue),vm.train_queue_index,vm.train_queue_total), ([7],1,2))

    def test_calltrain_upper_failure_has_new_empty_active_queue(self):
        vm=self.make();vm.train_queue=deque([9]);vm.train_queue_index=3
        with self.assertRaises(EraError):train_command(vm,'CALLTRAIN','1000')
        self.assertEqual(list(vm.train_queue),[])
        self.assertEqual(vm.train_queue_index,3)

    def test_calltrain_negative_failure_preserves_active_queue(self):
        vm=self.make();vm.train_queue=deque([9]);vm.train_queue_index=3
        with self.assertRaises(EraError):train_command(vm,'CALLTRAIN','-1')
        self.assertEqual(list(vm.train_queue),[9])
        self.assertEqual(vm.train_queue_index,3)

    def test_calltrain_zero_train_phase_has_no_completion_callback(self):
        vm=self.make('@SYSTEM_TITLE\nBEGIN TRAIN\n@EVENTTRAIN\nCALLTRAIN 0\nRETURN\n@SHOW_STATUS\nRETURN\n@SHOW_USERCOM\nRETURN\n@CALLTRAINEND\nA=99\nQUIT',max_steps=40)
        with self.assertRaises(EraError) as caught:vm.run()
        self.assertEqual(caught.exception.code,'E_LIMIT')
        self.assertEqual(vm.get('A'),0)
        self.assertEqual(list(vm.train_queue),[])

    def test_dotrain_constant_and_type_build_errors_precede_phase(self):
        vm=self.make();vm.train_queue=deque([9]);vm.train_queue_index=3
        for expression,code in [('1/0','E_ARITH'), ('"x"','E_TYPE')]:
            with self.assertRaises(EraError) as caught:train_command(vm,'DOTRAIN',expression)
            self.assertEqual(caught.exception.code,code)
            self.assertEqual((list(vm.train_queue),vm.train_queue_index),([9],3))

    def test_dotrain_wrong_phase_precedes_side_effect_and_queue_clear(self):
        vm=self.make();vm.train_queue=deque([9]);vm.train_queue_index=3
        with self.assertRaises(EraError) as caught:train_command(vm,'DOTRAIN','1/(A++)')
        self.assertEqual(caught.exception.code,'E_FLOW')
        self.assertEqual(vm.get('A'),0)
        self.assertEqual((list(vm.train_queue),vm.train_queue_index),([9],3))

    def test_dotrain_valid_phase_clears_before_expression_failure(self):
        vm=self.make();vm.train_context=True;vm.train_phase='SHOW_STATUS'
        vm.train_queue=deque([9]);vm.train_queue_index=3
        with self.assertRaises(EraError) as caught:train_command(vm,'DOTRAIN','1/(A++)')
        self.assertEqual(caught.exception.code,'E_ARITH')
        self.assertEqual(vm.get('A'),1)
        self.assertIsNone(vm.train_queue);self.assertEqual(vm.train_queue_index,0)

    def test_await_missing_zero_and_upper_bound(self):
        from pyemuera.runtime_effects import await_delay
        vm=self.make();vm.console.no_wait=False
        with patch('time.sleep') as sleep:
            for arg in ('','0','10000'): await_delay(vm,{'name':'AWAIT'},arg)
        sleep.assert_called_once_with(10)
        for arg in ('-1','10001'):
            with self.assertRaises(EraError):await_delay(vm,{'name':'AWAIT'},arg)

    def test_await_refreshes_even_when_no_wait(self):
        from pyemuera.runtime_effects import await_delay
        vm=self.make()
        with patch.object(vm.console.output,'flush') as flush,patch('time.sleep') as sleep:
            await_delay(vm,{'name':'AWAIT'},'')
        flush.assert_called_once();sleep.assert_not_called()

    def test_gettime_component_boundary_and_write_order(self):
        vm=self.make();events=[]
        samples=iter([datetime.datetime(2025,12,31,23,59,59,999000)] + [datetime.datetime(2026,1,1)]*6 + [datetime.datetime(2026,1,1,0,0,1)])
        clock=types.SimpleNamespace(datetime=types.SimpleNamespace(now=lambda:events.append('now') or next(samples)))
        original=vm.set
        def write(name,value):events.append(name);original(name,value)
        with patch.object(commands,'datetime',clock),patch.object(vm,'set',write):commands.execute_command(vm,'GETTIME','')
        self.assertEqual(events,['now']*7+['RESULT','now','RESULTS'])
        self.assertEqual(vm.get('RESULT'),20250101000000000)
        self.assertEqual(vm.get('RESULTS'),'2026/01/01 00:00:01')

    def test_gettime_result_write_failure_prevents_eighth_sample(self):
        vm=self.make();events=[];instant=datetime.datetime(2026,1,2)
        clock=types.SimpleNamespace(datetime=types.SimpleNamespace(now=lambda:events.append('now') or instant))
        with patch.object(commands,'datetime',clock),patch.object(vm,'set',side_effect=EraError('blocked')):
            with self.assertRaises(EraError):commands.execute_command(vm,'GETTIME','')
        self.assertEqual(len(events),7)

    def test_times_strict_double_setting_and_negative_truncation(self):
        from pyemuera.decimal_instruction import execute
        vm=self.make()
        vm.set('A',100);execute(vm,{'name':'TIMES'},'A, 0.29');self.assertEqual(vm.get('A'),29)
        vm.data.config['TIMESの計算をeramakerにあわせる']='YES'
        vm.set('A',100);execute(vm,{'name':'TIMES'},'A, 0.29');self.assertEqual(vm.get('A'),28)
        vm.set('A',-3);execute(vm,{'name':'TIMES'},'A, 0.5');self.assertEqual(vm.get('A'),-1)

    def test_times_overflow_and_invalid_multiplier(self):
        from pyemuera.decimal_instruction import execute
        vm=self.make();vm.set('A',(1<<63)-1)
        execute(vm,{'name':'TIMES'},'A, 2');self.assertEqual(vm.get('A'),-(1<<63))
        vm.set('A',7);execute(vm,{'name':'TIMES'},'A, nonnumeric');self.assertEqual(vm.get('A'),0)
        vm.set('A',7)
        with self.assertRaises(EraError):execute(vm,{'name':'TIMES'},'A, 1e30')
        self.assertEqual(vm.get('A'),7)

    def test_times_destination_index_read_and_write_are_separate(self):
        vm=self.script('A:0=3\nA:1=9\nB=0\nTIMES A:(B++), 2')
        self.assertEqual((vm.get('B'),vm.get('A:0'),vm.get('A:1')),(2,3,6))

    def test_assert_release_does_not_evaluate(self):
        vm=self.script('ASSERT A++ / 0\nB=7')
        self.assertEqual((vm.get('A'),vm.get('B')),(0,7))
