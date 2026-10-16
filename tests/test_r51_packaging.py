"""Installed packages must carry every runtime data file of the engine."""
from fnmatch import fnmatchcase
from pathlib import Path
import unittest

try:
    import tomllib
except ImportError:  # Python 3.10; the development tools and tests need 3.11+.
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'pyemuera'


@unittest.skipIf(tomllib is None, 'tomllib requires Python 3.11 or later')
class PackageDataR51(unittest.TestCase):
    def setUp(self):
        self.config = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))

    def runtime_data(self):
        return sorted(
            p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob('*')
            if p.is_file() and p.suffix not in ('.py', '.pyc', '.pyo') and '__pycache__' not in p.parts)

    def test_every_non_python_package_file_is_declared_package_data(self):
        patterns = self.config['tool']['setuptools']['package-data']['pyemuera']
        data = self.runtime_data()
        self.assertTrue(any(name.startswith('resources/') for name in data))
        self.assertTrue(any(name.startswith('specs/') for name in data))
        missing = [name for name in data if not any(fnmatchcase(name, pattern) for pattern in patterns)]
        self.assertEqual(missing, [])

    def test_runtime_data_has_no_nested_directories_outside_patterns(self):
        # setuptools globs do not recurse; a new sub-directory needs its own pattern.
        for name in self.runtime_data():
            with self.subTest(name=name):
                self.assertEqual(name.count('/'), 1)

    def test_project_version_matches_engine_version(self):
        init = (PACKAGE / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('__version__ = "%s"' % self.config['project']['version'], init)


if __name__ == '__main__':
    unittest.main()
