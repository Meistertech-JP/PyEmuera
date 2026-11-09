"""Opt-in expression plans made of ordinary nested Python closures.

Only AST structure is retained. Operands, references, helpers and VM bindings
remain live. Unsupported/malformed structures delegate when executed, rather
than raising during plan construction. No Python code generation is used.
"""

from . import expr as source

REFERENCE = source._BASE_EVALUATE
_NODE_SIZES = {'lit': 2, 'form': 2, 'missing': 1, 'var': 3,
               'inc': 4, 'call': 3, 'ternary': 4, 'unary': 3, 'binary': 4}


def _fallback(node):
    def run(vm, root=False):
        return _evaluate_fallback(node, vm)
    return run


class ClosurePlans:
    """Bounded identity table; strong references prevent reuse of live IDs."""

    def __init__(self, capacity=8192):
        if capacity < 1:
            raise ValueError('Closure plan capacity must be positive')
        self.capacity = capacity
        self.entries = {}
        self.hits = self.misses = self.clears = 0

    def plan(self, node, depth=0):
        key = id(node)
        row = self.entries.get(key)
        if row is not None and row[0] is node:
            self.hits += 1
            return row[1]
        self.misses += 1
        if depth > 64:
            result = _fallback(node)
        else:
            result = self._build(node, depth)
        if len(self.entries) >= self.capacity:
            self.entries.clear()
            self.clears += 1
        self.entries[key] = (node, result)
        return result

    def stats(self):
        return dict(hits=self.hits, misses=self.misses, clears=self.clears,
                    entries=len(self.entries), capacity=self.capacity)

    def _build(self, node, depth):
        if type(node) is not tuple or not node or type(node[0]) is not str:
            return _fallback(node)
        kind = node[0]
        if _NODE_SIZES.get(kind) != len(node):
            return _fallback(node)

        if kind == 'lit':
            def run(vm, root=False):
                return node[1]
            return run
        if kind == 'missing':
            def run(vm, root=False):
                return None
            return run
        if kind == 'form':
            def run(vm, root=False):
                return vm.format(node[1])
            return run
        if kind == 'var':
            def run(vm, root=False):
                return vm.read_node(node)
            return run
        if kind == 'call':
            def run(vm, root=False):
                return vm.call_expr(node[1], node[2])
            return run
        if kind == 'inc':
            def run(vm, root=False):
                if getattr(vm, 'initializing_declarations', False):
                    raise source.EraError(
                        'Increment is not a constant initializer', code='E_DECLARATION')
                _, target, delta, postfix = node
                ref = vm.ref_node(target)
                old = source.integer(ref.get())
                new = source.i64(old + delta)
                ref.set(new)
                return old if postfix else new
            return run
        if kind == 'ternary':
            condition = self.plan(node[1], depth + 1)
            yes = self.plan(node[2], depth + 1)
            no = self.plan(node[3], depth + 1)
            def run(vm, root=False):
                # Evaluator policy is fixed at VM construction; arithmetic
                # helper fetch order and single truth test remain unchanged.
                choose_yes = source.integer(condition(vm))
                if choose_yes:
                    selected, selected_plan = node[2], yes
                else:
                    selected, selected_plan = node[3], no
                return selected_plan(vm, True)
            return run
        if kind == 'unary':
            if type(node[1]) is not str:
                return _fallback(node)
            operand = self.plan(node[2], depth + 1)
            op = node[1]
            def run(vm, root=False):
                value = source.integer(operand(vm))
                if op == '+':
                    return value
                if op == '-':
                    if value == -(1 << 63):
                        vm.console.write(
                            '整数型最小値(-9223372036854775808)は-を取っても値は変化しません', True)
                    return source.i64(-source.integer(operand(vm)))
                if op == '!':
                    return int(not value)
                return source.i64(~value)
            return run

        if type(node[1]) is not str:
            return _fallback(node)
        op = node[1]
        left = self.plan(node[2], depth + 1)
        right = self.plan(node[3], depth + 1)
        if op in ('/', '%'):
            def run(vm, root=False):
                value = source.integer(right(vm))
                if value == 0:
                    raise source.EraError('Division by zero', code='E_ARITH')
                return source.apply_binary(op, left(vm), value)
            return run
        if op in ('&&', '!&'):
            def run(vm, root=False):
                value = left(vm)
                if source.integer(value) == 0:
                    return int(op == '!&')
                return source.apply_binary(op, value, right(vm))
            return run
        if op in ('||', '!|'):
            def run(vm, root=False):
                value = left(vm)
                if source.integer(value) != 0:
                    return int(op == '||')
                return source.apply_binary(op, value, right(vm))
            return run
        def run(vm, root=False):
            value = left(vm)
            return source.apply_binary(op, value, right(vm))
        return run

_MISSING = object()


def _live_helper(name):
    value = REFERENCE.__globals__.get(name, _MISSING)
    if value is _MISSING:
        value = REFERENCE.__builtins__.get(name, _MISSING)
        if value is _MISSING:
            raise NameError(f"name '{name}' is not defined", name=name)
    return value


# Fixed-recursion rare fallback, derived from the unchanged46 evaluator.
def _evaluate_fallback(node, vm):
    kind = node[0]
    if kind == 'lit':
        return node[1]
    if kind == 'form':
        return vm.format(node[1])
    if kind == 'missing':
        return None
    if kind == 'var':
        return vm.read_node(node)
    if kind == 'inc':
        if _live_helper('getattr')(vm, 'initializing_declarations', False):
            raise _live_helper('EraError')('Increment is not a constant initializer', code='E_DECLARATION')
        increment: IncrementNode = node
        _, target, delta, postfix = increment
        ref = vm.ref_node(target)
        old = _live_helper('integer')(ref.get())
        new = _live_helper('i64')(old + delta)
        ref.set(new)
        return old if postfix else new
    if kind == 'call':
        return vm.call_expr(node[1], node[2])
    if kind == 'ternary':
        return _evaluate_fallback(node[2] if _live_helper('integer')(_evaluate_fallback(node[1], vm)) else node[3], vm)
    if kind == 'unary':
        val = _live_helper('integer')(_evaluate_fallback(node[2], vm))
        op = node[1]
        if op == '+':
            return val
        if op == '-':
            if val == -(1 << 63):
                vm.console.write('整数型最小値(-9223372036854775808)は-を取っても値は変化しません', True)
            return _live_helper('i64')(-_live_helper('integer')(_evaluate_fallback(node[2], vm)))
        if op == '!':
            return _live_helper('int')(not val)
        return _live_helper('i64')(~val)
    if kind == 'binary':
        if node[1] in ('/', '%'):
            right = _live_helper('integer')(_evaluate_fallback(node[3], vm))
            if right == 0:
                raise _live_helper('EraError')('Division by zero', code='E_ARITH')
            return _live_helper('apply_binary')(node[1], _evaluate_fallback(node[2], vm), right)
        op, a = (node[1], _evaluate_fallback(node[2], vm))
        if op in ('&&', '!&') and _live_helper('integer')(a) == 0:
            return _live_helper('int')(op == '!&')
        if op in ('||', '!|') and _live_helper('integer')(a) != 0:
            return _live_helper('int')(op == '||')
        return _live_helper('apply_binary')(op, a, _evaluate_fallback(node[3], vm))
    raise _live_helper('EraError')(f'Invalid AST node: {kind}')
