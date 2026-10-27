# SPDX-License-Identifier: MIT
"""Typed virtual profiles, dependency compilation and sample evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field

from .common import freeze, thaw
from .pack import Pack
from .snapshot import AssetSnapshot, _identity, _record, _source_summary
from .report import public, fail, Diagnostic, Result, Report, Loss
from . import _native
from .records import OwnedRecord, _admit

_core = _native.required()


@public
def profile_snapshot(pack, id):
    if not isinstance(pack, Pack) or type(id) is not str:
        fail("E_PACK", "/", "Expected a compiled Pack and explicit profile ID.")
    pack._check_integrity()
    raw, sha256, doc, channels = pack._core.profile(id)
    document = freeze(doc)
    return _admit(_record(_core.profile_snapshot(raw, sha256, document), document, channels=freeze(channels)))


@dataclass(frozen=True)
class CompiledMapping(OwnedRecord):
    _handle_views = ("instructions", "required_inputs", "output_ids")
    pack: Pack
    source_snapshot: AssetSnapshot
    target_snapshot: AssetSnapshot
    mapping_id: str
    instructions: tuple
    required_inputs: tuple[str, ...]
    output_ids: tuple[str, ...]
    losses: tuple[Loss, ...]
    _core: object = field(default=None, init=False, repr=False, compare=False)

    def _check_consistency(self):
        core = self._core
        if (core is None or not core.check_views(self.instructions, self.required_inputs, self.output_ids)
                or not core.compiled_from(self.pack._core, self.mapping_id)):
            fail("E_RECORD_INTEGRITY", "/instructions", "Compiled views disagree with their core mapping.")
        signals = {s["id"]: s for s in self.pack.document["signals"]}
        for snapshot in (self.source_snapshot, self.target_snapshot):
            _check_profile(snapshot, self.pack, signals)

    def to_dict(self):
        self._check_integrity()
        result = {"schema_version": "1.0", "pack_sha256": self.pack.sha256,
                  "source_sha256": _identity(self.source_snapshot), "target_sha256": _identity(self.target_snapshot),
                  "mapping_id": self.mapping_id, "instructions": thaw(self.instructions),
                  "required_inputs": list(self.required_inputs), "outputs": list(self.output_ids),
                  "source_bindings": thaw(self.source_snapshot.bindings),
                  "target_bindings": thaw(self.target_snapshot.bindings),
                  "losses": [loss.to_dict() for loss in self.losses]}
        for side, snapshot in (("source", self.source_snapshot), ("target", self.target_snapshot)):
            if snapshot.source is not None:
                result[side + "_adapter"] = _source_summary(snapshot)
        return result


def _check_profile(snapshot, pack, signals):
    if snapshot.format != "profile":
        return
    if snapshot.document["pack_sha256"] != pack.sha256:
        fail("E_STALE_SOURCE", "/profile", "Profile snapshot belongs to a different pack.")
    profile = snapshot.document["profile"]
    expected = next((p for p in pack.document["profiles"] if p["id"] == profile["id"]), None)
    channels = {sid: {k: signals[sid][k] for k in ("id", "value_type", "units", "domain", "calibration")}
                for sid in expected["signal_ids"]} if expected is not None else None
    if profile != expected or snapshot.channels != channels:
        fail("E_RECORD_INTEGRITY", "/profile", "Profile selection/channels disagree with pack.")



@public
def compile_mapping(pack, source_snapshot, target_snapshot, mapping_id, allow_approximation=False):
    if not isinstance(pack, Pack) or not isinstance(source_snapshot, AssetSnapshot) or not isinstance(target_snapshot, AssetSnapshot):
        fail("E_MAPPING_TYPE", "/", "Expected Pack and explicit source/target snapshots.")
    if type(allow_approximation) is not bool or type(mapping_id) is not str:
        fail("E_MAPPING_TYPE", "/", "Mapping ID must be a string and approximation policy boolean.")
    pack._check_integrity()
    source_snapshot._check_integrity()
    target_snapshot._check_integrity()
    signals = {s["id"]: s for s in pack.document["signals"]}
    for snapshot in (source_snapshot, target_snapshot):
        _check_profile(snapshot, pack, signals)
    diagnostics, losses, handle = _core.compile_mapping(pack._core, mapping_id, allow_approximation,
                                                        source_snapshot.channels, target_snapshot.channels)
    losses = tuple(Loss(*loss) for loss in losses)
    report = Report(tuple(Diagnostic(*d) for d in diagnostics), losses)
    if handle is None:
        return Result(None, report)
    compiled = CompiledMapping(pack, source_snapshot, target_snapshot, mapping_id, *handle.views(), losses)
    object.__setattr__(compiled, "_core", handle)
    return Result(_admit(compiled), report)


@dataclass(frozen=True)
class EvaluatedValues(OwnedRecord):
    _handle_views = ("samples",)
    samples: tuple
    _core: object = field(default=None, init=False, repr=False, compare=False)

    def _check_consistency(self):
        if self._core is None or not self._core.check_view(self.samples):
            fail("E_RECORD_INTEGRITY", "/samples", "Sample views disagree with their core frames.")

    def to_dict(self):
        self._check_integrity()
        return {"samples": thaw(self.samples)}


@public
def evaluate_mapping(compiled_mapping, samples):
    if not isinstance(compiled_mapping, CompiledMapping) or not isinstance(samples, (tuple, list)):
        fail("E_SAMPLE_TYPE", "/", "Expected CompiledMapping and sample frame array.")
    compiled_mapping._check_integrity()
    core = compiled_mapping._core
    # The fast path declines (None) any sample it cannot take; MSF_TOOLS_PURE=1 skips it.
    frames = core.evaluate(samples) if _native.core is not None else None
    if frames is None:
        diagnostics, frames = core.evaluate_exact(samples)
        if frames is None:
            return Result(None, Report(tuple(Diagnostic(*d) for d in diagnostics), compiled_mapping.losses))
    record = EvaluatedValues(frames.view())
    object.__setattr__(record, "_core", frames)
    return Result(_admit(record), Report((), compiled_mapping.losses))
