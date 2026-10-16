"""Configuration contracts exercised through existing public engine paths.

The same assertions run on frozen r23; none imports the new implementation.
"""
from types import SimpleNamespace

from test_core import Harness
from pyemuera import builtins, commands, dispatcher
from pyemuera.errors import EraError, Unsupported


class ObservedConfig(dict):
    def __init__(self, values, trace, before_get=None):
        super().__init__(values)
        self.trace = trace
        self.before_get = before_get

    def get(self, *arguments):
        self.trace.append(('get', arguments))
        if self.before_get is not None:
            self.before_get(*arguments)
        return super().get(*arguments)


class ObservedString(str):
    def __new__(cls, value, trace):
        result = super().__new__(cls, value)
        result.trace = trace
        return result

    def upper(self):
        self.trace.append(('upper', str(self)))
        return super().upper()

    def __int__(self):
        self.trace.append(('int', str(self)))
        return int(str(self))


class ConfigurationContracts(Harness):
    def query(self, value, name='GETCONFIG'):
        vm = self.make(max_steps=10000)
        vm.data.config['KEY'] = value
        return vm, name + '("KEY")'

    def test_numeric_query_boolean_flags_are_case_insensitive(self):
        for value, expected in [('YES', 1), ('true', 1), ('No', 0), ('fAlSe', 0)]:
            with self.subTest(value=value):
                vm, source = self.query(value)
                self.assertEqual(vm.eval(source), expected)

    def test_numeric_query_accepts_int_syntax_without_extra_flag_trimming(self):
        for value, expected in [('005', 5), ('-7', -7), (' +12 ', 12)]:
            with self.subTest(value=value):
                vm, source = self.query(value)
                self.assertEqual(vm.eval(source), expected)
        vm, source = self.query(' YES ')
        with self.assertRaises(EraError) as caught:
            vm.eval(source)
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertIsInstance(caught.exception.__cause__, ValueError)

    def test_string_query_preserves_unicode_empty_and_whitespace_values(self):
        for value in ['', ' 日本語 ', 'true', '005']:
            with self.subTest(value=value):
                vm, source = self.query(value, 'GETCONFIGS')
                self.assertEqual(vm.eval(source), value)

    def test_key_case_and_spaces_are_not_normalized(self):
        vm = self.make()
        vm.data.config.update({' Key ': '6', 'Key': '7'})
        self.assertEqual(vm.eval('GETCONFIG(" Key ")'), 6)
        self.assertEqual(vm.eval('GETCONFIG("Key")'), 7)
        with self.assertRaises(EraError) as caught:
            vm.eval('GETCONFIG("key")')
        self.assertEqual(caught.exception.message,
                         'GETCONFIG関数:文字列"key"は適切なコンフィグ名ではありません')

    def test_key_type_is_checked_before_config_access(self):
        with self.assertRaises(EraError) as caught:
            builtins.call(SimpleNamespace(), 'GETCONFIG', [('lit', 7)])
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_TYPE', 'GETCONFIG関数:第1引数の型が間違っています'))

    def test_missing_and_none_values_keep_unsupported_default_error(self):
        for configured in (False, True):
            with self.subTest(configured=configured):
                vm = self.make()
                if configured:
                    vm.data.config['KEY'] = None
                with self.assertRaises(EraError) as caught:
                    vm.eval('GETCONFIG("KEY")')
                self.assertEqual(caught.exception.message,
                                 'GETCONFIG関数:文字列"KEY"は適切なコンフィグ名ではありません')

    def test_conversion_failure_keeps_name_specific_wrapper_and_cause(self):
        vm, source = self.query('invalid')
        with self.assertRaises(EraError) as caught:
            vm.eval(source)
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertEqual(caught.exception.message,
                         'GETCONFIG: invalid arguments (' + str(caught.exception.__cause__) + ')')
        self.assertIsInstance(caught.exception.__cause__, ValueError)

    def test_savenos_and_print_settings_retain_distinct_typeerror_boundaries(self):
        vm = self.make()
        vm.data.config['表示するセーブデータ数'] = None
        with self.assertRaises(TypeError):
            vm.eval('SAVENOS()')
        vm.data.config['PRINTCの文字数'] = None
        with self.assertRaises(EraError) as caught:
            vm.eval('PRINTCLENGTH()')
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertIsInstance(caught.exception.__cause__, TypeError)

    def test_untranslated_attribute_error_keeps_vm_diagnostic_boundary(self):
        vm = self.make('@MAIN\nGETCONFIG "KEY"\nRETURN\n')
        vm.data.config['KEY'] = 7
        with self.assertRaises(AttributeError):
            vm.eval('GETCONFIG("KEY")')
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_INTERNAL')
        self.assertEqual(caught.exception.location.line, 2)
        self.assertIsInstance(caught.exception.__cause__, AttributeError)

    def test_print_aliases_share_live_defaults_and_lower_bound(self):
        vm = self.make()
        for names, key, default in [
            (('GETPRINTCPERLINE', 'PRINTCPERLINE'), 'PRINTCを並べる数', 3),
            (('GETPRINTCLENGTH', 'PRINTCLENGTH'), 'PRINTCの文字数', 25),
        ]:
            for name in names:
                if name.startswith('GETPRINT'):
                    # These Python aliases are absent from the native registry;
                    # retain the low-level API while rejecting ERB spellings.
                    with self.assertRaises(EraError) as caught:
                        vm.eval(name + '()')
                    self.assertEqual(caught.exception.code, 'E_FUNCTION')
                    self.assertEqual(builtins.call(vm, name, ()), default)
                    continue
                self.assertEqual(vm.eval(name + '()'), default)
                for value, expected in [('-3', 1), ('0', 1), ('17', 17)]:
                    vm.data.config[key] = value
                    self.assertEqual(vm.eval(name + '()'), expected)
                del vm.data.config[key]

    def test_savenos_lower_and_upper_bound_use_current_configuration(self):
        vm = self.make()
        for value, expected in [('-1', 20), ('20', 20), ('40', 40), ('80', 80), ('99', 80)]:
            vm.data.config['表示するセーブデータ数'] = value
            self.assertEqual(vm.eval('SAVENOS()'), expected)

    def test_reads_are_not_cached_and_get_occurs_once_per_query(self):
        vm = self.make()
        trace = []
        vm.data.config = ObservedConfig({'KEY': '5'}, trace)
        self.assertEqual(vm.eval('GETCONFIG("KEY")'), 5)
        vm.data.config['KEY'] = '8'
        self.assertEqual(vm.eval('GETCONFIG("KEY")'), 8)
        self.assertEqual(trace, [('get', ('KEY',)), ('get', ('KEY',))])

    def test_flag_and_numeric_conversion_call_order_is_preserved(self):
        for value, expected, operations in [
            ('TRUE', 1, ['get', 'upper']),
            ('NO', 0, ['get', 'upper', 'upper']),
            ('12', 12, ['get', 'upper', 'upper', 'int']),
        ]:
            with self.subTest(value=value):
                vm = self.make()
                trace = []
                vm.data.config = ObservedConfig({'KEY': ObservedString(value, trace)}, trace)
                self.assertEqual(vm.eval('GETCONFIG("KEY")'), expected)
                self.assertEqual([row[0] for row in trace], operations)

    def test_getter_failures_keep_existing_error_identity_or_conversion(self):
        for name, key in [('GETCONFIG', 'KEY'), ('GETPRINTCLENGTH', 'PRINTCの文字数'),
                          ('SAVENOS', '表示するセーブデータ数')]:
            with self.subTest(name=name):
                vm = self.make()
                failure = ValueError('getter sentinel')
                def fail(*arguments):
                    raise failure
                vm.data.config = ObservedConfig({}, [], fail)
                source = name + '("KEY")' if name == 'GETCONFIG' else name + '()'
                if name == 'GETPRINTCLENGTH':
                    with self.assertRaises(EraError) as caught:
                        builtins.call(vm, name, ())
                    self.assertEqual(caught.exception.message,
                                     name + ': invalid arguments (getter sentinel)')
                    self.assertIs(caught.exception.__cause__, failure)
                    continue
                if name == 'SAVENOS':
                    with self.assertRaises(ValueError) as caught:
                        vm.eval(source)
                    self.assertIs(caught.exception, failure)
                else:
                    with self.assertRaises(EraError) as caught:
                        vm.eval(source)
                    self.assertEqual(caught.exception.message,
                                     name + ': invalid arguments (getter sentinel)')
                    self.assertIs(caught.exception.__cause__, failure)

    def test_existing_eraerror_from_getter_is_not_rewrapped(self):
        vm = self.make()
        failure = EraError('getter sentinel', code='E_CONFIG_SENTINEL')
        def fail(*arguments):
            raise failure
        vm.data.config = ObservedConfig({}, [], fail)
        with self.assertRaises(EraError) as caught:
            vm.eval('GETCONFIG("KEY")')
        self.assertIs(caught.exception, failure)

    def test_ast_key_side_effects_precede_configuration_read(self):
        vm = self.make()
        trace = []
        def read(*arguments):
            trace.append(('B_at_get', vm.get('B')))
        vm.data.config = ObservedConfig({'KEY1': '9'}, trace, read)
        self.assertEqual(vm.eval('GETCONFIG(STRFORM("KEY{++B}"))'), 9)
        self.assertEqual(trace, [('get', ('KEY1',)), ('B_at_get', 1)])

    def test_public_count_error_does_not_evaluate_arguments_or_rng(self):
        vm = self.make()
        trace = []
        vm.data.config = ObservedConfig({'KEY1': '9'}, trace)
        rng = vm.rng.getstate()
        with self.assertRaises(EraError) as caught:
            vm.eval('GETCONFIG(STRFORM("KEY{++B}"),RAND(10))')
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertEqual(vm.get('B'), 0)
        self.assertEqual(vm.rng.getstate(), rng)
        self.assertEqual(trace, [])

    def test_expression_statement_uses_existing_result_type_and_failure_nonwrite(self):
        vm = self.make()
        vm.data.config['KEY'] = 'text'
        vm.set('RESULT', 777)
        self.assertTrue(dispatcher.execute(vm, 'GETCONFIGS', '"KEY"'))
        self.assertEqual((vm.get('RESULT'), vm.get('RESULTS')), (777, 'text'))
        vm.data.config['KEY'] = 42
        self.assertTrue(commands.execute_command(vm, 'GETCONFIGS', '"KEY"'))
        self.assertEqual((vm.get('RESULT'), vm.get('RESULTS')), (42, 'text'))
        vm.data.config['KEY'] = 'invalid'
        with self.assertRaises(EraError):
            commands.execute_command(vm, 'GETCONFIG', '"KEY"')
        self.assertEqual((vm.get('RESULT'), vm.get('RESULTS')), (42, 'text'))

    def test_savenos_resolves_destination_before_read_and_keeps_failed_side_effect(self):
        for value, succeeds in [('40', True), ('invalid', False)]:
            with self.subTest(value=value):
                vm = self.make()
                vm.set('A:1', 13)
                trace = []
                def read(*arguments):
                    trace.append(('B_at_get', vm.get('B')))
                vm.data.config = ObservedConfig({'表示するセーブデータ数': value}, trace, read)
                if succeeds:
                    self.assertTrue(commands.execute_command(vm, 'SAVENOS', 'A:(++B)'))
                    self.assertEqual(vm.get('A:1'), 40)
                else:
                    with self.assertRaises(ValueError):
                        commands.execute_command(vm, 'SAVENOS', 'A:(++B)')
                    self.assertEqual(vm.get('A:1'), 13)
                self.assertEqual(vm.get('B'), 1)
                self.assertEqual(trace, [('get', ('表示するセーブデータ数', '20')), ('B_at_get', 1)])

    def test_runtime_failures_keep_instruction_location_and_cause(self):
        for name, key, value, code, cause in [
            ('GETCONFIG', 'KEY', 'invalid', 'E_ARGUMENT', ValueError),
            ('GETCONFIGS', 'KEY', None, 'E_ARGUMENT', None),
            ('SAVENOS', '表示するセーブデータ数', 'invalid', 'E_INTERNAL', ValueError),
        ]:
            with self.subTest(name=name):
                argument = ' "KEY"' if name.startswith('GETCONFIG') else ''
                vm = self.make('@MAIN\n' + name + argument + '\nRETURN\n')
                vm.data.config[key] = value
                with self.assertRaises(EraError) as caught:
                    vm.call('MAIN')
                self.assertEqual(caught.exception.code, code)
                self.assertTrue(caught.exception.location.path.endswith('Main.ERB'))
                self.assertEqual(caught.exception.location.line, 2)
                if cause is None:
                    self.assertIsNone(caught.exception.__cause__)
                else:
                    self.assertIsInstance(caught.exception.__cause__, cause)
