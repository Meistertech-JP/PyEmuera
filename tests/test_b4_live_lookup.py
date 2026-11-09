"""Live binding and error contracts for the installed VM.lookup implementation.

The method-only fixture avoids game loading and filesystem access. Expectations
are explicit semantic assertions and do not depend on a lookup implementation,
proposal module, cache layout, or dictionary probe count.
"""
from types import SimpleNamespace
import unittest

from pyemuera.data import Ref, Variable
from pyemuera.errors import EraError
from pyemuera.runtime import VM


class LiveLookup(unittest.TestCase):
    def setUp(self):
        self.vm = VM.__new__(VM)
        self.vm.active_init = {}
        self.vm.frames = []
        self.vm.data = SimpleNamespace(variables={})
        self.vm.legacy = {}

    def assert_lookup_error(self, name, code, message):
        with self.assertRaises(EraError) as caught:
            self.vm.lookup(name)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.message, message)

    def test_live_binding_precedence_and_replacements(self):
        global_var = Variable('A')
        scope_var = Variable('A')
        init_var = Variable('A')
        self.vm.data.variables['A'] = global_var
        scope = {'A': scope_var}
        self.vm.frames.append(SimpleNamespace(scope=scope))
        self.vm.active_init['A'] = init_var
        self.assertIs(self.vm.lookup('a'), init_var)

        replacement = Variable('A')
        self.vm.active_init['A'] = replacement
        self.assertIs(self.vm.lookup('a'), replacement)
        del self.vm.active_init['A']
        self.assertIs(self.vm.lookup('a'), scope_var)
        scope['A'] = replacement
        self.assertIs(self.vm.lookup('a'), replacement)
        del scope['A']
        self.assertIs(self.vm.lookup('a'), global_var)
        self.vm.data.variables['A'] = replacement
        self.assertIs(self.vm.lookup('a'), replacement)
        del self.vm.data.variables['A']
        self.assert_lookup_error('a', 'E_VARIABLE', 'Unknown variable A')

    def test_only_current_frame_is_searched_and_frame_changes_are_live(self):
        global_var, caller_var, callee_var = (Variable('A') for _ in range(3))
        self.vm.data.variables['A'] = global_var
        self.vm.frames.append(SimpleNamespace(scope={'A': caller_var}))
        self.assertIs(self.vm.lookup('A'), caller_var)
        self.vm.frames.append(SimpleNamespace(scope={}))
        self.assertIs(self.vm.lookup('A'), global_var)
        self.vm.frames[-1].scope = {'A': callee_var}
        self.assertIs(self.vm.lookup('A'), callee_var)
        self.vm.frames.pop()
        self.assertIs(self.vm.lookup('A'), caller_var)
        self.vm.frames.clear()
        self.assertIs(self.vm.lookup('A'), global_var)

    def test_active_init_none_shadows_unbound_scope_and_forbidden_global(self):
        self.vm.data.variables['A'] = Variable('A', forbidden=True)
        self.vm.frames.append(SimpleNamespace(scope={'A': None}))
        self.vm.active_init['A'] = None
        self.assertIsNone(self.vm.lookup('a'))
        del self.vm.active_init['A']
        self.assert_lookup_error('a', 'E_REFERENCE', 'Unbound REF variable A')
        self.vm.frames.clear()
        self.assert_lookup_error(
            'a', 'E_VARIABLE_FORBIDDEN', 'Variable A is disabled by VariableSize.csv'
        )

    def test_scope_none_does_not_fall_back_to_valid_global(self):
        self.vm.data.variables['A'] = Variable('A')
        scope = {'A': None}
        self.vm.frames.append(SimpleNamespace(scope=scope))
        self.assert_lookup_error('a', 'E_REFERENCE', 'Unbound REF variable A')
        rebound = Variable('DEST')
        scope['A'] = Ref(rebound, (0,))
        self.assertIs(self.vm.lookup('A'), rebound)
        scope['A'] = None
        self.assert_lookup_error('a', 'E_REFERENCE', 'Unbound REF variable A')

    def test_ref_rebinding_returns_current_underlying_variable(self):
        old, new = Variable('OLD'), Variable('NEW')
        alias = Ref(old, (0,))
        scope = {'ALIAS': alias}
        self.vm.frames.append(SimpleNamespace(scope=scope))
        self.assertIs(self.vm.lookup('alias'), old)
        scope['ALIAS'] = Ref(new, (0,))
        self.assertIs(self.vm.lookup('alias'), new)
        scope['ALIAS'].variable = old
        self.assertIs(self.vm.lookup('alias'), old)
        old.forbidden = True
        self.assert_lookup_error(
            'alias', 'E_VARIABLE_FORBIDDEN', 'ALIAS is disabled by VariableSize.csv'
        )
        old.forbidden = False
        self.assertIs(self.vm.lookup('alias'), old)

    def test_forbidden_initializer_blocks_valid_scope_and_global(self):
        blocked = Variable('A', forbidden=True)
        scope_var = Variable('A')
        self.vm.active_init['A'] = blocked
        self.vm.frames.append(SimpleNamespace(scope={'A': scope_var}))
        self.vm.data.variables['A'] = Variable('A')
        self.assert_lookup_error(
            'a', 'E_VARIABLE_FORBIDDEN', 'A is disabled by VariableSize.csv'
        )
        blocked.forbidden = False
        self.assertIs(self.vm.lookup('a'), blocked)
        del self.vm.active_init['A']
        self.assertIs(self.vm.lookup('a'), scope_var)

    def test_forbidden_scope_blocks_global_but_initializer_can_shadow_it(self):
        blocked = Variable('A', forbidden=True)
        self.vm.frames.append(SimpleNamespace(scope={'A': blocked}))
        self.vm.data.variables['A'] = Variable('A')
        self.assert_lookup_error(
            'a', 'E_VARIABLE_FORBIDDEN', 'A is disabled by VariableSize.csv'
        )
        init_var = Variable('A')
        self.vm.active_init['A'] = init_var
        self.assertIs(self.vm.lookup('a'), init_var)
        del self.vm.active_init['A']
        blocked.forbidden = False
        self.assertIs(self.vm.lookup('a'), blocked)

    def test_global_forbidden_flag_and_error_message_are_live(self):
        var = Variable('A')
        self.vm.data.variables['A'] = var
        self.assertIs(self.vm.lookup('a'), var)
        var.forbidden = True
        self.assert_lookup_error(
            'a', 'E_VARIABLE_FORBIDDEN', 'Variable A is disabled by VariableSize.csv'
        )
        var.forbidden = False
        self.assertIs(self.vm.lookup('a'), var)

    def test_all_qualified_legacy_names_normalize_and_rebind(self):
        for base in ('LOCAL', 'LOCALS', 'ARG', 'ARGS'):
            with self.subTest(base=base):
                old, new = Variable(base), Variable(base)
                self.vm.legacy = {'FUNC': {base: old}}
                name = base.lower() + '@func'
                self.assertIs(self.vm.lookup(name), old)
                self.vm.legacy['FUNC'][base] = new
                self.assertIs(self.vm.lookup(name), new)
                self.vm.legacy['FUNC'] = {base: old}
                self.assertIs(self.vm.lookup(name), old)

    def test_qualified_lookup_bypasses_initializer_scope_and_global(self):
        qualified = Variable('LOCAL')
        self.vm.legacy['FUNC'] = {'LOCAL': qualified}
        self.vm.active_init['LOCAL@FUNC'] = None
        self.vm.frames.append(SimpleNamespace(scope={'LOCAL@FUNC': None}))
        self.vm.data.variables['LOCAL@FUNC'] = Variable('LOCAL', forbidden=True)
        self.assertIs(self.vm.lookup('local@func'), qualified)

    def test_qualified_forbidden_message_uses_normalized_requested_name(self):
        var = Variable('LOCAL')
        self.vm.legacy['FUNC'] = {'LOCAL': var}
        self.assertIs(self.vm.lookup('local@func'), var)
        var.forbidden = True
        self.assert_lookup_error(
            'local@func', 'E_VARIABLE_FORBIDDEN',
            'LOCAL@FUNC is disabled by VariableSize.csv',
        )
        var.forbidden = False
        self.assertIs(self.vm.lookup('local@func'), var)

    def test_unknown_qualified_function_and_unsupported_base_errors(self):
        self.assert_lookup_error(
            'local@missing', 'E_VARIABLE', 'Unknown qualified function @MISSING'
        )
        self.assert_lookup_error(
            'a@missing', 'E_UNSUPPORTED',
            'Qualified private variables other than LOCAL/LOCALS/ARG/ARGS',
        )
        self.vm.legacy['FUNC'] = {'LOCAL': Variable('LOCAL')}
        self.assert_lookup_error(
            'a@func', 'E_UNSUPPORTED',
            'Qualified private variables other than LOCAL/LOCALS/ARG/ARGS',
        )

    def test_unicode_name_and_missing_name_error(self):
        var = Variable('日本語')
        self.vm.data.variables['日本語'] = var
        self.assertIs(self.vm.lookup('日本語'), var)
        self.assert_lookup_error(
            'missing', 'E_VARIABLE', 'Unknown variable MISSING'
        )


if __name__ == '__main__':
    unittest.main()
