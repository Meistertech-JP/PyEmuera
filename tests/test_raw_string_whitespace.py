"""Raw '=' follows native SP_SET / AnalyseFormattedString(trim=true).

Native source: ArgumentBuilder.cs:773-781, LexicalAnalyzer.cs:1272-1275.
These expected values are contractual literals, never baseline-generated goldens.
"""
import json
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera.data import Ref
from pyemuera.runtime import Frame, VM
from unittest.mock import patch
from pyemuera.text import find_assignment

# RHS / native final value. ASCII trimming applies to boundary literal segments,
# after escape decoding, never to substituted values.
RAW_CASES = (
    ('plain', 'X', 'X'),
    ('ascii_edges', ' \tX \t', 'X'),
    ('ascii_only', ' \t ', ''),
    ('u3000_edges', '\u3000X\u3000', '\u3000X\u3000'),
    ('u3000_only', '\u3000\u3000', '\u3000\u3000'),
    ('mixed_outer_ascii', ' \t\u3000X\u3000 \t', '\u3000X\u3000'),
    ('mixed_inner_ascii', '\u3000 \tX \t\u3000', '\u3000 \tX \t\u3000'),
    ('unicode_space_edges', '\u2003X\u00a0', '\u2003X\u00a0'),
    ('ascii_before_fullwidth_end', 'X \u3000\u3000', 'X \u3000\u3000'),
    ('escape_ascii_edges', r'\s\tX\t\s', 'X'),
    ('escape_u3000_edges', r'\SX\S', '\u3000X\u3000'),
    ('escape_ascii_before_u3000', r'X\s\S', 'X \u3000'),
    ('escaped_only_ascii', r'\s\t', ''),
    ('substitution_spaces', '%WS:7%', ' \u3000Q\u3000 '),
    ('literal_trim_around_substitution', r'\s%WS:7%\t', ' \u3000Q\u3000 '),
    ('mixed_form', ' \u3000{2+3} \u3000 ', '\u30005 \u3000'),
)

class RawStringWhitespace(Harness):
    def ready(self):
        vm = self.make(headers='#DIMS SAVEDATA WS,8',
                       csv={'Chara0.csv': '番号,0\nCSTR,0,csv\u3000 '})
        vm.set('WS:7', ' \u3000Q\u3000 ')
        return vm

    def test_native_literal_and_form_boundary_matrix(self):
        for label, rhs, expected in RAW_CASES:
            with self.subTest(case=label):
                vm = self.make('@MAIN\nWS = ' + rhs + '\nRETURN',
                               headers='#DIMS SAVEDATA WS,8')
                vm.set('WS:7', ' \u3000Q\u3000 ')
                vm.call('MAIN')
                self.assertEqual(vm.get('WS'), expected)

    def test_exact_strings_survive_json_save_and_restore(self):
        vm = self.ready()
        vm.call('MAIN')
        vm.data.add_character(0)
        expected = ['\u3000X\u3000', '\u3000\u3000', 'X \u3000', '\u2003X\u00a0']
        for i, value in enumerate(expected):
            vm._assignment('WS:' + str(i) + ' = ' + value)
        vm._assignment('CSTR:0:0 = \u3000C\u3000')
        before_rng = vm.rng.getstate()
        vm.saves.write(14, 'raw whitespace')
        saved = json.loads(vm.saves.path(14).read_text(encoding='utf-8'))
        actual = {tuple(k): v for k, v in saved['variables']['WS']['values']}
        for i, value in enumerate(expected):
            self.assertEqual(actual[(i,)], value)
            vm.set('WS:' + str(i), 'changed')
        vm.set('CSTR:0:0', 'changed')
        self.assertEqual(vm.saves.load(14), 1)
        self.assertEqual([vm.get('WS:' + str(i)) for i in range(4)], expected)
        self.assertEqual(vm.get('CSTR:0:0'), '\u3000C\u3000')
        self.assertEqual(vm.rng.getstate(), before_rng)

    def test_quoted_expression_and_compounds_keep_exact_values(self):
        vm = self.script('STR \'= " \u3000Q\u3000 "\nSTR += " \u3000"\nSTR *= 2')
        self.assertEqual(vm.get('STR'), (' \u3000Q\u3000  \u3000') * 2)

    def test_numeric_and_increment_unicode_suffixes_keep_expression_policy(self):
        vm = self.script('A = 2\u3000\nA++\u3000\n++A\u3000\nA--\u3000\n--A\u3000\nA += 5\u3000')
        self.assertEqual(vm.get('A'), 7)

    def test_comments_stay_source_comments(self):
        vm = self.script('STR = \u3000X\u3000 \t; comment\nA = 3 ; numeric\nA++\u3000 ; postfix')
        self.assertEqual(vm.get('STR'), '\u3000X\u3000')
        self.assertEqual(vm.get('A'), 4)

    def test_rhs_runs_before_destination_once_on_cold_and_warm_cache(self):
        vm = self.ready()
        text = 'WS:(A++) = {A++}\u3000'
        for _ in range(2):
            vm.set('A', 0)
            vm._assignment(text)
            self.assertEqual((vm.get('A'), vm.get('WS:1')), (2, '0\u3000'))
        self.assertEqual(len(vm._assignment_cache[text]), 4)

    def test_runtime_error_keeps_rhs_effects_and_does_not_evaluate_destination(self):
        vm = self.ready()
        for _ in range(2):
            vm.set('A', 0)
            with self.assertRaises(EraError) as error:
                vm._assignment('WS:(A++) = {A++}{1/0}\u3000')
            self.assertEqual(error.exception.code, 'E_ARITH')
            self.assertEqual(vm.get('A'), 1)

    def test_failed_destination_follows_rhs_and_preserves_string(self):
        vm = self.ready()
        with self.assertRaises(EraError) as error:
            vm._assignment('WS:99 = {A++}\u3000')
        self.assertEqual(error.exception.code, 'E_INDEX')
        self.assertEqual(vm.get('A'), 1)
        self.assertEqual(vm.get('WS'), '')

    def test_same_cache_plan_uses_live_reference_type(self):
        vm = self.ready()
        scope = {'DYN': Ref(vm.lookup('A'), (0,))}
        vm.frames.append(Frame(vm.program.functions['MAIN'][0], scope))
        text = 'DYN = \u30007\u3000'
        vm._assignment(text)
        self.assertEqual(vm.get('A'), 7)
        plan = vm._assignment_cache[text]
        nodes = plan[3]
        scope['DYN'] = Ref(vm.lookup('WS'), (0,))
        vm._assignment(text)
        self.assertEqual(vm.get('WS'), '\u30007\u3000')
        self.assertIs(vm._assignment_cache[text], plan)
        self.assertIs(plan[3], nodes)
        scope['DYN'] = Ref(vm.lookup('A'), (0,))
        vm._assignment(text)
        self.assertEqual(vm.get('A'), 7)
        self.assertIs(plan[3], nodes)

    def test_cache_hit_keeps_literal_and_does_not_capture_values(self):
        vm = self.ready()
        text = 'WS = \u3000{A}\u3000'
        vm.set('A', 3); vm._assignment(text)
        plan = vm._assignment_cache[text]
        vm.set('A', 8); vm._assignment(text)
        self.assertEqual(vm.get('WS'), '\u30008\u3000')
        self.assertIs(vm._assignment_cache[text], plan)

    def test_fixed_literals_do_not_consume_rng(self):
        vm = self.ready(); before = vm.rng.getstate()
        vm._assignment('WS = \u3000literal\u3000')
        self.assertEqual(vm.rng.getstate(), before)

    def test_csv_and_initial_sentinels_are_outside_this_patch(self):
        vm = self.ready(); vm.data.add_character(0)
        self.assertEqual(vm.get('CSTR:0:0'), 'csv')
        self.assertEqual((vm.get('NEXTCOM'), vm.get('PREVCOM')), (0, 0))

    def test_default_scanner_callers_are_unchanged(self):
        text = 'STR = \u3000X\u3000 '
        self.assertEqual(find_assignment(text), ('STR', '=', 'X\u3000 '))
        self.assertEqual(find_assignment(text, preserve_rhs=True), ('STR', '=', '\u3000X\u3000 '))
        self.assertIsNone(find_assignment('A == 5'))
        self.assertEqual(find_assignment('A == 5', legacy=True), ('A', '==', '5'))

    def test_invalid_assignment_does_not_enter_syntax_cache(self):
        vm = self.ready()
        with self.assertRaises(EraError): vm._assignment('not assignment')
        self.assertNotIn('not assignment', vm._assignment_cache)


    def test_single_argument_host_hook_controls_final_value(self):
        vm = self.ready(); seen = []
        def host(text):
            seen.append(text)
            self.assertIsInstance(text, str)
            return ' host value \t'
        with patch.object(vm, 'format', host):
            vm._assignment('WS = \u3000X\u3000')
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], '\u3000X\u3000')
        self.assertEqual(vm.get('WS'), ' host value \t')

    def test_single_argument_forwarding_hook_retains_native_boundary_policy(self):
        vm = self.ready(); ordinary = vm.format; seen = []
        def host(text):
            seen.append(text)
            return ordinary(text)
        with patch.object(vm, 'format', host):
            vm._assignment(r'WS = \s\u3000X\u3000\t'.replace(r'\u3000', '\u3000'))
        self.assertEqual(len(seen), 1)
        self.assertEqual(vm.get('WS'), '\u3000X\u3000')

    def test_vm_class_host_override_is_called_once(self):
        vm = self.ready(); original = VM.format; seen = []
        def host(instance, text):
            seen.append(text)
            return original(instance, text)
        with patch.object(VM, 'format', host):
            vm._assignment('WS = \u3000X\u3000')
        self.assertEqual(len(seen), 1)
        self.assertEqual(vm.get('WS'), '\u3000X\u3000')

    def test_subclass_host_override_can_delegate_to_super(self):
        seen = []
        class HostVM(VM):
            def format(self, text):
                seen.append(text)
                return super().format(text)
        vm = self.ready(); vm.__class__ = HostVM
        vm._assignment('WS = \u3000X\u3000')
        self.assertEqual(len(seen), 1)
        self.assertEqual(vm.get('WS'), '\u3000X\u3000')

    def test_host_hook_error_is_not_retried_and_precedes_lhs(self):
        vm = self.ready(); seen = []; failure = EraError('host blocked', code='E_RUNTIME')
        def host(text):
            seen.append(text)
            raise failure
        with patch.object(vm, 'format', host):
            with self.assertRaises(EraError) as error:
                vm._assignment('WS:(A++) = \u3000X\u3000')
        self.assertIs(error.exception, failure)
        self.assertEqual(len(seen), 1)
        self.assertEqual(vm.get('A'), 0)
        self.assertEqual(vm.format(' X \t'), ' X \t')

    def test_nested_ordinary_format_has_no_assignment_trim_context(self):
        vm = self.ready(); ordinary = vm.format; nested = []
        def host(text):
            nested.append(ordinary(' inner \t'))
            return ordinary(text)
        with patch.object(vm, 'format', host):
            vm._assignment(r'WS = \sX\t')
        self.assertEqual(nested, [' inner \t'])
        self.assertEqual(vm.get('WS'), 'X')
        self.assertEqual(vm.format(' after \t'), ' after \t')

    def test_base_render_receives_plain_str_for_existing_lexical_cache(self):
        from pyemuera import runtime
        vm = self.ready(); original = runtime.render
        with patch.object(runtime, 'render', wraps=original) as rendered:
            vm._assignment('WS = \u3000X\u3000')
        self.assertIs(type(rendered.call_args.args[0]), str)
        self.assertEqual(rendered.call_args.kwargs, {'trim_edges': True})

    def test_host_descriptor_is_read_once_before_rhs_and_lhs_effects(self):
        events = []; original = VM.format
        class HostVM(VM):
            @property
            def format(self):
                events.append(('read', self.get('A')))
                def host(text):
                    events.append(('call', self.get('A')))
                    return original(self, text)
                return host
        vm = self.ready(); vm.__class__ = HostVM
        vm._assignment('WS:(A++) = {A++}\u3000')
        self.assertEqual(events, [('read', 0), ('call', 0)])
        self.assertEqual((vm.get('A'), vm.get('WS:1')), (2, '0\u3000'))
