"""Parameter argument phases: no live evaluation during native builders."""
import io
from pathlib import Path
from unittest.mock import patch

from test_core import Harness
from pyemuera.console import Console
from pyemuera.data import GameData
from pyemuera.errors import EraError
from pyemuera.program import Program
from pyemuera.runtime import VM
from pyemuera import commands, dispatcher
from pyemuera.registry import COMMAND_SPECS, validate_document


class ParameterArguments(Harness):
    def configured(self, body, mode='YES'):
        initial = self.make('@MAIN\n' + body + '\nRETURN\n', max_steps=10000)
        root = initial.root
        (root / 'emuera.config').write_text(
            'ロード時に引数を解析する:' + mode + '\n', encoding='utf-8-sig',
        )
        self.output = io.StringIO()
        return VM(Program(root), GameData(root), Console([], self.output, no_wait=True),
                  seed=123, max_steps=10000)

    def warnings(self, vm):
        return [(diagnostic.severity, diagnostic.category,
                 diagnostic.reference_message, diagnostic.location.line)
                for diagnostic in vm.program.argument_diagnostics]

    def run_error(self, vm, code, line=2):
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.location.line, line)
        self.assertTrue(caught.exception.location.path.endswith('Main.ERB'))
        return caught.exception

    def test_void_builder_ignores_malformed_expression_with_one_warning(self):
        vm = self.configured('UPCHECK UNKNOWN( ++B,1/0')
        diagnostics = self.warnings(vm)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0][0:2], (1, 'E_ARGUMENT'))
        self.assertEqual(diagnostics[0][2], 'UPCHECK命令:引数は不要です')
        before = vm.rng.getstate()
        vm.call('MAIN')
        self.assertEqual(vm.get('B'), 0)
        self.assertEqual(vm.rng.getstate(), before)

    def test_void_no_argument_has_no_warning(self):
        vm = self.configured('UPCHECK')
        self.assertEqual(self.warnings(vm), [])
        vm.call('MAIN')

    def test_void_lazy_does_not_parse_evaluate_or_warn(self):
        vm = self.configured('UPCHECK ++B,RAND(10),(', mode='NO')
        before = vm.rng.getstate()
        vm.call('MAIN')
        self.assertEqual((vm.get('B'), self.warnings(vm)), (0, []))
        self.assertEqual(vm.rng.getstate(), before)

    def test_omission_supplies_zero_with_extended_warning(self):
        vm = self.configured('CUPCHECK')
        self.assertEqual([(row[0], row[2]) for row in self.warnings(vm)],
                         [(1, 'CUPCHECK命令:省略できない引数が省略されています。Emueraは0を補います')])
        vm.data.add_character(-1, void=True)
        vm.set('CUP:0:0', 2)
        vm.call('MAIN')
        self.assertEqual(vm.get('PALAM:0:0'), 2)

    def test_lazy_omission_has_no_loader_warning(self):
        vm = self.configured('CUPCHECK', mode='NO')
        vm.call('MAIN')
        self.assertEqual(self.warnings(vm), [])

    def test_only_first_expression_consumes_state_and_no_extra_rng(self):
        for mode in ('YES', 'NO'):
            with self.subTest(mode=mode):
                vm = self.configured('CUPCHECK ++B,RAND(10)', mode)
                before = vm.rng.getstate()
                vm.call('MAIN')
                self.assertEqual(vm.get('B'), 1)
                self.assertEqual(vm.rng.getstate(), before)
                self.assertEqual(len(self.warnings(vm)), int(mode == 'YES'))

    def test_extra_dynamic_division_is_not_evaluated(self):
        vm = self.configured('CUPCHECK 0,1/B')
        vm.call('MAIN')
        self.assertEqual(vm.get('B'), 0)
        self.assertEqual([row[0] for row in self.warnings(vm)], [1])

    def test_extra_constant_failure_precedes_first_side_effect_at_load(self):
        vm = self.configured('CUPCHECK ++B,1/0')
        self.assertEqual([row[0] for row in self.warnings(vm)], [1, 2])
        self.assertEqual(vm.get('B'), 0)
        self.run_error(vm, 'E_ARITH')
        self.assertEqual(vm.get('B'), 0)

    def test_extra_constant_failure_precedes_first_side_effect_at_runtime(self):
        vm = self.configured('CUPCHECK ++B,1/0', mode='NO')
        self.assertEqual(self.warnings(vm), [])
        self.run_error(vm, 'E_ARITH')
        self.assertEqual(vm.get('B'), 0)

    def test_first_constant_failure_does_not_evaluate_extra(self):
        vm = self.configured('CUPCHECK 1/0,++B')
        self.run_error(vm, 'E_ARITH')
        self.assertEqual(vm.get('B'), 0)

    def test_unknown_extra_is_not_silently_discarded(self):
        vm = self.configured('CUPCHECK ++B,UNDEFINED()')
        self.assertEqual([row[0] for row in self.warnings(vm)], [2])
        self.run_error(vm, 'E_FUNCTION')
        self.assertEqual(vm.get('B'), 0)

    def test_invalid_extra_syntax_precedes_count_warning(self):
        vm = self.configured('CUPCHECK 0,1+')
        self.assertEqual([row[0] for row in self.warnings(vm)], [2])
        self.run_error(vm, 'E_SYNTAX')

    def test_first_type_failure_follows_excess_warning(self):
        vm = self.configured('CUPCHECK "bad",2')
        self.assertEqual([row[0] for row in self.warnings(vm)], [1, 2])
        error = self.run_error(vm, 'E_TYPE')
        self.assertEqual(error.message, 'CUPCHECK命令:第1引数の型が正しくありません')

    def test_first_missing_rejected_after_excess_warning(self):
        vm = self.configured('CUPCHECK ,0')
        self.assertEqual([row[0] for row in self.warnings(vm)], [1, 2])
        error = self.run_error(vm, 'E_ARGUMENT')
        self.assertEqual(error.message, 'CUPCHECK命令:第1引数を認識できません')

    def test_trailing_null_extra_accepted(self):
        vm = self.configured('CUPCHECK 0,')
        self.assertEqual([row[0] for row in self.warnings(vm)], [1])
        vm.call('MAIN')

    def test_multiple_null_extras_accepted(self):
        vm = self.configured('CUPCHECK 0,,')
        self.assertEqual([row[0] for row in self.warnings(vm)], [1])
        vm.call('MAIN')

    def test_extra_string_type_is_unrestricted(self):
        vm = self.configured('CUPCHECK 0,"ignored"')
        self.assertEqual([row[0] for row in self.warnings(vm)], [1])
        vm.call('MAIN')

    def test_builder_does_not_run_user_function_or_rng(self):
        vm = self.configured(
            'CUPCHECK 0,EFFECT()\nRETURN\n'
            '@EFFECT\n#FUNCTION\nB++\nRETURN RAND(10)')
        before = vm.rng.getstate()
        vm.call('MAIN')
        self.assertEqual(vm.get('B'), 0)
        self.assertEqual(vm.rng.getstate(), before)

    def test_success_cache_contains_no_operand_values(self):
        vm = self.configured('CUPCHECK ++B', mode='NO')
        vm.call('MAIN')
        vm.call('MAIN')
        self.assertEqual(vm.get('B'), 2)

    def test_static_failure_is_not_cached(self):
        vm = self.configured('RETURN', mode='NO')
        for attempt in range(2):
            with self.assertRaises(EraError) as caught:
                commands.execute_command(vm, 'CUPCHECK', '++B,1/0')
            self.assertEqual(caught.exception.code, 'E_ARITH')
        self.assertEqual(vm.get('B'), 0)
        self.assertEqual(vm._parameter_argument_cache, set())

    def test_direct_and_declared_paths_validate_extras_without_a_frame(self):
        for entry in (commands.execute_command, dispatcher.execute):
            with self.subTest(entry=entry.__module__):
                vm = self.make()
                before = vm.rng.getstate()
                entry(vm, 'CUPCHECK', '++B,RAND(10)')
                self.assertEqual(vm.get('B'), 1)
                self.assertEqual(vm.rng.getstate(), before)

    def test_ignore_uncalled_function_keeps_native_analysis_scope(self):
        initial = self.make('@SYSTEM_TITLE\nQUIT\n@UNREACHED\nCUPCHECK 1/0\nRETURN\n')
        root = initial.root
        (root / 'emuera.config').write_text('ロード時に引数を解析する:YES\n'
                                           '呼び出されなかった関数を無視する:YES\n',encoding='utf-8-sig')
        vm = VM(Program(root), GameData(root), Console([], io.StringIO(), no_wait=True))
        self.assertEqual(vm.program.argument_diagnostics, [])

    def test_new_builder_binding_is_closed_to_parameter_commands(self):
        copied = dict(COMMAND_SPECS['UPCHECK'])
        with self.assertRaises(EraError) as caught:
            validate_document({'schema_version': 1, 'commands': {'PRINTL': copied}}, 'commands')
        self.assertEqual(caught.exception.code, 'E_SPEC')

    def test_ignored_void_text_does_not_select_an_uncalled_label(self):
        initial = self.make('@SYSTEM_TITLE\nUPCHECK UNREACHED()\nQUIT\n'
                            '@UNREACHED\nCUPCHECK 1/0\nRETURN\n')
        root = initial.root
        (root / 'emuera.config').write_text('ロード時に引数を解析する:YES\n'
                                           '呼び出されなかった関数を無視する:YES\n',encoding='utf-8-sig')
        vm = VM(Program(root), GameData(root), Console([], io.StringIO(), no_wait=True))
        self.assertEqual([row.severity for row in vm.program.argument_diagnostics], [1])
        self.assertEqual(vm.program.argument_diagnostics[0].reference_message,
                         'UPCHECK命令:引数は不要です')

    def test_bare_adapter_without_loaded_functions_uses_global_metadata(self):
        vm = self.make()
        vm.program.functions.clear()
        commands.execute_command(vm, 'CUPCHECK', '++B,RAND(10)')
        self.assertEqual(vm.get('B'), 1)

    def test_argument_checks_are_not_forced_at_load(self):
        self.assertFalse(COMMAND_SPECS['UPCHECK']['force_set_argument'])
        self.assertFalse(COMMAND_SPECS['CUPCHECK']['force_set_argument'])

