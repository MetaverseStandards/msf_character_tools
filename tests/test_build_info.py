# SPDX-License-Identifier: MIT
"""setup.py writes msf_tools/_build_info.json, {"version", "commit"}, into built packages."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('msf_setup', ROOT / 'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class GitCheckout(unittest.TestCase):
    """Git's answers are faked here; scripts/ci_local.sh builds a real wheel from a clone and checks its record."""
    def checkout(self, top, status=''):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        answers = {('rev-parse', '--show-toplevel', 'HEAD'): f'{top or root}\n{"b" * 40}',
                   ('status', '--porcelain', '--untracked-files=no'): status}
        fake = patch.object(setup, '_git', lambda where, *args: answers[args])
        fake.start()
        self.addCleanup(fake.stop)
        return root

    def test_a_clean_checkout_names_its_head(self):
        info = setup.build_info(self.checkout(None), '1.2.3')
        self.assertEqual(list(info.items()), [('version', '1.2.3'), ('commit', 'b' * 40)])

    def test_a_dirty_or_nested_checkout_names_no_commit(self):
        self.assertIsNone(setup.build_info(self.checkout(None, ' M msf_tools/__init__.py'), '1.2.3'))
        self.assertIsNone(setup.build_info(self.checkout('/elsewhere'), '1.2.3'))

    def test_no_git_names_no_commit(self):
        def missing(*args):
            raise FileNotFoundError('git')
        with patch.object(setup, '_git', missing):
            self.assertIsNone(setup.build_info(Path(tempfile.gettempdir()), '1.2.3'))


class Sdist(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / 'msf_tools').mkdir()
        no_git = patch.object(setup, 'source_commit', return_value=None)
        no_git.start()
        self.addCleanup(no_git.stop)

    def carry(self, info):
        (self.root / 'msf_tools/_build_info.json').write_text(json.dumps(info))

    def test_an_sdist_carries_its_checkouts_record(self):
        self.assertIsNone(setup.build_info(self.root, '1.2.3'))
        good = {'version': '1.2.3', 'commit': 'a' * 40}
        self.carry(good)
        self.assertEqual(setup.build_info(self.root, '1.2.3'), good)
        for bad in ({'version': '1.2.4', 'commit': 'a' * 40}, {'version': '1.2.3', 'commit': 'A' * 40},
                    {'version': '1.2.3', 'commit': 'a' * 39}, {'version': '1.2.3'}, ['1.2.3']):
            with self.subTest(info=bad):
                self.carry(bad)
                self.assertIsNone(setup.build_info(self.root, '1.2.3'))


if __name__ == '__main__':
    unittest.main()
