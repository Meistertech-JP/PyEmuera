"""Row-local PRINT_SPACE projection invalidation without changing native geometry.

Cells are the existing CLI approximation. These fixtures exercise ownership and
stale-row reuse, not a new native GUI/font-width observation.
"""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyemuera.console import Console
from pyemuera.platform1824 import execute
from pyemuera.startup import emit_startup


def space(console, value):
    vm = SimpleNamespace(console=console, args=lambda arg: [int(arg)])
    with patch.object(console, 'warning'):
        execute(vm, {'name': 'PRINT_SPACE'}, str(value))


class RowProjectionLifecycle(unittest.TestCase):
    def test_same_row_retains_fractional_space(self):
        console = Console(output=io.StringIO())
        space(console, 25)
        self.assertEqual(console.current, '')
        space(console, 25)
        self.assertEqual(console.current, ' ')

    def test_clearline_cannot_reuse_deleted_row_fraction(self):
        console = Console(output=io.StringIO())
        space(console, 25)
        console.write('old', True)
        console.clear_lines(1)
        self.assertEqual(console.line_count, 0)
        space(console, 25)
        self.assertEqual(console.current, '')
        self.assertEqual(console.shape_remainder, (0, 25))

    def test_reuse_replaces_fraction_along_with_current_row(self):
        console = Console(output=io.StringIO())
        space(console, 25)
        with patch.object(console, 'warning'):
            console.reuse_line('')
        space(console, 25)
        self.assertEqual(console.current, '')

    def test_discard_cancels_fractional_pending_row(self):
        console = Console(output=io.StringIO())
        space(console, 25)
        console.discard_current()
        space(console, 25)
        self.assertEqual(console.current, '')

    def test_completed_row_invalidates_existing_projection(self):
        console = Console(output=io.StringIO())
        space(console, 25)
        console.write('', True)
        self.assertEqual(console.shape_remainder, (None, 0))
        space(console, 25)
        self.assertEqual(console.shape_remainder, (1, 25))
        self.assertEqual(console.current, '')

    def test_host_echo_commits_row_and_invalidates_existing_fraction(self):
        console = Console(output=io.StringIO())
        space(console, 25)
        console._host_line_echo = True
        console._input_echo('7')
        self.assertEqual(console.shape_remainder, (None, 0))
        self.assertEqual(list(console.lines), ['7'])

    def test_reset_operations_do_not_eagerly_create_shape_state(self):
        for reset in ('newline', 'clear', 'reuse', 'discard'):
            with self.subTest(reset=reset):
                console = Console(output=io.StringIO())
                with patch.object(console, 'warning'):
                    if reset == 'newline':
                        console.write('healthy', True)
                    elif reset == 'clear':
                        console.write('healthy', True)
                        console.clear_lines(1)
                    elif reset == 'reuse':
                        console.reuse_line('healthy')
                    else:
                        console.discard_current()
                self.assertFalse(hasattr(console, 'shape_remainder'))

    def test_failure_before_logical_commit_preserves_existing_fraction(self):
        class Failure(io.StringIO):
            fail = False

            def write(self, text):
                if self.fail:
                    raise OSError('neutral row commit failure')
                return super().write(text)
        output = Failure()
        console = Console(output=output)
        space(console, 25)
        before = console.shape_remainder
        output.fail = True
        with self.assertRaises(OSError):
            console.write('broken', True)
        self.assertEqual(console.shape_remainder, before)
        console.close()
        self.assertEqual(console.shape_remainder, before)
        self.assertEqual(console.line_count, 0)

    def test_console_instances_do_not_share_fraction(self):
        left = Console(output=io.StringIO())
        right = Console(output=io.StringIO())
        space(left, 25)
        self.assertFalse(hasattr(right, 'shape_remainder'))
        space(right, 25)
        space(left, 25)
        self.assertEqual(left.current, ' ')
        self.assertEqual(right.current, '')

    def test_lightweight_console_still_uses_existing_optional_state(self):
        calls = []
        console = SimpleNamespace(skip_print=False, line_count=0, display_elements=[],
                                  warning=lambda *args: None,
                                  write=lambda text, **kwargs: calls.append((text, kwargs)))
        space(console, 25)
        space(console, 25)
        self.assertEqual([text for text, _ in calls], ['', ' '])
        self.assertEqual(console.shape_remainder, (0, 0))

    def test_startup_marker_stays_lazy_once_per_console(self):
        console = Console(output=io.StringIO())
        self.assertFalse(hasattr(console, '_startup_emitted'))
        settings = SimpleNamespace(load_label='label')
        emit_startup(console, settings, {})
        emit_startup(console, SimpleNamespace(load_label='changed'), {})
        self.assertTrue(console._startup_emitted)
        self.assertEqual(list(console.lines), ['label'])

    def test_startup_suppression_and_failure_keep_existing_sticky_marker(self):
        suppressed = Console(output=io.StringIO())
        emit_startup(suppressed, SimpleNamespace(load_label='label'),
                     {'ロード時にレポートを表示する': 'YES'})
        self.assertTrue(suppressed._startup_emitted)
        self.assertEqual(list(suppressed.lines), [])
        class Failure(io.StringIO):
            def write(self, text):
                raise OSError('neutral startup write failure')
        failed = Console(output=Failure())
        with self.assertRaises(OSError):
            emit_startup(failed, SimpleNamespace(load_label='label'), {})
        self.assertTrue(failed._startup_emitted)
        emit_startup(failed, SimpleNamespace(load_label='second'), {})
        self.assertEqual(list(failed.lines), [])


class MarkupCachePublication(unittest.TestCase):
    def test_first_construction_failure_does_not_publish_success_key(self):
        from pyemuera.html1824 import MarkupStyle
        console = Console(output=io.StringIO())
        with patch('pyemuera.html1824.MarkupStyle', side_effect=RuntimeError('neutral style build')):
            with self.assertRaisesRegex(RuntimeError, '^neutral style build$'):
                console.write('failed')
        self.assertIsNone(console._markup_signature)
        self.assertIsNone(console._markup_style)
        self.assertEqual(console.markup_current, [])
        self.assertEqual(console.current, '')
        self.assertIsNone(console._output_failure)
        console.write('retry')
        self.assertIsInstance(console._markup_style, MarkupStyle)
        self.assertEqual(console.markup_current[0][1].color, 0xc0c0c0)
        self.assertEqual(console.current, 'retry')

    def test_changed_style_failure_keeps_prior_cache_and_retries_new_style(self):
        console = Console(output=io.StringIO())
        console.ui = {'color': 0x123456, 'bgcolor': 0, 'style': 0, 'font': 'mono', 'alignment': 'LEFT'}
        console.write('old', True)
        old_key = console._markup_signature
        old_style = console._markup_style
        old_history = list(console.markup_lines)
        console.ui['color'] = 0x654321
        with patch('pyemuera.html1824.MarkupStyle', side_effect=RuntimeError('neutral style rebuild')):
            with self.assertRaisesRegex(RuntimeError, '^neutral style rebuild$'):
                console.write('failed')
        self.assertEqual(console._markup_signature, old_key)
        self.assertIs(console._markup_style, old_style)
        self.assertEqual(list(console.markup_lines), old_history)
        self.assertEqual(list(console.lines), ['old'])
        self.assertEqual(console.markup_current, [])
        self.assertEqual(console.current, '')
        console.write('retry')
        self.assertNotEqual(console._markup_signature, old_key)
        self.assertEqual(console._markup_style.color, 0x654321)
        self.assertEqual(console.markup_current[0][1].color, 0x654321)
        self.assertEqual(list(console.lines), ['old'])
