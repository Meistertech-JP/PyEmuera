"""v24 builders check ASTs without consuming runtime values or RNG."""
from test_core import Harness
from pyemuera import commands
from pyemuera.errors import EraError

class ArgumentsR40(Harness):
    def test_default_string_methods_reject_numeric_before_arithmetic(self):
        vm = self.make()
        for name in ('CHKFONT','GETCONFIG','GETCONFIGS','ISNUMERIC','HTML_ESCAPE',
                     'HTML_TOPLAINTEXT','TOINT','TOFULL','TOHALF','TOUPPER',
                     'TOLOWER','ESCAPE','COLOR_FROMNAME','GETLINESTR','STRFORM','UNICODEBYTE'):
            with self.subTest(name=name), self.assertRaises(EraError) as caught:
                vm.eval(name+'(1/0)')
            self.assertEqual(caught.exception.code,'E_TYPE')
            self.assertEqual(caught.exception.message,name+'関数:第1引数の型が間違っています')

    def test_default_type_rejection_preserves_postfix_and_rng(self):
        vm, control = self.make(), self.make()
        vm.set('A',4)
        for term in ('A++','RAND:100','A:999999','(A++ + RAND:100)'):
            with self.subTest(term=term), self.assertRaises(EraError) as caught:
                vm.eval('TOINT('+term+')')
            self.assertEqual(caught.exception.code,'E_TYPE')
        self.assertEqual(vm.get('A'),4)
        self.assertEqual(vm.eval('RAND:100000'),control.eval('RAND:100000'))

    def test_unknown_operand_is_parse_error_before_method_count(self):
        vm = self.make()
        with self.assertRaises(EraError) as caught:vm.eval('ALLSAMES(UNDECLARED_R40)')
        self.assertEqual(caught.exception.code,'E_VARIABLE')

    def test_comparison_minimum_and_homogeneous_types(self):
        vm = self.make()
        for name in ('ALLSAMES','NOSAMES','GROUPMATCH'):
            with self.subTest(name=name), self.assertRaises(EraError) as caught:vm.eval(name+'(1/0)')
            self.assertEqual(caught.exception.message,name+'関数には少なくとも2つの引数が必要です')
            with self.assertRaises(EraError) as caught:vm.eval(name+'(A++,"x")')
            self.assertEqual(caught.exception.code,'E_TYPE')
            self.assertEqual(vm.get('A'),0)

    def test_allsames_stops_after_first_mismatch(self):
        vm, control = self.make(), self.make()
        with self.assertRaises(EraError) as caught:
            vm.eval('ALLSAMES(1,2,A++,RAND:100,A:999999)')
        self.assertEqual(caught.exception.as_dict()['diagnostic_message'],
                         '配列変数Aの第１引数(999999)は配列の範囲外です')
        self.assertEqual(vm.get('A'),0)
        self.assertEqual(vm.eval('RAND:100000'),control.eval('RAND:100000'))
        self.assertEqual(vm.eval('ALLSAMES(0,A++,A++)'),0)
        self.assertEqual(vm.get('A'),2)

    def test_nosames_evaluates_all_before_distinct(self):
        vm = self.make()
        self.assertEqual(vm.eval('NOSAMES(0,0,A++)'),0)
        self.assertEqual(vm.get('A'),1)
        with self.assertRaises(EraError):vm.eval('NOSAMES(0,0,A++,A:999999)')
        self.assertEqual(vm.get('A'),1)

    def test_sp_getint_restructure_before_destination_rejection(self):
        vm = self.make()
        for name in ('SAVENOS','PRINTCPERLINE'):
            with self.subTest(name=name), self.assertRaises(EraError) as caught:commands.execute_command(vm,name,'1/0')
            self.assertEqual(caught.exception.code,'E_ARITH')
            with self.assertRaises(EraError) as caught:commands.execute_command(vm,name,'A++')
            self.assertIn('変数以外',caught.exception.message)
            self.assertEqual(vm.get('A'),0)

    def test_sp_getint_destination_extra_terms_and_partial_state(self):
        vm = self.make(); vm.set('A',7)
        commands.execute_command(vm,'PRINTCPERLINE','A,B++')
        self.assertEqual(vm.get('A'),vm.eval('PRINTCPERLINE()'))
        self.assertEqual(vm.get('B'),0)
        vm.set('A',7)
        with self.assertRaises(EraError):commands.execute_command(vm,'SAVENOS','A,1/0')
        self.assertEqual(vm.get('A'),7)

    def test_unregistered_expression_names_rejected(self):
        vm = self.make()
        for name in ('CSVSTR','EXISTFUNCTION','EXISTVAR','GETPRINTCLENGTH','GETPRINTCPERLINE','ISDEFINED'):
            with self.subTest(name=name), self.assertRaises(EraError) as caught:vm.eval(name+'()')
            self.assertEqual(caught.exception.code,'E_FUNCTION')

    def test_registered_native_functions_stay_registered(self):
        vm = self.make()
        self.assertEqual(vm.eval('ALLSAMES(2,2)'),1)
        self.assertEqual(vm.eval('NOSAMES(2,3)'),1)
        self.assertGreater(vm.eval('SAVENOS()'),0)
        with self.assertRaises(EraError) as caught:vm.eval('GETSPCHARA(0)')
        self.assertNotEqual(caught.exception.code,'E_FUNCTION')

    def test_unparenthesized_index_operator_native_rejection(self):
        vm = self.make()
        for text in ('A:++B','A:--B','A:-1','A:+1','A:!B','A:~B'):
            with self.subTest(text=text), self.assertRaises(EraError) as caught:
                commands.execute_command(vm,'SAVENOS',text)
            self.assertEqual(caught.exception.message,'変数の引数の読み取り中に予期しない演算子を発見しました')
            self.assertEqual(vm.get('B'),0)

    def test_getspchara_gate_dynamic_versus_constant_restructuring(self):
        vm = self.make()
        with self.assertRaises(EraError) as caught:
            commands.execute_command(vm,'GETSPCHARA','A++')
        self.assertIn('SPキャラ関係',caught.exception.message)
        self.assertEqual(vm.get('A'),0)
        with self.assertRaises(EraError) as caught:
            commands.execute_command(vm,'GETSPCHARA','1/0')
        self.assertEqual(caught.exception.code,'E_ARITH')

    def test_excess_default_signature_does_not_consume_values(self):
        vm, control = self.make(), self.make()
        with self.assertRaises(EraError) as caught:
            vm.eval('TOINT("1",A++,RAND:100)')
        self.assertEqual(caught.exception.code,'E_ARGUMENT')
        self.assertEqual(vm.get('A'),0)
        self.assertEqual(vm.eval('RAND:10000'),control.eval('RAND:10000'))

    def test_assignment_expression_rejected_without_mutation(self):
        vm = self.make()
        with self.assertRaises(EraError):vm.eval('TOINT(A=3)')
        self.assertEqual(vm.get('A'),0)

    def test_method_builder_checks_type_before_constant_restructuring(self):
        vm = self.make()
        with self.assertRaises(EraError) as caught:
            commands.execute_command(vm,'CHKFONT','1/0')
        self.assertEqual(caught.exception.message,'CHKFONT関数:第1引数の型が間違っています')
        with self.assertRaises(EraError) as caught:
            commands.execute_command(vm,'ALLSAMES','1,2,1/0')
        self.assertEqual(caught.exception.code,'E_ARITH')

    def test_array_descriptor_priority_before_arithmetic_or_effects(self):
        vm = self.make()
        for name in ('MAXARRAY','MAXCARRAY','MINARRAY','MINCARRAY',
                     'SUMARRAY','SUMCARRAY','STRJOIN'):
            for term in ('1/0','A++','RAND(100)'):
                with self.subTest(name=name,term=term), self.assertRaises(EraError) as caught:
                    commands.execute_command(vm,name,term)
                self.assertEqual(caught.exception.message,name+'関数の1番目の引数が変数ではありません')
        self.assertEqual(vm.get('A'),0)

    def test_array_bounds_effects_precede_index_resolution_failure(self):
        vm, control = self.make(), self.make()
        with self.assertRaises(EraError):vm.eval('SUMARRAY(A:999999,RAND(100))')
        self.assertEqual(vm.eval('RAND(10000)'),control.eval('RAND(10000)'))
        vm.set('A',999999)
        with self.assertRaises(EraError):vm.eval('SUMARRAY(A:(A),RAND(100))')
        control.eval('RAND(100)')
        self.assertEqual(vm.eval('RAND(10000)'),control.eval('RAND(10000)'))
        with self.assertRaises(EraError):vm.eval('STRJOIN(A:999999,"x",B++)')
        self.assertEqual(vm.get('B'),1)

    def test_remaining_captured_custom_arity_diagnostics(self):
        vm = self.make()
        groups=[('ARRAYMSORT',':少なくとも2の引数が必要です'),
                ('CMATCH CSVABL CSVBASE CSVCFLAG CSVCSTR CSVEQUIP CSVEXP CSVJUEL CSVMARK CSVRELATION CSVTALENT FINDCHARA FINDELEMENT FINDLASTCHARA FINDLASTELEMENT MATCH STRFIND STRFINDU INRANGEARRAY INRANGECARRAY','には少なくとも2つの引数が必要です'),
                ('GETBIT GETEXPLV GETNUMB GETPALAMLV',':引数の数が間違っています'),
                ('GETNUM','には2つの引数が必要です'),
                ('MESSKIP MOUSESKIP','の引数が多すぎます'),
                ('SAVETEXT',':少なくとも2個の引数が必要です')]
        for names,suffix in groups:
            for name in names.split():
                with self.subTest(name=name),self.assertRaises(EraError) as caught:
                    commands.execute_command(vm,name,'1/0')
                self.assertEqual(caught.exception.message,name+'関数'+suffix)

    def test_custom_signature_rejection_preserves_values(self):
        vm = self.make()
        for text in ('CSVABL(A++,"x")','STRFIND(A++,"x")','GETNUM(A++,"x")',
                     'GETBIT(A++,64)','SAVETEXT(A++,1)','MATCH(1/0,A++)',
                     'ARRAYMSORT(1/0,A)'):
            with self.subTest(text=text),self.assertRaises(EraError) as caught:vm.eval(text)
            self.assertNotEqual(caught.exception.code,'E_ARITH')
            self.assertEqual(vm.get('A'),0)

    def test_remaining_captured_default_signature_diagnostics(self):
        vm = self.make()
        for name in ('BARSTR CHARATU COLOR_FROMRGB CONVERT CURRENTALIGN CURRENTREDRAW '
                     'GETBGCOLOR GETCOLOR GETDEFBGCOLOR GETDEFCOLOR GETFOCUSCOLOR GETFONT '
                     'GETMILLISECOND GETSECOND GETSTYLE GETTIMES INRANGE ISSKIP LIMIT '
                     'LINEISEMPTY PRINTCLENGTH REPLACE STRCOUNT').split():
            with self.subTest(name=name),self.assertRaises(EraError) as caught:
                vm.eval(name+'(1/0)')
            self.assertEqual(caught.exception.message,name+'関数:引数の数が間違っています')
