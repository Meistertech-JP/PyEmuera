"""Constructor-selected experimental entry; no evaluator replacement polling.

Late runtime/expr evaluator replacement is supported by explicit legacy VMs.
Other helpers, variables, call/ref APIs and metadata remain live.
"""
from .closure_evaluator import ClosurePlans


def eval_node(self, node):
    if type(node) is tuple and node and type(node[0]) is str:
        kind = node[0]
        if kind == 'var' and len(node) == 3:
            return self.read_node(node)
        if kind == 'lit' and len(node) == 2:
            return node[1]
    plans = getattr(self, '_closure_plans', None)
    if plans is None:
        plans = self._closure_plans = ClosurePlans()
    return plans.plan(node)(self, True)
