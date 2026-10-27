# SPDX-License-Identifier: MIT
"""Immutable glTF/GLB inventory and explicit, bounded local resource decoding."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import importlib
import importlib.util
import math
import os
import re
import stat
from types import MappingProxyType
from urllib.parse import unquote, urlsplit

from . import _native
from .checks import keys, string, domain
from .common import freeze, thaw, digest, canonical_json, integer, SPECIAL_FILE_ERRNOS
from .report import public, fail, Report, Result, Diagnostic
from .records import OwnedRecord, _admit
from .sources import paths as source_paths
from .sources import (SOURCE_FORMATS, ReaderMismatch, SourceLimits, SourceParseError,
                      GENERATED_MAX_ACCESSOR_COMPONENTS, GENERATED_MAX_TOTAL_ACCESSOR_COMPONENTS)

_core = _native.built

SUPPORTED_REQUIRED_EXTENSIONS = frozenset()  # Inventory is broader than evaluation.
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_ACCESSOR_COMPONENTS = 1_000_000
MAX_TOTAL_ACCESSOR_COMPONENTS = 4_000_000


@dataclass(frozen=True)
class Resource:
    id: str
    uri: str | None
    byte_length: int
    sha256: str | None
    data: bytes | None

    def to_dict(self):
        return {"id": self.id, "uri": self.uri, "byte_length": self.byte_length,
                "sha256": self.sha256, "consumed": self.data is not None}


@dataclass(frozen=True)
class Chunk:
    type: int
    data: bytes


# Views of the Snapshot handle (msf_tools._core) that every inspected or
# profile snapshot owns; the handle binds them, and each resource's and chunk's
# fields, by identity.
_VIEW_FIELDS = ("original_bytes", "document", "resources", "chunks", "channels", "bindings", "source")


@dataclass(frozen=True)
class AssetSnapshot(OwnedRecord):
    _handle_views = _VIEW_FIELDS
    format: str
    original_bytes: bytes
    sha256: str
    document: Mapping
    resources: tuple[Resource, ...] = ()
    chunks: tuple[Chunk, ...] = ()
    channels: Mapping = None
    bindings: tuple = ()
    # Set only for snapshots generated from a source format; the GLB above is then
    # derived data and `source["sha256"]` is the identity that gets persisted.
    source: Mapping = None
    _core: object = field(default=None, init=False, repr=False, compare=False)

    @property
    def resource_hashes(self):
        self._check_integrity()
        return self._resource_hashes()

    def _resource_hashes(self):
        if self.source is not None:
            return {d["uri"]: d["sha256"] for d in self.source["dependencies"]}
        return {r.id: r.sha256 for r in self.resources if r.sha256 is not None}

    def _component_caps(self):
        if self.source is not None:
            return GENERATED_MAX_ACCESSOR_COMPONENTS, GENERATED_MAX_TOTAL_ACCESSOR_COMPONENTS
        return MAX_ACCESSOR_COMPONENTS, MAX_TOTAL_ACCESSOR_COMPONENTS

    def to_dict(self):
        self._check_integrity()
        result = {"schema_version": "1.0", "format": self.format, "asset_sha256": _identity(self),
                  "document": thaw(self.document), "resources": [r.to_dict() for r in self.resources],
                  "chunks": [{"type": c.type, "byte_length": len(c.data), "sha256": digest(c.data)} for c in self.chunks],
                  "channels": thaw(self.channels or {}), "bindings": thaw(self.bindings),
                  "capabilities": {"geometry": ["POSITION", "relative_morph", "linear_blend_skinning"],
                                   "animations": ["STEP", "LINEAR", "CUBICSPLINE"],
                                   "supported_required_extensions": sorted(SUPPORTED_REQUIRED_EXTENSIONS)}}
        if self.source is not None:
            result["generated_sha256"] = self.sha256
            result["source"] = thaw(self.source)
        return result

    def _check_consistency(self):
        core = self._core
        if (core is None or type(self.format) is not str or self.format != core.format or type(self.sha256) is not str
                or self.sha256 != core.sha256 or not core.check(_views(self)) or not core.check_items(_items(self))):
            fail("E_RECORD_INTEGRITY", "/", "Snapshot fields disagree with the asset they were inspected from.")


def _views(snapshot):
    return tuple(getattr(snapshot, name) for name in _VIEW_FIELDS)


def _items(snapshot):
    # Called once the view fields are known to be the handle's own tuples.
    out = []
    for r in snapshot.resources:
        out += (r.id, r.uri, r.byte_length, r.sha256, r.data)
    for c in snapshot.chunks:
        out += (c.type, c.data)
    return tuple(out)


def _record(handle, document, resources=(), chunks=(), channels=None, bindings=(), source=None):
    """An unadmitted snapshot whose views `handle` adopts."""
    record = AssetSnapshot(handle.format, handle.original, handle.sha256, document, resources, chunks, channels, bindings, source)
    object.__setattr__(record, "_core", handle)
    handle.adopt(_views(record), _items(record))
    return record


def _encodable(value):
    """The UnicodeEncodeError admission's fingerprint raised for a lone surrogate."""
    if type(value) is str:
        value.encode("utf-8")
    elif isinstance(value, Mapping):
        for k, v in value.items():
            _encodable(k)
            _encodable(v)
    elif type(value) is tuple:
        for v in value:
            _encodable(v)


def _admit_snapshot(snapshot, inspected_caps):
    """Admission as 0.3.0's fingerprint and consistency check ran it on a new snapshot."""
    handle = snapshot._core
    handle.check_encodable()
    for name in ("channels", "bindings", "source"):
        _encodable(getattr(snapshot, name))
    caps = snapshot._component_caps()
    if tuple(inspected_caps) != caps:
        handle.validate(*caps)
    if snapshot.source is not None:
        _check_source(snapshot.source, snapshot.document, snapshot.format, handle.morph_counts())
    return _admit(snapshot)


def _identity(snapshot):
    """The hash every sidecar, report and export records for this snapshot."""
    return snapshot.source["sha256"] if snapshot.source is not None else snapshot.sha256


def _source_summary(snapshot):
    """How a generated snapshot was produced, for exports that record its identity."""
    return {k: snapshot.source[k] for k in ("format", "adapter", "adapter_version", "reader", "options_sha256")}


# Each module exposes ADAPTER and imports its reader library at import time.
_ADAPTER_MODULES = {"usd": "msf_tools.sources.usd", "usda": "msf_tools.sources.usd", "usdc": "msf_tools.sources.usd",
                    "usdz": "msf_tools.sources.usd", "fbx": "msf_tools.sources.fbx"}
_GLTF_FORMATS = ("gltf", "glb", "gltf2", "json")
_FBX_BINARY_MAGIC = b"Kaydara FBX Binary  \x00"
# Losses whose strict refusal has a different name from the plain W_ to E_ swap.
_STRICT_CODES = {"W_INBETWEENS_DROPPED": "E_INBETWEEN_UNSUPPORTED", "W_SHEAR_BAKED": "E_SHEAR_UNSUPPORTED"}

_SOURCE_KEYS = {"format", "sha256", "byte_length", "adapter", "adapter_version", "reader", "options_sha256",
                "node_order", "node_paths", "target_keys", "dependencies", "losses"}
_DIAGNOSTIC_KEYS = {"code", "severity", "ref", "message", "remediation"}


def _check_source(source, doc, kind, morph_counts):
    def bad(message):
        fail("E_RECORD_INTEGRITY", "/source", message)

    def text(value):
        return type(value) is str and value != ""

    def sha(value):
        return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None

    def count(value):
        return type(value) is int and value >= 0

    if not isinstance(source, Mapping) or set(source) != _SOURCE_KEYS:
        bad("Source record keys are wrong.")
    if kind != "glb" or source["format"] not in SOURCE_FORMATS:
        bad("Source format is not a supported source format.")
    if not sha(source["sha256"]) or not sha(source["options_sha256"]) or not count(source["byte_length"]):
        bad("Source digests or byte length are malformed.")
    if not all(text(source[k]) for k in ("adapter", "adapter_version", "reader")):
        bad("Source adapter and reader must be named.")
    if source["node_order"] != "path-sorted-v2":
        bad("Unknown source node order.")
    if doc["asset"].get("generator") != f'{source["adapter"]} {source["adapter_version"]}':
        bad("Generated asset was not written by the recorded adapter.")
    paths, keys_by_mesh = source["node_paths"], source["target_keys"]
    if (not isinstance(paths, tuple) or len(paths) != len(doc.get("nodes", ())) or len(set(paths)) != len(paths)
            or not all(type(p) is str for p in paths)):
        bad("Source node paths must name every generated node once.")
    try:
        order = [source_paths.sort_key(p) for p in paths]
        for mesh_keys in keys_by_mesh if isinstance(keys_by_mesh, tuple) else ():
            for key in mesh_keys if isinstance(mesh_keys, tuple) else ():
                source_paths.parse_target_key(key)
    except ValueError as exc:
        bad(f"Source path or target key is malformed: {exc}")
    if any(a >= b for a, b in zip(order, order[1:])):
        bad("Source node paths must be in path-sorted order.")
    meshes = doc.get("meshes", ())
    if not isinstance(keys_by_mesh, tuple) or len(keys_by_mesh) != len(meshes):
        bad("Source target keys must list every generated mesh.")
    for targets, mesh_keys in zip(morph_counts, keys_by_mesh):
        if (not isinstance(mesh_keys, tuple) or len(mesh_keys) != targets or len(set(mesh_keys)) != len(mesh_keys)
                or not all(type(k) is str for k in mesh_keys)):
            bad("Source target keys must name every morph target of their mesh once.")
    dependencies = source["dependencies"]
    if not isinstance(dependencies, tuple) or not all(
            isinstance(d, Mapping) and set(d) == {"uri", "sha256", "byte_length"} and text(d["uri"]) and sha(d["sha256"])
            and count(d["byte_length"]) for d in dependencies):
        bad("Source dependencies are malformed.")
    uris = [d["uri"] for d in dependencies]
    if uris != sorted(set(uris)):
        bad("Source dependencies must be unique and sorted by URI.")
    if not isinstance(source["losses"], tuple) or not all(
            isinstance(d, Mapping) and set(d) == _DIAGNOSTIC_KEYS and all(type(d[k]) is str for k in _DIAGNOSTIC_KEYS)
            and d["severity"] in ("warning", "info") for d in source["losses"]):
        bad("Source losses must be warning or info diagnostics.")


class LocalResolver:
    """No-follow file reads under an explicit root; cumulative budget per resolver.

    Every component is opened relative to a directory descriptor with O_NOFOLLOW.
    This prevents symlink substitution between validation and the actual read.
    O_NONBLOCK keeps the open of a FIFO from waiting for a writer, so the
    descriptor reaches the regular-file check and is refused there.
    """
    def __init__(self, root, max_resource_bytes=64 * 1024 * 1024, max_total_bytes=256 * 1024 * 1024):
        self.root = Path(root).absolute()
        if not integer(max_resource_bytes) or not integer(max_total_bytes) or min(max_resource_bytes, max_total_bytes) <= 0:
            raise ValueError("Resource limits must be positive integers.")
        if self.root.is_symlink() or not self.root.is_dir() or self.root.resolve() != self.root:
            raise ValueError("Resolver root must be a real directory without symlink ancestors.")
        self.max_resource_bytes = max_resource_bytes
        self.max_total_bytes = max_total_bytes
        self._consumed = 0

    def __call__(self, uri):
        if type(uri) is not str:
            fail("E_RESOURCE_URI", "/resources", "URI must be a string.")
        parsed = urlsplit(uri)
        decoded = unquote(parsed.path, errors="strict")
        path = PurePosixPath(decoded)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not decoded or path.is_absolute() or "\\" in decoded or "\x00" in decoded or any(x in ("", ".", "..") for x in decoded.split("/")):
            fail("E_RESOURCE_URI", "/resources", "Resolver accepts relative local paths without traversal.")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(self.root, flags | os.O_DIRECTORY)
        try:
            for part in path.parts[:-1]:
                next_fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            try:
                resource_fd = os.open(path.parts[-1], flags, dir_fd=fd)
            except OSError as exc:
                if exc.errno in SPECIAL_FILE_ERRNOS:
                    fail("E_RESOURCE_TYPE", "/resources", "Resource must be a regular file.")
                raise
            try:
                info = os.fstat(resource_fd)
                if not stat.S_ISREG(info.st_mode):
                    fail("E_RESOURCE_TYPE", "/resources", "Resource must be a regular file.")
                limit = min(self.max_resource_bytes, self.max_total_bytes - self._consumed)
                if info.st_size > limit:
                    fail("E_RESOURCE_LIMIT", "/resources", "Resource exceeds explicit resolver budget.")
                pieces = []
                size = 0
                while True:
                    piece = os.read(resource_fd, min(65536, limit - size + 1))
                    if not piece:
                        break
                    size += len(piece)
                    if size > limit:
                        fail("E_RESOURCE_LIMIT", "/resources", "Resource grew beyond resolver budget.")
                    pieces.append(piece)
                self._consumed += size
                return b"".join(pieces)
            finally:
                os.close(resource_fd)
        finally:
            os.close(fd)


def index(value, array, ref):
    if not integer(value) or not 0 <= value < len(array):
        fail("E_REFERENCE", ref, "Index is not an integer in the referenced array.")
    return array[value]


@public
def decode_accessor(snapshot, index):
    if not isinstance(snapshot, AssetSnapshot) or snapshot.format == "profile":
        fail("E_SNAPSHOT", "/", "Expected a glTF asset snapshot.")
    snapshot._check_integrity()
    return snapshot._core.decode(index, f"/accessors/{index}")


@public
def inspect_asset(bytes, /, format, resolver=None, sidecar=None, *, isolate=False, limits=None, options=None):
    if type(format) is str and format.lower() in SOURCE_FORMATS and type(bytes) is type(b""):
        return _inspect_source_format(bytes, format.lower(), resolver, sidecar, limits, options, isolate)
    if type(bytes) is not type(b"") or type(format) is not str or format.lower() not in _GLTF_FORMATS:
        if type(format) is str and format.lower() not in _GLTF_FORMATS + SOURCE_FORMATS:
            fail("E_ASSET_TYPE", "/", "Expected a gltf/glb format or a source format: " + ", ".join(SOURCE_FORMATS) + ".")
        fail("E_ASSET_TYPE", "/", "Expected immutable bytes and gltf/glb format.")
    if limits is not None or options is not None or isolate is not False:
        fail("E_SOURCE_OPTIONS", "/", "isolate, limits and options apply only to source formats.")
    return _inspect_gltf(bytes, format, resolver, sidecar)


def _source_magic(data, fmt):
    """Return the concrete format the bytes show, or None when they disagree with `fmt`."""
    found = ("usda" if data.startswith(b"#usda") else "usdc" if data.startswith(b"PXR-USDC")
             else "usdz" if data.startswith(b"PK\x03\x04") else None)
    if fmt == "usd":
        return found if found in ("usda", "usdc") else None
    if fmt == "fbx":
        head = data[:4096]
        text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
        # ASCII FBX has no magic; accept text that starts like a comment or a node name.
        if data.startswith(_FBX_BINARY_MAGIC) or b"\x00" not in head and (text[:1].isalpha() or text[:1] == b";"):
            return "fbx"
        return None
    return fmt if found == fmt else None


def _source_options(options, fmt):
    if options is None:
        options = {}
    def bad(message):
        fail("E_SOURCE_OPTIONS", "/options", message)
    if not isinstance(options, Mapping):
        bad("Options must be a mapping.")
    unknown = set(options) - {"influences", "losses", "animation", "sample_rate"}
    if unknown:
        bad("Unknown options: " + ", ".join(sorted(map(str, unknown))))
    normalized = {"influences": options.get("influences", "faithful"), "losses": options.get("losses", "declare")}
    if normalized["influences"] not in ("faithful", "top4") or type(normalized["influences"]) is not str:
        bad("influences must be 'faithful' or 'top4'.")
    if normalized["losses"] not in ("declare", "strict") or type(normalized["losses"]) is not str:
        bad("losses must be 'declare' or 'strict'.")
    if "animation" in options:
        animation = options["animation"]
        if not (type(animation) is str and animation or type(animation) is int and animation >= 0):
            bad("animation must be a stack name or a nonnegative index.")
        normalized["animation"] = animation
    if "sample_rate" in options:
        rate = options["sample_rate"]
        if fmt != "fbx" or type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
            bad("sample_rate is a positive frame rate for FBX sources only.")
        normalized["sample_rate"] = float(rate)
    return normalized


def _missing_adapter(fmt):
    extra = "FBX" if fmt == "fbx" else "USD"
    fail("E_FORMAT_DEPENDENCY", "/", f"{extra} support is not installed in this build of msf-tools.",
         f"Use an msf-tools release that includes {extra} support.")


def _load_adapter(fmt):
    extra = "fbx" if fmt == "fbx" else "usd"
    module = _ADAPTER_MODULES[fmt]
    try:
        return importlib.import_module(module).ADAPTER
    except ImportError as exc:
        if exc.name == module:
            _missing_adapter(fmt)
        if isinstance(exc, ReaderMismatch):
            fail("E_FORMAT_DEPENDENCY", "/", str(exc), exc.remediation)
        fail("E_FORMAT_DEPENDENCY", "/", f"Reading {fmt} sources needs the optional {extra} reader, which is not installed.",
             f"pip install 'msf-tools[{extra}]'")


def _isolated_adapter(fmt, resolver):
    if resolver is not None and not isinstance(resolver, LocalResolver):
        fail("E_ISOLATE_RESOLVER", "/", "An isolated reader can only use a LocalResolver or no resolver.",
             "Pass a LocalResolver, or set isolate=False.")
    module = _ADAPTER_MODULES[fmt]
    # Look the module up without importing it, so the reader library is only ever loaded by the worker.
    try:
        found = importlib.util.find_spec(module) is not None
    except ImportError:
        found = False
    if not found:
        _missing_adapter(fmt)
    from .sources._worker import IsolatedAdapter
    return IsolatedAdapter(module)


def _inspect_source_format(data, fmt, resolver, sidecar, limits, options, isolate=False):
    concrete = _source_magic(data, fmt)
    if concrete is None:
        fail("E_FORMAT_MISMATCH", "/", f"Bytes do not start like a {fmt} file.")
    if limits is None:
        limits = SourceLimits()
    elif not isinstance(limits, SourceLimits):
        fail("E_SOURCE_OPTIONS", "/limits", "limits must be a SourceLimits.")
    options = _source_options(options, concrete)
    if len(data) > limits.max_source_bytes:
        fail("E_RESOURCE_LIMIT", "/", f"Source exceeds the {limits.max_source_bytes}-byte limit.")
    if resolver is not None and not callable(resolver):
        fail("E_RESOLVER", "/", "Resolver must be an explicitly supplied callable.")
    if type(isolate) is not bool:
        fail("E_SOURCE_OPTIONS", "/isolate", "isolate must be True or False.")
    adapter = _isolated_adapter(fmt, resolver) if isolate else _load_adapter(fmt)
    return _inspect_source(adapter, data, concrete, resolver, sidecar, options, limits)


def _inspect_gltf(bytes, format, resolver, sidecar, *, max_asset_bytes=MAX_ASSET_BYTES,
                  component_caps=(MAX_ACCESSOR_COMPONENTS, MAX_TOTAL_ACCESSOR_COMPONENTS), source=None):
    if len(bytes) > max_asset_bytes:
        fail("E_RESOURCE_LIMIT", "/", "Asset exceeds the 64 MiB input byte budget." if max_asset_bytes == MAX_ASSET_BYTES
             else f"Asset exceeds the {max_asset_bytes}-byte input budget.")
    if resolver is not None and not callable(resolver):
        fail("E_RESOLVER", "/", "Resolver must be an explicitly supplied callable.")
    diagnostics, handle = _core.inspect_gltf(bytes, format.lower() == "glb", resolver, *component_caps, source is not None)
    document = handle.document()
    resources = tuple(Resource(*r) for r in handle.resources())
    chunks = tuple(Chunk(*c) for c in handle.chunks())
    snapshot = _record(handle, document, resources, chunks, MappingProxyType({}), (), source)
    reindexed = []
    if sidecar is not None:
        sc, reindexed = _validate_sidecar(snapshot, sidecar)
        channels = {b["id"]: {k: b[k] for k in ("id", "value_type", "units", "domain", "calibration")} for b in sc["bindings"]}
        snapshot = _record(handle.fork(), document, resources, chunks, freeze(channels), freeze(sc["bindings"]), source)
    report = Report(tuple(Diagnostic(*d) for d in diagnostics) + tuple(reindexed))
    return Result(_admit_snapshot(snapshot, component_caps) if report.ok else None, report)


@public
def _inspect_source(adapter, data, fmt, resolver=None, sidecar=None, options=None, limits=None):
    """Convert a source with `adapter`, then admit the GLB through the glTF path."""
    options = _source_options(options, fmt)
    limits = SourceLimits() if limits is None else limits
    try:
        generated = adapter.convert(data, fmt, resolver, limits, options)
    except SourceParseError as exc:
        fail("E_SOURCE_PARSE", "/", str(exc)[:512] or "The source reader rejected the file.",
             "Check that the source file is valid for its declared format.")
    source = {"format": fmt, "sha256": digest(data), "byte_length": len(data),
              "adapter": adapter.name, "adapter_version": adapter.version, "reader": adapter.reader(),
              "options_sha256": digest(canonical_json(options)), "node_order": "path-sorted-v2",
              "node_paths": list(generated.node_paths), "target_keys": [list(k) for k in generated.target_keys],
              "dependencies": [{"uri": uri, "sha256": sha, "byte_length": length} for uri, sha, length in generated.dependencies],
              "losses": [d.to_dict() for d in generated.losses]}
    if (len(generated.dependencies) > limits.max_dependencies
            or sum(length for _, _, length in generated.dependencies) > limits.max_dependency_bytes):
        fail("E_RESOURCE_LIMIT", "/source/dependencies", "Source dependencies exceed the dependency count or byte limit.")
    result = _inspect_gltf(generated.glb, "glb", None, sidecar, max_asset_bytes=limits.max_generated_bytes,
                           component_caps=(limits.max_accessor_components, limits.max_total_accessor_components),
                           source=freeze(source))
    losses = generated.losses
    if options["losses"] == "strict":
        losses = tuple(Diagnostic(_STRICT_CODES.get(d.code, "E_" + d.code.removeprefix("W_")), "error", d.ref, d.message,
                                  "Allow declared losses, or change the source so the loss does not occur.")
                       if d.severity == "warning" else d for d in losses)
    report = Report(result.report.diagnostics + tuple(losses), result.report.losses)
    return Result(result.value, report)


@dataclass(frozen=True)
class Sidecar(OwnedRecord):
    document: Mapping

    def to_dict(self):
        self._check_integrity()
        return thaw(self.document)

    def to_bytes(self):
        self._check_integrity()
        return canonical_json(self.document)


def _binding(snapshot, b):
    keys(b, {"id", "value_type", "units", "domain", "calibration", "ref"}, set(), "/bindings")
    for field in ("id", "units", "calibration"):
        string(b[field], f"/bindings/{field}")
    if b["value_type"] != "scalar":
        fail("E_BINDING_TYPE", "/bindings", "Only scalar morph bindings are supported.")
    domain(b["domain"], "/bindings/domain")
    ref = b["ref"]
    if snapshot.source is not None:
        return _source_binding(snapshot, b)
    keys(ref, {"asset_sha256", "locator", "node", "mesh", "target"}, {"resource_sha256"}, "/bindings/ref")
    if ref["asset_sha256"] != _identity(snapshot):
        fail("E_STALE_SOURCE", "/bindings/ref", "Binding asset hash is stale.")
    node = index(ref["node"], snapshot.document.get("nodes", ()), "/bindings/ref/node")
    mesh = index(ref["mesh"], snapshot.document.get("meshes", ()), "/bindings/ref/mesh")
    if node.get("mesh") != ref["mesh"] or not integer(ref["target"]) or not 0 <= ref["target"] < snapshot._core.morph_counts()[ref["mesh"]]:
        fail("E_BINDING_REFERENCE", "/bindings/ref", "Binding does not address a mesh-instance morph target.")
    if ref["locator"] != f"/nodes/{ref['node']}/weights/{ref['target']}":
        fail("E_BINDING_REFERENCE", "/bindings/ref/locator", "Structural locator and indices disagree.")
    if "resource_sha256" in ref:
        # Bind every authored target resource; morphless primitives consume none.
        hashes = set()
        for p in mesh["primitives"]:
            for aid in (p["targets"][ref["target"]].values() if p.get("targets") else ()):
                a = snapshot.document["accessors"][aid]
                for vid in ([a["bufferView"]] if "bufferView" in a else []) + ([a["sparse"][field]["bufferView"] for field in ("indices", "values")] if "sparse" in a else []):
                    hashes.add(snapshot.resources[snapshot.document["bufferViews"][vid]["buffer"]].sha256)
        if type(ref["resource_sha256"]) is not str or ref["resource_sha256"] not in hashes or None in hashes:
            fail("E_STALE_SOURCE", "/bindings/ref/resource_sha256", "Consumed target resource digest is stale or unavailable.")
    return b


def _source_binding(snapshot, b):
    """Resolve a generated-snapshot binding by its source locator.

    The stored node, mesh, target and locator are hints: a different reader can
    add or drop nodes, which shifts glTF indices while the source is unchanged.
    """
    ref = b["ref"]
    if "resource_sha256" in ref:
        fail("E_BINDING_REFERENCE", "/bindings/ref/resource_sha256", "Generated snapshots bind by source locator, not buffer digests.")
    keys(ref, {"asset_sha256", "locator", "node", "mesh", "target", "source_locator"}, set(), "/bindings/ref")
    if ref["asset_sha256"] != _identity(snapshot):
        fail("E_STALE_SOURCE", "/bindings/ref", "Binding asset hash is stale.")
    if not all(integer(ref[k]) and ref[k] >= 0 for k in ("node", "mesh", "target")) or type(ref["locator"]) is not str:
        fail("E_BINDING_REFERENCE", "/bindings/ref", "Stored node, mesh and target must be nonnegative integers.")
    try:
        path, key = source_paths.split_locator(ref["source_locator"])
    except ValueError:
        fail("E_BINDING_REFERENCE", "/bindings/ref/source_locator", "Source locator must be '<node path>#<target key>'.")
    node_paths = snapshot.source["node_paths"]
    node = node_paths.index(path) if path in node_paths else None
    mesh = snapshot.document["nodes"][node].get("mesh") if node is not None else None
    targets = snapshot.source["target_keys"][mesh] if mesh is not None else ()
    if key not in targets:
        fail("E_STALE_SOURCE", "/bindings/ref/source_locator", f"Source locator {ref['source_locator']} names no morph target in this source.")
    target = targets.index(key)
    resolved = dict(ref, node=node, mesh=mesh, target=target, locator=f"/nodes/{node}/weights/{target}")
    return b if resolved == dict(ref) else dict(b, ref=resolved)


def _validate_sidecar(snapshot, sidecar):
    if isinstance(sidecar, Sidecar):
        sidecar._check_integrity()
    sc = sidecar.document if isinstance(sidecar, Sidecar) else sidecar
    keys(sc, {"schema_version", "asset_sha256", "resource_hashes", "bindings"}, {"metadata"}, "/sidecar")
    if sc["schema_version"] != "1.0":
        fail("E_SIDECAR_VERSION", "/sidecar", "Unsupported sidecar version.")
    if sc["asset_sha256"] != _identity(snapshot) or sc["resource_hashes"] != snapshot._resource_hashes():
        fail("E_STALE_SOURCE", "/sidecar", "Sidecar asset or consumed resource hashes are stale.")
    if "metadata" in sc and not isinstance(sc["metadata"], Mapping):
        fail("E_TYPE", "/sidecar/metadata", "Metadata must be an object.")
    if not isinstance(sc["bindings"], (tuple, list)):
        fail("E_TYPE", "/sidecar/bindings", "Bindings must be an array.")
    ids = set()
    locators = set()
    bindings, reindexed = [], []
    for original in sc["bindings"]:
        b = _binding(snapshot, original)
        if b is not original:
            reindexed.append(Diagnostic("W_BINDING_REINDEXED", "warning", "/bindings/ref",
                                        f"Binding {b['id']} now resolves to {b['ref']['locator']} through its source locator.",
                                        "Re-annotate to store the current indices."))
        if b["id"] in ids or b["ref"]["locator"] in locators:
            fail("E_DUPLICATE_BINDING", "/sidecar/bindings", "Binding IDs and structural destinations must be unique.")
        ids.add(b["id"])
        locators.add(b["ref"]["locator"])
        bindings.append(b)
    if reindexed:
        sc = dict(sc, bindings=bindings)
    from .common import json_value
    json_value(sc)
    return sc, reindexed


@public
def annotate_asset(snapshot, annotations):
    if not isinstance(snapshot, AssetSnapshot) or snapshot.format == "profile":
        fail("E_SNAPSHOT", "/", "Annotation requires an inspected glTF asset.")
    snapshot._check_integrity()
    keys(annotations, {"bindings"}, {"metadata"}, "/annotations")
    sc = {"schema_version": "1.0", "asset_sha256": _identity(snapshot),
          "resource_hashes": snapshot.resource_hashes, **thaw(annotations)}
    sc, reindexed = _validate_sidecar(snapshot, sc)
    return Result(_admit(Sidecar(thaw(sc))), Report(tuple(reindexed)))


@public
def morph_binding(snapshot, signal, node, target):
    if not isinstance(snapshot, AssetSnapshot) or snapshot.format == "profile":
        fail("E_SNAPSHOT", "/", "Binding requires an inspected glTF asset.")
    snapshot._check_integrity()
    n = index(node, snapshot.document.get("nodes", ()), "/node")
    if "mesh" not in n:
        fail("E_BINDING_REFERENCE", "/node", "Node must have a mesh.")
    b = {k: thaw(signal[k]) for k in ("id", "value_type", "units", "domain", "calibration")}
    b["ref"] = {"asset_sha256": _identity(snapshot), "locator": f"/nodes/{node}/weights/{target}",
                "node": node, "mesh": n["mesh"], "target": target}
    if snapshot.source is not None:
        mesh_keys = snapshot.source["target_keys"][n["mesh"]]
        if not integer(target) or not 0 <= target < len(mesh_keys):
            fail("E_BINDING_REFERENCE", "/bindings/ref", "Binding does not address a mesh-instance morph target.")
        b["ref"]["source_locator"] = source_paths.locator(snapshot.source["node_paths"][node], mesh_keys[target])
    _binding(snapshot, b)
    hashes = set()
    for p in snapshot.document["meshes"][n["mesh"]]["primitives"]:
        for aid in (p["targets"][target].values() if p.get("targets") else ()):
            a = snapshot.document["accessors"][aid]
            vids = ([a["bufferView"]] if "bufferView" in a else []) + ([a["sparse"][f]["bufferView"] for f in ("indices", "values")] if "sparse" in a else [])
            hashes.update(snapshot.resources[snapshot.document["bufferViews"][v]["buffer"]].sha256 for v in vids)
    # A generated GLB's buffer digest depends on the reader version, so it is never recorded.
    if len(hashes) == 1 and None not in hashes and snapshot.source is None:
        b["ref"]["resource_sha256"] = next(iter(hashes))
    return freeze(b)
