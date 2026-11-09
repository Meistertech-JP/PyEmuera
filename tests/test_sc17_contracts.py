"""Native initial sentinels and SAVEDATA RESULT; legacy JSON is never reinterpreted.

Native SC14 actual log SHA 50f934fd7d47bd873ccdc5dc5103be33cc8612a64fb6f1bbce2322049ecb2080.
Primary contracts: VariableData.SetDefaultValue, UpdateInBeginTrain,
Process.ScriptProc SAVEDATA (no RESULT assignment).
"""
import json
from pathlib import Path
from unittest.mock import patch
from test_core import Harness
from pyemuera.errors import EraError
from pyemuera import commands, dispatcher, save_commands
from pyemuera.native_save import decode

FIXTURES = Path(__file__).parent / 'fixtures' / 'compatibility_sidecar17'

class ConstructorSentinels(Harness):
    def test_constructor_values_and_sparse_defaults(self):
        vm = self.make()
        for name in ('NEXTCOM', 'PREVCOM'):
            self.assertEqual(vm.get(name), 0)
            self.assertEqual(vm.data.variables[name].default, 0)
            self.assertNotIn((0,), vm.data.variables[name].values)
            self.assertEqual(vm.initial[name].get((0,)), 0)
        self.assertEqual((vm.get('TARGET'), vm.get('ASSI')), (-1, -1))

    def test_new_reset_uses_constructor_defaults_without_load_migration(self):
        vm = self.make(); vm.set('NEXTCOM', 32); vm.set('PREVCOM', -1)
        vm.reset()
        self.assertEqual((vm.get('NEXTCOM'), vm.get('PREVCOM')), (0, 0))

    def test_begin_train_still_sets_minus_one_before_eventtrain(self):
        vm = self.make('@SYSTEM_TITLE\nADDVOIDCHARA\nTARGET=0\nBEGIN TRAIN\n'
                       '@EVENTTRAIN\nA=NEXTCOM\nB=PREVCOM\nQUIT')
        self.assertEqual((vm.get('NEXTCOM'), vm.get('PREVCOM')), (0, 0))
        vm.run()
        self.assertEqual((vm.get('A'), vm.get('B')), (-1, -1))

    def install_fixture(self, vm, filename):
        vm.saves.atomic_write(vm.saves.path(17), (FIXTURES / filename).read_bytes())

    def test_actual_b3_save_preserves_explicit_minus_one(self):
        vm = self.make(); self.install_fixture(vm, 'b3-current-negative.json')
        self.assertEqual(vm.saves.load(17), 1)
        self.assertEqual((vm.get('NEXTCOM'), vm.get('PREVCOM')), (-1, -1))
        vm.saves.write(18)
        saved = json.loads(vm.saves.path(18).read_text(encoding='utf-8'))
        for name in ('NEXTCOM', 'PREVCOM'):
            self.assertEqual(saved['variables'][name]['values'], [[[0], -1]])

    def test_profile_absent_and_a9_shape_keep_minus_one(self):
        for filename in ('derived-no-profile-negative.json', 'derived-a9-shape-negative.json'):
            with self.subTest(fixture=filename):
                vm = self.make(); self.install_fixture(vm, filename)
                self.assertEqual(vm.saves.load(17), 1)
                for name in ('NEXTCOM', 'PREVCOM'):
                    self.assertEqual(vm.get(name), -1)
                    self.assertEqual(vm.data.variables[name].dims, (1000,))
                    self.assertEqual(vm.get(name + ':999'), 0)

    def test_profile_absent_keeps_other_cells_exactly(self):
        vm = self.make(); self.install_fixture(vm, 'derived-no-profile-extra-cells.json')
        vm.saves.load(17)
        self.assertEqual((vm.get('NEXTCOM'), vm.get('PREVCOM')), (-1, -1))
        self.assertEqual((vm.get('NEXTCOM:999'), vm.get('PREVCOM:3')), (-5, 88))

    def test_zero_representations_are_not_replaced_by_old_minus_one(self):
        for filename in ('derived-current-empty-zero.json', 'derived-current-explicit-zero.json'):
            with self.subTest(fixture=filename):
                vm = self.make(); vm.set('NEXTCOM', -1); vm.set('PREVCOM', -1)
                self.install_fixture(vm, filename); vm.saves.load(17)
                self.assertEqual((vm.get('NEXTCOM'), vm.get('PREVCOM')), (0, 0))

    def test_missing_descriptor_is_still_rejected_atomically(self):
        for name in ('NEXTCOM', 'PREVCOM'):
            with self.subTest(variable=name):
                vm = self.make(); vm.set('NEXTCOM', 41); vm.set('PREVCOM', 42)
                before_rng = vm.rng.getstate()
                self.install_fixture(vm, 'invalid-missing-' + name + '.json')
                with self.assertRaises(EraError) as error: vm.saves.load(17)
                self.assertEqual(error.exception.code, 'E_SAVE')
                self.assertEqual((vm.get('NEXTCOM'), vm.get('PREVCOM')), (41, 42))
                self.assertEqual(vm.rng.getstate(), before_rng)

    def test_loading_old_save_does_not_change_future_new_game_defaults(self):
        vm = self.make(); self.install_fixture(vm, 'b3-current-negative.json'); vm.saves.load(17)
        self.assertEqual(vm.get('NEXTCOM'), -1)
        vm.reset()
        self.assertEqual((vm.get('NEXTCOM'), vm.get('PREVCOM')), (0, 0))

    def test_profile_spelling_dimensions_and_saved_flags_unchanged(self):
        vm = self.make(); vm.saves.write(17)
        saved = json.loads(vm.saves.path(17).read_text(encoding='utf-8'))
        self.assertEqual(saved['builtin_defaults_profile'], 'src1824-a10')
        for name in ('NEXTCOM', 'PREVCOM'):
            self.assertEqual(saved['variables'][name]['dims'], [1000])
            self.assertEqual(saved['variables'][name]['values'], [])
            self.assertTrue(vm.data.variables[name].saved)

class SavedataResult(Harness):
    def test_actual_vm_sentinel_is_visible_immediately_after_save(self):
        vm = self.script('RESULT=77\nSAVEDATA 97,"sentinel"\nA=RESULT')
        self.assertEqual(vm.get('A'), 77)
        self.assertTrue(vm.saves.path(97).is_file())

    def test_dispatch_and_historical_command_entry_keep_result_vector_and_results(self):
        for entry in (lambda vm: dispatcher.execute(vm, 'SAVEDATA', '17,"slot"'),
                      lambda vm: commands.execute_command(vm, 'SAVEDATA', '17,"slot"')):
            with self.subTest(entry=entry):
                vm = self.make(); vm.set('RESULT', 77); vm.set('RESULT:1', 60); vm.set('RESULTS', 'keep')
                before_rng = vm.rng.getstate(); entry(vm)
                self.assertEqual((vm.get('RESULT'), vm.get('RESULT:1'), vm.get('RESULTS')), (77, 60, 'keep'))
                self.assertEqual(vm.rng.getstate(), before_rng)

    def test_argument_side_effects_are_preserved_not_rolled_back_to_entry(self):
        vm = self.make(); vm.set('A', 17); vm.set('RESULT', 77)
        commands.execute_command(vm, 'SAVEDATA', 'A++,TOSTR(RESULT++)')
        self.assertEqual((vm.get('A'), vm.get('RESULT')), (18, 78))
        state = json.loads(vm.saves.path(17).read_text(encoding='utf-8'))
        self.assertEqual(state['description'], '77')

    def test_json_and_native_formats_preserve_immediate_result(self):
        for format in ('json', 'emuera-text', 'emuera-binary'):
            with self.subTest(format=format):
                vm = self.make(); vm.saves.format = format; vm.set('RESULT', 77)
                commands.execute_command(vm, 'SAVEDATA', '17,"slot"')
                self.assertEqual(vm.get('RESULT'), 77)
                if format == 'json':
                    saved = json.loads(vm.saves.path(17).read_text(encoding='utf-8'))
                    self.assertNotIn('RESULT', saved['variables'])
                else:
                    native = decode(vm.saves.native_path(17).read_bytes())
                    self.assertEqual(native.variables['RESULT'].values[(0,)], 77)

    def test_successful_host_store_mutation_is_not_undone(self):
        vm = self.make(); vm.set('RESULT', 77)
        def store(*args): vm.set('RESULT', 91)
        with patch.object(vm.saves, 'write', store):
            commands.execute_command(vm, 'SAVEDATA', '17,"slot"')
        self.assertEqual(vm.get('RESULT'), 91)

    def test_store_error_is_same_object_and_does_not_set_result(self):
        vm = self.make(); vm.set('RESULT', 77); failure = EraError('blocked', code='E_SAVE_IO')
        with patch.object(vm.saves, 'write', side_effect=failure):
            with self.assertRaises(EraError) as error:
                commands.execute_command(vm, 'SAVEDATA', '17,"slot"')
        self.assertIs(error.exception, failure)
        self.assertEqual(vm.get('RESULT'), 77)

    def test_argument_type_error_does_not_write_or_overwrite_result(self):
        vm = self.make(); vm.set('RESULT', 77)
        with patch.object(vm.saves, 'write') as write:
            with self.assertRaises(EraError):
                commands.execute_command(vm, 'SAVEDATA', '17,9')
        write.assert_not_called(); self.assertEqual(vm.get('RESULT'), 77)

    def test_saveglobal_and_failed_load_keep_existing_result_contracts(self):
        vm = self.make(); vm.set('RESULT', 77)
        commands.execute_command(vm, 'SAVEGLOBAL', '')
        self.assertEqual(vm.get('RESULT'), 1)
        commands.execute_command(vm, 'LOADDATA', '99')
        self.assertEqual(vm.get('RESULT'), 0)

    def test_callee_fallthrough_still_sets_zero_after_savedata(self):
        vm = self.make('@MAIN\nCALL SAVEHELP\nB=RESULT\nRETURN\n'
                       '@SAVEHELP\nRESULT=77\nSAVEDATA 97,"callee"\nA=RESULT\n')
        vm.call('MAIN')
        self.assertEqual((vm.get('A'), vm.get('B')), (77, 0))

    def test_actual_fixed_native_reference_init_save_and_fallthrough(self):
        reference = json.loads((FIXTURES / 'native14-actual-verification.json').read_text(encoding='utf-8'))
        self.assertEqual(reference['sha256'], '50f934fd7d47bd873ccdc5dc5103be33cc8612a64fb6f1bbce2322049ecb2080')
        self.assertTrue(reference['passed'])
        observed = reference['observed']
        timestamp = int(observed['CALLEE_BEFORE_SAVE98'][0].rsplit('=', 1)[1])
        source = ('@MAIN\nA=NEXTCOM\nB=PREVCOM\nRESULT=77\nSAVEDATA 97,"ref"\n'
                  'C=RESULT\nCALL SAVEHELP\nE=RESULT\nRETURN\n'
                  '@SAVEHELP\nRESULT=' + str(timestamp) + '\nSAVEDATA 98,"ref"\nD=RESULT\n')
        vm = self.make(source); vm.call('MAIN')
        actual = {'INIT': 'SC14|INIT|NEXT=' + str(vm.get('A')) + '|PREV=' + str(vm.get('B')),
                  'SENTINEL_AFTER_SAVE97': 'SC14|SENTINEL_AFTER_SAVE97|RESULT=' + str(vm.get('C')),
                  'CALLEE_AFTER_SAVE98': 'SC14|CALLEE_AFTER_SAVE98|RESULT=' + str(vm.get('D')),
                  'AFTER_CALLEE_FALLTHROUGH': 'SC14|AFTER_CALLEE_FALLTHROUGH|RESULT=' + str(vm.get('E'))}
        for name, line in actual.items(): self.assertEqual([line], observed[name])
