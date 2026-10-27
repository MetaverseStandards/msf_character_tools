# SPDX-License-Identifier: MIT
"""Independent position geometry and animation reference; no taxonomy dependency."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import bisect

from .common import freeze, thaw, number, integer
from .authoring import keys
from .snapshot import (AssetSnapshot, _decode_accessor, index, vector, SUPPORTED_REQUIRED_EXTENSIONS,
                       MAX_TOTAL_ACCESSOR_COMPONENTS, _identity, _source_summary)
from .math3d import (IDENTITY, matrix, multiply, inverse, trs, transform, slerp, normalize,
                     column_major, affine, validate_trs, authored_quaternion, linear, hermite,
                     _add, _sub, _product, _divide, _sum)
from .report import public, fail, Result, Report, Fault
from .records import OwnedRecord, _admit
from .gltf_semantics import morph_count, animation_layout, CORE_PATHS

# Position components read and written per mesh node instance (the base POSITION
# plus every morph-target POSITION), summed over instances, plus one set of inverse
# bind matrices per skin used. Inspection caps declared accessor components at the
# same number, so an asset that evaluates each of those accessors once fits;
# instancing a mesh or sharing accessors multiplies the work.
MAX_EVALUATION_COMPONENTS = MAX_TOTAL_ACCESSOR_COMPONENTS


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
    if path == "rotation":
        for q in values:
            authored_quaternion(q, "/animations")
    times = _animation_times(snapshot, sampler["input"])
    if timestamp <= times[0]:
        value = values[0]
    elif timestamp >= times[-1]:
        value = values[-1]
    else:
        i = bisect.bisect_right(times, timestamp) - 1
        if interpolation == "STEP":
            value = values[i]
        else:
            dt = _sub(times[i+1], times[i], "/animations")
            t = _divide(_sub(float(timestamp), times[i], "/animations"), dt, "/animations")
            if interpolation == "LINEAR":
                value = slerp(values[i], values[i+1], t) if path == "rotation" else linear(values[i], values[i+1], t)
            else:
                value = hermite(rows[3*i+1], rows[3*i+2], rows[3*(i+1)+1], rows[3*(i+1)], t, dt)
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
            validate_trs(local, affine_tolerance=1e-12, ref=f"/nodes/{i}")
        else:
            authored_quaternion(current.get("rotation", (0,0,0,1)), f"/nodes/{i}/rotation")
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


def _evaluation_components(document):
    accessors = document.get("accessors", ())
    per_mesh, per_skinned_mesh = [], []
    for mesh in document.get("meshes", ()):
        components = influences = 0
        for primitive in mesh["primitives"]:
            position = primitive["attributes"].get("POSITION")
            # Bad references are diagnosed per primitive during evaluation.
            if integer(position) and 0 <= position < len(accessors):
                count = accessors[position]["count"]
                targets = sum("POSITION" in target for target in primitive.get("targets", ()))
                components += 3 * count * (1 + targets)
                # Each influence set adds four joint and four weight components per vertex.
                influences += 8 * count * sum(k.startswith("JOINTS_") for k in primitive["attributes"])
        per_mesh.append(components)
        per_skinned_mesh.append(components + influences)
    instances = [node for node in document.get("nodes", ()) if "mesh" in node]
    skins = document.get("skins", ())
    # Inverse bind matrices are built once per skin, however many instances share it.
    used_skins = {node["skin"] for node in instances if "skin" in node}
    return (sum((per_skinned_mesh if "skin" in node else per_mesh)[node["mesh"]] for node in instances)
            + sum(16 * len(skins[i]["joints"]) for i in used_skins if integer(i) and 0 <= i < len(skins)))


@public
def evaluate_geometry(snapshot, *, timestamp=0.0, animation_id=None, morph_weights=None, node_transforms=None, attributes=("POSITION",)):
    _asset(snapshot)
    _time(timestamp)
    if tuple(attributes) != ("POSITION",):
        fail("E_GEOMETRY_CAPABILITY", "/attributes", "Reference evaluation supports positions only.")
    components = _evaluation_components(snapshot.document)
    budget = MAX_EVALUATION_COMPONENTS if snapshot.source is None else snapshot._component_caps()[1]
    if components > budget:
        fail("E_RESOURCE_LIMIT", "/nodes", f"Mesh instances need {components} position and morph-target components; the budget is {budget}.",
             "Reduce mesh instances or vertices, or evaluate a smaller asset.")
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
    skin_matrices = {}
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
                                p[k] = _add(p[k], _product(float(weight), delta[k], ref), ref)
                if "skin" in node:
                    if "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                        fail("E_SKIN", ref, "Skinned primitive needs JOINTS_0 and WEIGHTS_0.")
                    sets = sum(k.startswith("JOINTS_") for k in attrs)
                    if any(f"JOINTS_{s}" not in attrs or f"WEIGHTS_{s}" not in attrs for s in range(sets)):
                        fail("E_SKIN", ref, "Influence sets must be paired and numbered from 0.")
                    skin = snapshot.document["skins"][node["skin"]]
                    joints, skinweights = [()] * count, [()] * count
                    # Each vertex's influences are the sets concatenated in order, so one set evaluates exactly as before.
                    for s in range(sets):
                        set_joints = _accessor(snapshot, attrs[f"JOINTS_{s}"], "VEC4", {5121,5123}, count, False, ref)
                        normalized = snapshot.document["accessors"][attrs[f"WEIGHTS_{s}"]]["componentType"] != 5126
                        set_weights = _accessor(snapshot, attrs[f"WEIGHTS_{s}"], "VEC4", {5121,5123,5126}, count, normalized, ref)
                        joints = [a + tuple(b) for a, b in zip(joints, set_joints)] if sets > 1 else set_joints
                        skinweights = [a + tuple(b) for a, b in zip(skinweights, set_weights)] if sets > 1 else set_weights
                    if node["skin"] not in skin_matrices:
                        ibms = tuple(matrix(x) for x in _decode_accessor(snapshot, skin["inverseBindMatrices"])) if "inverseBindMatrices" in skin else tuple(IDENTITY for _ in skin["joints"])
                        skin_matrices[node["skin"]] = ibms, all(ibm[3] == IDENTITY[3] for ibm in ibms)
                    ibms, affine_ibms = skin_matrices[node["skin"]]
                    if not affine_ibms:
                        fail("E_SKIN_TYPE", ref, "Inverse bind matrices must be affine.")
                    mesh_inverse = inverse(worlds[ni])
                    # Admit every original row before any influence selects arithmetic.
                    for js, ws in zip(joints, skinweights):
                        if any(j >= len(skin["joints"]) for j in js):
                            fail("E_JOINT_BOUNDS", ref, "Joint index exceeds skin palette; unknown weighted joints are never deleted.")
                        if any(w < 0 for w in ws) or abs(_sub(_sum(ws, ref), 1.0, ref)) > 1e-6:
                            fail("E_SKIN_WEIGHTS", ref, ("Four" if sets == 1 else "All") + " skin weights must be nonnegative and sum to one; no implicit normalization.")
                    palettes, skinned = {}, []
                    for p, js, ws in zip(positions, joints, skinweights):
                        contributions = []
                        for j, w in zip(js, ws):
                            if w == 0:
                                continue
                            if j not in palettes:
                                palettes[j] = multiply(multiply(mesh_inverse, worlds[skin["joints"][j]]), ibms[j])
                            contributions.append((w, transform(palettes[j], p)))
                        skinned.append([_sum((_product(w,q[k],ref) for w,q in contributions),ref) for k in range(3)])
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
    golden = {"schema_version": "1.0", "asset_sha256": _identity(snapshot),
              "precision": "binary64", "coordinates": "mesh_local", "units": "metres",
              "evaluation": result.value.to_dict()}
    if snapshot.source is not None:
        golden["source"] = _source_summary(snapshot)
    return freeze(golden)


@public
def reparent_local(child_world, new_parent_world):
    """Hierarchy probe only. Reject shear/singular TRS; no skin preservation claim."""
    vector(child_world, 16, "/child_world")
    vector(new_parent_world, 16, "/new_parent_world")
    child = affine(matrix(child_world), 1e-9, '/child_world')
    parent = affine(matrix(new_parent_world), 1e-9, '/new_parent_world')
    local = multiply(inverse(parent), child)
    validate_trs(local, ref='/reparent')
    return tuple(column_major(local))
