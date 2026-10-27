# SPDX-License-Identifier: MIT
"""USD adapter built on usd-core (`pxr`). Importing this module fails when pxr is absent."""
from __future__ import annotations

from pathlib import Path
import tempfile

from pxr import Sdf, Tf, Usd, UsdGeom, UsdSkel

from ..report import fail
from . import Generated, SourceParseError
from . import glb, paths, transforms

_EARLIEST = Usd.TimeCode.EarliestTime()


def _node_path(prim):
    return paths.node_path([(name, None) for name in str(prim.GetPath()).split("/")[1:]])


def _matrix(gf):
    return [float(gf[r][c]) for r in range(4) for c in range(4)]


def _trs(prim, path):
    if not prim.IsA(UsdGeom.Xformable):
        return {}
    matrix = _matrix(UsdGeom.Xformable(prim).GetLocalTransformation(_EARLIEST))
    if not transforms.is_affine(matrix):
        fail("E_SOURCE_VALUE", path, "Transform is not affine.")
    if transforms.has_shear(matrix):
        fail("E_SHEAR_UNSUPPORTED", path, "Transform has shear, which glTF TRS cannot represent.")
    try:
        translation, rotation, scale = transforms.decompose(matrix)
    except ValueError:
        fail("E_SOURCE_VALUE", path, "Transform is singular.")
    return {"translation": translation, "rotation": rotation, "scale": scale}


def _triangles(mesh, path):
    counts = list(mesh.GetFaceVertexCountsAttr().Get(_EARLIEST) or ())
    indices = list(mesh.GetFaceVertexIndicesAttr().Get(_EARLIEST) or ())
    if sum(counts) != len(indices) or any(c < 0 for c in counts):
        fail("E_SOURCE_VALUE", path, "Face vertex counts and indices disagree.")
    triangles, start = [], 0
    for count in counts:
        face = indices[start:start + count]
        start += count
        for k in range(1, count - 1):
            triangles += [face[0], face[k], face[k + 1]]
    return triangles


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
            root = Path(tmp) / f"root.{fmt}"
            root.write_bytes(data)
            try:
                layer = Sdf.Layer.FindOrOpen(str(root))
                if layer is None:
                    raise SourceParseError("usd-core could not open the source layer.")
                if layer.GetCompositionAssetDependencies():
                    fail("E_SOURCE_REFERENCE", "/", "Layers with sublayers, references or payloads are not supported yet.")
                stage = Usd.Stage.Open(layer)
            except Tf.ErrorException as exc:
                raise SourceParseError(str(exc).strip()) from None
            try:
                return _convert(stage, self)
            finally:
                del stage


def _convert(stage, adapter):
    prims = [p for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
             if p != stage.GetPseudoRoot() and (p.IsA(UsdGeom.Xformable) or p.IsA(UsdGeom.Scope))]
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
    nodes, meshes, target_keys = [], [], []
    for i, prim in enumerate(prims):
        path = _node_path(prim)
        mesh_index = None
        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            points = [tuple(map(float, p)) for p in mesh.GetPointsAttr().Get(_EARLIEST) or ()]
            if points:
                keys, offsets = _blend_shapes(prim, points, path)
                mesh_index = len(meshes)
                meshes.append(glb.Mesh(points=tuple(points), triangles=tuple(_triangles(mesh, path)), targets=tuple(offsets)))
                target_keys.append(tuple(keys))
        nodes.append(glb.Node(name=prim.GetName(), children=tuple(children[i]), mesh=mesh_index, **_trs(prim, path)))
    try:
        raw = glb.write_glb(tuple(nodes), tuple(meshes), generator=f"{adapter.name} {adapter.version}")
    except ValueError as exc:
        fail("E_SOURCE_VALUE", "/", str(exc))
    return Generated(glb=raw, node_paths=tuple(_node_path(p) for p in prims), target_keys=tuple(target_keys),
                     dependencies=(), losses=())


ADAPTER = UsdAdapter()
