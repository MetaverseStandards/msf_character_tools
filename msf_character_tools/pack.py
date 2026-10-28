# SPDX-License-Identifier: MIT
"""Validated deterministic pack, survey CSV, coverage and checksums."""
from collections.abc import Mapping
from dataclasses import dataclass, field

from .authoring import ValidatedAuthoring, _TOKEN
from .common import thaw
from .report import public, fail
from .records import OwnedRecord, _admit


@dataclass(frozen=True)
class Pack(OwnedRecord):
    _handle_views = ("document",)
    document: Mapping
    sha256: str
    _core: object = field(default=None, init=False, repr=False, compare=False)

    def to_dict(self):
        self._check_integrity()
        return thaw(self.document)

    def to_bytes(self):
        self._check_integrity()
        return self._core.canonical()

    def _check_consistency(self):
        if self._core is None or not self._core.check_view(self.document):
            fail("E_RECORD_INTEGRITY", "/", "Pack view disagrees with its core document.")
        if self._core.sha256() != self.sha256:
            fail("E_RECORD_INTEGRITY", "/", "Pack canonical bytes and digest disagree.")

    @property
    def signals(self):
        self._check_integrity()
        return {s["id"]: s for s in self.document["signals"]}


@public
def compile_pack(validated_authoring):
    if not isinstance(validated_authoring, ValidatedAuthoring) or validated_authoring._token is not _TOKEN:
        fail("E_VALIDATED_REQUIRED", "/", "compile_pack requires validated_authoring.", "Call validate_authoring or load_authoring and check its Result first.")
    validated_authoring._check_integrity()
    handle = validated_authoring._core
    record = Pack(handle.view(), handle.sha256())
    object.__setattr__(record, "_core", handle)
    return _admit(record)


def survey_csv(pack):
    pack._check_integrity()
    return pack._core.survey_csv()


def coverage(pack):
    pack._check_integrity()
    return pack._core.coverage()
