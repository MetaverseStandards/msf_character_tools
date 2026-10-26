# SPDX-License-Identifier: MIT
"""Immutable glTF/GLB inventory and explicit, bounded local resource decoding."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import base64
import binascii
import os
import re
import stat
import struct
from urllib.parse import unquote, urlsplit

from .authoring import keys, string, domain
from .common import freeze, thaw, digest, canonical_json, parse_json, integer, number, SPECIAL_FILE_ERRNOS
from .report import public, fail, Report, Result, Diagnostic, Fault
from .records import OwnedRecord, _admit
from .math3d import matrix, validate_trs, authored_quaternion
from .gltf_semantics import (parse_document, morph_count, validate_meshes,
                             validate_skin_hierarchy, animation_layout, validate_bounds, validate_binary)
from .sources import paths as source_paths
from .sources import (SOURCE_FORMATS, SourceParseError, GENERATED_MAX_BYTES,
                      GENERATED_MAX_ACCESSOR_COMPONENTS, GENERATED_MAX_TOTAL_ACCESSOR_COMPONENTS)

COMPONENTS = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
              5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
SHAPES = {"SCALAR": (1, 1), "VEC2": (1, 2), "VEC3": (1, 3), "VEC4": (1, 4),
          "MAT2": (2, 2), "MAT3": (3, 3), "MAT4": (4, 4)}
SUPPORTED_REQUIRED_EXTENSIONS = frozenset()  # Inventory is broader than evaluation.
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_RESOURCE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_RESOURCE_BYTES = 256 * 1024 * 1024
MAX_ACCESSOR_COMPONENTS = 1_000_000
MAX_TOTAL_ACCESSOR_COMPONENTS = 4_000_000
MAX_STRUCTURAL_OBJECTS = 100_000


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


@dataclass(frozen=True)
class AssetSnapshot(OwnedRecord):
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
                  "capabilities": {"geometry": ["POSITION", "relative_morph", "four_influence_LBS"],
                                   "animations": ["STEP", "LINEAR", "CUBICSPLINE"],
                                   "supported_required_extensions": sorted(SUPPORTED_REQUIRED_EXTENSIONS)}}
        if self.source is not None:
            result["generated_sha256"] = self.sha256
            result["source"] = thaw(self.source)
        return result


    def _check_consistency(self):
        if type(self.original_bytes) is not bytes or digest(self.original_bytes) != self.sha256:
            fail("E_RECORD_INTEGRITY", "/", "Snapshot original bytes and digest disagree.")
        if self.format == "profile":
            doc = parse_json(self.original_bytes)
            if doc != thaw(self.document) or doc.get("schema_version") != "1.0" or doc.get("channels") != thaw(self.channels):
                fail("E_RECORD_INTEGRITY", "/", "Profile raw document and channels disagree.")
            if self.resources or self.chunks or self.bindings or self.source is not None:
                fail("E_RECORD_INTEGRITY", "/", "Profile contains asset-only state.")
            return
        kind, doc, chunks, bin_chunk = _parse_asset(self.original_bytes, self.format)
        if kind != self.format or doc != thaw(self.document) or chunks != self.chunks:
            fail("E_RECORD_INTEGRITY", "/", "Snapshot source, parsed view or chunks disagree.")
        # Includes hierarchy cycles before any world traversal.
        _validate_document(doc, self._component_caps())
        if self.source is not None:
            _check_source(self.source, doc, kind)
        expected = [(f"/buffers/{i}", b.get("uri"), b["byteLength"]) for i, b in enumerate(doc.get("buffers", ()))]
        expected += [(f"/images/{i}", img["uri"], None) for i, img in enumerate(doc.get("images", ())) if "uri" in img]
        if len(expected) != len(self.resources):
            fail("E_RECORD_INTEGRITY", "/resources", "Resource inventory disagrees with source.")
        for (rid, uri, length), resource in zip(expected, self.resources):
            if type(resource) is not Resource or resource.id != rid or resource.uri != uri or length is not None and resource.byte_length != length:
                fail("E_RECORD_INTEGRITY", rid, "Resource declaration disagrees with source.")
            data = resource.data
            if data is None:
                if resource.sha256 is not None or uri is None or uri.startswith("data:"):
                    fail("E_RECORD_INTEGRITY", rid, "Required embedded resource is missing.")
            else:
                if type(data) is not bytes or digest(data) != resource.sha256 or len(data) < resource.byte_length:
                    fail("E_RECORD_INTEGRITY", rid, "Resource bytes and identity disagree.")
                if length is None and resource.byte_length != len(data):
                    fail("E_RECORD_INTEGRITY", rid, "Image length and bytes disagree.")
                embedded = bin_chunk[:length] if uri is None else _data_uri(uri, rid) if uri.startswith("data:") else None
                if embedded is not None and data != embedded:
                    fail("E_RECORD_INTEGRITY", rid, "Embedded resource disagrees with raw source.")
        channels = {b["id"]: {k: b[k] for k in ("id", "value_type", "units", "domain", "calibration")} for b in self.bindings}
        if channels != self.channels:
            fail("E_RECORD_INTEGRITY", "/channels", "Channels disagree with bindings.")
        if self.bindings:
            _validate_sidecar(self, {"schema_version": "1.0", "asset_sha256": _identity(self),
                                     "resource_hashes": self._resource_hashes(), "bindings": self.bindings})


def _identity(snapshot):
    """The hash every sidecar, report and export records for this snapshot."""
    return snapshot.source["sha256"] if snapshot.source is not None else snapshot.sha256


def _source_summary(snapshot):
    """How a generated snapshot was produced, for exports that record its identity."""
    return {k: snapshot.source[k] for k in ("format", "adapter", "adapter_version", "reader", "options_sha256")}


_SOURCE_KEYS = {"format", "sha256", "byte_length", "adapter", "adapter_version", "reader", "options_sha256",
                "node_order", "node_paths", "target_keys", "dependencies", "losses"}
_DIAGNOSTIC_KEYS = {"code", "severity", "ref", "message", "remediation"}


def _check_source(source, doc, kind):
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
    for mesh, mesh_keys in zip(meshes, keys_by_mesh):
        if (not isinstance(mesh_keys, tuple) or len(mesh_keys) != morph_count(mesh) or len(set(mesh_keys)) != len(mesh_keys)
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


def positive_int(value, ref, zero=False):
    if not integer(value) or value < (0 if zero else 1):
        fail("E_TYPE", ref, "Expected a nonnegative integer." if zero else "Expected a positive integer.")


def vector(value, count, ref):
    if not isinstance(value, (tuple, list)) or len(value) != count or not all(number(x) for x in value):
        fail("E_TYPE", ref, f"Expected {count} finite numeric components.")


def _layout(accessor):
    _, size = COMPONENTS[accessor["componentType"]]
    columns, rows = SHAPES[accessor["type"]]
    column_stride = rows * size
    if columns > 1:
        column_stride = (column_stride + 3) // 4 * 4
    offsets = tuple(c * column_stride + r * size for c in range(columns) for r in range(rows))
    return offsets, columns * column_stride, size


def _read_elements(snapshot, view_id, offset, count, accessor, ref, sparse=False, raw=False):
    views = snapshot.document.get("bufferViews", ())
    view = index(view_id, views, ref)
    resource = snapshot.resources[view["buffer"]]
    if resource.data is None:
        fail("E_RESOURCE_UNAVAILABLE", ref, "Accessor needs an unresolved external buffer.", "Supply an explicit bounded LocalResolver.")
    offsets, element_size, size = _layout(accessor)
    stride = view.get("byteStride", element_size)
    if sparse and "byteStride" in view:
        fail("E_SPARSE_STRIDE", ref, "Sparse views cannot declare byteStride.")
    if stride < element_size or stride % size:
        fail("E_ACCESSOR_STRIDE", ref, "Stride is smaller than an element or misaligned.")
    start = view.get("byteOffset", 0) + offset
    if offset % size or start % size or accessor["type"].startswith("MAT") and start % 4:
        fail("E_ACCESSOR_ALIGNMENT", ref, "Accessor start violates component/matrix alignment.")
    end = offset + (count - 1) * stride + element_size if count else offset
    if end > view["byteLength"]:
        fail("E_ACCESSOR_BOUNDS", ref, "Accessor exceeds its bufferView.")
    fmt = "<" + COMPONENTS[accessor["componentType"]][0]
    normalized = accessor.get("normalized", False) and not raw
    rows = []
    for i in range(count):
        row = []
        for component_offset in offsets:
            v = struct.unpack_from(fmt, resource.data, start + i * stride + component_offset)[0]
            if not number(v):
                fail("E_NONFINITE", ref, "Binary accessor contains NaN or infinity.")
            if normalized:
                ct = accessor["componentType"]
                v = max(v / (127 if ct == 5120 else 32767), -1.0) if ct in (5120, 5122) else v / (255 if ct == 5121 else 65535)
            row.append(v)
        rows.append(tuple(row))
    return rows


def _decode_accessor(snapshot, accessor_id, *, raw=False):
    ref = f"/accessors/{accessor_id}"
    a = index(accessor_id, snapshot.document.get("accessors", ()), ref)
    offsets, _, _ = _layout(a)
    if a["count"] * len(offsets) > snapshot._component_caps()[0]:
        fail("E_RESOURCE_LIMIT", ref, "Accessor exceeds the decoded component budget.")
    if "bufferView" in a:
        rows = _read_elements(snapshot, a["bufferView"], a.get("byteOffset", 0), a["count"], a, ref, raw=raw)
    else:
        rows = [tuple(0.0 if a["componentType"] == 5126 or a.get("normalized") else 0 for _ in offsets) for _ in range(a["count"])]
    if "sparse" in a:
        sp = a["sparse"]
        ix = sp["indices"]
        indices = _read_elements(snapshot, ix["bufferView"], ix.get("byteOffset", 0), sp["count"],
                                 {"componentType": ix["componentType"], "type": "SCALAR"}, ref + "/sparse/indices", True)
        vals = _read_elements(snapshot, sp["values"]["bufferView"], sp["values"].get("byteOffset", 0), sp["count"], a, ref + "/sparse/values", True, raw=raw)
        last = -1
        for (i,), row in zip(indices, vals):
            if i <= last or i >= a["count"]:
                fail("E_SPARSE_INDEX", ref, "Sparse indices must be strictly increasing and in range.")
            rows[i] = row
            last = i
    return tuple(rows)


@public
def decode_accessor(snapshot, index):
    if not isinstance(snapshot, AssetSnapshot) or snapshot.format == "profile":
        fail("E_SNAPSHOT", "/", "Expected a glTF asset snapshot.")
    snapshot._check_integrity()
    return _decode_accessor(snapshot, index)


def _validate_document(doc, component_caps=(MAX_ACCESSOR_COMPONENTS, MAX_TOTAL_ACCESSOR_COMPONENTS)):
    max_accessor, max_total = component_caps
    if not isinstance(doc, Mapping) or not isinstance(doc.get("asset"), Mapping) or doc["asset"].get("version") != "2.0":
        fail("E_GLTF_VERSION", "/asset", "Expected glTF asset.version 2.0.")
    if "minVersion" in doc["asset"] and doc["asset"]["minVersion"] != "2.0":
        fail("E_GLTF_VERSION", "/asset/minVersion", "Unsupported minimum glTF version.")
    for name in ("buffers", "bufferViews", "accessors", "nodes", "meshes", "skins", "animations", "scenes", "images", "textures", "samplers", "materials", "cameras"):
        if name in doc and (not isinstance(doc[name], list) or not all(isinstance(x, Mapping) for x in doc[name])):
            fail("E_TYPE", f"/{name}", "Expected an array of objects.")
        if len(doc.get(name, ())) > MAX_STRUCTURAL_OBJECTS:
            fail("E_RESOURCE_LIMIT", f"/{name}", "Structural inventory exceeds object budget.")
    for name in ("extensionsUsed", "extensionsRequired"):
        if name in doc and (not isinstance(doc[name], list) or not all(type(x) is str for x in doc[name]) or len(set(doc[name])) != len(doc[name])):
            fail("E_TYPE", f"/{name}", "Expected unique extension strings.")
    if not set(doc.get("extensionsRequired", ())) <= set(doc.get("extensionsUsed", ())):
        fail("E_EXTENSION", "/extensionsRequired", "Required extensions must also be listed as used.")
    buffers, views, accessors = (doc.get(k, ()) for k in ("buffers", "bufferViews", "accessors"))
    for i, b in enumerate(buffers):
        positive_int(b.get("byteLength"), f"/buffers/{i}/byteLength")
        if "uri" in b:
            string(b["uri"], f"/buffers/{i}/uri")
    for i, v in enumerate(views):
        ref = f"/bufferViews/{i}"
        b = index(v.get("buffer"), buffers, ref)
        positive_int(v.get("byteLength"), ref)
        positive_int(v.get("byteOffset", 0), ref, True)
        if v.get("byteOffset", 0) + v["byteLength"] > b["byteLength"]:
            fail("E_BUFFER_BOUNDS", ref, "bufferView exceeds declared buffer length.")
        if "byteStride" in v and (not integer(v["byteStride"]) or not 4 <= v["byteStride"] <= 252 or v["byteStride"] % 4):
            fail("E_ACCESSOR_STRIDE", ref, "byteStride must be a multiple of 4 between 4 and 252.")
        if "target" in v and v["target"] not in (34962, 34963):
            fail("E_TYPE", ref, "Unknown bufferView target.")
    validate_meshes(doc, index)
    decoded_components = 0
    for i, a in enumerate(accessors):
        ref = f"/accessors/{i}"
        if not integer(a.get("componentType")) or a["componentType"] not in COMPONENTS or type(a.get("type")) is not str or a["type"] not in SHAPES:
            fail("E_ACCESSOR_TYPE", ref, "Unsupported componentType or shape.")
        positive_int(a.get("count"), ref)
        positive_int(a.get("byteOffset", 0), ref, True)
        if type(a.get("normalized", False)) is not bool or a.get("normalized") and a["componentType"] in (5125, 5126):
            fail("E_ACCESSOR_TYPE", ref, "normalized only supports byte/short components.")
        offsets, element_size, size = _layout(a)
        decoded_components += a["count"] * len(offsets)
        if a["count"] * len(offsets) > max_accessor or decoded_components > max_total:
            fail("E_RESOURCE_LIMIT", ref, "Accessor exceeds per-accessor or total decoded component budget.")
        for field in ("min", "max"):
            if field in a:
                vector(a[field], len(offsets), ref + "/" + field)
        validate_bounds(a, None, ref)
        if "min" in a and "max" in a and any(lo > hi for lo, hi in zip(a["min"], a["max"])):
            fail("E_ACCESSOR_DOMAIN", ref, "Accessor min exceeds max.")
        if "bufferView" in a:
            v = index(a["bufferView"], views, ref)
            stride = v.get("byteStride", element_size)
            start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
            if a.get("byteOffset", 0) % size or start % size or a["type"].startswith("MAT") and start % 4:
                fail("E_ACCESSOR_ALIGNMENT", ref, "Misaligned accessor.")
            if stride < element_size or stride % size or a.get("byteOffset", 0) + (a["count"] - 1) * stride + element_size > v["byteLength"]:
                fail("E_ACCESSOR_BOUNDS", ref, "Accessor range or stride exceeds bufferView.")
        elif a.get("byteOffset", 0):
            fail("E_ACCESSOR_BOUNDS", ref, "Accessor without bufferView cannot have a byteOffset.")
        if "sparse" in a:
            sp = a["sparse"]
            keys(sp, {"count", "indices", "values"}, {"extensions", "extras"}, ref)
            positive_int(sp["count"], ref)
            if sp["count"] > a["count"]:
                fail("E_SPARSE_INDEX", ref, "Sparse count exceeds accessor count.")
            for field in ("indices", "values"):
                item = sp[field]
                keys(item, {"bufferView", *( ["componentType"] if field == "indices" else [])}, {"byteOffset", "extensions", "extras"}, ref)
                v = index(item["bufferView"], views, ref)
                positive_int(item.get("byteOffset", 0), ref, True)
                if "byteStride" in v or "target" in v:
                    fail("E_SPARSE_STRIDE", ref, "Sparse bufferView cannot declare stride or target.")
                if field == "indices" and (not integer(item["componentType"]) or item["componentType"] not in (5121, 5123, 5125)):
                    fail("E_SPARSE_TYPE", ref, "Sparse indices must be unsigned byte/short/int.")
                item_size = COMPONENTS[item["componentType"]][1] if field == "indices" else element_size
                align = item_size if field == "indices" else size
                start = v.get("byteOffset", 0) + item.get("byteOffset", 0)
                if start % align or item.get("byteOffset", 0) % align or field == "values" and a["type"].startswith("MAT") and start % 4 or item.get("byteOffset", 0) + sp["count"] * item_size > v["byteLength"]:
                    fail("E_ACCESSOR_BOUNDS", ref, "Sparse data misaligned or out of bounds.")
    nodes, meshes, skins = (doc.get(k, ()) for k in ("nodes", "meshes", "skins"))
    parents = {}
    skinned_meshes = set()
    for i, n in enumerate(nodes):
        ref = f"/nodes/{i}"
        if "matrix" in n:
            vector(n["matrix"], 16, ref)
            validate_trs(matrix(n["matrix"]), affine_tolerance=1e-12, ref=ref)
            if any(k in n for k in ("translation", "rotation", "scale")):
                fail("E_NODE_TRANSFORM", ref, "matrix and TRS are mutually exclusive.")
        for k, length in (("translation", 3), ("rotation", 4), ("scale", 3)):
            if k in n:
                vector(n[k], length, ref + "/" + k)
        if "rotation" in n:
            authored_quaternion(n["rotation"], ref)
        for k, arr in (("mesh", meshes), ("skin", skins), ("camera", doc.get("cameras", ()))):
            if k in n:
                index(n[k], arr, ref + "/" + k)
        if "skin" in n and "mesh" not in n:
            fail("E_SKIN", ref, "Skinned node must reference a mesh.")
        if "skin" in n:
            skinned_meshes.add(n["mesh"])
        children = n.get("children", [])
        if not isinstance(children, list) or not all(integer(x) for x in children) or len(set(children)) != len(children):
            fail("E_HIERARCHY", ref, "Children must be unique integer indices.")
        for child in children:
            index(child, nodes, ref + "/children")
            if child in parents:
                fail("E_HIERARCHY", ref, "Node has multiple parents.")
            parents[child] = i
    complete = set()
    for i in range(len(nodes)):
        visiting = set()
        child = i
        while child not in complete:
            if child in visiting:
                fail("E_HIERARCHY_CYCLE", f"/nodes/{i}", "Node hierarchy contains a cycle.")
            visiting.add(child)
            if child not in parents:
                break
            child = parents[child]
        complete.update(visiting)
    for i, mesh in enumerate(meshes):
        for j, p in enumerate(mesh["primitives"]):
            ref = f"/meshes/{i}/primitives/{j}"
            if i in skinned_meshes and not {"JOINTS_0", "WEIGHTS_0"} <= p["attributes"].keys():
                fail("E_SKIN", ref, "Skinned primitive needs JOINTS_0 and WEIGHTS_0.")
            if "indices" in p:
                a = index(p["indices"], accessors, ref)
                if a["type"] != "SCALAR" or a["componentType"] not in (5121,5123,5125) or a.get("normalized", False):
                    fail("E_INDEX_TYPE", ref, "Primitive indices must be unsigned unnormalized scalars.")
            if "material" in p:
                index(p["material"], doc.get("materials", ()), ref)
        if "weights" in mesh:
            vector(mesh["weights"], morph_count(mesh), f"/meshes/{i}/weights")
    for i, n in enumerate(nodes):
        if "weights" in n:
            if "mesh" not in n:
                fail("E_MORPH", f"/nodes/{i}", "Node weights need a mesh.")
            vector(n["weights"], morph_count(meshes[n["mesh"]]), f"/nodes/{i}/weights")
    for i, skin in enumerate(skins):
        ref = f"/skins/{i}"
        joints = skin.get("joints")
        if not isinstance(joints, list) or not joints or not all(integer(x) for x in joints) or len(set(joints)) != len(joints):
            fail("E_SKIN", ref, "Skin needs unique joint indices.")
        for joint in joints:
            index(joint, nodes, ref)
        if "skeleton" in skin:
            index(skin["skeleton"], nodes, ref)
        if "inverseBindMatrices" in skin:
            a = index(skin["inverseBindMatrices"], accessors, ref)
            if a["type"] != "MAT4" or a["componentType"] != 5126 or a["count"] < len(joints) or a.get("normalized", False):
                fail("E_SKIN_TYPE", ref, "Inverse bind accessor must be unnormalized FLOAT MAT4 with at least one matrix per joint.")
    for i, scene in enumerate(doc.get("scenes", ())):
        roots = scene.get("nodes", [])
        if not isinstance(roots, list) or not all(integer(x) for x in roots) or len(set(roots)) != len(roots):
            fail("E_SCENE", f"/scenes/{i}", "Scene nodes must be unique indices.")
        for root in roots:
            index(root, nodes, f"/scenes/{i}")
            if root in parents:
                fail("E_SCENE", f"/scenes/{i}", "Scene roots cannot have parents.")
    if "scene" in doc:
        index(doc["scene"], doc.get("scenes", ()), "/scene")
    for i, anim in enumerate(doc.get("animations", ())):
        ref = f"/animations/{i}"
        if not isinstance(anim.get("samplers"), list) or not anim["samplers"] or not isinstance(anim.get("channels"), list) or not anim["channels"]:
            fail("E_ANIMATION", ref, "Animation requires samplers and channels.")
        for sampler in anim["samplers"]:
            if not isinstance(sampler, Mapping):
                fail("E_ANIMATION", ref, "Sampler must be an object.")
            a = index(sampler.get("input"), accessors, ref)
            index(sampler.get("output"), accessors, ref)
            if a["type"] != "SCALAR" or a["componentType"] != 5126 or "min" not in a or "max" not in a:
                fail("E_ANIMATION_TYPE", ref, "Animation times require FLOAT SCALAR with min/max.")
            if sampler.get("interpolation") == "CUBICSPLINE" and a["count"] < 2:
                fail("E_ANIMATION_TYPE", ref, "Cubic samplers require at least two input keys.")
            if sampler.get("interpolation", "LINEAR") not in ("STEP", "LINEAR", "CUBICSPLINE"):
                fail("E_ANIMATION", ref, "Unknown interpolation.")
        driven = set()
        for ci, channel in enumerate(anim["channels"]):
            if not isinstance(channel, Mapping) or not isinstance(channel.get("target"), Mapping):
                fail("E_ANIMATION", ref, "Channel needs a target object.")
            index(channel.get("sampler"), anim["samplers"], ref)
            target = channel["target"]
            if type(target.get("path")) is not str:
                fail("E_TYPE", ref + f"/channels/{ci}/target/path", "Animation target path is required and must be a string.")
            if target.get("path") not in ("translation", "rotation", "scale", "weights"):
                extensions = target.get("extensions", {})
                if not isinstance(extensions, Mapping) or not any(k in doc.get("extensionsUsed", ()) for k in extensions):
                    fail("E_ANIMATION", ref, "Noncore animation path requires an inventoried extension.")
                if "KHR_animation_pointer" in extensions:
                    pointer = extensions["KHR_animation_pointer"]
                    if not isinstance(pointer, Mapping) or type(pointer.get("pointer")) is not str or not pointer["pointer"].startswith("/"):
                        fail("E_ANIMATION", ref, "Animation pointer must declare a JSON structural path.")
                continue
            if "node" in target:
                node = index(target["node"], nodes, ref)
                pair = (target["node"], target["path"])
                if pair in driven:
                    fail("E_MULTIPLE_WRITERS", ref, "Animation has competing property channels.")
                driven.add(pair)
                if "matrix" in node and target["path"] != "weights":
                    fail("E_ANIMATION", ref, "TRS animation cannot target a matrix-authored node.")
                animation_layout(doc, anim["samplers"][channel["sampler"]], target, index, ref)
    for i, image in enumerate(doc.get("images", ())):
        if ("uri" in image) == ("bufferView" in image):
            fail("E_IMAGE", f"/images/{i}", "Image requires exactly one URI or bufferView.")
        if "uri" in image:
            string(image["uri"], f"/images/{i}/uri")
        else:
            index(image["bufferView"], views, f"/images/{i}")
            string(image.get("mimeType"), f"/images/{i}/mimeType")
    validate_skin_hierarchy(doc, parents)
    for i, texture in enumerate(doc.get("textures", ())):
        for field, array in (("source", doc.get("images", ())), ("sampler", doc.get("samplers", ()))):
            if field in texture:
                index(texture[field], array, f"/textures/{i}")


def _data_uri(uri, ref):
    if not re.fullmatch(r"data:[^,]*;base64,[A-Za-z0-9+/=\r\n]*", uri):
        fail("E_RESOURCE_URI", ref, "Only explicit base64 data URIs are supported.")
    try:
        return base64.b64decode(uri.split(",", 1)[1].replace("\r", "").replace("\n", ""), validate=True)
    except binascii.Error:
        fail("E_RESOURCE_URI", ref, "Invalid base64 resource.")


def _parse_asset(raw, format):
    chunks = []
    bin_chunk = None
    if format.lower() == "glb":
        if len(raw) < 20:
            fail("E_GLB_HEADER", "/", "Truncated GLB header.")
        magic, version, length = struct.unpack_from("<III", raw)
        if magic != 0x46546C67 or version != 2 or length != len(raw) or length % 4:
            fail("E_GLB_HEADER", "/", "GLB magic/version/total length mismatch.")
        cursor = 12
        while cursor < len(raw):
            if cursor + 8 > len(raw):
                fail("E_GLB_CHUNK", "/", "Truncated chunk header.")
            size, kind = struct.unpack_from("<II", raw, cursor)
            cursor += 8
            if size % 4 or cursor + size > len(raw):
                fail("E_GLB_CHUNK", "/", "Chunk length is unaligned or exceeds GLB.")
            chunks.append(Chunk(kind, raw[cursor:cursor + size]))
            cursor += size
        if not chunks or chunks[0].type != 0x4E4F534A or sum(c.type == 0x4E4F534A for c in chunks) != 1 or sum(c.type == 0x004E4942 for c in chunks) > 1:
            fail("E_GLB_CHUNK", "/", "GLB needs one first JSON chunk and at most one BIN chunk.")
        for i, c in enumerate(chunks):
            if c.type == 0x004E4942:
                if i != 1:
                    fail("E_GLB_CHUNK", "/", "BIN chunk must be second.")
                bin_chunk = c.data
        doc = parse_document(chunks[0].data.decode("utf-8"))
        kind = "glb"
    else:
        doc = parse_document(raw.decode("utf-8"))
        kind = "gltf"
    return kind, doc, tuple(chunks), bin_chunk


@public
def inspect_asset(bytes, /, format, resolver=None, sidecar=None):
    if type(bytes) is not type(b"") or type(format) is not str or format.lower() not in ("gltf", "glb", "gltf2", "json"):
        fail("E_ASSET_TYPE", "/", "Expected immutable bytes and gltf/glb format.")
    return _inspect_gltf(bytes, format, resolver, sidecar)


def _inspect_gltf(bytes, format, resolver, sidecar, *, max_asset_bytes=MAX_ASSET_BYTES,
                  component_caps=(MAX_ACCESSOR_COMPONENTS, MAX_TOTAL_ACCESSOR_COMPONENTS), source=None):
    if len(bytes) > max_asset_bytes:
        fail("E_RESOURCE_LIMIT", "/", "Asset exceeds the 64 MiB input byte budget." if max_asset_bytes == MAX_ASSET_BYTES
             else f"Asset exceeds the {max_asset_bytes}-byte input budget.")
    if resolver is not None and not callable(resolver):
        fail("E_RESOLVER", "/", "Resolver must be an explicitly supplied callable.")
    kind, doc, chunks, bin_chunk = _parse_asset(bytes, format)
    _validate_document(doc, component_caps)
    resources = []
    warnings = []
    consumed_bytes = 0
    for i, b in enumerate(doc.get("buffers", ())):
        uri = b.get("uri")
        data = None
        ref = f"/buffers/{i}"
        if uri is None:
            if kind != "glb" or i != 0 or bin_chunk is None:
                fail("E_RESOURCE", ref, "Buffer without URI needs the first GLB BIN chunk.")
            if not b["byteLength"] <= len(bin_chunk) <= b["byteLength"] + 3 or any(bin_chunk[b["byteLength"]:]):
                fail("E_GLB_PADDING", ref, "BIN length or zero padding violates declared buffer length.")
            data = bin_chunk[:b["byteLength"]]
        elif uri.startswith("data:"):
            data = _data_uri(uri, ref)
        elif resolver is not None:
            data = resolver(uri)
            if type(data) is not type(bytes):
                fail("E_RESOLVER", ref, "Resolver must return immutable bytes.")
        else:
            warnings.append(Diagnostic("W_RESOURCE_UNCONSUMED", "warning", ref, "External resource inventoried without fetching.", "Supply a bounded local resolver to evaluate its accessors."))
        if data is not None:
            consumed_bytes += len(data)
            if len(data) > MAX_RESOURCE_BYTES or consumed_bytes > MAX_TOTAL_RESOURCE_BYTES:
                fail("E_RESOURCE_LIMIT", ref, "Consumed resource exceeds byte budget.")
            if len(data) < b["byteLength"]:
                fail("E_BUFFER_BOUNDS", ref, "Consumed buffer is shorter than byteLength.")
        resources.append(Resource(ref, uri, b["byteLength"], digest(data) if data is not None else None, data))
    snapshot = AssetSnapshot(kind, bytes, digest(bytes), freeze(doc), tuple(resources), tuple(chunks), freeze({}), source=source)
    errors = []
    for i, a in enumerate(doc.get("accessors", ())):
        # Spec1509: descriptors without base or sparse data may declare arbitrary
        # representable bounds. Structural/range checks already ran above.
        if "bufferView" not in a and "sparse" not in a:
            continue
        try:
            rows = _decode_accessor(snapshot, i, raw=True)
            validate_bounds(a, rows, f"/accessors/{i}")
        except Fault as exc:
            if exc.diagnostic.code != "E_RESOURCE_UNAVAILABLE":
                errors.append(exc.diagnostic)
    errors.extend(validate_binary(snapshot, _decode_accessor))
    # Validate available core channels independently of unknown extension channels.
    from .geometry import _sample_channel, _animation_times
    for i, anim in enumerate(doc.get("animations", ())):
        for sampler in anim["samplers"]:
            try:
                _animation_times(snapshot, sampler["input"])
            except Fault as exc:
                if exc.diagnostic.code != "E_RESOURCE_UNAVAILABLE":
                    errors.append(exc.diagnostic)
        for ci in range(len(anim["channels"])):
            try:
                _sample_channel(snapshot, i, ci, 0.0)
            except Fault as exc:
                if exc.diagnostic.code != "E_RESOURCE_UNAVAILABLE":
                    errors.append(exc.diagnostic)
    # Image payloads are also inventoried. BufferView images share their buffer digest.
    for i, img in enumerate(doc.get("images", ())):
        if "uri" in img:
            uri = img["uri"]
            data = _data_uri(uri, f"/images/{i}") if uri.startswith("data:") else resolver(uri) if resolver else None
            if data is not None and type(data) is not type(bytes):
                fail("E_RESOLVER", f"/images/{i}", "Resolver must return immutable bytes.")
            if data is not None:
                consumed_bytes += len(data)
                if len(data) > MAX_RESOURCE_BYTES or consumed_bytes > MAX_TOTAL_RESOURCE_BYTES:
                    fail("E_RESOURCE_LIMIT", f"/images/{i}", "Consumed image exceeds byte budget.")
            resources.append(Resource(f"/images/{i}", uri, len(data) if data is not None else 0, digest(data) if data is not None else None, data))
    snapshot = AssetSnapshot(kind, bytes, digest(bytes), freeze(doc), tuple(resources), tuple(chunks), freeze({}), source=source)
    if sidecar is not None:
        sc = _validate_sidecar(snapshot, sidecar)
        channels = {b["id"]: {k: b[k] for k in ("id", "value_type", "units", "domain", "calibration")} for b in sc["bindings"]}
        snapshot = AssetSnapshot(kind, bytes, digest(bytes), freeze(doc), tuple(resources), tuple(chunks), freeze(channels),
                                 freeze(sc["bindings"]), source=source)
    report = Report(tuple(errors + warnings))
    return Result(_admit(snapshot) if report.ok else None, report)


@public
def _inspect_source(adapter, data, fmt, resolver=None, sidecar=None, options=None):
    """Convert a source with `adapter`, then admit the GLB through the glTF path."""
    options = {} if options is None else options
    try:
        generated = adapter.convert(data, fmt, resolver, None, options)
    except SourceParseError as exc:
        fail("E_SOURCE_PARSE", "/", str(exc)[:512] or "The source reader rejected the file.",
             "Check that the source file is valid for its declared format.")
    source = {"format": fmt, "sha256": digest(data), "byte_length": len(data),
              "adapter": adapter.name, "adapter_version": adapter.version, "reader": adapter.reader(),
              "options_sha256": digest(canonical_json(options)), "node_order": "path-sorted-v2",
              "node_paths": list(generated.node_paths), "target_keys": [list(k) for k in generated.target_keys],
              "dependencies": [{"uri": uri, "sha256": sha, "byte_length": length} for uri, sha, length in generated.dependencies],
              "losses": [d.to_dict() for d in generated.losses]}
    result = _inspect_gltf(generated.glb, "glb", None, sidecar, max_asset_bytes=GENERATED_MAX_BYTES,
                           component_caps=(GENERATED_MAX_ACCESSOR_COMPONENTS, GENERATED_MAX_TOTAL_ACCESSOR_COMPONENTS),
                           source=freeze(source))
    report = Report(result.report.diagnostics + tuple(generated.losses), result.report.losses)
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
    keys(ref, {"asset_sha256", "locator", "node", "mesh", "target"}, {"resource_sha256"}, "/bindings/ref")
    if ref["asset_sha256"] != _identity(snapshot):
        fail("E_STALE_SOURCE", "/bindings/ref", "Binding asset hash is stale.")
    node = index(ref["node"], snapshot.document.get("nodes", ()), "/bindings/ref/node")
    mesh = index(ref["mesh"], snapshot.document.get("meshes", ()), "/bindings/ref/mesh")
    if node.get("mesh") != ref["mesh"] or not integer(ref["target"]) or not 0 <= ref["target"] < morph_count(mesh):
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
    for b in sc["bindings"]:
        _binding(snapshot, b)
        if b["id"] in ids or b["ref"]["locator"] in locators:
            fail("E_DUPLICATE_BINDING", "/sidecar/bindings", "Binding IDs and structural destinations must be unique.")
        ids.add(b["id"])
        locators.add(b["ref"]["locator"])
    from .common import json_value
    json_value(sc)
    return sc


@public
def annotate_asset(snapshot, annotations):
    if not isinstance(snapshot, AssetSnapshot) or snapshot.format == "profile":
        fail("E_SNAPSHOT", "/", "Annotation requires an inspected glTF asset.")
    snapshot._check_integrity()
    keys(annotations, {"bindings"}, {"metadata"}, "/annotations")
    sc = {"schema_version": "1.0", "asset_sha256": _identity(snapshot),
          "resource_hashes": snapshot.resource_hashes, **thaw(annotations)}
    _validate_sidecar(snapshot, sc)
    return _admit(Sidecar(sc))


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
