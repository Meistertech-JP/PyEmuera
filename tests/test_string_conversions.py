"""String conversions through public expression/command paths.

All historical test IDs remain. R41 source-backed expectation changes are
listed in verification/r41/numeric_test_expectation_changes.json.
Python observers are test-only instruments for lookup/error ordering.
"""
from pathlib import Path
from types import SimpleNamespace

from test_core import Harness
from pyemuera import builtins, commands, dispatcher
from pyemuera.errors import EraError, Unsupported


class ObservedConfig(dict):
    def __init__(self, values, trace, failure=None):
        super().__init__(values)
        self.trace = trace
        self.failure = failure

    def get(self, *arguments):
        self.trace.append(('get', arguments))
        if self.failure is not None:
            raise self.failure
        return super().get(*arguments)


class ObservedProgram:
    def __init__(self, program, configuration, trace):
        self.original = program
        self.configuration = configuration
        self.trace = trace

    def __getattr__(self, name):
        return getattr(self.original, name)

    @property
    def config(self):
        self.trace.append(('program.config',))
        return self.configuration


class ObservedString(str):
    def __new__(cls, value, trace, failure=None):
        result = super().__new__(cls, value)
        result.trace = trace
        result.failure = failure
        return result

    def change(self, name):
        self.trace.append((name, str(self)))
        if self.failure is not None:
            raise self.failure
        return getattr(super(), name)()

    def upper(self):
        return self.change('upper')

    def lower(self):
        return self.change('lower')


class StringConversionContracts(Harness):
    def width_vm(self, configuration, failure=None):
        vm = self.make(max_steps=10000)
        trace = []
        config = ObservedConfig(configuration, trace, failure)
        vm.program = ObservedProgram(vm.program, config, trace)
        return vm, config, trace

    def test_decimal_defaults_and_empty_format_keep_signed_values(self):
        vm = self.make()
        for expression, expected in [('TOSTR(0)', '0'), ('TOSTR(-7)', '-7'),
                                     ('TOSTR(-7,"")', '-7')]:
            with self.subTest(expression=expression):
                self.assertEqual(vm.eval(expression), expected)

    def test_decimal_and_hexadecimal_formats_keep_padding_and_case(self):
        vm = self.make()
        for spec, expected in [('d', '12'), ('D4', '0012'), ('x4', '000c'), ('X4', '000C')]:
            with self.subTest(spec=spec):
                self.assertEqual(vm.eval('TOSTR(12,"' + spec + '")'), expected)

    def test_hexadecimal_masks_negative_int64_values(self):
        vm = self.make()
        self.assertEqual(vm.eval('TOSTR(-1,"X")'), 'FFFFFFFFFFFFFFFF')
        vm.set('A', -(1 << 63))
        self.assertEqual(vm.eval('TOSTR(A,"x")'), '8000000000000000')
        self.assertEqual(vm.eval('TOSTR(A,"D")'), '-9223372036854775808')

    def test_zero_only_format_uses_sign_aware_padding(self):
        vm = self.make()
        self.assertEqual(vm.eval('TOSTR(-7,"0000")'), '-0007')
        self.assertEqual(vm.eval('TOSTR(12345,"00")'), '12345')

    def test_unsupported_formats_are_not_newly_accepted_or_trimmed(self):
        vm = self.make()
        # Historical ID retained: all four are actually valid .NET formats.
        for spec, expected in [('N2', '7.00'), (' D2', ' D2'),
                               ('D-2', 'D-2'), ('#000', '007')]:
            with self.subTest(spec=spec):
                self.assertEqual(builtins.call(vm, 'TOSTR', [('lit', 7), ('lit', spec)]), expected)

    def test_format_width_limit_keeps_boundary_and_diagnostic(self):
        vm = self.make()
        # Framework accepts at most 99 as standard precision; longer forms
        # are custom formats, not arbitrary widths or engine-limit errors.
        self.assertEqual(vm.eval('TOSTR(7,"D99")'), '0'*98+'7')
        text = vm.eval('TOSTR(7,"D1000000")')
        self.assertEqual(text, 'D1000007')
        self.assertEqual(vm.eval('TOSTR(7,"D1000001")'), 'D1000071')

    def test_optional_missing_format_is_distinct_from_empty_string(self):
        vm = self.make()
        # Native optional null and empty both select the default format.
        self.assertEqual(vm.eval('TOSTR(7,)'), '7')
        self.assertEqual(vm.eval('TOSTR(7,"")'), '7')

    def test_numeric_value_type_is_checked_before_format_type(self):
        vm = self.make()
        with self.assertRaises(EraError) as caught:
            vm.eval('TOSTR("wrong",7)')
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_TYPE', 'Integer required, got str'))

    def test_case_conversion_retains_unicode_behavior_without_width_changes(self):
        vm = self.make()
        self.assertEqual(vm.eval('TOUPPER("aßａ日本")'), 'ASSＡ日本')
        self.assertEqual(vm.eval('TOLOWER("AİＡ日本")'), 'ai\u0307ａ日本')

    def test_japanese_width_conversion_delegates_existing_mapping(self):
        vm = self.make()
        self.assertEqual(vm.eval('TOFULL("a ﾊﾟ")'), 'ａ　パ')
        self.assertEqual(vm.eval('TOHALF("Ａ　パ")'), 'A ﾊﾟ')
        self.assertEqual(vm.eval('TOHALF("①㈱㍍")'), '①㈱㍍')

    def test_empty_width_string_reads_program_config_but_skips_locale_get(self):
        for name in ('TOHALF', 'TOFULL'):
            with self.subTest(name=name):
                vm, config, trace = self.width_vm({'内部で使用する東アジア言語': 'CHINESE'})
                self.assertEqual(vm.eval(name + '("")'), '')
                self.assertEqual(trace, [('program.config',)])

    def test_nonempty_width_string_retains_unsupported_language_diagnostic(self):
        vm, config, trace = self.width_vm({'内部で使用する東アジア言語': 'CHINESE'})
        with self.assertRaises(Unsupported) as caught:
            vm.eval('TOFULL("a")')
        self.assertEqual(caught.exception.message,
                         'StrConv width policy for CHINESE requires a separate Windows locale oracle')
        self.assertEqual(trace, [('program.config',),
                                 ('get', ('内部で使用する東アジア言語', 'JAPANESE'))])

    def test_width_surrogate_and_supplementary_policy_is_not_broadened(self):
        vm = self.make()
        for name in ('TOHALF', 'TOFULL'):
            for text in ('😀', '\ud800'):
                with self.subTest(name=name, text=repr(text)):
                    with self.assertRaises(Unsupported) as caught:
                        builtins.call(vm, name, [('lit', text)])
                    self.assertEqual(caught.exception.message,
                                     'StrConv width with supplementary/surrogate characters')
        self.assertEqual(builtins.call(vm, 'TOUPPER', [('lit', '\ud800')]), '\ud800')

    def test_width_string_type_is_checked_before_program_access(self):
        for name in ('TOHALF', 'TOFULL'):
            with self.subTest(name=name):
                with self.assertRaises(EraError) as caught:
                    builtins.call(SimpleNamespace(), name, [('lit', 7)])
                self.assertEqual((caught.exception.code, caught.exception.message),
                                 ('E_TYPE', name+'関数:第1引数の型が間違っています'))

    def test_case_method_is_called_once_and_valueerror_keeps_wrapper_and_cause(self):
        vm = self.make()
        for name, operation in [('TOUPPER', 'upper'), ('TOLOWER', 'lower')]:
            with self.subTest(name=name):
                trace = []
                failure = ValueError('case sentinel')
                value = ObservedString('a', trace, failure)
                with self.assertRaises(EraError) as caught:
                    builtins.call(vm, name, [('lit', value)])
                self.assertEqual(caught.exception.message,
                                 name + ': invalid arguments (case sentinel)')
                self.assertIs(caught.exception.__cause__, failure)
                self.assertEqual(trace, [(operation, 'a')])

    def test_locale_getter_eraerror_propagates_without_reclassification(self):
        failure = EraError('locale sentinel', code='E_CONFIG_OBSERVER')
        vm, config, trace = self.width_vm({}, failure)
        with self.assertRaises(EraError) as caught:
            vm.eval('TOFULL("a")')
        self.assertIs(caught.exception, failure)

    def test_locale_getter_valueerror_keeps_name_specific_translation(self):
        failure = ValueError('locale sentinel')
        vm, config, trace = self.width_vm({}, failure)
        with self.assertRaises(EraError) as caught:
            vm.eval('TOHALF("a")')
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_ARGUMENT', 'TOHALF: invalid arguments (locale sentinel)'))
        self.assertIs(caught.exception.__cause__, failure)

    def test_locale_reads_are_live_and_once_per_nonempty_call(self):
        vm, config, trace = self.width_vm({})
        self.assertEqual(vm.eval('TOFULL("a")'), 'ａ')
        config['内部で使用する東アジア言語'] = 'CHINESE'
        with self.assertRaises(Unsupported):
            vm.eval('TOFULL("a")')
        self.assertEqual([row[0] for row in trace],
                         ['program.config', 'get', 'program.config', 'get'])

    def test_all_arguments_evaluate_left_to_right_before_value_type_failure(self):
        vm = self.make('@MAIN\nRETURN\n@FIRST\n#FUNCTIONS\nB=B*10+1\nRETURNF "wrong"\n'
                       '@SECOND\n#FUNCTIONS\nB=B*10+2\nRETURNF "D2"\n')
        with self.assertRaises(EraError) as caught:
            vm.eval('TOSTR(FIRST(),SECOND())')
        self.assertEqual(caught.exception.code, 'E_TYPE')
        self.assertEqual(vm.get('B'), 12)

    def test_rng_in_second_argument_is_consumed_before_value_failure(self):
        vm = self.make()
        reference = self.make()
        reference.eval('RAND(10)')
        with self.assertRaises(EraError):
            vm.eval('TOSTR("wrong",STRFORM("{RAND(10)}"))')
        self.assertEqual(vm.rng.getstate(), reference.rng.getstate())

    def test_argument_count_failure_precedes_evaluation_and_rng(self):
        vm = self.make()
        state = vm.rng.getstate()
        with self.assertRaises(EraError) as caught:
            vm.eval('TOSTR(++B,"D2",RAND(10))')
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertEqual(vm.get('B'), 0)
        self.assertEqual(vm.rng.getstate(), state)

    def test_direct_and_declared_commands_keep_result_assignment_and_failure_state(self):
        for execute in (commands.execute_command, dispatcher.execute):
            with self.subTest(execute=execute.__module__):
                vm = self.make()
                vm.set('RESULT', 777)
                vm.set('RESULTS', 'sentinel')
                self.assertTrue(execute(vm, 'TOSTR', '7,"D2"'))
                self.assertEqual((vm.get('RESULT'), vm.get('RESULTS')), (777, '07'))
                with self.assertRaises(EraError) as caught:
                    execute(vm, 'TOSTR', '++B,"Q2"')
                self.assertEqual(caught.exception.message, 'TOSTR関数の書式指定が間違っています')
                self.assertEqual((vm.get('B'), vm.get('RESULT'), vm.get('RESULTS')),
                                 (1, 777, '07'))

    def test_vm_error_retains_erb_location_and_existing_diagnostic(self):
        vm = self.make('@MAIN\nTOSTR 7,"Q2"\nRETURN\n')
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_ARGUMENT', 'TOSTR関数の書式指定が間違っています'))
        self.assertEqual((Path(caught.exception.location.path).name, caught.exception.location.line),
                         ('Main.ERB', 2))
