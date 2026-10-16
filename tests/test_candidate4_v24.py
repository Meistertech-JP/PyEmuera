"""Neutral source-contract regressions; original exe runtime is pending."""
import io,re,unittest
from test_core import Harness
from pyemuera.expr import evaluate,parse
from pyemuera.errors import EraError,Unsupported
from pyemuera.terminal_frame import RetainedFrame

class V24Contracts(Harness):
    def test_strjoin_count_and_boundary(self):
        vm=self.script('A=1,2,3,4')
        self.assertEqual(vm.eval('STRJOIN(A,"-",1,3)'),'2-3-4')
        self.assertEqual(vm.eval('STRJOIN(A,"-",4,0)'),'')
        for expr in ('STRJOIN(A,"-",0,-1)','STRJOIN(A,"-",999,2)'):
            with self.assertRaises(EraError):vm.eval(expr)
    def test_numeric_check_is_not_conversion(self):
        vm=self.make()
        for text,want in [('1e3',1),('1p3',1),('1e',0),('1e+3',0),('1e-3',0),('0x',0),('0b',0),('0xff',1),('+0xff',0),('12.',1),('12.3x',0),('',0),('１２',0)]:
            with self.subTest(text=text):self.assertEqual(vm.eval_node(('call','ISNUMERIC',(('lit',text),))),want)
        with self.assertRaises(EraError):vm.eval('ISNUMERIC("9223372036854775808")')
        with self.assertRaises(EraError):vm.eval('ISNUMERIC("0b2")')
    def test_divmod_rhs_first_and_zero_blocks_lhs(self):
        class Observer:
            def __init__(self,right):self.trace=[];self.right=right
            def call_expr(self,name,args):self.trace.append(name);return 9 if name=='LEFT' else self.right
        for op in ('/','%'):
            v=Observer(2);evaluate(parse('LEFT()'+op+'RIGHT()'),v);self.assertEqual(v.trace,['RIGHT','LEFT'])
            v=Observer(0)
            with self.assertRaises(EraError):evaluate(parse('LEFT()'+op+'RIGHT()'),v)
            self.assertEqual(v.trace,['RIGHT'])
    def test_getnum_descriptor_does_not_read_empty_character(self):
        vm=self.make(csv={'Abl.csv':'0,neutral\n'})
        self.assertEqual(vm.eval('GETNUM(ABL,"neutral")'),0)
        self.assertEqual(vm.eval('GETNUM(ABL:(++A),"neutral")'),0);self.assertEqual(vm.get('A'),0)
        self.assertEqual(vm.eval('GETNUMB("ABL","neutral")'),0)
        with self.assertRaises(EraError):vm.eval('GETNUM("ABL","neutral")')
    def test_msort_int64_and_partial_update(self):
        vm=self.make(headers='#DIM KEYS,3\n#DIM ROWS,1')
        vm.set('KEYS',1<<40);vm.set('KEYS:1',2)
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'),0)
        self.assertEqual([vm.get('KEYS'),vm.get('KEYS:1')],[2,1<<40])
    def test_msort_extreme_difference_explicit_gap(self):
        vm=self.make(headers='#DIM KEYS,3\n#DIM ROWS,3');vm.set('KEYS',-(1<<63));vm.set('KEYS:1',(1<<63)-1)
        # ID retained; r41 closes the recorded gap using the wrapped comparator
        # and Framework's two-element comparison network (source + r40 probes).
        self.assertEqual(vm.eval('ARRAYMSORT(KEYS,ROWS)'),1)
        self.assertEqual([vm.get('KEYS'),vm.get('KEYS:1')],[(1<<63)-1,-(1<<63)])
    def test_unary_minus_v24_reads_operand_twice(self):
        vm=self.make('@MAIN\nRETURN\n@NEXTVAL\n#FUNCTION\nA+=1\nRETURNF A')
        self.assertEqual(vm.eval('-NEXTVAL()'),-2);self.assertEqual(vm.get('A'),2)
    def test_unary_minus_minvalue_system_warning(self):
        vm=self.make();vm.set('A',-(1<<63))
        self.assertEqual(vm.eval('-A'),-(1<<63))
        self.assertIn('整数型最小値',self.output.getvalue())
    def test_getnum_all_character_name_descriptors(self):
        vm=self.make(csv={'Chara7.csv':'番号,7\n名前,Neutral\n呼び名,Call\nあだ名,Nick\n主人の呼び方,Master\n'})
        for descriptor in ('NAME','CALLNAME','NICKNAME','MASTERNAME'):
            for key in ('Neutral','Call','Nick','Master'):
                with self.subTest(descriptor=descriptor,key=key):
                    self.assertEqual(vm.eval(f'GETNUM({descriptor},"{key}")'),7)
                    self.assertEqual(vm.eval(f'GETNUMB("{descriptor}","{key}")'),7)
    def test_character_csv_assistant_metadata_discarded(self):
        vm=self.script('ADDCHARA 0',csv={'Chara0.csv':'番号,0\n名前,Neutral\nISASSI,1\n助手,1\n'})
        self.assertEqual(vm.get('ISASSI:0'),0)
        self.assertFalse(any('助手' in w or 'ISASSI' in w for w in vm.data.warnings))

class VirtualResize(unittest.TestCase):
    def test_grow_erases_old_physical_rows(self):
        out=io.StringIO();size=[(5,6)];frame=RetainedFrame(out,color=False,size_provider=lambda:size[0])
        frame.feed('abcdefghijkl');frame.present()
        screen=['']*6;row=col=0
        def apply(data):
            nonlocal row,col
            for token in re.findall(r'\x1b\[[0-9;?]*[A-Za-z]|[^\x1b]+',data):
                if token.endswith('H') and token.startswith('\x1b['):
                    r,c=map(int,token[2:-1].split(';'));row,col=r-1,c-1
                elif token=='\x1b[K':screen[row]=screen[row][:col]
                elif not token.startswith('\x1b'):
                    line=screen[row];screen[row]=line[:col].ljust(col)+token+line[col+len(token):];col+=len(token)
        apply(out.getvalue());self.assertEqual(screen[:3],['abcd','efgh','ijkl'])
        out.seek(0);out.truncate();size[0]=(20,6);frame.present();apply(out.getvalue())
        self.assertEqual(screen[:3],['abcdefghijkl','',''])
