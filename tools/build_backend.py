# SPDX-License-Identifier: MIT
"""PEP 517 backend: scikit-build-core, plus the build record; see docs/building.md."""
from pathlib import Path
import tempfile
import tomllib

from scikit_build_core import build as _backend
from scikit_build_core.build import (  # noqa: F401  re-exported hooks
    build_editable, get_requires_for_build_editable, get_requires_for_build_sdist, get_requires_for_build_wheel,
    prepare_metadata_for_build_editable, prepare_metadata_for_build_wheel)

import build_info

ROOT = Path(__file__).resolve().parents[1]


def _record():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    return build_info.build_info(ROOT, version)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    settings = dict(config_settings or {})
    with tempfile.TemporaryDirectory() as tmp:
        record = Path(tmp, "_build_info.json")
        build_info.write(record, _record())
        if record.exists():
            settings["cmake.define.MSF_BUILD_INFO_FILE"] = str(record)
        return _backend.build_wheel(wheel_directory, settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    # pyproject.toml's sdist.include picks the record up although .gitignore lists it.
    path = ROOT / build_info.BUILD_INFO
    previous = path.read_bytes() if path.is_file() else None
    try:
        build_info.write(path, _record())
        return _backend.build_sdist(sdist_directory, config_settings)
    finally:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(previous)
