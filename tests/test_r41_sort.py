"""Captured Framework/native sort regressions and additional source contracts.

New sizes/distributions are synthetic source-informed regressions, not new
Windows observations. See verification/r41/sort/comparison.json.
"""
import json
from pathlib import Path
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.sort1824 import compare_int64, framework_list_order, _intro_sort


MIN = -(1 << 63)
MAX = (1 << 63) - 1
FIXTURES = Path(__file__).with_name('fixtures') / 'r41_sort_cases.json'


class FrameworkSort(Harness):
    def arrays(self, keys, *, extra=1, string=False, rows=2):
        headers = f'#{"DIMS" if string else "DIM"} KEYS,{len(keys)+extra}\n#DIM ROWS,{len(keys)+extra},{rows}'
        vm = self.make(headers=headers)
        for index, value in enumerate(keys):
            vm.set(f'KEYS:{index}', value)
            for column in range(rows):
                vm.set(f'ROWS:{index}:{column}', 10000 * column + index + 1)
        for index in range(len(keys), len(keys)+extra):
            for column in range(rows):
                vm.set(f'ROWS:{index}:{column}', -10000 - 100 * index - column)
        return vm

    def test_unchecked_subtraction_not_total_order(self):
        self.assertEqual(compare_int64(MIN, MAX), 1)
        self.assertEqual(compare_int64(MAX, MIN), -1)
        self.assertEqual(compare_int64(MIN, 1), 1)
        self.assertEqual(compare_int64(1, MAX), -1)
        self.assertEqual(compare_int64(MAX, MIN), -1)
        self.assertEqual(compare_int64(MIN, MIN), 0)
        # Difference exactly 2**63 compares negative in BOTH directions.
        self.assertEqual(compare_int64(1, MIN + 1), -1)
        self.assertEqual(compare_int64(MIN + 1, 1), -1)

    def test_captured_equal24_native_row_permutation(self):
        vm = self.arrays([1]*24)
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 1)
        self.assertEqual([vm.get(f'ROWS:{i}:0') for i in range(24)],
                         [1]+list(range(22,1,-1))+[23,24])
        self.assertEqual(vm.get('ROWS:24:0'), -12400)

    def test_captured_native_extreme_valid(self):
        vm = self.arrays([MAX,MIN,1,-1])
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 1)
        self.assertEqual([vm.get(f'KEYS:{i}') for i in range(4)], [1,MAX,MIN,-1])
        self.assertEqual([vm.get(f'ROWS:{i}:0') for i in range(4)], [3,1,2,4])

    def test_captured_v48_probe_all_four_cases(self):
        cases = [([MAX,MIN,1,-1],[2,0,1,3]),
                 ([MIN,MAX,-1,1],[1,0,2,3]),
                 ([1,MAX,-1,MIN],[2,0,1,3]),
                 ([1]*24,[0]+list(range(21,0,-1))+[22,23])]
        for keys, expected in cases:
            with self.subTest(keys=keys):
                self.assertEqual(framework_list_order(keys), expected)

    def test_equal_string_keys_use_same_sort_algorithm(self):
        vm = self.arrays(['same']*24, extra=0, string=True)
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 1)
        self.assertEqual([vm.get(f'ROWS:{i}:0') for i in range(24)],
                         [1]+list(range(22,1,-1))+[23,24])

    def test_empty_string_anywhere_returns_zero_without_writes(self):
        vm = self.arrays(['b','a',''], extra=0, string=True)
        before = {name:dict(vm.lookup(name).values) for name in ('KEYS','ROWS')}
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 0)
        self.assertEqual({name:vm.lookup(name).values for name in before}, before)

    def test_numeric_zero_stops_prefix_and_preserves_tail(self):
        vm = self.arrays([3,1,0,2,-1])
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 1)
        self.assertEqual([vm.get(f'KEYS:{i}') for i in range(6)], [1,3,0,2,-1,0])
        self.assertEqual([vm.get(f'ROWS:{i}:0') for i in range(5)], [2,1,3,4,5])

    def test_zero_first_does_not_sort_any_row(self):
        vm = self.arrays([0,3,2,1])
        before = {name:dict(vm.lookup(name).values) for name in ('KEYS','ROWS')}
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 1)
        self.assertEqual({name:vm.lookup(name).values for name in before}, before)

    def test_full_integer_array_without_sentinel(self):
        vm = self.arrays([3,-1,2], extra=0)
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 1)
        self.assertEqual([vm.get(f'KEYS:{i}') for i in range(3)], [-1,2,3])

    def test_later_short_array_preserves_prior_changes_and_later_untouched(self):
        vm = self.make(headers='#DIM KEYS,4\n#DIM ROWS,4\n#DIM SHORT,1\n#DIM AFTER,4')
        for name in ('KEYS','ROWS','AFTER'):
            for index,value in enumerate((3,1,2,0)):
                vm.set(f'{name}:{index}', value)
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS,SHORT,AFTER)'), 0)
        self.assertEqual([vm.get(f'KEYS:{i}') for i in range(4)], [1,2,3,0])
        self.assertEqual([vm.get(f'ROWS:{i}') for i in range(4)], [1,2,3,0])
        self.assertEqual([vm.get(f'AFTER:{i}') for i in range(4)], [3,1,2,0])

    def test_aliased_array_is_cloned_when_argument_reached(self):
        vm = self.arrays([3,1,2])
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS,ROWS)'), 1)
        self.assertEqual([vm.get(f'ROWS:{i}:0') for i in range(3)], [3,1,2])

    def test_dynamic_subscripts_are_not_read(self):
        vm = self.arrays([3,1,2])
        vm.set('A', 9999)
        before_rng = vm.rng.getstate()
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS:(++A),ROWS:RAND(100000):(++A))'), 1)
        self.assertEqual(vm.get('A'), 9999)
        self.assertEqual(vm.rng.getstate(), before_rng)

    def test_ignored_subscript_still_checks_constant_axis(self):
        vm = self.arrays([3,1,2])
        before = dict(vm.lookup('KEYS').values)
        with self.assertRaises(EraError) as caught:
            vm.eval('ARRAYMSORT(KEYS:9999,ROWS)')
        self.assertEqual(caught.exception.code, 'E_INDEX')
        self.assertEqual(vm.lookup('KEYS').values, before)

    def test_validation_failure_does_not_consume_subscript_effects(self):
        vm = self.arrays([3,1,2])
        with self.assertRaises(EraError):
            vm.eval('ARRAYMSORT(KEYS:(++A),1/0)')
        self.assertEqual(vm.get('A'), 0)

    def test_three_dimensional_destination_source_typo_rejects(self):
        vm = self.make(headers='#DIM KEYS,4\n#DIM CUBE,4,2,2')
        with self.assertRaises(EraError) as caught:
            vm.eval('ARRAYMSORT(KEYS,CUBE)')
        self.assertEqual(caught.exception.diagnostic_message or caught.exception.message,
                         'ARRAYMSORT関数:2番目の引数が配列変数ではありません')

    def test_bad_comparer_exception_precedes_all_game_array_writes(self):
        case = next(c for c in json.loads(FIXTURES.read_text())['cases'] if c['case_id']=='inconsistent31')
        vm = self.arrays(case['keys'])
        vm.set('RESULT', 917)
        vm.set('RESULTS', 'retained')
        before = {name:dict(vm.lookup(name).values) for name in ('KEYS','ROWS')}
        with self.assertRaises(EraError) as caught:
            vm.eval('ARRAYMSORT(KEYS,ROWS)')
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertEqual({name:vm.lookup(name).values for name in before}, before)
        self.assertEqual((vm.get('RESULT'),vm.get('RESULTS')), (917,'retained'))

    def test_heap_fallback_retains_numeric_order_and_items(self):
        keys = [9,-4,1,8,2,2,-3,5,7,4,6,11,10,1,12,-2,3,13,14,15,16,17,18,19]
        items = [(value,index) for index,value in enumerate(keys)]
        _intro_sort(items, lambda left,right: compare_int64(left[0],right[0]), 0, len(items)-1, 0)
        self.assertEqual([value for value,index in items], sorted(keys))
        self.assertEqual(sorted(index for value,index in items), list(range(len(keys))))

    def test_arraysort_extremes_uses_compareto_not_wrapped_difference(self):
        from pyemuera.array_commands import execute
        from pyemuera.registry import COMMAND_SPECS
        vm = self.arrays([MAX,MIN,1,-1], extra=0)
        execute(vm, dict(COMMAND_SPECS['ARRAYSORT'],name='ARRAYSORT'), 'KEYS,FORWARD,0,4')
        self.assertEqual([vm.get(f'KEYS:{i}') for i in range(4)], [MIN,-1,1,MAX])


def _case_regression(case):
    def run(self):
        keys = case['keys']
        expected = case['expected_order']
        self.assertEqual(framework_list_order(keys), expected)
        vm = self.arrays(keys)
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'), 1)
        self.assertEqual([vm.get(f'KEYS:{i}') for i in range(len(keys))], [keys[i] for i in expected])
        for column in range(2):
            self.assertEqual([vm.get(f'ROWS:{i}:{column}') for i in range(len(keys))],
                             [10000*column+i+1 for i in expected])
        self.assertEqual(vm.get(f'ROWS:{len(keys)}:1'), -10000-100*len(keys)-1)
    return run


for _case in json.loads(FIXTURES.read_text())['cases']:
    if 'expected_order' in _case:
        setattr(FrameworkSort, 'test_source_fixture_'+_case['case_id'], _case_regression(_case))
