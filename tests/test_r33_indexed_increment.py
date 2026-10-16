"""Postfix attaches to a complete reference, not its unparenthesized index."""
from test_core import Harness
from pyemuera.expr import parse
from pyemuera.errors import EraError


class IndexedIncrement(Harness):
    def test_LOCAL_numeric_index_postfix(self):
        vm=self.script('LOCAL:0=1\nA=LOCAL:0++ + LOCAL:0\nB=LOCAL:0')
        self.assertEqual((vm.get('A'),vm.get('B')),(3,2))

    def test_global_index_name_postfix_changes_array_not_index(self):
        vm=self.make();vm.set('A',2);vm.set('B:2',8)
        self.assertEqual(vm.eval('B:A++'),8)
        self.assertEqual((vm.get('A'),vm.get('B:2')),(2,9))

    def test_parenthesized_index_side_effect_remains_inside(self):
        vm=self.make();vm.set('A',2);vm.set('FLAG:2',9)
        self.assertEqual(vm.eval('FLAG:(A++)'),9)
        self.assertEqual(vm.get('A'),3)

    def test_parenthesized_index_and_outer_postfix(self):
        vm=self.make();vm.set('A',2);vm.set('FLAG:2',9)
        self.assertEqual(vm.eval('FLAG:(A++)++'),9)
        self.assertEqual((vm.get('A'),vm.get('FLAG:2')),(3,10))

    def test_multi_dimensional_postfix(self):
        vm=self.make(headers='#DIM GRID,2,3\n');vm.set('GRID:1:2',6)
        self.assertEqual(vm.eval('GRID:1:2++'),6)
        self.assertEqual(vm.get('GRID:1:2'),7)

    def test_prefix_increment_resolves_full_reference(self):
        vm=self.make();vm.set('FLAG:2',6)
        self.assertEqual(vm.eval('++FLAG:2'),7)

    def test_overflow_wrap_preserved(self):
        vm=self.make();vm.set('FLAG:2',(1<<63)-1)
        self.assertEqual(vm.eval('FLAG:2++'),(1<<63)-1)
        self.assertEqual(vm.get('FLAG:2'),-(1<<63))

    def test_index_error_retains_index_expression_side_effect(self):
        vm=self.make();vm.set('A',100000)
        with self.assertRaises(EraError) as caught:vm.eval('FLAG:(A++)++')
        self.assertEqual(caught.exception.code,'E_INDEX')
        self.assertEqual(vm.get('A'),100001)

    def test_division_RHS_order_is_unchanged(self):
        vm=self.make();vm.set('A',2)
        self.assertEqual(vm.eval('A++ / A'),1)
        self.assertEqual(vm.get('A'),3)

    def test_minus_re_evaluates_indexed_operand(self):
        vm=self.make();vm.set('FLAG:0',1)
        self.assertEqual(vm.eval('-FLAG:0++'),-2)
        self.assertEqual(vm.get('FLAG:0'),3)

    def test_short_circuit_does_not_write_indexed_operand(self):
        vm=self.make()
        self.assertEqual(vm.eval('0 && FLAG:0++'),0)
        self.assertEqual(vm.get('FLAG:0'),0)

    def test_immutable_tuple_cache_shape(self):
        node=parse('LOCAL:0++')
        self.assertEqual(node,('inc',('var','LOCAL',(('lit',0),)),1,True))
        self.assertIs(parse('LOCAL:0++'),node)
        self.assertIs(type(node),tuple)
