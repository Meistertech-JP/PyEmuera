"""Captured numeric bad-comparer text; state checks are source-based Python proof.

The native hidden arrays/RESULT/RNG and CLR stack are not exposed by its log.
"""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.sort1824 import framework_list_order, _intro_sort, compare_int64

FIXTURES=Path(__file__).with_name('fixtures')
PROFILE=json.loads((FIXTURES/'r42_numeric_sort_diagnostic.json').read_text(encoding='utf-8'))
NEUTRAL=FIXTURES/'r42_numeric_sort_inconsistent31/ERB'
INTERNAL='ARRAYMSORT comparer produced inconsistent sort results'
KEYS=next(x['keys'] for x in json.loads((FIXTURES/'r41_sort_cases.json').read_text())['cases'] if x['case_id']=='inconsistent31')


class NumericSortDiagnostic(Harness):
    def original_vm(self):
        vm=self.make()
        # Keep the received source bytes exactly, including BOM and line endings.
        (vm.root/'ERB/Main.ERB').write_bytes((NEUTRAL/'Main.ERB').read_bytes())
        (vm.root/'ERB/Header.ERH').write_bytes((NEUTRAL/'Header.ERH').read_bytes())
        from pyemuera.program import Program
        from pyemuera.data import GameData
        from pyemuera.runtime import VM
        self.vm=VM(Program(vm.root),GameData(vm.root),vm.console,seed=42)
        return self.vm

    def arrays_vm(self):
        vm=self.make(headers='#DIM KEYS,32\n#DIM ROWS,32,2')
        for i,value in enumerate(KEYS):
            vm.set(f'KEYS:{i}',value);vm.set(f'ROWS:{i}:0',i+1);vm.set(f'ROWS:{i}:1',10001+i)
        vm.set('ROWS:31:1',917)
        return vm

    def test_captured_native_and_framework_messages_agree(self):
        fields=PROFILE['framework_probe_line'].split('|',3)
        self.assertEqual(PROFILE['native_body'],fields[2]+':'+fields[3])
        self.assertEqual(PROFILE['native_header'],'Main.ERBの96行目で予期しないエラーが発生しました:Emuera')
        for filename,sha in PROFILE['fixture_hashes'].items():
            self.assertEqual(hashlib.sha256((NEUTRAL.parent/filename).read_bytes()).hexdigest(),sha)

    def test_direct_api_retains_code_internal_message_and_cause(self):
        original=list(KEYS)
        with self.assertRaises(EraError) as caught:framework_list_order(original)
        error=caught.exception
        self.assertEqual(error.code,'E_ARGUMENT');self.assertEqual(error.message,INTERNAL)
        self.assertEqual(error.as_dict()['internal_message'],INTERNAL)
        self.assertEqual(error.diagnostic_message,PROFILE['native_body'])
        self.assertIsInstance(error.__cause__,IndexError)
        self.assertEqual(original,KEYS);self.assertIsNone(error.location)

    def test_received_fixture_stops_at_line96_without_post_sort_output(self):
        vm=self.original_vm()
        with self.assertRaises(EraError) as caught:vm.run()
        error=caught.exception
        self.assertEqual(error.code,'E_ARGUMENT');self.assertEqual(error.location.line,PROFILE['native_line'])
        self.assertEqual(Path(error.location.path).name,PROFILE['native_file'])
        self.assertEqual(error.as_dict()['diagnostic_message'],PROFILE['native_body'])
        self.assertNotIn('R41_SORT|',self.output.getvalue());self.assertNotIn('R41_ROW|',self.output.getvalue())
        self.assertEqual(vm.exit_reason,'error');self.assertEqual(vm.frames,[])

    def test_original_fixture_arrays_result_rng_unchanged_at_failure_stage(self):
        vm=self.original_vm();vm.set('RESULT',917);vm.set('RESULTS','retained')
        observed={};execute=vm.execute
        def observe(frame,ins,pc):
            if ins.location.line==96:
                observed['arrays']={n:copy.deepcopy(vm.lookup(n).values) for n in ('KEYS','ROWS')}
                observed['result']=(vm.get('RESULT'),vm.get('RESULTS'))
                observed['rng']=copy.deepcopy(vm.rng.getstate())
            return execute(frame,ins,pc)
        with patch.object(vm,'execute',side_effect=observe):
            with self.assertRaises(EraError):vm.run()
        self.assertEqual({n:vm.lookup(n).values for n in ('KEYS','ROWS')},observed['arrays'])
        self.assertEqual((vm.get('RESULT'),vm.get('RESULTS')),observed['result'])
        self.assertEqual(observed['result'],(917,'retained'))
        self.assertEqual(vm.rng.getstate(),observed['rng'])
        self.assertEqual(vm.get('ROWS:31:1'),917)

    def test_ignored_dynamic_subscripts_have_no_side_effect_on_failure(self):
        vm=self.arrays_vm();vm.set('A',41);vm.set('RESULT',917)
        before_rng=copy.deepcopy(vm.rng.getstate())
        before_arrays={n:copy.deepcopy(vm.lookup(n).values) for n in ('KEYS','ROWS')}
        with self.assertRaises(EraError) as caught:vm.eval('ARRAYMSORT(KEYS:(++A),ROWS:RAND(1000):(++A))')
        self.assertEqual(caught.exception.diagnostic_message,PROFILE['native_body'])
        self.assertEqual(vm.get('A'),41);self.assertEqual(vm.get('RESULT'),917)
        self.assertEqual(vm.rng.getstate(),before_rng)
        self.assertEqual({n:vm.lookup(n).values for n in ('KEYS','ROWS')},before_arrays)

    def test_unrelated_argument_error_keeps_its_diagnostic(self):
        vm=self.make()
        with self.assertRaises(EraError) as caught:vm.eval('ARRAYMSORT(1,2)')
        self.assertNotEqual(caught.exception.as_dict()['diagnostic_message'],PROFILE['native_body'])
        self.assertNotIn('FunctorComparer',str(caught.exception))

    def test_string_failure_is_not_presented_as_int64_comparer(self):
        with patch('pyemuera.sort1824._intro_sort',side_effect=IndexError('synthetic string fault')):
            with self.assertRaises(EraError) as caught:framework_list_order(['a','b'],string=True)
        self.assertEqual(caught.exception.code,'E_ARGUMENT')
        self.assertEqual(caught.exception.message,INTERNAL)
        self.assertIsNone(caught.exception.diagnostic_message)
        self.assertNotIn('System.Int64',str(caught.exception))

    def test_cli_error_report_keeps_python_classification_and_separate_body(self):
        from pyemuera.cli import main
        vm=self.original_vm();out=vm.root/'error.json';stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            result=main(['--no-wait','--seed','42','--error-report',str(out),str(vm.root)])
        error=json.loads(out.read_text())['error']
        self.assertEqual(result,1);self.assertEqual(error['code'],'E_ARGUMENT')
        self.assertEqual(error['message'],INTERNAL);self.assertEqual(error['internal_message'],INTERNAL)
        self.assertEqual(error['diagnostic_message'],PROFILE['native_body'])
        self.assertEqual(error['line'],96);self.assertNotIn('R41_SORT|',stdout.getvalue())
        self.assertIn(PROFILE['native_body'],stderr.getvalue())
        self.assertNotIn('System.Collections.Generic.IntrospectiveSortUtilities',stderr.getvalue())
        self.assertNotIn('internal_diagnostic',error)

    def test_detached_list_partial_order_matches_framework_probe(self):
        expected=[tuple(int(v) for v in item.split(':')) for item in PROFILE['framework_probe_partial_line'].split('|')[2:]]
        count,capacity=(int(v) for v in PROFILE['framework_probe_size_line'].split('|')[2:])
        items=[(value,i) for i,value in enumerate(KEYS)]+[(0,0)]*(capacity-count)
        with self.assertRaises(IndexError):
            _intro_sort(items,lambda a,b:compare_int64(a[0],b[0]),0,count-1,2*capacity.bit_length())
        self.assertEqual(items[:count],expected)
        self.assertNotEqual(items[:count],list(zip(KEYS,range(count))))
