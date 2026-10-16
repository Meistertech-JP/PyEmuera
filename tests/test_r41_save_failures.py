"""Expected host write failures must never look like an internal VM fault."""
import errno
from unittest.mock import patch
from test_core import Harness, CHARA
from pyemuera.errors import EraError
from pyemuera.autosave import run as autosave

FORMATS = ('json', 'emuera-text', 'emuera-binary')


class SaveFailureContracts(Harness):
    def destination(self, vm):
        return vm.saves.path(0) if vm.saves.format == 'json' else vm.saves.native_path(0)

    def test_parent_file_collision_all_formats(self):
        for format in FORMATS:
            with self.subTest(format=format):
                vm = self.make(csv=CHARA)
                vm.saves.format = format
                path = self.destination(vm)
                path.parent.parent.mkdir()
                path.parent.write_bytes(b'untouched parent sentinel')
                original = vm.root / 'save00.sav'
                original.write_bytes(b'untouched original sentinel')
                with self.assertRaises(EraError) as caught:
                    vm.saves.write(0)
                self.assertEqual(caught.exception.code, 'E_SAVE_IO')
                self.assertIn('親フォルダとファイルが衝突', caught.exception.as_dict()['diagnostic_message'])
                self.assertEqual(path.parent.read_bytes(), b'untouched parent sentinel')
                self.assertEqual(original.read_bytes(), b'untouched original sentinel')
                self.assertFalse(list(vm.root.rglob('.writing-*')))

    def test_overlay_root_file_collision(self):
        vm = self.make()
        (vm.root / '.pyemuera').write_bytes(b'root sentinel')
        with self.assertRaises(EraError) as caught:
            vm.saves.write(0)
        self.assertEqual(caught.exception.code, 'E_SAVE_IO')
        self.assertEqual((vm.root / '.pyemuera').read_bytes(), b'root sentinel')

    def test_destination_directory_collision_all_formats(self):
        for format in FORMATS:
            with self.subTest(format=format):
                vm = self.make(csv=CHARA)
                vm.saves.format = format
                path = self.destination(vm)
                path.mkdir(parents=True)
                sentinel = path / 'sentinel'
                sentinel.write_bytes(b'keep directory')
                with self.assertRaises(EraError) as caught:
                    vm.saves.write(0)
                self.assertEqual(caught.exception.code, 'E_SAVE_IO')
                self.assertIn('既存のフォルダ', caught.exception.message)
                self.assertEqual(sentinel.read_bytes(), b'keep directory')
                self.assertFalse(list(path.parent.glob('.writing-*')))

    def test_fsync_and_replace_failure_preserve_previous_all_formats(self):
        for format in FORMATS:
            for operation in ('os.fsync', 'os.replace'):
                with self.subTest(format=format, operation=operation):
                    vm = self.make(csv=CHARA)
                    vm.saves.format = format
                    vm.saves.write(0)
                    path = self.destination(vm)
                    before = path.read_bytes()
                    vm.set('MONEY', 999)
                    with patch('pyemuera.persistence.' + operation, side_effect=OSError(errno.ENOSPC, 'disk full')):
                        with self.assertRaises(EraError) as caught:
                            vm.saves.write(0)
                    self.assertEqual(caught.exception.code, 'E_SAVE_IO')
                    self.assertIn('空き容量', caught.exception.message)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(vm.get('MONEY'), 999)
                    self.assertFalse(list(path.parent.glob('.writing-*')))

    def test_temporary_creation_permission_error(self):
        vm = self.make()
        with patch('pyemuera.persistence.tempfile.NamedTemporaryFile', side_effect=PermissionError(errno.EACCES, 'denied')):
            with self.assertRaises(EraError) as caught:
                vm.saves.write(0)
        self.assertIn('書き込み権限', caught.exception.message)
        self.assertFalse(vm.saves.path(0).exists())
        self.assertFalse(list(vm.root.rglob('.writing-*')))

    def test_script_failure_preserves_result_and_location(self):
        vm = self.make('@MAIN\nRESULT=77\nSAVEDATA 0, "never saved"\nRESULT=1\n')
        path = vm.saves.path(0)
        path.parent.parent.mkdir()
        path.parent.write_bytes(b'sentinel')
        with self.assertRaises(EraError) as caught:
            vm.run('MAIN')
        self.assertEqual(caught.exception.code, 'E_SAVE_IO')
        self.assertEqual(caught.exception.location.line, 3)
        self.assertEqual(vm.get('RESULT'), 77)
        self.assertNotIn('internal_diagnostic', caught.exception.as_dict())
        self.assertEqual(vm.frames, [])

    def test_autosave_reports_understandable_failure_and_skips(self):
        vm = self.make()
        path = vm.saves.path(99)
        path.parent.parent.mkdir()
        path.parent.write_bytes(b'autosave sentinel')
        autosave(vm)
        self.assertIn('親フォルダとファイルが衝突', self.output.getvalue())
        self.assertIn('オートセーブをスキップします', self.output.getvalue())
        self.assertEqual(path.parent.read_bytes(), b'autosave sentinel')
        self.assertEqual(vm.console.wait_count, 1)

    def test_atomic_write_preserves_interrupt_without_translation(self):
        vm = self.make()
        vm.saves.write(0)
        path = vm.saves.path(0)
        before = path.read_bytes()
        with patch('pyemuera.persistence.os.fsync', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                vm.saves.write(0)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(path.parent.glob('.writing-*')))

    def test_partial_temp_write_failure_preserves_previous_all_formats(self):
        from pyemuera import persistence
        create=persistence.tempfile.NamedTemporaryFile
        for format in FORMATS:
            with self.subTest(format=format):
                vm=self.make(csv=CHARA);vm.saves.format=format;vm.saves.write(0)
                path=self.destination(vm);before=path.read_bytes()
                def partial(*args,**kw):
                    f=create(*args,**kw);write=f.write
                    def fail(data):
                        write(data[:17])
                        raise OSError(errno.ENOSPC,'partial test write')
                    f.write=fail
                    return f
                with patch('pyemuera.persistence.tempfile.NamedTemporaryFile',side_effect=partial):
                    with self.assertRaises(EraError) as caught:vm.saves.write(0)
                self.assertEqual(caught.exception.code,'E_SAVE_IO')
                self.assertEqual(path.read_bytes(),before);self.assertFalse(list(path.parent.glob('.writing-*')))

    def test_global_failure_never_reports_result_one_all_formats(self):
        for format in FORMATS:
            with self.subTest(format=format):
                vm=self.make('@MAIN\nRESULT=88\nSAVEGLOBAL\nRESULT=1\n')
                vm.saves.format=format
                path=vm.saves.path('global') if format=='json' else vm.saves.native_path('global')
                path.parent.parent.mkdir();path.parent.write_bytes(b'global sentinel')
                original=vm.root/'global.sav';original.write_bytes(b'original global sentinel')
                with self.assertRaises(EraError) as caught:vm.run('MAIN')
                self.assertEqual(caught.exception.code,'E_SAVE_IO');self.assertEqual(vm.get('RESULT'),88)
                self.assertEqual(path.parent.read_bytes(),b'global sentinel')
                self.assertEqual(original.read_bytes(),b'original global sentinel')
