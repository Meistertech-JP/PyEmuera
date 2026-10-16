"""Source-backed Restructure checks remain separate from runtime effects."""
from test_core import Harness
from pyemuera import commands
from pyemuera.data import Variable
from pyemuera.errors import EraError
from pyemuera.expr import parse
from types import SimpleNamespace


TRACE = '\n@TRACE()\n#FUNCTION\nA++\nPRINTFORML R41_TRACE|{A}|{RAND:10000}\nRETURNF 0\n'


class ArgumentsR41(Harness):
    def test_static_bounds_precede_comparison_values(self):
        vm,control=self.make(),self.make()
        for name in ('ALLSAMES','NOSAMES','GROUPMATCH'):
            with self.subTest(name=name),self.assertRaises(EraError) as caught:
                vm.eval(name+'(1,2,A++,RAND:100,A:999999)')
            self.assertEqual(caught.exception.as_dict()['diagnostic_message'],
                             '配列変数Aの第１引数(999999)は配列の範囲外です')
        self.assertEqual(vm.get('A'),0)
        self.assertEqual(vm.eval('RAND:10000'),control.eval('RAND:10000'))

    def test_allsames_shortcut_skips_dynamic_index_and_rng(self):
        vm,control=self.make(),self.make()
        self.assertEqual(vm.eval('ALLSAMES(1,2,A:(B++),RAND:100)'),0)
        self.assertEqual(vm.get('B'),0)
        self.assertEqual(vm.eval('RAND:10000'),control.eval('RAND:10000'))

    def test_nosames_equal_values_do_not_shortcut(self):
        vm=self.make()
        self.assertEqual(vm.eval('NOSAMES(0,0,A++,A++)'),0)
        self.assertEqual(vm.get('A'),2)
        self.assertEqual(vm.eval('ALLSAMES("x","x","x")'),1)
        self.assertEqual(vm.eval('NOSAMES("x","y","z")'),1)

    def test_static_bounds_prevent_user_method_trace_and_rng(self):
        source='@MAIN\nRETURN\n'+TRACE
        vm,control=self.make(source),self.make(source)
        with self.assertRaises(EraError):vm.eval('NOSAMES(0,0,TRACE(),A:999999)')
        self.assertEqual(vm.get('A'),0)
        self.assertNotIn('R41_TRACE',vm.console.output.getvalue())
        self.assertEqual(vm.eval('RAND:10000'),control.eval('RAND:10000'))

    def test_dynamic_failure_keeps_earlier_trace_and_rng(self):
        source='@MAIN\nRETURN\n'+TRACE
        vm,control=self.make(source),self.make(source)
        vm.set('B',999999)
        with self.assertRaises(EraError) as caught:vm.eval('NOSAMES(0,0,TRACE(),A:(B++))')
        self.assertEqual(caught.exception.code,'E_INDEX')
        self.assertEqual((vm.get('A'),vm.get('B')),(1,1000000))
        self.assertIn('R41_TRACE|1|',vm.console.output.getvalue())
        control.eval('RAND:10000')
        self.assertEqual(vm.eval('RAND:10000'),control.eval('RAND:10000'))

    def test_constant_second_axis_rejects_before_dynamic_first(self):
        vm=self.make(headers='#DIM GRID,2,3')
        with self.assertRaises(EraError) as caught:
            vm.eval('NOSAMES(0,0,GRID:(B++):3)')
        self.assertEqual(vm.get('B'),0)
        self.assertEqual(caught.exception.as_dict()['diagnostic_message'],
                         '配列型変数GRIDの第２引数(3)は配列の範囲外です')

    def test_literal_arithmetic_and_pure_method_index_checks(self):
        vm=self.make()
        for index in ('(999+1)','ABS(1000)'):
            with self.subTest(index=index),self.assertRaises(EraError):
                vm.eval('ALLSAMES(1,2,A:'+index+')')

    def test_character_registration_axis_is_not_static_bounds(self):
        vm=self.make()
        self.assertEqual(vm.eval('ALLSAMES(1,2,ABL:999999:0)'),0)
        with self.assertRaises(EraError) as caught:
            vm.eval('ALLSAMES(1,2,ABL:999999:100)')
        self.assertEqual(caught.exception.as_dict()['diagnostic_message'],
                         'キャラクタ配列変数ABLの第２引数(100)は配列の範囲外です')

    def test_arg_axes_are_deferred_until_runtime_read(self):
        vm=self.make()
        self.assertEqual(vm.eval('ALLSAMES(1,2,ARG:999999)'),0)
        with self.assertRaises(EraError):vm.eval('NOSAMES(0,0,A++,ARG:999999)')
        self.assertEqual(vm.get('A'),1)

    def test_ref_axes_do_not_use_declared_placeholder_shape(self):
        source='@MAIN\nCALL CHECK,A\nRETURN\n@CHECK(DEST)\n#DIM REF DEST\nB=ALLSAMES(1,2,DEST:999999)\nRETURN'
        vm=self.make(source)
        vm.call('MAIN')
        self.assertEqual(vm.get('B'),0)

    def test_type_validation_precedes_constant_bounds(self):
        vm=self.make()
        with self.assertRaises(EraError) as caught:vm.eval('NOSAMES(0,"x",A:999999)')
        self.assertEqual(caught.exception.code,'E_TYPE')

    def test_statement_static_failure_preserves_result_and_location(self):
        source='@MAIN\nA=0\nRESULT=77\nNOSAMES 0,0,A++,A:999999\nRETURN'
        vm=self.make(source)
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.location.line,4)
        self.assertEqual((vm.get('A'),vm.get('RESULT')),(0,77))

    def test_unique_descriptor_restructure_exceptions(self):
        vm=self.make()
        # GetnumMethod only restructures its keyword; StrJoinMethod only
        # restructures delimiter/start/count. Their first descriptors survive.
        self.assertEqual(vm.eval('ALLSAMES(1,2,GETNUM(A:999999,"x"))'),0)
        with self.assertRaises(EraError):commands.execute_command(vm,'STRJOIN','A:999999,"x",B++')
        self.assertEqual(vm.get('B'),1)

    def test_builtin_and_declared_token_diagnostic_subtypes(self):
        for name in ('A','FLAG','STR','LOCAL','ITEMPRICE'):
            with self.subTest(name=name),self.assertRaises(EraError) as caught:
                Variable(name,(2,)).get((2,))
            self.assertTrue(caught.exception.as_dict()['diagnostic_message'].startswith('配列変数'+name))
        with self.assertRaises(EraError) as caught:Variable('CUSTOM',(2,)).get((2,))
        self.assertTrue(caught.exception.as_dict()['diagnostic_message'].startswith('配列型変数CUSTOM'))

    def test_direct_decimal_min_is_lexically_rejected(self):
        vm=self.make()
        for expression in ('-9223372036854775808','+9223372036854775808',
                           'A++ + -9223372036854775808','9223372036854775808e0'):
            with self.subTest(expression=expression),self.assertRaises(EraError) as caught:vm.eval(expression)
            self.assertEqual(caught.exception.code,'E_SYNTAX')
            self.assertEqual(caught.exception.as_dict()['diagnostic_message'],
                             '"9223372036854775808"は64ビット符号付き整数の範囲を超えています')
        self.assertEqual(vm.get('A'),0)

    def test_computed_min_and_other_valid_negative_values_survive(self):
        vm=self.make()
        for expression,value in (('-9223372036854775807',-(1<<63)+1),
                                  ('(-9223372036854775807-1)',-(1<<63)),
                                  ('9223372036854775807+1',-(1<<63)),
                                  ('0x8000000000000000',-(1<<63)),
                                  ('0xffffffffffffffff',-1),
                                  ('0b'+'1'*64,-1)):
            with self.subTest(expression=expression):self.assertEqual(vm.eval(expression),value)

    def test_unary_minus_computed_min_keeps_native_warning(self):
        vm=self.make()
        self.assertEqual(vm.eval('-(-9223372036854775807-1)'),-(1<<63))
        self.assertIn('整数型最小値(-9223372036854775808)',self.output.getvalue())

    def test_radix_token_overflow_and_exponent_boundaries(self):
        vm=self.make()
        for expression,value in (('1e3',1000),('1p3',8),('1e-3',0),('0x1p10',65536)):
            with self.subTest(expression=expression):self.assertEqual(vm.eval(expression),value)
        for expression in ('0x10000000000000000','0b'+'1'*65,'1e1000','0b102'):
            with self.subTest(expression=expression),self.assertRaises(EraError):parse(expression)

    def test_literal_method_adapter_without_functions_is_supported(self):
        from pyemuera.builtins import call
        vm=SimpleNamespace(program=SimpleNamespace(functions={}),declarations={})
        self.assertEqual(call(vm,'ALLSAMES',( ('lit',2),('lit',2) )),1)
        self.assertEqual(call(vm,'NOSAMES',( ('lit',2),('lit',3) )),1)

    def test_numeric_load_diagnostic_keeps_lexical_body(self):
        source='@MAIN\nA=-9223372036854775808\nRETURN'
        vm=self.make(source,csv={'../emuera.config':'ロード時に引数を解析する:YES'})
        self.assertEqual(vm.program.argument_diagnostics[0].reference_message,
                         '"9223372036854775808"は64ビット符号付き整数の範囲を超えています')

    def test_private_varsize_restructures_without_live_frame(self):
        source=('@MAIN\nCALL FIRST\nCALL SECOND\nRETURN\n'
                '@FIRST\n#DIMS HASH_TABLE,4\n#DIM DYNAMIC INDEX\n'
                'INDEX=1\nHASH_TABLE:(INDEX % VARSIZE("HASH_TABLE")) = stored\n'
                'A=VARSIZE("HASH_TABLE")\nRETURN\n'
                '@SECOND\n#DIMS DYNAMIC HASH_TABLE,7\n'
                'A:1=VARSIZE("HASH_TABLE",0)\nRETURN')
        vm=self.make(source,csv={'../emuera.config':'ロード時に引数を解析する:YES'})
        self.assertEqual(vm.program.argument_diagnostics,[])
        vm.call('MAIN')
        self.assertEqual((vm.get('A'),vm.get('A:1')),(4,7))
        first=vm.program.functions['FIRST'][0]
        self.assertEqual(vm.static[first.uid]['HASH_TABLE'].get((1,)),'stored')

    def test_ref_varsize_remains_binding_dependent(self):
        source=('@MAIN\nCALL CHECK,A\nRETURN\n'
                '@CHECK(TABLE)\n#DIM REF TABLE\nB=VARSIZE("TABLE")\nRETURN')
        vm=self.make(source,csv={'../emuera.config':'ロード時に引数を解析する:YES'})
        self.assertEqual(vm.program.argument_diagnostics,[])
        vm.call('MAIN')
        self.assertEqual(vm.get('B'),1000)
