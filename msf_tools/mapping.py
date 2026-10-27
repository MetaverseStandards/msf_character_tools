# SPDX-License-Identifier: MIT
"""Typed virtual profiles, dependency compilation and sample evaluation."""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
import json
from collections.abc import Mapping

from .authoring import keys, in_domain
from .common import freeze, thaw, digest, canonical_json, number
from .pack import Pack
from .snapshot import AssetSnapshot, _identity, _source_summary
from .report import public, fail, Fault, Result, Report, Loss
from . import _native
from .records import OwnedRecord, _admit
from .math3d import _add, _divide, _product, _sub, _sum

_LOSS_EFFECTS = {"approximated", "dropped", "unknown"}


@public
def profile_snapshot(pack, id):
    if not isinstance(pack, Pack) or type(id) is not str:
        fail("E_PACK", "/", "Expected a compiled Pack and explicit profile ID.")
    pack._check_integrity()
    profile = next((p for p in pack.document["profiles"] if p["id"] == id), None)
    if profile is None:
        fail("E_PROFILE", "/profiles", f"Unknown profile {id}.")
    signals = {s["id"]: s for s in pack.document["signals"]}
    channels = {sid: {k: signals[sid][k] for k in ("id", "value_type", "units", "domain", "calibration")} for sid in profile["signal_ids"]}
    doc = {"schema_version": "1.0", "profile": thaw(profile), "pack_sha256": pack.sha256, "channels": thaw(channels)}
    raw = canonical_json(doc)
    return _admit(AssetSnapshot("profile", raw, digest(raw), doc, channels=channels))


@dataclass(frozen=True)
class CompiledMapping(OwnedRecord):
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
        if self._core is not None and _program_document(self) != self._core.document():
            fail("E_RECORD_INTEGRITY", "/instructions", "Compiled views disagree with their core program.")
        mapping = next((m for m in self.pack.document["mappings"] if m["id"] == self.mapping_id), None)
        if mapping is None:
            fail("E_RECORD_INTEGRITY", "/mapping_id", "Compiled mapping has no authoring source.")
        rules = mapping["rules"]
        writers = {r["outputs"][0]: r["id"] for r in rules}
        authored = {r["id"]: r for r in rules}
        done = set()
        for rule in self.instructions:
            dependencies = {writers[s] for s in rule["inputs"] if s in writers}
            if rule != authored.get(rule["id"]) or rule["id"] in done or not dependencies <= done:
                fail("E_RECORD_INTEGRITY", "/instructions", "Compiled instructions disagree with authoring/dependencies.")
            done.add(rule["id"])
        required = tuple(dict.fromkeys(s for r in rules for s in r["inputs"] if s not in writers))
        outputs = tuple(dict.fromkeys(r["outputs"][0] for r in rules if r["outputs"][0] in self.target_snapshot.channels))
        if done != authored.keys() or required != self.required_inputs or outputs != self.output_ids:
            fail("E_RECORD_INTEGRITY", "/instructions", "Compiled rule coverage or input/output IDs disagree.")
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


def _dependency_waves(rules, dependencies):
    """Order rules in dependency waves; rules on or behind a cycle are left out."""
    by_id = {r["id"]: r for r in rules}
    position = {r["id"]: i for i, r in enumerate(rules)}
    dependents = {rid: [] for rid in dependencies}
    for rid, needs in dependencies.items():
        for need in needs:
            dependents[need].append(rid)
    pending = {rid: len(needs) for rid, needs in dependencies.items()}
    # A rule joins the wave after the one holding its last dependency, and each
    # wave runs in declaration order: [A needs B, B, C] gives [B, C, A].
    wave = [r["id"] for r in rules if not pending[r["id"]]]
    ordered = []
    while wave:
        ordered.extend(by_id[rid] for rid in wave)
        ready = []
        for rid in wave:
            for dependent in dependents[rid]:
                pending[dependent] -= 1
                if not pending[dependent]:
                    ready.append(dependent)
        wave = sorted(ready, key=position.__getitem__)
    return ordered


@public
def compile_mapping(pack, source_snapshot, target_snapshot, mapping_id, allow_approximation=False):
    if not isinstance(pack, Pack) or not isinstance(source_snapshot, AssetSnapshot) or not isinstance(target_snapshot, AssetSnapshot):
        fail("E_MAPPING_TYPE", "/", "Expected Pack and explicit source/target snapshots.")
    if type(allow_approximation) is not bool or type(mapping_id) is not str:
        fail("E_MAPPING_TYPE", "/", "Mapping ID must be a string and approximation policy boolean.")
    pack._check_integrity()
    source_snapshot._check_integrity()
    target_snapshot._check_integrity()
    # Reuse the checked pack's index within this operation. Full profile
    # comparisons belong at the boundary, outside the per-channel loop.
    signals = {s["id"]: s for s in pack.document["signals"]}
    for snapshot in (source_snapshot, target_snapshot):
        _check_profile(snapshot, pack, signals)
    mapping = next((m for m in pack.document["mappings"] if m["id"] == mapping_id), None)
    if mapping is None:
        fail("E_MAPPING_REFERENCE", "/mappings", f"Unknown mapping {mapping_id}.")
    diagnostics, losses = [], []
    evidence = {e["id"]: e for e in pack.document["evidence"]}
    def check(fn, *args):
        try:
            fn(*args)
        except Fault as exc:
            diagnostics.append(exc.diagnostic)
    def execution_evidence(record, kind, rule):
        # Inventory validation preserves statuses; execution checks each own
        # reference. These declarations do not establish domain equivalence.
        sid, status = record["id"], record["evidence_status"]
        if kind == "Rule":
            if status == "unresolved":
                check(fail, "E_EVIDENCE_STATUS", sid, f"Rule {sid} has unresolved evidence_status and cannot execute.")
        elif status == "unresolved" or rule["evidence_status"] == "verified_current" and status != "verified_current":
            check(fail, "E_EVIDENCE_STATUS", sid, f"Signal {sid} has evidence_status {status}, incompatible with rule {rule['id']} ({rule['evidence_status']}).")
        if not record["evidence"]:
            check(fail, "E_EVIDENCE_REQUIRED", sid, f"{kind} {sid} requires nonempty evidence for execution.")
        for eid in record["evidence"]:
            ref_status = evidence[eid]["status"]
            if ref_status == "unresolved" or status == "verified_current" and ref_status != "verified_current":
                check(fail, "E_EVIDENCE_COMPATIBILITY", sid, f"{kind} {sid} includes evidence {eid} with status {ref_status}, incompatible with its evidence_status {status}.")
    def channel(sid, snapshot):
        if sid not in (snapshot.channels or {}):
            fail("E_CHANNEL_REFERENCE", sid, "Required channel is absent from snapshot.", "Use profile_snapshot or hash-bound structural sidecar bindings.")
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
        execution_evidence(r, "Rule", r)
        if r.get("mapping_quality") == "approximate" and not allow_approximation:
            check(fail, "E_APPROXIMATION", rid, "Approximate rule requires explicit opt-in.")
        if r.get("mapping_quality") == "approximate" and not r["loss_annotations"]:
            check(fail, "E_LOSS_REQUIRED", rid, f"Approximate rule {rid} requires explicit loss_annotations.")
        for loss in r["loss_annotations"]:
            if loss["effect"] in _LOSS_EFFECTS and not allow_approximation:
                check(fail, "E_APPROXIMATION", rid, "Declared loss requires explicit approximation opt-in.")
            losses.append(Loss(loss["category"], loss["effect"], loss["reason"], tuple(loss["refs"]), loss.get("units"), loss.get("bound")))
        for sid in (*r["inputs"], *r["outputs"]):
            if signals[sid]["disposition"] != "mapped":
                check(fail, "E_SIGNAL_DISPOSITION", rid, f"Signal {sid} is not mapped.")
            execution_evidence(signals[sid], "Signal", r)
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
        if r["operator"]["id"] == "piecewise_linear":
            knots, bounds = r["operator"]["knots"], inputs[0]["domain"]
            if bounds.get("min") != knots[0][0] or bounds.get("max") != knots[-1][0]:
                check(fail, "E_DOMAIN_COMPATIBILITY", rid, "Piecewise-linear knots must start and end at the input domain bounds.")
        if r["operator"]["id"] == "identity":
            for field in ("neutral", "side", "coupling"):
                if (field in inputs[0]) != (field in out) or field in inputs[0] and inputs[0][field] != out[field]:
                    check(fail, f"E_{field.upper()}_COMPATIBILITY", rid,
                          f"Identity requires equal presence and value of {field} on {inputs[0]['id']} and {output}.")
        else:
            # Exact arithmetic on one basis needs no blanket assumption guard.
            # A changed basis or declared loss needs an authored derivation;
            # its entailment remains the domain reviewer's responsibility.
            mixed_basis = any(s["calibration"] != out["calibration"] or s["units"] != out["units"] for s in inputs)
            declared_loss = any(loss["effect"] in _LOSS_EFFECTS for loss in r["loss_annotations"])
            if not r["assumptions"] and (mixed_basis or r.get("mapping_quality") == "approximate" or declared_loss):
                check(fail, "E_DERIVATION_ASSUMPTIONS", rid,
                      f"Nonidentity rule {rid} requires explicit derivation assumptions for differing calibration/units or declared approximation/loss.")
    dependencies = {r["id"]: {writers[s] for s in r["inputs"] if s in writers} for r in rules}
    ordered = _dependency_waves(rules, dependencies)
    if len(ordered) < len(rules):
        check(fail, "E_MAPPING_CYCLE", mapping_id, "Mapping dependency graph contains a cycle.")
    consumed = {s for r in rules for s in r["inputs"]}
    required = tuple(dict.fromkeys(s for r in rules for s in r["inputs"] if s not in writers))
    outputs = tuple(dict.fromkeys(r["outputs"][0] for r in rules if r["outputs"][0] in (target_snapshot.channels or {})))
    for sid in required:
        check(channel, sid, source_snapshot)
    for sid in writers:
        if sid in (source_snapshot.channels or {}):
            check(fail, "E_MULTIPLE_WRITERS", sid, "Rule output is also a source channel driver.")
        # Intermediate values can remain virtual; terminal outputs must be target-bound.
        if sid in (target_snapshot.channels or {}) or sid not in consumed:
            check(channel, sid, target_snapshot)
    if not outputs:
        check(fail, "E_MAPPING_OUTPUT", mapping_id, "Mapping has no target-bound outputs.")
    report = Report(tuple(diagnostics), tuple(losses))
    if not report.ok:
        return Result(None, report)
    compiled = CompiledMapping(pack, source_snapshot, target_snapshot, mapping_id, tuple(ordered), required, outputs, tuple(losses))
    if _native.core is not None:
        compiled = _with_program(compiled, signals)
    return Result(_admit(compiled), report)


def _program_document(compiled):
    # Not canonical_json: views rebuilt from these bytes must keep key order and
    # the sign of zero, which canonical_json drops.
    views = {"instructions": compiled.instructions, "required_inputs": compiled.required_inputs,
             "output_ids": compiled.output_ids}
    return json.dumps(_plain(views), ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8", "surrogatepass")


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


class _Inexact(Exception):
    """A domain bound binary64 cannot hold exactly; the mapping stays on the reference path."""


def _domain(bounds):
    low, high = float(bounds.get("min", 0.0)), float(bounds.get("max", 0.0))
    if low != bounds.get("min", 0.0) or high != bounds.get("max", 0.0):
        raise _Inexact
    return ("min" in bounds, low, "max" in bounds, high)


def _with_program(compiled, signals):
    """Rebuild the record's views from a core program compiled from their canonical bytes."""
    document = _program_document(compiled)
    views = json.loads(document)
    sources = [sid for sid in compiled.source_snapshot.channels or {} if sid in signals]
    slots = {sid: i for i, sid in enumerate(sources)}
    instructions = []
    try:
        source_domains = [(sid, _domain(signals[sid]["domain"])) for sid in sources]
        for rule in views["instructions"]:
            op, output = rule["operator"], rule["outputs"][0]
            out = slots.setdefault(output, len(slots))
            knots = op.get("knots", ())
            instructions.append((op["id"], [slots[s] for s in rule["inputs"]], out, _domain(signals[output]["domain"]),
                                 float(op.get("scale", 0.0)), float(op.get("offset", 0.0)),
                                 [float(w) for w in op.get("weights", ())],
                                 [float(k[0]) for k in knots], [float(k[1]) for k in knots]))
    except _Inexact:
        return compiled
    handle = _native.core.compile({
        "document": document, "sources": source_domains, "slots": len(slots), "instructions": instructions,
        "required": [slots[s] for s in views["required_inputs"]],
        "outputs": [(sid, slots[sid]) for sid in views["output_ids"]]})
    views = freeze(json.loads(handle.document()))
    rebuilt = CompiledMapping(compiled.pack, compiled.source_snapshot, compiled.target_snapshot, compiled.mapping_id,
                              views["instructions"], views["required_inputs"], views["output_ids"], compiled.losses)
    object.__setattr__(rebuilt, "_core", handle)
    return rebuilt


def _piecewise_linear(knots, x, ref):
    """Interpolate within the knot segment holding x; compilation put x inside the knots."""
    xs = [float(k[0]) for k in knots]
    i = bisect.bisect_right(xs, x) - 1
    if xs[i] == x:
        return float(knots[i][1])
    (xa, ya), (xb, yb) = ((float(a), float(b)) for a, b in knots[i:i + 2])
    t = _divide(_sub(x, xa, ref), _sub(xb, xa, ref), ref)
    value = _add(ya, _product(t, _sub(yb, ya, ref), ref), ref)
    # Rounding could step past the segment's far end; keeping the value inside
    # [ya, yb] keeps the operator monotone across knots.
    return min(max(value, min(ya, yb)), max(ya, yb))


@dataclass(frozen=True)
class EvaluatedValues(OwnedRecord):
    _handle_views = ("samples",)
    samples: tuple
    _core: object = field(default=None, init=False, repr=False, compare=False)

    def _check_consistency(self):
        if self._core is not None and not self._core.check_view(self.samples):
            fail("E_RECORD_INTEGRITY", "/samples", "Sample views disagree with their core frames.")

    def to_dict(self):
        self._check_integrity()
        return {"samples": thaw(self.samples)}


@public
def evaluate_mapping(compiled_mapping, samples):
    if not isinstance(compiled_mapping, CompiledMapping) or not isinstance(samples, (tuple, list)):
        fail("E_SAMPLE_TYPE", "/", "Expected CompiledMapping and sample frame array.")
    compiled_mapping._check_integrity()
    if compiled_mapping._core is not None:
        # None means some sample needs the reference path, which owns every diagnostic.
        handle = compiled_mapping._core.evaluate(samples)
        if handle is not None:
            record = EvaluatedValues(handle.view())
            object.__setattr__(record, "_core", handle)
            return Result(_admit(record), Report((), compiled_mapping.losses))
    diagnostics, frames = [], []
    # The compiled mapping's check above already verified its pack; Pack.signals would verify it again.
    signals = {s["id"]: s for s in compiled_mapping.pack.document["signals"]}
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
                    math_ref = ref + "/rules/" + rule["id"]
                    if op["id"] == "identity":
                        value = args[0]
                    elif op["id"] == "affine":
                        value = _add(_product(float(op["scale"]), args[0], math_ref), float(op["offset"]), math_ref)
                    elif op["id"] == "weighted_sum":
                        value = _sum((_product(float(w), x, math_ref) for w, x in zip(op["weights"], args)), math_ref)
                    else:
                        value = _piecewise_linear(op["knots"], args[0], math_ref)
                    in_domain(value, signals[output]["domain"], ref + "/rules/" + rule["id"])
                    values[output] = float(value)
                except Fault as exc:
                    diagnostics.append(exc.diagnostic)
            written = {sid: values[sid] for sid in compiled_mapping.output_ids if sid in values}
            frames.append(freeze({"timestamp": float(frame["timestamp"]), "values": written, "validity": {sid: True for sid in written}}))
        except Fault as exc:
            diagnostics.append(exc.diagnostic)
    report = Report(tuple(diagnostics), compiled_mapping.losses)
    return Result(_admit(EvaluatedValues(tuple(frames))) if report.ok else None, report)
