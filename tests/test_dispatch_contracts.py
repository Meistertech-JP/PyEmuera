"""Observable contracts at the refactored expression/save/check boundaries."""
from types import SimpleNamespace
from unittest.mock import patch
from test_core import Harness
from pyemuera import builtins, commands, dispatcher, save_commands
from pyemuera.errors import EraError, FlowSignal
from pyemuera.reference_functions import function


class DispatchContracts(Harness):
    def test_reference_resolves_before_later_argument_side_effects(self):
        vm = self.script('VALUES=10,20,30,40\nB=0', headers='#DIM VALUES,4')
        # v24 reads start/end before fixing the descriptor's dynamic index.
        self.assertEqual(vm.eval('SUMARRAY(VALUES:(++B),++B,++B)'), 20)
        self.assertEqual(vm.get('B'), 3)

    def test_range_error_preserves_evaluated_side_effects(self):
        vm = self.script('B=0', headers='#DIM VALUES,4')
        with self.assertRaises(EraError) as caught:
            vm.eval('SUMARRAY(VALUES,++B,++B+10)')
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_INDEX', 'SUMARRAY: invalid range 1:12'))
        self.assertEqual(vm.get('B'), 2)

    def test_reference_failure_blocks_later_rng_consumption(self):
        vm = self.make(headers='#DIM VALUES,4')
        with patch.object(vm.rng, 'randrange') as draw:
            with self.assertRaises(EraError):
                vm.eval('MATCH(VALUES:99,RAND(100))')
            draw.assert_not_called()

    def test_evaluation_failure_is_outside_value_exception_translation(self):
        vm = self.make()
        failure = ValueError('evaluation sentinel')
        with patch('pyemuera.builtins.evaluate', side_effect=failure):
            with self.assertRaises(ValueError) as caught:
                builtins.call(vm, 'RAND', [('lit', 10)])
        self.assertIs(caught.exception, failure)

    def test_character_descriptor_and_empty_ranges_keep_distinct_errors(self):
        vm = self.make()
        with self.assertRaises(EraError) as caught:
            vm.eval('SUMCARRAY(CFLAG:0:0)')
        self.assertEqual(caught.exception.code, 'E_CHARACTER')
        self.assertEqual(vm.eval('SUMARRAY(A,0,0)'), 0)
        self.assertEqual(vm.eval('STRJOIN(A,"/",0,0)'), '')
        with self.assertRaises(EraError) as caught:
            vm.eval('MAXARRAY(A,0,0)')
        self.assertEqual(caught.exception.message, 'Empty array range')

    def test_matching_materializes_all_reads_before_selecting_first_hit(self):
        reads = []
        variable = SimpleNamespace(character=False, string=False, dims=(3,),
                                   get=lambda key: reads.append(key) or 7)
        reference = SimpleNamespace(variable=variable, key=(0,), size=lambda: 3)
        vm = SimpleNamespace(data=SimpleNamespace(character_count=0))
        self.assertEqual(function(vm, 'FINDELEMENT', [reference, 7]), 0)
        self.assertEqual(reads, [(0,), (1,), (2,)])

    def save_vm(self, values, *, loaded=False, failure=None):
        events = []
        def args(text):
            events.append(('evaluate', text))
            return values
        def store(operation, *args):
            events.append((operation, *args))
            if failure is not None:
                raise failure
            return loaded
        vm = SimpleNamespace(
            args=args, set=lambda *args: events.append(('set', *args)),
            console=SimpleNamespace(skip_print=False,
                                    warning=lambda *args: events.append(('warning', *args))),
            saves=SimpleNamespace(write=lambda *args: store('write', *args),
                                  load=lambda *args: store('load', *args)),
        )
        return vm, events

    def test_save_evaluates_arguments_before_count_check_without_store_write(self):
        vm, events = self.save_vm([1, 'description', 3])
        with self.assertRaises(EraError) as caught:
            save_commands.execute(vm, {'name': 'SAVEDATA'}, 'source')
        self.assertEqual(caught.exception.message, 'SAVEDATA: expected 1..2 arguments, got 3')
        self.assertEqual(events, [('evaluate', 'source')])

    def test_save_store_failure_does_not_commit_result(self):
        failure = EraError('store failure', code='E_SAVE')
        vm, events = self.save_vm([2, 'description'], failure=failure)
        with self.assertRaises(EraError) as caught:
            save_commands.execute(vm, {'name': 'SAVEDATA'}, 'source')
        self.assertIs(caught.exception, failure)
        self.assertEqual(events, [('evaluate', 'source'), ('write', 2, 'description')])

    def test_successful_slot_load_transfers_without_result_overwrite(self):
        vm, events = self.save_vm([2], loaded=True)
        with self.assertRaises(FlowSignal) as caught:
            commands.execute_command(vm, 'LOADDATA', 'source')
        self.assertEqual(caught.exception.state, 'LOADDATAEND')
        self.assertEqual(events, [('evaluate', 'source'), ('load', 2)])

    def test_failed_global_load_warns_but_slot_load_propagates(self):
        failure = EraError('bad store', code='E_SAVE')
        vm, events = self.save_vm([], failure=failure)
        save_commands.execute(vm, {'name': 'LOADGLOBAL'}, '')
        self.assertEqual(events, [('evaluate', ''), ('load', 'global'),
                                  ('warning', 'global-load', str(failure)), ('set', 'RESULT', 0)])
        vm, events = self.save_vm([2], failure=failure)
        with self.assertRaises(EraError) as caught:
            save_commands.execute(vm, {'name': 'LOADDATA'}, '2')
        self.assertIs(caught.exception, failure)
        self.assertEqual(events, [('evaluate', '2'), ('load', 2)])

    def test_declared_save_dispatch_and_direct_entrypoint_have_same_effects(self):
        vm = self.make()
        dispatcher.execute(vm, 'SAVEDATA', '0,"neutral"')
        vm.set('A', 99)
        with self.assertRaises(FlowSignal):
            commands.execute_command(vm, 'LOADDATA', '0')
        self.assertEqual(vm.get('A'), 0)

    def test_historical_argument_module_preserves_callable_identity(self):
        from pyemuera import command_arguments, command_arguments_r13
        self.assertIs(command_arguments.check, command_arguments_r13.check)
        self.assertIs(command_arguments.lazy, command_arguments_r13.lazy)

    def test_historical_save_adapter_retains_non_save_fallback(self):
        vm = self.make()
        vm.set('A', 99)
        self.assertTrue(save_commands.execute(vm, {'name': 'RESETDATA'}, ''))
        self.assertEqual(vm.get('A'), 0)
