"""Source-based save/header contracts and portable delivered-signal checks.

These tests do not certify Windows console event delivery or native interchange.
"""
import copy
import signal
import struct
from unittest.mock import patch
from test_core import Harness, CHARA
from pyemuera import native_save as codec
from pyemuera.cli_interrupts import CLIInterrupts
from pyemuera.errors import EraError
from pyemuera.native_store import snapshot
from pyemuera.random1824 import execute as random_command


class SaveInterruptContracts(Harness):
    def original(self, vm, raw):
        path = vm.data.root / 'save00.sav'
        path.write_bytes(raw)
        return path

    def test_chkdata_missing_source_message(self):
        vm = self.make()
        self.assertEqual(vm.saves.check(0), (1, '----'))

    def test_chkdata_text_reads_description_without_body(self):
        vm = self.make(csv=CHARA)
        self.original(vm, b'123\r\n1\r\nheader only\r\n')
        self.assertEqual(vm.saves.check(0), (0, 'header only'))
        vm.set('MONEY', 77)
        with self.assertRaises(EraError):
            vm.saves.load(0)
        self.assertEqual(vm.get('MONEY'), 77)

    def test_chkdata_binary_reads_description_without_body(self):
        vm = self.make(csv=CHARA)
        raw = (codec.MAGIC + struct.pack('<IIBqq', 1808, 0, 0, 123, 1)
               + b'\x02x\x00')
        self.original(vm, raw)
        self.assertEqual(vm.saves.check(0), (0, 'x'))
        with self.assertRaises(EraError):
            vm.saves.load(0)

    def test_chkdata_wrong_game_precedes_bad_version(self):
        vm = self.make(csv=CHARA)
        self.original(vm, b'999\nnot a version\n')
        self.assertEqual(vm.saves.check(0), (2, '異なるゲームのセーブデータです'))

    def test_chkdata_version_message_keeps_native_typo(self):
        vm = self.make(csv={'GameBase.csv':'コード,123\nバージョン,30\nバージョン違い認める,20\n'})
        self.original(vm, b'123\n19\n')
        self.assertEqual(vm.saves.check(0), (3, 'セーブデータのバーションが異なります'))

    def test_chkdata_text_read_errors(self):
        vm = self.make(csv=CHARA)
        for raw, expected in [(b'', '読み取るべき数値がありません'),
                              (b'bad\n', '数値として認識できません'),
                              (b'123\n1\n', '読み取るべき文字列がありません')]:
            with self.subTest(raw=raw):
                self.original(vm, raw)
                self.assertEqual(vm.saves.check(0), (4, expected))

    def test_chkdata_binary_wrong_type_precedes_identity(self):
        vm = self.make(csv=CHARA)
        self.original(vm, codec.MAGIC + struct.pack('<IIB', 1808, 0, 1))
        self.assertEqual(vm.saves.check(0), (4, 'セーブデータが壊れています'))

    def test_native_str_is_unsaved_and_resets_to_csv(self):
        for format in ('emuera-text', 'emuera-binary'):
            with self.subTest(format=format):
                vm = self.make(csv={**CHARA, 'Str.csv':'0,CSV initial\n'})
                vm.saves.format = format
                vm.set('STR', 'saved-time STR')
                vm.set('SAVESTR', 'saved string')
                vm.set('TSTR', 'temporary string')
                self.assertNotIn('STR', snapshot(vm, 0).variables)
                vm.saves.write(0)
                vm.set('STR', 'after save')
                vm.set('SAVESTR', 'changed')
                vm.set('TSTR', 'changed')
                vm.saves.load(0)
                self.assertEqual(vm.get('STR'), 'CSV initial')
                self.assertEqual(vm.get('SAVESTR'), 'saved string')
                self.assertEqual(vm.get('TSTR'), 'temporary string')

    def test_native_source_rng_requires_explicit_dump_and_init(self):
        for format in ('emuera-text', 'emuera-binary'):
            with self.subTest(format=format):
                vm = self.make(csv=CHARA)
                vm.saves.format = format
                random_command(vm, {'name':'DUMPRAND'}, '')
                stored_rng = copy.deepcopy(vm.rng.getstate())
                vm.saves.write(0)
                vm.rng.randrange(100)
                active_rng = copy.deepcopy(vm.rng.getstate())
                vm.set('RANDDATA:0', 0)
                vm.saves.load(0)
                self.assertEqual(vm.rng.getstate(), active_rng)
                random_command(vm, {'name':'INITRAND'}, '')
                self.assertEqual(vm.rng.getstate(), stored_rng)

    def test_native_restore_policy_preserves_stream(self):
        for format in ('emuera-text', 'emuera-binary'):
            with self.subTest(format=format):
                vm = self.make(csv=CHARA)
                vm.saves.format = format
                vm.saves.native_rng = 'restore'
                before = copy.deepcopy(vm.rng.getstate())
                vm.saves.write(0)
                expected = [vm.rng.randrange(10000) for _ in range(10)]
                vm.saves.load(0)
                self.assertEqual(vm.rng.getstate(), before)
                self.assertEqual([vm.rng.randrange(10000) for _ in range(10)], expected)

    def test_json_selfload_keeps_str_and_rng(self):
        vm = self.make(csv=CHARA)
        vm.set('STR', 'JSON saved string')
        before = copy.deepcopy(vm.rng.getstate())
        vm.saves.write(0)
        vm.set('STR', 'changed')
        vm.rng.randrange(100)
        vm.saves.load(0)
        self.assertEqual(vm.get('STR'), 'JSON saved string')
        self.assertEqual(vm.rng.getstate(), before)

    def test_keyboardinterrupt_before_replace_preserves_all_formats(self):
        for format in ('json', 'emuera-text', 'emuera-binary'):
            with self.subTest(format=format):
                vm = self.make(csv=CHARA)
                original = self.original(vm, b'original user file')
                vm.saves.format = format
                vm.saves.write(0)
                path = vm.saves.path(0) if format == 'json' else vm.saves.native_path(0)
                old = path.read_bytes()
                vm.set('MONEY', 987)
                with patch('pyemuera.persistence.os.replace', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                    vm.saves.write(0)
                self.assertEqual(path.read_bytes(), old)
                self.assertEqual(original.read_bytes(), b'original user file')
                self.assertFalse(list(path.parent.glob('.writing-*')))

    def test_saveinfo_begin_preserves_existing_autosave(self):
        from pyemuera.autosave import run
        from pyemuera.errors import FlowSignal
        vm = self.make('@SAVEINFO\nPUTFORM replacement\nBEGIN TITLE\n')
        vm.saves.write(99, 'previous save')
        old = vm.saves.path(99).read_bytes()
        with patch.object(vm.saves, 'write', wraps=vm.saves.write) as writer:
            with self.assertRaises(FlowSignal):
                run(vm)
            writer.assert_not_called()
        self.assertEqual(vm.saves.path(99).read_bytes(), old)

    def test_delivered_sigint_interrupts_busy_vm_and_unwinds(self):
        vm = self.make('@MAIN\nCALL BUSY\n@BUSY\nWHILE 1\nA++\nWEND\n')
        tick = vm.tick
        def deliver():
            tick()
            if vm.steps == 100:
                signal.raise_signal(signal.SIGINT)
        previous = signal.getsignal(signal.SIGINT)
        with CLIInterrupts() as interrupts, patch.object(vm, 'tick', side_effect=deliver):
            with self.assertRaises(KeyboardInterrupt):
                vm.run('MAIN')
            self.assertEqual(interrupts.received['signal'], 'SIGINT')
            self.assertEqual(vm.frames, [])
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)
