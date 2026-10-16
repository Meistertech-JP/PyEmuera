"""Packaging must fail closed when frozen payload or membership changes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

_SPEC = importlib.util.spec_from_file_location('r47_pack', Path(__file__).resolve().parents[1] / 'tools/package_r47.py')
_PACK = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PACK)


class FrozenPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'candidate'
        self.stage.mkdir()
        (self.stage / 'data.txt').write_bytes(b'final data')
        self.units = {'pyz_sha256': 'f' * 64, 'tests': 1, 'failures': 0, 'errors': 0, 'skipped': 0}
        self.controls = _PACK.freeze(self.stage, '3.0.0a10.dev4+r47', self.units)

    def test_payload_change_rejected(self):
        (self.stage / 'data.txt').write_bytes(b'new contents')
        with self.assertRaisesRegex(ValueError, 'changed after freeze'):
            _PACK.write_zip(self.stage, self.root / 'out.zip', self.controls)
        self.assertFalse((self.root / 'out.zip').exists())

    def test_unregistered_file_rejected(self):
        (self.stage / 'extra.txt').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'membership'):
            _PACK.write_zip(self.stage, self.root / 'out.zip', self.controls)

    def test_missing_file_rejected(self):
        (self.stage / 'data.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'membership'):
            _PACK.write_zip(self.stage, self.root / 'out.zip', self.controls)

    def test_manifest_change_rejected(self):
        (self.stage / 'MANIFEST.sha256').write_text('stale manifest', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed after freeze'):
            _PACK.write_zip(self.stage, self.root / 'out.zip', self.controls)

    def test_fresh_manifest_replaces_old(self):
        (self.stage / 'PACK_MANIFEST.json').write_text('{"engine_version":"r45"}', encoding='utf-8')
        controls = _PACK.freeze(self.stage, '3.0.0a10.dev4+r47', self.units)
        _PACK.write_zip(self.stage, self.root / 'out.zip', controls)
        with zipfile.ZipFile(self.root / 'out.zip') as archive:
            pack = json.loads(archive.read('candidate/PACK_MANIFEST.json'))
            self.assertEqual(pack['engine_version'], '3.0.0a10.dev4+r47')
            self.assertEqual(set(pack['files']), {'data.txt'})

    def test_untested_pyz_rejected(self):
        (self.stage / 'PyEmuera.pyz').write_bytes(b'different engine')
        with self.assertRaisesRegex(ValueError, 'untested pyz'):
            _PACK.freeze(self.stage, '3.0.0a10.dev4+r47', self.units)
