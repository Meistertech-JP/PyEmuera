"""Guard live binding/error boundaries and immutable UTF-16 width caching."""
import unittest
from test_core import Harness
from pyemuera import substring_utf16 as sub
from pyemuera.data import Variable, Ref
from pyemuera.errors import EraError
from pyemuera.expr import parse


class WidthCache(unittest.TestCase):
    def test_every_utf16_unit_matches_cp932_codec(self):
        for unit in range(65536):
            self.assertEqual(sub._cached_unit_width(unit),
                             len(chr(unit).encode('cp932', errors='replace')))
        self.assertLessEqual(sub._cached_unit_width.cache_info().currsize, 65536)

    def test_cache_does_not_merge_caller_type_errors(self):
        self.assertEqual(sub.unit_width(65),1)
        with self.assertRaises(TypeError):
            sub.unit_width(65.0)
        with self.assertRaises(ValueError):
            sub.unit_width(-1)

    def test_surrogate_replacement_width_and_split_are_units(self):
        # U+1F600 occupies two independently replaced UTF-16 units in v24.
        self.assertEqual(sub.substring('A\U0001f600Ｂ',1,1),'\ud83d')
        self.assertEqual(sub.substring('A\U0001f600Ｂ',2,1),'\ude00')
        self.assertEqual(sub.substring('A\U0001f600Ｂ',3,1),'Ｂ')
        self.assertEqual(sub.substring('A\U0001f600Ｂ',4,1),'')

    def test_cached_measurements_are_immutable_and_large_text_is_not_retained(self):
        sub._short_text_measure.cache_clear()
        text='Ａx\U0001f600'
        u,widths,total=sub._short_text_measure(text)
        self.assertIsInstance(u,tuple)
        self.assertIsInstance(widths,tuple)
        self.assertEqual((widths,total),((2,1,1,1),5))
        before=sub._short_text_measure.cache_info()
        self.assertEqual(sub.substring('x'*2049,2048,1),'x')
        self.assertEqual(sub._short_text_measure.cache_info(),before)

    def test_str_subclasses_keep_uncached_acceptance_without_hash_or_length(self):
        class Text(str):
            __hash__=None
            def __len__(self):
                raise AssertionError('extra length observation')
        self.assertEqual(sub.substring(Text('Ａbc'),2,1),'b')

    def test_short_measure_cache_evicts_and_includes_2048_scalar_boundary(self):
        sub._short_text_measure.cache_clear()
        for i in range(257):
            self.assertEqual(sub.substring(str(i),0,-1),str(i))
        self.assertEqual(sub._short_text_measure.cache_info().currsize,256)
        text='\U0001f600'*2048
        self.assertEqual(sub.substring(text,0,1),'\ud83d')
        self.assertEqual(len(sub._short_text_measure(text)[0]),4096)


class LiveReferenceFastPaths(Harness):
    def test_scalar_and_literal_observe_replaced_variables_and_shape(self):
        vm=self.make()
        scalar=parse('A'); literal=parse('A:1')
        old=Variable('A',(2,));old.set((0,),10);old.set((1,),20)
        vm.data.variables['A']=old
        self.assertEqual(vm.read_node(scalar),10)
        self.assertEqual(vm.read_node(literal),20)
        new=Variable('A',(1,));new.set((0,),30)
        vm.data.variables['A']=new
        self.assertEqual(vm.read_node(scalar),30)
        with self.assertRaises(EraError) as error:
            vm.read_node(literal)
        self.assertEqual(error.exception.code,'E_INDEX')
        new.forbidden=True
        with self.assertRaises(EraError) as error:
            vm.read_node(scalar)
        self.assertEqual(error.exception.code,'E_VARIABLE_FORBIDDEN')

    def test_ref_nonzero_base_rejected_before_literal_range(self):
        from pyemuera.runtime import Frame
        vm=self.make('@MAIN\nRETURN\n')
        var=Variable('A',(2,))
        frame=Frame(vm.program.functions['MAIN'][0],{'A':Ref(var,(1,))})
        vm.frames.append(frame)
        for node in (parse('A'),parse('A:9999')):
            with self.assertRaises(EraError) as error:
                vm._resolve_ref(node)
            self.assertEqual(error.exception.code,'E_UNSUPPORTED')

    def test_character_implicit_target_and_index_effects_remain_live(self):
        vm=self.make()
        vm.data.character_count=2
        char=Variable('CFLAG',(4,),character=True)
        vm.data.variables['CFLAG']=char
        char.set((0,1),10);char.set((1,1),20)
        node=parse('CFLAG:1')
        vm.set('TARGET',0);self.assertEqual(vm.read_node(node),10)
        vm.set('TARGET',1);self.assertEqual(vm.read_node(node),20)
        vm.set('TARGET',2)
        with self.assertRaises(EraError) as error:
            vm.read_node(node)
        self.assertEqual(error.exception.code,'E_CHARACTER')

    def test_user_character_string_array_keeps_target_and_write_observer(self):
        vm=self.make()
        vm.data.character_count=2
        var=Variable('CUSTOM',(3,),string=True,character=True)
        vm.data.variables['CUSTOM']=var
        var.set((1,1),'before')
        vm.set('TARGET',1)
        node=parse('CUSTOM:1')
        self.assertEqual(vm.read_node(node),'before')
        writes=[]
        var.write_observer=lambda v,k,old,new:writes.append((v.name,k,old,new))
        vm.ref_node(node).set('after')
        self.assertEqual(writes,[('CUSTOM',(1,1),'before','after')])
        self.assertEqual(vm._resolve_ref(node,True)[1],(0,1))
