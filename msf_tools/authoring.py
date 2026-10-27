# SPDX-License-Identifier: MIT
"""Strict authoring validation. Authoring is data, never executable code."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import os
import stat
import tomllib

from . import _native
from .common import thaw, SPECIAL_FILE_ERRNOS
from .report import public, Diagnostic, Report, Result, fail
from .records import OwnedRecord, _admit

_core = _native.built
_TOKEN = object()


@dataclass(frozen=True)
class ValidatedAuthoring(OwnedRecord):
    _handle_views = ("document",)
    document: Mapping
    _token: object
    _core: object = field(default=None, init=False, repr=False, compare=False)

    def _check_consistency(self):
        if self._core is None or not self._core.check_view(self.document):
            fail("E_RECORD_INTEGRITY", "/", "Authoring view disagrees with its core document.")

    def to_dict(self):
        self._check_integrity()
        return thaw(self.document)


def _validated(outcome):
    diagnostics, handle = outcome
    report = Report(tuple(Diagnostic(*d) for d in diagnostics))
    if handle is None:
        return Result(None, report)
    record = ValidatedAuthoring(handle.view(), _TOKEN)
    object.__setattr__(record, "_core", handle)
    return Result(_admit(record), report)


@public
def validate_authoring(document):
    return _validated(_core.validate_authoring(document))


@public
def load_authoring(path):
    path = Path(path)
    if path.is_file():
        return validate_authoring(tomllib.loads(path.read_text(encoding="utf-8")))
    if not path.is_dir() or not (path / "pack.toml").is_file():
        fail("E_AUTHORING_PATH", "/", "Expected TOML file or directory containing pack.toml.")
    merger = _core.Merger()
    files = authoring_files(path)
    names = set()
    for p in files:
        relative = p.relative_to(path)
        if p.is_symlink() or any((path.joinpath(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts))):
            fail("E_FRAGMENT_PATH", str(relative), "Symlink fragments are forbidden.")
        folded = str(relative).casefold()
        if folded in names or any(part.split('.')[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))} for part in relative.parts):
            fail("E_FRAGMENT_PATH", str(relative), "Reserved filename or case-insensitive collision.")
        names.add(folded)
        merger.add(str(relative), tomllib.loads(_read_fragment(p, relative)))
    return _validated(merger.validate())


def _read_fragment(path, relative):
    # Fragments are discovered, not named by the caller. O_NONBLOCK keeps a FIFO
    # from blocking the open so the descriptor check can refuse it.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno in SPECIAL_FILE_ERRNOS:
            fail("E_FRAGMENT_PATH", str(relative), "Authoring fragments must be regular files.")
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            fail("E_FRAGMENT_PATH", str(relative), "Authoring fragments must be regular files.")
        with os.fdopen(fd, encoding="utf-8", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def authoring_files(path):
    """Prune hidden/generated directories before traversal; paths sorted globally."""
    path = Path(path)
    files = []
    for directory, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "generated"]
        for name in names:
            if not name.startswith(".") and name.endswith(".toml"):
                files.append(Path(directory) / name)
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                fail("E_FRAGMENT_PATH", str((Path(directory) / name).relative_to(path)), "Symlink fragment directories are forbidden.")
    return sorted(files)
