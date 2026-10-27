# SPDX-License-Identifier: MIT
"""FBX source adapter on ufbx 0.23.1, through the msf-tools-ufbx shim.

ufbx loads the file from memory already in metres and right-handed +Y up,
applies geometric transforms to the points, compensates inherit modes and
moves pivots into the node matrices (adding helper nodes where it must).
Static and animated node TRS both come from ufbx's node-to-parent matrices.
"""
from __future__ import annotations

from array import array
import math

from msf_tools_ufbx import ffi, lib

from . import ReaderMismatch

SHIM_ABI = 4
# A stale build would still load, since cffi compiled it against its own declarations, and then fill fewer fields.
if getattr(lib, "msf_fbx_shim_abi", None) is None or lib.msf_fbx_shim_abi() != SHIM_ABI:
    raise ReaderMismatch(f"The installed msf-tools-ufbx does not match this msf-tools (it needs shim ABI {SHIM_ABI}).",
                         "Reinstall msf-tools-ufbx from this checkout: pip install ./native/ufbx")
_PACKED = lib.msf_fbx_ufbx_version()
UFBX_VERSION = f"{_PACKED // 1000000}.{_PACKED // 1000 % 1000}.{_PACKED % 1000}"

from ..report import Diagnostic, fail
from . import Generated, SourceParseError
from . import glb, paths, skinning, transforms

_HELPERS = {1: "geometry", 2: "scale"}
_METHODS = {0: None, 1: "rigid", 2: "dual quaternion", 3: "blended dual quaternion and linear"}
MAX_SAMPLES = 100_000


class FbxAdapter:
    name = "msf-ufbx"
    version = "1"
    formats = ("fbx",)

    def reader(self):
        return "ufbx " + UFBX_VERSION

    def convert(self, data, fmt, resolver, limits, options):
        limit = ffi.new("msf_fbx_limits *", {"memory_limit": limits.max_reader_memory, "allocation_limit": 0})
        out, err = ffi.new("msf_fbx **"), ffi.new("char[1024]")
        if not lib.msf_fbx_open(ffi.from_buffer(data), len(data), limit, out, err, 1024):
            message = ffi.string(err).decode("utf-8", "replace").strip()
            if "memory limit" in message.lower():
                fail("E_SOURCE_MEMORY", "/", f"The FBX reader went over max_reader_memory: {message[:400]}",
                     "Raise limits.max_reader_memory, or reduce the source.")
            raise SourceParseError(message or "ufbx could not read the file.")
        try:
            return _Scene(out[0], options, limits).convert(self)
        finally:
            lib.msf_fbx_close(out[0])


def _matrix(values):
    return [float(x) for x in values]


def _near(row, rest):
    return all(abs(x - y) <= 1e-6 * max(1.0, abs(y)) for x, y in zip(row, rest))


def _trs(matrix, path):
    if not all(math.isfinite(x) for x in matrix):
        fail("E_SOURCE_VALUE", path, "Transform has a non-finite number.")
    try:
        translation, rotation, scale = transforms.decompose(matrix)
    except ValueError:
        fail("E_SOURCE_VALUE", path, "Transform is singular.")
    return {"translation": translation, "rotation": rotation, "scale": scale}


def _shear(path):
    fail("E_SHEAR_UNSUPPORTED", path, "Transform has shear, which glTF TRS cannot represent.",
         "Remove the shear, or keep it only on static unskinned leaf meshes, where it is baked into the points.")


def _apply(m, p):
    return tuple(math.fsum(m[4 * c + r] * p[c] for c in range(3)) + m[12 + r] for r in range(3))


def _quaternions(rows):
    out = [rows[0]]
    for q in rows[1:]:
        out.append(q if math.fsum(a * b for a, b in zip(out[-1], q)) >= 0 else tuple(-x for x in q))
    return out


class _Scene:
    def __init__(self, handle, options, limits):
        self.h, self.options, self.limits = handle, options, limits
        self.info = ffi.new("msf_fbx_info *")
        lib.msf_fbx_info_get(handle, self.info)
        self.nodes = []
        for i in range(self.info.nodes):
            node = ffi.new("msf_fbx_node *")
            if not lib.msf_fbx_node_get(handle, i, node):
                fail("E_SOURCE_VALUE", "/", "The FBX reader could not report a node.")
            self.nodes.append({"parent": node.parent, "name": ffi.unpack(node.name, node.name_len).decode("utf-8", "replace"),
                               "mesh": node.mesh, "helper": node.helper, "pivots": node.pivots,
                               "to_parent": _matrix(node.to_parent),
                               "skipped": ffi.string(node.skipped).decode() if node.skipped != ffi.NULL else None})
        self.losses, self.skipped = [], {"empty mesh": 0, "hole face": 0, "point or line face": 0}
        sizes = ffi.new("uint32_t[8]")
        self.empty = {m for m in range(self.info.meshes) if lib.msf_fbx_mesh_sizes(self.h, m, sizes) and sizes[0] == 0}
        self.skipped["empty mesh"] = len(self.empty)

    def paths(self):
        """Node paths per the path-sorted-v2 grammar: escaped names, [k] for duplicate siblings, helper suffixes."""
        logical = [self._logical_parent(i) for i in range(len(self.nodes))]
        groups = {}
        for i, node in enumerate(self.nodes):
            if not node["helper"]:
                groups.setdefault((logical[i], node["name"]), []).append(i)
        component = {}
        for members in groups.values():
            for k, i in enumerate(members):
                component[i] = (self.nodes[i]["name"], k if len(members) > 1 else None)
        helpers = {}
        out = [None] * len(self.nodes)

        def chain(i):
            parts = []
            while i >= 0:
                parts.append(component[i])
                i = logical[i]
            return parts[::-1]
        for i, node in enumerate(self.nodes):
            if node["helper"]:
                owner = self._logical_parent(i)  # a helper can sit under another helper of the same owner
                kind = _HELPERS[node["helper"]]
                k = helpers.setdefault((owner, kind), 0)
                helpers[(owner, kind)] += 1
                out[i] = (owner, kind, k)
            else:
                out[i] = paths.node_path(chain(i))
        for i, value in enumerate(out):
            if isinstance(value, tuple):
                owner, kind, k = value
                many = sum(1 for o, kd, _ in (v for v in out if isinstance(v, tuple)) if o == owner and kd == kind) > 1
                out[i] = paths.node_path(chain(owner), helper=(kind, k if many else None))
        return out

    def _logical_parent(self, i):
        parent = self.nodes[i]["parent"]
        while parent >= 0 and self.nodes[parent]["helper"]:
            parent = self.nodes[parent]["parent"]
        return parent

    def convert(self, adapter):
        info = self.info
        conversion = []
        if info.unit_meters > 0 and info.unit_meters != 1.0:  # ufbx leaves a nonpositive unit unconverted
            conversion.append(Diagnostic("I_UNITS_CONVERTED", "info", "/", f"Converted {info.unit_meters:g} metres per unit to metres.",
                                         "No action needed."))
        if info.axes_converted:
            conversion.append(Diagnostic("I_AXES_CONVERTED", "info", "/", "Converted the file's axes to right-handed +Y up.",
                                         "No action needed."))
        if any(n["pivots"] for n in self.nodes):
            conversion.append(Diagnostic("I_PIVOTS_BAKED", "info", "/", "Pivots, offsets and pre/post rotations are baked into node TRS.",
                                         "No action needed."))
        if info.helper_nodes:
            conversion.append(skinning.warning("W_HELPER_NODES", "/", f"The reader added {skinning.count(info.helper_nodes, 'helper node', 'helper nodes')} "
                                               "for geometric transforms or inherited scale it could not fold into the nodes."))
        node_paths = self.paths()
        order = sorted(range(len(self.nodes)), key=lambda i: paths.sort_key(node_paths[i]))
        index = {shim: k for k, shim in enumerate(order)}
        children = {k: [] for k in range(len(order))}
        for shim, node in enumerate(self.nodes):
            if node["parent"] >= 0:
                children[index[node["parent"]]].append(index[shim])
        animation, time_losses, animated = self.animation(order, node_paths)
        meshes, mesh_of_shim, skins, target_keys = self.meshes(order, node_paths, index, animated)
        nodes = []
        for k, shim in enumerate(order):
            node, path = self.nodes[shim], node_paths[shim]
            matrix = node["to_parent"]
            trs = {}
            if transforms.has_shear(matrix):
                if shim not in self.baked:
                    _shear(path)
            else:
                trs = _trs(matrix, path)
                if transforms.determinant(matrix) < 0:
                    self.losses.append(Diagnostic("I_MIRRORED", "info", path, "Mirrored transform stored as a negative X scale.",
                                                  "No action needed."))
            mesh, skin = mesh_of_shim.get(shim, (None, None))
            weights = meshes[mesh].weights if mesh is not None and any(meshes[mesh].weights) else None
            nodes.append(glb.Node(name=None if node["helper"] else node["name"], children=tuple(children[k]), mesh=mesh, skin=skin, weights=weights, **trs))
        kinds = {}
        for node in self.nodes:
            if node["skipped"]:
                kinds[node["skipped"]] = kinds.get(node["skipped"], 0) + 1
        kinds.update({"material": info.materials, "texture": info.textures})
        kinds.update(self.skipped)
        parts = [f"{n} {kind}{'' if n == 1 else 'es' if kind.endswith(('h', 'x')) else 's'}" for kind, n in kinds.items() if n]
        if parts:
            text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
            self.losses.append(skinning.warning("W_SKIPPED", "/", f"Skipped {text}."))
        try:
            raw = glb.write_glb(tuple(nodes), tuple(meshes), tuple(skins), animation, generator=f"{adapter.name} {adapter.version}")
        except ValueError as exc:
            fail("E_SOURCE_VALUE", "/", str(exc))
        return Generated(glb=raw, node_paths=tuple(node_paths[shim] for shim in order), target_keys=tuple(target_keys),
                         dependencies=(), losses=tuple(conversion + time_losses + self.losses))

    def meshes(self, order, node_paths, index, animated):
        """glTF meshes in node order (one per ufbx mesh, shared by its instances), skins and target keys."""
        self.baked = set()
        meshes, mesh_index, mesh_of_shim, skins, target_keys = [], {}, {}, [], []
        for shim in order:
            node = self.nodes[shim]
            m = node["mesh"]
            if m < 0 or m in self.empty:
                continue
            path = node_paths[shim]
            if m not in mesh_index:
                mesh, keys, skin = self.mesh(m, shim, path, index)
                bake = transforms.has_shear(node["to_parent"])
                if bake:
                    leaf = not any(n["parent"] == shim for n in self.nodes)
                    if not leaf or skin is not None or shim in animated:
                        _shear(path)
                    self.baked.add(shim)
                    linear = node["to_parent"][:12] + [0.0, 0.0, 0.0, 1.0]
                    mesh = glb.Mesh(points=tuple(_apply(node["to_parent"], p) for p in mesh.points), triangles=mesh.triangles,
                                    targets=tuple(tuple(_apply(linear, o) for o in t) for t in mesh.targets),
                                    influences=mesh.influences, weights=mesh.weights)
                    self.losses.append(skinning.warning("W_SHEAR_BAKED", path, "Sheared transform baked into the mesh points."))
                skin_index = None
                if skin is not None:
                    skin_index = len(skins)
                    skins.append(skin)
                mesh_index[m] = (len(meshes), skin_index)
                meshes.append(mesh)
                target_keys.append(keys)
            elif transforms.has_shear(node["to_parent"]):
                _shear(path)
            mesh_of_shim[shim] = mesh_index[m]
        return meshes, mesh_of_shim, skins, target_keys

    def mesh(self, m, shim, path, index):
        sizes = ffi.new("uint32_t[8]")
        if not lib.msf_fbx_mesh_sizes(self.h, m, sizes):
            fail("E_SOURCE_VALUE", path, "The FBX reader could not report a mesh.")
        points, triangles = sizes[0], sizes[1]
        self.skipped["hole face"] += sizes[2]
        self.skipped["point or line face"] += sizes[3]
        if sizes[7]:
            self.losses.append(skinning.warning("W_SUBDIV_CAGE", path, "Subdivision surface uses its control cage."))
        if sizes[6]:
            self.losses.append(skinning.warning("W_POINTS_ANIMATION_DROPPED", path,
                                                "Dropped the vertex cache animation; the mesh's own points are used."))
        positions = ffi.new("double[]", 3 * points or 1)
        tri = ffi.new("uint32_t[]", 3 * triangles or 1)
        if not lib.msf_fbx_mesh_fill(self.h, m, positions, points, tri, triangles):
            fail("E_SOURCE_VALUE", path, "The FBX reader could not fill a mesh.")
        coords = [tuple(positions[3 * v:3 * v + 3]) for v in range(points)]
        keys, offsets, weights = self.blend(m, sizes[5], points, path)
        influences, skin = None, None
        if sizes[4] > 1:
            fail("E_SOURCE_VALUE", path, "A mesh with more than one skin deformer is not supported.")
        if sizes[4] == 1:
            influences, skin = self.skin(m, shim, points, path, index)
        mesh = glb.Mesh(points=tuple(coords), triangles=tuple(tri[0:3 * triangles]), targets=tuple(offsets),
                        influences=influences, weights=tuple(weights) if offsets else ())
        return mesh, tuple(keys), skin

    def skin(self, m, shim, points, path, index):
        sizes = ffi.new("uint32_t[2]")
        lib.msf_fbx_skin_sizes(self.h, m, 0, sizes)
        clusters, entries = sizes[0], sizes[1]
        offsets, which = ffi.new("uint32_t[]", points + 1), ffi.new("uint32_t[]", entries or 1)
        weights, bones = ffi.new("double[]", entries or 1), ffi.new("int32_t[]", clusters or 1)
        binds, method = ffi.new("double[]", 16 * clusters or 1), ffi.new("int *")
        if not lib.msf_fbx_skin_fill(self.h, m, 0, offsets, points, which, weights, entries, bones, binds, clusters, method):
            fail("E_SOURCE_VALUE", path, "The FBX reader could not fill a skin.")
        slot_of_bone, joints, matrices, slot_of_cluster = {}, [], [], []
        for c in range(clusters):
            bone = bones[c]
            if bone < 0:
                fail("E_SOURCE_VALUE", path, "A skin cluster has no bone node.")
            matrix = _matrix(binds[16 * c:16 * c + 16])
            if bone in slot_of_bone:
                if matrices[slot_of_bone[bone]] != matrix:
                    fail("E_SOURCE_VALUE", path, "Two skin clusters bind the same bone differently.")
            else:
                slot_of_bone[bone] = len(joints)
                joints.append(bone)
                matrices.append(matrix)
            slot_of_cluster.append(slot_of_bone[bone])
        merged_rows = [skinning.merge(((slot_of_cluster[which[k]], float(weights[k])) for k in range(offsets[v], offsets[v + 1])), path)
                       for v in range(points)]
        root = self._unweighted_slot(shim, slot_of_bone)
        rows, losses = skinning.influence_rows(merged_rows, root, self.options["influences"], path,
                                               "the nearest ancestor joint of the mesh, or the skeleton root")
        self.losses += losses
        if _METHODS.get(method[0], "unknown"):
            self.losses.append(skinning.method_loss(path, _METHODS.get(method[0], "unknown")))
        skin = glb.Skin(joints=tuple(index[b] for b in joints), inverse_bind_matrices=tuple(matrices))
        return rows, skin

    def _unweighted_slot(self, shim, slot_of_bone):
        parent = self.nodes[shim]["parent"]
        while parent >= 0:
            if parent in slot_of_bone:
                return slot_of_bone[parent]
            parent = self.nodes[parent]["parent"]
        for bone, slot in sorted(slot_of_bone.items(), key=lambda item: item[1]):
            ancestor = self.nodes[bone]["parent"]
            while ancestor >= 0 and ancestor not in slot_of_bone:
                ancestor = self.nodes[ancestor]["parent"]
            if ancestor < 0:
                return slot
        return 0

    def channel(self, m, c, path):
        """Blend channel c of mesh m: (deformer index, deformer name, channel name, keyframes, static weight)."""
        sizes = ffi.new("uint32_t[2]")
        lib.msf_fbx_blend_sizes(self.h, m, c, sizes)
        keyframes, total = sizes[0], sizes[1]
        deformer, counts = ffi.new("uint32_t *"), ffi.new("uint32_t[]", keyframes or 1)
        indices, values = ffi.new("uint32_t[]", total or 1), ffi.new("double[]", 3 * total or 1)
        targets, weight = ffi.new("double[]", keyframes or 1), ffi.new("double *")
        name_ptrs, name_lens = ffi.new("const char *[2]"), ffi.new("size_t[2]")
        if not lib.msf_fbx_blend_fill(self.h, m, c, deformer, counts, indices, values, targets, keyframes, total,
                                      weight, name_ptrs, name_lens):
            fail("E_SOURCE_VALUE", path, "The FBX reader could not fill a blend channel.")
        start, frames = 0, []
        for k in range(keyframes):
            frames.append((float(targets[k]), [(indices[start + i], tuple(values[3 * (start + i):3 * (start + i) + 3]))
                                              for i in range(counts[k])]))
            start += counts[k]
        return (deformer[0], *(ffi.unpack(name_ptrs[k], name_lens[k]).decode("utf-8", "replace") for k in range(2)),
                frames, float(weight[0]))

    def blend(self, m, channels, points, path):
        keys, offsets, weights = [], [], []
        dropped = partial = 0
        names = []
        for c in range(channels):
            deformer, deformer_name, channel_name, frames, weight = self.channel(m, c, path)
            names.append((deformer, deformer_name, channel_name))
            dense = [(0.0, 0.0, 0.0)] * points
            if frames:
                full = [f for f in frames if abs(f[0] - 1.0) < 1e-9]
                main = full[0] if full else max(frames, key=lambda f: f[0])
                scale = 1.0
                if not full:
                    if main[0] <= 0:
                        fail("E_SOURCE_VALUE", path, "A blend channel has no keyframe with a positive weight.")
                    partial += 1
                    scale = 1.0 / main[0]
                dropped += len(frames) - 1
                for i, o in main[1]:
                    if i >= points:
                        fail("E_SOURCE_VALUE", path, "A blend shape offset names a point the mesh does not have.")
                    dense[i] = tuple(x * scale for x in o)
            offsets.append(tuple(dense))
            weights.append(weight)
        deformer_names = {}
        for d, deformer_name, _ in names:
            deformer_names.setdefault(d, deformer_name)
        deformer_k = self._dedupe({d: n for d, n in deformer_names.items()})
        channel_groups = {}
        for c, (d, _, channel_name) in enumerate(names):
            channel_groups.setdefault((d, channel_name), []).append(c)
        for c, (d, _, channel_name) in enumerate(names):
            group = channel_groups[(d, channel_name)]
            k = group.index(c) if len(group) > 1 else None
            keys.append(paths.target_key([deformer_k[d], (channel_name, k)]))
        if dropped:
            self.losses.append(skinning.warning("W_INBETWEENS_DROPPED", path,
                                                f"Dropped {skinning.count(dropped, 'in-between shape', 'in-between shapes')}; the main shapes are kept."))
        if partial:
            self.losses.append(skinning.warning("W_INBETWEEN_PARTIAL", path,
                                                f"{skinning.count(partial, 'blend channel has', 'blend channels have')} no full-weight shape; "
                                                "the largest-weight shape is scaled up to full weight."))
        return keys, offsets, weights

    @staticmethod
    def _dedupe(names):
        """(name, k) components for {id: name}, with k only where names repeat, in id order."""
        groups = {}
        for d in sorted(names):
            groups.setdefault(names[d], []).append(d)
        return {d: (names[d], groups[names[d]].index(d) if len(groups[names[d]]) > 1 else None) for d in names}

    def animation(self, order, node_paths):
        """One glTF animation sampled from the chosen stack; returns (animations, losses, animated shim nodes)."""
        stacks = self.info.anim_stacks
        if not stacks:
            return (), [], set()
        losses = []
        choice = self.options.get("animation", 0)
        names = []
        for s in range(stacks):
            stack = ffi.new("msf_fbx_stack *")
            lib.msf_fbx_stack_get(self.h, s, stack)
            names.append((ffi.unpack(stack.name, stack.name_len).decode("utf-8", "replace"), stack.time_begin, stack.time_end))
        if isinstance(choice, str):
            found = [s for s, (name, _, _) in enumerate(names) if name == choice]
            if not found:
                fail("E_SOURCE_OPTIONS", "/options/animation", f"The file has no animation stack named {choice!r}.")
            chosen = found[0]
        else:
            if choice >= stacks:
                fail("E_SOURCE_OPTIONS", "/options/animation", f"The file has {stacks} animation stacks.")
            chosen = choice
        if stacks > 1:
            losses.append(skinning.warning("W_ANIMATIONS_SKIPPED", "/",
                                           f"Used animation stack {names[chosen][0]!r}; skipped {skinning.count(stacks - 1, 'other stack', 'other stacks')}."))
        _, begin, end = names[chosen]
        rate = self.options.get("sample_rate") or (self.info.fps if self.info.fps > 0 else 30.0)
        if not (math.isfinite(begin) and math.isfinite(end)) or end <= begin:
            return (), losses, set()
        count = int(math.floor((end - begin) * rate + 1e-9)) + 1
        times = [begin + k / rate for k in range(count)]
        if end - times[-1] > 1e-9:
            times.append(end)
        if len(times) > MAX_SAMPLES:
            fail("E_RESOURCE_LIMIT", "/", f"The animation needs {len(times)} samples, over the {MAX_SAMPLES} limit.",
                 "Lower options.sample_rate.")
        nodes, channels = len(self.nodes), self.info.blend_channels
        values = len(times) * (16 * nodes + channels)
        if values > self.limits.max_animation_values:
            fail("E_RESOURCE_LIMIT", "/", f"The animation needs {values} sampled values ({len(times)} samples of {nodes} nodes "
                 f"and {channels} blend channels), over the {self.limits.max_animation_values} limit.",
                 "Lower options.sample_rate, or raise limits.max_animation_values.")
        to_parent = ffi.new("double[]", 16 * nodes or 1)
        weights = ffi.new("double[]", channels or 1)
        err = ffi.new("char[512]")
        # One flat array of doubles per node: sample k's matrix is values 16k to 16k + 15.
        matrices = [array("d") for _ in range(nodes)]
        weight_values = array("d")
        for t in times:
            if not lib.msf_fbx_evaluate(self.h, chosen, t, to_parent, ffi.NULL, nodes, weights, channels, err, 512):
                fail("E_SOURCE_VALUE", "/", "The FBX reader could not evaluate the animation: "
                     + ffi.string(err).decode("utf-8", "replace")[:300])
            raw = ffi.buffer(to_parent, 8 * 16 * nodes)
            for i in range(nodes):
                matrices[i].frombytes(raw[128 * i:128 * i + 128])
            weight_values.frombytes(ffi.buffer(weights, 8 * channels))
        shift = min(0.0, times[0])
        if shift < 0:
            losses.append(skinning.warning("W_TIME_SHIFTED", "/", f"Shifted the animation by {-shift:g} seconds so it starts at 0."))
        seconds = tuple(t - shift for t in times)
        out, animated = [], set()
        # A constant channel is left out only when it matches the static pose, since a stack can hold a node at a
        # value that differs from it. Curves store float32, so matching allows float32 rounding.
        for k, shim in enumerate(order):
            path = node_paths[shim]
            flat, static = matrices[shim], array("d", self.nodes[shim]["to_parent"])
            if all(flat[j:j + 16] == static for j in range(0, len(flat), 16)):
                continue
            series = [list(flat[j:j + 16]) for j in range(0, len(flat), 16)]
            animated.add(shim)
            if any(transforms.has_shear(s) for s in series):
                _shear(path)
            samples = [_trs(s, path) for s in series]
            rest = _trs(self.nodes[shim]["to_parent"], path) if not transforms.has_shear(self.nodes[shim]["to_parent"]) else None
            for field in ("translation", "rotation", "scale"):
                rows = [sample[field] for sample in samples]
                if field == "rotation":
                    rows = _quaternions(rows)
                varies = any(row != rows[0] for row in rows)
                if varies or rest is None or not (_near(rows[0], rest[field])
                                                  or field == "rotation" and _near(rows[0], [-x for x in rest[field]])):
                    out.append(glb.Channel(node=k, path=field, times=seconds, values=tuple(rows)))
        for k, shim in enumerate(order):
            m = self.nodes[shim]["mesh"]
            if m < 0 or m in self.empty:
                continue
            sizes = ffi.new("uint32_t[8]")
            lib.msf_fbx_mesh_sizes(self.h, m, sizes)
            ids = []
            for c in range(sizes[5]):
                cid = ffi.new("uint32_t *")
                lib.msf_fbx_blend_channel_id(self.h, m, c, cid)
                ids.append(cid[0])
            if not ids:
                continue
            rows = [tuple(weight_values[r * channels + i] for i in ids) for r in range(len(times))]
            static = tuple(self.channel(m, c, node_paths[shim])[4] for c in range(sizes[5]))
            if any(row != rows[0] for row in rows) or not _near(rows[0], static):
                out.append(glb.Channel(node=k, path="weights", times=seconds, values=tuple(rows)))
        return ((glb.Animation(channels=tuple(out)),) if out else ()), losses, animated


ADAPTER = FbxAdapter()
