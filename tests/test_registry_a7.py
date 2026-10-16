"""Neutral fixtures for metadata routing and compiler lowering."""
import copy,json,unittest
from dataclasses import asdict
from importlib.resources import files
from test_core import Harness
from pyemuera.registry import COMMAND_SPECS,FUNCTION_SPECS,SYNTAX_SPECS,validate_document,_unique
from pyemuera.dispatcher import DISPATCH
from pyemuera.errors import EraError
from pyemuera.program import command
from pyemuera.runtime import supported_command
from pyemuera.audit import audit

class RegistryA7(Harness):
    def test_expected_source_print_variants(self):
        expected={f'PRINT{body}{style}{end}' for body in ('','V','S','FORM','FORMS') for style in ('','K','D') for end in ('','L','W')}
        expected|={f'PRINTSINGLE{body}{style}' for body in ('','V','S','FORM','FORMS') for style in ('','K','D')}
        expected|={f'PRINT{body}{column}{style}' for body in ('','FORM') for column in ('C','LC') for style in ('','K','D')}
        actual={n for n,s in COMMAND_SPECS.items() if s['family']=='print' and s.get('source') and s['source']['line']<165}
        self.assertEqual(actual,expected)
    def test_all_registered_prints_use_one_handler(self):
        from pyemuera.printing import execute
        for n,s in COMMAND_SPECS.items():
            if s['family']=='print':self.assertIs(DISPATCH[n][0],execute)
    def test_unknown_similar_suffixes_rejected(self):
        for n in ('PRINTN','PRINTVLC','PRINTFORMLW','PRINTSINGLEW','PRINTKDW','PRINTWHAT'):
            self.assertFalse(supported_command(n),n)
    def test_immutable_registry(self):
        with self.assertRaises(TypeError):COMMAND_SPECS['PRINTL']['newline']=False
    def test_duplicate_key_rejected(self):
        with self.assertRaises(EraError):json.loads('{"x":1,"x":2}',object_pairs_hook=_unique)
    def test_handler_import_path_is_not_executable(self):
        with self.assertRaises(EraError):validate_document({'schema_version':1,'commands':{'BAD':{'family':'os.system'}}},'commands')
    def test_boolean_not_integer_flags(self):
        spec=dict(COMMAND_SPECS['PRINTL']);spec['newline']=1
        with self.assertRaises(EraError):validate_document({'schema_version':1,'commands':{'PRINTL':spec}},'commands')
    def test_invalid_function_arity_rejected(self):
        with self.assertRaises(EraError):validate_document({'schema_version':1,'functions':{'X':{'min_args':2,'max_args':1,'handler':'legacy','reference_first':False}}},'functions')
    def test_function_tables_share_single_contract(self):
        from pyemuera import builtins,compat1824
        for n,s in FUNCTION_SPECS.items():
            self.assertEqual(builtins.ARITY[n],(s['min_args'],s['max_args']))
            self.assertEqual(n in compat1824.ARITY,s['handler']=='compat1824')
    def test_compiler_control_lowering_preserved(self):
        vm=self.make('@MAIN\nIF 1\nREPEAT 2\nA+=1\nREND\nENDIF\nRETURN')
        code=vm.program.functions['MAIN'][0].code
        self.assertIn('_IF',[x.op for x in code]);self.assertIn('_REPEAT',[x.op for x in code]);self.assertNotIn('IF',[x.op for x in code])
        vm.call('MAIN');self.assertEqual(vm.get('A'),2)
    def test_audit_knows_all_printdata_variants(self):
        vm=self.make('@MAIN\nPRINTDATAKW\nDATA abc\nENDDATA\nRETURN')
        self.assertEqual(audit(vm.program,vm.data)['unsupported_command_counts'],{})
    def test_print_payload_spaces_unchanged_by_registry(self):
        self.assertEqual(command('PRINTFORMW 　{2} '),('PRINTFORMW','　{2} '))
    def test_two_vms_no_registry_state_leak(self):
        a=self.make('@MAIN\nFORCEKANA 1\nPRINTKL あ\nRETURN');a.call('MAIN')
        b=self.make('@MAIN\nPRINTKL あ\nRETURN');b.call('MAIN');self.assertEqual(self.output.getvalue(),'あ\n')

# Exhaustive real PRINT variants: expected output derives from the test's
# independently enumerated family product, not from production PrintSpec flags.
def variant_test(body,style,end,single=False,column=None):
    def check(self):
        name=('PRINTSINGLE' if single else 'PRINT')+body+(column or '')+style+end
        arg={'':'hello','V':'"hello"','S':'"hello"','FORM':'hel%"lo"%','FORMS':'"hel%\\\"lo\\\"%"'}[body]
        vm=self.make('@MAIN\n'+name+' '+arg+'\nRETURN',csv={'_fixed.config':'PRINTCの文字数:8\n'})
        vm.call('MAIN')
        expected='hello'
        if column=='C':expected='   '+expected
        if column=='LC':expected=expected+'    '
        if single or end in ('L','W'):expected+='\n'
        self.assertEqual(self.output.getvalue(),expected)
        self.assertEqual(vm.console.wait_count,1 if end=='W' else 0)
    return check
for body in ('','V','S','FORM','FORMS'):
    for style in ('','K','D'):
        for end in ('','L','W'):
            setattr(RegistryA7,'test_variant_PRINT'+body+style+end,variant_test(body,style,end))
        setattr(RegistryA7,'test_variant_PRINTSINGLE'+body+style,variant_test(body,style,'',True))
for body in ('','FORM'):
    for column in ('C','LC'):
        for style in ('','K','D'):
            setattr(RegistryA7,'test_variant_PRINT'+body+column+style,variant_test(body,style,'',column=column))

class RegistryIntegrationA7(Harness):
    def test_describe_without_game(self):
        from pyemuera.cli import main
        from contextlib import redirect_stdout
        import io
        out=io.StringIO()
        with redirect_stdout(out):rc=main(['--describe','PRINTFORMW'])
        d=json.loads(out.getvalue());self.assertEqual(rc,0);self.assertTrue(d['command']['wait']);self.assertEqual(d['command']['argument_mode'],'form')
    def test_fingerprint_is_stable(self):
        from pyemuera.registry import fingerprint
        self.assertEqual(fingerprint(),fingerprint());self.assertEqual(len(fingerprint()),64)
    def test_input_print_inside_method_rejected(self):
        vm=self.make('@MAIN\nA=F()\nRETURN\n@F\n#FUNCTION\nPRINTW x\nRETURNF 1')
        with self.assertRaises(EraError):vm.call('MAIN')
    def test_sif_data_block_rejected(self):
        with self.assertRaises(EraError):self.make('@MAIN\nSIF 1\nPRINTDATA\nDATA x\nENDDATA')

class LengthContractsA7(Harness):
    def test_strlen_statement_is_raw_not_expression(self):
        vm=self.script('STRLEN 日本語\nA=RESULT');self.assertEqual(vm.get('A'),6)
    def test_strlenu_statement_counts_quotes_literally(self):
        vm=self.script('STRLENU "日本"\nA=RESULT');self.assertEqual(vm.get('A'),4)
    def test_strlen_expression_stays_expression(self):
        with self.assertRaises(EraError) as error:self.make().eval('STRLEN("日本")')
        self.assertEqual(error.exception.code,'E_FUNCTION')
        self.assertEqual(error.exception.message,'命令名"STRLEN"が関数のように使われています')
    def test_strlen_raw_not_misidentified_assignment(self):
        self.assertEqual(command('STRLEN -='),('STRLEN','-='));vm=self.script('STRLEN -=\nA=RESULT');self.assertEqual(vm.get('A'),2)
