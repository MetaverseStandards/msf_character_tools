# SPDX-License-Identifier: MIT
"""Validated deterministic pack, survey CSV, coverage and checksums."""
from collections.abc import Mapping
from dataclasses import dataclass
import csv
import io

from .authoring import ValidatedAuthoring, _TOKEN
from .common import canonical_json, digest, thaw
from .report import public, fail


@dataclass(frozen=True)
class Pack:
    document: Mapping
    sha256: str

    def to_dict(self):
        return thaw(self.document)

    def to_bytes(self):
        return canonical_json(self.document)

    @property
    def signals(self):
        return {s["id"]: s for s in self.document["signals"]}


@public
def compile_pack(validated_authoring):
    if not isinstance(validated_authoring, ValidatedAuthoring) or validated_authoring._token is not _TOKEN:
        fail("E_VALIDATED_REQUIRED", "/", "compile_pack requires validated_authoring.", "Call validate_authoring or load_authoring and check its Result first.")
    return Pack(validated_authoring.document, digest(canonical_json(validated_authoring.document)))


def survey_csv(pack):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    profiles = pack.document["profiles"]
    writer.writerow(["id", "label", "value_type", "units", "disposition", "evidence_status"] + [p["id"] for p in profiles])
    for s in pack.document["signals"]:
        writer.writerow([s[k] for k in ("id", "label", "value_type", "units", "disposition", "evidence_status")] +
                        ["1" if s["id"] in p["signal_ids"] else "" for p in profiles])
    return stream.getvalue().encode("utf-8")


def coverage(pack):
    signals = pack.document["signals"]
    rules = [r for mapping in pack.document["mappings"] for r in mapping["rules"]]
    dispositions = ("mapped", "unsupported", "unresolved", "excluded")
    qualities = ("exact", "approximate")
    def partitions(rows):
        return {d: [r["id"] for r in rows if r["disposition"] == d] for d in dispositions}
    def rule_quality(rows):
        return {q: [r["id"] for r in rows if r.get("mapping_quality") == q] for q in qualities}
    profiles = []
    for p in pack.document["profiles"]:
        selected = [s for s in signals if s["id"] in p["signal_ids"]]
        used = [r for r in rules if any(sid in p["signal_ids"] for sid in (*r["inputs"], *r["outputs"]))]
        profiles.append({"id": p["id"], "signal_ids": list(p["signal_ids"]), "count": len(selected),
                         "dispositions": partitions(selected), "disposition_counts": {d: len(v) for d, v in partitions(selected).items()},
                         "mapping_quality": rule_quality(used), "mapping_quality_counts": {q: len(v) for q, v in rule_quality(used).items()},
                         "metadata": thaw(p.get("metadata", {}))})
    evidence = []
    for e in pack.document["evidence"]:
        evidence.append({**thaw(e), "signal_ids": [s["id"] for s in signals if e["id"] in s["evidence"]],
                         "profile_ids": [p["id"] for p in pack.document["profiles"] if e["id"] in p.get("evidence", ())],
                         "rule_ids": [r["id"] for r in rules if e["id"] in r["evidence"]]})
    return {"schema_version": "1.0", "pack_sha256": pack.sha256,
            "totals": {"signals": len(signals), "profiles": len(profiles), "rules": len(rules), "evidence": len(evidence)},
            "dispositions": partitions(signals), "disposition_counts": {d: len(v) for d,v in partitions(signals).items()},
            "mapping_quality": rule_quality(rules), "mapping_quality_counts": {q: len(v) for q,v in rule_quality(rules).items()},
            "profiles": profiles, "rules": [thaw(r) for r in rules], "evidence": evidence,
            "signals": [{"id": s["id"], "disposition": s["disposition"],
                         "reason": thaw(s.get("metadata", {})).get("reason"),
                         "profiles": [p["id"] for p in pack.document["profiles"] if s["id"] in p["signal_ids"]],
                         "rules": [r["id"] for m in pack.document["mappings"] for r in m["rules"] if s["id"] in (*r["inputs"], *r["outputs"])]}
                        for s in pack.document["signals"]]}
