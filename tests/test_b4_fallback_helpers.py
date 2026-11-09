"""Unchanged standalone independent fallback regressions;46 expectations."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from pyemuera import expr
from pyemuera.closure_evaluator import ClosurePlans
from pyemuera.data import Variable, Ref
from pyemuera.errors import EraError
RECORDS=[]

class FallbackHelpers(unittest.TestCase):
    def test_fallback_inc_retains_expr_getattr_binding(self):
        events=[]
        variable=Variable('A',(4,))
        def ref(node):
            events.append(('ref',node[1]))
            return Ref(variable,(0,))
        vm=SimpleNamespace(initializing_declarations=False,ref_node=ref)
        def custom_getattr(obj,name,default):
            events.append(('expr.getattr',name))
            return True
        error=result=None
        with patch.object(expr,'getattr',custom_getattr,create=True):
            try:
                result=ClosurePlans().plan(['inc',('var','A',()),1,False])(vm,True)
            except EraError as caught:
                error=caught
        RECORDS.append({'case':'fallback-expr-getattr','result':result,
                        'error':error.code if error else None,'events':events,
                        'storage':[(repr(k),v) for k,v in variable.values.items()]})
        self.assertIsInstance(error,EraError)
        self.assertEqual(error.code,'E_DECLARATION')
        self.assertEqual(variable.values,{})
        self.assertEqual(events,[('expr.getattr','initializing_declarations')])

    def test_fallback_unary_retains_expr_int_binding(self):
        events=[]
        def integer(value):
            events.append(('integer',value))
            return value
        def custom_int(value):
            events.append(('expr.int',value))
            return 77
        with patch.object(expr,'integer',integer),patch.object(expr,'int',custom_int,create=True):
            result=ClosurePlans().plan(['unary','!',('lit',0)])(SimpleNamespace(),True)
        RECORDS.append({'case':'fallback-expr-int','result':result,'events':events})
        self.assertEqual(result,77)
        self.assertEqual(events,[('integer',0),('expr.int',True)])

if __name__=='__main__': unittest.main()
