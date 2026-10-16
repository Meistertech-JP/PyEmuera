"""Whitespace/display regressions found by running Touhou Tentacle Palace."""
from test_core import Harness
from pyemuera.program import command


class CompatA5(Harness):
    def test_print_fullwidth_space_is_data_after_ascii_separator(self):
        self.script('PRINT 　\nPRINTL X')
        self.assertEqual(self.output.getvalue(), '　X\n')

    def test_print_second_ascii_space_is_data(self):
        self.script('PRINT  \nPRINTL X')
        self.assertEqual(self.output.getvalue(), ' X\n')

    def test_printform_fullwidth_space_is_preserved(self):
        self.script('PRINTFORM 　\nPRINTFORML X')
        self.assertEqual(self.output.getvalue(), '　X\n')

    def test_print_two_fullwidth_spaces_consumes_one_separator(self):
        self.script('PRINT　　\nPRINTL X')
        self.assertEqual(self.output.getvalue(), '　X\n')

    def test_indentation_is_not_printed_but_argument_space_is(self):
        vm=self.make('@MAIN\n\t\tPRINT 　\n\tPRINTL X\nRETURN')
        vm.call('MAIN')
        self.assertEqual(self.output.getvalue(), '　X\n')

    def test_trailing_halfwidth_space_survives_source_loading(self):
        self.script('PRINT X \nPRINTL Y')
        self.assertEqual(self.output.getvalue(), 'X Y\n')

    def test_command_consumes_exactly_one_separator(self):
        self.assertEqual(command('PRINT 　'), ('PRINT', '　'))
        self.assertEqual(command('PRINT  '), ('PRINT', ' '))
        self.assertEqual(command('PRINT　　'), ('PRINT', '　'))

    def test_map_style_gap_does_not_collapse(self):
        body='\n'.join([
            'PRINT 　',
            'PRINT ┌','PRINT ─','PRINT ┐','PRINT 　',
            'PRINT ┌','PRINT ─','PRINT ┐','PRINT 　',
            'PRINT 　','PRINTFORML 【情報】',
        ])
        self.script(body)
        self.assertEqual(self.output.getvalue(), '　┌─┐　┌─┐　　【情報】\n')
