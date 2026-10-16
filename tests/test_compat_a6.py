from test_core import Harness
from pyemuera.errors import EraError


class CompatA6(Harness):
    def test_variablesize_negative_forbids_builtin(self):
        vm=self.make(csv={'VariableSize.csv':'A,-1\n'})
        self.assertTrue(vm.data.variables['A'].forbidden)
        with self.assertRaises(EraError) as cm:
            vm.eval('A:0')
        self.assertEqual(cm.exception.code,'E_VARIABLE_FORBIDDEN')
        from pyemuera import builtins
        self.assertEqual(builtins.call(vm,'EXISTVAR',[('lit','A')]),0)
        with self.assertRaises(EraError) as cm:
            vm.eval('EXISTVAR("A")')
        self.assertEqual(cm.exception.code,'E_FUNCTION')

    def test_variablesize_negative_nonforbiddable_is_warning_not_fatal(self):
        vm=self.make(csv={'VariableSize.csv':'RESULT,-1\n'})
        self.assertFalse(vm.data.variables['RESULT'].forbidden)
        self.assertTrue(any('使用禁止にできない' in w for w in vm.data.warnings))
        self.assertEqual(vm.eval('RESULT:0'),0)

    def test_variablesize_zero_is_warning_not_fatal(self):
        vm=self.make(csv={'VariableSize.csv':'A,0\n'})
        self.assertFalse(vm.data.variables['A'].forbidden)
        self.assertTrue(any('配列長に0は指定できません' in w for w in vm.data.warnings))

    def test_printbutton_displays_label_not_hidden_value(self):
        self.script('PRINTBUTTON @"{11,2}", 11')
        self.assertEqual(self.output.getvalue(),'11')

    def test_printbutton_map_cell_width_matches_room_walls(self):
        self.script('PRINTFORM ┌─┐\nPRINTL\nPRINTFORM │\nPRINTBUTTON @"{1,2}", 1\nPRINTFORML │\nPRINTFORM └─┘')
        self.assertEqual(self.output.getvalue(),'┌─┐\n│ 1│\n└─┘')

    def test_printbuttonlc_and_printbuttonc_use_printc_padding(self):
        self.script('PRINTBUTTONC "x", 999\nPRINTL\nPRINTBUTTONLC "x", 999',
                    csv={'_fixed.config':'PRINTCの文字数:5\n'})
        self.assertEqual(self.output.getvalue(),'    x\nx     ')

    def test_printc_does_not_implicitly_wrap_at_perline(self):
        self.script('PRINTC a\nPRINTC b',
                    csv={'_fixed.config':'PRINTCを並べる数:2\nPRINTCの文字数:3\n'})
        self.assertEqual(self.output.getvalue(),'  a  b')

    def test_printlc_has_legacy_extra_trailing_byte(self):
        self.script('PRINTLC x',csv={'_fixed.config':'PRINTCの文字数:5\n'})
        self.assertEqual(self.output.getvalue(),'x     ')
