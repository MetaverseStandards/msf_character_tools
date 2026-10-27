# SPDX-License-Identifier: MIT
"""The build backend writes msf_tools/_build_info.json, {"version", "commit"}, into built packages."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import build_info as setup  # noqa: E402
try:
    import build_backend  # noqa: E402
except ImportError:  # scikit-build-core is a build requirement, not a test one
    build_backend = None
finally:
    sys.path.remove(str(ROOT / 'tools'))


STRAY = {'version': '1.2.3', 'commit': 'c' * 40}


def fake_git(top, head, status):
    """Stand-in for build_info._git; top=None means "not inside a Git checkout"."""
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
        self.assertIsNone(self.build_info(status='?? core/include/msf/extra.hpp'))

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


@unittest.skipIf(build_backend is None, 'scikit-build-core not installed')
class Backend(unittest.TestCase):
    """scikit-build-core is faked here; scripts/ci_local.sh builds a real sdist and wheel."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / 'msf_tools').mkdir()
        (self.root / 'pyproject.toml').write_text('[project]\nversion = "1.2.3"\n')
        self.seen = []

    def build(self, hook, status='', **fakes):
        with patch.object(build_backend, 'ROOT', self.root), patch.object(setup, '_git', fake_git('root', 'b' * 40, status)), \
                patch.object(build_backend._backend, hook, **fakes), contextlib.redirect_stdout(io.StringIO()):
            return getattr(build_backend, hook)('dist')

    def record(self):
        path = self.root / 'msf_tools/_build_info.json'
        return json.loads(path.read_text()) if path.exists() else None

    def test_an_sdist_carries_the_record_and_the_tree_is_left_as_it_was(self):
        self.build('build_sdist', side_effect=lambda *args: self.seen.append(self.record()))
        self.assertEqual(self.seen, [{'version': '1.2.3', 'commit': 'b' * 40}])
        self.assertIsNone(self.record())
        (self.root / 'msf_tools/_build_info.json').write_text(json.dumps(STRAY))
        self.build('build_sdist', status=' M msf_tools/mapping.py', side_effect=lambda *args: self.seen.append(self.record()))
        self.assertEqual((self.seen[1], self.record()), (None, STRAY))

    def test_a_wheel_gets_the_record_through_cmake(self):
        def wheel(directory, settings, metadata):
            path = settings.get('cmake.define.MSF_BUILD_INFO_FILE')
            self.seen.append(path and json.loads(Path(path).read_text()))
        self.build('build_wheel', side_effect=wheel)
        self.build('build_wheel', status='?? msf_tools/zz.py', side_effect=wheel)
        self.assertEqual(self.seen, [{'version': '1.2.3', 'commit': 'b' * 40}, None])


if __name__ == '__main__':
    unittest.main()
