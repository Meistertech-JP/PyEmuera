"""Contracts for moving scalar/bit operations across the dispatch boundary."""
import copy
from unittest.mock import patch
from test_core import Harness
from pyemuera import builtins, commands, dispatcher
from pyemuera.errors import EraError
from pyemuera.registry import COMMAND_SPECS, FUNCTION_SPECS, validate_document
from pyemuera.scalar_numeric import FUNCTION_NAMES, COMMAND_NAMES

class ScalarDispatch(Harness):
    def test_registered_routes_are_closed(self):
        self.assertEqual({n for n,s in FUNCTION_SPECS.items() if s['handler']=='scalar_numeric'},FUNCTION_NAMES)
        self.assertEqual({n for n,s in COMMAND_SPECS.items() if s['family']=='scalar_numeric'},COMMAND_NAMES)
        for n in COMMAND_NAMES:self.assertEqual(dispatcher.DISPATCH[n][0].__module__,'pyemuera.scalar_numeric')

    def test_registry_rejects_arbitrary_family_binding(self):
        for kind,spec in [('commands',{'family':'scalar_numeric'}),('functions',{'handler':'scalar_numeric','min_args':1,'max_args':1,'reference_first':False})]:
            with self.subTest(kind=kind),self.assertRaises(EraError) as cm:
                validate_document({'schema_version':1,kind:{'INJECT':spec}},kind)
            self.assertEqual(cm.exception.code,'E_SPEC')

    def test_scalar_boundaries(self):
        vm=self.make()
        for expr,want in [('ABS(-7)',7),('SIGN(-7)',-1),('SIGN(0)',0),('MAX(-9,-1)',-1),('MIN(-9,-1)',-9),('LIMIT(9,2,5)',5),('INRANGE(5,2,5)',1),('GETBIT((-9223372036854775807-1),63)',1)]:
            with self.subTest(expr=expr):self.assertEqual(vm.eval(expr),want)

    def test_abs_overflow_remains_arithmetic_error(self):
        self.make();self.error('ABS((-9223372036854775807-1))','E_ARITH')

    def test_getbit_invalid_index_remains_index_error(self):
        self.make()
        for bit in [-1,64]:self.error('GETBIT(1,'+str(bit)+')','E_INDEX')

    def test_function_validation_precedes_evaluation(self):
        vm=self.make()
        with patch.object(builtins,'evaluate') as e:
            with self.assertRaises(EraError):builtins.call(vm,'ABS',[])
            e.assert_not_called()

    def test_function_arguments_evaluated_left_to_right_once(self):
        vm=self.make();seen=[];original=builtins.evaluate
        def watch(node,context):
            seen.append(node);return original(node,context)
        with patch.object(builtins,'evaluate',watch):self.assertEqual(vm.eval('LIMIT(9,2,5)'),5)
        self.assertEqual([n[1] for n in seen],[9,2,5])

    def test_no_random_result_cache(self):
        vm=self.make();state=vm.rng.getstate();values=[vm.eval('MAX(RAND(100000),RAND(100000))') for _ in range(4)]
        vm.rng.setstate(state);expected=[max(vm.rng.randrange(0,100000),vm.rng.randrange(0,100000)) for _ in range(4)]
        self.assertEqual(values,expected)

    def test_bit_commands_signed_duplicate_semantics(self):
        vm=self.script('A=0\nSETBIT A,0,63\nINVERTBIT A,0,0\nCLEARBIT A,0')
        self.assertEqual(vm.get('A'),-(1<<63))

    def test_later_bad_bit_preserves_destination(self):
        vm=self.make();vm.set('A',8)
        with self.assertRaises(EraError) as cm:dispatcher.execute(vm,'SETBIT','A,0,64')
        self.assertEqual(cm.exception.code,'E_INDEX');self.assertEqual(vm.get('A'),8)

    def test_bit_side_effect_order_and_atomic_commit(self):
        vm=self.make();vm.set('A',8);seen=[];original=vm.eval
        def evaluate(text):
            seen.append(text);vm.set('B',vm.get('B')+1)
            return original(text)
        with patch.object(vm,'eval',evaluate):
            with self.assertRaises(EraError):dispatcher.execute(vm,'SETBIT','A,0,64,1')
        self.assertEqual(seen,['0','64']);self.assertEqual(vm.get('B'),2);self.assertEqual(vm.get('A'),8)

    def test_direct_command_adapter_uses_same_contract(self):
        vm=self.make();commands.execute_command(vm,'SETBIT','A,2');self.assertEqual(vm.get('A'),4)

    def test_bit_destination_index_evaluated_once(self):
        vm=self.make();vm.set('A',3)
        dispatcher.execute(vm,'SETBIT','A:A,0,1');self.assertEqual(vm.get('A:3'),3);self.assertEqual(vm.get('A'),3)
