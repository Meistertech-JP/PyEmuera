"""Adversarial freeze and saved-ZIP tests; these do not stage a release."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


PACK = module('r50_package_test', 'tools/package_r50.py')
VERIFY = module('r50_independent_test', 'tools/verify_distribution_r50.py')


class FrozenPublicPackageR50(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.stage = self.root / 'candidate'
        self.stage.mkdir()
        (self.stage / 'data.txt').write_bytes(b'original public bytes')
        self.units = {'pyz_sha256': 'f' * 64, 'tests': 1, 'failures': 0, 'errors': 0, 'skipped': 0}
        self.pins = PACK.freeze(self.stage, PACK.VERSION, self.units)
        self.output = self.root / 'candidate.zip'

    def reject(self):
        with self.assertRaisesRegex(ValueError, 'changed after freeze'):
            PACK.write_zip(self.stage, self.output, self.pins)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name(self.output.name + '.pending').exists())

    def saved(self):
        PACK.write_zip(self.stage, self.output, self.pins)
        return VERIFY.inspect_archive(self.output)

    def altered_zip(self, transform, extras=()):
        PACK.write_zip(self.stage, self.output, self.pins)
        result = io.BytesIO()
        with zipfile.ZipFile(self.output) as source, zipfile.ZipFile(result, 'w') as target:
            for info in source.infolist():
                target.writestr(info, transform(info.filename, source.read(info)))
            for name, raw in extras:
                target.writestr(name, raw)
        result.seek(0)
        return result

    def test_full_saved_zip_crc_sizes_hashes_and_membership_pass(self):
        files, pack, hashes, errors = self.saved()
        self.assertEqual(errors, [])
        self.assertEqual(set(files), {'data.txt'} | PACK.CONTROL)
        self.assertEqual(set(hashes), {'data.txt', 'PACK_MANIFEST.json'})
        self.assertEqual(pack['files']['data.txt'], {
            'bytes': 21, 'sha256': hashlib.sha256(b'original public bytes').hexdigest()})

    def test_same_size_payload_mutation_rejected(self):
        (self.stage / 'data.txt').write_bytes(b'changed! public bytes')
        self.reject()

    def test_added_file_rejected(self):
        (self.stage / 'extra.txt').write_bytes(b'unregistered')
        self.reject()

    def test_removed_file_rejected(self):
        (self.stage / 'data.txt').unlink()
        self.reject()

    def test_forged_manifest_and_matching_hashlists_cannot_replace_frozen_pins(self):
        (self.stage / 'data.txt').write_bytes(b'forged')
        # An attacker regenerating all three controls still lacks the saved pins.
        PACK.freeze(self.stage, PACK.VERSION, self.units)
        self.reject()

    def test_each_control_is_individually_pinned(self):
        for name in sorted(PACK.CONTROL):
            with self.subTest(name=name):
                path = self.stage / name
                old = path.read_bytes()
                path.write_bytes(old + b' ')
                self.reject()
                path.write_bytes(old)

    def test_refreeze_uses_actual_current_content(self):
        (self.stage / 'data.txt').write_bytes(b'new reviewed bytes')
        self.pins = PACK.freeze(self.stage, PACK.VERSION, self.units)
        files, pack, hashes, errors = self.saved()
        self.assertEqual(errors, [])
        self.assertEqual(pack['files']['data.txt']['sha256'], hashlib.sha256(b'new reviewed bytes').hexdigest())
        self.assertEqual(files['data.txt'], b'new reviewed bytes')

    def test_mutation_after_preflight_during_stream_is_rejected(self):
        original = PACK.source_file
        def race(root, rel):
            path = original(root, rel)
            if rel == 'data.txt':
                path.write_bytes(b'late change')
            return path
        with patch.object(PACK, 'source_file', side_effect=race):
            self.reject()

    def test_added_file_after_stream_is_rejected(self):
        original = PACK.inventory
        calls = []
        def race(stage):
            calls.append(stage)
            if len(calls) == 2:
                (stage / 'late.txt').write_bytes(b'late addition')
            return original(stage)
        with patch.object(PACK, 'inventory', side_effect=race):
            self.reject()

    def test_existing_output_and_pending_are_preserved(self):
        self.output.write_bytes(b'existing delivery')
        with self.assertRaises(FileExistsError):
            PACK.write_zip(self.stage, self.output, self.pins)
        self.assertEqual(self.output.read_bytes(), b'existing delivery')
        self.output.unlink()
        pending = self.output.with_name(self.output.name + '.pending')
        pending.write_bytes(b'existing interrupted attempt')
        with self.assertRaises(FileExistsError):
            PACK.write_zip(self.stage, self.output, self.pins)
        self.assertEqual(pending.read_bytes(), b'existing interrupted attempt')

    def test_untested_pyz_and_postbuild_sidecar_rejected(self):
        (self.stage / 'PyEmuera.pyz').write_bytes(b'untested engine')
        with self.assertRaisesRegex(ValueError, 'untested pyz'):
            PACK.freeze(self.stage, PACK.VERSION, self.units)
        (self.stage / 'PyEmuera.pyz').unlink()
        (self.stage / 'R50_DISTRIBUTION_INTEGRITY.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'postbuild'):
            PACK.freeze(self.stage, PACK.VERSION, self.units)

    def test_reparse_point_and_parent_link_rejected(self):
        fake = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=0o100644, st_file_attributes=0x400))
        with self.assertRaisesRegex(ValueError, 'reparse'):
            PACK.no_link(fake)
        original = PACK.no_link
        folder = self.stage / 'nested'
        folder.mkdir()
        (folder / 'file.txt').write_bytes(b'bytes')
        def parent_link(path):
            if path == folder:
                raise ValueError('symlink or reparse point in input')
            return original(path)
        with patch.object(PACK, 'no_link', side_effect=parent_link):
            with self.assertRaisesRegex(ValueError, 'reparse'):
                PACK.source_file(self.stage, 'nested/file.txt')

    def test_windows_aliases_and_traversal_names_rejected(self):
        for name in ['a/../b', '/absolute', 'a//b', 'CON.txt', 'a./b', 'a /b',
                     'a:b', 'a\\b', 'a\nb', 'a?b', './a']:
            with self.subTest(name=name):
                self.assertFalse(PACK.safe_path(name))
                self.assertFalse(VERIFY.safe_path(name))
        with self.assertRaisesRegex(ValueError, 'case-collision'):
            PACK.check_names(['README.md', 'readme.md'])

    def test_saved_payload_mutation_detected_without_builder_import(self):
        changed = self.altered_zip(lambda name, raw: b'edited saved payload' if name.endswith('/data.txt') else raw)
        errors = VERIFY.inspect_archive(changed)[3]
        self.assertIn('SHA mismatch: data.txt', errors)
        self.assertIn('pack size/SHA mismatch: data.txt', errors)

    def test_saved_missing_and_extra_member_detected(self):
        changed = self.altered_zip(lambda name, raw: raw, [('candidate/extra.txt', b'extra')])
        errors = VERIFY.inspect_archive(changed)[3]
        self.assertIn('hashlist membership', errors)
        self.assertIn('pack membership', errors)

    def test_saved_case_collision_and_symlink_detected(self):
        symlink = zipfile.ZipInfo('candidate/link.txt')
        symlink.create_system = 3
        symlink.external_attr = 0o120777 << 16
        changed = self.altered_zip(lambda name, raw: raw,
                                   [('candidate/DATA.txt', b'collision'), (symlink, b'data.txt')])
        errors = VERIFY.inspect_archive(changed)[3]
        self.assertIn('duplicate or Windows case-collision', errors)
        self.assertIn('encrypted, directory or nonregular ZIP member', errors)

    def test_saved_unsafe_member_detected(self):
        changed = self.altered_zip(lambda name, raw: raw, [('candidate/../escape.txt', b'bad')])
        self.assertIn('unsafe archive member path', VERIFY.inspect_archive(changed)[3])
        original = self.output.read_bytes()
        # All mutations retain readable members and unchanged manifest controls.
        # A freshly matching outer SHA cannot establish raw-byte privacy.
        private = b'X:' + b'/Users/' + b'fixture-owner/local-note'
        end = len(original) - 22
        central = struct.unpack_from('<I', original, end + 16)[0]
        interstitial = bytearray(original[:central] + private + original[central:])
        struct.pack_into('<I', interstitial, end + len(private) + 16, central + len(private))
        # Also make a prefixed ZIP whose central offsets account for the prefix.
        prefixed = bytearray(private + original)
        position = central + len(private)
        while prefixed[position:position + 4] == b'PK\x01\x02':
            old_offset = struct.unpack_from('<I', prefixed, position + 42)[0]
            struct.pack_into('<I', prefixed, position + 42, old_offset + len(private))
            lengths = struct.unpack_from('<3H', prefixed, position + 28)
            position += 46 + sum(lengths)
        struct.pack_into('<I', prefixed, end + len(private) + 16, central + len(private))
        for label, raw in [('prefix', private + original), ('adjusted-prefix', prefixed),
                           ('suffix', original + private), ('interstitial', interstitial)]:
            with self.subTest(raw_region=label):
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertEqual(archive.read('candidate/data.txt'), b'original public bytes')
                with self.assertRaisesRegex(ValueError, 'unconsumed raw bytes'):
                    VERIFY.inspect_archive(io.BytesIO(raw))

        # Positive ZIP64 EOCD/locator control, with the builder's existing local
        # force_zip64 headers, followed by negative raw-region controls.
        count = len(self.pins)
        central_size = end - central
        zip64_end = struct.pack('<4sQ2H2I4Q', b'PK\x06\x06', 44, 45, 45, 0, 0,
                                count, count, central_size, central)
        locator = struct.pack('<4sIQI', b'PK\x06\x07', 0, end, 1)
        eocd = struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, 0xffff, 0xffff,
                           0xffffffff, 0xffffffff, 0)
        zip64_raw = original[:end] + zip64_end + locator + eocd
        self.assertEqual(VERIFY.inspect_archive(io.BytesIO(zip64_raw))[3], [])
        for raw in (private + zip64_raw, zip64_raw + private):
            with self.subTest(zip64_raw_region=True):
                with self.assertRaisesRegex(ValueError, 'unconsumed raw bytes'):
                    VERIFY.inspect_archive(io.BytesIO(raw))

    def test_duplicate_json_control_key_is_not_accepted(self):
        changed = self.altered_zip(lambda name, raw: b'{"files":{},"files":{}}'
                                   if name.endswith('/PACK_MANIFEST.json') else raw)
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            VERIFY.inspect_archive(changed)

    def test_saved_crc_corruption_detected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('candidate/data.txt', b'unique raw CRC payload')
        raw = stream.getvalue().replace(b'unique raw CRC payload', b'changedraw CRC payload')
        with self.assertRaises(zipfile.BadZipFile):
            VERIFY.inspect_archive(io.BytesIO(raw))
        # A member's central/local compressed-size fields can include bytes
        # beyond deflate EOF, which ZipFile also silently ignores.
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('candidate/data.txt', b'neutral compressed payload')
        original = stream.getvalue()
        end = len(original) - 22
        central = struct.unpack_from('<I', original, end + 16)[0]
        extra = b'X:' + b'/Users/' + b'fixture-owner/hidden-after-deflate'
        hidden = bytearray(original[:central] + extra + original[central:])
        size = struct.unpack_from('<I', hidden, 18)[0]
        struct.pack_into('<I', hidden, 18, size + len(extra))
        struct.pack_into('<I', hidden, central + len(extra) + 20, size + len(extra))
        struct.pack_into('<I', hidden, end + len(extra) + 16, central + len(extra))
        with self.subTest(unconsumed_compressed_stream=True):
            with zipfile.ZipFile(io.BytesIO(hidden)) as archive:
                self.assertEqual(archive.read('candidate/data.txt'), b'neutral compressed payload')
            with self.assertRaisesRegex(ValueError, 'unconsumed raw bytes'):
                VERIFY.inspect_archive(io.BytesIO(hidden))

    def test_external_outer_sha_is_independent_of_internal_manifests(self):
        self.saved()
        sidecar = self.root / 'SHA256-r50.txt'
        digest = hashlib.sha256(self.output.read_bytes()).hexdigest()
        sidecar.write_text(digest + '  candidate.zip\n', encoding='utf-8')
        self.assertTrue(VERIFY.verify_outer_hashlist(sidecar, [self.output])['passed'])
        self.output.write_bytes(self.output.read_bytes() + b'outer edit')
        self.assertFalse(VERIFY.verify_outer_hashlist(sidecar, [self.output])['passed'])

    def test_outer_hashlist_cannot_reference_parent_directory(self):
        sidecar = self.root / 'SHA256-r50.txt'
        sidecar.write_text('f' * 64 + '  ../outside.zip\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            VERIFY.verify_outer_hashlist(sidecar, [self.output])


if __name__ == '__main__':
    unittest.main()
