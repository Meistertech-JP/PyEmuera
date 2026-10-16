"""OUTPUTLOG host I/O failures warn and return; other failures propagate."""

import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from test_core import Harness
from pyemuera import outputlog
from pyemuera.errors import EraError


SUCCESS = '※※※ログファイルをemuera.logに出力しました※※※'


class OutputlogB1(Harness):
    def make_log_vm(self):
        return self.make('@MAIN\nPRINTL before\nOUTPUTLOG\nA=7\nRETURN\n')

    def log_directory(self, vm):
        return vm.data.root / '.pyemuera' / 'logs'

    def run_quiet(self, vm):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            vm.call('MAIN')
        return stderr.getvalue()

    def assert_native_failure(self, vm, warning):
        self.assertEqual(vm.get('A'), 7)
        self.assertIn('ログの出力に失敗しました', warning)
        self.assertNotIn(SUCCESS, vm.console.lines)
        self.assertEqual(getattr(vm, 'outputlog_records', []), [])

    def test_native_target_directory_collision_warns_and_continues(self):
        vm = self.make_log_vm()
        target = self.log_directory(vm) / 'emuera.log'
        target.mkdir(parents=True)
        marker = target / 'keep.txt'
        marker.write_bytes(b'original')
        self.assert_native_failure(vm, self.run_quiet(vm))
        self.assertEqual(marker.read_bytes(), b'original')
        self.assertEqual(list(target.parent.glob('.writing-*')), [])

    def test_overlay_parent_file_collision_warns_and_preserves_file(self):
        vm = self.make_log_vm()
        overlay = vm.data.root / '.pyemuera'
        overlay.write_bytes(b'original')
        self.assert_native_failure(vm, self.run_quiet(vm))
        self.assertEqual(overlay.read_bytes(), b'original')

    def test_log_parent_file_collision_warns_and_preserves_file(self):
        vm = self.make_log_vm()
        folder = self.log_directory(vm)
        folder.parent.mkdir()
        folder.write_bytes(b'original')
        self.assert_native_failure(vm, self.run_quiet(vm))
        self.assertEqual(folder.read_bytes(), b'original')

    def test_atomic_replace_permission_failure_warns_and_continues(self):
        vm = self.make_log_vm()
        target = self.log_directory(vm) / 'emuera.log'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'old log')
        with patch('pyemuera.persistence.os.replace', side_effect=PermissionError('denied')):
            self.assert_native_failure(vm, self.run_quiet(vm))
        self.assertEqual(target.read_bytes(), b'old log')
        self.assertEqual(list(target.parent.glob('.writing-*')), [])

    def test_raw_oserror_from_native_write_still_warns_and_continues(self):
        vm = self.make_log_vm()
        with patch.object(vm.saves, 'atomic_write', side_effect=OSError('disk full')):
            self.assert_native_failure(vm, self.run_quiet(vm))

    def test_non_io_errors_and_interrupts_from_native_write_propagate(self):
        for error in (EraError('path', code='E_PATH'), EraError('script', code='E_RUNTIME'),
                      ValueError('bug'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__, code=getattr(error, 'code', None)):
                vm = self.make_log_vm()
                with patch.object(vm.saves, 'atomic_write', side_effect=error):
                    with self.assertRaises(type(error)) as caught:
                        outputlog.write(vm)
                self.assertIs(caught.exception, error)
                self.assertNotIn(SUCCESS, vm.console.lines)
                self.assertEqual(vm.get('A'), 0)

    def test_manifest_directory_collision_reports_partial_success(self):
        vm = self.make_log_vm()
        target = self.log_directory(vm) / 'outputlog-manifest.json'
        target.mkdir(parents=True)
        marker = target / 'keep.txt'
        marker.write_bytes(b'original')
        warning = self.run_quiet(vm)
        self.assertEqual(vm.get('A'), 7)
        self.assertIn(SUCCESS, vm.console.lines)
        self.assertIn('emuera.log', warning)
        self.assertIn('追加ログ', warning)
        self.assertIn('失敗', warning)
        self.assertNotIn('review it before sharing', warning)
        self.assertEqual(marker.read_bytes(), b'original')
        self.assertEqual((target.parent / 'emuera.log').read_bytes().decode('utf-16'), 'before\r\n')
        self.assertEqual(getattr(vm, 'outputlog_records', []), [])
        self.assertEqual(len(list(target.parent.glob('output-*.txt'))), 1)

    def test_capture_open_failure_reports_partial_success_and_continues(self):
        vm = self.make_log_vm()
        original = Path.open

        def deny_capture(path, *args, **kwargs):
            if path.name.startswith('output-') and path.suffix == '.txt':
                raise PermissionError('denied')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'open', deny_capture):
            warning = self.run_quiet(vm)
        self.assertEqual(vm.get('A'), 7)
        self.assertIn(SUCCESS, vm.console.lines)
        self.assertIn('追加ログ', warning)
        self.assertEqual(getattr(vm, 'outputlog_records', []), [])
        self.assertFalse((self.log_directory(vm) / 'outputlog-manifest.json').exists())

    def test_manifest_failure_does_not_publish_uncommitted_record(self):
        vm = self.make_log_vm()
        original = vm.saves.atomic_write

        def fail_manifest(path, data):
            if path.name == 'outputlog-manifest.json':
                raise EraError('manifest I/O', code='E_SAVE_IO')
            return original(path, data)

        with patch.object(vm.saves, 'atomic_write', side_effect=fail_manifest):
            warning = self.run_quiet(vm)
        self.assertEqual(vm.get('A'), 7)
        self.assertIn('追加ログ', warning)
        self.assertEqual(getattr(vm, 'outputlog_records', []), [])

    def test_failed_later_manifest_keeps_previous_manifest_and_records(self):
        vm = self.make_log_vm()
        self.run_quiet(vm)
        manifest = self.log_directory(vm) / 'outputlog-manifest.json'
        before = manifest.read_bytes()
        records = list(vm.outputlog_records)
        original = vm.saves.atomic_write

        def fail_manifest(path, data):
            if path == manifest:
                raise EraError('manifest I/O', code='E_SAVE_IO')
            return original(path, data)

        with patch.object(vm.saves, 'atomic_write', side_effect=fail_manifest):
            self.run_quiet(vm)
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual(vm.outputlog_records, records)

    def test_non_io_errors_and_interrupts_from_manifest_propagate(self):
        for error in (EraError('path', code='E_PATH'), EraError('script', code='E_RUNTIME'),
                      ValueError('bug'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__, code=getattr(error, 'code', None)):
                vm = self.make_log_vm()
                original = vm.saves.atomic_write

                def fail_manifest(path, data):
                    if path.name == 'outputlog-manifest.json':
                        raise error
                    return original(path, data)

                with patch.object(vm.saves, 'atomic_write', side_effect=fail_manifest):
                    with self.assertRaises(type(error)) as caught:
                        outputlog.write(vm)
                self.assertIs(caught.exception, error)
                self.assertEqual(vm.get('A'), 0)

    def test_success_records_capture_manifest_and_native_bytes(self):
        vm = self.make_log_vm()
        warning = self.run_quiet(vm)
        folder = self.log_directory(vm)
        self.assertEqual(vm.get('A'), 7)
        self.assertEqual((folder / 'emuera.log').read_bytes(), b'\xff\xfe' + 'before\r\n'.encode('utf-16-le'))
        manifest = json.loads((folder / 'outputlog-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['records'], vm.outputlog_records)
        self.assertEqual(len(vm.outputlog_records), 1)
        capture = folder / vm.outputlog_records[0]['file']
        self.assertEqual(capture.read_bytes(), ('before\n' + SUCCESS + '\n\n').encode('utf-8'))
        self.assertIn('review it before sharing', warning)

    def test_ordinary_save_io_failure_remains_fatal(self):
        vm = self.make()
        target = self.log_directory(vm) / 'collision'
        target.mkdir(parents=True)
        with self.assertRaises(EraError) as caught:
            vm.saves.atomic_write(target, b'data')
        self.assertEqual(caught.exception.code, 'E_SAVE_IO')

    def test_capture_write_failure_retains_partial_file_without_record(self):
        vm = self.make_log_vm()
        original = Path.open

        class FailingStream:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, data):
                self.stream.write(data[:3])
                raise OSError('disk full')

        def fail_capture(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            if path.name.startswith('output-') and path.suffix == '.txt':
                return FailingStream(stream)
            return stream

        with patch.object(Path, 'open', fail_capture):
            warning = self.run_quiet(vm)
        self.assertEqual(vm.get('A'), 7)
        self.assertIn('追加ログ', warning)
        folder = self.log_directory(vm)
        self.assertEqual([p.read_bytes() for p in folder.glob('output-*.txt')], [b'bef'])
        self.assertEqual(getattr(vm, 'outputlog_records', []), [])
        self.assertFalse((folder / 'outputlog-manifest.json').exists())

    def test_raw_oserror_from_manifest_warns_and_continues(self):
        vm = self.make_log_vm()
        original = vm.saves.atomic_write

        def fail_manifest(path, data):
            if path.name == 'outputlog-manifest.json':
                raise OSError('disk full')
            return original(path, data)

        with patch.object(vm.saves, 'atomic_write', side_effect=fail_manifest):
            warning = self.run_quiet(vm)
        self.assertEqual(vm.get('A'), 7)
        self.assertIn('追加ログ', warning)
        self.assertEqual(getattr(vm, 'outputlog_records', []), [])

    def test_non_io_capture_open_errors_and_interrupts_propagate(self):
        original = Path.open
        for error in (EraError('path', code='E_PATH'), ValueError('bug'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                vm = self.make_log_vm()

                def fail_capture(path, *args, **kwargs):
                    if path.name.startswith('output-') and path.suffix == '.txt':
                        raise error
                    return original(path, *args, **kwargs)

                with patch.object(Path, 'open', fail_capture):
                    with self.assertRaises(type(error)) as caught:
                        outputlog.write(vm)
                self.assertIs(caught.exception, error)

    def test_capture_name_collision_uses_suffix_without_overwriting(self):
        vm = self.make_log_vm()
        folder = self.log_directory(vm)
        folder.mkdir(parents=True)
        previous = folder / 'output-fixed.txt'
        previous.write_bytes(b'previous')
        with patch.object(outputlog, 'datetime') as clock:
            clock.now.return_value.strftime.return_value = 'fixed'
            self.run_quiet(vm)
        self.assertEqual(previous.read_bytes(), b'previous')
        self.assertEqual(vm.outputlog_records[0]['file'], 'output-fixed-1.txt')
