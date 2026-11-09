"""Observable boundaries for ordinary and character reference resolution."""
from unittest.mock import call, patch

from test_core import Harness
from pyemuera.data import Ref, Variable
from pyemuera.errors import EraError
from pyemuera.expr import parse
from pyemuera.runtime import Frame


class DynamicReferencePaths(Harness):
    def make_array(self, dims=(2, 3)):
        vm = self.make()
        var = Variable('A', dims)
        vm.data.variables['A'] = var
        return vm, var

    def test_operands_use_eval_node_once_left_to_right(self):
        vm, var = self.make_array()
        node = parse('A:(I++):(I++)')
        vm.set('I', 0)
        with patch.object(vm, 'eval_node', wraps=vm.eval_node) as evaluate:
            actual, key = vm._resolve_ref(node)
        self.assertIs(actual, var)
        self.assertEqual(key, (0, 1))
        self.assertEqual(vm.get('I'), 2)
        self.assertEqual(evaluate.call_args_list,
                         [call(node[2][0]), call(node[2][1])])

    def test_too_many_indices_precedes_all_operand_effects(self):
        vm, _ = self.make_array((2,))
        vm.set('I', 0)
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('A:(I++):(I++)'))
        self.assertEqual((error.exception.code, error.exception.message),
                         ('E_INDEX', 'A: too many array indices'))
        self.assertEqual(vm.get('I'), 0)

    def test_out_of_range_first_index_still_evaluates_second(self):
        vm, var = self.make_array()
        vm.set('I', 99)
        vm.set('J', 0)
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('A:(I++):(J++)'))
        self.assertEqual((vm.get('I'), vm.get('J')), (100, 1))
        with self.assertRaises(EraError) as expected:
            var.validate((99, 0))
        self.assertEqual(error.exception.as_dict(), expected.exception.as_dict())

    def test_second_operand_error_precedes_first_index_bounds(self):
        vm, _ = self.make_array()
        vm.set('I', 99)
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('A:(I++):(1/0)'))
        self.assertEqual(error.exception.code, 'E_ARITH')
        self.assertEqual(vm.get('I'), 100)

    def test_named_fallback_and_string_conversion_keep_axis_and_order(self):
        vm, _ = self.make_array()
        node = parse('A:UNKNOWN_INDEX:"COLUMN"')
        with patch.object(vm.data, 'index_of', side_effect=[1, 2]) as index_of:
            with patch.object(vm, 'eval_node', wraps=vm.eval_node) as evaluate:
                _, key = vm._resolve_ref(node)
        self.assertEqual(key, (1, 2))
        self.assertEqual(evaluate.call_args_list, [call(node[2][0])])
        self.assertEqual(index_of.call_args_list,
                         [call('A', 'UNKNOWN_INDEX', 0),
                          call('A', 'COLUMN', 1)])

    def test_non_variable_error_does_not_fall_back_or_evaluate_next(self):
        vm, _ = self.make_array()
        vm.set('I', 0)
        vm.data.variables['B'].forbidden = True
        with patch.object(vm.data, 'index_of') as index_of:
            with self.assertRaises(EraError) as error:
                vm._resolve_ref(parse('A:B:(I++)'))
        self.assertEqual(error.exception.code, 'E_VARIABLE_FORBIDDEN')
        index_of.assert_not_called()
        self.assertEqual(vm.get('I'), 0)

    def test_defined_string_index_is_converted_after_evaluation(self):
        vm, _ = self.make_array((3,))
        vm.set('STR', 'ROW')
        node = parse('A:STR')
        with patch.object(vm.data, 'index_of', return_value=2) as index_of:
            with patch.object(vm, 'eval_node', wraps=vm.eval_node) as evaluate:
                self.assertEqual(vm._resolve_ref(node)[1], (2,))
        evaluate.assert_called_once_with(node[2][0])
        index_of.assert_called_once_with('A', 'ROW', 0)

    def test_index_conversion_error_precedes_next_operand(self):
        vm, _ = self.make_array()
        vm.set('I', 0)
        with patch.object(vm.data, 'index_of', return_value=1.5):
            with self.assertRaises(EraError) as error:
                vm._resolve_ref(parse('A:"ROW":(I++)'))
        self.assertEqual((error.exception.code, error.exception.message),
                         ('E_TYPE', 'Integer required, got float'))
        self.assertEqual(vm.get('I'), 0)

    def test_dynamic_single_index_zero_fills_and_validates_trailing_axis(self):
        vm, var = self.make_array()
        vm.set('I', 1)
        self.assertEqual(vm._resolve_ref(parse('A:I')), (var, (1, 0)))
        vm.data.variables['A'] = Variable('A', (2, 0))
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('A:I'))
        with self.assertRaises(EraError) as expected:
            vm.data.variables['A'].validate((1, 0))
        self.assertEqual(error.exception.as_dict(), expected.exception.as_dict())

    def test_zero_base_ref_rebinding_and_writes_observe_live_target(self):
        vm, old = self.make_array((3,))
        scope = {'ALIAS': Ref(old, (0,))}
        vm.frames.append(Frame(vm.program.functions['MAIN'][0], scope))
        node = parse('ALIAS:I')
        vm.set('I', 1)
        ref = vm.ref_node(node)
        ref.set(10)
        self.assertEqual(old.get((1,)), 10)
        new = Variable('NEW', (3,))
        scope['ALIAS'] = Ref(new, (0,))
        with patch.object(new, 'write_observer') as observe:
            vm.ref_node(node).set(20)
            observe.assert_called_once_with(new, (1,), 0, 20)
        self.assertEqual((old.get((1,)), new.get((1,))), (10, 20))
        new.readonly = True
        with self.assertRaises(EraError) as error:
            vm.ref_node(node).set(30)
        self.assertEqual(error.exception.code, 'E_READONLY')

    def test_dynamic_ast_does_not_keep_old_global_binding_or_shape(self):
        vm, old = self.make_array((3,))
        node = parse('A:I')
        vm.set('I', 1)
        self.assertIs(vm._resolve_ref(node)[0], old)
        new = Variable('A', (3, 2))
        vm.data.variables['A'] = new
        actual, key = vm._resolve_ref(node)
        self.assertIs(actual, new)
        self.assertEqual(key, (1, 0))
        vm.set('I', 2)
        self.assertEqual(vm._resolve_ref(node)[1], (2, 0))
        new.dims = (2, 2)
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(node)
        self.assertEqual(error.exception.code, 'E_INDEX')

    def test_lookup_and_ref_errors_precede_dynamic_effects(self):
        vm, var = self.make_array((3,))
        scope = {'ALIAS': None}
        vm.frames.append(Frame(vm.program.functions['MAIN'][0], scope))
        vm.set('I', 0)
        node = parse('ALIAS:(I++)')
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(node)
        self.assertEqual(error.exception.code, 'E_REFERENCE')
        scope['ALIAS'] = Ref(var, (1,))
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(node)
        self.assertEqual(error.exception.code, 'E_UNSUPPORTED')
        var.forbidden = True
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(node)
        self.assertEqual(error.exception.code, 'E_VARIABLE_FORBIDDEN')
        self.assertEqual(vm.get('I'), 0)

    def test_character_target_and_descriptor_rules_remain_live(self):
        vm = self.make()
        vm.data.character_count = 1
        var = Variable('CFLAG', (3,), character=True)
        vm.data.variables['CFLAG'] = var
        vm.set('I', 1)
        vm.set('TARGET', 2)
        node = parse('CFLAG:I')
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(node)
        self.assertEqual(error.exception.code, 'E_CHARACTER')
        self.assertEqual(vm._resolve_ref(node, allow_character_descriptor=True),
                         (var, (0, 1)))
        vm.set('TARGET', 0)
        self.assertEqual(vm._resolve_ref(node), (var, (0, 1)))

    def test_scalar_read_rebinds_ref_and_keeps_forbidden_precedence(self):
        vm, old = self.make_array((2,))
        old.set((0,), 10)
        scope = {'ALIAS': Ref(old, (0,))}
        vm.frames.append(Frame(vm.program.functions['MAIN'][0], scope))
        node = parse('ALIAS')
        self.assertEqual(vm.read_node(node), 10)
        new = Variable('NEW', (1, 1), default=30)
        scope['ALIAS'] = Ref(new, (0, 0))
        self.assertEqual(vm.read_node(node), 30)
        scope['ALIAS'] = Ref(new, (1, 0))
        with self.assertRaises(EraError) as error:
            vm.read_node(node)
        self.assertEqual(error.exception.code, 'E_UNSUPPORTED')
        new.forbidden = True
        with self.assertRaises(EraError) as error:
            vm.read_node(node)
        self.assertEqual(error.exception.code, 'E_VARIABLE_FORBIDDEN')
        scope['ALIAS'] = None
        with self.assertRaises(EraError) as error:
            vm.read_node(node)
        self.assertEqual(error.exception.code, 'E_REFERENCE')

    def test_scalar_read_keeps_zero_shape_diagnostic_and_live_default(self):
        vm, var = self.make_array((1, 0))
        node = parse('A')
        with self.assertRaises(EraError) as actual:
            vm.read_node(node)
        with self.assertRaises(EraError) as expected:
            vm._resolve_ref(node)
        self.assertEqual(actual.exception.as_dict(), expected.exception.as_dict())
        var.dims = ()
        var.default = 12
        self.assertEqual(vm.read_node(node), 12)
        var.default = 14
        self.assertEqual(vm.read_node(node), 14)

    def test_scalar_character_read_uses_live_target_and_rejects_ref(self):
        vm = self.make()
        vm.data.character_count = 2
        var = Variable('CFLAG', (3,), character=True)
        var.set((0, 0), 10)
        var.set((1, 0), 20)
        vm.data.variables['CFLAG'] = var
        node = parse('CFLAG')
        vm.set('TARGET', 0)
        self.assertEqual(vm.read_node(node), 10)
        vm.set('TARGET', 1)
        self.assertEqual(vm.read_node(node), 20)
        vm.set('TARGET', 2)
        with self.assertRaises(EraError) as error:
            vm.read_node(node)
        self.assertEqual(error.exception.code, 'E_CHARACTER')
        vm.frames.append(Frame(vm.program.functions['MAIN'][0],
                               {'ALIAS': Ref(var, (0, 0))}))
        with self.assertRaises(EraError) as error:
            vm.read_node(parse('ALIAS'))
        self.assertEqual(error.exception.code, 'E_UNSUPPORTED')


class CharacterReferencePaths(Harness):
    def make_character(self, name='CFLAG'):
        vm = self.make()
        vm.data.character_count = 2
        vm.set('TARGET', 0)
        var = Variable(name, (3,), character=True)
        vm.data.variables[name] = var
        return vm, var

    def test_explicit_first_index_effects_are_once_and_live(self):
        for name in ('CFLAG', 'TALENT'):
            with self.subTest(name=name):
                vm, var = self.make_character(name)
                vm.set('I', 0)
                node = parse(name + ':(I++):1')
                with patch.object(vm, 'eval_node', wraps=vm.eval_node) as evaluate:
                    actual, key = vm._resolve_ref(node)
                self.assertIs(actual, var)
                self.assertEqual(key, (0, 1))
                evaluate.assert_called_once_with(node[2][0])
                self.assertEqual(vm.get('I'), 1)
                self.assertEqual(vm._resolve_ref(node)[1], (1, 1))
                with self.assertRaises(EraError) as error:
                    vm._resolve_ref(node)
                self.assertEqual((error.exception.code, vm.get('I')),
                                 ('E_CHARACTER', 3))

    def test_character_count_is_checked_after_first_operand(self):
        vm, _ = self.make_character()
        node = parse('CFLAG:(I++):1')
        original = vm.eval_node

        def shrink(operand):
            value = original(operand)
            vm.data.character_count = 0
            return value

        with patch.object(vm, 'eval_node', side_effect=shrink):
            with self.assertRaises(EraError) as error:
                vm._resolve_ref(node)
        self.assertEqual((error.exception.code, error.exception.message),
                         ('E_CHARACTER', 'CFLAG: character index 0 outside 0..-1'))
        self.assertEqual(vm.get('I'), 1)

        def grow(operand):
            value = original(operand)
            vm.data.character_count = 2
            return value

        with patch.object(vm, 'eval_node', side_effect=grow):
            self.assertEqual(vm._resolve_ref(node)[1], (1, 1))
        self.assertEqual(vm.get('I'), 2)

    def test_variable_is_captured_before_effect_but_shape_validation_is_live(self):
        vm, old = self.make_character()
        node = parse('CFLAG:I:1')
        new = Variable('CFLAG', (0,), character=True, forbidden=True)

        def rebind(operand):
            self.assertEqual(operand, node[2][0])
            vm.data.variables['CFLAG'] = new
            return 0

        with patch.object(vm, 'eval_node', side_effect=rebind) as evaluate:
            actual, key = vm._resolve_ref(node)
        self.assertIs(actual, old)
        self.assertEqual(key, (0, 1))
        evaluate.assert_called_once_with(node[2][0])
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(node)
        self.assertEqual(error.exception.code, 'E_VARIABLE_FORBIDDEN')
        vm.data.variables['CFLAG'] = old

        def resize(operand):
            old.dims = (1,)
            vm.data.character_count = 0
            return 0

        with patch.object(vm, 'eval_node', side_effect=resize):
            with self.assertRaises(EraError) as error:
                vm._resolve_ref(node)
        with self.assertRaises(EraError) as expected:
            old.validate((0, 1))
        self.assertEqual(error.exception.as_dict(), expected.exception.as_dict())

    def test_descriptor_implicit_bypasses_target_but_explicit_keeps_character(self):
        vm, var = self.make_character()
        vm.data.character_count = 0
        vm.data.variables['TARGET'].forbidden = True
        with patch.object(vm, 'lookup', wraps=vm.lookup) as lookup:
            self.assertEqual(vm._resolve_ref(parse('CFLAG:1'), True),
                             (var, (0, 1)))
        self.assertEqual(lookup.call_args_list, [call('CFLAG')])
        self.assertEqual(vm._resolve_ref(parse('CFLAG:5:1'), True),
                         (var, (5, 1)))
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('CFLAG:5:1'))
        self.assertEqual(error.exception.code, 'E_CHARACTER')
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('CFLAG:999'))
        self.assertEqual(error.exception.code, 'E_VARIABLE_FORBIDDEN')
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('CFLAG:999'), True)
        with self.assertRaises(EraError) as expected:
            var.validate((0, 999))
        self.assertEqual(error.exception.as_dict(), expected.exception.as_dict())

    def test_implicit_literal_observes_target_and_character_count_each_time(self):
        vm, var = self.make_character('TALENT')
        node = parse('TALENT:1')
        vm.set('TARGET', 1)
        self.assertEqual(vm._resolve_ref(node), (var, (1, 1)))
        vm.set('TARGET', 0)
        self.assertEqual(vm._resolve_ref(node), (var, (0, 1)))
        vm.data.character_count = 0
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(node)
        self.assertEqual(error.exception.code, 'E_CHARACTER')

    def test_unknown_named_index_fallback_uses_original_axis(self):
        vm, _ = self.make_character()
        node = parse('CFLAG:UNKNOWN_INDEX:1')
        with patch.object(vm.data, 'index_of', return_value=1) as index_of:
            with patch.object(vm, 'eval_node', wraps=vm.eval_node) as evaluate:
                self.assertEqual(vm._resolve_ref(node)[1], (1, 1))
        evaluate.assert_called_once_with(node[2][0])
        index_of.assert_called_once_with('CFLAG', 'UNKNOWN_INDEX', 0)
        vm.set('TARGET', 0)
        # A nonliteral element index must remain on the general axis-1 path.
        with patch.object(vm.data, 'index_of', return_value=2) as index_of:
            self.assertEqual(vm._resolve_ref(parse('CFLAG:UNKNOWN_INDEX'))[1],
                             (0, 2))
        index_of.assert_called_once_with('CFLAG', 'UNKNOWN_INDEX', 1)

    def test_string_character_index_conversion_and_non_variable_errors(self):
        vm, _ = self.make_character()
        vm.set('STR', 'ROW')
        for text in ('CFLAG:STR:1', 'CFLAG:"ROW":1'):
            with self.subTest(text=text):
                with patch.object(vm.data, 'index_of', return_value=1) as index_of:
                    self.assertEqual(vm._resolve_ref(parse(text))[1], (1, 1))
                index_of.assert_called_once_with('CFLAG', 'ROW', 0)
        vm.data.variables['I'].forbidden = True
        with patch.object(vm.data, 'index_of') as index_of:
            with self.assertRaises(EraError) as error:
                vm._resolve_ref(parse('CFLAG:I:1'))
        self.assertEqual(error.exception.code, 'E_VARIABLE_FORBIDDEN')
        index_of.assert_not_called()
        with patch.object(vm.data, 'index_of', return_value=1.5):
            with self.assertRaises(EraError) as error:
                vm._resolve_ref(parse('CFLAG:"ROW":1'))
        self.assertEqual((error.exception.code, error.exception.message),
                         ('E_TYPE', 'Integer required, got float'))

    def test_invalid_indices_preserve_full_diagnostic_before_character_count(self):
        vm, var = self.make_character()
        vm.data.character_count = 0
        for text, key in (('CFLAG:0:99', (0, 99)),
                          ('CFLAG:99', (0, 99)),
                          ('CFLAG:0xFFFFFFFFFFFFFFFF:1', (-1, 1))):
            with self.subTest(text=text):
                with self.assertRaises(EraError) as error:
                    vm._resolve_ref(parse(text))
                with self.assertRaises(EraError) as expected:
                    var.validate(key)
                self.assertEqual(error.exception.as_dict(),
                                 expected.exception.as_dict())

    def test_invalid_literal_element_waits_for_first_index_effect_or_error(self):
        vm, var = self.make_character()
        vm.set('I', 0)
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('CFLAG:(I++):99'))
        self.assertEqual(vm.get('I'), 1)
        with self.assertRaises(EraError) as expected:
            var.validate((0, 99))
        self.assertEqual(error.exception.as_dict(), expected.exception.as_dict())
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('CFLAG:(1/0):99'))
        self.assertEqual(error.exception.code, 'E_ARITH')

    def test_arity_rank_and_ref_checks_precede_first_operand_effects(self):
        vm, var = self.make_character()
        vm.set('I', 0)
        for dims, text in (((3,), 'CFLAG:(I++):1:1'),
                           ((), 'CFLAG:(I++):1')):
            with self.subTest(dims=dims):
                var.dims = dims
                with self.assertRaises(EraError) as error:
                    vm._resolve_ref(parse(text))
                self.assertEqual((error.exception.code, error.exception.message),
                                 ('E_INDEX', 'CFLAG: too many array indices'))
                self.assertEqual(vm.get('I'), 0)
        var.dims = (3,)
        scope = {'CFLAG': Ref(var, (0, 0))}
        vm.frames.append(Frame(vm.program.functions['MAIN'][0], scope))
        with self.assertRaises(EraError) as error:
            vm._resolve_ref(parse('CFLAG:(I++):1'))
        self.assertEqual(error.exception.code, 'E_UNSUPPORTED')
        self.assertEqual(vm.get('I'), 0)
