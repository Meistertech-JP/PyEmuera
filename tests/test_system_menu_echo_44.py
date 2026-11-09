"""Native-source system menu echo assertions for the selected runtime.

No Program, GameData, VM, OS console, GUI, sleep or game is constructed.
Uses the same selected pyemuera modules in discovery and the exact-pyz runner.
"""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera.console import Console
from pyemuera.errors import EraError
from pyemuera import shop_purchase, input_commands
from pyemuera import default_title as TITLE, flow as FLOW
from pyemuera.registry import command_spec

class Stop(BaseException):
    pass

class ObservedConsole(Console):
    def __init__(self, entries):
        super().__init__(entries, output=io.StringIO(), no_wait=False)
        self.echoes = []
        self.warnings = []

    def _input_echo(self, text):
        self.echoes.append(text)
        return super()._input_echo(text)

    def warning(self, *args):
        self.warnings.append(args)

def vm_for(console, limit=0):
    writes = []
    return SimpleNamespace(console=console, writes=writes,
                           set=lambda n, v: writes.append((n, v)),
                           tick=lambda: None,
                           data=SimpleNamespace(settings=SimpleNamespace(shop_limit=limit)))

class NativeSystemMenuContracts(unittest.TestCase):
    def test_canonical_title_zero_one_echo_once(self):
        for text in ('0', '1'):
            with self.subTest(text=text):
                con = ObservedConsole([text])
                vm = vm_for(con)
                self.assertEqual(TITLE.select(vm), int(text))
                self.assertEqual(con.echoes, [text])
                self.assertEqual(list(con.lines), [text])
                self.assertEqual(con.line_count, 1)
                self.assertEqual(vm.writes, [('RESULT', int(text))])

    def test_all_accepted_numeric_selections_echo_before_retry(self):
        for text in ('-1', '2', '-9223372036854775808', '9223372036854775807'):
            with self.subTest(text=text):
                con = ObservedConsole([text, '0'])
                self.assertEqual(TITLE.select(vm_for(con)), 0)
                self.assertEqual(con.echoes, [text, '0'])

    def test_native_retains_accepted_original_numeric_spelling(self):
        for text in ('+00', ' 0 ', '-0', '000', '\t0\t'):
            with self.subTest(text=text):
                con = ObservedConsole([text])
                self.assertEqual(TITLE.select(vm_for(con)), 0)
                # EmueraConsole.doInputToEmueraProgram prints original str.
                self.assertEqual(con.echoes, [text])
                self.assertEqual(list(con.lines), [text])

    def test_native_title_reject_replaces_echo_not_completed_extra_rows(self):
        con = ObservedConsole(['2', '0'])
        self.assertEqual(TITLE.select(vm_for(con)), 0)
        # Native endOpenning deletes echoed 2, prints a temporary message;
        # next accepted input replaces it. Only the accepted 0 remains.
        self.assertEqual(list(con.lines), ['0'])
        self.assertEqual(con.line_count, 1)

    def test_invalid_numeric_syntax_or_overflow_replay_never_echoes(self):
        for text in ('bad', '', '1.0', '1e2', '0x0', '9223372036854775808', '-9223372036854775809'):
            with self.subTest(text=text):
                con = ObservedConsole([text])
                with self.assertRaises(EraError) as caught:
                    TITLE.select(vm_for(con))
                self.assertEqual(caught.exception.code, 'E_INPUT')
                self.assertEqual(con.echoes, [])

    def test_malformed_typed_record_never_echoes(self):
        con = ObservedConsole([{'kind': 'string', 'text': '0'}])
        with self.assertRaises(EraError) as caught:
            TITLE.select(vm_for(con))
        self.assertEqual(caught.exception.code, 'E_REPLAY')
        self.assertEqual(con.input_count, 0)
        self.assertEqual(con.echoes, [])

    def test_typed_valid_integer_record_echoes_once(self):
        con = ObservedConsole([{'kind': 'integer', 'text': '0', 'timeout': False}])
        self.assertEqual(TITLE.select(vm_for(con)), 0)
        self.assertEqual(con.echoes, ['0'])

    def test_shop_zero_dispatch_echoes_once_before_usershop(self):
        con = ObservedConsole(['0'])
        vm = vm_for(con, limit=0)
        def phase(vm, name, **kw):
            if name == 'USERSHOP':
                self.assertEqual(con.echoes, ['0'])
                self.assertEqual(vm.writes, [('RESULT', 0)])
                raise Stop()
        with patch.object(FLOW, 'phase_call', side_effect=phase):
            with self.assertRaises(Stop):
                FLOW.shop(vm, loaded=True)
        self.assertEqual(con.line_count, 1)

    def test_native_unsold_and_unaffordable_retry_remove_rejected_echo(self):
        for sold in (False, True):
            with self.subTest(sold=sold):
                con = ObservedConsole(['0', '-1'])
                vm = vm_for(con, limit=1)
                def phase(vm, name, **kw):
                    if name == 'USERSHOP':
                        raise Stop()
                with patch.object(FLOW, 'phase_call', side_effect=phase), \
                     patch.object(shop_purchase, 'item_on_sale', return_value=sold), \
                     patch.object(shop_purchase, 'buy_item', return_value=False):
                    with self.assertRaises(Stop):
                        FLOW.shop(vm, loaded=True)
                self.assertEqual(list(con.lines), ['-1'])
                self.assertEqual(con.line_count, 1)

    def test_command_input_echo_unchanged_not_doubled(self):
        con = ObservedConsole(['0'])
        vm = vm_for(con)
        self.assertTrue(input_commands.execute(vm, {**command_spec('INPUT'), 'name': 'INPUT'}, ''))
        self.assertEqual(con.echoes, ['0'])
        self.assertEqual(con.line_count, 1)

    def test_terminal_host_echo_logical_only_not_second_physical_copy(self):
        class Host(ObservedConsole):
            def _read_input_entry(self, deadline, one, any_key):
                self._host_line_echo = True
                return '0', False
        con = Host(None)
        self.assertEqual(TITLE.select(vm_for(con)), 0)
        self.assertEqual(list(con.lines), ['0'])
        self.assertEqual(con.line_count, 1)
        self.assertNotIn('0', con.output.getvalue())

    def test_input_exception_does_not_echo_or_write_result(self):
        con = ObservedConsole([])
        vm = vm_for(con)
        with patch.object(con, 'input', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                TITLE.select(vm)
        self.assertEqual(con.echoes, [])
        self.assertEqual(vm.writes, [])

if __name__ == '__main__':
    unittest.main()
