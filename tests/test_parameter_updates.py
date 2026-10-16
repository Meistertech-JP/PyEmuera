"""Public adapter contracts updated for the r25 source-compatible semantics.

Frozen r24 tests remain historical evidence. These direct/declared-dispatch
checks retain input effects, roles, diagnostic positions and partial failures,
while explicitly changing omission, eligibility, notification and clear order.
Small manually assigned dimensions are unit allocations, not native CSV loads.
"""
from contextlib import ExitStack
from unittest.mock import patch

from test_core import Harness
from pyemuera import commands, dispatcher
from pyemuera.errors import EraError


ARRAYS = ('PALAM', 'UP', 'DOWN', 'CUP', 'CDOWN')


class ParameterUpdates(Harness):
    def roster(self, count=3, size=2, source='@MAIN\nRETURN\n'):
        vm = self.make(source, max_steps=10000)
        for name in ARRAYS:
            vm.data.variables[name].dims = (size,)
        for _ in range(count):
            vm.data.add_character(-1, void=True)
        for character in range(count):
            vm.set(f'PALAM:{character}:0', 10 + character)
        for name, value in {'MASTER': 0, 'TARGET': 1, 'ASSI': 2, 'PLAYER': 2,
                            'RESULT': 777}.items():
            vm.set(name, value)
        vm.set('RESULTS', 'unchanged')
        return vm

    def state(self, vm):
        return {name: dict(vm.data.variables[name].values) for name in ARRAYS}

    def test_upcheck_changes_only_target_and_keeps_other_state(self):
        vm = self.roster()
        vm.set('UP:0', 5)
        vm.set('DOWN:0', 2)
        roles = [vm.get(name) for name in ('MASTER', 'TARGET', 'ASSI', 'PLAYER')]
        rng = vm.rng.getstate()
        self.assertTrue(commands.execute_command(vm, 'UPCHECK', ''))
        self.assertEqual([vm.get(f'PALAM:{character}:0') for character in range(3)],
                         [10, 14, 12])
        self.assertEqual((vm.get('UP:0'), vm.get('DOWN:0')), (0, 0))
        self.assertEqual([vm.get(name) for name in ('MASTER', 'TARGET', 'ASSI', 'PLAYER')], roles)
        self.assertEqual((vm.get('RESULT'), vm.get('RESULTS')), (777, 'unchanged'))
        self.assertEqual(vm.rng.getstate(), rng)

    def test_cupcheck_explicit_expression_evaluates_once_and_selects_one_character(self):
        vm = self.roster()
        vm.set('CUP:0:0', 4)
        vm.set('CUP:1:0', 8)
        self.assertTrue(commands.execute_command(vm, 'CUPCHECK', '++B'))
        self.assertEqual((vm.get('B'), vm.get('PALAM:1:0')), (1, 19))
        self.assertEqual((vm.get('PALAM:0:0'), vm.get('CUP:0:0')), (10, 4))
        self.assertEqual(vm.get('CUP:1:0'), 0)

    def test_cupcheck_omitted_visits_only_zero_and_resets_its_local_deltas(self):
        vm = self.roster()
        for character in range(3):
            vm.set(f'CUP:{character}:0', character + 2)
            vm.set(f'CDOWN:{character}:0', 1)
        self.assertTrue(dispatcher.execute(vm, 'CUPCHECK', ''))
        self.assertEqual([vm.get(f'PALAM:{character}:0') for character in range(3)],
                         [11, 11, 12])
        self.assertEqual(vm.data.variables['CUP'].values, {(1, 0): 3, (2, 0): 4})
        self.assertEqual(vm.data.variables['CDOWN'].values, {(1, 0): 1, (2, 0): 1})
        self.assertEqual(vm.get('RESULT'), 777)

    def test_omitted_cupcheck_on_empty_roster_succeeds_without_updates(self):
        vm = self.roster(count=0)
        before = self.state(vm)
        self.assertTrue(commands.execute_command(vm, 'CUPCHECK', ''))
        self.assertEqual(self.state(vm), before)

    def test_invalid_up_clears_globals_and_invalid_cup_preserves_arrays(self):
        for name, argument in [('UPCHECK', ''), ('CUPCHECK', '-1'), ('CUPCHECK', '3')]:
            with self.subTest(name=name, argument=argument):
                vm = self.roster()
                vm.set('TARGET', -1)
                vm.set('UP:0', 9)
                vm.set('DOWN:0', 2)
                before = self.state(vm)
                self.assertTrue(commands.execute_command(vm, name, argument))
                if name == 'UPCHECK':
                    before['UP'] = {}
                    before['DOWN'] = {}
                self.assertEqual(self.state(vm), before)

    def test_extra_arguments_are_not_eagerly_evaluated(self):
        for name in ('UPCHECK', 'CUPCHECK'):
            with self.subTest(name=name):
                vm = self.roster()
                before = self.state(vm)
                rng = vm.rng.getstate()
                self.assertTrue(commands.execute_command(vm, name, '++B,RAND(10)'))
                self.assertEqual(vm.get('B'), 1 if name == 'CUPCHECK' else 0)
                self.assertEqual(vm.rng.getstate(), rng)
                self.assertEqual(self.state(vm), before)

    def test_upcheck_ignores_expression_errors_without_argument_effects(self):
        vm = self.roster()
        before = self.state(vm)
        self.assertTrue(commands.execute_command(vm, 'UPCHECK', '++B,1/0'))
        self.assertEqual(vm.get('B'), 0)
        self.assertEqual(self.state(vm), before)

    def test_cupcheck_type_conversion_failure_precedes_updates(self):
        vm = self.roster()
        before = self.state(vm)
        with self.assertRaises(EraError) as caught:
            commands.execute_command(vm, 'CUPCHECK', '"bad"')
        self.assertEqual(caught.exception.code, 'E_TYPE')
        self.assertEqual(self.state(vm), before)

    def test_shorter_palam_still_clears_complete_delta_arrays(self):
        vm = self.roster(size=2)
        vm.data.variables['UP'].dims = (3,)
        vm.data.variables['DOWN'].dims = (4,)
        vm.set('UP:0', 1)
        vm.set('UP:2', 8)
        vm.set('DOWN:3', 9)
        commands.execute_command(vm, 'UPCHECK', '')
        self.assertEqual(vm.get('PALAM:1:0'), 12)
        self.assertEqual(vm.get('UP:2'), 0)
        self.assertEqual(vm.get('DOWN:3'), 0)

    def test_signed_wrap_has_no_clamp_and_both_nonpositive_deltas_skip(self):
        vm = self.roster(size=4)
        initial = [2**63 - 1, -(2**63), 7, 8]
        deltas = [1, -1, -3, 0]
        for index, value in enumerate(initial):
            vm.set(f'PALAM:1:{index}', value)
            vm.set(f'UP:{index}', deltas[index])
        commands.execute_command(vm, 'UPCHECK', '')
        self.assertEqual([vm.get(f'PALAM:1:{index}') for index in range(4)],
                         [-(2**63), -(2**63), 7, 8])

    def test_zero_delta_reads_skip_palam_then_clear_up_and_down_in_order(self):
        vm = self.roster(size=2)
        trace = []
        with ExitStack() as stack:
            for name in ('PALAM', 'UP', 'DOWN'):
                variable = vm.data.variables[name]
                original_get, original_set = variable.get, variable.set
                def read(key, name=name, original=original_get):
                    trace.append(('get', name, tuple(key)))
                    return original(key)
                def write(key, value, name=name, original=original_set):
                    trace.append(('set', name, tuple(key), value))
                    return original(key, value)
                stack.enter_context(patch.object(variable, 'get', side_effect=read))
                stack.enter_context(patch.object(variable, 'set', side_effect=write))
            commands.execute_command(vm, 'UPCHECK', '')
        self.assertEqual(trace, [
            ('get', 'UP', (0,)), ('get', 'DOWN', (0,)),
            ('get', 'UP', (1,)), ('get', 'DOWN', (1,)),
            ('set', 'UP', (0,), 0), ('set', 'UP', (1,), 0),
            ('set', 'DOWN', (0,), 0), ('set', 'DOWN', (1,), 0),
        ])

    def test_palam_observer_failure_keeps_palam_write_without_clearing_deltas(self):
        vm = self.roster()
        vm.set('UP:0', 5)
        vm.set('DOWN:0', 2)
        def fail(*parts):
            raise EraError('observer sentinel', code='E_OBSERVER')
        vm.data.variables['PALAM'].write_observer = fail
        with self.assertRaises(EraError) as caught:
            commands.execute_command(vm, 'UPCHECK', '')
        self.assertEqual(caught.exception.code, 'E_OBSERVER')
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('UP:0'), vm.get('DOWN:0')),
                         (14, 5, 2))

    def test_up_observer_failure_keeps_its_reset_and_leaves_down_intact(self):
        vm = self.roster()
        vm.set('UP:0', 5)
        vm.set('DOWN:0', 2)
        def fail(*parts):
            raise EraError('observer sentinel', code='E_OBSERVER')
        vm.data.variables['UP'].write_observer = fail
        with self.assertRaises(EraError):
            commands.execute_command(vm, 'UPCHECK', '')
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('UP:0'), vm.get('DOWN:0')),
                         (14, 0, 2))

    def test_down_observer_failure_keeps_both_resets(self):
        vm = self.roster()
        vm.set('UP:0', 5)
        vm.set('DOWN:0', 2)
        def fail(*parts):
            raise EraError('observer sentinel', code='E_OBSERVER')
        vm.data.variables['DOWN'].write_observer = fail
        with self.assertRaises(EraError):
            commands.execute_command(vm, 'UPCHECK', '')
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('UP:0'), vm.get('DOWN:0')),
                         (14, 0, 0))

    def test_later_read_failure_preserves_earlier_parameter_and_deltas(self):
        vm = self.roster()
        for index in range(2):
            vm.set(f'UP:{index}', 5)
            vm.set(f'DOWN:{index}', 2)
        down = vm.data.variables['DOWN']
        original = down.get
        def read(key):
            if key == (1,):
                raise EraError('read sentinel', code='E_INDEX')
            return original(key)
        with patch.object(down, 'get', side_effect=read):
            with self.assertRaises(EraError):
                commands.execute_command(vm, 'UPCHECK', '')
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('UP:0'), vm.get('DOWN:0')),
                         (14, 5, 2))
        self.assertEqual((vm.get('PALAM:1:1'), vm.get('UP:1'), vm.get('DOWN:1')),
                         (0, 5, 2))

    def test_omitted_cupcheck_does_not_snapshot_or_visit_later_characters(self):
        vm = self.roster(count=2, size=1)
        vm.set('CUP:0:0', 5)
        vm.set('CUP:1:0', 6)
        def shrink(variable, key, old, new):
            vm.data.character_count = 1
        vm.data.variables['PALAM'].write_observer = shrink
        self.assertTrue(commands.execute_command(vm, 'CUPCHECK', ''))
        self.assertEqual(vm.get('PALAM:0:0'), 15)
        self.assertEqual(vm.get('CUP:0:0'), 0)
        self.assertEqual(vm.data.variables['PALAM'].values[(1, 0)], 11)
        self.assertEqual(vm.data.variables['CUP'].values[(1, 0)], 6)

    def test_runtime_array_error_retains_instruction_location(self):
        for name, argument in [('UPCHECK', ''), ('CUPCHECK', '0')]:
            with self.subTest(name=name):
                vm = self.roster(count=1, size=1,
                                 source='@MAIN\n' + name + ' ' + argument + '\nRETURN\n')
                vm.set('TARGET', 0)
                vm.set('UP:0', 1)
                vm.set('CUP:0:0', 1)
                vm.data.variables['PALAMNAME'].dims = (0,)
                with self.assertRaises(EraError) as caught:
                    vm.call('MAIN')
                self.assertEqual(caught.exception.code, 'E_INDEX')
                self.assertTrue(caught.exception.location.path.endswith('Main.ERB'))
                self.assertEqual(caught.exception.location.line, 2)

    def test_skip_print_does_not_suppress_parameter_updates(self):
        vm = self.roster()
        vm.console.skip_print = True
        vm.set('UP:0', 5)
        self.assertTrue(dispatcher.execute(vm, 'UPCHECK', ''))
        self.assertEqual(vm.get('PALAM:1:0'), 16)
        self.assertEqual(self.output.getvalue(), '')
