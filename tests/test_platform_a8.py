from test_core import Harness
from pyemuera.errors import EraError

class Host:
    def __init__(self):self.focus=True;self.key=-32768;self.queries=[];self.cleared=False
    def active(self):return self.focus
    def key_state(self,key):self.queries.append(key);return self.key
    def client_size(self):return (640,480)
    def clear_input(self):self.cleared=True

class PlatformA8(Harness):
    def vm(self):
        v=self.make();v.host_adapter=Host();return v
    def test_active(self):
        v=self.vm();self.assertEqual(v.eval('ISACTIVE()'),1);v.host_adapter.focus=False;self.assertEqual(v.eval('ISACTIVE()'),0)
    def test_inactive_key_does_not_evaluate_arg(self):
        v=self.vm();v.host_adapter.focus=False;self.assertEqual(v.eval('GETKEY(A++)'),0);self.assertEqual(v.get('A'),0);self.assertFalse(v.host_adapter.queries)
    def test_key_high_bit(self):
        v=self.vm();self.assertEqual(v.eval('GETKEY(65)'),1);v.host_adapter.key=0;self.assertEqual(v.eval('GETKEY(65)'),0)
    def test_trigger_toggling_shared_between_functions(self):
        v=self.vm();self.assertEqual(v.eval('GETKEYTRIGGERED(65)'),1);self.assertEqual(v.eval('GETKEYTRIGGERED(65)'),0);v.host_adapter.key=-32767;self.assertEqual(v.eval('GETKEYTRIGGERED(65)'),1)
        v.host_adapter.key=-32768;v.eval('GETKEY(65)');self.assertEqual(v.eval('GETKEYTRIGGERED(65)'),0)
    def test_invalid_key_not_queried(self):
        v=self.vm();self.assertEqual(v.eval('GETKEY(256)'),0);self.assertEqual(v.eval('GETKEY(-1)'),0);self.assertFalse(v.host_adapter.queries)
    def test_client_pixels_not_columns(self):
        v=self.vm();self.assertEqual(v.eval('CLIENTWIDTH()'),640);self.assertEqual(v.eval('CLIENTHEIGHT()'),480)
    def test_unavailable_platform_explicit_error(self):
        v=self.make()
        with self.assertRaises(EraError) as cm:v.eval('GETKEY(65)')
        self.assertEqual(cm.exception.code,'E_PLATFORM')
    def test_clear_textbox_invokes_adapter_not_noop(self):
        v=self.make('@MAIN\nCLEARTEXTBOX\nRETURN');v.host_adapter=Host();v.call('MAIN');self.assertTrue(v.host_adapter.cleared)
    def test_print_space_quantizes_centiem(self):
        self.script('PRINT_SPACE 100\nPRINTL X');self.assertEqual(self.output.getvalue(),'  X\n')
    def test_print_space_fraction_accumulates(self):
        self.script('PRINT_SPACE 25\nPRINT_SPACE 25\nPRINTL X');self.assertEqual(self.output.getvalue(),' X\n')
    def test_print_space_negative_rejected(self):
        with self.assertRaises(EraError):self.script('PRINT_SPACE -1')
    def test_source_unimplemented_is_distinct(self):
        for name in ['REF','REFBYNAME','SAVEVAR','LOADVAR']:
            with self.subTest(name=name):
                with self.assertRaises(EraError) as cm:self.script(name)
                self.assertEqual(cm.exception.code,'E_ARGUMENT' if name in {'REF','REFBYNAME'} else 'E_SOURCE_UNIMPLEMENTED')
