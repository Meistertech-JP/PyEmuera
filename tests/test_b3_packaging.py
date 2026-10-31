"""Distribution checks for the bundled ZORKERB game."""
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_builder', ROOT / 'tools/build_release_archives.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BundledGames(unittest.TestCase):
    def test_both_games_and_licenses_are_mapped_from_allowlisted_bytes(self):
        source = builder.path_inventory()
        runtime = builder.runtime_files(source)
        zork = {n for n in source if n.startswith('examples/zorkerb/')}
        self.assertTrue(zork)
        self.assertIn('examples/zorkerb/ERB/02_Flow.ERB', zork)
        self.assertIn('examples/zorkerb/CSV/GameBase.csv', zork)
        self.assertIn('examples/zorkerb/LICENSE', zork)
        self.assertIn('examples/zorkerb/licenses/ZORK1-MIT.txt', zork)
        for name in zork:
            self.assertEqual(runtime['ZORKERB/' + name[len('examples/zorkerb/'):]], source[name])
        self.assertEqual(runtime['sample/replay.txt'], source['examples/smoke/replay.txt'])
        self.assertEqual([n for n in runtime if n.lower().endswith('.pyz')], ['PyEmuera.pyz'])


if __name__ == '__main__':
    unittest.main()
