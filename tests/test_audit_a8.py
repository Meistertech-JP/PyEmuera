"""Bundled argument audit / dispatch invariants. Does not bundle the C# sources."""
import json,unittest
from pathlib import Path
from pyemuera.registry import COMMAND_SPECS,FUNCTION_SPECS,validate_document,fingerprint
from pyemuera.dispatcher import DISPATCH
from pyemuera.errors import EraError
from tools.reference_contracts import clean,balanced

class SourceAuditA8(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.doc=json.loads((Path(__file__).resolve().parent.parent/'SOURCE_AUDIT_1824.json').read_text())
    def test_source_registration_counts(self):
        self.assertEqual(len(self.doc['commands']),265);self.assertEqual(len(self.doc['functions']),160);self.assertEqual(len(self.doc['argument_builders']),54)
    def test_evidence_has_source_locations_and_hashes(self):
        for row in self.doc['commands']+self.doc['functions']:
            ev=row['contract']['registration'];self.assertGreater(ev['start_line'],0);self.assertGreaterEqual(ev['end_line'],ev['start_line']);self.assertRegex(ev['sha256'],r'^[a-f0-9]{64}$')
    def test_audit_fingerprint_matches_executable_tables(self):self.assertEqual(self.doc['language_specs_sha256'],fingerprint())
    def test_fixed_arity_has_no_mismatch(self):
        self.assertEqual(self.doc['counts']['fixed_arity_mismatches'],[])
        self.assertGreater(sum(row.get('fixed_arity_matches_source') is True for row in self.doc['functions']),50)
    def test_partial_results_are_not_renamed_exact(self):
        self.assertFalse(self.doc['full_compatibility']);self.assertTrue(any(r['status']=='partial_documented' for r in self.doc['commands']))
        self.assertFalse(any(r['all_argument_forms_verified'] for r in self.doc['commands']+self.doc['functions']))
    def test_new_command_families_actually_dispatch(self):
        families={'SAVECHARA':'character','LOADCHARA':'character','DELDATA':'save','INITRAND':'random','DUMPRAND':'random','TONEINPUT':'input','HTML_TAGSPLIT':'html','SPLIT':'array','CLEARTEXTBOX':'platform','REFBYNAME':'source_unimplemented'}
        for name,family in families.items():
            self.assertEqual(COMMAND_SPECS[name]['family'],family);self.assertIn(name,DISPATCH)
    def test_methods_use_reference_flags(self):
        self.assertFalse(COMMAND_SPECS['CALL']['method_safe']);self.assertTrue(COMMAND_SPECS['CALLF']['method_safe']);self.assertTrue(COMMAND_SPECS['INITRAND']['method_safe'])
        self.assertFalse(COMMAND_SPECS['PRINTFORMW']['method_safe']);self.assertTrue(COMMAND_SPECS['PRINTFORM']['method_safe'])
    def test_input_schema_rejects_bad_arity_and_flags(self):
        spec=dict(COMMAND_SPECS['TINPUT'])
        for key,val in [('max_args',True),('one','yes'),('method_safe',1)]:
            with self.subTest(key=key),self.assertRaises(EraError):validate_document({'schema_version':1,'commands':{'TINPUT':{**spec,key:val}}},'commands')
    def test_source_mask_preserves_lines_and_hides_comments(self):
        text='// { fake }\nclass Foo { string s="// { }"; /* } */ int x; }'
        mask=clean(text,True);self.assertEqual(mask.count('\n'),text.count('\n'))
        start=mask.index('{');self.assertEqual(balanced(mask,start),len(text))
    def test_original_reference_stubs_have_explicit_status(self):
        rows={r['name']:r for r in self.doc['commands']}
        for name in ['REF','REFBYNAME','SAVEVAR','LOADVAR']:self.assertEqual(rows[name]['status'],'source_unimplemented')
