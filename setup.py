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


def checkout(root):
    """Where root stands in Git: (True, HEAD or None) inside a checkout, (False, None) outside one.

    HEAD is given only at the top of a checkout with no changes to tracked files and
    no untracked files under msf_tools/, which setuptools would build into the wheel.
    """
    try:
        top, head = _git(root, "rev-parse", "--show-toplevel", "HEAD").splitlines()
    except (OSError, ValueError):
        return False, None
    except subprocess.CalledProcessError:
        # Also fails inside a checkout with no commits yet.
        try:
            return _git(root, "rev-parse", "--is-inside-work-tree") == "true", None
        except subprocess.CalledProcessError:
            return False, None
    if Path(top).resolve() != Path(root).resolve():
        return True, None
    for line in _git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
        if not line.startswith("?? ") or line[3:].lstrip('"').startswith("msf_tools/"):
            return True, None
    return True, head


def build_info(root, version):
    """{"version", "commit"} for a build from root, or None when the source commit is unknown.

    Inside a Git checkout only Git counts, so a record left in a dirty checkout is
    never used. An sdist has no .git, so outside any checkout the record its
    checkout wrote is used, if it names this version.
    """
    inside, commit = checkout(root)
    if inside:
        return None if commit is None else {"version": version, "commit": commit}
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
