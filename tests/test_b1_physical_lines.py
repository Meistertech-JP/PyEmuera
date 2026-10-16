"""Physical source records follow the native ReadLine contract, not splitlines."""

import codecs
import struct
import unittest

from test_core import Harness
from pyemuera.display_elements import image_resource
from pyemuera.errors import EraError
from pyemuera.source_lines import source_lines
from pyemuera.startup import read_startup
from pyemuera.text import read_text


class PhysicalLines(unittest.TestCase):
    def test_empty_input_has_no_physical_lines(self):
        self.assertEqual(source_lines(''), [])

    def test_terminators_and_empty_records(self):
        cases = {
            '\n': [''], '\r': [''], '\r\n': [''],
            'a\n': ['a'], 'a\r': ['a'], 'a\r\n': ['a'],
            'a\n\n': ['a', ''], 'a\r\n\r\n': ['a', ''],
            '\r\na\rb\nc\r\n\n': ['', 'a', 'b', 'c', ''],
            'a\r\r\nb': ['a', '', 'b'], 'a': ['a'],
        }
        for text, expected in cases.items():
            with self.subTest(text=repr(text)):
                self.assertEqual(source_lines(text), expected)

    def test_unicode_and_control_separators_remain_data(self):
        # Every extra boundary accepted by str.splitlines is ordinary data here.
        for separator in ('\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029'):
            with self.subTest(separator=repr(separator)):
                self.assertEqual(source_lines('a' + separator + 'b\n'), ['a' + separator + 'b'])


class PhysicalSourceReaders(Harness):
    def test_erb_print_preserves_unicode_separators_without_extra_commands(self):
        for separator in ('\u2028', '\u2029'):
            with self.subTest(separator=repr(separator)):
                value = 'A' + separator + 'B'
                vm = self.make('@MAIN\nPRINTL ' + value + '\nRETURN\n')
                self.assertEqual(vm.program.original_source['ERB/Main.ERB'],
                                 ['@MAIN', 'PRINTL ' + value, 'RETURN'])
                self.assertEqual(vm.program.load_errors, [])
                vm.call('MAIN')
                self.assertEqual(self.output.getvalue(), value + '\n')

    def test_erb_assignment_preserves_embedded_separators(self):
        value = 'A\u2028B\u2029C'
        vm = self.make('@MAIN\nSTR \'= "' + value + '"\nRETURN\n')
        vm.call('MAIN')
        self.assertEqual(vm.get('STR'), value)

    def test_erb_diagnostic_uses_physical_line_after_unicode_data(self):
        vm = self.make('@MAIN\r\nPRINTL A\u2028B\u2029C\r\n\r\nTHROW failure\r\n')
        with self.assertRaises(EraError) as caught:
            vm.call('MAIN')
        self.assertEqual(caught.exception.location.path, 'ERB/Main.ERB')
        self.assertEqual(caught.exception.location.line, 4)

    def test_erb_cr_lf_crlf_and_trailing_newline_execute_identically(self):
        for newline in ('\r', '\n', '\r\n'):
            for trailing in ('', newline):
                with self.subTest(newline=repr(newline), trailing=bool(trailing)):
                    vm = self.make(newline.join(('@MAIN', '', 'A=7', 'RETURN')) + trailing)
                    vm.call('MAIN')
                    self.assertEqual(vm.get('A'), 7)
                    self.assertEqual(vm.program.original_source['ERB/Main.ERB'],
                                     ['@MAIN', '', 'A=7', 'RETURN'])

    def test_empty_erb_and_erh_have_no_synthetic_lines(self):
        vm = self.make('')
        self.assertEqual(vm.program.original_source['ERB/Main.ERB'], [])
        path = vm.root / 'ERB' / 'Empty.ERH'
        path.write_bytes(b'')
        self.assertEqual(list(vm.program._lines(path)), [])
        self.assertEqual(vm.program.original_source['ERB/Empty.ERH'], [])

    def test_erh_macro_preserves_unicode_value_for_execution(self):
        for newline in ('\r', '\n', '\r\n'):
            with self.subTest(newline=repr(newline)):
                value = 'A\u2028B\u2029C'
                vm = self.make('@MAIN\nSTR \'= TEXT\nRETURN\n',
                               headers='#DEFINE TEXT "' + value + '"' + newline)
                self.assertEqual(vm.program.macros['TEXT'], '"' + value + '"')
                self.assertEqual(vm.program.load_errors, [])
                vm.call('MAIN')
                self.assertEqual(vm.get('STR'), value)

    def test_erh_diagnostic_uses_physical_line_after_unicode_data(self):
        with self.assertRaises(EraError) as caught:
            self.make(headers='#DEFINE TEXT "A\u2028B\u2029C"\r\n\r\n[ENDIF]\r\n')
        self.assertEqual(caught.exception.location.path, 'ERB/Header.ERH')
        self.assertEqual(caught.exception.code, 'E_SYNTAX')
        self.assertEqual(caught.exception.location.line, 3)

    def test_csv_gamebase_value_and_name_rows_preserve_unicode(self):
        value = 'A\u2028B\u2029C'
        vm = self.make(csv={'GameBase.csv': 'タイトル,' + value + '\n',
                            'ABL.csv': '0,' + value + '\n1,next\n'})
        self.assertEqual(vm.data.gamebase['TITLE'], value)
        self.assertEqual(vm.data.csv_rows['ABL'], [['0', value], ['1', 'next']])

    def test_csv_cr_lf_crlf_empty_and_trailing_records(self):
        for newline in ('\r', '\n', '\r\n'):
            for trailing in ('', newline):
                with self.subTest(newline=repr(newline), trailing=bool(trailing)):
                    vm = self.make(csv={'ABL.csv': newline.join(('', '0,first', '', '1,last')) + trailing,
                                        'Empty.csv': ''})
                    self.assertEqual(vm.data.csv_rows['ABL'], [['0', 'first'], ['1', 'last']])
                    self.assertEqual(vm.data.csv_rows['EMPTY'], [])

    def test_csv_size_diagnostic_uses_physical_record_and_source(self):
        text = ';note\u2028inside\u2029comment\r\n\r\nUNKNOWN,100\r\n'
        vm = self.make(csv={'VariableSize.csv': text})
        self.assertEqual(len(vm.data.size_diagnostics), 1)
        diagnostic = vm.data.size_diagnostics[0]
        self.assertEqual(diagnostic.location.path, 'CSV/VariableSize.csv')
        self.assertEqual(diagnostic.location.line, 3)
        self.assertEqual(diagnostic.source_text, 'UNKNOWN,100')

    def test_rename_csv_preserves_unicode_replacement(self):
        value = 'A\u2028B\u2029C'
        vm = self.make('@MAIN\nPRINTL [[TOKEN]]\nRETURN\n',
                       csv={'_fixed.config': '_Rename.csvを利用する:YES',
                            '_Rename.csv': value + ',TOKEN\n'})
        self.assertEqual(vm.program.renames['TOKEN'], value)
        vm.call('MAIN')
        self.assertEqual(self.output.getvalue(), value + '\n')

    def test_replace_csv_startup_and_settings_use_same_physical_value(self):
        value = 'A\u2028B\u2029C'
        vm = self.make(csv={'_Replace.csv': 'LoadLabel,' + value + '\r\nMoneyLabel,' + value + '\r\n'})
        startup, _ = read_startup(vm.root)
        self.assertEqual(startup.load_label, value)
        self.assertEqual(vm.data.settings.load_label, value)
        self.assertEqual(vm.data.settings.money_label, value)

    def test_resource_csv_comment_does_not_turn_into_active_declaration(self):
        vm = self.make()
        folder = vm.root / 'RESOURCES'
        folder.mkdir()
        (folder / 'resource.csv').write_text(';comment\u2028name,image.png\u2029other,image.png\n',
                                            encoding='utf-8-sig')
        self.assertEqual(vm.eval('SPRITECREATED("name")'), 0)

    def test_resource_csv_diagnostic_uses_physical_line(self):
        vm = self.make()
        folder = vm.root / 'RESOURCES'
        folder.mkdir()
        (folder / 'resource.csv').write_text(';comment\u2028inside\u2029comment\r\n\r\nname,image.png\r\n',
                                            encoding='utf-8-sig', newline='')
        with self.assertRaises(EraError) as caught:
            vm.eval('SPRITECREATED("name")')
        self.assertEqual(caught.exception.code, 'E_UNSUPPORTED')
        self.assertEqual(caught.exception.location.line, 3)

    def test_image_resource_csv_keeps_unicode_resource_name(self):
        vm = self.make()
        folder = vm.root / 'resources'
        folder.mkdir()
        value = 'A\u2028B\u2029C'
        (folder / 'resource.csv').write_text(value + ',image.png\n', encoding='utf-8-sig')
        (folder / 'image.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\0' * 8 + struct.pack('>II', 12, 34))
        resource = image_resource(vm, value)
        self.assertIsNotNone(resource)
        self.assertEqual((resource['width'], resource['height']), (12, 34))

    def test_bom_and_pending_eof_decoder_contract_is_unchanged(self):
        vm = self.make()
        path = vm.root / 'ERB' / 'Decoder.ERB'
        cases = [
            (codecs.BOM_UTF8 + b'@MAIN\nRETURN\n\xe3\x81', '@MAIN\nRETURN\n'),
            (codecs.BOM_UTF16_LE + '@MAIN\r\nRETURN\r\n'.encode('utf-16-le') + b'X', '@MAIN\r\nRETURN\r\n'),
            (b'@MAIN\nRETURN\n\x81', '@MAIN\nRETURN\n'),
        ]
        for raw, expected in cases:
            with self.subTest(raw=repr(raw)):
                path.write_bytes(raw)
                self.assertEqual(read_text(path)[0], expected)
                lines = list(vm.program._lines(path))
                self.assertEqual([line.text for line in lines], ['@MAIN', 'RETURN'])
                self.assertEqual([line.location.line for line in lines], [1, 2])
