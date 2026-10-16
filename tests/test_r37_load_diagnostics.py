import io
from pathlib import Path
from unittest.mock import patch
from test_core import Harness
from pyemuera.load_arguments import display_diagnostics
from pyemuera.load_arguments import analysis_functions
from pyemuera.errors import EraError
from pyemuera.cli import main

CONFIG='FunctionNotCalledWarning:DISPLAY\nFunctionNotFoundWarning:DISPLAY\n'

class Registration(Harness):
    def test_unknown_uncalled_instruction_is_detected_at_load(self):
        vm=self.make('@SYSTEM_TITLE\nQUIT\n@UNUSED\nUNKNOWN_COMMAND\nRETURN',csv={'_fixed.config':CONFIG})
        before=vm.rng.getstate();self.assertEqual(len(vm.program.lexical_diagnostics),1)
        diagnostic=vm.program.lexical_diagnostics[0]
        self.assertEqual((diagnostic.location.line,diagnostic.reference_message),(4,'解釈できない行です'))
        with self.assertRaises(EraError) as error:vm.run()
        self.assertEqual(error.exception.code,'E_LOAD');self.assertEqual(vm.steps,0);self.assertEqual(vm.rng.getstate(),before)
        self.assertLess(self.output.getvalue().index('警告Lv2:'),self.output.getvalue().index('警告Lv1:'))

    def test_hidden_warnings_do_not_enable_invalid_source(self):
        vm=self.make('@SYSTEM_TITLE\nQUIT\n@UNUSED\nUNKNOWN_COMMAND',csv={'_fixed.config':CONFIG+'DisplayWarningLevel:3'})
        with self.assertRaises(EraError) as error:vm.run()
        self.assertEqual(error.exception.code,'E_LOAD');self.assertNotIn('警告Lv',self.output.getvalue())

    def test_compati_error_line_allows_unreached_invalid_source(self):
        vm=self.make('@SYSTEM_TITLE\nQUIT\n@UNUSED\nUNKNOWN_COMMAND',csv={'_fixed.config':'CompatiErrorLine:YES'})
        vm.run();self.assertEqual(vm.exit_reason,'quit')

    def test_compati_error_line_does_not_clear_reached_line_error(self):
        vm=self.make('@SYSTEM_TITLE\nUNKNOWN_COMMAND',csv={'_fixed.config':'CompatiErrorLine:YES'})
        with self.assertRaises(EraError) as error:vm.run()
        self.assertEqual(error.exception.code,'E_SYNTAX');self.assertEqual(error.exception.location.line,2)

    def test_bad_header_registers_lexical_and_invalid_label_warning(self):
        vm=self.make('@SYSTEM_TITLE\nQUIT\n@ BAD HEADER(\nRETURN\n@GOOD\nRETURN',csv={'_fixed.config':CONFIG})
        display_diagnostics(vm)
        self.assertIn('字句解析中に対応する\')\'のない\'(\'',self.output.getvalue())
        self.assertIn('関数@<Error>は定義されていますが一度も呼び出されません',self.output.getvalue())
        self.assertIn('GOOD',vm.program.functions);self.assertNotIn('<Error>',vm.program.functions)
        with self.assertRaises(EraError) as error:vm.run()
        self.assertEqual(error.exception.code,'E_LOAD')

    def test_unknown_instruction_does_not_consume_its_operand(self):
        vm=self.make('@SYSTEM_TITLE\nQUIT\n@UNUSED\nUNKNOWN ++B,RAND(10)',csv={'_fixed.config':CONFIG})
        before=vm.rng.getstate();display_diagnostics(vm)
        self.assertEqual(vm.get('B'),0);self.assertEqual(vm.rng.getstate(),before);self.assertEqual(vm.steps,0)

    def test_direct_call_of_valid_function_keeps_api(self):
        vm=self.make('@MAIN\nA=7\nRETURN\n@OTHER\nUNKNOWN')
        vm.call('MAIN');self.assertEqual(vm.get('A'),7)

class Reachability(Harness):
    def test_literal_form_selects_only_its_static_child(self):
        vm=self.make('@SYSTEM_TITLE\nCALLFORM CHILD\nQUIT\n@CHILD\nRETURN\n@UNUSED\nRETURN',csv={'_fixed.config':CONFIG})
        self.assertEqual([f.name for f in analysis_functions(vm.program)[0]],['SYSTEM_TITLE','CHILD'])
        self.assertEqual([d.reference_message for d in vm.program.uncalled_diagnostics],['関数@UNUSEDは定義されていますが一度も呼び出されません'])
        vm.run();self.assertEqual(vm.exit_reason,'quit')

    def test_dynamic_form_remains_conservative_without_evaluation(self):
        vm=self.make('@SYSTEM_TITLE\nCALLFORM CHILD_{B++}\nQUIT\n@CHILD_0\nRETURN\n@UNUSED\nRETURN',csv={'_fixed.config':CONFIG})
        self.assertEqual(vm.program.uncalled_diagnostics,[])
        self.assertEqual(vm.get('B'),0);self.assertEqual(vm.steps,0)
        vm.run();self.assertEqual(vm.get('B'),1)

    def test_declared_ref_instruction_has_source_builder_error(self):
        vm=self.make('@SYSTEM_TITLE\n#DIM REF REF_TARGET\nREF REF_TARGET,A\nQUIT\n@UNUSED\nRETURN',csv={'_fixed.config':CONFIG+'ロード時に引数を解析する:YES\n'})
        self.assertEqual([d.reference_message for d in vm.program.argument_diagnostics],['REF命令:書式が間違っています'])
        self.assertEqual(len(vm.program.uncalled_diagnostics),1)
        with self.assertRaises(EraError) as error:vm.run()
        self.assertEqual(error.exception.code,'E_ARGUMENT')

    def test_refbyname_does_not_evaluate_effectful_name(self):
        vm=self.make('@SYSTEM_TITLE\n#DIM REF REF_TARGET\nREFBYNAME REF_TARGET,NAMEFUNC()\nQUIT\n@NAMEFUNC\n#FUNCTIONS\nB++\nRETURNF "A"')
        before=vm.rng.getstate()
        with self.assertRaises(EraError) as error:vm.run()
        self.assertEqual(error.exception.code,'E_ARGUMENT');self.assertEqual(vm.get('B'),0);self.assertEqual(vm.rng.getstate(),before)

class NativeSettings(Harness):
    def test_missing_csv_cli_fails_before_startup(self):
        vm=self.make('@SYSTEM_TITLE\nQUIT');(vm.root/'CSV').rmdir();out=io.StringIO();error=io.StringIO()
        with patch('sys.stdout',out),patch('sys.stderr',error):code=main([str(vm.root),'--no-wait'])
        self.assertEqual(code,1);self.assertNotIn('Now Loading',out.getvalue());self.assertIn('E_NO_CSV',error.getvalue())

    def test_data_only_api_retains_explicit_builtin_adaptation(self):
        vm=self.make();(vm.root/'CSV').rmdir()
        from pyemuera.data import GameData
        data=GameData(vm.root);self.assertIn('CSV directory not found. Built-in defaults only.',data.warnings)

    def test_unknown_getconfigs_native_diagnostic(self):
        vm=self.make()
        with self.assertRaises(EraError) as error:vm.eval('GETCONFIGS("unknown-item")')
        self.assertEqual(error.exception.code,'E_ARGUMENT')
        self.assertEqual(error.exception.message,'GETCONFIGS関数:文字列"unknown-item"は適切なコンフィグ名ではありません')

    def test_known_unimplemented_default_is_separate(self):
        vm=self.make()
        self.assertEqual(vm.eval('GETCONFIG("WindowX")'),760)
