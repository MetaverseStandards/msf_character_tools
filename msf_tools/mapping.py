# SPDX-License-Identifier: MIT
"""Typed virtual profiles, dependency compilation and sample evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
import math

from .authoring import keys, in_domain
from .common import freeze, thaw, digest, canonical_json, number
from .pack import Pack
from .snapshot import AssetSnapshot
from .report import public, fail, Fault, Result, Report, Loss


@public
def profile_snapshot(pack, id):
    if not isinstance(pack, Pack) or type(id) is not str:
        fail("E_PACK", "/", "Expected a compiled Pack and explicit profile ID.")
    profile = next((p for p in pack.document["profiles"] if p["id"] == id), None)
    if profile is None:
        fail("E_PROFILE", "/profiles", f"Unknown profile {id}.")
    signals = pack.signals
    channels = {sid: {k: signals[sid][k] for k in ("id", "value_type", "units", "domain", "calibration")} for sid in profile["signal_ids"]}
    doc = {"schema_version": "1.0", "profile": thaw(profile), "pack_sha256": pack.sha256, "channels": thaw(channels)}
    raw = canonical_json(doc)
    return AssetSnapshot("profile", raw, digest(raw), freeze(doc), channels=freeze(channels))


@dataclass(frozen=True)
class CompiledMapping:
    pack: Pack
    source_snapshot: AssetSnapshot
    target_snapshot: AssetSnapshot
    mapping_id: str
    instructions: tuple
    required_inputs: tuple[str, ...]
    output_ids: tuple[str, ...]
    losses: tuple[Loss, ...]

    def to_dict(self):
        return {"schema_version": "1.0", "pack_sha256": self.pack.sha256,
                "source_sha256": self.source_snapshot.sha256, "target_sha256": self.target_snapshot.sha256,
                "mapping_id": self.mapping_id, "instructions": thaw(self.instructions),
                "required_inputs": list(self.required_inputs), "outputs": list(self.output_ids),
                "source_bindings": thaw(self.source_snapshot.bindings),
                "target_bindings": thaw(self.target_snapshot.bindings),
                "losses": [loss.to_dict() for loss in self.losses]}


@public
def compile_mapping(pack, source_snapshot, target_snapshot, mapping_id, allow_approximation=False):
    if not isinstance(pack, Pack) or not isinstance(source_snapshot, AssetSnapshot) or not isinstance(target_snapshot, AssetSnapshot):
        fail("E_MAPPING_TYPE", "/", "Expected Pack and explicit source/target snapshots.")
    if type(allow_approximation) is not bool or type(mapping_id) is not str:
        fail("E_MAPPING_TYPE", "/", "Mapping ID must be a string and approximation policy boolean.")
    mapping = next((m for m in pack.document["mappings"] if m["id"] == mapping_id), None)
    if mapping is None:
        fail("E_MAPPING_REFERENCE", "/mappings", f"Unknown mapping {mapping_id}.")
    signals = pack.signals
    diagnostics, losses = [], []
    def check(fn, *args):
        try:
            fn(*args)
        except Fault as exc:
            diagnostics.append(exc.diagnostic)
    def channel(sid, snapshot):
        if sid not in (snapshot.channels or {}):
            fail("E_CHANNEL_REFERENCE", sid, "Required channel is absent from snapshot.", "Use profile_snapshot or hash-bound structural sidecar bindings.")
        if snapshot.format == "profile" and snapshot.document.get("pack_sha256") != pack.sha256:
            fail("E_STALE_SOURCE", sid, "Profile snapshot belongs to a different pack.")
        actual = snapshot.channels[sid]
        expected = signals[sid]
        if any(actual[k] != expected[k] for k in ("value_type", "units", "domain", "calibration")):
            fail("E_CHANNEL_TYPE", sid, "Snapshot channel type/domain/calibration disagrees with pack.")
    writers = {}
    rules = mapping["rules"]
    for r in rules:
        rid = r["id"]
        if r["disposition"] != "mapped":
            check(fail, "E_UNRESOLVED_RULE", rid, "Requested mapping contains an unsupported, unresolved or excluded rule.")
        if r.get("mapping_quality") == "approximate" and not allow_approximation:
            check(fail, "E_APPROXIMATION", rid, "Approximate rule requires explicit opt-in.")
        if r.get("mapping_quality") == "approximate" and not r["loss_annotations"]:
            losses.append(Loss("signal", "approximated", "Declared approximate mapping.", (rid,)))
        for loss in r["loss_annotations"]:
            if loss["effect"] in ("approximated", "dropped", "unknown") and not allow_approximation:
                check(fail, "E_APPROXIMATION", rid, "Declared loss requires explicit approximation opt-in.")
            losses.append(Loss(loss["category"], loss["effect"], loss["reason"], tuple(loss["refs"]), loss.get("units"), loss.get("bound")))
        for sid in (*r["inputs"], *r["outputs"]):
            if signals[sid]["disposition"] != "mapped":
                check(fail, "E_SIGNAL_DISPOSITION", rid, f"Signal {sid} is not mapped.")
        output = r["outputs"][0]
        if output in writers:
            check(fail, "E_MULTIPLE_WRITERS", output, "Two rules write the same signal.")
        writers[output] = rid
        inputs, out = [signals[s] for s in r["inputs"]], signals[output]
        if any(s["value_type"] != out["value_type"] for s in inputs):
            check(fail, "E_SHAPE", rid, "Operator shapes disagree.")
        if any(s["units"] != out["units"] for s in inputs) and not (r["operator"]["id"] == "affine" and r["assumptions"]):
            check(fail, "E_UNITS", rid, "Unit conversion needs explicit affine coefficients and assumptions.")
        if r["operator"]["id"] == "identity" and inputs[0]["calibration"] != out["calibration"]:
            check(fail, "E_CALIBRATION", rid, "Identity requires the same explicit calibration basis.")
        if r["operator"]["id"] == "identity" and inputs[0]["domain"] != out["domain"]:
            check(fail, "E_DOMAIN_COMPATIBILITY", rid, "Identity requires equal declared domains.")
    dependencies = {r["id"]: {writers[s] for s in r["inputs"] if s in writers} for r in rules}
    ordered = []
    done = set()
    while len(done) < len(rules):
        available = [r for r in rules if r["id"] not in done and dependencies[r["id"]] <= done]
        if not available:
            check(fail, "E_MAPPING_CYCLE", mapping_id, "Mapping dependency graph contains a cycle.")
            break
        for r in available:
            ordered.append(r)
            done.add(r["id"])
    required = tuple(dict.fromkeys(s for r in rules for s in r["inputs"] if s not in writers))
    outputs = tuple(dict.fromkeys(r["outputs"][0] for r in rules if r["outputs"][0] in (target_snapshot.channels or {})))
    for sid in required:
        check(channel, sid, source_snapshot)
    for sid in writers:
        if sid in (source_snapshot.channels or {}):
            check(fail, "E_MULTIPLE_WRITERS", sid, "Rule output is also a source channel driver.")
        # Intermediate values can remain virtual; terminal outputs must be target-bound.
        if sid in (target_snapshot.channels or {}) or not any(sid in r["inputs"] for r in rules):
            check(channel, sid, target_snapshot)
    if not outputs:
        check(fail, "E_MAPPING_OUTPUT", mapping_id, "Mapping has no target-bound outputs.")
    report = Report(tuple(diagnostics), tuple(losses))
    compiled = CompiledMapping(pack, source_snapshot, target_snapshot, mapping_id, tuple(ordered), required, outputs, tuple(losses))
    return Result(compiled if report.ok else None, report)


@dataclass(frozen=True)
class EvaluatedValues:
    samples: tuple

    def to_dict(self):
        return {"samples": thaw(self.samples)}


@public
def evaluate_mapping(compiled_mapping, samples):
    if not isinstance(compiled_mapping, CompiledMapping) or not isinstance(samples, (tuple, list)):
        fail("E_SAMPLE_TYPE", "/", "Expected CompiledMapping and sample frame array.")
    diagnostics, frames = [], []
    signals = compiled_mapping.pack.signals
    for i, frame in enumerate(samples):
        ref = f"/samples/{i}"
        values = {}
        invalid = set()
        try:
            keys(frame, {"timestamp", "values", "validity"}, set(), ref)
            if not number(frame["timestamp"]) or frame["timestamp"] < 0:
                fail("E_TIMESTAMP", ref + "/timestamp", "Timestamp must be nonnegative finite seconds.")
            if not isinstance(frame["values"], Mapping) or not isinstance(frame["validity"], Mapping):
                fail("E_SAMPLE_TYPE", ref, "values and validity must be objects by signal ID.")
            for sid in set(frame["values"]) | set(frame["validity"]):
                try:
                    if sid not in (compiled_mapping.source_snapshot.channels or {}):
                        fail("E_SAMPLE_REFERENCE", ref, f"Sample contains unknown/non-source channel {sid}.")
                    if sid not in frame["values"] or sid not in frame["validity"] or type(frame["validity"][sid]) is not bool:
                        fail("E_VALIDITY", ref + "/" + str(sid), "Every supplied value needs explicit boolean validity.")
                    in_domain(frame["values"][sid], signals[sid]["domain"], ref + "/" + sid)
                    if not frame["validity"][sid]:
                        fail("E_INVALID_SAMPLE", ref + "/" + sid, "Input is explicitly invalid; neutral is not substituted.")
                    values[sid] = float(frame["values"][sid])
                except Fault as exc:
                    diagnostics.append(exc.diagnostic)
                    invalid.add(sid)
            for sid in compiled_mapping.required_inputs:
                if sid not in values and sid not in invalid:
                    diagnostics.append(Fault("E_MISSING_SAMPLE", ref + "/" + sid, "Required input or validity is missing.").diagnostic)
            for rule in compiled_mapping.instructions:
                output = rule["outputs"][0]
                if any(s not in values for s in rule["inputs"]):
                    continue
                try:
                    args = [values[s] for s in rule["inputs"]]
                    op = rule["operator"]
                    value = args[0] if op["id"] == "identity" else op["scale"] * args[0] + op["offset"] if op["id"] == "affine" else sum(float(w) * x for w, x in zip(op["weights"], args))
                    in_domain(value, signals[output]["domain"], ref + "/rules/" + rule["id"])
                    values[output] = float(value)
                except Fault as exc:
                    diagnostics.append(exc.diagnostic)
            written = {sid: values[sid] for sid in compiled_mapping.output_ids if sid in values}
            frames.append(freeze({"timestamp": float(frame["timestamp"]), "values": written, "validity": {sid: True for sid in written}}))
        except Fault as exc:
            diagnostics.append(exc.diagnostic)
    report = Report(tuple(diagnostics), compiled_mapping.losses)
    return Result(EvaluatedValues(tuple(frames)) if report.ok else None, report)
