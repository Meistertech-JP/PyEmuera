"""Source-derived format fixtures, public adapters, and native r40 evidence.

New fixtures are not claimed as new Windows observations. Native retest inputs
and the standalone Framework probe live in verification/r41/numeric_fixtures.
"""
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_core import Harness
from pyemuera import builtins, commands, dispatcher
from pyemuera.errors import EraError
from pyemuera.numeric_format import format_int64, NumberFormat


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/r41_numeric_formats.json'


class NumericFormatsR41(Harness):
    def check_category(self, category):
        vm = self.make()
        for row in json.loads(FIXTURE.read_text())['cases']:
            if row['category'] != category:
                continue
            with self.subTest(case_id=row['case_id'], value=row['value'], spec=row['format']):
                # Pass typed AST literals to cover Int64.MinValue and escape
                # semantics without conflating the independent ERB lexer.
                args = [('lit', row['value']), ('lit', row['format'])]
                self.assertEqual(builtins.call(vm, 'TOSTR', args), row['expected'])
                self.assertEqual(builtins.call(vm, 'MONEYSTR', args), '$' + row['expected'])

    def test_standard_formats_keep_integer_precision(self):
        self.check_category('standard')

    def test_framework_standard_parser_boundary(self):
        self.check_category('parser')

    def test_general_custom_literals_quotes_and_escape(self):
        self.check_category('custom_literal')

    def test_custom_grouping_scaling_and_rounding(self):
        self.check_category('custom_scale')

    def test_positive_negative_zero_sections_and_rounded_zero(self):
        self.check_category('custom_section')

    def test_custom_exponent_sign_digits_and_multiple_markers(self):
        self.check_category('custom_scientific')

    def test_native_named_case_replays_through_program_output(self):
        vm = self.make('@MAIN\nPRINTFORML R40_MONEY|%MONEYSTR(10)%|%MONEYSTR(10,"Named")%\nRETURN\n')
        vm.call('MAIN')
        self.assertEqual(self.output.getvalue(), 'R40_MONEY|$10|$Named\n')
        native = json.loads((ROOT/'verification/r41/received_r40/evidence/results/extra-native/moneystr-default/result.json').read_text())
        self.assertEqual(native['native_markers'], ['R40_MONEY|$10|$Named'])
        self.assertEqual(native['status'], 'FAIL')  # Historical evidence stays immutable.

    def test_money_prefix_and_suffix_wrap_completed_format(self):
        vm = self.make(csv={'_Replace.csv':'お金の単位,円\n単位の位置,後\n'})
        self.assertEqual(vm.eval('MONEYSTR(-10,"D4")'), '-0010円')
        self.assertEqual(vm.eval('MONEYSTR(10,"Named")'), 'Named円')
        self.assertEqual(vm.eval('MONEYSTR(10,"C2")'), '¥10.00円')

    def test_invalid_standard_styles_report_native_name(self):
        vm = self.make()
        for name in ('MONEYSTR', 'TOSTR'):
            for style in ('Q', 'Q2', 'R', 'R2', 'B', 'B8', 'Z99'):
                with self.subTest(name=name, style=style):
                    with self.assertRaises(EraError) as caught:
                        builtins.call(vm, name, [('lit', 10), ('lit', style)])
                    message = ('MONEYSTR関数の第2引数の書式指定が間違っています'
                               if name == 'MONEYSTR' else 'TOSTR関数の書式指定が間違っています')
                    self.assertEqual((caught.exception.code, caught.exception.message), ('E_ARGUMENT', message))

    def test_invalid_money_style_keeps_effects_and_result_assignment(self):
        for execute in (commands.execute_command, dispatcher.execute):
            with self.subTest(execute=execute.__module__):
                vm = self.make()
                vm.set('RESULTS', 'sentinel')
                vm.set('RESULT', 917)
                with self.assertRaises(EraError) as caught:
                    execute(vm, 'MONEYSTR', '++B,"Q2"')
                self.assertEqual(caught.exception.message, 'MONEYSTR関数の第2引数の書式指定が間違っています')
                self.assertEqual((vm.get('B'), vm.get('RESULTS'), vm.get('RESULT')), (1, 'sentinel', 917))

    def test_empty_optional_style_uses_default_in_both_adapters(self):
        vm = self.make()
        for expression, expected in [('MONEYSTR(10,)', '$10'), ('MONEYSTR(10,"")', '$10'),
                                     ('TOSTR(10,)', '10'), ('TOSTR(10,"")', '10')]:
            self.assertEqual(vm.eval(expression), expected)

    def test_value_and_format_expressions_evaluate_once_in_order(self):
        vm = self.make('@MAIN\nRETURN\n@VALUE\n#FUNCTION\nB=B*10+1\nRETURNF 1234\n'
                       '@STYLE\n#FUNCTIONS\nB=B*10+2\nRETURNF "#,##0"\n')
        self.assertEqual(vm.eval('MONEYSTR(VALUE(),STYLE())'), '$1,234')
        self.assertEqual(vm.get('B'), 12)

    def test_japanese_number_culture_is_independent_of_host_width_locale(self):
        vm = self.make()
        vm.program.config['内部で使用する東アジア言語'] = 'CHINESE'
        with patch('locale.localeconv', side_effect=AssertionError('host locale read')):
            self.assertEqual(vm.eval('TOSTR(1234,"N2")'), '1,234.00')
            self.assertEqual(vm.eval('MONEYSTR(1234,"C")'), '$¥1,234')

    def test_explicit_number_format_changes_separators_patterns_and_group_sizes(self):
        culture = replace(NumberFormat(), decimal_separator=',', group_separator='.',
                          group_sizes=(3, 2), negative_sign='minus', positive_sign='plus',
                          currency_symbol='EUR', currency_decimal_separator=',',
                          currency_group_separator='.', currency_digits=2,
                          currency_positive_pattern=3, currency_negative_pattern=8,
                          percent_positive_pattern=0, percent_negative_pattern=0,
                          number_negative_pattern=0)
        self.assertEqual(format_int64(12345678, '#,##0.00', culture), '1.23.45.678,00')
        self.assertEqual(format_int64(-1234, 'N1', culture), '(1.234,0)')
        self.assertEqual(format_int64(1234, 'C', culture), '1.234,00 EUR')
        self.assertEqual(format_int64(-1234, 'C', culture), 'minus1.234,00 EUR')
        self.assertEqual(format_int64(10, 'P0', culture), '1,000 %')
        self.assertEqual(format_int64(-10, 'P0', culture), 'minus1,000 %')
        self.assertEqual(format_int64(1234, '0.0E+00', culture), '1,2Eplus03')
        stopped = replace(culture, group_sizes=(3, 0))
        self.assertEqual(format_int64(12345678, '#,##0', stopped), '12345.678')
