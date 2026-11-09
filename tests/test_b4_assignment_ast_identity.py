"""Syntax identity reuse without skipping live restructure or reference work.

Adoptable into tests: normally tests installed pyemuera. External verify.py
selects the isolated candidate; frozen modules are optional differential data.
"""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera import assignment1824 as installed, expr, runtime
from construction_fixture import construct_vm
from pyemuera.data import Variable, Ref
from pyemuera.errors import EraError

HERE = Path(__file__).resolve().parent / 'fixtures/b4_assignment_identity'


def load_source(folder, name):
    path = HERE / folder / (name + '.py')
    spec = importlib.util.spec_from_file_location(
        'pyemuera._identity_' + folder + '_' + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TARGET, RT = installed, runtime
FROZEN = load_source('frozen', 'assignment1824')
FROZEN_RT = load_source('frozen', 'runtime')


def v(name):
    return ('var', name, ())


def fixture(rt=RT, backend='closures'):
    """Real assignment/evaluator methods, explicit small live binding adapter."""
    vm = construct_vm(rt.VM, backend, expected_entry_module=(
        None if rt is RT else 'pyemuera._identity_frozen_runtime'))
    vm.frames = []
    vm.program = SimpleNamespace(functions={})
    vm._closure_plans = None
    vm._assignment_cache = {}
    vm.events = []
    vm.roots = []
    vm.variables = {name: Variable(name) for name in ('A', 'B', 'C')}
    vm.variables['A'].set((0,), 10)
    vm.variables['B'].set((0,), 2)
    vm.variables['C'].set((0,), 1)
    syntax = {}
    def expression_node(text):
        if text not in syntax:
            syntax[text] = expr.parse(text)
        return syntax[text]
    vm.expression_node = expression_node
    def lookup(name):
        vm.events.append(('lookup', name))
        return vm.variables[name]
    vm.lookup = lookup
    def read(node):
        vm.events.append(('read', node[1]))
        return vm.variables[node[1]].get((0,))
    vm.read_node = read
    def ref(node):
        vm.events.append(('ref', node[1]))
        return Ref(vm.variables[node[1]], (0,))
    vm.ref_node = ref
    selected_eval_node = vm.eval_node
    def run(node):
        vm.roots.append(node)
        return selected_eval_node(node)
    vm.eval_node = run
    def call(name, args):
        vm.events.append(('call', name))
        if name == 'ABS':
            return abs(vm.eval_node(args[0]))
        raise AssertionError('Unexpected fixture call: ' + name)
    vm.call_expr = call
    vm.console = SimpleNamespace(write=lambda text, nl: vm.events.append(('warning', nl)))
    return vm


class AssignmentASTIdentity(unittest.TestCase):
    def assign(self, vm, text, module=TARGET, rt=RT):
        # Runtime's local import remains live; patch only this process's import
        # target while exercising the isolated candidate, never source files.
        with patch.object(installed, 'restructure', module.restructure):
            return rt.VM._assignment(vm, text)

    def test_nonfolded_recursive_shapes_retain_exact_root_every_query(self):
        vm = fixture()
        a, b = v('A'), v('B')
        roots = [('unary', '-', a), ('binary', '+', a, b),
                 ('ternary', a, b, ('lit', 0)), ('call', 'ABS', (a,)),
                 ('binary', '+', ('unary', '-', a), ('call', 'ABS', (b,)))]
        for node in roots:
            with self.subTest(node=node):
                vm.events.clear()
                self.assertIs(TARGET.restructure(node, vm), node)
                first = list(vm.events)
                self.assertTrue(first)
                self.assertIs(TARGET.restructure(node, vm), node)
                self.assertEqual(vm.events, first + first)
                self.assertFalse(any(e[0] == 'read' for e in vm.events))

    def test_equal_fresh_folded_child_replaces_parent_each_time(self):
        vm = fixture()
        vm.variables['B'].readonly = True
        node = ('binary', '+', v('A'), v('B'))
        first = TARGET.restructure(node, vm)
        second = TARGET.restructure(node, vm)
        self.assertIsNot(first, node)
        self.assertIsNot(first, second)
        self.assertEqual(first, second)
        self.assertEqual(vm.events.count(('read', 'B')), 2)
        vm.variables['B'].values[(0,)] = 9
        third = TARGET.restructure(node, vm)
        self.assertEqual(third[3], ('lit', 9))

    def test_constant_method_runs_fresh_and_function_shadowing_stays_live(self):
        vm = fixture()
        calls = []
        def call(name, args):
            calls.append((name, args))
            return len(calls)
        vm.call_expr = call
        node = ('binary', '+', v('A'), ('call', 'ABS', (('lit', -2),)))
        self.assertEqual(TARGET.restructure(node, vm)[3], ('lit', 1))
        self.assertEqual(TARGET.restructure(node, vm)[3], ('lit', 2))
        vm.program.functions['ABS'] = object()
        self.assertIs(TARGET.restructure(node, vm), node)
        self.assertEqual(len(calls), 2)

    def test_ref_binding_prevents_folding_and_rebinding_is_seen(self):
        vm = fixture()
        vm.variables['B'].readonly = True
        vm.frames = [SimpleNamespace(scope={'B': Ref(vm.variables['B'], (0,))})]
        node = ('binary', '+', v('A'), v('B'))
        self.assertIs(TARGET.restructure(node, vm), node)
        self.assertNotIn(('lookup', 'B'), vm.events)
        vm.frames[-1].scope.clear()
        self.assertEqual(TARGET.restructure(node, vm)[3], ('lit', 2))

    def test_readonly_bounds_and_metadata_rechecked(self):
        vm = fixture()
        vm.variables['B'].readonly = True
        node = ('binary', '+', v('A'), v('B'))
        self.assertEqual(TARGET.restructure(node, vm)[3], ('lit', 2))
        vm.variables['B'].dims = (0,)
        with self.assertRaises(EraError):
            TARGET.restructure(node, vm)
        vm.variables['B'].readonly = False
        self.assertIs(TARGET.restructure(node, vm), node)

    def test_custom_containers_and_noncanonical_shapes_keep_old_normalization(self):
        class Tuple(tuple):
            pass
        class Kind(str):
            pass
        vm = fixture()
        for node in (['unary', '-', v('A')], Tuple(('unary', '-', v('A'))),
                     ('unary', '-', v('A'), 'extra'),
                     (Kind('binary'), '+', v('A'), v('B')),
                     ('call', 'ABS', [v('A')])):
            with self.subTest(node=node):
                result = TARGET.restructure(node, vm)
                self.assertIsNot(result, node)
                self.assertIs(type(result), tuple)
                self.assertIs(type(result[0]), str)
                if node[0] == 'call':
                    self.assertIs(type(result[2]), tuple)

    def test_unchosen_constant_failure_is_still_eager(self):
        vm = fixture()
        bad = ('binary', '/', ('lit', 1), ('lit', 0))
        node = ('ternary', v('C'), ('lit', 7), bad)
        with self.assertRaises(EraError) as caught:
            TARGET.restructure(node, vm)
        self.assertEqual(caught.exception.code, 'E_ARITH')
        self.assertEqual(vm.events, [('lookup', 'C')])

    def test_compound_reuses_lowered_root_without_freezing_values(self):
        vm = fixture()
        for _ in range(3):
            self.assign(vm, 'A += B')
        self.assertEqual(vm.variables['A'].get((0,)), 16)
        self.assertIs(vm.roots[0], vm.roots[1])
        self.assertIs(vm.roots[1], vm.roots[2])
        self.assertEqual(vm.events.count(('lookup', 'B')), 3)
        self.assertEqual(vm.events.count(('read', 'A')), 3)
        self.assertEqual(vm.events.count(('ref', 'A')), 3)
        vm.variables['B'].set((0,), 5)
        self.assign(vm, 'A += B')
        self.assertEqual(vm.variables['A'].get((0,)), 21)
        self.assertIs(vm.roots[0], vm.roots[-1])

    def test_source_and_lhs_identity_replacement_invalidates_lowering(self):
        vm = fixture()
        self.assign(vm, 'A += B')
        first = vm.roots[-1]
        original = vm.expression_node
        vm.expression_node = lambda text: tuple(list(original(text)))
        self.assign(vm, 'A += B')
        second = vm.roots[-1]
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first[3], second[3])
        vm.expression_node = original
        plan = vm._assignment_cache['A += B']
        plan[1] = tuple(list(plan[1]))
        self.assign(vm, 'A += B')
        self.assertIs(vm.roots[-1][2], plan[1])
        self.assertIsNot(vm.roots[-1], second)

    def test_new_equal_folded_subtree_invalidates_root_and_metadata_is_live(self):
        vm = fixture()
        vm.variables['B'].readonly = True
        for _ in range(2):
            self.assign(vm, 'A += C + B')
        self.assertEqual(vm.variables['A'].get((0,)), 16)
        self.assertEqual(vm.roots[-1], vm.roots[-2])
        self.assertIsNot(vm.roots[-1], vm.roots[-2])
        vm.variables['B'].values[(0,)] = 8
        self.assign(vm, 'A += C + B')
        self.assertEqual(vm.variables['A'].get((0,)), 25)
        vm.variables['B'].readonly = False
        self.assign(vm, 'A += C + B')
        stable = vm.roots[-1]
        self.assign(vm, 'A += C + B')
        self.assertIs(vm.roots[-1], stable)

    def test_constant_add_retains_one_ref_and_fresh_readonly_value(self):
        vm = fixture()
        vm.variables['B'].readonly = True
        self.assign(vm, 'A += B')
        vm.variables['B'].values[(0,)] = 7
        self.assign(vm, 'A += B')
        self.assertEqual(vm.variables['A'].get((0,)), 19)
        self.assertEqual(vm.events.count(('ref', 'A')), 2)
        self.assertNotIn(('read', 'A'), vm.events)
        self.assertIsNone(vm._assignment_cache['A += B'][3])

    def test_failed_store_keeps_committed_state_and_observer_identity(self):
        vm = fixture()
        failure = RuntimeError('observer')
        def observer(*args):
            vm.events.append(('observer', vm.variables['A'].get((0,))))
            raise failure
        vm.variables['A'].write_observer = observer
        with self.assertRaises(RuntimeError) as caught:
            self.assign(vm, 'A += B')
        self.assertIs(caught.exception, failure)
        self.assertEqual(vm.variables['A'].get((0,)), 12)
        self.assertEqual(vm.events[-1], ('observer', 12))
        vm.variables['A'].write_observer = None
        root = vm.roots[-1]
        self.assign(vm, 'A += B')
        self.assertIs(vm.roots[-1], root)
        self.assertEqual(vm.variables['A'].get((0,)), 14)

    def test_unique_method_does_not_visit_descriptor_indices(self):
        vm = fixture()
        name = next(iter(TARGET.CONTRACTS['unique_methods']))
        descriptor = ('var', 'A', (('call', 'MUST_NOT_RUN', ()),))
        calls = []
        vm.call_expr = lambda name, args: calls.append((name, args)) or 6
        node = ('call', name, (descriptor, ('lit', 'keyword')))
        self.assertEqual(TARGET.restructure(node, vm), ('lit', 6))
        self.assertEqual(TARGET.restructure(node, vm), ('lit', 6))
        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0][1][0], descriptor)
        self.assertEqual(vm.events, [])

    def test_compound_index_is_reexecuted_for_read_and_write(self):
        outcomes = []
        pairs = [(TARGET, RT)]
        if FROZEN_RT is not None:
            pairs.insert(0, (FROZEN, FROZEN_RT))
        for module, rt in pairs:
            vm = fixture(rt)
            vm.variables['A'] = Variable('A', (2,))
            vm.variables['A'].set((0,), 10)
            vm.variables['A'].set((1,), 3)
            indices = []
            def call(name, args):
                self.assertEqual(name, 'NEXT')
                value = len(indices) % 2
                indices.append(value)
                vm.events.append(('index', value))
                return value
            vm.call_expr = call
            def key(node):
                return tuple(vm.eval_node(x) for x in node[2]) or (0,)
            def read(node):
                vm.events.append(('read', node[1]))
                return vm.variables[node[1]].get(key(node))
            def ref(node):
                vm.events.append(('ref', node[1]))
                return Ref(vm.variables[node[1]], key(node))
            vm.read_node, vm.ref_node = read, ref
            for _ in range(2):
                self.assign(vm, 'A:NEXT() *= B', module, rt)
            self.assertEqual(indices, [0, 1, 0, 1])
            self.assertEqual(vm.variables['A'].values, {(0,): 10, (1,): 20})
            if module is TARGET:
                # Ignore index/call roots: find the two lowered binary roots.
                roots = [node for node in vm.roots if node[0] == 'binary']
                self.assertIs(roots[0], roots[1])
            outcomes.append((indices, vm.events, vm.variables['A'].values))
        if len(outcomes) == 2:
            self.assertEqual(*outcomes)

    def test_compound_global_evaluator_hook_receives_actual_stable_root(self):
        vm = fixture(backend='legacy')
        roots = []
        base = expr._BASE_EVALUATE
        def hook(node, machine):
            roots.append(node)
            return base(node, machine)
        with patch.object(RT, 'evaluate', hook):
            self.assign(vm, 'A *= B')
            self.assign(vm, 'A *= B')
        self.assertEqual(vm.variables['A'].get((0,)), 40)
        self.assertEqual(len(roots), 2)
        self.assertIs(roots[0], roots[1])

    def test_frozen_restructure_order_values_warnings_and_errors(self):
        nodes = [expr.parse(text) for text in (
            '-A', 'A+B', 'A ? B # C', 'ABS(A)', 'A+ABS(-2)',
            'A ? 7 # (1/0)', 'A+(1/0)')]
        nodes.append(('unary', '-', ('lit', -(1 << 63))))
        for node in nodes:
            outcomes = []
            for module in (FROZEN, TARGET):
                vm = fixture()
                try:
                    value = module.restructure(node, vm)
                    result = ('value', value)
                except EraError as error:
                    result = ('error', error.code, str(error))
                outcomes.append((result, vm.events))
            with self.subTest(node=node):
                self.assertEqual(*outcomes)

    def test_frozen_compound_differential_fresh_state_both_backends(self):
        for backend in ('legacy', 'closures'):
            for text in ('A += B', 'A -= B', 'A *= B', 'A /= B',
                         'A %= B', 'A += C+B', 'A += 3'):
                for mode in ('mutable', 'readonly-source', 'zero-rhs',
                             'readonly-destination', 'rebound-source'):
                    outcomes = []
                    for module, rt in ((FROZEN, FROZEN_RT), (TARGET, RT)):
                        vm = fixture(rt, backend)
                        results = []
                        for turn in range(3):
                            if mode == 'readonly-source':
                                vm.variables['B'].readonly = True
                            elif mode == 'zero-rhs':
                                vm.variables['B'].values[(0,)] = 0
                            elif mode == 'readonly-destination' and turn == 1:
                                vm.variables['A'].readonly = True
                            elif mode == 'rebound-source' and turn:
                                vm.variables['B'] = Variable('B', default=7)
                            try:
                                self.assign(vm, text, module, rt)
                                results.append('ok')
                            except EraError as error:
                                results.append((error.code, str(error)))
                        outcomes.append((results, list(vm.events),
                                         vm.variables['A'].get((0,))))
                    with self.subTest(backend=backend, text=text, mode=mode):
                        self.assertEqual(*outcomes)


if __name__ == '__main__':
    unittest.main()
