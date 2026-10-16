"""Native method roots select analysis, never live function invocation."""
import io
from test_core import Harness
from pyemuera.program import Program
from pyemuera.data import GameData
from pyemuera.console import Console
from pyemuera.runtime import VM
from pyemuera.load_arguments import analysis_functions
from pyemuera.errors import EraError

class LoadRoots(Harness):
    def fixture(self,tail,mode='YES',ignore='YES',analysis=False,system=True):
        prefix='@SYSTEM_TITLE\nRETURN\n' if system else '@MAIN\nRETURN\n'
        initial=self.make(prefix+tail,max_steps=10000);root=initial.root
        config='ロード時に引数を解析する:'+mode+'\n'
        if ignore is not None:config+='呼び出されなかった関数を無視する:'+ignore+'\n'
        (root/'emuera.config').write_text(config,encoding='utf-8-sig')
        return VM(Program(root,analysis_mode=analysis),GameData(root),Console([],io.StringIO(),no_wait=True),seed=42,max_steps=10000)
    def selected(self,vm):return [f.name for f in analysis_functions(vm.program)[0]]
    def test_numeric_unused_method_is_root_and_marks_static_error(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nCUPCHECK 1/0\nRETURNF 0\n')
        self.assertEqual(self.selected(vm),['SYSTEM_TITLE','VALUE'])
        self.assertEqual([(d.severity,d.category,d.location.line) for d in vm.program.argument_diagnostics],[(2,'E_ARITH',5)])
        self.assertEqual((vm.get('B'),vm.steps,len(vm.frames)),(0,0,0))
    def test_string_unused_method_static_type_is_checked(self):
        vm=self.fixture('@TEXT\n#FUNCTIONS\nRETURNF 7\n')
        self.assertEqual([d.category for d in vm.program.argument_diagnostics],['E_TYPE'])
        self.assertIn('TEXT',self.selected(vm))
    def test_no_mode_preserves_dynamic_expression_boundary(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nCUPCHECK 1/0\nRETURNF 0\n',mode='NO')
        self.assertEqual(vm.program.argument_diagnostics,[])
        self.assertIn('VALUE',self.selected(vm))
        with self.assertRaises(EraError) as caught:vm.eval('VALUE()')
        self.assertEqual(caught.exception.code,'E_ARITH')
        self.assertEqual(caught.exception.location.line,5)
    def test_selected_method_is_not_executed_and_rng_not_consumed(self):
        tail='@VALUE\n#FUNCTION\nB++\nRETURNF RAND(10)\n'
        vm=self.fixture(tail);other=self.fixture('@VALUE\n#FUNCTION\nRETURNF 0\n')
        self.assertEqual(vm.rng.getstate(),other.rng.getstate())
        self.assertEqual((vm.get('B'),vm.steps,len(vm.frames)),(0,0,0))
    def test_ordinary_uncalled_function_stays_ignored(self):
        vm=self.fixture('@PLAIN\nCUPCHECK 1/0\nRETURN\n')
        self.assertEqual(self.selected(vm),['SYSTEM_TITLE'])
        self.assertEqual(vm.program.argument_diagnostics,[])
    def test_method_safety_runs_even_when_argument_analysis_no(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nINPUT\nRETURNF 0\n',mode='NO')
        d=vm.program.argument_diagnostics[0]
        self.assertEqual((d.severity,d.category,d.location.line),(2,'E_METHOD_CONTEXT',5))
        self.assertEqual(d.reference_message,'INPUT命令は#FUNCTION中で使うことはできません')
    def test_unsafe_call_does_not_make_ordinary_child_reachable(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nCALL PLAIN\nRETURNF 0\n@PLAIN\nCUPCHECK 1/0\nRETURN\n')
        self.assertEqual(self.selected(vm),['SYSTEM_TITLE','VALUE'])
        self.assertEqual([d.category for d in vm.program.argument_diagnostics],['E_METHOD_CONTEXT'])
    def test_unsafe_dynamic_call_does_not_select_all_functions(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nCALLFORM PLAIN\nRETURNF 0\n@PLAIN\nCUPCHECK 1/0\nRETURN\n')
        self.assertEqual(self.selected(vm),['SYSTEM_TITLE','VALUE'])
        self.assertEqual([d.category for d in vm.program.argument_diagnostics],['E_METHOD_CONTEXT'])
    def test_up_void_does_not_select_plain_but_method_is_independent_root(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nUPCHECK PLAIN()\nRETURNF 0\n@PLAIN\nCUPCHECK 1/0\nRETURN\n')
        self.assertEqual(self.selected(vm),['SYSTEM_TITLE','VALUE'])
        self.assertEqual([d.severity for d in vm.program.argument_diagnostics],[1])
    def test_analysis_mode_and_ignore_no_still_include_ordinary_functions(self):
        tail='@VALUE\n#FUNCTION\nRETURNF 0\n@PLAIN\nCUPCHECK 1/0\nRETURN\n'
        for opts in ({'ignore':'NO'},{'analysis':True}):
            vm=self.fixture(tail,**opts);self.assertIn('PLAIN',self.selected(vm))
            self.assertEqual([d.category for d in vm.program.argument_diagnostics],['E_ARITH'])
    def test_no_system_implicit_api_fallback_retains_main_and_plain(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nRETURNF 0\n@PLAIN\nRETURN\n',system=False,ignore=None)
        self.assertEqual(self.selected(vm),['MAIN','VALUE','PLAIN'])
        self.assertEqual(analysis_functions(vm.program)[2],'api_module_without_system_entry')
    def test_error_at_invocation_preserves_prior_body_side_effect(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nB++\nCUPCHECK 1/0\nRETURNF 0\n')
        self.assertEqual(vm.get('B'),0)
        with self.assertRaises(EraError) as caught:vm.eval('VALUE()')
        self.assertEqual((vm.get('B'),caught.exception.code,caught.exception.location.line),(1,'E_ARITH',6))

    def test_system_method_directive_does_not_create_new_context_error(self):
        initial=self.make('@SYSTEM_TITLE\n#FUNCTION\nINPUT\nRETURN\n',max_steps=10000)
        root=initial.root
        (root/'emuera.config').write_text('ロード時に引数を解析する:NO\n呼び出されなかった関数を無視する:YES\n')
        vm=VM(Program(root),GameData(root),Console([],io.StringIO(),no_wait=True))
        self.assertEqual(vm.program.argument_diagnostics,[])
        self.assertTrue(all(ins.argument_error is None for ins in vm.program.functions['SYSTEM_TITLE'][0].code))

    def test_nullable_returnf_on_unused_methods_is_not_a_syntax_error(self):
        vm=self.fixture('@VALUE\n#FUNCTION\nRETURNF\n@TEXT\n#FUNCTIONS\nRETURNF\n')
        self.assertEqual(vm.program.argument_diagnostics,[])
        self.assertEqual(vm.eval('VALUE()'),0)
        self.assertEqual(vm.eval('TEXT()'),'')
