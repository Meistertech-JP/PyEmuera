"""r30 Windows A12/A13 and native ConstantData resize acceptance order."""
import io
from test_core import Harness
from pyemuera.errors import EraError, Location
from pyemuera.variable_sizes import parse_size_row

class VariableSizeContracts(Harness):
    def data(self, text):
        return self.make(csv={'VariableSize.csv':text}).data

    def test_under100_retains_each_original_extent(self):
        data = self.data('BASE,3\nMAXBASE,5\nCSTR,3\nABL,4\nA,3\nTIME,3\n')
        for name, size in [('BASE',100),('MAXBASE',100),('CSTR',100),('ABL',100),('A',1000),('TIME',1000)]:
            self.assertEqual(data.variables[name].dims, (size,))
            self.assertNotIn(name, data.sizes)
        self.assertEqual([d.severity for d in data.size_diagnostics], [1]*6)
        self.assertEqual([d.location.line for d in data.size_diagnostics], list(range(1,7)))

    def test_rejected_duplicate_keeps_previous_accepted_size(self):
        data = self.data('BASE,101\nBASE,3\n')
        self.assertEqual(data.variables['BASE'].dims, (101,))
        self.assertEqual(data.sizes['BASE'], (101,))
        self.assertEqual(len(data.size_diagnostics),1)

    def test_accepted_duplicate_warns_after_replacement(self):
        data = self.data('ABL,101\nABL,102\n')
        self.assertEqual(data.variables['ABL'].dims,(102,))
        self.assertIn('上書きします', data.size_diagnostics[0].reference_message)

    def test_100_and_101_have_exact_bounds(self):
        for size in [100,101]:
            vm=self.make(csv={'VariableSize.csv':f'BASE,{size}\nMAXBASE,{size}\nCSTR,{size}\n','Chara7.csv':'番号,7\n'})
            self.assertEqual(vm.eval(f'CSVBASE(7,{size-1})'),0)
            self.assertEqual(vm.eval(f'CSVCSTR(7,{size-1})'),'')
            for field in ['CSVBASE','CSVCSTR']:
                with self.assertRaises(EraError) as e: vm.eval(f'{field}(7,{size})')
                self.assertEqual(e.exception.code,'E_INDEX')
            self.assertFalse(vm.data.size_diagnostics)

    def test_base_extent_still_includes_larger_maxbase(self):
        vm=self.make(csv={'VariableSize.csv':'BASE,102\nMAXBASE,105\n','Chara7.csv':'番号,7\n'})
        self.assertEqual(vm.data.variables['BASE'].dims,(102,))
        self.assertEqual(vm.eval('CSVBASE(7,104)'),0)
        with self.assertRaises(EraError):vm.eval('CSVBASE(7,105)')

    def test_accepted_name_reconciliation(self):
        data=self.data('ABL,102\nABLNAME,106\n')
        self.assertEqual(data.variables['ABL'].dims,(106,))
        self.assertEqual(data.variables['ABLNAME'].dims,(106,))

    def test_rejected_alias_does_not_shrink_main(self):
        data=self.data('ABL,101\nABLNAME,2\n')
        self.assertEqual(data.variables['ABL'].dims,(101,))
        self.assertEqual(data.variables['ABLNAME'].dims,(101,))

    def test_four_local_arrays_may_be_small(self):
        data=self.data('LOCAL,1\nARG,2\nLOCALS,3\nARGS,4\n')
        self.assertFalse(data.size_diagnostics)
        self.assertEqual([data.sizes[n] for n in ['LOCAL','ARG','LOCALS','ARGS']],[(1,),(2,),(3,),(4,)])

    def test_multidimensional_small_dimensions_are_not_1d(self):
        data=self.data('DA,2,3\nTA,2,3,4\nCDFLAG,1,2\n')
        self.assertFalse(data.size_diagnostics)
        for name,dims in [('DA',(2,3)),('TA',(2,3,4)),('CDFLAG',(1,2))]: self.assertEqual(data.variables[name].dims,dims)

    def test_zero_warns_level2_and_retains_size(self):
        data=self.data('ABL,0\nLOCAL,0\nDA,0,2\n')
        self.assertEqual([d.severity for d in data.size_diagnostics],[2,2,2])
        self.assertEqual(data.variables['ABL'].dims,(100,))
        self.assertNotIn('LOCAL',data.sizes)

    def test_negative_forbids_and_ignores_bad_tail(self):
        data=self.data('ABL,-1,bad\nDA,-2,wrong\nLOCAL,-1\n')
        for name in ['ABL','DA']:self.assertTrue(data.variables[name].forbidden)
        self.assertEqual(data.sizes['LOCAL'],(-1,))
        self.assertFalse(data.size_diagnostics)

    def test_nonforbiddable_negative_warns_level2(self):
        data=self.data('RESULT,-1\nSTAIN,-1\n')
        self.assertEqual([d.severity for d in data.size_diagnostics],[2,2])
        self.assertFalse(data.variables['RESULT'].forbidden)
        self.assertFalse(data.variables['STAIN'].forbidden)

    def test_positive_after_forbidden_reenables(self):
        data=self.data('ABL,-1\nABL,101\n')
        self.assertFalse(data.variables['ABL'].forbidden)
        self.assertEqual(data.variables['ABL'].dims,(101,))

    def test_small_positive_does_not_reenable_forbidden(self):
        data=self.data('ABL,-1\nABL,2\n')
        self.assertTrue(data.variables['ABL'].forbidden)

    def test_bad_integer_warns_and_continues(self):
        data=self.data('ABL,bad\nABL,2147483648\nABL,101\n')
        self.assertEqual(data.variables['ABL'].dims,(101,))
        self.assertEqual([d.severity for d in data.size_diagnostics],[1,1])

    def test_target_validation_precedes_bad_size(self):
        data=self.data('NO_SUCH,bad\nNAME,bad\nRANDDATA,bad\n')
        self.assertIn('変数名',data.size_diagnostics[0].reference_message)
        self.assertIn('配列変数でない',data.size_diagnostics[1].reference_message)
        self.assertIn('変更できません',data.size_diagnostics[2].reference_message)

    def test_extra_positive_tail_warns_before_minimum(self):
        data=self.data('BASE,3,2\n')
        self.assertEqual([d.severity for d in data.size_diagnostics],[0,1])
        self.assertEqual(data.variables['BASE'].dims,(100,))

    def test_1d_non_numeric_extra_is_ignored(self):
        data=self.data('BASE,101,bad\n')
        self.assertEqual(data.variables['BASE'].dims,(101,))
        self.assertFalse(data.size_diagnostics)

    def test_multidimensional_missing_and_bad_dimension(self):
        data=self.data('DA,2\nDA,2,bad\nTA,2,3,bad\nDA,2,0\n')
        self.assertEqual(len(data.size_diagnostics),4)
        self.assertEqual(data.variables['DA'].dims,(100,100))

    def test_upper_size_limit_and_dimension_product(self):
        data=self.data('ABL,1000000\nABL,1000001\nDA,1001,1000\nTA,101,100,1000\n')
        self.assertEqual(data.variables['ABL'].dims,(1000000,))
        self.assertEqual(len(data.size_diagnostics),3)

    def test_location_and_comment_line_are_preserved(self):
        data=self.data(';comment\n\nBASE,3\n')
        d=data.size_diagnostics[0]
        self.assertEqual((d.location.path,d.location.line,d.source_text,d.phase),('CSV/VariableSize.csv',3,'BASE,3','csv-load'))

    def test_display_threshold_does_not_change_registration(self):
        for threshold,count in [(0,2),(1,1),(2,0)]:
            vm=self.make('@SYSTEM_TITLE\nQUIT',csv={'VariableSize.csv':'BASE,3,2\n','_fixed.config':f'表示する最低警告レベル:{threshold}\n'})
            vm.run()
            self.assertEqual(len(vm.data.size_diagnostics),2)
            self.assertEqual(len(vm.emitted_diagnostics),count)

    def test_csv_loading_success_does_not_consume_rng(self):
        bad=self.make(csv={'VariableSize.csv':'BASE,3\n'})
        good=self.make(csv={'VariableSize.csv':'BASE,100\n'})
        self.assertEqual(bad.rng.getstate(),good.rng.getstate())

    def test_numeric_name_csv_uses_retained_extent(self):
        vm=self.make(csv={'VariableSize.csv':'ABL,2\n','Abl.csv':'2,inside\n100,outside\n'})
        self.assertEqual(vm.get('ABLNAME:2'),'inside')
        self.assertNotIn('OUTSIDE',vm.data.symbols['ABL'])
