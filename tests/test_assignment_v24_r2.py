"""Source-contract tests; only two original B mismatches have Windows evidence.

SET_Instruction 448-506; SP_SET_ArgumentBuilder 660-840;
VariableTerm 47-165; OperatorMethod DivIntInt/ModIntInt 298-328.
Expectations below derive from those contracts, not captured Python values.
"""
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.assignment1824 import restructure
from pyemuera.expr import parse
from pyemuera.runtime import Frame
from pyemuera.data import Ref

HEADER='#DIM OR_TRACE\n#DIM OR_IDX\n#DIM OR_DEN\n#DIM OR_ARR,4\n#DIMS OR_STR,4\n#DIM CONST OR_CONST=3\n'
FUNCTIONS='''@OR_LEFT
#FUNCTION
OR_TRACE=OR_TRACE*10+1
RETURNF 9
@OR_NEXT
#FUNCTION
OR_TRACE=OR_TRACE*10+2
OR_IDX+=1
RETURNF OR_IDX
@OR_OTHER
#FUNCTION
OR_TRACE=OR_TRACE*10+3
RETURNF 5
@OR_ZERO
#FUNCTION
OR_TRACE=OR_TRACE*10+3
RETURNF OR_DEN
@OR_STRING
#FUNCTIONS
OR_TRACE=OR_TRACE*10+1
RETURNF "X"
@OR_STRING2
#FUNCTIONS
OR_TRACE=OR_TRACE*10+3
RETURNF "Y"
@OR_MOVE
#FUNCTION
OR_TRACE=OR_TRACE*10+1
OR_IDX+=1
RETURNF 9
@OR_BAD_NEXT
#FUNCTION
OR_TRACE=OR_TRACE*10+2
OR_IDX+=1
RETURNF OR_IDX==0 ? 0 # 99
'''

class AssignmentV24(Harness):
    def vm_ready(self):
        vm=self.make('@MAIN\nRETURN\n'+FUNCTIONS,headers=HEADER)
        vm.set('OR_IDX',-1);vm.set('OR_ARR:0',3);vm.set('OR_ARR:1',7)
        vm.set('OR_STR:0','a');vm.set('OR_STR:1','b');return vm
    def test_normal_rhs_then_destination(self):
        vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()=OR_LEFT()')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_ARR:0'),vm.get('OR_IDX')),(12,9,0))
    def test_dynamic_add_can_read_and_write_different_elements(self):
        vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()+=OR_LEFT()')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_ARR:0'),vm.get('OR_ARR:1'),vm.get('OR_IDX')),(212,3,12,1))
    def test_const_plus_minus_only_resolve_once(self):
        for op in ('+=','-='):
            for rhs in ('3','1+2','OR_CONST','ABS(-3)','MAX(1,3)'):
                with self.subTest(op=op,rhs=rhs):
                    vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()'+op+rhs)
                    self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_IDX'),vm.get('OR_ARR:0'),vm.get('OR_ARR:1')),(2,0,6 if op=='+=' else 0,7))
    def test_mutable_rhs_is_never_constant_even_if_unchanged(self):
        vm=self.vm_ready();vm.set('A',3);vm._assignment('OR_ARR:OR_NEXT()+=A')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_ARR:1')),(22,6))
    def test_builtin_canrestructure_false_stays_dynamic(self):
        vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()+=NOSAMES(1,2)')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_ARR:1')),(22,4))
    def test_rand_and_virtual_variables_are_never_constant(self):
        for rhs in ('RAND:1','CHARANUM'):
            vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()+='+rhs)
            self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_ARR:1')),(22,3))
    def test_ref_binding_is_not_a_compile_time_constant(self):
        vm=self.vm_ready();vm.frames.append(Frame(vm.program.functions['MAIN'],{'OR_REF':Ref(vm.lookup('OR_CONST'),(0,))}))
        node=parse('OR_REF');self.assertEqual(restructure(node,vm),node)
    def test_getnum_unique_fold_does_not_evaluate_descriptor_indices(self):
        vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()+=GETNUM(ABL:OR_OTHER(),"missing")')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_IDX'),vm.get('OR_ARR:0')),(2,0,2))
    def test_other_compound_operators_follow_binary_source_order(self):
        for op,value,trace in [('-=',-6,212),('*=',27,212),('/=',0,122),('%=',3,122),('<<=',1536,212),('>>=',0,212),('&=',1,212),('|=',11,212),('^=',10,212)]:
            with self.subTest(op=op):
                vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()'+op+'OR_LEFT()')
                self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_ARR:0'),vm.get('OR_ARR:1')),(trace,3,value))
    def test_other_compound_constants_do_not_use_addconst(self):
        vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()*=3')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_ARR:1')),(22,9))
    def test_string_form_and_expression_rhs_before_destination(self):
        for statement,want in [('OR_STR:OR_NEXT()={OR_LEFT()}','9'),('OR_STR:OR_NEXT()\'=OR_STRING()','X')]:
            with self.subTest(statement=statement):
                vm=self.vm_ready();vm._assignment(statement)
                self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_STR:0')),(12,want))
    def test_string_compounds_read_then_rhs_then_write(self):
        for statement,trace,want in [('OR_STR:OR_NEXT()+="X"',22,'aX'),('OR_STR:OR_NEXT()+=OR_STRING()',212,'aX'),('OR_STR:OR_NEXT()*=OR_LEFT()',212,'a'*9)]:
            with self.subTest(statement=statement):
                vm=self.vm_ready();vm._assignment(statement)
                self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_STR:0'),vm.get('OR_STR:1')),(trace,'a',want))
    def test_array_all_sources_precede_one_destination_resolution(self):
        for statement,want in [('OR_ARR:OR_NEXT()=OR_LEFT(),OR_OTHER()',[9,5]),('OR_STR:OR_NEXT()\'=OR_STRING(),OR_STRING2()',['X','Y'])]:
            with self.subTest(statement=statement):
                vm=self.vm_ready();vm._assignment(statement);name='OR_STR' if isinstance(want[0],str) else 'OR_ARR'
                self.assertEqual(vm.get('OR_TRACE'),132);self.assertEqual([vm.get(name+':'+str(i)) for i in range(2)],want)
    def test_normal_rhs_error_never_evaluates_lhs(self):
        vm=self.vm_ready()
        with self.assertRaises(EraError):vm._assignment('OR_ARR:OR_NEXT()=OR_LEFT()/OR_ZERO()')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_IDX'),vm.get('OR_ARR:0')),(3,-1,3))
    def test_compound_div_zero_never_reads_or_writes_lhs(self):
        for op in ('/=','%='):
            vm=self.vm_ready()
            with self.assertRaises(EraError):vm._assignment('OR_ARR:OR_NEXT()'+op+'OR_ZERO()')
            self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_IDX'),vm.get('OR_ARR:0')),(3,-1,3))
    def test_multi_rhs_error_preserves_sources_and_blocks_destination(self):
        vm=self.vm_ready()
        with self.assertRaises(EraError):vm._assignment('OR_ARR:OR_NEXT()=OR_LEFT(),1/OR_ZERO()')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_IDX'),vm.get('OR_ARR:0')),(13,-1,3))
    def test_array_boundary_failure_preserves_written_prefix(self):
        for statement,name,want in [('OR_ARR:3=OR_LEFT(),OR_OTHER()','OR_ARR',9),('OR_STR:3\'=OR_STRING(),OR_STRING2()','OR_STR','X')]:
            with self.subTest(statement=statement):
                vm=self.vm_ready()
                with self.assertRaises(EraError):vm._assignment(statement)
                self.assertEqual((vm.get('OR_TRACE'),vm.get(name+':3')),(13,want))
    def test_failed_second_index_preserves_prior_read_and_rhs(self):
        vm=self.vm_ready()
        with self.assertRaises(EraError):vm._assignment('OR_ARR:OR_BAD_NEXT()+=OR_LEFT()')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_IDX'),vm.get('OR_ARR:0')),(212,1,3))
    def test_rhs_can_move_destination_without_changing_read_value(self):
        vm=self.vm_ready();vm.set('OR_IDX',0);vm._assignment('OR_ARR:OR_IDX+=OR_MOVE()')
        self.assertEqual((vm.get('OR_ARR:0'),vm.get('OR_ARR:1'),vm.get('OR_IDX'),vm.get('OR_TRACE')),(3,12,1,1))
    def test_increment_statement_uses_one_resolution(self):
        vm=self.vm_ready();vm._assignment('OR_ARR:OR_NEXT()++')
        self.assertEqual((vm.get('OR_TRACE'),vm.get('OR_IDX'),vm.get('OR_ARR:0')),(2,0,4))
