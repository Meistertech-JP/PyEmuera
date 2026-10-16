"""Controller safety/evidence checks; no Windows hardware acceptance inferred."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1]/'tools/windows_host_retest_r42.py'
spec = importlib.util.spec_from_file_location('windows_host_retest_r42', path)
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class WindowsHostControllerR42(unittest.TestCase):
    def test_guard_requires_live_owned_pid_nonce_visible_hwnd_and_foreground(self):
        identity = dict(pid=10, nonce='token', hwnd=20, host_pid=30)
        observation = dict(hwnd=20, host_pid=30, visible=True, foreground_hwnd=20)
        self.assertTrue(controller.guard(identity, observation, pid=10, nonce='token', alive=True))
        for patch in (dict(hwnd=21), dict(host_pid=31), dict(visible=False), dict(foreground_hwnd=21)):
            with self.subTest(patch=patch):
                self.assertFalse(controller.guard(identity, dict(observation, **patch), pid=10, nonce='token', alive=True))
        self.assertFalse(controller.guard(identity, observation, pid=11, nonce='token', alive=True))
        self.assertFalse(controller.guard(identity, observation, pid=10, nonce='other', alive=True))
        self.assertFalse(controller.guard(identity, observation, pid=10, nonce='token', alive=False))

    def test_hidden_or_missing_console_identity_is_blocked(self):
        self.assertFalse(controller.guard({}, {}, pid=10, nonce='token', alive=True))
        self.assertFalse(controller.guard(dict(pid=10,nonce='token',hwnd=0,host_pid=30),
                                          dict(hwnd=0,host_pid=30,visible=True,foreground_hwnd=0),
                                          pid=10,nonce='token',alive=True))

    def test_reader_completion_does_not_imply_cancel_api_or_physical_event_success(self):
        report = controller.projection(dict(host_input=dict(reader_completed=True,cancellation_requested=True),
                                           interruption=dict(signal='SIGINT')),
                                       dict(console_mode_restored=True), exit_code=130, elapsed=.3, guard_started=True)
        self.assertTrue(report['reader_completed'])
        self.assertTrue(report['signal_received'])
        self.assertTrue(report['cancel_requested'])
        self.assertIsNone(report['event_sent'])
        self.assertIsNone(report['cancel_api_result'])
        self.assertFalse(report['full_windows_acceptance'])
        self.assertEqual(report['status'], 'OBSERVED_NOT_ACCEPTED')

    def test_absent_session_fields_remain_unknown(self):
        report = controller.projection({}, {}, exit_code=2, elapsed=90, guard_started=False)
        for field in ('signal_received','reader_completed','cancel_requested','cancel_api_result','console_mode_restored'):
            self.assertIsNone(report[field])
        self.assertEqual(report['status'],'BLOCKED')

    def test_forced_cleanup_cannot_be_success(self):
        report=controller.projection(dict(interruption=dict(signal='SIGINT')),{},exit_code=130,elapsed=2,
                                     guard_started=True,forced=True)
        self.assertEqual(report['status'],'BLOCKED')
