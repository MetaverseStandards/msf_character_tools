# SPDX-License-Identifier: MIT
"""setup.py writes msf_tools/_build_info.json, {"version", "commit"}, into built packages."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('msf_setup', ROOT / 'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


STRAY = {'version': '1.2.3', 'commit': 'c' * 40}


def fake_git(top, head, status):
    """Stand-in for setup._git; top=None means "not inside a Git checkout"."""
    def git(root, *args):
        if top is None:
            raise subprocess.CalledProcessError(128, 'git')
        return {('rev-parse', '--show-toplevel', 'HEAD'): f'{root if top == "root" else top}\n{head}',
                ('status', '--porcelain', '--untracked-files=all'): status}[args]
    return git


class Tree(unittest.TestCase):
    """Git's answers are faked here; scripts/ci_local.sh builds a real wheel from a clone and checks its record."""
    def build_info(self, top='root', status='', carried=None, git=None):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / 'msf_tools').mkdir()
        if carried is not None:
            (root / 'msf_tools/_build_info.json').write_text(json.dumps(carried))
        with patch.object(setup, '_git', git or fake_git(top, 'b' * 40, status)):
            return setup.build_info(root, '1.2.3')


class GitCheckout(Tree):
    def test_a_clean_checkout_names_its_head(self):
        self.assertEqual(list(self.build_info().items()), [('version', '1.2.3'), ('commit', 'b' * 40)])
        self.assertEqual(self.build_info(status='?? notes.txt\n?? docs/draft.md')['commit'], 'b' * 40)

    def test_a_dirty_or_nested_checkout_names_no_commit(self):
        self.assertIsNone(self.build_info(status=' M msf_tools/__init__.py'))
        self.assertIsNone(self.build_info(status=' M README.md'))
        self.assertIsNone(self.build_info(top='/elsewhere'))

    def test_untracked_package_files_would_be_built_so_name_no_commit(self):
        self.assertIsNone(self.build_info(status='?? msf_tools/zz_untracked.py'))
        self.assertIsNone(self.build_info(status='?? notes.txt\n?? msf_tools/sources/extra.py'))
        self.assertIsNone(self.build_info(status='?? "msf_tools/with space.py"'))

    def test_a_record_left_in_a_checkout_is_never_used(self):
        self.assertIsNone(self.build_info(status=' M msf_tools/mapping.py', carried=STRAY))
        self.assertIsNone(self.build_info(top='/elsewhere', carried=STRAY))
        self.assertEqual(self.build_info(carried=STRAY)['commit'], 'b' * 40)


class Sdist(Tree):
    def test_an_sdist_outside_any_checkout_carries_its_checkouts_record(self):
        self.assertIsNone(self.build_info(top=None))
        good = {'version': '1.2.3', 'commit': 'a' * 40}
        self.assertEqual(self.build_info(top=None, carried=good), good)
        for bad in ({'version': '1.2.4', 'commit': 'a' * 40}, {'version': '1.2.3', 'commit': 'A' * 40},
                    {'version': '1.2.3', 'commit': 'a' * 39}, {'version': '1.2.3'}, ['1.2.3']):
            with self.subTest(info=bad):
                self.assertIsNone(self.build_info(top=None, carried=bad))

    def test_a_checkout_without_commits_is_still_a_checkout(self):
        def no_head(root, *args):
            if args == ('rev-parse', '--is-inside-work-tree'):
                return 'true'
            raise subprocess.CalledProcessError(128, 'git')
        self.assertIsNone(self.build_info(git=no_head, carried=STRAY))

    def test_without_git_only_a_carried_record_counts(self):
        def missing(*args):
            raise FileNotFoundError('git')
        self.assertIsNone(self.build_info(git=missing))
        self.assertEqual(self.build_info(git=missing, carried=STRAY), STRAY)


class StaleBuild(unittest.TestCase):
    def test_a_module_left_in_build_lib_by_an_earlier_build_is_not_shipped(self):
        from setuptools.dist import Distribution
        build_lib = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, build_lib)
        (build_lib / 'msf_tools').mkdir()
        (build_lib / 'msf_tools/zz_deleted.py').write_text('gone = True\n')
        command = setup.BuildPy(Distribution({'name': 'msf-tools', 'version': '1.2.3', 'packages': ['msf_tools', 'msf_tools.sources'],
                                               'script_name': 'setup.py'}))
        command.build_lib = str(build_lib)
        command.ensure_finalized()
        with contextlib.chdir(ROOT), patch.object(setup, 'build_info', return_value=STRAY), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            command.run()
        built = {p.relative_to(build_lib).as_posix() for p in build_lib.rglob('*') if p.is_file()}
        self.assertNotIn('msf_tools/zz_deleted.py', built)
        self.assertLessEqual({'msf_tools/__init__.py', 'msf_tools/sources/__init__.py', 'msf_tools/_build_info.json'}, built)


if __name__ == '__main__':
    unittest.main()
