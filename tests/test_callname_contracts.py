"""Source-derived template CALLNAME contracts; native execution is separate."""
from unittest.mock import patch

from test_core import Harness
from pyemuera import builtins, commands
from pyemuera.errors import EraError


OPTION = 'CALLNAMEが空文字列の時にNAMEを代入する'
NORMAL = '番号,7\n名前,first\n呼び名,\n名前,last\n基礎,1,121\n'
SPECIAL = '番号,7\n呼び名,\n名前,sp-first\n名前,sp-last\nCFLAG,0,1\n'


class CallnameContracts(Harness):
    def fixture(self, option=None, normal=NORMAL, special=SPECIAL):
        csv = {'Chara7.csv': normal, 'Chara7sp.csv': special,
               '_fixed.config': 'SPキャラを使用する:YES\n'}
        if option is not None:
            csv['_fixed.config'] += f'{OPTION}:{option}\n'
        return csv

    def assert_template_and_live(self, vm, normal, special='sp-last'):
        rng = vm.rng.getstate()
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), normal)
        self.assertEqual(vm.eval('CSVCALLNAME(7,-1)'), special)
        commands.execute_command(vm, 'ADDCHARA', '7')
        commands.execute_command(vm, 'ADDSPCHARA', '7')
        self.assertEqual([vm.get(f'CALLNAME:{i}') for i in range(2)], [normal, special])
        self.assertEqual([vm.get(f'NAME:{i}') for i in range(2)], ['last', 'sp-last'])
        self.assertEqual(vm.rng.getstate(), rng)

    def test_default_false_is_shared_by_csv_and_live_initialization(self):
        self.assert_template_and_live(self.make(csv=self.fixture()), '', '')

    def test_enabled_uses_final_name_and_resolves_normal_sp_independently(self):
        self.assert_template_and_live(self.make(csv=self.fixture('YES')), 'last')

    def test_missing_name_and_callname_remain_empty_when_enabled(self):
        vm = self.make(csv=self.fixture('YES', '番号,7\n'))
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), '')
        vm.data.add_character(7)
        self.assertEqual(vm.get('NAME:0'), '')
        self.assertEqual(vm.get('CALLNAME:0'), '')

    def test_missing_callname_and_explicit_empty_follow_same_option(self):
        for value, expected in [(None, ''), ('NO', ''), ('YES', 'last')]:
            with self.subTest(value=value):
                vm = self.make(csv=self.fixture(value, '番号,7\n名前,first\n名前,last\n'))
                self.assertEqual(vm.eval('CSVCALLNAME(7)'), expected)
                vm.data.add_character(7)
                self.assertEqual(vm.get('CALLNAME:0'), expected)

    def test_duplicate_callname_last_row_wins_in_both_option_states(self):
        for option in ['NO', 'YES']:
            for suffix, expected in [('\n呼び名,latest\n', 'latest'),
                                     ('\n呼び名,\n', '' if option == 'NO' else 'last')]:
                with self.subTest(option=option, suffix=suffix):
                    vm = self.make(csv=self.fixture(option, NORMAL + 'CALLNAME,earlier' + suffix))
                    self.assertEqual(vm.eval('CSVCALLNAME(7)'), expected)
                    vm.data.add_character(7)
                    self.assertEqual(vm.get('CALLNAME:0'), expected)

    def test_nonempty_callname_survives_name_row_order_and_aliases(self):
        vm = self.make(csv=self.fixture('YES',
            'NO,7\nCALLNAME,first-call\nNAME,first\n呼び名,last-call\n名前,last\n'))
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), 'last-call')
        vm.data.add_character(7)
        self.assertEqual(vm.get('CALLNAME:0'), 'last-call')

    def test_live_name_change_and_empty_callname_write_never_reapply_fallback(self):
        vm = self.make(csv=self.fixture('YES'))
        vm.data.add_character(7)
        vm.set('NAME:0', 'changed-live-name')
        self.assertEqual(vm.get('CALLNAME:0'), 'last')
        vm.set('CALLNAME:0', '')
        self.assertEqual(vm.get('CALLNAME:0'), '')
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), 'last')
        vm.data.add_character(7)
        self.assertEqual(vm.get('CALLNAME:1'), 'last')

    def test_config_dictionary_change_after_load_does_not_change_template(self):
        for initial, after, expected in [('NO', 'YES', ''), ('YES', 'NO', 'last')]:
            with self.subTest(initial=initial):
                vm = self.make(csv=self.fixture(initial))
                vm.data.config[OPTION] = after
                vm.data.config['CompatiCALLNAME'] = after
                self.assertEqual(vm.eval('CSVCALLNAME(7)'), expected)
                vm.data.add_character(7)
                self.assertEqual(vm.get('CALLNAME:0'), expected)

    def test_raw_template_rows_remain_unmodified(self):
        vm = self.make(csv=self.fixture('YES'))
        self.assertEqual(vm.data.template(7)[2], ['呼び名', ''])
        self.assertEqual(vm.data.csv_rows['CHARA7'][2], ['呼び名', ''])
        self.assertEqual(vm.eval('CSVBASE(7,1)'), 121)

    def test_void_character_does_not_use_template_fallback(self):
        vm = self.make(csv=self.fixture('YES'))
        vm.data.add_character(7, void=True)
        self.assertEqual(vm.get('CALLNAME:0'), '')

    def test_optional_null_sp_remains_normal_and_all_terms_still_evaluate(self):
        vm = self.make(csv=self.fixture('YES'))
        self.assertEqual(builtins._call_with_values(vm, 'CSVCALLNAME', [7, None]), 'last')
        rng = vm.rng.getstate()
        self.assertEqual(vm.eval('CSVCALLNAME(7,++B)'), 'sp-last')
        self.assertEqual(vm.get('B'), 1)
        self.assertEqual(vm.rng.getstate(), rng)

    def test_disabled_sp_rejection_precedes_template_lookup(self):
        vm = self.make(csv={'Chara7.csv': NORMAL, '_fixed.config': f'{OPTION}:YES\n'})
        with patch.object(vm.data, 'template', side_effect=AssertionError('must not lookup')):
            with self.assertRaises(EraError) as caught:
                vm.eval('CSVCALLNAME(99,-1)')
        self.assertEqual(caught.exception.code, 'E_ARGUMENT')
        self.assertTrue(caught.exception.message.startswith('SPキャラ関係'))

    def test_missing_template_keeps_erb_location_and_result(self):
        vm = self.make('@MAIN\nRESULTS = sentinel\nCSVCALLNAME 99\nRETURN\n',
                       csv=self.fixture('YES'))
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ('E_CSV', 'No Chara CSV for ID 99 (SP=0)'))
        self.assertEqual(caught.exception.location.line, 3)
        self.assertTrue(caught.exception.location.path.endswith('Main.ERB'))
        self.assertEqual(vm.get('RESULTS'), 'sentinel')

    def test_config_aliases_share_file_order_and_fixed_first_success(self):
        csv = self.fixture()
        csv['_default.config'] = f'{OPTION}:YES\n'
        csv['../emuera.config'] = 'CompatiCALLNAME:NO\n'
        csv['_fixed.config'] += 'CompatiCALLNAME:YES\n' + f'{OPTION}:NO\n'
        vm = self.make(csv=csv)
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), 'last')
        # ConfigItem.Fixed rejects the later alias row too.
        self.assertEqual(vm.data.config[OPTION], 'YES')

    def test_aliases_before_fixed_setting_follow_last_successful_row(self):
        csv = self.fixture()
        csv['_default.config'] = f'{OPTION}:YES\nCompatiCALLNAME:NO\n'
        vm = self.make(csv=csv)
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), '')

    def test_empty_raw_config_value_does_not_lock_or_override(self):
        csv = self.fixture()
        csv['_fixed.config'] += f'{OPTION}:\nCompatiCALLNAME:YES\n'
        vm = self.make(csv=csv)
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), 'last')
        self.assertEqual(vm.data.warnings, [])

    def test_invalid_value_warns_and_stops_only_this_options_file_scan(self):
        csv = self.fixture()
        csv['_default.config'] = f'{OPTION}:NO\nCompatiCALLNAME:invalid\n{OPTION}:YES\nX:retained\n'
        vm = self.make(csv=csv)
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), '')
        self.assertNotIn('X', vm.data.config)
        self.assertEqual(len(vm.data.warnings), 1)
        self.assertIn('CSV/_default.config:2: CompatiCALLNAME: 不正な指定です', vm.data.warnings[0])

    def test_invalid_default_does_not_prevent_later_config_file(self):
        csv = self.fixture()
        csv['_default.config'] = 'CompatiCALLNAME:invalid\n'
        csv['../emuera.config'] = f'{OPTION}:YES\n'
        vm = self.make(csv=csv)
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), 'last')
        self.assertEqual(len(vm.data.warnings), 1)

    def test_fixed_value_prevents_invalid_later_alias_from_being_parsed(self):
        csv = self.fixture('YES')
        csv['_fixed.config'] += 'CompatiCALLNAME:invalid\n'
        vm = self.make(csv=csv)
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), 'last')
        self.assertEqual(vm.data.warnings, [])

    def test_config_key_is_case_sensitive_but_value_is_case_insensitive(self):
        csv = self.fixture()
        csv['_fixed.config'] += 'compaticallname:YES\n'
        self.assertEqual(self.make(csv=csv).eval('CSVCALLNAME(7)'), '')

    def test_native_bool_uses_first_colon_value(self):
        vm = self.make(csv=self.fixture('YES:ignored'))
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), 'last')


VALID_BOOL = [('yes', True), ('TrUe', True), ('前', True), ('+1', True),
              ('-1', True), ('2147483647', True), ('-2147483648', True),
              (' 001 ', True), ('NO', False), ('fAlSe', False), ('後', False),
              ('0', False), ('-0', False)]
INVALID_BOOL = ['2147483648', '-2147483649', '0x1', '1_0', '１', 'on', ' ']


for index, (value, enabled) in enumerate(VALID_BOOL):
    def valid(self, value=value, enabled=enabled):
        vm = self.make(csv=self.fixture(value))
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), 'last' if enabled else '')
        self.assertEqual(vm.data.warnings, [])
    setattr(CallnameContracts, f'test_native_bool_valid_{index:02}', valid)

for index, value in enumerate(INVALID_BOOL):
    def invalid(self, value=value):
        vm = self.make(csv=self.fixture(value))
        self.assertEqual(vm.eval('CSVCALLNAME(7)'), '')
        self.assertEqual(len(vm.data.warnings), 1)
        self.assertIn('不正な指定です', vm.data.warnings[0])
    setattr(CallnameContracts, f'test_native_bool_invalid_{index:02}', invalid)
