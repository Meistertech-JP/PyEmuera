"""Source-derived CSV contracts, distinct from behavior-preserving refactors."""
from unittest.mock import patch
from test_core import Harness
from pyemuera import builtins, commands
from pyemuera.errors import EraError

NUMERIC = 'BASE ABL MARK EXP RELATION TALENT CFLAG EQUIP JUEL'.split()
CSV = {'Chara7.csv': '番号,7\n名前,normal\n基礎,1,121\nCSTR,0,zero\nCSTR,3,last\n',
       'VariableSize.csv': ''.join(f'{name},4\n' for name in NUMERIC + ['MAXBASE','CSTR'])}
SPCSV = dict(CSV, **{'_fixed.config': 'SPキャラを使用する:YES\n',
                   'Chara7sp.csv': '番号,7\n名前,special\nCFLAG,0,1\n基礎,1,150\nCSTR,0,spzero\n'})


class CsvTemplateIndices(Harness):
    def assert_index_error(self, vm, expression, message='参照可能範囲外を参照しました'):
        with self.assertRaises(EraError) as caught:
            vm.eval(expression)
        self.assertEqual((caught.exception.code, caught.exception.message), ('E_INDEX', message))

    def test_base_extent_includes_maxbase(self):
        csv = dict(CSV, **{'VariableSize.csv': 'BASE,2\nMAXBASE,5\n'})
        vm = self.make(csv=csv)
        self.assertEqual(vm.data.variables['BASE'].dims, (100,))
        self.assertEqual(vm.eval('CSVBASE(7,4)'), 0)
        self.assertEqual(vm.eval('CSVBASE(7,5)'),0)
        self.assert_index_error(vm, 'CSVBASE(7,100)')

    def test_name_array_reconciliation_sets_query_extent(self):
        vm = self.make(csv=dict(CSV, **{'VariableSize.csv': 'ABL,2\nABLNAME,6\n'}))
        self.assertEqual(vm.eval('CSVABL(7,5)'), 0)
        self.assertEqual(vm.eval('CSVABL(7,6)'),0)
        self.assert_index_error(vm, 'CSVABL(7,100)')

    def test_forbidden_array_has_no_valid_template_index(self):
        vm = self.make(csv=dict(CSV, **{'VariableSize.csv': 'ABL,-1\n'}))
        self.assertTrue(vm.data.variables['ABL'].forbidden)
        self.assert_index_error(vm, 'CSVABL(7,0)')

    def test_cstr_checks_narrowed_int32(self):
        vm = self.make(csv=CSV)
        for number in [0, 1 << 32, -(1 << 32)]:
            self.assertEqual(vm.eval(f'CSVCSTR(7,{number})'), 'zero')
        self.assertEqual(vm.eval('CSVCSTR(7,4294967299)'), 'last')
        for number in [-1,100,2147483648,4294967295]:
            self.assert_index_error(vm, f'CSVCSTR(7,{number})', 'CSTRの参照可能範囲外を参照しました')

    def test_cstr_missing_valid_slot_and_local_alias(self):
        vm = self.make(csv=CSV)
        self.assertEqual(vm.eval('CSVCSTR(7,1)'), '')
        with self.assertRaises(EraError) as caught:
            vm.eval('CSVSTR(7,4294967296)')
        self.assertEqual(caught.exception.code, 'E_FUNCTION')
        # The alias remains available to existing Python embedding callers.
        self.assertEqual(builtins.call(vm,'CSVSTR',[('lit',7),('lit',4294967296)]),'zero')
        with self.assertRaises(EraError) as caught:
            builtins.call(vm,'CSVSTR',[('lit',7),('lit',-1)])
        self.assertEqual(caught.exception.code,'E_INDEX')

    def test_missing_relation_is_not_live_relation_default(self):
        vm = self.make(csv=dict(CSV, **{'_replace.csv': 'RELATIONの初期値,73\n'}))
        vm.data.add_character(7)
        self.assertEqual(vm.get('RELATION:0:2'), 73)
        self.assertEqual(vm.eval('CSVRELATION(7,2)'), 0)

    def test_scalar_negative_second_argument_selects_special_template(self):
        vm = self.make(csv=SPCSV)
        self.assertEqual(vm.eval('CSVNAME(7,-1)'), 'special')
        self.assertEqual(vm.eval('EXISTCSV(7,-1)'), 1)
        self.assertEqual(vm.eval('CSVBASE(7,1,-1)'), 150)

    def test_optional_null_special_flag_defaults_to_normal(self):
        vm = self.make(csv=SPCSV)
        for name, values, result in [('CSVNAME',[7,None],'normal'), ('EXISTCSV',[7,None],1),
                                     ('CSVBASE',[7,1,None],121), ('CSVCSTR',[7,0,None],'zero')]:
            self.assertEqual(builtins._call_with_values(vm, name, values), result)

    def test_disabled_special_flag_rejected_before_lookup(self):
        vm = self.make(csv=CSV)
        with patch.object(vm.data, 'template', side_effect=AssertionError('lookup must not occur')):
            for source in ['CSVNAME(99,-1)','CSVBASE(99,-1,1)','CSVCSTR(99,-1,1)','EXISTCSV(99,1)']:
                with self.assertRaises(EraError) as caught:
                    vm.eval(source)
                self.assertEqual(caught.exception.code, 'E_ARGUMENT')
                self.assertTrue(caught.exception.message.startswith('SPキャラ関係'))

    def test_missing_template_precedes_bad_index(self):
        vm = self.make(csv=CSV)
        for source in ['CSVBASE(99,-1)','CSVCSTR(99,-1)']:
            with self.assertRaises(EraError) as caught:
                vm.eval(source)
            self.assertEqual((caught.exception.code, caught.exception.message),
                             ('E_CSV', 'No Chara CSV for ID 99 (SP=0)'))

    def test_all_terms_evaluate_before_bounds_and_rng_is_preserved(self):
        vm = self.make(csv=SPCSV)
        before = vm.rng.getstate()
        self.assert_index_error(vm, 'CSVBASE(7,-1,++B)')
        self.assertEqual(vm.get('B'), 1)
        self.assertEqual(vm.rng.getstate(), before)
        with self.assertRaises(EraError):
            vm.eval('CSVBASE(7,-1,RAND(1))')
        self.assertNotEqual(vm.rng.getstate(), before)

    def test_evaluation_failure_precedes_bounds(self):
        vm = self.make(csv=CSV)
        with self.assertRaises(EraError) as caught:
            vm.eval('CSVBASE(7,-1,1/0)')
        self.assertEqual(caught.exception.code, 'E_ARITH')

    def test_command_failure_retains_result_and_reports_erb_location(self):
        vm = self.make('@MAIN\nRESULT=77\nCSVBASE 7,-1\nRETURN\n', csv=CSV)
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.location.line, 3)
        self.assertTrue(caught.exception.location.path.endswith('Main.ERB'))
        self.assertEqual(vm.get('RESULT'), 77)

    def test_required_index_still_rejected_not_defaulted(self):
        vm = self.make(csv=CSV)
        for name in ['CSVBASE','CSVCSTR']:
            with self.assertRaises(EraError):
                builtins._call_with_values(vm, name, [7,None])

    def test_scalar_callname_default_does_not_apply_legacy_fallback(self):
        vm = self.make(csv=dict(CSV, **{'Chara7.csv':'番号,7\n名前,first\n名前,last\n呼び名,\n'}))
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), '')


for field in NUMERIC:
    def check(self, field=field):
        vm = self.make(csv=CSV)
        self.assertEqual(vm.eval(f'CSV{field}(7,3)'), 0)
        for index in [-1,vm.data.variables[field].dims[0],1 << 32, -(1 << 32), (1 << 63)-1]:
            self.assert_index_error(vm, f'CSV{field}(7,{index})')
    setattr(CsvTemplateIndices, 'test_numeric_' + field.lower() + '_bounds', check)
