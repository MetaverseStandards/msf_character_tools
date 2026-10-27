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
from . import glb, paths, transforms

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


def _skipped(counts):
    parts = [f"{n} {kind}" for kind, n in sorted(counts.items()) if kind not in ("hole face", "external asset dependency") and n]
    for kind in ("hole face", "external asset dependency"):
        if counts[kind]:
            plural = {"hole face": "hole faces", "external asset dependency": "external asset dependencies"}[kind]
            parts.append(f"{counts[kind]} {kind if counts[kind] == 1 else plural}")
    if not parts:
        return []
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return [Diagnostic("W_SKIPPED", "warning", "/", f"Skipped {text}.", "Review the declared loss.")]


def _blend_shapes(prim, points, path):
    binding = UsdSkel.BindingAPI(prim)
    tokens = list(binding.GetBlendShapesAttr().Get() or ())
    targets = list(binding.GetBlendShapeTargetsRel().GetTargets()) if tokens else []
    if len(tokens) != len(targets):
        fail("E_SOURCE_VALUE", path, "skel:blendShapes and skel:blendShapeTargets have different lengths.")
    keys, offsets = [], []
    for token, target in zip(tokens, targets):
        shape = UsdSkel.BlendShape(prim.GetStage().GetPrimAtPath(target))
        if not shape:
            fail("E_SOURCE_VALUE", path, f"Blend shape target {target} is not a BlendShape.")
        values = [tuple(map(float, v)) for v in shape.GetOffsetsAttr().Get() or ()]
        indices = shape.GetPointIndicesAttr().Get()
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
    return keys, offsets


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
                return _convert(stage, self, dependencies, external)
            finally:
                del stage


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
    """Resolve an authored layer path against the layer that names it, or refuse it."""
    if not asset.startswith(("./", "../")) or "\\" in asset or "://" in asset:
        fail("E_SOURCE_REFERENCE", "/", f"Layer path @{asset}@ is not a ./ or ../ relative path.",
             "Author layer references as paths relative to the referring layer.")
    anchored = posixpath.normpath(posixpath.join(posixpath.dirname(base), asset))
    if anchored == ".." or anchored.startswith("../") or anchored.startswith("/"):
        fail("E_SOURCE_REFERENCE", "/", f"Layer path @{asset}@ escapes the source root.")
    return anchored


def _refuse_clips(layer):
    # Value clips name layers that usd-core opens lazily, outside the closure checked here.
    clipped = []
    layer.Traverse("/", lambda path: clipped.append(path) if path.IsPrimPath() and any(
        layer.GetPrimAtPath(path).HasInfo(key) for key in ("clips", "clipSets")) else None)
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


def _convert(stage, adapter, dependencies, external):
    conversion = _Conversion(stage)
    skipped = Counter({"external asset dependency": external})
    every = [p for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()) if p != stage.GetPseudoRoot()]
    for prim in every:
        kind = _skipped_kind(prim)
        if kind:
            skipped[kind] += 1
    prims = [p for p in every if p.IsA(UsdGeom.Xformable) or p.IsA(UsdGeom.Scope)]
    order = sorted(range(len(prims)), key=lambda i: paths.sort_key(_node_path(prims[i])))
    prims = [prims[i] for i in order]
    index = {p.GetPath(): i for i, p in enumerate(prims)}
    children = {i: [] for i in range(len(prims))}
    for i, prim in enumerate(prims):
        if prim.IsA(UsdGeom.Xformable) and UsdGeom.Xformable(prim).GetResetXformStack():
            continue
        parent = prim.GetParent()
        while parent and parent.GetPath() not in index:
            parent = parent.GetParent()
        if parent:
            children[index[parent.GetPath()]].append(i)
    nodes, meshes, target_keys, losses = [], [], [], []
    for i, prim in enumerate(prims):
        path = _node_path(prim)
        local = _local(prim, path, conversion)
        baked = None
        if local is not None and transforms.has_shear(local):
            if (not prim.IsA(UsdGeom.Mesh) or children[i]
                    or UsdGeom.Xformable(prim).TransformMightBeTimeVarying()):
                _shear(path)
            baked, local = local, None
            losses.append(Diagnostic("W_SHEAR_BAKED", "warning", path, "Sheared transform baked into the mesh points.",
                                     "Review the declared loss."))
        elif local is not None and transforms.determinant(local) < 0:
            losses.append(Diagnostic("I_MIRRORED", "info", path, "Mirrored transform stored as a negative X scale.", "No action needed."))
        mesh_index = None
        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            if mesh.GetSubdivisionSchemeAttr().Get() != UsdGeom.Tokens.none:
                losses.append(Diagnostic("W_SUBDIV_CAGE", "warning", path, "Subdivision surface uses its control cage.",
                                         "Review the declared loss."))
            left = mesh.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded
            if left:
                losses.append(Diagnostic("I_WINDING_FLIPPED", "info", path, "Left-handed faces reversed to glTF winding.", "No action needed."))
            points = [conversion.point(tuple(map(float, p))) for p in mesh.GetPointsAttr().Get(_EARLIEST) or ()]
            if points:
                keys, offsets = _blend_shapes(prim, points, path)
                offsets = [tuple(conversion.point(o) for o in target) for target in offsets]
                flip = left
                if baked is not None:
                    points = [_apply(baked, p) for p in points]
                    offsets = [tuple(_apply(baked[:12] + [0.0, 0.0, 0.0, 1.0], o) for o in target) for target in offsets]
                    flip = flip != (transforms.determinant(baked) < 0)
                mesh_index = len(meshes)
                meshes.append(glb.Mesh(points=tuple(points), triangles=tuple(_triangles(mesh, path, flip, skipped)),
                                       targets=tuple(offsets)))
                target_keys.append(tuple(keys))
        trs = _trs(local, path) if local is not None else {}
        nodes.append(glb.Node(name=prim.GetName(), children=tuple(children[i]), mesh=mesh_index, **trs))
    try:
        raw = glb.write_glb(tuple(nodes), tuple(meshes), generator=f"{adapter.name} {adapter.version}")
    except ValueError as exc:
        fail("E_SOURCE_VALUE", "/", str(exc))
    return Generated(glb=raw, node_paths=tuple(_node_path(p) for p in prims), target_keys=tuple(target_keys),
                     dependencies=dependencies, losses=tuple(conversion.losses + losses + _skipped(skipped)))


ADAPTER = UsdAdapter()
