"""VM ARRAYSORT regression: received native rows and bounded local contracts.

The six final orders are parsed from the original received UTF-16LE OUTPUTLOG.
Other assertions protect existing VM behavior or exercise fault injection;
they do not claim fresh native hidden-state or Linux observations.
"""
from collections import Counter
from contextlib import contextmanager, ExitStack
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

from test_core import Harness, CHARA
from pyemuera import collation1824
from pyemuera.collation_portable import PortableNLSBackend
from pyemuera.dispatcher import execute
from pyemuera.errors import EraError, InternalError


FIXTURE_PATH = Path(__file__).parent / 'fixtures/r50/arraysort-native-six.json'
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
NATIVE_LOG_SHA256 = '4e63e49110f2a3a0e1e941cd24dbe68358f3070bdd59661698455e5a2c1ab4f6'
PROBE_SHA256 = '3b06164ae9563d41d526d5af5088c4f1323b35fe8ead7f710fb2c328d9d450e9'
CASE_IDS = tuple('RESULT_' + group + '_' + order
                 for group in ('A', 'C', 'K') for order in ('FORWARD', 'BACK'))


def utf16(value):
    return value.encode('utf-16-le', 'surrogatepass').hex()


@contextmanager
def backend_mode(mode):
    """Force portable ja-JP without pretending the host is Linux.

    _culture is pinned as in the received audit driver because a portable
    backend has no Windows user_default_culture transport.
    """
    with ExitStack() as stack:
        if mode == 'portable':
            backend = PortableNLSBackend()
            stack.enter_context(patch.object(collation1824, '_backend', return_value=backend))
            stack.enter_context(patch.object(
                collation1824, '_culture', side_effect=lambda backend, culture: culture or 'ja-JP'))
        else:
            backend = collation1824._backend()
        yield backend


def snapshot(vm):
    return {
        'variables': {name: dict(var.values) for name, var in vm.data.variables.items()},
        'items': dict(vm.lookup('ITEMS').values),
        'result': dict(vm.lookup('RESULT').values),
        'results': dict(vm.lookup('RESULTS').values),
        'rng': copy.deepcopy(vm.rng.getstate()),
    }


class NativeFixtureR50(unittest.TestCase):
    def test_full_original_bytes_and_source_pins(self):
        raw = bytes.fromhex(FIXTURE['native_log_bytes_hex'])
        probe = bytes.fromhex(FIXTURE['probe_erb_bytes_hex'])
        self.assertEqual(len(raw), 628)
        self.assertEqual(len(probe), 2053)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), NATIVE_LOG_SHA256)
        self.assertEqual(hashlib.sha256(probe).hexdigest(), PROBE_SHA256)
        self.assertTrue(raw.startswith(b'\xff\xfe'))
        self.assertTrue(probe.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(raw[2:].decode('utf-16-le'), FIXTURE['native_log_decoded_value'])
        self.assertEqual(FIXTURE['source_pins']['native_log']['sha256'], NATIVE_LOG_SHA256)
        self.assertEqual(FIXTURE['source_pins']['probe_erb']['sha256'], PROBE_SHA256)
        self.assertEqual(FIXTURE['source_pins']['native_exe']['sha256'],
                         '14cf28c137c6b76396c4d02fcb23ba6a31132301ce1fe0fcbab8c9f1c29d8964')
        self.assertEqual(FIXTURE['native_environment'], {
            'os': 'Windows 10', 'build': 19045, 'framework': '.NET Framework 4.8.1',
            'framework_release': 533509, 'culture': 'ja-JP',
            'source': 'received audit and task attachment',
        })

    def test_each_expected_value_is_from_raw_native_line_and_input_from_probe(self):
        native = bytes.fromhex(FIXTURE['native_log_bytes_hex'])[2:].decode('utf-16-le')
        probe = bytes.fromhex(FIXTURE['probe_erb_bytes_hex']).decode('utf-8-sig')
        native_rows = {line.split('|')[0]: line for line in native.splitlines()
                       if line.startswith('RESULT_')}
        self.assertEqual(tuple(row['case_id'] for row in FIXTURE['cases']), CASE_IDS)
        self.assertEqual(set(native_rows), set(CASE_IDS))
        for row in FIXTURE['cases']:
            with self.subTest(case=row['case_id']):
                raw_line = native_rows[row['case_id']]
                self.assertEqual(row['native_output_line'], raw_line)
                self.assertEqual(row['native_output_line_utf16le_hex'], utf16(raw_line))
                self.assertEqual(row['expected_values'], raw_line.split('|')[1:])
                self.assertEqual(row['expected_utf16le_hex'], [utf16(s) for s in raw_line.split('|')[1:]])
                self.assertEqual(row['input_utf16le_hex'], [utf16(s) for s in row['input_values']])
                self.assertEqual(len(row['expected_values']), 12)
                self.assertEqual(Counter(row['input_utf16le_hex']), Counter(row['expected_utf16le_hex']))
                self.assertIn(row['probe_body'], '\n'.join(probe.splitlines()))
                self.assertEqual(probe.splitlines()[row['probe_sort_line'] - 1], row['command'])
                assignments = re.findall(r'^STR:(\d+) = (.*)$', row['probe_body'], re.MULTILINE)
                self.assertEqual([int(index) for index, value in assignments],
                                 list(range(row['start'], row['start'] + 12)))
                self.assertEqual([value for index, value in assignments], row['input_values'])


class NativeSixVMR50(Harness):
    def check_native_row(self, row, mode):
        # Execute the received assignment/ARRAYSORT/PRINTFORML body in the VM.
        vm = self.make('@MAIN\n' + row['probe_body'] + '\n')
        rng = copy.deepcopy(vm.rng.getstate())
        original_compare = collation1824.compare_strings
        observed_identities = []
        with backend_mode(mode) as backend:
            identity = collation1824.comparison_identity()
            expected_backend = 'portable-ms-nls' if mode == 'portable' or sys.platform != 'win32' else 'windows-nls'
            self.assertEqual(identity['backend'], expected_backend)
            self.assertEqual(type(backend).__name__,
                             'WindowsNLSBackend' if expected_backend == 'windows-nls' else 'PortableNLSBackend')
            self.assertEqual(identity['culture'], 'ja-JP')

            def counted(left, right, culture=None):
                self.assertIs(collation1824._backend(), backend)
                observed_identities.append(collation1824.comparison_identity(culture))
                return original_compare(left, right, culture)

            # Patch before command invocation. No dependency on array_commands
            # importing a global comparator, and count actual backend transport.
            with patch.object(backend, 'compare', wraps=backend.compare) as backend_compare, patch.object(
                collation1824, 'compare_strings', side_effect=counted
            ) as compare:
                vm.call('MAIN')
            actual = [vm.get(f'STR:{i}') for i in range(row['start'], row['start'] + row['count'])]
            self.native_observation = {
                'case_id': row['case_id'], 'mode': mode, 'sys_platform': sys.platform,
                'backend_class': type(backend).__name__, 'backend_identity': identity,
                'compare_strings_calls': compare.call_count,
                'backend_compare_calls': backend_compare.call_count,
                'every_comparison_identity_matched': all(item == identity for item in observed_identities),
                'comparison_cultures': sorted({call.args[2] for call in backend_compare.call_args_list}),
                'input_utf16le_hex': row['input_utf16le_hex'],
                'actual_values': actual, 'actual_utf16le_hex': [utf16(value) for value in actual],
                'expected_utf16le_hex': row['expected_utf16le_hex'],
                'matches_received_native': actual == row['expected_values'],
                'rng_unchanged': vm.rng.getstate() == rng,
                'native_observation': 'received six-case Emuera OUTPUTLOG, not a new native run',
            }
            self.assertGreater(compare.call_count, 0, 'ARRAYSORT did not call compare_strings')
            self.assertEqual(backend_compare.call_count, compare.call_count)
            self.assertTrue(all(item == identity for item in observed_identities))
            self.assertTrue(all(call.args[2] == identity['culture'] for call in backend_compare.call_args_list))
        self.assertEqual([utf16(value) for value in actual], row['expected_utf16le_hex'])
        self.assertEqual(actual, row['expected_values'])
        self.assertEqual([line for line in self.output.getvalue().splitlines() if line.startswith('RESULT_')],
                         [row['native_output_line']])
        self.assertEqual(vm.rng.getstate(), rng)


def add_native_test(row, mode):
    def test(self):
        self.check_native_row(row, mode)
    test.__name__ = 'test_' + row['case_id'] + '_' + mode
    setattr(NativeSixVMR50, test.__name__, test)


for _row in FIXTURE['cases']:
    for _mode in ('default_backend', 'portable'):
        add_native_test(_row, _mode)


class ArraySortStateR50(Harness):
    def arrays(self, values, *, string=True, source='@MAIN\nARRAYSORT ITEMS\n', extra=''):
        vm = self.make(source, headers=f'#{"DIMS" if string else "DIM"} ITEMS,{len(values)}\n#DIMS OTHER,3\n' + extra)
        for index, value in enumerate(values):
            vm.set(f'ITEMS:{index}', value)
        vm.set('OTHER:0', 'unrelated')
        vm.set('RESULT:0', 917)
        vm.set('RESULT:1', 121)
        vm.set('RESULTS:0', 'retained')
        vm.set('RESULTS:1', 'also retained')
        return vm

    def command(self, vm, arguments):
        self.assertTrue(execute(vm, 'ARRAYSORT', arguments))

    def values(self, vm):
        return [vm.get(f'ITEMS:{i}') for i in range(vm.lookup('ITEMS').dims[0])]

    def test_partial_range_preserves_outside_all_other_variables_result_results_rng(self):
        for mode in ('default_backend', 'portable'):
            for row in FIXTURE['cases']:
                with self.subTest(mode=mode, case=row['case_id']), backend_mode(mode):
                    vm = self.arrays(['prefix'] + row['input_values'] + ['suffix'])
                    before = snapshot(vm)
                    self.command(vm, f'ITEMS,{row["order"]},1,12')
                    self.assertEqual(self.values(vm), ['prefix'] + row['expected_values'] + ['suffix'])
                    after = snapshot(vm)
                    before.pop('items'); after.pop('items')
                    before['variables'].pop('ITEMS', None); after['variables'].pop('ITEMS', None)
                    self.assertEqual(after, before)

    def test_raw_multiset_preserves_cultural_ties_duplicates_empty_and_utf16(self):
        values = ['e\u0301', '', 'é', 'a', 'é', '', 'A', 'e\u0301', '\0', '😀', '\ud83d\ude00']
        for order in ('FORWARD', 'BACK'):
            with self.subTest(order=order), backend_mode('portable') as backend:
                self.assertEqual(backend.compare('é', 'e\u0301', 'ja-JP'), 0)
                vm = self.arrays(values)
                self.command(vm, f'ITEMS,{order},0,{len(values)}')
                self.assertEqual(Counter(self.values(vm)), Counter(values))
                self.assertEqual(Counter(map(utf16, self.values(vm))), Counter(map(utf16, values)))
                self.assertEqual(self.values(vm).count(''), 2)

    def test_back_reverses_comparer_arguments_instead_of_reversing_ascending_output(self):
        # Two distinct equal strings expose reverse(ascending): it would flip
        # their order. The two-element Framework swap compares input[0],input[1].
        vm = self.arrays(['é', 'e\u0301'])
        original_compare = collation1824.compare_strings
        with backend_mode('portable'), patch.object(
            collation1824, 'compare_strings', wraps=original_compare
        ) as compare:
            self.command(vm, 'ITEMS,BACK,0,2')
        self.assertEqual(self.values(vm), ['é', 'e\u0301'])
        self.assertEqual([call.args[:2] for call in compare.call_args_list], [('e\u0301', 'é')])
        self.assertNotEqual(self.values(vm), list(reversed(['é', 'e\u0301'])))

    def test_back_calls_reversed_arguments_not_negated_forward_comparison(self):
        vm = self.arrays(['b', 'a'])
        with patch.object(collation1824, 'compare_strings', return_value=7) as compare:
            self.command(vm, 'ITEMS,BACK,0,2')
        self.assertEqual([call.args[:2] for call in compare.call_args_list], [('a', 'b')])
        self.assertEqual(self.values(vm), ['a', 'b'])

    def test_count_zero_is_vm_noop_and_count_one_never_compares(self):
        # ScriptProc's num==0 break precedes VariableEvaluator.SortArray's
        # num<=0 normalization. An empty helper input is a separate API case.
        for string, values in ((True, ['b', 'A', '', 'a']), (False, [9, -2, 3, 1])):
            for order in ('FORWARD', 'BACK'):
                for start, count in ((0, 0), (2, 0), (4, 0), (0, 1), (3, 1)):
                    with self.subTest(string=string, order=order, start=start, count=count):
                        vm = self.arrays(values, string=string)
                        before = snapshot(vm)
                        with patch.object(collation1824, 'compare_strings', side_effect=AssertionError('unexpected comparison')) as compare:
                            self.command(vm, f'ITEMS,{order},{start},{count}')
                        compare.assert_not_called()
                        self.assertEqual(snapshot(vm), before)

    def test_default_order_empty_fields_and_omitted_count(self):
        for arguments, expected in (
            ('ITEMS', ['a', 'A', 'b', 'B']),
            ('ITEMS,,,', ['a', 'A', 'b', 'B']),
            ('ITEMS,,1,', ['b', 'a', 'A', 'B']),
            ('ITEMS, back ,1', ['b', 'B', 'A', 'a']),
        ):
            with self.subTest(arguments=arguments), backend_mode('portable'):
                vm = self.arrays(['b', 'A', 'a', 'B'])
                self.command(vm, arguments)
                self.assertEqual(self.values(vm), expected)

    def test_array_reference_subscript_evaluates_once_but_range_uses_explicit_start(self):
        vm = self.arrays(['b', 'a', 'A', 'c'])
        vm.set('A', 0)
        with backend_mode('portable'):
            self.command(vm, 'ITEMS:(++A),FORWARD,0,3')
        self.assertEqual(vm.get('A'), 1)
        self.assertEqual(self.values(vm), ['a', 'A', 'b', 'c'])

    def test_rng_argument_is_evaluated_once_before_sorting(self):
        vm = self.arrays(['c', 'b', 'a'])
        expected_rng = copy.deepcopy(vm.rng)
        expected_count = expected_rng.randrange(4)
        with backend_mode('portable'):
            self.command(vm, 'ITEMS,FORWARD,0,RAND(4)')
        self.assertEqual(vm.rng.getstate(), expected_rng.getstate())
        expected = {
            0: ['c', 'b', 'a'], 1: ['c', 'b', 'a'],
            2: ['b', 'c', 'a'], 3: ['a', 'b', 'c'],
        }[expected_count]
        self.assertEqual(self.values(vm), expected)

    def test_string_reference_parameter_sorts_the_callers_array(self):
        vm = self.arrays(['prefix', 'a', 'B', 'suffix'], source=(
            '@MAIN\nCALL SORTING,ITEMS\n'
            '@SORTING(DEST)\n#DIMS REF DEST\nARRAYSORT DEST,BACK,1,2\n'))
        with backend_mode('portable'):
            vm.call('MAIN')
        self.assertEqual(self.values(vm), ['prefix', 'B', 'a', 'suffix'])
        self.assertEqual(vm.get('OTHER:0'), 'unrelated')

    def test_ignore_case_configuration_does_not_casefold_arraysort_values(self):
        row = FIXTURE['cases'][0]
        for setting in ('YES', 'NO'):
            with self.subTest(setting=setting), backend_mode('portable'):
                vm = self.arrays(row['input_values'])
                for config in (vm.program.config, vm.data.config):
                    config['IgnoreCase'] = setting
                    config['大文字小文字の違いを無視する'] = setting
                self.command(vm, 'ITEMS,FORWARD,0,12')
                self.assertEqual(self.values(vm), row['expected_values'])

    def test_array_read_error_precedes_comparison_and_writeback(self):
        vm = self.arrays(['c', 'b', 'a'])
        before = snapshot(vm)
        var = vm.lookup('ITEMS')
        original_get = var.get

        def read(key):
            if key == (1,):
                raise EraError('neutral array read failure', code='E_INDEX')
            return original_get(key)

        with patch.object(var, 'get', side_effect=read), patch.object(
            collation1824, 'compare_strings', side_effect=AssertionError('comparison before complete read')
        ) as compare:
            with self.assertRaises(EraError) as caught:
                execute(vm, 'ARRAYSORT', 'ITEMS,FORWARD,0,3')
        self.assertEqual(caught.exception.code, 'E_INDEX')
        compare.assert_not_called()
        self.assertEqual(snapshot(vm), before)

    def test_writeback_failure_preserves_prior_writes_and_other_state(self):
        # Unlike comparison failure, existing sequential var.set writeback can
        # leave a prefix when the embedding transport fails after the first set.
        vm = self.arrays(['prefix', 'c', 'b', 'a', 'suffix'])
        before = snapshot(vm)
        var = vm.lookup('ITEMS')
        original_set = var.set
        writes = []

        def write(key, value):
            writes.append((key, value))
            if len(writes) == 2:
                raise EraError('neutral array write failure', code='E_INDEX')
            return original_set(key, value)

        with backend_mode('portable'), patch.object(var, 'set', side_effect=write):
            with self.assertRaises(EraError) as caught:
                execute(vm, 'ARRAYSORT', 'ITEMS,FORWARD,1,3')
        self.assertEqual(caught.exception.code, 'E_INDEX')
        self.assertEqual(writes, [((1,), 'a'), ((2,), 'b')])
        self.assertEqual(self.values(vm), ['prefix', 'a', 'b', 'a', 'suffix'])
        after = snapshot(vm)
        before.pop('items'); after.pop('items')
        before['variables'].pop('ITEMS', None); after['variables'].pop('ITEMS', None)
        self.assertEqual(after, before)

    def test_numeric_signed_extremes_and_partial_ranges_never_use_string_comparer(self):
        for order, expected in (
            ('FORWARD', [99, -(1 << 63), -1, 0, 0, (1 << 63) - 1, 77]),
            ('BACK', [99, (1 << 63) - 1, 0, 0, -1, -(1 << 63), 77]),
        ):
            with self.subTest(order=order):
                vm = self.arrays([99, (1 << 63) - 1, 0, -(1 << 63), 0, -1, 77], string=False)
                before = snapshot(vm)
                with patch.object(collation1824, 'compare_strings', side_effect=AssertionError('numeric used collation')) as compare:
                    self.command(vm, f'ITEMS,{order},1,5')
                compare.assert_not_called()
                self.assertEqual(self.values(vm), expected)
                after = snapshot(vm)
                before.pop('items'); after.pop('items')
                before['variables'].pop('ITEMS', None); after['variables'].pop('ITEMS', None)
                self.assertEqual(after, before)

    def test_comparison_eraerror_after_prior_comparisons_leaves_all_state_unchanged(self):
        for mode in ('default_backend', 'portable'):
            for order in ('FORWARD', 'BACK'):
                with self.subTest(mode=mode, order=order), backend_mode(mode):
                    vm = self.arrays(['prefix', 'd', 'c', 'b', 'a', 'suffix'])
                    before = snapshot(vm)
                    calls = []
                    original_compare = collation1824.compare_strings
                    failure = EraError('neutral injected comparison failure', code='E_COLLATION')

                    def fail(left, right, culture=None):
                        calls.append((left, right))
                        if len(calls) == 3:
                            raise failure
                        return original_compare(left, right, culture)

                    with patch.object(collation1824, 'compare_strings', side_effect=fail):
                        with self.assertRaises(EraError) as caught:
                            self.command(vm, f'ITEMS,{order},1,4')
                    self.assertEqual(len(calls), 3)
                    self.assertEqual(caught.exception.code, 'E_COLLATION')
                    self.assertEqual(snapshot(vm), before)

    def test_comparison_python_exception_has_bounded_diagnostic_and_command_location(self):
        secret = 'do-not-echo-array-value-' + 'x' * 10000
        vm = self.arrays(['d', 'c', 'b', 'a'], source='@MAIN\nCALL SORTING\nA=999\n@SORTING\nARRAYSORT ITEMS,BACK,0,4\nB=999\n')
        before = snapshot(vm)
        failure = ValueError(secret)
        with patch.object(collation1824, 'compare_strings', side_effect=failure) as compare:
            with self.assertRaises(InternalError) as caught:
                vm.call('MAIN')
        error = caught.exception
        self.assertGreater(compare.call_count, 0)
        self.assertEqual(error.code, 'E_INTERNAL')
        # A helper may wrap the comparison error; it must remain in the cause
        # chain and none of its arbitrary text belongs in the ERB diagnostic.
        causes = []; cause = error
        while cause is not None and len(causes) < 16:
            causes.append(cause); cause = cause.__cause__
        self.assertIn(failure, causes)
        self.assertEqual((Path(error.location.path).name, error.location.line), ('Main.ERB', 5))
        self.assertEqual([(frame['function'], frame['line']) for frame in error.era_stack],
                         [('MAIN', 2), ('SORTING', 5)])
        report = error.as_dict()
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn(secret, str(error))
        diagnostic = report['internal_diagnostic']
        self.assertFalse(diagnostic['source_and_locals_included'])
        self.assertLessEqual(len(diagnostic['frames']), 16)
        for frame in diagnostic['frames']:
            self.assertEqual(set(frame), {'file', 'line', 'function'})
            self.assertEqual(frame['file'], Path(frame['file']).name)
        self.assertEqual(snapshot(vm), before)

    def test_eraerror_command_location_and_state_survive_vm_unwind(self):
        vm = self.arrays(['d', 'c', 'b', 'a'], source='@MAIN\nARRAYSORT ITEMS,FORWARD,0,4\nA=999\n')
        before = snapshot(vm)
        with patch.object(collation1824, 'compare_strings', side_effect=EraError('neutral', code='E_COLLATION')):
            with self.assertRaises(EraError) as caught:
                vm.call('MAIN')
        error = caught.exception
        self.assertEqual((error.code, Path(error.location.path).name, error.location.line),
                         ('E_COLLATION', 'Main.ERB', 2))
        self.assertEqual([(frame['function'], frame['line']) for frame in error.era_stack], [('MAIN', 2)])
        self.assertEqual(snapshot(vm), before)


class ArraySortValidationR50(Harness):
    arrays = ArraySortStateR50.arrays
    command = ArraySortStateR50.command
    values = ArraySortStateR50.values


def add_validation_test(name, arguments, code, headers=''):
    def test(self):
        vm = self.arrays(['c', 'b', 'a'], extra=headers)
        before = snapshot(vm)
        with patch.object(collation1824, 'compare_strings', side_effect=AssertionError('compared before validation')) as compare:
            with self.assertRaises(EraError) as caught:
                execute(vm, 'ARRAYSORT', arguments)
        self.assertEqual(caught.exception.code, code)
        compare.assert_not_called()
        self.assertEqual(snapshot(vm), before)
    test.__name__ = 'test_validation_' + name
    setattr(ArraySortValidationR50, test.__name__, test)


for _plan in (
    ('missing_reference_keeps_existing_syntax_error', '', 'E_SYNTAX'),
    ('too_many_arguments', 'ITEMS,FORWARD,0,2,0', 'E_ARGUMENT'),
    ('unknown_order', 'ITEMS,SIDEWAYS,A:0++,RAND(7)', 'E_ARGUMENT'),
    ('quoted_order', 'ITEMS,"BACK",A:0++,RAND(7)', 'E_ARGUMENT'),
    ('reference_error_precedes_order', 'ITEMS:(1/0),INVALID,A:0++,RAND(7)', 'E_ARITH'),
    ('nonvariable_reference', '"ITEMS",FORWARD,A:0++,RAND(7)', 'E_REFERENCE'),
    ('invalid_reference_index', 'ITEMS:999,FORWARD,A:0++,RAND(7)', 'E_INDEX'),
    ('negative_start', 'ITEMS,FORWARD,-1,1', 'E_INDEX'),
    ('negative_count', 'ITEMS,FORWARD,0,-1', 'E_INDEX'),
    ('end_beyond_bounds', 'ITEMS,FORWARD,2,2', 'E_INDEX'),
    ('start_beyond_bounds', 'ITEMS,FORWARD,4,0', 'E_INDEX'),
    ('start_type', 'ITEMS,FORWARD,"0",RAND(7)', 'E_TYPE'),
    ('count_type', 'ITEMS,FORWARD,0,"2"', 'E_TYPE'),
    ('multidimensional', 'MATRIX,FORWARD,A:0++,RAND(7)', 'E_UNSUPPORTED', '#DIMS MATRIX,2,3'),
    ('readonly', 'LOCKED,FORWARD,A:0++,RAND(7)', 'E_READONLY', '#DIMS CONST LOCKED,3="c","b","a"'),
    ('readonly_precedes_dimension', 'LOCKED,INVALID,A:0++,RAND(7)', 'E_READONLY', '#DIMS CONST LOCKED,3="c","b","a"'),
):
    add_validation_test(*_plan)


def validation_evaluation_order(self):
    vm = self.arrays(['d', 'c', 'b', 'a', 'e'])
    events = []
    original_ref, original_eval = vm.ref, vm.eval

    def ref(text):
        events.append(('ref', text))
        return original_ref(text)

    def evaluate(text):
        events.append(('eval', text))
        return original_eval(text)

    with backend_mode('portable'), patch.object(vm, 'ref', side_effect=ref), patch.object(vm, 'eval', side_effect=evaluate):
        self.command(vm, 'ITEMS:(A:0++),FORWARD,(A:0++),(A:0++)')
    self.assertEqual(events, [('ref', 'ITEMS:(A:0++)'), ('eval', '(A:0++)'), ('eval', '(A:0++)')])
    self.assertEqual(vm.get('A:0'), 3)
    self.assertEqual(self.values(vm), ['d', 'b', 'c', 'a', 'e'])


def validation_prior_side_effects_survive_later_range_error(self):
    vm = self.arrays(['c', 'b', 'a'])
    before = snapshot(vm)
    with patch.object(collation1824, 'compare_strings') as compare:
        with self.assertRaises(EraError) as caught:
            execute(vm, 'ARRAYSORT', 'ITEMS:(A:0++),FORWARD,(A:0++),(A:0+++3)')
    self.assertEqual(caught.exception.code, 'E_INDEX')
    self.assertEqual(vm.get('A:0'), 3)
    self.assertEqual(self.values(vm), ['c', 'b', 'a'])
    compare.assert_not_called()
    after = snapshot(vm)
    before['variables'].pop('A', None); after['variables'].pop('A', None)
    self.assertEqual(after, before)


def validation_character_arrays_remain_unsupported(self):
    vm = self.make(headers='#DIMS ITEMS,3\n#DIMS CHARADATA CHARS,3', csv=CHARA)
    vm.data.add_default_character(0)
    vm.set('CHARS:0:0', 'c'); vm.set('CHARS:0:1', 'b'); vm.set('CHARS:0:2', 'a')
    before = snapshot(vm)
    with patch.object(collation1824, 'compare_strings') as compare:
        with self.assertRaises(EraError) as caught:
            execute(vm, 'ARRAYSORT', 'CHARS:0:0,FORWARD,A:0++,RAND(7)')
    self.assertEqual(caught.exception.code, 'E_UNSUPPORTED')
    compare.assert_not_called()
    self.assertEqual(snapshot(vm), before)


def validation_value_type_error_does_not_write(self):
    for string, invalid in ((True, 7), (False, 'seven')):
        with self.subTest(string=string):
            vm = self.arrays(['c', 'b', 'a'] if string else [3, 2, 1], string=string)
            # A direct embedding caller can corrupt sparse storage. Preserve
            # the existing post-sort type validation, using count 1 so no
            # comparison obscures that specific failure stage.
            vm.lookup('ITEMS').values[(1,)] = invalid
            before = snapshot(vm)
            with patch.object(collation1824, 'compare_strings') as compare:
                with self.assertRaises(EraError) as caught:
                    execute(vm, 'ARRAYSORT', 'ITEMS,FORWARD,1,1')
            self.assertEqual(caught.exception.code, 'E_TYPE')
            compare.assert_not_called()
            self.assertEqual(snapshot(vm), before)


ArraySortValidationR50.test_reference_start_count_evaluation_order = validation_evaluation_order
ArraySortValidationR50.test_prior_side_effects_survive_later_range_error = validation_prior_side_effects_survive_later_range_error
ArraySortValidationR50.test_character_arrays_remain_unsupported = validation_character_arrays_remain_unsupported
ArraySortValidationR50.test_value_type_error_does_not_write = validation_value_type_error_does_not_write


if __name__ == '__main__':
    unittest.main()
