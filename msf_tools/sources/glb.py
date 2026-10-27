# SPDX-License-Identifier: MIT
"""Deterministic GLB writer shared by source adapters.

Each source point becomes exactly one glTF vertex and triangle indices refer to
points, because the reference evaluator reads POSITION only; splitting corners
for normals or texture coordinates would multiply vertex and morph work.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from ..common import canonical_json

_FLOAT = struct.Struct("<f")


@dataclass(frozen=True)
class Mesh:
    """One primitive. `targets` holds one offset per point per morph target;
    `influences` holds one sequence of (joint, weight) pairs per point."""
    points: tuple
    triangles: tuple = ()
    targets: tuple = ()
    influences: tuple | None = None
    weights: tuple = ()


@dataclass(frozen=True)
class Node:
    name: str | None = None
    children: tuple = ()
    translation: tuple = (0.0, 0.0, 0.0)
    rotation: tuple = (0.0, 0.0, 0.0, 1.0)
    scale: tuple = (1.0, 1.0, 1.0)
    mesh: int | None = None
    skin: int | None = None
    weights: tuple | None = None


@dataclass(frozen=True)
class Skin:
    """`inverse_bind_matrices` are 16 floats each, column-major as in glTF."""
    joints: tuple
    inverse_bind_matrices: tuple
    skeleton: int | None = None


@dataclass(frozen=True)
class Channel:
    """One sampler and channel. `values` holds one row per time: 3 numbers for
    translation and scale, an xyzw quaternion for rotation, or one weight per
    morph target of the node's mesh for weights."""
    node: int
    path: str
    times: tuple
    values: tuple
    interpolation: str = "LINEAR"


@dataclass(frozen=True)
class Animation:
    channels: tuple
    name: str | None = None


def _f32(value):
    if not math.isfinite(value):
        raise ValueError("Source data contains a non-finite number.")
    rounded = _FLOAT.unpack(_FLOAT.pack(value))[0]
    if not math.isfinite(rounded):
        raise ValueError("Source value overflows binary32.")
    return rounded


def _vectors(rows, size, what):
    out = []
    for row in rows:
        if len(row) != size:
            raise ValueError(f"{what} needs {size} components per element.")
        out.append(tuple(_f32(float(x)) for x in row))
    return out


def _normalized(pairs):
    merged = {}
    for joint, weight in pairs:
        if type(joint) is not int or joint < 0 or not math.isfinite(weight) or weight < 0:
            raise ValueError("Influences need nonnegative joint indices and finite nonnegative weights.")
        merged[joint] = merged.get(joint, 0.0) + weight
    positive = sorted((j, w) for j, w in merged.items() if w > 0)
    total = math.fsum(w for _, w in positive)
    if not positive or not math.isfinite(total):
        raise ValueError("Every skinned point needs a positive finite weight.")
    weights = [_f32(w / total) for _, w in positive]
    # Fold the binary32 rounding residual into the largest weight (lower joint on ties).
    largest = max(range(len(weights)), key=lambda i: (weights[i], -positive[i][0]))
    weights[largest] = _f32(weights[largest] + (1.0 - math.fsum(weights)))
    return [(j, w) for (j, _), w in zip(positive, weights)]


class _Buffer:
    def __init__(self):
        self.data = bytearray()
        self.views = []
        self.accessors = []

    def view(self, payload):
        while len(self.data) % 4:
            self.data.append(0)
        self.views.append({"buffer": 0, "byteOffset": len(self.data), "byteLength": len(payload)})
        self.data.extend(payload)
        return len(self.views) - 1

    def accessor(self, **fields):
        self.accessors.append(fields)
        return len(self.accessors) - 1

    def vec3(self, rows):
        bounds = {"min": [min(r[k] for r in rows) for k in range(3)], "max": [max(r[k] for r in rows) for k in range(3)]}
        view = self.view(b"".join(struct.pack("<3f", *r) for r in rows))
        return self.accessor(bufferView=view, componentType=5126, type="VEC3", count=len(rows), **bounds)

    def target(self, offsets):
        nonzero = [i for i, r in enumerate(offsets) if any(r)]
        bounds = {"min": [min(r[k] for r in offsets) for k in range(3)], "max": [max(r[k] for r in offsets) for k in range(3)]}
        if not nonzero:
            return self.accessor(componentType=5126, type="VEC3", count=len(offsets), **bounds)
        # Sparse entries cost 16 bytes against 12 dense; two thirds keeps a margin.
        if 3 * len(nonzero) > 2 * len(offsets):
            return self.vec3(offsets)
        indices = self.view(struct.pack(f"<{len(nonzero)}I", *nonzero))
        values = self.view(b"".join(struct.pack("<3f", *offsets[i]) for i in nonzero))
        sparse = {"count": len(nonzero), "indices": {"bufferView": indices, "componentType": 5125},
                  "values": {"bufferView": values}}
        return self.accessor(componentType=5126, type="VEC3", count=len(offsets), sparse=sparse, **bounds)


def _primitive(buffer, mesh):
    points = _vectors(mesh.points, 3, "Points")
    if not points:
        raise ValueError("Mesh needs at least one point.")
    primitive = {"attributes": {"POSITION": buffer.vec3(points)}}
    triangles = list(mesh.triangles)
    if triangles:
        if len(triangles) % 3 or any(type(i) is not int or not 0 <= i < len(points) for i in triangles):
            raise ValueError("Triangles must be point-index triples within the mesh.")
        wide = len(points) >= 65535
        view = buffer.view(struct.pack(f"<{len(triangles)}{'I' if wide else 'H'}", *triangles))
        primitive["indices"] = buffer.accessor(bufferView=view, componentType=5125 if wide else 5123,
                                               type="SCALAR", count=len(triangles))
    else:
        primitive["mode"] = 0
    if mesh.influences is not None:
        if len(mesh.influences) != len(points):
            raise ValueError("Influences need one entry per point.")
        rows = [_normalized(pairs) for pairs in mesh.influences]
        if max(j for row in rows for j, _ in row) > 65535:
            raise ValueError("Joint indices must fit unsigned 16-bit storage.")
        for s in range((max(len(row) for row in rows) + 3) // 4):
            chunk = [row[4 * s:4 * s + 4] + [(0, 0.0)] * (4 - len(row[4 * s:4 * s + 4])) for row in rows]
            joints = buffer.view(b"".join(struct.pack("<4H", *(j for j, _ in r)) for r in chunk))
            weights = buffer.view(b"".join(struct.pack("<4f", *(w for _, w in r)) for r in chunk))
            primitive["attributes"][f"JOINTS_{s}"] = buffer.accessor(bufferView=joints, componentType=5123, type="VEC4", count=len(rows))
            primitive["attributes"][f"WEIGHTS_{s}"] = buffer.accessor(bufferView=weights, componentType=5126, type="VEC4", count=len(rows))
    if mesh.targets:
        targets = [_vectors(t, 3, "Morph offsets") for t in mesh.targets]
        if any(len(t) != len(points) for t in targets):
            raise ValueError("Morph targets need one offset per point.")
        primitive["targets"] = [{"POSITION": buffer.target(t)} for t in targets]
    return primitive


_WIDTH = {"translation": 3, "rotation": 4, "scale": 3}


def _animation(buffer, animation, nodes, meshes, inputs):
    samplers, channels = [], []
    for channel in animation.channels:
        if type(channel.node) is not int or not 0 <= channel.node < len(nodes):
            raise ValueError("Animation channels must target a node.")
        if channel.interpolation not in ("LINEAR", "STEP"):
            raise ValueError("Animation interpolation must be LINEAR or STEP.")
        if channel.path == "weights":
            mesh = nodes[channel.node].mesh
            width = len(meshes[mesh].targets) if mesh is not None else 0
            if not width:
                raise ValueError("Weight channels need a node whose mesh has morph targets.")
        elif channel.path in _WIDTH:
            width = _WIDTH[channel.path]
        else:
            raise ValueError("Animation path must be translation, rotation, scale or weights.")
        times = tuple(_f32(float(t)) for t in channel.times)
        if not times or times[0] < 0 or any(a >= b for a, b in zip(times, times[1:])):
            raise ValueError("Animation times must be nonnegative and strictly increasing in binary32.")
        values = _vectors(channel.values, width, f"Animation {channel.path} values")
        if len(values) != len(times):
            raise ValueError("Animation channels need one value row per time.")
        if times not in inputs:
            view = buffer.view(struct.pack(f"<{len(times)}f", *times))
            inputs[times] = buffer.accessor(bufferView=view, componentType=5126, type="SCALAR", count=len(times),
                                            min=[times[0]], max=[times[-1]])
        flat = [x for row in values for x in row]
        view = buffer.view(struct.pack(f"<{len(flat)}f", *flat))
        scalar = channel.path == "weights"
        output = buffer.accessor(bufferView=view, componentType=5126, count=len(flat) if scalar else len(values),
                                 type="SCALAR" if scalar else f"VEC{width}")
        samplers.append({"input": inputs[times], "output": output, "interpolation": channel.interpolation})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": channel.node, "path": channel.path}})
    row = {"samplers": samplers, "channels": channels}
    if animation.name is not None:
        row["name"] = animation.name
    return row


def write_glb(nodes, meshes, skins=(), animations=(), *, generator):
    """Return GLB bytes for nodes, meshes and skins given in final glTF index order."""
    buffer = _Buffer()
    gltf_meshes = []
    for mesh in meshes:
        row = {"primitives": [_primitive(buffer, mesh)]}
        if mesh.weights:
            if len(mesh.weights) != len(mesh.targets):
                raise ValueError("Default morph weights need one value per target.")
            row["weights"] = [float(w) for w in mesh.weights]
        gltf_meshes.append(row)
    gltf_skins = []
    for skin in skins:
        matrices = _vectors(skin.inverse_bind_matrices, 16, "Inverse bind matrices")
        if len(matrices) != len(skin.joints):
            raise ValueError("Skins need one inverse bind matrix per joint.")
        view = buffer.view(b"".join(struct.pack("<16f", *r) for r in matrices))
        row = {"joints": list(skin.joints),
               "inverseBindMatrices": buffer.accessor(bufferView=view, componentType=5126, type="MAT4", count=len(matrices))}
        if skin.skeleton is not None:
            row["skeleton"] = skin.skeleton
        gltf_skins.append(row)
    gltf_nodes, children = [], set()
    for node in nodes:
        row = {}
        if node.name is not None:
            row["name"] = node.name
        if node.children:
            row["children"] = sorted(node.children)
            children.update(node.children)
        for field, default in (("translation", (0.0, 0.0, 0.0)), ("rotation", (0.0, 0.0, 0.0, 1.0)), ("scale", (1.0, 1.0, 1.0))):
            value = tuple(float(x) for x in getattr(node, field))
            if any(not math.isfinite(x) for x in value):
                raise ValueError("Node transforms must be finite.")
            if value != default:
                row[field] = list(value)
        for field in ("mesh", "skin"):
            if getattr(node, field) is not None:
                row[field] = getattr(node, field)
        if node.weights is not None:
            row["weights"] = [float(w) for w in node.weights]
        gltf_nodes.append(row)
    inputs = {}
    gltf_animations = [_animation(buffer, animation, nodes, meshes, inputs) for animation in animations]
    document = {"asset": {"version": "2.0", "generator": generator}, "scene": 0,
                "scenes": [{"nodes": [i for i in range(len(gltf_nodes)) if i not in children]}],
                "nodes": gltf_nodes, "meshes": gltf_meshes, "accessors": buffer.accessors}
    if gltf_skins:
        document["skins"] = gltf_skins
    if gltf_animations:
        document["animations"] = gltf_animations
    if buffer.data:
        while len(buffer.data) % 4:
            buffer.data.append(0)
        document["buffers"] = [{"byteLength": len(buffer.data)}]
        document["bufferViews"] = buffer.views
    text = canonical_json(document)
    text += b" " * (-len(text) % 4)
    chunks = struct.pack("<II", len(text), 0x4E4F534A) + text
    if buffer.data:
        chunks += struct.pack("<II", len(buffer.data), 0x004E4942) + bytes(buffer.data)
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks
