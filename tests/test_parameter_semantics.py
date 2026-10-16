"""Complete native source contracts; controlled dimensions are unit allocations.

No native executable is run here. Positive dimensions below 100 are test-only;
the 300/100/200 case separately exercises a native-loadable size combination.
"""
from unittest.mock import patch
from test_core import Harness
from pyemuera import parameter_updates
from pyemuera.errors import EraError


class ParameterSemantics(Harness):
    def roster(self, size=2, count=3, source='@MAIN\nRETURN\n'):
        vm = self.make(source, max_steps=10000)
        for name in ('PALAM', 'UP', 'DOWN', 'CUP', 'CDOWN'):
            vm.data.variables[name].dims = (size,)
        for _ in range(count):
            vm.data.add_character(-1, void=True)
        for character in range(count):
            vm.set(f'PALAM:{character}:0', 10 + character)
        vm.set('TARGET', 1)
        vm.set('RESULT', 777)
        for index in range(size):
            vm.data.variables['PALAMNAME'].set((index,), f'P{index}', internal=True)
        return vm

    def run_update(self, vm, name='UPCHECK', argument=''):
        return parameter_updates.execute(vm, name, argument)

    def arrays(self, vm):
        return {name: dict(vm.data.variables[name].values)
                for name in ('PALAM', 'UP', 'DOWN', 'CUP', 'CDOWN')}

    def test_target_update_with_notification_and_no_roles_result_rng_changes(self):
        vm = self.roster()
        vm.set('UP:0', 5)
        vm.set('DOWN:0', 2)
        roles = [vm.get(name) for name in ('MASTER', 'TARGET', 'ASSI', 'PLAYER')]
        rng = vm.rng.getstate()
        self.assertTrue(self.run_update(vm))
        self.assertEqual([vm.get(f'PALAM:{c}:0') for c in range(3)], [10, 14, 12])
        self.assertEqual(self.output.getvalue(), 'P0 11+5-2=14\n')
        self.assertEqual([vm.get(name) for name in ('MASTER', 'TARGET', 'ASSI', 'PLAYER')], roles)
        self.assertEqual(vm.get('RESULT'), 777)
        self.assertEqual(vm.rng.getstate(), rng)

    def test_up_ignores_malformed_raw_argument_and_effects(self):
        vm = self.roster()
        rng = vm.rng.getstate()
        with patch.object(vm, 'eval', side_effect=AssertionError('argument evaluation')):
            self.run_update(vm, argument='++B,RAND(10),(')
        self.assertEqual(vm.get('B'), 0)
        self.assertEqual(vm.rng.getstate(), rng)

    def test_cup_first_term_executes_once_and_extra_effects_do_not(self):
        vm = self.roster()
        vm.set('CUP:1:0', 5)
        rng = vm.rng.getstate()
        with patch.object(vm, 'eval', wraps=vm.eval) as evaluate:
            self.run_update(vm, 'CUPCHECK', '++B,RAND(10),++C')
        self.assertEqual(evaluate.call_count, 1)
        self.assertEqual(evaluate.call_args.args, ('++B',))
        self.assertEqual((vm.get('B'), vm.get('C'), vm.get('PALAM:1:0')), (1, 0, 16))
        self.assertEqual(vm.rng.getstate(), rng)

    def test_cup_omission_selects_only_zero(self):
        vm = self.roster()
        for c in range(3):
            vm.set(f'CUP:{c}:0', c + 2)
        self.run_update(vm, 'CUPCHECK')
        self.assertEqual([vm.get(f'PALAM:{c}:0') for c in range(3)], [12, 11, 12])
        self.assertEqual([vm.get(f'CUP:{c}:0') for c in range(3)], [0, 3, 4])

    def test_cup_null_first_term_is_rejected_before_effects(self):
        vm = self.roster()
        before = self.arrays(vm)
        with self.assertRaises(EraError) as caught:
            self.run_update(vm, 'CUPCHECK', ',++B')
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertEqual(self.arrays(vm), before)
        self.assertEqual(vm.get('B'), 0)

    def test_up_invalid_int64_targets_clear_globals_without_narrowing(self):
        for target in (-1, 3, 2**32, 2**63 - 1, -(2**63)):
            with self.subTest(target=target):
                vm = self.roster(size=3)
                vm.set('TARGET', target)
                vm.set('UP:2', 9)
                vm.set('DOWN:2', 7)
                vm.set('CUP:0:0', 8)
                palam = dict(vm.data.variables['PALAM'].values)
                self.run_update(vm)
                self.assertEqual(vm.data.variables['PALAM'].values, palam)
                self.assertEqual(vm.data.variables['UP'].values, {})
                self.assertEqual(vm.data.variables['DOWN'].values, {})
                self.assertEqual(vm.get('CUP:0:0'), 8)
                self.assertEqual(self.output.getvalue(), '')

    def test_cup_invalid_int64_targets_preserve_every_array(self):
        for target in (-1, 3, 2**32, 2**63 - 1, -(2**63)):
            with self.subTest(target=target):
                vm = self.roster()
                vm.set('CUP:0:0', 8)
                before = self.arrays(vm)
                vm.set('B', target)
                self.run_update(vm, 'CUPCHECK', 'B')
                self.assertEqual(self.arrays(vm), before)
                self.assertEqual(self.output.getvalue(), '')

    def test_invalid_cup_keeps_first_expression_side_effect(self):
        vm = self.roster()
        vm.set('B', -2)
        before = self.arrays(vm)
        self.run_update(vm, 'CUPCHECK', '++B,++C')
        self.assertEqual((vm.get('B'), vm.get('C')), (-1, 0))
        self.assertEqual(self.arrays(vm), before)

    def test_empty_roster_up_clears_but_cup_does_not(self):
        vm = self.roster(count=0)
        vm.set('UP:0', 8)
        vm.set('DOWN:0', 3)
        before = self.arrays(vm)
        self.run_update(vm, 'CUPCHECK')
        self.assertEqual(self.arrays(vm), before)
        self.run_update(vm)
        self.assertEqual(vm.data.variables['UP'].values, {})
        self.assertEqual(vm.data.variables['DOWN'].values, {})

    def test_both_nonpositive_skip_parameter_and_name_accesses(self):
        for up, down in [(0, 0), (-1, 0), (0, -1), (-2, -4)]:
            with self.subTest(up=up, down=down):
                vm = self.roster(size=1)
                vm.set('UP:0', up)
                vm.set('DOWN:0', down)
                with patch.object(vm.data.variables['PALAM'], 'get', side_effect=AssertionError('PALAM read')):
                    with patch.object(vm.data.variables['PALAMNAME'], 'get', side_effect=AssertionError('name read')):
                        self.run_update(vm)
                self.assertEqual(vm.get('PALAM:1:0'), 11)
                self.assertEqual(self.output.getvalue(), '')

    def test_negative_up_enters_arithmetic_but_not_notification(self):
        vm = self.roster(size=1)
        vm.set('UP:0', -20)
        vm.set('DOWN:0', 2)
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:0'), -11)
        self.assertEqual(self.output.getvalue(), 'P0 11-2=-11\n')

    def test_negative_down_enters_arithmetic_but_not_notification(self):
        vm = self.roster(size=1)
        vm.set('UP:0', 3)
        vm.set('DOWN:0', -4)
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:0'), 18)
        self.assertEqual(self.output.getvalue(), 'P0 11+3=18\n')

    def test_positive_down_may_make_negative_palam(self):
        vm = self.roster(size=1)
        vm.set('DOWN:0', 20)
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:0'), -9)
        self.assertEqual(self.output.getvalue(), 'P0 11-20=-9\n')

    def test_signed_addition_wraps_without_zero_clamp(self):
        vm = self.roster(size=1)
        vm.set('PALAM:1:0', 2**63 - 1)
        vm.set('UP:0', 1)
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:0'), -(2**63))

    def test_subtraction_wraps_before_addition(self):
        vm = self.roster(size=1)
        vm.set('PALAM:1:0', 0)
        vm.set('UP:0', 2**63 - 1)
        vm.set('DOWN:0', -(2**63))
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:0'), -1)
        self.assertEqual(self.output.getvalue(), 'P0 0+9223372036854775807=-1\n')

    def test_negative_palam_downflow_wraps(self):
        vm = self.roster(size=1)
        vm.set('PALAM:1:0', -(2**63))
        vm.set('DOWN:0', 1)
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:0'), 2**63 - 1)

    def test_whole_global_clears_include_cells_beyond_palam(self):
        vm = self.roster(size=2)
        vm.data.variables['UP'].dims = (3,)
        vm.data.variables['DOWN'].dims = (4,)
        vm.set('UP:0', 1)
        vm.set('UP:2', 8)
        vm.set('DOWN:3', 9)
        self.run_update(vm)
        self.assertEqual(vm.data.variables['UP'].values, {})
        self.assertEqual(vm.data.variables['DOWN'].values, {})

    def test_whole_local_clears_preserve_other_character(self):
        vm = self.roster(size=2)
        vm.data.variables['CUP'].dims = (3,)
        vm.data.variables['CDOWN'].dims = (4,)
        vm.set('CUP:1:0', 1)
        vm.set('CUP:1:2', 8)
        vm.set('CDOWN:1:3', 9)
        vm.set('CUP:0:2', 4)
        self.run_update(vm, 'CUPCHECK', '1')
        self.assertEqual(vm.data.variables['CUP'].values, {(0, 2): 4})
        self.assertEqual(vm.data.variables['CDOWN'].values, {})

    def test_native_loadable_unequal_sizes_reexpand_and_fail_after_commits(self):
        vm = self.roster(size=1)
        for name, size in [('PALAM', 300), ('UP', 100), ('DOWN', 200)]:
            vm.data.variables[name].dims = (size,)
        vm.set('UP:0', 1)
        vm.set('UP:99', 2)
        vm.set('DOWN:199', 3)
        with self.assertRaises(EraError) as caught:
            self.run_update(vm)
        self.assertEqual(caught.exception.code, 'E_INDEX')
        self.assertIn('UP(100,)', caught.exception.message)
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('PALAM:1:99')), (12, 2))
        self.assertEqual((vm.get('UP:0'), vm.get('UP:99'), vm.get('DOWN:199')), (1, 2, 3))
        self.assertEqual(self.output.getvalue(), 'P0 11+1=12\n 0+2=2\n')
        self.assertEqual([vm.data.variables[n].dims for n in ('PALAM', 'UP', 'DOWN')], [(300,), (100,), (200,)])

    def test_smaller_down_check_shrinks_loop_and_still_clears_full_up(self):
        vm = self.roster(size=4)
        vm.data.variables['UP'].dims = (3,)
        vm.data.variables['DOWN'].dims = (2,)
        vm.set('UP:0', 1)
        vm.set('UP:2', 5)
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:2'), 0)
        self.assertEqual(vm.data.variables['UP'].values, {})

    def test_equal_down_length_does_not_reexpand_smaller_up(self):
        vm = self.roster(size=3)
        vm.data.variables['UP'].dims = (1,)
        vm.set('UP:0', 1)
        vm.set('DOWN:2', 5)
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:2'), 0)
        self.assertEqual(vm.data.variables['DOWN'].values, {})

    def test_zero_length_palam_loop_still_clears_global(self):
        vm = self.roster(size=1)
        vm.data.variables['PALAM'].dims = (0,)
        vm.set('UP:0', 5)
        self.run_update(vm)
        self.assertEqual(vm.data.variables['UP'].values, {})

    def test_skip_print_updates_without_names_or_console_calls(self):
        vm = self.roster(size=1)
        vm.set('UP:0', 5)
        vm.console.skip_print = True
        with patch.object(vm.data.variables['PALAMNAME'], 'get', side_effect=AssertionError('name read')):
            with patch.object(vm.console, 'write', side_effect=AssertionError('console write')):
                self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:0'), 16)
        self.assertEqual(vm.data.variables['UP'].values, {})

    def test_current_style_existing_prefix_and_override_are_preserved(self):
        vm = self.roster(size=1)
        vm.set('UP:0', 1)
        vm.ui.update(color=0x102030, bgcolor=0x405060, style=3, font='test-font')
        before = dict(vm.ui)
        style = (0x010203, 0x040506, 1)
        vm.console.style_override = style
        vm.console.write('prefix:')
        self.run_update(vm)
        self.assertEqual(vm.ui, before)
        self.assertIs(vm.console.style_override, style)
        self.assertEqual(self.output.getvalue(), 'prefix:P0 11+1=12\n')
        elements, alignment = vm.console.markup_lines[-1]
        self.assertEqual(alignment, 'LEFT')
        self.assertEqual((elements[0][1].color, elements[0][1].bits), (style[0], style[2]))

    def test_empty_name_keeps_native_space_prefix(self):
        vm = self.roster(size=1)
        vm.data.variables['PALAMNAME'].set((0,), '', internal=True)
        vm.set('UP:0', 1)
        self.run_update(vm)
        self.assertEqual(self.output.getvalue(), ' 11+1=12\n')

    def test_commits_prints_newlines_then_up_whole_then_down_whole(self):
        vm = self.roster(size=2)
        vm.set('UP:0', 5)
        vm.set('DOWN:0', 2)
        events = []
        for name in ('PALAM', 'UP', 'DOWN'):
            vm.data.variables[name].write_observer = lambda variable, key, old, value, name=name: events.append((name, key, value))
        original = vm.console.write
        def write(text, newline=False, **options):
            events.append(('write', text, newline))
            return original(text, newline, **options)
        with patch.object(vm.console, 'write', side_effect=write):
            self.run_update(vm)
        self.assertEqual(events, [('PALAM', (1, 0), 14), ('write', 'P0 11+5-2=14', False),
                                  ('write', '', True), ('UP', (0,), 0), ('UP', (1,), 0),
                                  ('DOWN', (0,), 0), ('DOWN', (1,), 0)])

    def test_parameter_notice_finishes_before_next_parameter_commit(self):
        vm = self.roster(size=2)
        vm.set('UP:0', 1)
        vm.set('DOWN:1', 2)
        events = []
        vm.data.variables['PALAM'].write_observer = lambda *parts: events.append('PALAM')
        original = vm.console.write
        def write(text, newline=False, **options):
            events.append('NewLine' if newline else 'Print')
            return original(text, newline, **options)
        with patch.object(vm.console, 'write', side_effect=write):
            self.run_update(vm)
        self.assertEqual(events, ['PALAM', 'Print', 'NewLine', 'PALAM', 'Print', 'NewLine'])
        self.assertEqual(self.output.getvalue(), 'P0 11+1=12\nP1 0-2=-2\n')

    def test_name_failure_preserves_earlier_commit_without_clearing(self):
        vm = self.roster(size=2)
        vm.data.variables['PALAMNAME'].dims = (1,)
        vm.set('UP:0', 1)
        vm.set('UP:1', 2)
        with self.assertRaises(EraError):
            self.run_update(vm)
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('PALAM:1:1')), (12, 0))
        self.assertEqual((vm.get('UP:0'), vm.get('UP:1')), (1, 2))
        self.assertEqual(self.output.getvalue(), 'P0 11+1=12\n')

    def test_skip_print_avoids_missing_name_failure(self):
        vm = self.roster(size=2)
        vm.data.variables['PALAMNAME'].dims = (1,)
        vm.set('UP:1', 2)
        vm.console.skip_print = True
        self.run_update(vm)
        self.assertEqual(vm.get('PALAM:1:1'), 2)

    def test_palam_observer_failure_keeps_commit_and_deltas_without_print(self):
        vm = self.roster(size=1)
        vm.set('UP:0', 5)
        def fail(*parts):
            raise EraError('observer sentinel', code='E_OBSERVER')
        vm.data.variables['PALAM'].write_observer = fail
        with self.assertRaises(EraError):
            self.run_update(vm)
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('UP:0')), (16, 5))
        self.assertEqual(self.output.getvalue(), '')

    def test_print_failure_keeps_commit_all_deltas_and_no_later_update(self):
        vm = self.roster(size=2)
        vm.set('UP:0', 5)
        with patch.object(vm.console, 'write', side_effect=EraError('print failure', code='E_CONSOLE')):
            with self.assertRaises(EraError):
                self.run_update(vm)
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('PALAM:1:1'), vm.get('UP:0')), (16, 0, 5))

    def test_newline_failure_preserves_current_print_row_and_deltas(self):
        vm = self.roster(size=1)
        vm.set('UP:0', 5)
        original = vm.console.write
        def write(text, newline=False, **options):
            if newline:
                raise EraError('newline failure', code='E_CONSOLE')
            return original(text, newline, **options)
        with patch.object(vm.console, 'write', side_effect=write):
            with self.assertRaises(EraError):
                self.run_update(vm)
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('UP:0')), (16, 5))
        self.assertEqual(vm.console.current, 'P0 11+5=16')
        self.assertEqual(list(vm.console.lines), [])

    def test_later_read_failure_leaves_first_notification_and_all_deltas(self):
        vm = self.roster(size=2)
        vm.set('UP:0', 5)
        vm.set('UP:1', 7)
        down = vm.data.variables['DOWN']
        original = down.get
        def read(key):
            if key == (1,):
                raise EraError('read sentinel', code='E_INDEX')
            return original(key)
        with patch.object(down, 'get', side_effect=read):
            with self.assertRaises(EraError):
                self.run_update(vm)
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('PALAM:1:1')), (16, 0))
        self.assertEqual((vm.get('UP:0'), vm.get('UP:1')), (5, 7))
        self.assertEqual(self.output.getvalue(), 'P0 11+5=16\n')

    def test_up_clear_failure_leaves_down_and_up_suffix(self):
        vm = self.roster(size=2)
        vm.set('UP:0', 5)
        vm.set('UP:1', 7)
        vm.set('DOWN:0', 2)
        def fail(*parts):
            raise EraError('clear sentinel', code='E_OBSERVER')
        vm.data.variables['UP'].write_observer = fail
        with self.assertRaises(EraError):
            self.run_update(vm)
        self.assertEqual((vm.get('PALAM:1:0'), vm.get('PALAM:1:1')), (14, 7))
        self.assertEqual((vm.get('UP:0'), vm.get('UP:1'), vm.get('DOWN:0')), (0, 7, 2))

    def test_down_clear_failure_occurs_after_all_up_clears(self):
        vm = self.roster(size=2)
        vm.set('UP:0', 5)
        vm.set('UP:1', 7)
        vm.set('DOWN:0', 2)
        vm.set('DOWN:1', 3)
        def fail(*parts):
            raise EraError('clear sentinel', code='E_OBSERVER')
        vm.data.variables['DOWN'].write_observer = fail
        with self.assertRaises(EraError):
            self.run_update(vm)
        self.assertEqual(vm.data.variables['UP'].values, {})
        self.assertEqual((vm.get('DOWN:0'), vm.get('DOWN:1')), (0, 3))

    def test_first_runtime_argument_failure_keeps_its_effects_without_updates(self):
        vm = self.roster(source='@MAIN\nRETURN\n@FAULT\n#FUNCTION\nRETURNF 1/A\n')
        before = self.arrays(vm)
        with self.assertRaises(EraError) as caught:
            self.run_update(vm, 'CUPCHECK', '++B+FAULT(),++C')
        self.assertEqual(caught.exception.code, 'E_ARITH')
        self.assertEqual((vm.get('B'), vm.get('C')), (1, 0))
        self.assertEqual(self.arrays(vm), before)

    def disabled_fixture(self, sizes, count=2):
        vm = self.make(csv={'VariableSize.csv': sizes}, max_steps=10000)
        for _ in range(count):
            vm.data.add_character(-1, void=True)
        vm.set('TARGET', 0)
        return vm

    def test_csv_forbidden_palam_has_zero_internal_length_and_clears_up_down(self):
        vm = self.disabled_fixture('PALAM,-1\n')
        vm.set('UP:99', 7)
        vm.set('DOWN:99', 3)
        self.assertTrue(vm.data.variables['PALAM'].forbidden)
        with patch.object(vm.data.variables['PALAM'], 'get', side_effect=AssertionError('forbidden PALAM read')):
            self.run_update(vm)
        self.assertEqual(vm.data.variables['UP'].values, {})
        self.assertEqual(vm.data.variables['DOWN'].values, {})
        self.assertEqual(self.output.getvalue(), '')

    def test_csv_forbidden_up_zero_loop_ignores_inaccessible_stale_storage(self):
        vm = self.disabled_fixture('UP,-1\n')
        up = vm.data.variables['UP']
        up.values[(0,)] = 99  # Impossible native storage, retained API sentinel.
        vm.set('DOWN:99', 7)
        with patch.object(up, 'get', side_effect=AssertionError('zero UP read')):
            with patch.object(up, 'set', side_effect=AssertionError('zero UP clear')):
                self.run_update(vm)
        self.assertEqual(up.values, {(0,): 99})
        self.assertEqual(vm.data.variables['DOWN'].values, {})

    def test_csv_forbidden_up_reexpanded_loop_fails_at_zero_before_any_commit(self):
        vm = self.disabled_fixture('PALAM,300\nUP,-1\nDOWN,200\n')
        vm.set('DOWN:199', 7)
        before = self.arrays(vm)
        with self.assertRaises(EraError) as caught:
            self.run_update(vm)
        self.assertEqual(caught.exception.code, 'E_INDEX')
        self.assertIn('UP(0,): array index outside (0,)', caught.exception.message)
        self.assertEqual(self.arrays(vm), before)
        self.assertEqual(self.output.getvalue(), '')

    def test_csv_forbidden_cup_reexpanded_loop_fails_without_any_global_clear(self):
        vm = self.disabled_fixture('PALAM,300\nCUP,-1\nCDOWN,200\n')
        vm.set('CDOWN:0:199', 7)
        vm.set('UP:0', 3)
        before = self.arrays(vm)
        with self.assertRaises(EraError) as caught:
            self.run_update(vm, 'CUPCHECK', '0')
        self.assertEqual(caught.exception.code, 'E_INDEX')
        self.assertIn('CUP(0, 0): array index outside (None, 0)', caught.exception.message)
        self.assertEqual(self.arrays(vm), before)

    def test_csv_forbidden_cdown_shrinks_to_zero_and_clears_only_selected_cup(self):
        vm = self.disabled_fixture('PALAM,300\nCUP,100\nCDOWN,-1\n')
        vm.set('CUP:0:99', 7)
        vm.set('CUP:1:99', 9)
        cdown = vm.data.variables['CDOWN']
        with patch.object(cdown, 'get', side_effect=AssertionError('zero CDOWN read')):
            with patch.object(cdown, 'set', side_effect=AssertionError('zero CDOWN clear')):
                self.run_update(vm, 'CUPCHECK', '0')
        self.assertEqual(vm.data.variables['CUP'].values, {(1, 99): 9})
        self.assertEqual(self.output.getvalue(), '')

    def test_csv_forbidden_palam_cup_clears_only_selected_local_slice(self):
        vm = self.disabled_fixture('PALAM,-1\n')
        vm.set('CUP:0:99', 7)
        vm.set('CDOWN:0:99', 3)
        vm.set('CUP:1:99', 9)
        self.run_update(vm, 'CUPCHECK', '0')
        self.assertEqual(vm.data.variables['CUP'].values, {(1, 99): 9})
        self.assertEqual(vm.data.variables['CDOWN'].values, {})
        self.assertEqual(self.output.getvalue(), '')
