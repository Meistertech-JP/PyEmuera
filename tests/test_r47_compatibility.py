"""Raw Framework oracles: r46 extra pairs and correctly targeted r47 sorts."""
import gzip
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from pyemuera.collation_portable import PortableNLSBackend
from pyemuera.sort1824 import framework_list_order
import pyemuera.sort1824 as sort_module
from pyemuera.errors import EraError
from test_core import Harness

FIXTURE=Path(__file__).parent/'fixtures/r47'
def load(name):return json.loads(gzip.decompress((FIXTURE/name).read_bytes()))
def decode(h):return bytes.fromhex(h).decode('utf-16-le','surrogatepass')

class CollationR47(unittest.TestCase):
    def test_placeholder_shape_does_not_invent_boundary_order(self):
        backend=PortableNLSBackend()
        self.assertEqual(backend.compare('\u115f\u11a8','\u11a8'),0)

    def test_extra_5767_framework_pairs(self):
        oracle=load('extra_framework.json.gz')
        values=list(map(decode,oracle['inputs_utf16le_hex']))
        backend=PortableNLSBackend(cache_size=0)
        self.assertEqual(len(oracle['pairs']),5767)
        for l,r,expected in oracle['pairs']:
            with self.subTest(l=l,r=r):self.assertEqual(backend.compare(values[l],values[r]),expected)

    def test_ordinary_nul_is_weightless(self):
        backend=PortableNLSBackend()
        for text in ['abc','\u65e5\u672c','a\u11a8b','\u1113\u1113']:
            for pos in range(len(text)+1):
                self.assertEqual(backend.compare(text,text[:pos]+'\0'+text[pos:]),0)

    def test_nul_and_soft_hyphen_share_jamo_boundary(self):
        backend=PortableNLSBackend()
        for mark in ['\0','\0\0','\u00ad']:
            self.assertEqual(backend.compare('\u1113\u1162\0\u11ab','\u1113\u1162'+mark+'\u11ab'),0)

class SortTraceR47(unittest.TestCase):
    def test_correctly_targeted_framework_call_traces(self):
        oracle=load('sort_modern.json.gz')
        self.assertEqual(oracle['target_framework'],'.NETFramework,Version=v4.8')
        backend=PortableNLSBackend(cache_size=0)
        original=sort_module._intro_sort
        for plan,expected in zip(load('sort_plan.json.gz'),oracle['cases'],strict=True):
            calls=[]
            active=False
            def entry(items,compare,low,high,depth):
                nonlocal active
                if active:return original(items,compare,low,high,depth)
                def logged(l,r):
                    sign=(0 if l[1]==r[1] else -1) if plan['mode']=='contradiction' else compare(l,r)
                    calls.append({'call_index':len(calls),'left_original_row':l[1],
                                  'right_original_row':r[1],'comparison_sign':sign})
                    return sign
                active=True
                try:return original(items,logged,low,high,depth)
                finally:active=False
            comparer=(lambda a,b:(a>b)-(a<b)) if plan['mode']=='ordinal' else backend.compare
            with self.subTest(case=plan['name']), patch.object(sort_module,'_intro_sort',entry), patch('pyemuera.collation1824.compare_strings',comparer):
                if expected['exception']:
                    with self.assertRaises(EraError):framework_list_order(list(map(decode,plan['inputs_utf16le_hex'])),string=True)
                else:
                    self.assertEqual(framework_list_order(list(map(decode,plan['inputs_utf16le_hex'])),string=True),expected['order'])
                self.assertEqual(calls,expected['calls'])

class ArrayStateR47(Harness):
    def test_alias44_related_arrays_result_and_rng(self):
        plans=load('sort_plan.json.gz');cases=load('sort_modern.json.gz')['cases']
        backend=PortableNLSBackend(cache_size=0)
        for plan,expected in zip(plans[:2],cases[:2]):
            values=list(map(decode,plan['inputs_utf16le_hex']))
            vm=self.make(headers='#DIMS KEYS,44\n#DIM ROWS,44,2')
            for i,key in enumerate(values):
                vm.set(f'KEYS:{i}',key)
                vm.set(f'ROWS:{i}:0',i)
                vm.set(f'ROWS:{i}:1',1000+i)
            vm.set('RESULT',917);state=vm.rng.getstate()
            with patch('pyemuera.collation1824.compare_strings',backend.compare):
                self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'),1)
            self.assertEqual(vm.rng.getstate(),state)
            self.assertEqual(vm.get('RESULT'),917)
            self.assertEqual([vm.get(f'ROWS:{i}:0') for i in range(44)],expected['order'])
            self.assertEqual([vm.get(f'ROWS:{i}:1') for i in range(44)],[1000+i for i in expected['order']])
