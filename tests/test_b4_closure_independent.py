"""Current evaluator is the oracle; each backend owns independent VM state.

No Python code generation. Ordinary VM.eval is ERB evaluation, not Python eval.
Cold/warm repetitions are paired steps within one backend, never running two
backends against the same VM. Ready to copy into the parent's tests directory.
"""
from contextlib import ExitStack
import gc
import os
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from pyemuera import expr, runtime, closure_evaluator
from pyemuera.closure_evaluator import ClosurePlans
from pyemuera.data import Variable, Ref
from pyemuera.errors import EraError, Location
from pyemuera.random1824 import EngineRandom
from pyemuera.runtime import VM
from test_core import Harness
from construction_fixture import construct_vm


COMPARISONS = 0


def lit(value): return ('lit', value)
def var(name): return ('var', name, ())
def binary(op, left, right): return ('binary', op, left, right)


class TraceConsole:
    def __init__(self, events):
        self.events = events
        self.output = []
        self.line_count = 0
    def write(self, text, newline=False, **kwargs):
        self.output.append((text, newline))
        self.events.append(('output', text, newline))
    def warning(self, key, message):
        self.events.append(('warning', key, message))


def independent_vm(backend):
    """Actual VM lookup/ref/read/set methods; no disk or gameplay involved."""
    vm = construct_vm(VM, backend)
    events = []
    variables = {name: Variable(name, (4,)) for name in ('A', 'B', 'I', 'ARR', 'TARGET')}
    variables['A'].set((0,), 7)
    variables['B'].set((0,), 3)
    variables['I'].set((0,), 1)
    variables['ARR'].set((1,), 11)
    variables['CFLAG'] = Variable('CFLAG', (2,), character=True)
    variables['CFLAG'].set((0, 1), 19)
    variables['CFLAG'].set((1, 1), 29)
    variables['STR'] = Variable('STR', (4,), string=True)
    vm.data = SimpleNamespace(variables=variables, character_count=2, config={},
                              index_of=lambda name, word, axis=0: 1)
    vm.frames = []
    vm.active_init = {}
    vm.static = {}
    vm.legacy = {}
    vm.initializing_declarations = False
    vm.location = Location('neutral.ERB', 17)
    vm.program = SimpleNamespace(debug=False, expand=lambda text: text)
    vm._expression_cache = {}
    vm._assignment_cache = {}
    vm._loop_cache = {}
    vm._closure_plans = None
    vm.rng = EngineRandom(12345)
    vm.console = TraceConsole(events)
    vm.events = events
    for variable in variables.values():
        variable.write_observer = lambda v, k, old, new: events.append(('write', v.name, k, old, new))
    original_read = vm.read_node
    def read(node):
        events.append(('read', node[1]))
        return original_read(node)
    vm.read_node = read
    return vm


def variable_state(variable):
    return (variable.name, variable.dims, variable.string, variable.character,
            variable.default, variable.readonly, variable.forbidden,
            tuple(sorted(variable.values.items())))


def state(vm):
    scopes = []
    for frame in vm.frames:
        scope = {}
        for name, value in frame.scope.items():
            if isinstance(value, Ref):
                scope[name] = ('ref', variable_state(value.variable), value.key)
            elif isinstance(value, Variable): scope[name] = variable_state(value)
            else: scope[name] = value
        scopes.append(scope)
    return {'variables': {n: variable_state(v) for n, v in sorted(vm.data.variables.items())},
            'character_count': vm.data.character_count, 'scopes': scopes,
            'rng': vm.rng.getstate(), 'output': tuple(vm.console.output),
            'location': (vm.location.path, vm.location.line) if vm.location else None}


def outcome(action):
    try:
        value = action()
        return {'kind': 'value', 'type': type(value).__module__ + '.' + type(value).__qualname__,
                'value': value}
    except EraError as error:
        return {'kind': 'error', 'type': type(error).__name__, 'error': error.as_dict()}
    except Exception as error:
        return {'kind': 'python', 'type': type(error).__name__, 'args': error.args,
                'message': str(error)}


class IndependentExpressions(unittest.TestCase):
    def paired(self, action, setup=None, backends=('legacy','closures')):
        global COMPARISONS
        old, new = (independent_vm(backend) for backend in backends)
        self.assertIsNot(old, new)
        for attribute in ('data', 'frames', 'rng', 'console', 'events'):
            self.assertIsNot(getattr(old, attribute), getattr(new, attribute))
        for name in old.data.variables:
            self.assertIsNot(old.data.variables[name], new.data.variables[name])
            self.assertIsNot(old.data.variables[name].values, new.data.variables[name].values)
        records = []
        for vm in (old, new):
            with ExitStack() as stack:
                if setup: setup(vm, stack)
                result = outcome(lambda: action(vm))
                records.append({'outcome': result, 'events': list(vm.events), 'state': state(vm)})
        COMPARISONS += 1
        self.assertEqual(records[0], records[1])
        return records[0]

    def test_all_binary_operators_signed_string_and_error_matrix(self):
        ops = ('+', '-', '*', '/', '%', '<<', '>>', '&', '|', '^', '==', '!=',
               '<', '>', '<=', '>=', '&&', '||', '!&', '!|', '^^')
        pairs = ((7, 3), (-7, 3), (1, 0), (-(1 << 63), -1), ((1 << 63) - 1, 1),
                 (1, 63), (True, 2), ('x', 'y'), ('ab', 3), (None, 1))
        for op in ops:
            for left, right in pairs:
                with self.subTest(op=op, left=left, right=right):
                    self.paired(lambda vm: vm.eval_node(binary(op, lit(left), lit(right))))

    def test_seeded_mixed_trees_have_independent_rng_and_state(self):
        rng = random.Random(260026)
        def tree(depth):
            if depth == 0 or rng.randrange(3) == 0:
                return var(rng.choice(('A', 'B', 'I'))) if rng.randrange(2) else lit(rng.choice((-1, 0, 1, 63)))
            return binary(rng.choice(('+', '-', '*', '/', '%', '==', '&&', '||')), tree(depth-1), tree(depth-1))
        for index in range(40):
            node = tree(3)
            with self.subTest(index=index): self.paired(lambda vm: vm.eval_node(node))

    def test_division_and_modulo_rhs_first_zero_blocks_lhs(self):
        for op in ('/', '%'):
            def setup(vm, stack): vm.set('A', 0); vm.events.clear()
            result = self.paired(lambda vm: vm.eval_node(binary(op, ('inc', var('A'), 1, True), lit(0))), setup)
            self.assertEqual(result['outcome']['error']['code'], 'E_ARITH')
            self.assertEqual(result['events'], [])

    def test_rhs_type_error_keeps_rhs_write_but_never_reads_lhs(self):
        def setup(vm, stack):
            def read(node):
                vm.events.append(('read', node[1]))
                if node[1] == 'RIGHT': vm.set('B', 8); return 'bad'
                raise AssertionError('LHS must be blocked')
            vm.read_node = read
        for op in ('/', '%'):
            result = self.paired(lambda vm: vm.eval_node(binary(op, var('LEFT'), var('RIGHT'))), setup)
            self.assertEqual(result['outcome']['error']['code'], 'E_TYPE')
            self.assertEqual([e for e in result['events'] if e[0]=='read'], [('read', 'RIGHT')])

    def test_apply_helper_lookup_order_for_normal_and_rhs_first_operators(self):
        for op in ('+', '/', '%', '&&', '||'):
            def setup(vm, stack):
                original = expr.apply_binary
                def helper(label):
                    def call(operator, a, b):
                        vm.events.append(('helper', label)); return original(operator, a, b)
                    return call
                stack.enter_context(patch.object(expr, 'apply_binary', helper('initial')))
                def read(node):
                    vm.events.append(('read', node[1]))
                    expr.apply_binary = helper(node[1])
                    return 6 if node[1]=='LEFT' else 2
                vm.read_node = read
            result = self.paired(lambda vm: vm.eval_node(binary(op, var('LEFT'), var('RIGHT'))), setup)
            expected = [('read','RIGHT'),('read','LEFT'),('helper','RIGHT')] if op in ('/','%') else [('read','LEFT'),('read','RIGHT'),('helper','LEFT')]
            if op == '||': expected = [('read','LEFT')]
            self.assertEqual(result['events'], expected)

    def test_short_circuit_and_ternary_never_touch_dead_errors_or_rng(self):
        bad = ('binary', '/', ('inc', var('A'), 1, True), lit(0))
        fixtures = [(binary('&&',lit(0),bad),0), (binary('||',lit(1),bad),1),
                    (binary('!&',lit(0),bad),1),(binary('!|',lit(1),bad),0),
                    (('ternary',lit(1),lit(19),bad),19),
                    (('ternary',lit(0),bad,lit(23)),23)]
        for node, expected in fixtures:
            result = self.paired(lambda vm: vm.eval_node(node))
            self.assertEqual(result['outcome']['value'], expected)
            self.assertEqual(result['events'], [])
        self.paired(lambda vm: vm.eval('0 && RAND:100'))
        self.paired(lambda vm: vm.eval('1 ? A++ # RAND:100'))

    def test_unary_minus_reads_twice_and_warning_precedes_second_read(self):
        for first in (7, -(1 << 63)):
            def setup(vm, stack):
                values = iter((first, 9))
                def read(node): vm.events.append(('read', 'A')); return next(values)
                vm.read_node = read
            result = self.paired(lambda vm: vm.eval_node(('unary','-',var('A'))), setup)
            self.assertEqual(result['outcome']['value'], -9)
            self.assertEqual(len([e for e in result['events'] if e[0]=='read']), 2)
            self.assertEqual([e[0] for e in result['events']], ['read','output','read'] if first==-(1<<63) else ['read','read'])

    def test_unary_integer_and_i64_helpers_are_fetched_at_current_times(self):
        def setup(vm, stack):
            old_integer, old_i64 = expr.integer, expr.i64
            def integer(label):
                def call(value): vm.events.append(('integer',label)); return old_integer(value)
                return call
            def wrap(label):
                def call(value): vm.events.append(('i64',label)); return old_i64(value)
                return call
            stack.enter_context(patch.object(expr,'integer',integer('I0')))
            stack.enter_context(patch.object(expr,'i64',wrap('W0')))
            count = [0]
            def read(node):
                count[0] += 1; vm.events.append(('read',count[0]))
                expr.integer=integer('I'+str(count[0])); expr.i64=wrap('W'+str(count[0]))
                return -(1<<63) if count[0]==1 else 7
            vm.read_node=read
        result=self.paired(lambda vm:vm.eval_node(('unary','-',var('A'))),setup)
        self.assertEqual([e for e in result['events'] if e[0] != 'output'],
                         [('read',1),('integer','I0'),('read',2),('integer','I1'),('i64','W1')])

    def test_ternary_evaluator_is_captured_before_condition_and_branch_root(self):
        def setup(vm, stack):
            original = expr.evaluate
            stack.enter_context(patch.object(expr,'evaluate',original))
            def changed(node, owner):
                vm.events.append(('replacement',node[0])); return 99
            def read(node):
                vm.events.append(('read',node[1])); expr.evaluate=changed; return 1
            vm.read_node=read
        result=self.paired(lambda vm:vm.eval_node(('ternary',var('C'),lit(7),lit(8))),setup, backends=('legacy','legacy'))
        self.assertEqual(result['outcome']['value'],7)
        self.assertEqual(result['events'],[('read','C')])
        nested=self.paired(lambda vm:vm.eval_node(('ternary',var('C'),binary('+',lit(1),lit(2)),lit(8))),setup, backends=('legacy','legacy'))
        self.assertEqual(nested['outcome']['value'],198)
        self.assertEqual(nested['events'],[('read','C'),('replacement','lit'),('replacement','lit')])

    def test_ternary_condition_truth_test_occurs_once(self):
        def setup(vm, stack):
            class Condition(int):
                def __bool__(self): vm.events.append(('bool',)); return True
            vm.read_node=lambda node:Condition(1)
        result=self.paired(lambda vm:vm.eval_node(('ternary',var('C'),lit(7),lit(8))),setup)
        self.assertEqual(result['outcome']['value'],7)
        self.assertEqual(result['events'],[('bool',)])

    def test_replaced_recursive_evaluator_after_left_preserves_rhs_hook(self):
        def setup(vm, stack):
            original=expr.evaluate; stack.enter_context(patch.object(expr,'evaluate',original))
            def changed(node, owner): vm.events.append(('recursive',node[1])); return 13
            def read(node): vm.events.append(('read',node[1])); expr.evaluate=changed; return 5
            vm.read_node=read
        result=self.paired(lambda vm:vm.eval_node(binary('+',var('LEFT'),var('RIGHT'))),setup, backends=('legacy','legacy'))
        self.assertEqual(result['outcome']['value'],18)
        self.assertEqual(result['events'],[('read','LEFT'),('recursive','RIGHT')])

    def test_runtime_alias_replacement_is_never_bypassed(self):
        def setup(vm, stack):
            def changed(node, owner): vm.events.append(('runtime',node[0],owner is vm)); return 71
            stack.enter_context(patch.object(runtime,'evaluate',changed))
        result=self.paired(lambda vm:vm.eval_node(binary('+',lit(1),lit(2))),setup, backends=('legacy','legacy'))
        self.assertEqual(result['outcome']['value'],71)
        self.assertEqual(result['events'],[('runtime','binary',True)])

    def test_prior_partial_write_and_original_error_identity_survive(self):
        for op in ('+', '/', '%'):
            def setup(vm, stack):
                failure=EraError('sentinel body',Location('host.ERB',42),'E_SENTINEL',diagnostic_message='exact diagnostic')
                vm.failure=failure
                def read(node):
                    vm.events.append(('read',node[1])); vm.set('A',11); raise failure
                vm.read_node=read
            def action(vm):
                try: return vm.eval_node(binary(op,var('LEFT'),var('RIGHT')))
                except EraError as error:
                    self.assertIs(error,vm.failure); raise
            result=self.paired(action,setup)
            self.assertEqual(result['outcome']['error']['line'],42)
            self.assertEqual(result['outcome']['error']['message'],'sentinel body')
            self.assertEqual(result['events'][0],('read','RIGHT' if op in ('/','%') else 'LEFT'))

    def test_warm_plans_keep_ref_rebinding_shape_forbidden_and_unbound_live(self):
        def setup(vm, stack):
            old,new=Variable('OLD',(2,),default=7),Variable('NEW',(2,),default=11)
            vm.frames=[SimpleNamespace(scope={'ALIAS':Ref(old,(0,))})]
            vm.new_binding=new
        def action(vm):
            node=binary('+',('var','ALIAS',(lit(1),)),lit(1)); steps=[]
            steps.append(outcome(lambda:vm.eval_node(node)))
            vm.frames[-1].scope['ALIAS']=Ref(vm.new_binding,(0,))
            steps.append(outcome(lambda:vm.eval_node(node)))
            vm.new_binding.dims=(1,);steps.append(outcome(lambda:vm.eval_node(node)))
            vm.new_binding.forbidden=True;steps.append(outcome(lambda:vm.eval_node(node)))
            vm.frames[-1].scope['ALIAS']=None;steps.append(outcome(lambda:vm.eval_node(node)))
            return steps
        result=self.paired(action,setup)
        records=result['outcome']['value']
        self.assertEqual([r.get('value') for r in records[:2]],[8,12])
        self.assertEqual([r['error']['code'] for r in records[2:]],['E_INDEX','E_VARIABLE_FORBIDDEN','E_REFERENCE'])

    def test_target_character_count_and_values_change_between_same_backend_steps(self):
        def action(vm):
            node=binary('+',('var','CFLAG',(lit(1),)),lit(1)); results=[]
            vm.set('TARGET',0);results.append(outcome(lambda:vm.eval_node(node)))
            vm.set('TARGET',1);results.append(outcome(lambda:vm.eval_node(node)))
            vm.data.character_count=1;results.append(outcome(lambda:vm.eval_node(node)))
            return results
        result=self.paired(action)
        self.assertEqual([r['value'] for r in result['outcome']['value'][:2]],[20,30])
        self.assertEqual(result['outcome']['value'][2]['error']['code'],'E_CHARACTER')

    def test_inc_rng_form_and_call_are_live_without_plan_value_capture(self):
        for text in ('A++ + A++','++A / ++B','A++ % ++B','RAND:100 + RAND:100','A:(I++)+1'):
            with self.subTest(text=text):
                self.paired(lambda vm:[vm.eval(text),vm.eval(text)])
        def setup(vm,stack):
            vm.format=lambda text:vm.events.append(('format',text)) or vm.get('A')
            def call(name,args):
                vm.events.append(('call',name));vm.set('A',vm.get('A')+1);return vm.get('A')
            vm.call_expr=call
        self.paired(lambda vm:[vm.eval_node(('form','CURRENT')),vm.eval_node(('call','TOUCH',())),vm.eval_node(('form','CURRENT'))],setup)

    def test_plan_construction_has_no_effects_or_eager_dead_branch_errors(self):
        vm=independent_vm('closures');before=state(vm);plans=ClosurePlans()
        dead=(('binary','/',lit(1),lit(0)),('unknown',),(),('var','NO_SUCH_VARIABLE',()))
        for bad in dead:
            node=('ternary',lit(1),lit(19),bad)
            plan=plans.plan(node)
            self.assertEqual(state(vm),before);self.assertEqual(vm.events,[])
            self.assertEqual(plan(vm,True),19)
        def setup(owner, stack): owner.initializing_declarations=True
        self.paired(lambda owner:owner.eval_node(('ternary',lit(1),lit(19),('inc',var('A'),1,True))), setup)

    def test_warm_root_terminals_keep_live_read_hook_and_reentrant_vm(self):
        def action(vm):
            node=var('A')
            first=vm.eval_node(node)
            original=vm.read_node
            def changed(current):
                vm.events.append(('new-read',current[1]))
                nested=vm.eval_node(binary('+',lit(2),lit(3)))
                return original(current)+nested
            vm.read_node=changed
            second=vm.eval_node(node)
            vm.set('A',20)
            third=vm.eval_node(node)
            return first,second,third
        result=self.paired(action)
        self.assertEqual(result['outcome']['value'],(7,12,25))

    def test_unsupported_and_malformed_nodes_keep_current_runtime_errors(self):
        for node in ((),('unknown',),('binary',),('lit',),['binary','+',lit(1),lit(2)],('unary','?',lit(1))):
            with self.subTest(node=node):self.paired(lambda vm:vm.eval_node(node))

    def test_increment_in_declaration_phase_fails_without_write(self):
        def setup(vm,stack):vm.initializing_declarations=True
        result=self.paired(lambda vm:vm.eval_node(('inc',var('A'),1,True)),setup)
        self.assertEqual(result['outcome']['error']['code'],'E_DECLARATION')
        self.assertEqual(result['events'],[])

    def test_identity_cache_is_bounded_and_keeps_no_vm(self):
        plans=ClosurePlans(capacity=3);first=lit(1000);equal=tuple(['lit',int('1000')])
        self.assertEqual(first,equal);self.assertIsNot(first,equal)
        plan=plans.plan(first);self.assertIs(plan,plans.plan(first));self.assertIsNot(plan,plans.plan(equal))
        for index in range(12):plans.plan(lit(index))
        self.assertLessEqual(len(plans.entries),3);self.assertGreater(plans.clears,0)
        vm=independent_vm('closures');reference=weakref.ref(vm)
        self.assertEqual(plan(vm,True),1000)
        del vm;gc.collect();self.assertIsNone(reference())


class IndependentInstructionBoundaries(Harness):
    def execute_pair(self, source, headers=''):
        records=[];owners=[]
        for backend in ('legacy','closures'):
            vm=self.make(source,headers=headers,expression_backend=backend);owners.append(vm)
            events=[]
            for variable in vm.data.variables.values():
                variable.write_observer=lambda v,k,old,new:events.append((v.name,k,old,new))
            result=outcome(lambda:vm.call('MAIN'))
            records.append({'outcome':result,'writes':list(events),
                            'values':{n:variable_state(v) for n,v in vm.data.variables.items()},
                            'rng':vm.rng.getstate(),'output':self.output.getvalue(),
                            'location':(vm.location.path,vm.location.line) if vm.location else None})
        self.assertIsNot(owners[0].program,owners[1].program)
        self.assertIsNot(owners[0].data,owners[1].data)
        self.assertIsNot(owners[0].rng,owners[1].rng)
        self.assertEqual(records[0],records[1])
        return records[0],owners

    def test_error_code_body_location_stack_and_prior_instruction_writes(self):
        record,owners=self.execute_pair('@MAIN\nA=7\nB=A++ / 0\nRETURN\n')
        error=record['outcome']['error']
        self.assertEqual((error['code'],error['file'],error['line']),('E_ARITH','ERB/Main.ERB',3))
        self.assertEqual(error['message'],'Division by zero')
        self.assertTrue(error['stack'])
        self.assertEqual([vm.get('A') for vm in owners],[7,7])
        self.assertEqual([vm.get('B') for vm in owners],[0,0])

    def test_multivalue_bounds_failure_keeps_prior_element_and_all_rhs_effects(self):
        record,owners=self.execute_pair('@MAIN\nA=5\nSMALL:1=A++,A++\nRETURN\n','#DIM SMALL,2')
        self.assertEqual(record['outcome']['error']['code'],'E_INDEX')
        self.assertEqual([vm.get('A') for vm in owners],[7,7])
        self.assertEqual([vm.get('SMALL:1') for vm in owners],[5,5])
        self.assertEqual([e[0] for e in record['writes']].count('A'),3)

    def test_formatted_output_side_effects_then_later_error_are_preserved(self):
        record,owners=self.execute_pair('@MAIN\nPRINTFORML {A++}\nB=RAND:100\nC=1/0\nRETURN\n')
        self.assertEqual(record['outcome']['error']['line'],4)
        self.assertEqual(record['output'],'0\n')
        self.assertEqual([vm.get('A') for vm in owners],[1,1])

    def test_actual_user_call_and_ref_rhs_then_destination_effects(self):
        source='@MAIN\nSTR:(A++) = {A++}\nCALL F\nRETURN\n@F\nB+=1\nRETURN B\n'
        record,owners=self.execute_pair(source)
        self.assertEqual(record['outcome']['kind'],'value')
        self.assertEqual([(vm.get('A'),vm.get('STR:1'),vm.get('B')) for vm in owners],[(2,'0',1),(2,'0',1)])

    def test_legacy_default_remains_when_environment_is_absent(self):
        with patch.dict(os.environ,{},clear=True):
            vm=self.make()
        self.assertEqual(vm.expression_backend,'legacy')


if __name__=='__main__':unittest.main()
