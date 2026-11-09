import dataclasses
import inspect
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pyemuera.console import Console
from pyemuera.errors import EraError, Unsupported
from pyemuera.system_input import AcceptedInteger, LegacyInteger, acquire, echo, reject


class QuietConsole(Console):
    def __init__(self, entries):
        super().__init__(entries, output=io.StringIO())
        self.notes = []

    def warning(self, *args):
        self.notes.append(args)


class ReceiptContracts(unittest.TestCase):
    def test_immutable_raw_value_receipt_and_normal_public_return(self):
        c = QuietConsole([' +00 ', '1'])
        receipt = acquire(c)
        self.assertEqual(receipt, AcceptedInteger(' +00 ', 0, False))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.raw = 'different'
        self.assertIs(type(c.input()), int)
        self.assertNotIn('_system_integer_acceptance', c.__dict__)

    def test_signature_is_unchanged(self):
        self.assertEqual(str(inspect.signature(Console.input)),
                         '(self, string=False, default=None, *, kind=None, force=False, timeout_ms=None, one=False, any_key=False)')

    def test_read_validate_journal_once_and_echo_after_acceptance(self):
        c = QuietConsole(['+00'])
        events = []
        c.journal = SimpleNamespace(note=lambda *a, **kw: events.append(('request', a)),
                                    input=lambda *a: events.append(('journal', a)))
        read, validate = c._read_input_entry, c._validate_input_entry
        def rd(*args):
            events.append(('read', c.input_count))
            return read(*args)
        def check(*args):
            events.append(('validate', c.input_count))
            return validate(*args)
        with patch.object(c, '_read_input_entry', side_effect=rd) as r, \
             patch.object(c, '_validate_input_entry', side_effect=check) as v:
            receipt = acquire(c)
        self.assertEqual((r.call_count, v.call_count, c.input_count), (1, 1, 1))
        self.assertEqual([x[0] for x in events], ['request', 'read', 'validate', 'journal'])
        self.assertEqual(events[-1][1], ('integer', '+00', False))
        self.assertEqual(c.line_count, 0)
        echo(c, receipt)
        self.assertEqual(list(c.lines), ['+00'])

    def test_old_input_override_called_once_without_new_keywords_or_echo(self):
        class Old(QuietConsole):
            def input(self):
                self.calls = getattr(self, 'calls', 0) + 1
                return 0
        c = Old(None)
        result = acquire(c)
        self.assertEqual(result, LegacyInteger(0))
        self.assertIsNone(echo(c, result))
        self.assertEqual((c.calls, c.line_count), (1, 0))

    def test_forwarding_input_override_keeps_old_host_policy(self):
        class Old(QuietConsole):
            def input(self):
                self.calls = getattr(self, 'calls', 0) + 1
                return super().input()
        c = Old(['+00'])
        self.assertEqual(acquire(c), LegacyInteger(0))
        self.assertEqual((c.calls, c.input_count, c.line_count), (1, 1, 0))

    def test_input_only_stub_and_explicit_protocol(self):
        stub = SimpleNamespace(input=Mock(return_value=0))
        self.assertEqual(acquire(stub), LegacyInteger(0))
        stub.input.assert_called_once_with()
        class Host(QuietConsole):
            def input_system_integer(self):
                return AcceptedInteger('+00', 0, False)
        c = Host(None)
        echo(c, acquire(c))
        self.assertEqual(list(c.lines), ['+00'])

    def test_nested_system_acquisitions_have_independent_receipts(self):
        class Nested(QuietConsole):
            def _read_input_entry(self, *args):
                if not getattr(self, 'nested', False):
                    self.nested = True
                    self.inner = acquire(self)
                    self._host_line_echo = True
                    return ' +00 ', False
                return super()._read_input_entry(*args)
        c = Nested(['7'])
        outer = acquire(c)
        self.assertEqual(c.inner, AcceptedInteger('7', 7, False))
        self.assertEqual(outer, AcceptedInteger(' +00 ', 0, True))
        self.assertEqual(c.input_count, 2)
        self.assertNotIn('_system_integer_acceptance', c.__dict__)

    def test_nested_ordinary_input_cannot_claim_outer_receipt(self):
        class Nested(QuietConsole):
            def _read_input_entry(self, *args):
                if not getattr(self, 'nested', False):
                    self.nested = True
                    self.inner = self.input()
                    return '+00', False
                return super()._read_input_entry(*args)
        c = Nested(['7'])
        self.assertEqual(acquire(c), AcceptedInteger('+00', 0, False))
        self.assertEqual(c.inner, 7)

    def test_receipt_host_echo_does_not_use_later_mutated_flag(self):
        c = QuietConsole(None)
        c._host_line_echo = False
        echo(c, AcceptedInteger('0', 0, True))
        self.assertEqual(list(c.lines), ['0'])
        self.assertEqual(c.output.getvalue(), '')
        self.assertFalse(c._host_line_echo)

    def test_temporary_row_is_completed_then_replaced_on_next_accepted_echo(self):
        c = QuietConsole(['2', '0'])
        owner = echo(c, acquire(c))
        reject(c, owner, 'invalid', title=True)
        self.assertEqual((list(c.lines), c.line_count, c.current), (['invalid'], 1, ''))
        self.assertTrue(c._system_input_row.temporary)
        receipt = acquire(c)
        self.assertEqual(list(c.lines), ['invalid'])
        echo(c, receipt)
        self.assertEqual((list(c.lines), c.line_count), (['0'], 1))

    def test_temporary_row_survives_eof_and_bad_numeric_replay(self):
        for remaining, code in (([], 'E_INPUT_EOF'), (['bad'], 'E_INPUT')):
            with self.subTest(code=code):
                c = QuietConsole(['2'] + remaining)
                reject(c, echo(c, acquire(c)), 'invalid', title=True)
                with self.assertRaises(EraError) as caught:
                    acquire(c)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual((list(c.lines), c.line_count), (['invalid'], 1))
                self.assertNotIn('_system_integer_acceptance', c.__dict__)

    def test_pending_print_prefix_survives_temporary_row_replacement(self):
        c = QuietConsole(['2'])
        reject(c, echo(c, acquire(c)), 'invalid', title=True)
        c.write('prefix')
        self.assertEqual((list(c.lines), c.current, c.line_count), (['invalid'], 'prefix', 1))
        c.write('suffix', True)
        self.assertEqual((list(c.lines), c.line_count), (['prefixsuffix'], 1))
        self.assertEqual(list(c.log_lines), ['prefixsuffix'])

    def test_stale_owner_cannot_delete_a_new_row(self):
        c = QuietConsole(['2'])
        owner = echo(c, acquire(c))
        c.clear_lines(1)
        c.write('unrelated', True)
        with self.assertRaises(Unsupported):
            reject(c, owner, 'invalid', title=True)
        self.assertEqual(list(c.lines), ['unrelated'])

    def test_forwarded_echo_hook_called_once(self):
        class Hook(QuietConsole):
            def _input_echo(self, text):
                self.calls = getattr(self, 'calls', 0) + 1
                return super()._input_echo(text)
        c = Hook(['0'])
        echo(c, acquire(c))
        self.assertEqual((c.calls, c.line_count), (1, 1))

    def test_output_hook_interference_is_preserved_and_fails_closed(self):
        class Hook(QuietConsole):
            def _input_echo(self, text):
                super()._input_echo(text)
                self.write('hook output', True)
        c = Hook(['2'])
        with self.assertRaises(Unsupported):
            echo(c, acquire(c))
        self.assertEqual(list(c.lines), ['2', 'hook output'])
        self.assertNotIn('_system_integer_echo_call', c.__dict__)

    def test_error_cancellation_leave_no_receipt_for_later_call(self):
        c = QuietConsole(['0'])
        with patch.object(c, '_read_input_entry', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                acquire(c)
        self.assertNotIn('_system_integer_acceptance', c.__dict__)
        self.assertEqual(acquire(c), AcceptedInteger('0', 0, False))

    def test_public_timeout_and_malformed_record_contract_unchanged(self):
        c = QuietConsole([{'kind': 'timed_integer', 'text': '', 'timeout': True}])
        c.journal = SimpleNamespace(note=Mock(), input=Mock())
        self.assertEqual(c.input(default=19, kind='timed_integer', timeout_ms=166), 19)
        self.assertEqual((c.input_count, c.last_timeout, c.line_count), (1, True, 0))
        c.journal.input.assert_called_once_with('timed_integer', '', True)
        c = QuietConsole([{'kind': 'string', 'text': '0'}])
        c.journal = SimpleNamespace(note=Mock(), input=Mock())
        with self.assertRaises(EraError) as caught:
            acquire(c)
        self.assertEqual(caught.exception.code, 'E_REPLAY')
        self.assertEqual(c.input_count, 0)
        c.journal.input.assert_not_called()

    def test_echo_output_failure_is_not_retried(self):
        c = QuietConsole(['0'])
        receipt = acquire(c)
        c.output = SimpleNamespace(write=Mock(side_effect=OSError('disk fail')), flush=Mock())
        with self.assertRaises(OSError):
            echo(c, receipt)
        self.assertEqual((c.input_count, c.line_count), (1, 0))
        c.output.write.assert_called_once()
        self.assertNotIn('_system_integer_echo_call', c.__dict__)
