# SPDX-License-Identifier: MIT
"""Builds record their source commit in msf_tools/_build_info.json; see docs/building.md."""
import json
from pathlib import Path
import re
import subprocess

BUILD_INFO = Path("msf_tools", "_build_info.json")
ROOT = Path(__file__).resolve().parent


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def source_commit(root):
    """HEAD when root is the top of a Git checkout with no changes to tracked files, else None."""
    try:
        top, head = _git(root, "rev-parse", "--show-toplevel", "HEAD").splitlines()
        if Path(top).resolve() != Path(root).resolve() or _git(root, "status", "--porcelain", "--untracked-files=no"):
            return None
        return head
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def build_info(root, version):
    """{"version", "commit"} for a build from root, or None when the source commit is unknown.

    A clean checkout names its HEAD. An sdist has no .git, so it carries the record
    its checkout wrote, which is used only if it names this version.
    """
    commit = source_commit(root)
    if commit is not None:
        return {"version": version, "commit": commit}
    carried = Path(root) / BUILD_INFO
    try:
        info = json.loads(carried.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (isinstance(info, dict) and set(info) == {"version", "commit"} and info["version"] == version
            and isinstance(info["commit"], str) and re.fullmatch("[0-9a-f]{40}", info["commit"])):
        return {"version": version, "commit": info["commit"]}
    return None


def _write(path, info):
    path = Path(path)
    if info is None:
        path.unlink(missing_ok=True)
        print(f"warning: no source commit for this build (not a clean Git checkout or a recorded sdist); {BUILD_INFO} omitted")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    from setuptools import setup
    from setuptools.command.build_py import build_py
    from setuptools.command.sdist import sdist

    class BuildPy(build_py):
        def run(self):
            super().run()
            if not getattr(self, "editable_mode", False):
                _write(Path(self.build_lib, BUILD_INFO), build_info(ROOT, self.distribution.get_version()))

        def get_outputs(self, include_bytecode=True):
            extra = Path(self.build_lib, BUILD_INFO)
            return super().get_outputs(include_bytecode) + ([str(extra)] if extra.is_file() else [])

    class Sdist(sdist):
        def make_release_tree(self, base_dir, files):
            super().make_release_tree(base_dir, files)
            _write(Path(base_dir, BUILD_INFO), build_info(ROOT, self.distribution.get_version()))

    setup(cmdclass={"build_py": BuildPy, "sdist": Sdist})
