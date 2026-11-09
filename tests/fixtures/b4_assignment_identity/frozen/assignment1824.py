"""SP_SET constant-add routing, derived from v24 Restructure contracts.

Never use a runtime result to classify a mutable expression as SingleTerm.
This helper folds only source-certified constant nodes; scopes are resolved
afresh, so same-text statements in different functions cannot share values.
"""

import json
from importlib.resources import files
from .expr import apply_binary, integer
from .errors import EraError
from .data import Ref

CONTRACTS = json.loads(
    files('pyemuera')
    .joinpath('specs/assignment_constant_methods.json')
    .read_text(encoding='utf-8')
)
CONSTANT_METHODS = frozenset(CONTRACTS['eligible_methods'])


def restructure(node, vm):
    kind = node[0]
    if kind == 'lit':
        return node
    if kind == 'var':
        if node[1] in ('__INT_MAX__', '__INT_MIN__') and not node[2]:
            return ('lit', vm.read_node(node))
        # ReferenceToken.CanRestructure=false, even if a binding points at
        # immutable storage. Do not turn a runtime REF binding into a constant.
        if vm.frames and isinstance(vm.frames[-1].scope.get(node[1]), Ref):
            return node
        try:
            var = vm.lookup(node[1])
        except EraError:
            # RAND and virtual variables are handled by read_node, not lookup.
            # An unbound/missing variable is also NOT a constant: defer its
            # failure to evaluation of the binary source, after any LHS read.
            return node
        if not var.readonly or var.character:
            return node
        indices = tuple(restructure(x, vm) for x in node[2])
        if all(x[0] == 'lit' for x in indices):
            return ('lit', vm.read_node(('var', node[1], indices)))
        return node
    if kind == 'unary':
        child = restructure(node[2], vm)
        if child[0] != 'lit':
            return ('unary', node[1], child)
        # Preserve existing v24 unary-minus MinValue warning semantics.
        return ('lit', vm.eval_node(('unary', node[1], child)))
    if kind == 'binary':
        left = restructure(node[2], vm)
        right = restructure(node[3], vm)
        if left[0] == right[0] == 'lit':
            return ('lit', apply_binary(node[1], left[1], right[1]))
        return ('binary', node[1], left, right)
    if kind == 'ternary':
        children = tuple(restructure(x, vm) for x in node[1:])
        if all(x[0] == 'lit' for x in children):
            return children[1] if integer(children[0][1]) else children[2]
        return ('ternary',) + children
    if (
        kind == 'call'
        and node[1] not in vm.program.functions
        and node[1] in CONTRACTS['unique_methods']
    ):
        # GetnumMethod.UniqueRestructure folds only its keyword. The first
        # argument is a descriptor; its dynamic indices must never be read.
        if len(node[2]) == 2 and node[2][0][0] == 'var':
            keyword = restructure(node[2][1], vm)
            if keyword[0] == 'lit':
                return ('lit', vm.call_expr(node[1], (node[2][0], keyword)))
        return node
    if (
        kind == 'call'
        and node[1] in CONSTANT_METHODS
        and node[1] not in vm.program.functions
    ):
        args = tuple(restructure(x, vm) for x in node[2])
        if all(x[0] in ('lit', 'missing') for x in args):
            return ('lit', vm.call_expr(node[1], args))
        return ('call', node[1], args)
    return node
