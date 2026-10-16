"""Process.State.ReturnF / printError and ExpressionParser CASE contracts.

New Windows comparison remains pending; the four error states are independently
observed cross-mode evidence, not whole-language equality.
"""
from test_core import Harness
from pyemuera.errors import EraError,InternalError,Location
from pyemuera.expr import parse_case_condition
from pyemuera.runtime import Frame
from pyemuera.cli import normalize_error
from unittest.mock import patch
from pathlib import Path
import json,tempfile,io
from pyemuera.program import Program
from pyemuera.data import GameData
from pyemuera.console import Console
from pyemuera.runtime import VM

class DiagnosticsR4(Harness):
    def fail_run(self,source,headers='#DIM DEN\n'):
        vm=self.make(source,headers=headers)
        with self.assertRaises(EraError) as cm:vm.run('MAIN')
        self.assertEqual(vm.frames,[]);self.assertEqual(vm.method_depth,0)
        return vm,cm.exception

    def test_returned_method_error_uses_caller_instruction(self):
        vm,e=self.fail_run('@MAIN\nA=1/GOOD()\nRETURN\n@GOOD\n#FUNCTION\nB+=1\nRETURNF 0\n')
        self.assertEqual((e.code,e.location.line),('E_ARITH',2));self.assertEqual(vm.eval('B'),1)
        self.assertEqual([(x['function'],x['line']) for x in e.era_stack],[('MAIN',2)])

    def test_method_internal_error_keeps_callee_instruction(self):
        vm,e=self.fail_run('@MAIN\nA=BAD()\nRETURN\n@BAD\n#FUNCTION\nB+=1\nRETURNF 1/DEN\n')
        self.assertEqual(e.location.line,7);self.assertEqual([x['function'] for x in e.era_stack],['MAIN','BAD'])
        self.assertEqual(vm.eval('B'),1)

    def test_nested_success_return_then_caller_error(self):
        vm,e=self.fail_run('@MAIN\nA=1/OUTER()\nRETURN\n@OUTER\n#FUNCTION\nRETURNF INNER()\n@INNER\n#FUNCTION\nRETURNF 0\n')
        self.assertEqual(e.location.line,2);self.assertEqual([x['function'] for x in e.era_stack],['MAIN'])

    def test_nested_internal_error_keeps_deep_stack(self):
        vm,e=self.fail_run('@MAIN\nA=OUTER()\nRETURN\n@OUTER\n#FUNCTION\nRETURNF INNER()\n@INNER\n#FUNCTION\nRETURNF 1/DEN\n')
        self.assertEqual(e.location.line,9);self.assertEqual([x['function'] for x in e.era_stack],['MAIN','OUTER','INNER'])

    def test_explicit_exception_position_takes_precedence(self):
        vm=self.make('@MAIN\nA=1\nRETURN\n');pos=Location('Explicit.ERB',73)
        def broken(*args):raise EraError('explicit',pos,'E_TYPE')
        with patch.object(vm,'execute',broken),self.assertRaises(EraError) as cm:vm.run('MAIN')
        self.assertEqual(cm.exception.location,pos);self.assertEqual(cm.exception.era_stack[0]['line'],2)

    def test_implicit_method_return_restores_caller(self):
        vm,e=self.fail_run('@MAIN\nA=1/ZERO()\nRETURN\n@ZERO\n#FUNCTION\nB+=1\n')
        self.assertEqual(e.location.line,2);self.assertEqual(vm.eval('B'),1)

    def test_call_and_callf_return_positions(self):
        for call,body in [('CALL SUB','@SUB\nB+=1\nRETURN\n'),('CALLF SUB','@SUB\n#FUNCTION\nB+=1\nRETURNF 1\n')]:
            with self.subTest(call=call):
                vm,e=self.fail_run('@MAIN\n'+call+'\nA=1/DEN\nRETURN\n'+body)
                self.assertEqual(e.location.line,3);self.assertEqual(vm.eval('B'),1)

    def test_dynamic_callform_return_location(self):
        vm,e=self.fail_run('@MAIN\nCALLFORM %"SUB"%\nA=1/DEN\nRETURN\n@SUB\nB+=1\nRETURN\n')
        self.assertEqual(e.location.line,3);self.assertEqual(vm.eval('B'),1)

    def test_normal_execution_restores_host_position(self):
        vm=self.make('@MAIN\nA=GOOD()\nRETURN\n@GOOD\n#FUNCTION\nRETURNF 9\n')
        vm.location=Location('Host.ERB',88);vm.call('MAIN')
        self.assertEqual(vm.location,Location('Host.ERB',88));self.assertEqual(vm.eval('A'),9)

    def test_exception_unwinds_dynamic_private_scope(self):
        vm,e=self.fail_run('@MAIN\nA=BAD()\nRETURN\n@BAD\n#FUNCTION\n#DIM DYNAMIC PRIVATE\nPRIVATE=7\nRETURNF 1/DEN\n')
        self.assertEqual(e.location.line,8);self.assertEqual(vm.frames,[])
        with self.assertRaises(EraError):vm.eval('PRIVATE')

    def test_rnd_and_side_effects_are_not_replayed_during_unwind(self):
        vm=self.make('@MAIN\nA=1/GOOD()\nRETURN\n@GOOD\n#FUNCTION\nB=RAND:100\nRETURNF 0\n')
        state=vm.rng.getstate();expected=VM(vm.program,GameData(vm.root),Console([],io.StringIO(),no_wait=True),seed=123)
        first=expected.eval('RAND:100');after=expected.rng.getstate()
        with self.assertRaises(EraError):vm.run('MAIN')
        self.assertEqual(vm.eval('B'),first);self.assertEqual(vm.rng.getstate(),after);self.assertNotEqual(state,after)

    def test_unknown_python_faults_are_internal_not_argument_errors(self):
        causes=[ValueError('private ERB content'),TypeError('private'),IndexError('private'),OverflowError('private'),UnicodeError('private'),RuntimeError('private')]
        for cause in causes:
            with self.subTest(type=type(cause).__name__):
                vm=self.make('@MAIN\nA=1\nRETURN\n')
                def broken(*args):raise cause
                with patch.object(vm,'execute',broken),self.assertRaises(InternalError) as cm:vm.run('MAIN')
                e=cm.exception;self.assertEqual((e.code,e.location.line),('E_INTERNAL',2));self.assertIs(e.__cause__,cause)
                self.assertNotIn('private',json.dumps(e.as_dict()));self.assertTrue(e.developer_frames)

    def test_erb_type_error_stays_erb_error(self):
        vm,e=self.fail_run('@MAIN\nPRINTFORML {1,"x"}\nRETURN\n')
        self.assertEqual((e.code,e.location.line),('E_TYPE',2));self.assertNotIsInstance(e,InternalError)

    def test_cli_unknown_error_diagnostic_is_bounded(self):
        e=normalize_error(ValueError('game body secret'))
        self.assertIsInstance(e,InternalError);self.assertNotIn('secret',json.dumps(e.as_dict()))

    def test_four_observed_post_error_states_and_locations(self):
        root=Path(__file__).resolve().parents[1]/'verification/oracle_v24/run03/cases'
        expected={'rhs-error':(3,-1,[3,7,0,0],'E_ARITH'),'compound-zero':(3,-1,[3,7,0,0],'E_ARITH'),'write-index-error':(212,1,[3,7,0,0],'E_INDEX'),'array-bounds':(13,-1,[3,7,0,9],'E_INDEX')}
        for cid,(trace,idx,arr,code) in expected.items():
            with self.subTest(case=cid),tempfile.TemporaryDirectory() as td:
                import shutil
                g=Path(td)/'game';shutil.copytree(root/cid/'neutral_game',g)
                vm=VM(Program(g),GameData(g),Console([],io.StringIO(),no_wait=True),seed=42)
                with self.assertRaises(EraError) as cm:vm.run(None)
                e=cm.exception;self.assertEqual((e.location.line,e.code),(7,code))
                self.assertEqual(vm.data.variables['OR_TRACE'].get((0,)),trace)
                self.assertEqual(vm.data.variables['OR_IDX'].get((0,)),idx)
                self.assertEqual([vm.data.variables['OR_ARR'].get((i,)) for i in range(4)],arr)
                self.assertEqual(e.era_stack[-1]['line'],7)

class CaseTokensR4(Harness):
    def test_quoted_to_is_literal(self):
        vm=self.make();self.assertTrue(vm._case('GO TO X','"GO TO X"'))
        self.assertTrue(vm._case('','""'));self.assertTrue(vm._case('全角 TO 空白','"全角 TO 空白"'))

    def test_nested_and_form_tokens_do_not_split_keyword(self):
        vm=self.make()
        for text,value in [('("GO TO X")','GO TO X'),('@"GO TO {1}"','GO TO 1'),('"GO \\" TO X"','GO " TO X')]:
            self.assertTrue(vm._case(value,text))

    def test_actual_ranges_multiple_conditions_and_is(self):
        vm=self.make();self.assertTrue(vm._case(2,'1 TO 3'));self.assertFalse(vm._case(4,'1 TO 3'))
        self.assertTrue(vm._case(9,'1 TO 3, IS >= 9'));self.assertTrue(vm._case(1,'IS + 2'))
        self.assertTrue(vm._case('B','"A" TO "C"'))

    def test_range_short_circuit_preserves_side_effect_order(self):
        vm=self.make('@MAIN\nRETURN\n@LEFT\n#FUNCTION\nB=B*10+1\nRETURNF 3\n@RIGHT\n#FUNCTION\nB=B*10+2\nRETURNF 9\n')
        self.assertFalse(vm._case(2,'LEFT() TO RIGHT()'));self.assertEqual(vm.eval('B'),1)

    def test_full_selectcase_caseelse_and_comment(self):
        vm=self.script('SELECTCASE "GO TO X"\nCASE "GO TO X" ; comment TO ignored\nA=9\nCASEELSE\nA=1\nENDSELECT\nRETURN')
        self.assertEqual(vm.eval('A'),9)

    def test_invalid_case_syntax_is_not_internal_fault(self):
        for s in ['','1 TO','TO 2','1 TO 2 TO 3','IS','IS ? 2','"unclosed']:
            with self.subTest(text=s),self.assertRaises(EraError) as cm:parse_case_condition(s)
            self.assertIn(cm.exception.code,('E_SYNTAX','E_FORMAT'))
