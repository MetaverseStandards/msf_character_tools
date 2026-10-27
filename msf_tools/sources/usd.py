# SPDX-License-Identifier: MIT
"""USD adapter built on usd-core (`pxr`). Importing this module fails when pxr is absent."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import io
import math
import posixpath
import re
import tempfile
import zipfile

from pxr import Sdf, Tf, Usd, UsdGeom, UsdLux, UsdShade, UsdSkel

from ..common import digest
from ..report import Diagnostic, fail
from . import Generated, SourceParseError
from . import glb, paths, skinning, transforms

_EARLIEST = Usd.TimeCode.EarliestTime()


def _node_path(prim):
    return paths.node_path([(name, None) for name in str(prim.GetPath()).split("/")[1:]])


def _matrix(gf):
    return [float(gf[r][c]) for r in range(4) for c in range(4)]


_Z_UP = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))
_Y_UP = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class _Conversion:
    """C = metersPerUnit * R_up, applied to points and offsets as C p and to local matrices as C L C^-1.

    R_up is a signed axis permutation, so conjugating a shear-free matrix keeps it shear-free.
    """

    def __init__(self, stage):
        self.scale = float(UsdGeom.GetStageMetersPerUnit(stage))
        if not math.isfinite(self.scale) or self.scale <= 0:
            fail("E_SOURCE_VALUE", "/", "metersPerUnit must be a positive finite number.")
        self.rotation = _Z_UP if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z else _Y_UP
        self.losses = []
        if self.scale != 1.0:
            self.losses.append(Diagnostic("I_UNITS_CONVERTED", "info", "/", f"Converted {self.scale:g} metres per unit to metres.", "No action needed."))
        if self.rotation is _Z_UP:
            self.losses.append(Diagnostic("I_AXES_CONVERTED", "info", "/", "Converted Z-up to Y-up.", "No action needed."))

    def point(self, p, scale=True):
        k = self.scale if scale else 1.0
        return tuple(k * math.fsum(self.rotation[r][c] * p[c] for c in range(3)) for r in range(3))

    def matrix(self, m):
        """Conjugate a column-major local matrix."""
        a = [[m[4 * c + r] for c in range(3)] for r in range(3)]
        r = self.rotation
        b = [[math.fsum(r[i][k] * a[k][l] * r[j][l] for k in range(3) for l in range(3)) for j in range(3)] for i in range(3)]
        t = self.point(m[12:15])
        return [x for col in range(3) for x in (b[0][col], b[1][col], b[2][col], 0.0)] + [*t, 1.0]


def _apply(m, p):
    return tuple(math.fsum(m[4 * c + r] * p[c] for c in range(3)) + m[12 + r] for r in range(3))


def _local(prim, path, conversion):
    """The prim's local matrix at the earliest time, converted, or None for prims without one."""
    if not prim.IsA(UsdGeom.Xformable):
        return None
    matrix = _matrix(UsdGeom.Xformable(prim).GetLocalTransformation(_EARLIEST))
    if not all(math.isfinite(x) for x in matrix):
        fail("E_SOURCE_VALUE", path, "Transform has a non-finite number.")
    if not transforms.is_affine(matrix):
        fail("E_SOURCE_VALUE", path, "Transform is not affine.")
    return conversion.matrix(matrix)


def _trs(matrix, path):
    try:
        translation, rotation, scale = transforms.decompose(matrix)
    except ValueError:
        fail("E_SOURCE_VALUE", path, "Transform is singular.")
    return {"translation": translation, "rotation": rotation, "scale": scale}


def _shear(path):
    fail("E_SHEAR_UNSUPPORTED", path, "Transform has shear, which glTF TRS cannot represent.",
         "Remove the shear, or keep it only on static unskinned leaf meshes, where it is baked into the points.")


def _triangles(mesh, path, flip, skipped):
    counts = list(mesh.GetFaceVertexCountsAttr().Get(_EARLIEST) or ())
    indices = list(mesh.GetFaceVertexIndicesAttr().Get(_EARLIEST) or ())
    if sum(counts) != len(indices) or any(c < 0 for c in counts):
        fail("E_SOURCE_VALUE", path, "Face vertex counts and indices disagree.")
    holes = set(mesh.GetHoleIndicesAttr().Get(_EARLIEST) or ())
    if any(not 0 <= h < len(counts) for h in holes):
        fail("E_SOURCE_VALUE", path, "Hole indices must name faces of the mesh.")
    skipped["hole face"] += len(holes)
    triangles, start = [], 0
    for f, count in enumerate(counts):
        face = indices[start:start + count]
        start += count
        if f in holes:
            continue
        for k in range(1, count - 1):
            triangles += [face[0], face[k + 1], face[k]] if flip else [face[0], face[k], face[k + 1]]
    return triangles


def _skipped_kind(prim):
    if prim.IsA(UsdGeom.Mesh):
        return None
    if (prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.PointInstancer) or prim.IsA(UsdGeom.Camera)
            or prim.HasAPI(UsdLux.LightAPI) or prim.IsA(UsdShade.Material)):
        return prim.GetTypeName() or "untyped prim"
    return None


_PLURALS = {"hole face": "hole faces",
            "external asset dependency": "external asset dependencies"}


def _skipped(counts):
    """One W_SKIPPED counting skipped prims by type name, then the other skipped kinds."""
    parts = [f"{n} {kind}" for kind, n in sorted(counts.items()) if kind not in _PLURALS and n]
    parts += [f"{counts[kind]} {kind if counts[kind] == 1 else plural}" for kind, plural in _PLURALS.items() if counts[kind]]
    if not parts:
        return []
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return [Diagnostic("W_SKIPPED", "warning", "/", f"Skipped {text}.", "Review the declared loss.")]


def _time_varying(prim, query):
    """Names of the attributes feeding a mesh's points, topology, blend shapes or skin weights that change over time."""
    mesh = UsdGeom.Mesh(prim)
    attributes = [mesh.GetPointsAttr(), mesh.GetFaceVertexCountsAttr(), mesh.GetFaceVertexIndicesAttr(), mesh.GetHoleIndicesAttr()]
    if query is not None:
        # The skin primvars can be inherited from an ancestor, so they come from the skinning query.
        attributes += [query.GetJointIndicesPrimvar().GetAttr(), query.GetJointWeightsPrimvar().GetAttr(), query.GetGeomBindTransformAttr()]
    for target in UsdSkel.BindingAPI(prim).GetBlendShapeTargetsRel().GetTargets():
        shape = UsdSkel.BlendShape(prim.GetStage().GetPrimAtPath(target))
        if shape:
            attributes += [shape.GetOffsetsAttr(), shape.GetPointIndicesAttr()]
    return [a.GetName() if a.GetPrim() == prim else str(a.GetPath()) for a in attributes if a and a.ValueMightBeTimeVarying()]


def _blend_shapes(prim, points, path):
    binding = UsdSkel.BindingAPI(prim)
    tokens = list(binding.GetBlendShapesAttr().Get() or ())
    targets = list(binding.GetBlendShapeTargetsRel().GetTargets()) if tokens else []
    if len(tokens) != len(targets):
        fail("E_SOURCE_VALUE", path, "skel:blendShapes and skel:blendShapeTargets have different lengths.")
    keys, offsets, inbetweens = [], [], 0
    for token, target in zip(tokens, targets):
        shape = UsdSkel.BlendShape(prim.GetStage().GetPrimAtPath(target))
        if not shape:
            fail("E_SOURCE_VALUE", path, f"Blend shape target {target} is not a BlendShape.")
        values = [tuple(map(float, v)) for v in shape.GetOffsetsAttr().Get(_EARLIEST) or ()]
        indices = shape.GetPointIndicesAttr().Get(_EARLIEST)
        if not shape.GetOffsetsAttr().HasAuthoredValue():
            # A shape that only moves normals leaves positions where they are.
            values = [(0.0, 0.0, 0.0)] * (len(indices) if indices else len(points))
        dense = [(0.0, 0.0, 0.0)] * len(points)
        if indices is None or len(indices) == 0:
            if len(values) != len(points):
                fail("E_SOURCE_VALUE", path, f"Blend shape {token} needs one offset per point.")
            dense = values
        else:
            if len(indices) != len(values) or any(not 0 <= i < len(points) for i in indices):
                fail("E_SOURCE_VALUE", path, f"Blend shape {token} point indices are invalid.")
            for i, v in zip(indices, values):
                dense[i] = v
        keys.append(paths.target_key([(str(token), None)]))
        offsets.append(tuple(dense))
        inbetweens += len(shape.GetInbetweens())
    return [str(t) for t in tokens], keys, offsets, inbetweens


class UsdAdapter:
    name = "msf-usd"
    version = "1"
    formats = ("usda", "usdc", "usdz")

    def reader(self):
        return "usd-core " + ".".join(map(str, Usd.GetVersion()))

    def convert(self, data, fmt, resolver, limits, options):
        with tempfile.TemporaryDirectory() as tmp:
            layer, dependencies, external = _materialize(Path(tmp), data, fmt, resolver, limits)
            try:
                stage = Usd.Stage.Open(layer)
            except Tf.ErrorException as exc:
                raise SourceParseError(str(exc).strip()) from None
            try:
                generated = _convert(stage, self, dependencies, external, options)
                _check_used_layers(stage, Path(tmp))
                return generated
            finally:
                del stage


def _check_used_layers(stage, tmp):
    """Refuse if any layer the stage used, clip layers included, came from outside the materialized folder.

    The pre-scan should already stop every route out; this catches any it misses.
    """
    root = tmp.resolve()
    for layer in stage.GetUsedLayers(includeClipLayers=True):
        if layer.anonymous:
            continue
        real = layer.realPath.split("[", 1)[0]
        try:
            Path(real).resolve().relative_to(root)
        except ValueError:
            fail("E_SOURCE_REFERENCE", "/", f"usd-core loaded a layer from outside the source: {layer.identifier[:200]}",
                 "Remove the reference, clip or other path that reaches outside the source.")


def _open(identifier):
    try:
        layer = Sdf.Layer.FindOrOpen(identifier)
    except Tf.ErrorException as exc:
        raise SourceParseError(str(exc).strip()) from None
    if layer is None:
        raise SourceParseError("usd-core could not open a source layer.")
    return layer


def _usdz_members(root, data, limits):
    def bad(message):
        fail("E_USDZ_ARCHIVE", "/", message, "Repackage the USDZ with stored, unencrypted, unique relative members.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        bad(f"USDZ is not a readable ZIP archive: {exc}")
    if len(infos) > limits.max_usdz_members:
        bad(f"USDZ has more than {limits.max_usdz_members} members.")
    names = [info.filename for info in infos]
    for info in infos:
        name = info.filename
        if info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 0x1:
            bad(f"USDZ member {name!r} is compressed or encrypted.")
        if not name or name.startswith("/") or "\\" in name or ".." in name.split("/") or re.match(r"[A-Za-z]:", name):
            bad(f"USDZ member {name!r} is not a plain relative path.")
    if len(set(names)) != len(names):
        bad("USDZ has duplicate member names.")
    try:
        listed = list(Sdf.ZipFile.Open(str(root)).GetFileNames())
    except Tf.ErrorException:
        listed = None
    if listed != names:
        bad("usd-core reads the USDZ members differently from the ZIP directory.")
    return names


def _anchor(asset, base):
    """Resolve an authored layer path against the layer that names it, or refuse it.

    USD looks for a bare path such as `sub.usda` next to the referring layer before
    trying search paths. Only that first step is taken here, so search paths are never used.
    """
    if asset.startswith("/") or "\\" in asset or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", asset):
        fail("E_SOURCE_REFERENCE", "/", f"Layer path @{asset}@ is not a relative path.",
             "Author layer references as paths relative to the referring layer.")
    anchored = posixpath.normpath(posixpath.join(posixpath.dirname(base), asset))
    if anchored == ".." or anchored.startswith("../") or anchored.startswith("/"):
        fail("E_SOURCE_REFERENCE", "/", f"Layer path @{asset}@ escapes the source root.")
    return anchored


def _refuse_clips(layer):
    # Value clips name layers that usd-core opens lazily, outside the closure checked here.
    clipped = []

    def visit(path):
        # Clips can sit on a variant spec (/A{v=x}) as well as a prim; a variant set path (/A{v=}) has no prim spec.
        spec = layer.GetPrimAtPath(path) if path.IsPrimPath() or path.IsPrimVariantSelectionPath() else None
        if spec and any(spec.HasInfo(key) for key in ("clips", "clipSets")):
            clipped.append(path)

    layer.Traverse("/", visit)
    if clipped:
        fail("E_SOURCE_REFERENCE", "/", f"Value clips on {clipped[0]} are not supported.",
             "Flatten the clips into the layer before inspecting.")


def _materialize(tmp, data, fmt, resolver, limits):
    """Write the source and every layer it composes under `tmp`, before any stage exists."""
    root = tmp / f"root.{fmt}"
    root.write_bytes(data)
    members = _usdz_members(root, data, limits) if fmt == "usdz" else None
    # A package's root layer is its first member, and other members are named relative to it.
    base = members[0] if members else root.name
    layer = _open(str(root))
    queue, seen, fetched, external = [(layer, base)], {base}, {}, set()
    total = 0
    while queue:
        current, location = queue.pop(0)
        _refuse_clips(current)
        external.update(current.GetExternalAssetDependencies())
        for asset in sorted(current.GetCompositionAssetDependencies()):
            if not asset:  # a reference to a prim in the same layer
                continue
            anchored = _anchor(asset, location)
            if anchored in seen:
                continue
            seen.add(anchored)
            if members is not None:
                if anchored not in members:
                    fail("E_SOURCE_REFERENCE", "/", f"Layer path @{asset}@ is not inside the USDZ package.")
                queue.append((_open(f"{root}[{anchored}]"), anchored))
                continue
            if resolver is None:
                fail("E_SOURCE_REFERENCE", "/", f"Layer @{asset}@ needs a resolver.", "Pass a LocalResolver rooted at the source directory.")
            try:
                payload = resolver(anchored)
            except OSError as exc:
                fail("E_SOURCE_REFERENCE", "/", f"Layer @{asset}@ could not be read: {exc}")
            if type(payload) is not bytes:
                fail("E_RESOLVER", "/", "Resolver must return immutable bytes.")
            total += len(payload)
            fetched[anchored] = (digest(payload), len(payload))
            if len(fetched) > limits.max_dependencies or total > limits.max_dependency_bytes:
                fail("E_RESOURCE_LIMIT", "/source/dependencies", "Source layers exceed the dependency count or byte limit.")
            target = tmp / anchored
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            queue.append((_open(str(target)), anchored))
    return layer, tuple((uri, sha, length) for uri, (sha, length) in sorted(fetched.items())), len(external)


def _checked(gf, path, conversion):
    matrix = _matrix(gf)
    if not all(math.isfinite(x) for x in matrix):
        fail("E_SOURCE_VALUE", path, "Transform has a non-finite number.")
    if not transforms.is_affine(matrix):
        fail("E_SOURCE_VALUE", path, "Transform is not affine.")
    return conversion.matrix(matrix)


class _Skeleton:
    """One bound skeleton: joint node paths in skeleton order, converted locals and inverse binds."""

    def __init__(self, skel, query, path, conversion):
        tokens = [str(t) for t in query.GetJointOrder()]
        valid, reason = query.GetTopology().Validate()
        if not valid:
            fail("E_SOURCE_VALUE", path, f"Skeleton joints are invalid: {reason}")
        if any(not c for t in tokens for c in t.split("/")):
            fail("E_SOURCE_VALUE", path, "Skeleton joint names must be non-empty path components.")
        base = paths.parse_node_path(path)[0]
        self.paths = [paths.node_path(base[:-1] + [(base[-1][0] + ".joints", None)] + [(c, None) for c in t.split("/")])
                      for t in tokens]
        if len(set(self.paths)) != len(self.paths):
            fail("E_SOURCE_VALUE", path, "Skeleton joint names must be unique.")
        self.owner = path
        self.query = query
        self.tokens = {t: j for j, t in enumerate(tokens)}
        self.parents = list(query.GetTopology().GetParentIndices())
        self.root = next(j for j, parent in enumerate(self.parents) if parent < 0) if tokens else None
        self.locals = [_checked(gf, self.paths[j], conversion)
                       for j, gf in enumerate(query.ComputeJointLocalTransforms(_EARLIEST) or ())]
        binds = list(skel.GetBindTransformsAttr().Get() or ())
        if len(self.locals) != len(tokens) or len(binds) != len(tokens):
            fail("E_SOURCE_VALUE", path, "Skeleton needs one rest or animated transform and one bind transform per joint.")
        self.inverse_binds = []
        for j, gf in enumerate(binds):
            matrix = _checked(gf, self.paths[j], conversion)
            if transforms.determinant(matrix) == 0:
                fail("E_SOURCE_VALUE", self.paths[j], "Bind transform is singular.")
            self.inverse_binds.append(conversion.matrix(_matrix(gf.GetInverse())))


def _skel_bindings(prims):
    """Skinning queries keyed by mesh prim path, each with the skeleton prim path it binds to.

    A mesh can be bound only for its blend shapes, with no joint influences."""
    predicate = Usd.TraverseInstanceProxies()
    cache, bound, skeletons = UsdSkel.Cache(), {}, {}
    for prim in prims:
        if not prim.IsA(UsdSkel.Root):
            continue
        root = UsdSkel.Root(prim)
        cache.Populate(root, predicate)
        for binding in cache.ComputeSkelBindings(root, predicate):
            skel = binding.GetSkeleton()
            query = cache.GetSkelQuery(skel)
            if not query:
                fail("E_SOURCE_VALUE", _node_path(skel.GetPrim()), "Skeleton could not be read.")
            skeletons.setdefault(skel.GetPrim().GetPath(), (skel, query))
            for target in binding.GetSkinningTargets():
                if target.GetPrim().IsA(UsdGeom.Mesh):
                    bound.setdefault(target.GetPrim().GetPath(), (skel.GetPrim().GetPath(), target))
    return skeletons, bound


def _influences(target, skeleton, count, path, mode):
    """Per-point (skeleton joint, weight) pairs for one skinned mesh, and the losses they declare."""
    indices, weights = target.ComputeJointInfluences(_EARLIEST)
    indices, weights = list(indices), [float(w) for w in weights]
    size = target.GetNumInfluencesPerComponent()
    if target.GetInterpolation() == UsdGeom.Tokens.constant:
        indices, weights = indices * count, weights * count
    if size < 1 or len(indices) != size * count or len(weights) != len(indices):
        fail("E_SOURCE_VALUE", path, "Joint influences need one set per point.")
    order = target.GetJointOrder()
    if order is None:
        mapping = list(range(len(skeleton.paths)))
    else:
        if any(str(t) not in skeleton.tokens for t in order):
            fail("E_SOURCE_VALUE", path, "skel:joints names a joint the skeleton does not have.")
        mapping = [skeleton.tokens[str(t)] for t in order]
    merged_rows = []
    for v in range(count):
        joints = indices[size * v:size * v + size]
        if any(not 0 <= joint < len(mapping) for joint in joints):
            fail("E_SOURCE_VALUE", path, "Joint influences need valid joint indices.")
        merged_rows.append(skinning.merge(zip((mapping[j] for j in joints), weights[size * v:size * v + size]), path))
    rows, losses = skinning.influence_rows(merged_rows, skeleton.root, mode, path)
    method = str(target.GetSkinningMethod())
    if method != "classicLinear":
        losses.append(skinning.method_loss(path, method))
    return rows, losses


def _quaternions(rows):
    """Flip quaternions into the hemisphere of their predecessor so LINEAR slerp takes the short way."""
    out = [rows[0]]
    for q in rows[1:]:
        out.append(q if math.fsum(a * b for a, b in zip(out[-1], q)) >= 0 else tuple(-x for x in q))
    return out


def _blend_weights(anim, tokens, code):
    order = {str(t): k for k, t in enumerate(anim.GetBlendShapeOrder())}
    weights = list(anim.ComputeBlendShapeWeights(code))
    return tuple(float(weights[order[t]]) if t in order and order[t] < len(weights) else 0.0 for t in tokens)


def _animate(stage, entries, skeletons, weighted, conversion):
    """One glTF animation sampling every animated node at the union of authored time codes."""
    moving = {i for i, (_, prim, _) in enumerate(entries) if prim is not None and prim.IsA(UsdGeom.Xformable)
              and UsdGeom.Xformable(prim).TransformMightBeTimeVarying()}
    codes = set()
    for i in moving:
        codes.update(UsdGeom.Xformable(entries[i][1]).GetTimeSamples())
    for skeleton in skeletons.values():
        anim = skeleton.query.GetAnimQuery()
        if anim:
            codes.update(anim.GetJointTransformTimeSamples())
            codes.update(anim.GetBlendShapeWeightTimeSamples())
    if stage.HasAuthoredTimeCodeRange():
        codes = {c for c in codes if stage.GetStartTimeCode() <= c <= stage.GetEndTimeCode()}
    codes = sorted(codes)
    if len(codes) < 2:
        return (), []
    rate = float(stage.GetTimeCodesPerSecond())
    if not math.isfinite(rate) or rate <= 0:
        fail("E_SOURCE_VALUE", "/", "timeCodesPerSecond must be a positive finite number.")
    shift = min(0.0, codes[0])
    losses = []
    if shift < 0:
        losses.append(skinning.warning("W_TIME_SHIFTED", "/", f"Shifted time codes by {-shift:g} so the animation starts at 0 seconds."))
    times = tuple((c - shift) / rate for c in codes)
    poses = {}
    channels = []
    for i, (path, prim, joint) in enumerate(entries):
        matrices = None
        if joint is not None:
            skeleton, j = joint
            if skeleton.query.GetAnimQuery():
                if skeleton.owner not in poses:
                    poses[skeleton.owner] = [list(skeleton.query.ComputeJointLocalTransforms(Usd.TimeCode(c))) for c in codes]
                matrices = [_checked(pose[j], path, conversion) for pose in poses[skeleton.owner]]
        elif i in moving:
            xformable = UsdGeom.Xformable(prim)
            matrices = [_checked(xformable.GetLocalTransformation(Usd.TimeCode(c)), path, conversion) for c in codes]
        if matrices:
            if any(transforms.has_shear(matrix) for matrix in matrices):
                _shear(path)
            samples = [_trs(matrix, path) for matrix in matrices]
            for field in ("translation", "rotation", "scale"):
                rows = [sample[field] for sample in samples]
                if field == "rotation":
                    rows = _quaternions(rows)
                if any(row != rows[0] for row in rows):
                    channels.append(glb.Channel(node=i, path=field, times=times, values=tuple(rows)))
        if i in weighted:
            anim, tokens = weighted[i]
            rows = [_blend_weights(anim, tokens, Usd.TimeCode(c)) for c in codes]
            if any(row != rows[0] for row in rows):
                channels.append(glb.Channel(node=i, path="weights", times=times, values=tuple(rows)))
    return ((glb.Animation(channels=tuple(channels)),) if channels else ()), losses


def _convert(stage, adapter, dependencies, external, options):
    conversion = _Conversion(stage)
    skipped = Counter({"external asset dependency": external})
    every = [p for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()) if p != stage.GetPseudoRoot()]
    for prim in every:
        kind = _skipped_kind(prim)
        if kind:
            skipped[kind] += 1
    prims = [p for p in every if p.IsA(UsdGeom.Xformable) or p.IsA(UsdGeom.Scope)]
    prim_paths = {p.GetPath(): _node_path(p) for p in prims}
    found, bound = _skel_bindings(every)
    skeletons = {path: _Skeleton(skel, query, prim_paths[path], conversion)
                 for path, (skel, query) in found.items() if path in prim_paths}
    entries = [(prim_paths[p.GetPath()], p, None) for p in prims]
    entries += [(joint_path, None, (skeleton, j)) for skeleton in skeletons.values() for j, joint_path in enumerate(skeleton.paths)]
    entries.sort(key=lambda entry: paths.sort_key(entry[0]))
    index = {entry[0]: i for i, entry in enumerate(entries)}
    children = {i: [] for i in range(len(entries))}
    for i, (_, prim, joint) in enumerate(entries):
        if joint is not None:
            skeleton, j = joint
            parent = skeleton.parents[j]
            children[index[skeleton.paths[parent] if parent >= 0 else skeleton.owner]].append(i)
            continue
        if prim.IsA(UsdGeom.Xformable) and UsdGeom.Xformable(prim).GetResetXformStack():
            continue
        parent = prim.GetParent()
        while parent and parent.GetPath() not in prim_paths:
            parent = parent.GetParent()
        if parent:
            children[index[prim_paths[parent.GetPath()]]].append(i)
    def skinned_by(prim):
        found = bound.get(prim.GetPath())
        if found is None or found[0] not in skeletons or not skeletons[found[0]].paths or not found[1].HasJointInfluences():
            return None
        return found

    used = {skinned_by(prim)[0] for _, prim, _ in entries if prim is not None and skinned_by(prim) is not None}
    skin_of = {path: k for k, path in enumerate(sorted(used, key=lambda path: index[skeletons[path].owner]))}
    nodes, meshes, target_keys, losses, weighted = [], [], [], [], {}
    for i, (path, prim, joint) in enumerate(entries):
        if joint is not None:
            skeleton, j = joint
            local = skeleton.locals[j]
            if transforms.has_shear(local):
                _shear(path)
            name = skeleton.paths[j].rsplit("/", 1)[1]
            nodes.append(glb.Node(name=paths.unescape(name), children=tuple(children[i]), **_trs(local, path)))
            continue
        skinned = skinned_by(prim)
        binding = bound.get(prim.GetPath())
        animation = skeletons[binding[0]].query.GetAnimQuery() if binding is not None and binding[0] in skeletons else None
        local = _local(prim, path, conversion)
        baked = None
        if local is not None and transforms.has_shear(local):
            if (not prim.IsA(UsdGeom.Mesh) or children[i] or skinned is not None
                    or UsdGeom.Xformable(prim).TransformMightBeTimeVarying()):
                _shear(path)
            baked, local = local, None
            losses.append(skinning.warning("W_SHEAR_BAKED", path, "Sheared transform baked into the mesh points."))
        elif local is not None and transforms.determinant(local) < 0:
            losses.append(Diagnostic("I_MIRRORED", "info", path, "Mirrored transform stored as a negative X scale.", "No action needed."))
        mesh_index = skin_index = static_weights = None
        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            if mesh.GetSubdivisionSchemeAttr().Get() != UsdGeom.Tokens.none:
                losses.append(skinning.warning("W_SUBDIV_CAGE", path, "Subdivision surface uses its control cage."))
            left = mesh.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded
            if left:
                losses.append(Diagnostic("I_WINDING_FLIPPED", "info", path, "Left-handed faces reversed to glTF winding.", "No action needed."))
            varying = _time_varying(prim, skinned[1] if skinned is not None else None)
            if varying:
                losses.append(skinning.warning("W_POINTS_ANIMATION_DROPPED", path,
                                               f"Dropped the animation of {', '.join(varying)}; the earliest value is used."))
            points = [conversion.point(tuple(map(float, p))) for p in mesh.GetPointsAttr().Get(_EARLIEST) or ()]
            if points:
                tokens, keys, offsets, inbetweens = _blend_shapes(prim, points, path)
                if inbetweens:
                    losses.append(skinning.warning("W_INBETWEENS_DROPPED", path,
                                           f"Dropped {skinning.count(inbetweens, 'in-between shape', 'in-between shapes')}; the main shapes are kept."))
                offsets = [tuple(conversion.point(o) for o in target) for target in offsets]
                flip = left
                if skinned is not None:
                    # Skinning ignores the mesh's own transform; geomBindTransform carries the points into skeleton space.
                    baked = _checked(skinned[1].GetGeomBindTransform(_EARLIEST), path, conversion)
                if baked is not None:
                    points = [_apply(baked, p) for p in points]
                    offsets = [tuple(_apply(baked[:12] + [0.0, 0.0, 0.0, 1.0], o) for o in target) for target in offsets]
                    flip = flip != (transforms.determinant(baked) < 0)
                influences = None
                if skinned is not None:
                    influences, found_losses = _influences(skinned[1], skeletons[skinned[0]], len(points), path, options["influences"])
                    losses += found_losses
                    skin_index = skin_of[skinned[0]]
                if tokens and animation and animation.GetBlendShapeOrder():
                    weighted[i] = (animation, tokens)
                    static_weights = _blend_weights(animation, tokens, _EARLIEST)
                    if not any(static_weights):
                        static_weights = None
                mesh_index = len(meshes)
                meshes.append(glb.Mesh(points=tuple(points), triangles=tuple(_triangles(mesh, path, flip, skipped)),
                                       targets=tuple(offsets), influences=influences))
                target_keys.append(tuple(keys))
        trs = _trs(local, path) if local is not None else {}
        nodes.append(glb.Node(name=prim.GetName(), children=tuple(children[i]), mesh=mesh_index, skin=skin_index,
                              weights=static_weights, **trs))
    skins = [glb.Skin(joints=tuple(index[p] for p in skeletons[path].paths), inverse_bind_matrices=tuple(skeletons[path].inverse_binds))
             for path in skin_of]
    animations, time_losses = _animate(stage, entries, skeletons, weighted, conversion)
    try:
        raw = glb.write_glb(tuple(nodes), tuple(meshes), tuple(skins), animations, generator=f"{adapter.name} {adapter.version}")
    except ValueError as exc:
        fail("E_SOURCE_VALUE", "/", str(exc))
    return Generated(glb=raw, node_paths=tuple(entry[0] for entry in entries), target_keys=tuple(target_keys),
                     dependencies=dependencies, losses=tuple(conversion.losses + time_losses + losses + _skipped(skipped)))


ADAPTER = UsdAdapter()
