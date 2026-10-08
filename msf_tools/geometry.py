# SPDX-License-Identifier: MIT
"""Independent position geometry and animation reference; no taxonomy dependency."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import bisect
import math

from .common import freeze, thaw, number, integer
from .authoring import keys
from .snapshot import AssetSnapshot, _decode_accessor, index, vector, SUPPORTED_REQUIRED_EXTENSIONS
from .math3d import IDENTITY, matrix, multiply, inverse, trs, transform, slerp, normalize, column_major
from .report import public, fail, Result, Report, Fault
from .records import OwnedRecord, _admit
from .gltf_semantics import morph_count, animation_layout, CORE_PATHS


def _time(timestamp):
    if not number(timestamp) or timestamp < 0:
        fail("E_TIMESTAMP", "/timestamp", "Timestamp must be nonnegative finite seconds.")


def _asset(snapshot):
    if not isinstance(snapshot, AssetSnapshot) or snapshot.format == "profile":
        fail("E_SNAPSHOT", "/", "Expected an inspected glTF/GLB snapshot.")
    snapshot._check_integrity()
    unsupported = set(snapshot.document.get("extensionsRequired", ())) - SUPPORTED_REQUIRED_EXTENSIONS
    if unsupported:
        fail("E_REQUIRED_EXTENSION", "/extensionsRequired", "Requested evaluation has unsupported required behavior: " + ", ".join(sorted(unsupported)))


def _animation_times(snapshot, accessor_id):
    times = tuple(x[0] for x in _decode_accessor(snapshot, accessor_id))
    if any(t < 0 for t in times) or any(a >= b for a, b in zip(times, times[1:])):
        fail("E_ANIMATION_TIME", "/animations", "Animation times must be nonnegative and strictly increasing.")
    return times


def _sample_channel(snapshot, animation_id, channel_id, timestamp):
    anim = snapshot.document["animations"][animation_id]
    channel = anim["channels"][channel_id]
    target = channel["target"]
    if "node" not in target or target["path"] not in CORE_PATHS:
        return None
    ref = f"/animations/{animation_id}/channels/{channel_id}"
    sampler = anim["samplers"][channel["sampler"]]
    path = target["path"]
    count = animation_layout(snapshot.document, sampler, target, index, ref)
    interpolation = sampler.get("interpolation", "LINEAR")
    rows = _decode_accessor(snapshot, sampler["output"])
    if path == "weights":
        flat = tuple(x[0] for x in rows)
        rows = tuple(flat[i:i+count] for i in range(0, len(flat), count))
    values = rows[1::3] if interpolation == "CUBICSPLINE" else rows
    if path == "rotation" and any(abs(sum(x*x for x in q) - 1) > 1e-5 for q in values):
        fail("E_QUATERNION", "/animations", "Authored rotation keys must be unit quaternions.")
    times = _animation_times(snapshot, sampler["input"])
    if timestamp <= times[0]:
        value = values[0]
    elif timestamp >= times[-1]:
        value = values[-1]
    else:
        i = bisect.bisect_right(times, timestamp) - 1
        dt = times[i+1] - times[i]
        t = (timestamp - times[i]) / dt
        if interpolation == "STEP":
            value = values[i]
        elif interpolation == "LINEAR":
            value = slerp(values[i], values[i+1], t) if path == "rotation" else tuple(x + t*(y-x) for x, y in zip(values[i], values[i+1]))
        else:
            h00, h10, h01, h11 = 2*t**3-3*t**2+1, t**3-2*t**2+t, -2*t**3+3*t**2, t**3-t**2
            value = tuple(h00*p0 + h10*dt*m0 + h01*p1 + h11*dt*m1 for p0, m0, p1, m1 in zip(rows[3*i+1], rows[3*i+2], rows[3*(i+1)+1], rows[3*(i+1)]))
    if path == "rotation":
        value = normalize(value)
    if not all(number(x) for x in value):
        fail("E_NONFINITE", "/animations", "Animation result is not finite.")
    return target["node"], path, tuple(value)


def _sample_animation(snapshot, animation_id, timestamp):
    _time(timestamp)
    anim = index(animation_id, snapshot.document.get("animations", ()), "/animations")
    result = {}
    for ci in range(len(anim["channels"])):
        sampled = _sample_channel(snapshot, animation_id, ci, timestamp)
        if sampled is not None:
            node, path, value = sampled
            result.setdefault(node, {})[path] = value
    return result


@public
def sample_animation(snapshot, animation_id, timestamp):
    _asset(snapshot)
    return freeze(_sample_animation(snapshot, animation_id, timestamp))


def _worlds(snapshot, overrides):
    nodes = snapshot.document.get("nodes", ())
    parents = {child: i for i, n in enumerate(nodes) for child in n.get("children", ())}
    locals_ = []
    for i, node in enumerate(nodes):
        current = dict(node)
        current.update(overrides.get(i, {}))
        if "matrix" in current:
            local = matrix(current["matrix"])
            if any(abs(local[3][j] - IDENTITY[3][j]) > 1e-12 for j in range(4)):
                fail("E_TRANSFORM", f"/nodes/{i}", "Node matrix must be affine.")
        else:
            local = trs(current.get("translation", (0,0,0)), current.get("rotation", (0,0,0,1)), current.get("scale", (1,1,1)))
        locals_.append(local)
    worlds = {}
    for i in range(len(nodes)):
        chain = []
        j = i
        while j not in worlds:
            chain.append(j)
            if j not in parents:
                break
            j = parents[j]
        for j in reversed(chain):
            worlds[j] = multiply(worlds[parents[j]], locals_[j]) if j in parents else locals_[j]
    return worlds


@dataclass(frozen=True)
class GeometryValues(OwnedRecord):
    timestamp: float
    instances: tuple

    def to_dict(self):
        self._check_integrity()
        return {"timestamp": self.timestamp, "instances": thaw(self.instances)}


def _accessor(snapshot, aid, shape, components, count=None, normalized=None, ref="/geometry"):
    a = index(aid, snapshot.document.get("accessors", ()), ref)
    if a["type"] != shape or a["componentType"] not in components or count is not None and a["count"] != count or normalized is not None and a.get("normalized", False) != normalized:
        fail("E_GEOMETRY_TYPE", ref, "Geometry accessor has incompatible binary type, shape, count or normalization.")
    return _decode_accessor(snapshot, aid)


@public
def evaluate_geometry(snapshot, *, timestamp=0.0, animation_id=None, morph_weights=None, node_transforms=None, attributes=("POSITION",)):
    _asset(snapshot)
    _time(timestamp)
    if tuple(attributes) != ("POSITION",):
        fail("E_GEOMETRY_CAPABILITY", "/attributes", "Reference evaluation supports positions only.")
    if animation_id is not None and not integer(animation_id):
        fail("E_ANIMATION_REFERENCE", "/animation_id", "Select one explicit integer clip index.")
    overrides = _sample_animation(snapshot, animation_id, timestamp) if animation_id is not None else {}
    nodes = snapshot.document.get("nodes", ())
    for label, supplied in (("morph_weights", morph_weights), ("node_transforms", node_transforms)):
        if supplied is None:
            continue
        if not isinstance(supplied, Mapping):
            fail("E_GEOMETRY_TYPE", "/" + label, "Overrides must map integer node indices to values.")
        for ni, item in supplied.items():
            node = index(ni, nodes, "/" + label)
            if label == "morph_weights":
                if "mesh" not in node:
                    fail("E_MORPH", "/morph_weights", "Morph override needs a mesh node.")
                count = morph_count(snapshot.document["meshes"][node["mesh"]])
                vector(item, count, "/morph_weights")
                item = {"weights": tuple(item)}
            else:
                keys(item, set(), {"matrix", "translation", "rotation", "scale"}, "/node_transforms")
                if "matrix" in item and len(item) != 1 or "matrix" in node and "matrix" not in item or "matrix" in item and any(k in node for k in ("translation", "rotation", "scale")):
                    fail("E_NODE_TRANSFORM", "/node_transforms", "Matrix/TRS overrides must use the authored transform representation.")
                for field, count in (("matrix",16), ("translation",3), ("rotation",4), ("scale",3)):
                    if field in item:
                        vector(item[field], count, "/node_transforms/" + field)
            if set(item) & set(overrides.get(ni, {})) or "matrix" in item and set(overrides.get(ni, {})) - {"weights"}:
                fail("E_MULTIPLE_WRITERS", f"/nodes/{ni}", "Animation and explicit overrides drive the same property.")
            overrides.setdefault(ni, {}).update(item)
    worlds = _worlds(snapshot, overrides)
    instances, diagnostics = [], []
    for ni, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        mesh = snapshot.document["meshes"][node["mesh"]]
        primitives = []
        for pi, primitive in enumerate(mesh["primitives"]):
            ref = f"/nodes/{ni}/meshes/{node['mesh']}/primitives/{pi}"
            try:
                attrs = primitive["attributes"]
                if "POSITION" not in attrs:
                    fail("E_GEOMETRY_CAPABILITY", ref, "Primitive has no supported POSITION accessor.")
                if any(k.startswith("JOINTS_") and k != "JOINTS_0" or k.startswith("WEIGHTS_") and k != "WEIGHTS_0" for k in attrs):
                    fail("E_INFLUENCE_LIMIT", ref, "Requested geometry has more than four influences.")
                if any(k in primitive.get("extensions", {}) for k in ("KHR_draco_mesh_compression",)):
                    fail("E_GEOMETRY_CAPABILITY", ref, "Compressed geometry requires an unsupported decoder.")
                if any("EXT_meshopt_compression" in v.get("extensions", {}) for v in snapshot.document.get("bufferViews", ())):
                    fail("E_GEOMETRY_CAPABILITY", ref, "Compressed bufferViews require an unsupported decoder.")
                basis = _accessor(snapshot, attrs["POSITION"], "VEC3", {5126}, normalized=False, ref=ref)
                count = len(basis)
                if "indices" in primitive:
                    ix = _decode_accessor(snapshot, primitive["indices"])
                    if any(i[0] >= count for i in ix):
                        fail("E_INDEX_BOUNDS", ref, "Primitive index exceeds vertex count.")
                targets = primitive.get("targets", ())
                weights = overrides.get(ni, {}).get("weights", node.get("weights", mesh.get("weights", tuple(0.0 for _ in range(morph_count(mesh))))))
                positions = [list(map(float, p)) for p in basis]
                for weight, target in zip(weights, targets):
                    if "POSITION" in target:
                        deltas = _accessor(snapshot, target["POSITION"], "VEC3", {5126}, count, False, ref)
                        for p, delta in zip(positions, deltas):
                            for k in range(3):
                                p[k] += float(weight) * delta[k]
                if "skin" in node:
                    if "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                        fail("E_SKIN", ref, "Skinned primitive needs JOINTS_0 and WEIGHTS_0.")
                    skin = snapshot.document["skins"][node["skin"]]
                    joints = _accessor(snapshot, attrs["JOINTS_0"], "VEC4", {5121,5123}, count, False, ref)
                    weight_accessor = snapshot.document["accessors"][attrs["WEIGHTS_0"]]
                    normalized = weight_accessor["componentType"] != 5126
                    skinweights = _accessor(snapshot, attrs["WEIGHTS_0"], "VEC4", {5121,5123,5126}, count, normalized, ref)
                    ibms = tuple(matrix(x) for x in _decode_accessor(snapshot, skin["inverseBindMatrices"])) if "inverseBindMatrices" in skin else tuple(IDENTITY for _ in skin["joints"])
                    for ibm in ibms:
                        if ibm[3] != IDENTITY[3]:
                            fail("E_SKIN_TYPE", ref, "Inverse bind matrices must be affine.")
                    mesh_inverse = inverse(worlds[ni])
                    palettes = tuple(multiply(multiply(mesh_inverse, worlds[j]), ibm) for j, ibm in zip(skin["joints"], ibms))
                    skinned = []
                    for p, js, ws in zip(positions, joints, skinweights):
                        if any(j >= len(palettes) for j in js):
                            fail("E_JOINT_BOUNDS", ref, "Joint index exceeds skin palette; unknown weighted joints are never deleted.")
                        if any(w < 0 for w in ws) or abs(sum(ws) - 1.0) > 1e-6:
                            fail("E_SKIN_WEIGHTS", ref, "Four skin weights must be nonnegative and sum to one; no implicit normalization.")
                        ps = [transform(palettes[j], p) for j in js]
                        skinned.append([sum(w*q[k] for w,q in zip(ws,ps)) for k in range(3)])
                    positions = skinned
                if not all(number(x) for p in positions for x in p):
                    fail("E_NONFINITE", ref, "Geometry result overflows binary64.")
                primitives.append(freeze({"primitive": pi, "positions": positions}))
            except Fault as exc:
                diagnostics.append(exc.diagnostic)
        instances.append(freeze({"node": ni, "mesh": node["mesh"], "primitives": primitives}))
    if not instances:
        fail("E_GEOMETRY_EMPTY", "/nodes", "Asset has no mesh instances.")
    report = Report(tuple(diagnostics))
    return Result(_admit(GeometryValues(float(timestamp), tuple(instances))) if report.ok else None, report)


@public
def export_geometry_golden(snapshot, **kwargs):
    result = evaluate_geometry(snapshot, **kwargs)
    if not result.ok:
        return result
    return freeze({"schema_version": "1.0", "asset_sha256": snapshot.sha256,
                   "precision": "binary64", "coordinates": "mesh_local", "units": "metres",
                   "evaluation": result.value.to_dict()})


@public
def reparent_local(child_world, new_parent_world):
    """Hierarchy probe only. Reject shear/singular TRS; no skin preservation claim."""
    vector(child_world, 16, "/child_world")
    vector(new_parent_world, 16, "/new_parent_world")
    local = multiply(inverse(matrix(new_parent_world)), matrix(child_world))
    if any(abs(local[3][i] - IDENTITY[3][i]) > 1e-9 for i in range(4)):
        fail("E_TRANSFORM", "/reparent", "Expected affine transforms.")
    axes = [tuple(local[r][c] for r in range(3)) for c in range(3)]
    sizes = [math.sqrt(sum(x*x for x in a)) for a in axes]
    if min(sizes) == 0:
        fail("E_SINGULAR", "/reparent", "Reparented local has singular scale.")
    if any(abs(sum(x*y for x,y in zip(axes[i],axes[j])) / (sizes[i]*sizes[j])) > 1e-9 for i in range(3) for j in range(i)):
        fail("E_SHEAR", "/reparent", "Reparented local cannot be represented by TRS without shear.")
    return tuple(column_major(local))
