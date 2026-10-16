"""Source-backed header/declaration grammar and load-time source positions."""
import unittest
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.program import parse_signature

class LoadSyntaxContracts(Harness):
    def test_header_ascii_space(self):
        vm=self.make('@ MAIN(ARG:0)\nA=ARG:0\nRETURN');vm.call('MAIN',[7]);self.assertEqual(vm.get('A'),7)

    def test_header_tabs(self):
        vm=self.make('@\t\tMAIN\nA=9\nRETURN');vm.call('MAIN');self.assertEqual(vm.get('A'),9)

    def test_header_full_width_space(self):
        self.assertEqual(parse_signature('@\u3000MAIN'),('MAIN',[]))

    def test_original_wire_header_shape(self):
        name,p=parse_signature('@ WIRE_KOJO_10_YS(ARG:0, ARG:1, ARGS:0, ARGS:1, ARG:2, ARG:3, ARG:4, ARG:5, ARG:6)')
        self.assertEqual(name,'WIRE_KOJO_10_YS');self.assertEqual(len(p),9)

    def test_missing_header_is_rejected(self):
        with self.assertRaises(EraError):parse_signature('@  ')

    def test_double_at_is_rejected(self):
        with self.assertRaises(EraError):parse_signature('@@MAIN')

    def test_numeric_header_is_rejected(self):
        with self.assertRaises(EraError):parse_signature('@ 123MAIN')

    def test_operator_in_header_is_rejected(self):
        with self.assertRaises(EraError):parse_signature('@ A+B')

    def test_unclosed_header_parameter_list_is_rejected(self):
        with self.assertRaises(EraError):parse_signature('@ MAIN(ARG:0')

    def test_spaced_header_retains_error_location(self):
        vm=self.make('; comment\n\n@ MAIN(ARG:0')
        with self.assertRaises(EraError) as cm:vm.run()
        self.assertEqual(cm.exception.as_dict()['file'],'ERB/Main.ERB');self.assertEqual(cm.exception.location.line,3)

    def test_const_numeric_trailing_comma(self):
        vm=self.make('@MAIN\n#DIM CONST TABLE,3 = 1,2,3,\nA=TABLE:2');vm.call('MAIN');self.assertEqual(vm.get('A'),3)

    def test_const_string_trailing_comma_preserves_quoted_comma(self):
        vm=self.make('@MAIN\n#DIMS CONST TABLE,2 = "a,","b",\nPRINTFORM %TABLE:0%/%TABLE:1%');vm.call('MAIN');self.assertEqual(self.output.getvalue(),'a,/b')

    def test_global_trailing_comma_dimension_inference(self):
        vm=self.make(headers='#DIM TABLE = 4,5,');self.assertEqual(vm.data.variables['TABLE'].dims,(2,));self.assertEqual(vm.get('TABLE:1'),5)

    def test_missing_middle_initializer_rejected_with_private_line(self):
        with self.assertRaises(EraError) as cm:self.make('@MAIN\n#DIM CONST T,3=1,,3,')
        self.assertEqual(cm.exception.code,'E_DECLARATION');self.assertEqual(cm.exception.location.line,2)

    def test_two_trailing_commas_are_rejected(self):
        with self.assertRaises(EraError):self.make(headers='#DIM T=1,2,,')

    def test_empty_initializer_is_rejected(self):
        with self.assertRaises(EraError):self.make(headers='#DIM T=,')

    def test_const_count_still_enforced(self):
        with self.assertRaises(EraError):self.make(headers='#DIM CONST T,3=1,2,')

    def test_global_expression_error_has_header_location(self):
        with self.assertRaises(EraError) as cm:self.make(headers='; comment\n#DIM T=1+ ,')
        self.assertEqual(cm.exception.as_dict()['file'],'ERB/Header.ERH');self.assertEqual(cm.exception.location.line,2)

    def test_local_size_error_has_function_location(self):
        with self.assertRaises(EraError) as cm:self.make('; comment\n@MAIN\n#LOCALSIZE 1+')
        self.assertEqual(cm.exception.location.line,2)

    def test_compiler_prefix_expression_error_has_statement_location(self):
        with self.assertRaises(EraError) as cm:self.make('@MAIN\n; comment\n++(')
        self.assertEqual(cm.exception.as_dict()['file'],'ERB/Main.ERB');self.assertEqual(cm.exception.location.line,3)

class CharacterCSVIntegerPrefixes(Harness):
    def character(self,row):
        vm=self.make(csv={'Chara0.csv':'番号,0\n名前,test\n'+row+'\n'});vm.data.add_character(0);return vm

    def test_numeric_value_prefix_semicolon(self):
        vm=self.character('能力,3,7;note');self.assertEqual(vm.get('ABL:0:3'),7)

    def test_missing_numeric_prefix_defaults_to_one(self):
        vm=self.character('素質,163,;note');self.assertEqual(vm.get('TALENT:0:163'),1)

    def test_invalid_numeric_value_defaults_to_one(self):
        vm=self.character('能力,3,garbage');self.assertEqual(vm.get('ABL:0:3'),1)

    def test_numeric_value_i64_overflow_defaults_to_one(self):
        vm=self.character('能力,3,9223372036854775808');self.assertEqual(vm.get('ABL:0:3'),1)

    def test_numeric_index_prefix(self):
        vm=self.character('能力,3;index,7');self.assertEqual(vm.get('ABL:0:3'),7)

    def test_signed_hex_numeric_prefix(self):
        vm=self.character('能力,3,-0xA;note');self.assertEqual(vm.get('ABL:0:3'),-10)

    def test_string_csv_semicolon_is_data(self):
        vm=self.character('CSTR,3,text;note');self.assertEqual(vm.get('CSTR:0:3'),'text;note')

    def test_csv_query_and_addchar_use_same_value_contract(self):
        vm=self.character('能力,3,7;note');self.assertEqual(vm.eval('CSVABL(0,3)'),vm.get('ABL:0:3'))

    def test_csv_query_missing_value_uses_one(self):
        vm=self.character('素質,163,;note');self.assertEqual(vm.eval('CSVTALENT(0,163)'),1)

class CharacterCSVNumericTokens(unittest.TestCase):
    def test_checked_decimal_boundary(self):
        from pyemuera.data import character_csv_integer as parse
        self.assertEqual(parse('9223372036854775807;note'),(True,9223372036854775807))
        self.assertEqual(parse('9223372036854775808;note'),(False,0))

    def test_negative_numeric_prefix(self):
        from pyemuera.data import character_csv_integer as parse
        self.assertEqual(parse('-12;note'),(True,-12))

    def test_binary_invalid_digit_is_not_silently_truncated(self):
        from pyemuera.data import character_csv_integer as parse
        self.assertEqual(parse('0b102;note'),(False,0))

    def test_missing_hex_digits_invalid(self):
        from pyemuera.data import character_csv_integer as parse
        self.assertEqual(parse('0x;note'),(False,0))

    def test_hex_bit_pattern_matches_int64(self):
        from pyemuera.data import character_csv_integer as parse
        self.assertEqual(parse('0xFFFFFFFFFFFFFFFF;note'),(True,-1))

    def test_decimal_exponent_and_binary_scale(self):
        from pyemuera.data import character_csv_integer as parse
        self.assertEqual(parse('3p4;note'),(True,48));self.assertEqual(parse('13e3;note'),(True,13000))

    def test_exponent_overflow_is_invalid(self):
        from pyemuera.data import character_csv_integer as parse
        self.assertEqual(parse('10e400;note'),(False,0))

    def test_nonnumeric_and_interior_space_are_invalid(self):
        from pyemuera.data import character_csv_integer as parse
        self.assertEqual(parse(';note'),(False,0));self.assertEqual(parse('- 1'),(False,0))

class SpriteAbsenceContracts(Harness):
    def test_absent_sprite_expression_returns_source_zero(self):
        vm=self.make();self.assertEqual(vm.eval('SPRITECREATED("absent")'),0)

    def test_absent_sprite_command_sets_result(self):
        vm=self.script('RESULT=9\nSPRITECREATED "absent"');self.assertEqual(vm.get('RESULT'),0)

    def test_comment_only_catalog_has_no_sprite(self):
        vm=self.make();r=vm.root/'RESOURCES';r.mkdir();(r/'resource.csv').write_text(';name,image.png\n')
        self.assertEqual(vm.eval('SPRITECREATED("name")'),0)

    def test_active_catalog_does_not_return_false_zero(self):
        vm=self.make();r=vm.root/'RESOURCES';r.mkdir();(r/'resource.csv').write_text(';comment\nname,image.png\n')
        with self.assertRaises(EraError) as cm:vm.eval('SPRITECREATED("name")')
        self.assertEqual(cm.exception.code,'E_UNSUPPORTED');self.assertEqual(cm.exception.location.line,2)

    def test_query_wrong_type_is_rejected(self):
        vm=self.make()
        with self.assertRaises(EraError):vm.eval('SPRITECREATED(3)')

    def test_query_arity_is_not_silently_ignored(self):
        vm=self.make()
        with self.assertRaises(EraError):vm.eval('SPRITECREATED("name",1)')

class EncodingInstructionFORM(Harness):
    def test_command_raw_form_variable(self):
        vm=self.script('STR:0 = ABC\nENCODETOUNI %STR:0%\nA=RESULT');self.assertEqual(vm.get('A'),3);self.assertEqual([vm.get('RESULT:'+str(i)) for i in range(1,4)],[65,66,67])

    def test_command_literal_quotes_are_data(self):
        vm=self.script('ENCODETOUNI "A"\nA=RESULT');self.assertEqual(vm.get('A'),3);self.assertEqual([vm.get('RESULT:'+str(i)) for i in range(1,4)],[34,65,34])

    def test_command_empty_sets_only_length(self):
        vm=self.script('RESULT:1=9\nENCODETOUNI');self.assertEqual(vm.get('RESULT'),0);self.assertEqual(vm.get('RESULT:1'),9)

    def test_command_japanese_bmp(self):
        vm=self.script('ENCODETOUNI あ');self.assertEqual(vm.get('RESULT:1'),0x3042)

    def test_expression_remains_different_contract(self):
        self.assertEqual(self.make().eval('ENCODETOUNI("A",0)'),65)

    def test_command_result_limit_preserves_result(self):
        vm=self.make('@MAIN\nENCODETOUNI ' + 'A'*101,csv={'VariableSize.csv':'RESULT,100\n'});vm.set('RESULT',9)
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertEqual(vm.get('RESULT'),9)

    def test_surrogate_failure_precedes_result_write(self):
        vm=self.make('@MAIN\nENCODETOUNI 😀');vm.set('RESULT',9)
        with self.assertRaises(EraError):vm.call('MAIN')
        self.assertEqual(vm.get('RESULT'),9)

if __name__=='__main__':unittest.main()
