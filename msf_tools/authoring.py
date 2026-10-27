# SPDX-License-Identifier: MIT
"""Strict authoring validation. Authoring is data, never executable code."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat
import tomllib

from .common import thaw, json_value, number, SPECIAL_FILE_ERRNOS
from .report import public, Diagnostic, Report, Result, Fault, fail
from .records import OwnedRecord, _admit

ARRAYS = ("signals", "profiles", "mappings", "evidence")
TOP = {"schema_version", "data_version", "operator_version", "id", "license", *ARRAYS}
SIGNAL_REQUIRED = {"id", "label", "value_type", "units", "domain", "calibration",
                   "disposition", "evidence", "evidence_status"}
SIGNAL_OPTIONAL = {"region", "side", "neutral", "native_default", "coupling", "native_id",
                   "surface", "validity", "confidence", "time", "metadata"}
RULE_REQUIRED = {"id", "inputs", "outputs", "operator", "disposition", "assumptions",
                 "evidence", "evidence_status", "loss_annotations"}
DISPOSITIONS = {"mapped", "unsupported", "unresolved", "excluded"}
STATUSES = {"verified_current", "proposed", "unresolved"}
_TOKEN = object()
# Explicit blank set shared by the authoring/pack 1.0 schema character class.
# Includes the existing control whitespace policy and the U+FEFF format mark.
_BLANK_CHARACTERS = ("\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020"
                     "\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
                     "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")

@dataclass(frozen=True)
class ValidatedAuthoring(OwnedRecord):
    document: Mapping
    _token: object

    def to_dict(self):
        self._check_integrity()
        return thaw(self.document)


def keys(obj, required, optional, ref):
    if not isinstance(obj, Mapping):
        fail("E_TYPE", ref, "Expected an object.")
    if any(type(key) is not str for key in obj):
        fail("E_TYPE", ref, "Object keys must be strings.")
    missing = required - obj.keys()
    extra = obj.keys() - required - optional
    if missing:
        fail("E_REQUIRED", ref, "Missing keys: " + ", ".join(sorted(missing)))
    if extra:
        fail("E_UNKNOWN_KEY", ref, "Unknown keys: " + ", ".join(sorted(extra)))


def string(value, ref):
    if type(value) is not str or not value.strip(_BLANK_CHARACTERS):
        fail("E_TYPE", ref, "Expected a nonempty string.")


def strings(value, ref, unique=True, nonempty=False):
    if not isinstance(value, (list, tuple)):
        fail("E_TYPE", ref, "Expected an array of strings.")
    for i, x in enumerate(value):
        string(x, f"{ref}/{i}")
    if unique and len(set(value)) != len(value):
        fail("E_DUPLICATE", ref, "Duplicate array entries.")
    if nonempty and not value:
        fail("E_REQUIRED", ref, "At least one entry is required.")


def coupling(value, ref):
    if type(value) is str:
        string(value, ref)
    else:
        strings(value, ref)


def enum(value, choices, ref):
    if type(value) is not str or value not in choices:
        fail("E_ENUM", ref, "Expected one of " + ", ".join(sorted(choices)))


def domain(obj, ref):
    keys(obj, set(), {"min", "max"}, ref)
    for k, v in obj.items():
        if not number(v):
            fail("E_TYPE", f"{ref}/{k}", "Domain bounds must be finite numbers.")
    if "min" in obj and "max" in obj and obj["min"] > obj["max"]:
        fail("E_DOMAIN", ref, "Domain minimum exceeds maximum.")


def in_domain(value, bounds, ref):
    if not number(value):
        fail("E_TYPE", ref, "Expected a finite scalar, excluding boolean.")
    if ("min" in bounds and value < bounds["min"]) or ("max" in bounds and value > bounds["max"]):
        fail("E_DOMAIN", ref, "Value is outside its declared domain.", "Supply a valid sample; no clamping or neutral substitution is performed.")


def loss_annotation(obj, ref):
    keys(obj, {"category", "effect", "reason", "refs"}, {"units", "bound"}, ref)
    enum(obj["category"], {"signal", "geometry", "binding", "animation", "material", "metadata"}, ref)
    enum(obj["effect"], {"preserved", "approximated", "dropped", "unknown"}, ref)
    string(obj["reason"], ref)
    strings(obj["refs"], ref)
    if "units" in obj:
        string(obj["units"], ref)
    if "bound" in obj and (not number(obj["bound"]) or obj["bound"] < 0):
        fail("E_TYPE", ref, "Loss bound must be finite and nonnegative.")


def validate_signal(s, ref):
    keys(s, SIGNAL_REQUIRED, SIGNAL_OPTIONAL, ref)
    for k in ("id", "label", "units", "calibration"):
        string(s[k], f"{ref}/{k}")
    enum(s["value_type"], {"scalar"}, f"{ref}/value_type")
    enum(s["disposition"], DISPOSITIONS, ref)
    enum(s["evidence_status"], STATUSES, ref)
    strings(s["evidence"], f"{ref}/evidence")
    domain(s["domain"], f"{ref}/domain")
    for k in ("neutral", "native_default"):
        if k in s:
            in_domain(s[k], s["domain"], f"{ref}/{k}")
    for k in ("region", "side", "native_id", "surface", "time"):
        if k in s:
            string(s[k], f"{ref}/{k}")
    if "validity" in s and type(s["validity"]) not in (str, bool):
        fail("E_TYPE", f"{ref}/validity", "Expected a boolean or explicit validity description.")
    if type(s.get("validity")) is str:
        string(s["validity"], f"{ref}/validity")
    if "confidence" in s and not (type(s["confidence"]) is str or
            number(s["confidence"]) and 0 <= s["confidence"] <= 1):
        fail("E_TYPE", ref, "Confidence must be a description or number in [0,1].")
    if type(s.get("confidence")) is str:
        string(s["confidence"], f"{ref}/confidence")
    if "coupling" in s:
        coupling(s["coupling"], f"{ref}/coupling")
    if "metadata" in s and not isinstance(s["metadata"], Mapping):
        fail("E_TYPE", ref, "metadata must be an object.")


def validate_rule(r, ref):
    keys(r, RULE_REQUIRED, {"mapping_quality", "coupling"}, ref)
    string(r["id"], ref)
    strings(r["inputs"], f"{ref}/inputs", nonempty=True)
    strings(r["outputs"], f"{ref}/outputs", nonempty=True)
    strings(r["assumptions"], f"{ref}/assumptions")
    strings(r["evidence"], f"{ref}/evidence")
    enum(r["disposition"], DISPOSITIONS, ref)
    enum(r["evidence_status"], STATUSES, ref)
    if r["disposition"] == "mapped":
        if "mapping_quality" not in r:
            fail("E_REQUIRED", ref, "Mapped rules require mapping_quality.")
        enum(r["mapping_quality"], {"exact", "approximate"}, ref)
    elif "mapping_quality" in r:
        fail("E_DISPOSITION", ref, "mapping_quality is only valid on mapped rules.")
    if "coupling" in r:
        coupling(r["coupling"], f"{ref}/coupling")
    op = r["operator"]
    keys(op, {"id"}, {"scale", "offset", "weights"}, f"{ref}/operator")
    enum(op["id"], {"identity", "affine", "weighted_sum"}, ref)
    if len(r["outputs"]) != 1 or op["id"] != "weighted_sum" and len(r["inputs"]) != 1:
        fail("E_ARITY", ref, "Unary operators need 1 input/output; weighted_sum needs N inputs and 1 output.")
    allowed = {"identity": {"id"}, "affine": {"id", "scale", "offset"},
               "weighted_sum": {"id", "weights"}}[op["id"]]
    if set(op) != allowed:
        fail("E_OPERATOR", ref, "Operator coefficients must be explicit and match its type.")
    if op["id"] == "affine":
        if not number(op["scale"]) or not number(op["offset"]):
            fail("E_TYPE", ref, "Affine coefficients must be finite scalars.")
    if op["id"] == "weighted_sum":
        w = op["weights"]
        if not isinstance(w, (tuple, list)) or len(w) != len(r["inputs"]) or not all(number(x) for x in w):
            fail("E_TYPE", ref, "Weights must be finite, ordered and match inputs.")
    if not isinstance(r["loss_annotations"], (list, tuple)):
        fail("E_TYPE", ref, "loss_annotations must be an array.")
    for i, loss in enumerate(r["loss_annotations"]):
        loss_annotation(loss, f"{ref}/loss_annotations/{i}")


@public
def validate_authoring(document):
    diagnostics = []
    def check(fn, *args):
        try:
            fn(*args)
            return True
        except Fault as exc:
            diagnostics.append(exc.diagnostic)
            return False
    if not check(keys, document, TOP, set(), "/"):
        return Result(None, Report(tuple(diagnostics)))
    check(json_value, document)
    for k in ("id", "license"):
        check(string, document[k], f"/{k}")
    check(enum, document["schema_version"], {"1.0"}, "/schema_version")
    check(enum, document["operator_version"], {"1.0"}, "/operator_version")
    if type(document["data_version"]) is not str or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", document["data_version"]):
        diagnostics.append(Diagnostic("E_VERSION", "error", "/data_version", "Expected a semantic data version.", "Use an independently versioned data release."))
    inventories = {}
    rules = {}
    for category in ARRAYS:
        rows = document[category]
        if not isinstance(rows, (list, tuple)):
            check(fail, "E_TYPE", f"/{category}", "Expected an array.")
            inventories[category] = {}
            continue
        ids = {}
        inventories[category] = ids
        for i, row in enumerate(rows):
            ref = f"/{category}/{i}"
            if not isinstance(row, Mapping):
                check(fail, "E_TYPE", ref, "Expected an object.")
                continue
            if type(row.get("id")) is str:
                if row["id"] in ids:
                    check(fail, "E_DUPLICATE_ID", ref, f"Duplicate {category} ID {row['id']}.")
                else:
                    ids[row["id"]] = row
            if category == "signals":
                check(validate_signal, row, ref)
            elif category == "profiles":
                if check(keys, row, {"id", "label", "signal_ids"}, {"evidence", "metadata"}, ref):
                    check(string, row["id"], ref)
                    check(string, row["label"], ref)
                    check(strings, row["signal_ids"], ref)
                    if "evidence" in row:
                        check(strings, row["evidence"], ref)
                    if "metadata" in row and not isinstance(row["metadata"], Mapping):
                        check(fail, "E_TYPE", ref, "metadata must be an object.")
            elif category == "evidence":
                if check(keys, row, {"id", "claim", "status"}, {"url", "revision", "retrieved", "sha256", "locator", "license", "authorship"}, ref):
                    for k, v in row.items():
                        check(string, v, f"{ref}/{k}")
                    check(enum, row["status"], STATUSES, ref)
                    if "url" in row:
                        if type(row["url"]) is not str or not row["url"].startswith("https://"):
                            check(fail, "E_EVIDENCE", ref, "Public evidence URL must use HTTPS.")
                        if not ({"revision", "retrieved", "sha256"} & row.keys()) or "locator" not in row:
                            check(fail, "E_EVIDENCE", ref, "Public evidence needs revision/retrieved/digest and locator.")
                    elif not {"license", "authorship"} <= row.keys():
                        check(fail, "E_EVIDENCE", ref, "Original evidence needs license and authorship.")
                    if "sha256" in row and (type(row["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}", row["sha256"])):
                        check(fail, "E_EVIDENCE", ref, "Invalid SHA256 digest.")
            else:
                if check(keys, row, {"id", "rules"}, set(), ref):
                    check(string, row["id"], ref)
                    if not isinstance(row["rules"], (list, tuple)):
                        check(fail, "E_TYPE", ref, "rules must be an array.")
                        continue
                    for j, r in enumerate(row["rules"]):
                        rr = f"{ref}/rules/{j}"
                        check(validate_rule, r, rr)
                        if isinstance(r, Mapping) and type(r.get("id")) is str:
                            if r["id"] in rules:
                                check(fail, "E_DUPLICATE_ID", rr, "Rule IDs must be unique across mappings.")
                            rules[r["id"]] = r
    for category, rows in inventories.items():
        for sid, row in rows.items():
            ref = f"/{category}/{sid}"
            refs = row.get("evidence", ())
            if isinstance(refs, (list, tuple)):
                for eid in refs:
                    if type(eid) is str and eid not in inventories["evidence"]:
                        check(fail, "E_REFERENCE", ref, f"Unknown evidence {eid}.")
            if category == "profiles" and isinstance(row.get("signal_ids"), (list, tuple)):
                for signal in row["signal_ids"]:
                    if type(signal) is str and signal not in inventories["signals"]:
                        check(fail, "E_REFERENCE", ref, f"Unknown signal {signal}.")
    for rid, r in rules.items():
        for field, inventory in (("inputs", inventories["signals"]), ("outputs", inventories["signals"]), ("evidence", inventories["evidence"])):
            if isinstance(r.get(field), (list, tuple)):
                for item in r[field]:
                    if type(item) is str and item not in inventory:
                        check(fail, "E_REFERENCE", f"/rules/{rid}/{field}", f"Unknown reference {item}.")
    report = Report(tuple(diagnostics))
    return Result(_admit(ValidatedAuthoring(document, _TOKEN)) if report.ok else None, report)


@public
def load_authoring(path):
    path = Path(path)
    if path.is_file():
        return validate_authoring(tomllib.loads(path.read_text(encoding="utf-8")))
    if not path.is_dir() or not (path / "pack.toml").is_file():
        fail("E_AUTHORING_PATH", "/", "Expected TOML file or directory containing pack.toml.")
    merged = {k: [] for k in ARRAYS}
    seen_meta = set()
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
        doc = tomllib.loads(_read_fragment(p, relative))
        for k, v in doc.items():
            if k in ARRAYS:
                if not isinstance(v, list):
                    fail("E_TYPE", str(relative), f"{k} must be an array.")
                merged[k].extend(v)
            else:
                if k in seen_meta:
                    fail("E_DUPLICATE_KEY", str(relative), f"Duplicate metadata key {k}.")
                seen_meta.add(k)
                merged[k] = v
    return validate_authoring(merged)


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
