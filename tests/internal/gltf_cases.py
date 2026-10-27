# SPDX-License-Identifier: MIT
"""Random glTF/GLB assets and the battery of public calls run on each, for the
differential tests against the 0.3.0 oracle.

random_asset(rng) builds a structurally rich asset (meshes with morph targets,
sparse and descriptor-only accessors, skins, node hierarchies, animations of
every interpolation, images, materials), often damaged on purpose at the JSON,
binary or container level. BATTERY runs the same calls on both sides.
"""
import base64
import copy
import json
import math
import struct

COMPONENTS = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}
WIDTH = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


class Builder:
    def __init__(self, rng):
        self.rng = rng
        self.data = bytearray()
        self.views = []
        self.accessors = []

    def view(self, payload, **extra):
        while len(self.data) % 4:
            self.data.append(0)
        self.views.append({'buffer': 0, 'byteOffset': len(self.data), 'byteLength': len(payload), **extra})
        self.data.extend(payload)
        return len(self.views) - 1

    def rows(self, rows, shape, component=5126, normalized=False, bounds=False, **extra):
        code = COMPONENTS[component]
        payload = bytearray()
        for row in rows:
            payload.extend(struct.pack('<' + code * len(row), *row))
        a = {'bufferView': self.view(bytes(payload)), 'componentType': component, 'type': shape, 'count': len(rows), **extra}
        if normalized:
            a['normalized'] = True
        if bounds and rows:
            stored = [struct.unpack('<' + code * len(r), struct.pack('<' + code * len(r), *r)) for r in rows]
            a['min'] = [min(r[k] for r in stored) for k in range(len(stored[0]))]
            a['max'] = [max(r[k] for r in stored) for k in range(len(stored[0]))]
        self.accessors.append(a)
        return len(self.accessors) - 1

    def sparse(self, count, entries, shape='VEC3', descriptor_bounds=None):
        """A sparse accessor over zeros; entries: {index: row}."""
        indices = sorted(entries)
        a = {'componentType': 5126, 'type': shape, 'count': count}
        if indices:
            ix = self.view(struct.pack(f'<{len(indices)}I', *indices))
            values = self.view(b''.join(struct.pack('<' + 'f' * len(entries[i]), *entries[i]) for i in indices))
            a['sparse'] = {'count': len(indices), 'indices': {'bufferView': ix, 'componentType': 5125}, 'values': {'bufferView': values}}
        rows = [tuple(entries.get(i, (0.0,) * WIDTH[shape])) for i in range(count)]
        stored = [struct.unpack('<' + 'f' * len(r), struct.pack('<' + 'f' * len(r), *r)) for r in rows]
        a['min'] = [min(r[k] for r in stored) for k in range(WIDTH[shape])]
        a['max'] = [max(r[k] for r in stored) for k in range(WIDTH[shape])]
        if descriptor_bounds is not None:
            a['min'], a['max'] = descriptor_bounds
        self.accessors.append(a)
        return len(self.accessors) - 1


def unit_quaternion(rng):
    q = [rng.gauss(0, 1) for _ in range(4)]
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return [x / n for x in q]


def vec(rng, n, low=-2, high=2):
    return tuple(rng.uniform(low, high) for _ in range(n))


def primitive(b, rng, n, targets):
    attrs = {'POSITION': b.rows([vec(rng, 3) for _ in range(n)], 'VEC3', bounds=True)}
    p = {'attributes': attrs}
    roll = rng.random()
    if roll < 0.15:
        attrs['NORMAL'] = b.rows([vec(rng, 3, -1, 1) for _ in range(n)], 'VEC3')
    elif roll < 0.25:
        attrs['TEXCOORD_0'] = (b.rows([vec(rng, 2, 0, 1) for _ in range(n)], 'VEC2') if rng.random() < 0.5 else
                               b.rows([(rng.randrange(256), rng.randrange(256)) for _ in range(n)], 'VEC2', 5121, True))
    elif roll < 0.32:
        attrs['COLOR_0'] = b.rows([vec(rng, 4, 0, 1 if rng.random() < 0.9 else 1.5) for _ in range(n)], 'VEC4')
    elif roll < 0.38:
        attrs['TANGENT'] = b.rows([vec(rng, 3, -1, 1) + (rng.choice((1.0, -1.0, 1.0, 0.5)),) for _ in range(n)], 'VEC4')
    mode = rng.choice((0, 0, 4, 4, 1, 2, 3, 5, 6))
    minimum = {0: 1, 1: 2, 2: 2, 3: 2, 4: 3, 5: 3, 6: 3}[mode]
    step = {1: 2, 4: 3}.get(mode, 1)
    if n < minimum or n % step or rng.random() < 0.4:
        count = step * rng.randrange(max(1, (minimum + step - 1) // step), 4)
        component = rng.choice((5121, 5123, 5125))
        idx = [rng.randrange(n + (1 if rng.random() < 0.03 else 0)) for _ in range(count)]
        p['indices'] = b.rows([(i,) for i in idx], 'SCALAR', component)
    if mode != 4 or rng.random() < 0.5:
        p['mode'] = mode
    if targets:
        p['targets'] = []
        for _ in range(targets):
            kind = rng.random()
            if kind < 0.5:
                t = b.rows([vec(rng, 3, -1, 1) for _ in range(n)], 'VEC3', bounds=True)
            elif kind < 0.8:
                t = b.sparse(n, {i: vec(rng, 3, -1, 1) for i in rng.sample(range(n), rng.randrange(0, n + 1))})
            else:
                t = b.sparse(n, {})
            p['targets'].append({'POSITION': t})
    return p


def skin_parts(b, rng, nodes, mesh_nodes, n_joints):
    first = len(nodes)
    for j in range(n_joints):
        node = {}
        if rng.random() < 0.7:
            node['translation'] = list(vec(rng, 3, -3, 3))
        if rng.random() < 0.6:
            node['rotation'] = unit_quaternion(rng)
        if rng.random() < 0.3:
            node['scale'] = [rng.choice((1, 2, 0.5)) for _ in range(3)]
        nodes.append(node)
    for j in range(1, n_joints):
        nodes[first + rng.randrange(0, j)].setdefault('children', []).append(first + j)
    skin = {'joints': list(range(first, first + n_joints))}
    if rng.random() < 0.85:
        ibms = []
        for _ in range(n_joints):
            q = unit_quaternion(rng)
            x, y, z, w = q
            r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
            cols = [r[i][c] for c in range(3) for i in range(3)]
            m = cols[0:3] + [0] + cols[3:6] + [0] + cols[6:9] + [0] + list(vec(rng, 3)) + [1]
            if rng.random() < 0.03:
                m[3] = 0.5
            ibms.append(tuple(m))
        skin['inverseBindMatrices'] = b.rows(ibms, 'MAT4')
    return skin


def influences(b, rng, n, n_joints, sets):
    rows = []
    for _ in range(n):
        positive = rng.sample(range(n_joints), rng.randrange(1, min(4 * sets, n_joints) + 1))
        shares = [1.0]
        while len(shares) < len(positive):
            shares.sort()
            half = shares.pop() / 2
            shares += [half, half]
        slots = rng.sample(range(4 * sets), len(positive))
        joints = [rng.randrange(n_joints) for _ in range(4 * sets)]
        weights = [0.0] * (4 * sets)
        for slot, joint, share in zip(slots, positive, shares):
            joints[slot], weights[slot] = joint, share
        if rng.random() < 0.03:
            weights[slots[0]] += 0.01
        if rng.random() < 0.03:
            joints[rng.randrange(4 * sets)] = n_joints
        rows.append((joints, weights))
    attrs = {}
    for s in range(sets):
        attrs[f'JOINTS_{s}'] = b.rows([tuple(j[4 * s:4 * s + 4]) for j, _ in rows], 'VEC4', rng.choice((5121, 5123)))
        if rng.random() < 0.1:
            attrs[f'WEIGHTS_{s}'] = b.rows([tuple(min(255, round(w * 255)) for w in ws[4 * s:4 * s + 4]) for _, ws in rows], 'VEC4', 5121, True)
        else:
            attrs[f'WEIGHTS_{s}'] = b.rows([tuple(ws[4 * s:4 * s + 4]) for _, ws in rows], 'VEC4')
    return attrs


def animation(b, rng, nodes, meshes):
    samplers, channels = [], []
    driven = set()
    for _ in range(rng.randrange(1, 4)):
        node = rng.randrange(len(nodes))
        paths = ['translation', 'rotation', 'scale']
        mesh = nodes[node].get('mesh')
        count = len(meshes[mesh]['primitives'][0].get('targets', ())) if mesh is not None else 0
        if count:
            paths.append('weights')
        path = rng.choice(paths)
        if (node, path) in driven and rng.random() < 0.95:
            continue
        driven.add((node, path))
        interpolation = rng.choice(('STEP', 'LINEAR', 'LINEAR', 'CUBICSPLINE', None))
        keys = rng.randrange(1 if interpolation != 'CUBICSPLINE' else 2, 5)
        times = sorted({round(rng.uniform(0, 2), 3) for _ in range(keys)})
        if rng.random() < 0.05:
            times = times[::-1]
        keys = len(times)
        if interpolation == 'CUBICSPLINE' and keys < 2:
            times, keys = [0.0, 1.0], 2
        width = {'translation': 3, 'rotation': 4, 'scale': 3}.get(path, 1)
        per_key = 3 if interpolation == 'CUBICSPLINE' else 1
        values = []
        for _ in range(keys * per_key * (count if path == 'weights' else 1)):
            if path == 'rotation':
                values.append(tuple(unit_quaternion(rng)))
            elif path == 'weights':
                values.append((rng.uniform(-0.5, 1.5),))
            else:
                values.append(vec(rng, width, 0.1, 2))
        if path in ('rotation', 'weights') and rng.random() < 0.25:
            component = rng.choice((5120, 5121, 5122, 5123))
            scale = {5120: 127, 5121: 255, 5122: 32767, 5123: 65535}[component]
            low = 0 if component in (5121, 5123) else -scale
            output = b.rows([tuple(max(low, min(scale, round(x * scale))) for x in row) for row in values],
                            'VEC4' if path == 'rotation' else 'SCALAR', component, True)
        else:
            output = b.rows(values, 'VEC4' if path == 'rotation' else 'SCALAR' if path == 'weights' else 'VEC3')
        sampler = {'input': b.rows([(t,) for t in times], 'SCALAR', bounds=True), 'output': output}
        if interpolation is not None:
            sampler['interpolation'] = interpolation
        samplers.append(sampler)
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': node, 'path': path}})
    if not channels:
        return animation(b, rng, nodes, meshes)
    return {'samplers': samplers, 'channels': channels}


def document(rng):
    b = Builder(rng)
    meshes, nodes = [], []
    for _ in range(rng.randrange(1, 3)):
        targets = rng.choice((0, 0, 1, 2, 3))
        n = rng.randrange(1, 6)
        prims = [primitive(b, rng, n, targets) for _ in range(rng.choice((1, 1, 2)))]
        mesh = {'primitives': prims}
        if targets and rng.random() < 0.5:
            mesh['weights'] = [rng.uniform(0, 1) for _ in range(targets)]
        meshes.append(mesh)
    for mi, mesh in enumerate(meshes):
        node = {'mesh': mi}
        if rng.random() < 0.4:
            node['translation'] = list(vec(rng, 3))
        if rng.random() < 0.4:
            node['rotation'] = unit_quaternion(rng)
        if rng.random() < 0.2:
            node['scale'] = list(vec(rng, 3, 0.5, 2))
        if rng.random() < 0.1:
            node = {'mesh': mi, 'matrix': [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 1, 2, 3, 1] if rng.random() < 0.8 else
                    [1, 0.5, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
        targets = len(mesh['primitives'][0].get('targets', ()))
        if targets and rng.random() < 0.3:
            node['weights'] = [rng.uniform(0, 1) for _ in range(targets)]
        nodes.append(node)
    skins = []
    if rng.random() < 0.35:
        mi = 0
        n_joints = rng.randrange(1, 5)
        sets = rng.choice((1, 1, 2))
        n = meshes[mi]['primitives'][0]['attributes']
        count = b.accessors[n['POSITION']]['count']
        for p in meshes[mi]['primitives']:
            p['attributes'].update(influences(b, rng, b.accessors[p['attributes']['POSITION']]['count'], n_joints, sets))
        skins.append(skin_parts(b, rng, nodes, [0], n_joints))
        nodes[0]['skin'] = 0
        nodes[0].pop('matrix', None)
        del count
    if len(nodes) > 1 and rng.random() < 0.5:
        parent = rng.randrange(len(nodes))
        child = rng.randrange(len(nodes))
        if parent != child and not any(child in n.get('children', ()) for n in nodes):
            nodes[parent].setdefault('children', []).append(child)
    d = {'asset': {'version': '2.0'}, 'meshes': meshes, 'nodes': nodes}
    if skins:
        d['skins'] = skins
    if rng.random() < 0.5:
        d['animations'] = [animation(b, rng, nodes, meshes) for _ in range(rng.choice((1, 1, 2)))]
    roots = [i for i in range(len(nodes)) if not any(i in n.get('children', ()) for n in nodes)]
    if rng.random() < 0.8:
        d['scenes'] = [{'nodes': roots}]
        if rng.random() < 0.7:
            d['scene'] = 0
    if rng.random() < 0.15:
        image = rng.random()
        if image < 0.4:
            d['images'] = [{'uri': 'data:image/png;base64,' + base64.b64encode(bytes(rng.randrange(256) for _ in range(8))).decode()}]
        elif image < 0.7:
            d['images'] = [{'bufferView': b.view(bytes(range(8))), 'mimeType': 'image/png'}]
        else:
            d['images'] = [{'uri': 'tex.png'}]
        d['samplers'] = [{'magFilter': 9729}]
        d['textures'] = [{'source': 0, 'sampler': 0}]
        d['materials'] = [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}]
        for mesh in meshes:
            mesh['primitives'][0]['material'] = 0
    if rng.random() < 0.08:
        d['extensionsUsed'] = ['KHR_materials_unlit']
        if rng.random() < 0.5:
            d['extensionsRequired'] = ['KHR_materials_unlit']
    if rng.random() < 0.05:
        d['cameras'] = [{'type': 'perspective', 'perspective': {'yfov': 1.0, 'znear': 0.1}}]
        nodes.append({'camera': 0})
    d['accessors'] = b.accessors
    if b.data:
        d['bufferViews'] = b.views
    return d, bytes(b.data)


# Mutations ------------------------------------------------------------------

POOL = [None, True, False, 0, 1, -1, 2, 3, 4, 7, 12, 64, 255, 5120, 5121, 5123, 5125, 5126, 34962, 34963, 0.5, -0.0, 1.5,
        1e308, 2**53 + 1, 10**30, '', 'x', 'VEC3', 'SCALAR', 'MAT4', 'LINEAR', 'CUBICSPLINE', 'STEP', 'weights', 'rotation',
        'translation', 'pointer', [], {}, [0], [1, 2], [0, 0, 0], [0, 0, 0, 1], [1, 1, 1], {'node': 0, 'path': 'weights'}, '2.0']
KEYS = ['byteStride', 'byteOffset', 'normalized', 'min', 'max', 'sparse', 'target', 'skeleton', 'skin', 'mesh', 'weights',
        'children', 'matrix', 'rotation', 'scale', 'translation', 'extensions', 'extras', 'mode', 'indices', 'material',
        'interpolation', 'uri', 'bufferView', 'minVersion', 'camera', 'zzz']
# Raw JSON numbers written in place of an integer, to reach parse_document's exact integer slots.
LEXEMES = ['2.0', '1e1', '1E0', '1.5', '-0', '0.0', '4e-0', '3.0000000000000001', '1e400', '2e0', '9007199254740993.0']


def containers(value, path=()):
    yield path, value
    if len(path) > 8:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            yield from containers(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from containers(v, path + (i,))


def mutate(d, rng, tokens):
    spots = [v for _, v in containers(d) if isinstance(v, (dict, list))]
    target = rng.choice(spots)
    roll = rng.random()
    if isinstance(target, dict) and target:
        k = rng.choice(list(target))
        if roll < 0.35:
            target[k] = copy.deepcopy(rng.choice(POOL))
        elif roll < 0.5:
            del target[k]
        elif roll < 0.65:
            target[rng.choice(KEYS)] = copy.deepcopy(rng.choice(POOL))
        elif roll < 0.85 and type(target[k]) is int:
            marker = f'@lexeme{len(tokens)}@'
            tokens[marker] = rng.choice(LEXEMES)
            target[k] = marker
        elif type(target[k]) is int:
            target[k] += rng.choice((-1, 1, 4, 1000))
        else:
            target[k] = copy.deepcopy(rng.choice(POOL))
    elif isinstance(target, list) and target:
        i = rng.randrange(len(target))
        if roll < 0.4:
            target[i] = copy.deepcopy(rng.choice(POOL))
        elif roll < 0.6 and type(target[i]) is int:
            marker = f'@lexeme{len(tokens)}@'
            tokens[marker] = rng.choice(LEXEMES)
            target[i] = marker
        elif roll < 0.8:
            target.append(copy.deepcopy(target[i]))
        else:
            del target[i]


def encode(d, tokens):
    text = json.dumps(d, separators=(',', ':'), allow_nan=True)
    for marker, value in tokens.items():
        text = text.replace(json.dumps(marker), value)
    return text.encode()


def glb(json_bytes, binary, rng, damage):
    text = json_bytes + b' ' * (-len(json_bytes) % 4)
    chunks = struct.pack('<II', len(text), 0x4E4F534A) + text
    if binary is not None:
        pad = b'\x00' * (-len(binary) % 4)
        if damage and rng.random() < 0.2 and pad:
            pad = b'\x01' + pad[1:]
        chunks += struct.pack('<II', len(binary) + len(pad), 0x004E4942) + binary + pad
    raw = bytearray(struct.pack('<III', 0x46546C67, 2, 12 + len(chunks)) + chunks)
    if damage and rng.random() < 0.3:
        roll = rng.random()
        if roll < 0.2:
            struct.pack_into('<I', raw, 8, len(raw) + 4)
        elif roll < 0.4:
            struct.pack_into('<I', raw, 4, 1)
        elif roll < 0.55:
            struct.pack_into('<I', raw, 12, len(text) + 4)
        elif roll < 0.7:
            raw += struct.pack('<II', 4, 0x12345678) + b'\x00' * 4
            struct.pack_into('<I', raw, 8, len(raw))
        elif roll < 0.85:
            raw = raw[:rng.randrange(0, len(raw))]
        else:
            raw[rng.randrange(len(raw))] ^= 1 << rng.randrange(8)
    return bytes(raw)


def random_asset(rng, damage=None):
    """(raw bytes, format, blobs for the resolver or None)."""
    d, binary = document(rng)
    damage = rng.random() < 0.6 if damage is None else damage
    data = bytearray(binary)
    if damage and data and rng.random() < 0.4:
        for _ in range(rng.randrange(1, 4)):
            data[rng.randrange(len(data))] = rng.randrange(256)
    tokens = {}
    container = rng.choice(('data', 'data', 'glb', 'glb', 'external'))
    blobs = None
    if data:
        if container == 'data':
            text = base64.b64encode(bytes(data)).decode()
            if rng.random() < 0.1:
                text = text[:4] + '\r\n' + text[4:]
            d['buffers'] = [{'byteLength': len(binary), 'uri': 'data:application/octet-stream;base64,' + text}]
        elif container == 'external':
            d['buffers'] = [{'byteLength': len(binary), 'uri': 'buf.bin'}]
            blobs = {'buf.bin': bytes(data)} if rng.random() < 0.85 else None
        else:
            d['buffers'] = [{'byteLength': len(binary)}]
    if d.get('images') and d['images'][0].get('uri') == 'tex.png' and rng.random() < 0.7:
        blobs = dict(blobs or {}, **{'tex.png': b'\x89PNG....'})
    if damage:
        for _ in range(rng.choice((1, 1, 1, 2, 3))):
            mutate(d, rng, tokens)
    json_bytes = encode(d, tokens)
    if container == 'glb':
        return glb(json_bytes, bytes(data) if data else None, rng, damage), rng.choice(('glb', 'glb', 'GLB')), blobs
    return json_bytes, rng.choice(('gltf', 'gltf', 'json', 'gltf2')), blobs


SIGNAL = {'id': 'sig', 'value_type': 'scalar', 'units': '1', 'domain': {'min': 0, 'max': 1}, 'calibration': 'basis'}

BATTERY = r'''
from collections.abc import Mapping as _Mapping
from types import MappingProxyType as _Proxy

# A Mapping whose items() returns `items` as given, not (key, value) tuples.
class _Odd(_Mapping):
    def __init__(self, items, data=None): self._items, self._data = items, dict(data or {})
    def __getitem__(self, key): return self._data[key]
    def __iter__(self): return iter(self._data)
    def __len__(self): return len(self._data)
    def items(self): return self._items

def gltf_battery(raw, fmt, blobs, signal, deep=True):
    resolver = (lambda uri: blobs[uri]) if blobs is not None else None
    result = m.inspect_asset(raw, fmt, resolver)
    out = [encode(result)]
    if not result.ok or not deep:
        return out
    s = result.value
    doc = s.document
    accessors = len(doc.get('accessors', ()))
    for i in list(range(min(accessors, 10))) + [accessors, -1, True, 1.0]:
        out.append(attempt(lambda: m.decode_accessor(s, i)))
    out.append(attempt(lambda: s.resource_hashes))
    out.append(attempt(lambda: m.evaluate_geometry(s)))
    for a in range(min(len(doc.get('animations', ())), 2)):
        for t in (0, 0.0, 0.25, 0.7, 1, 1.999, 3.5, -1, True):
            out.append(attempt(lambda: m.sample_animation(s, a, t)))
            out.append(attempt(lambda: m.evaluate_geometry(s, timestamp=t, animation_id=a)))
    out.append(attempt(lambda: m.sample_animation(s, 7, 0.0)))
    nodes = doc.get('nodes', ())
    for ni, node in enumerate(nodes[:3]):
        if 'mesh' in node:
            mesh = doc['meshes'][node['mesh']]
            count = max((len(p.get('targets', ())) for p in mesh['primitives']), default=0)
            for weights in ([0.5] * count, [0.25] * (count + 1), [True] * count):
                out.append(attempt(lambda: m.evaluate_geometry(s, morph_weights={ni: weights})))
        for override in ({'translation': [1, 2, 3]}, {'rotation': [0, 0, 0.6, 0.8]}, {'scale': [2, 2, 2]},
                         {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 2, 3, 1]}, {'rotation': [0, 0, 0, 2]}):
            out.append(attempt(lambda: m.evaluate_geometry(s, node_transforms={ni: override})))
    translation = _Odd([['translation', (1, 2, 3)]], {'translation': (1, 2, 3)})
    for ni in range(min(len(nodes), 2)):
        for pairs in ([[ni, (0.5,)]], [(ni,)], [ni], [[ni, translation]], [[ni, {'translation': (1, 2, 3)}], 'x']):
            out.append(attempt(lambda: m.evaluate_geometry(s, morph_weights=_Odd(pairs))))
            out.append(attempt(lambda: m.evaluate_geometry(s, node_transforms=_Odd(pairs))))
    out.append(attempt(lambda: m.canonical_json(_Proxy(_Odd([['scene', [1, 2]]], {'scene': [1, 2]})))))
    out.append(attempt(lambda: m.evaluate_geometry(s, attributes=('POSITION', 'NORMAL'))))
    out.append(attempt(lambda: m.export_geometry_golden(s, timestamp=0.5)))
    bindings = []
    for ni, node in enumerate(nodes):
        if 'mesh' not in node:
            continue
        mesh = doc['meshes'][node['mesh']]
        count = max((len(p.get('targets', ())) for p in mesh['primitives']), default=0)
        for target in range(count + 1):
            binding = attempt(lambda: m.morph_binding(s, dict(signal, id=f'sig.{ni}.{target}'), ni, target))
            out.append(binding)
            if binding[0] == 'value' and len(bindings) < 3:
                bindings.append(m.morph_binding(s, dict(signal, id=f'sig.{ni}.{target}'), ni, target).value)
    annotated = m.annotate_asset(s, {'bindings': bindings, 'metadata': {'note': 'fuzz'}})
    out.append(encode(annotated))
    if annotated.ok:
        bound = m.inspect_asset(raw, fmt, resolver, annotated.value)
        out.append(encode(bound))
        out.append(attempt(lambda: annotated.value.to_bytes()))
        if bound.ok:
            out.append(attempt(lambda: m.evaluate_geometry(bound.value)))
    return out
'''


# Inputs at the API boundary that random assets do not reach: odd types for
# timestamps, indices and overrides, opaque extension values, undecodable or
# over-deep JSON, resolvers that misbehave and lone surrogates. `exact` records
# the exception a call raises, message included, where public() would fold it
# into E_INPUT or E_INTERNAL.
EDGES = r"""
import json as _json
from collections.abc import Mapping

def exact(fn, *args, **kwargs):
    try:
        return ('value', encode(getattr(fn, '__wrapped__', fn)(*args, **kwargs)))
    except Exception as exc:
        diagnostic = getattr(exc, 'diagnostic', None)
        if diagnostic is not None:
            return ('fault', diagnostic.code, diagnostic.ref, diagnostic.message)
        return ('error', type(exc).__name__, str(exc))

class Falsy:
    def __init__(self, blobs): self.blobs = blobs
    def __bool__(self): return False
    def __call__(self, uri): return self.blobs[uri]

# A Mapping whose items() returns `items` as given, not (key, value) tuples.
class OddItems(Mapping):
    def __init__(self, items, data=None): self._items, self._data = items, dict(data or {})
    def __getitem__(self, key): return self._data[key]
    def __iter__(self): return iter(self._data)
    def __len__(self): return len(self._data)
    def items(self): return self._items() if callable(self._items) else self._items

def _pairs_then_raise():
    yield (5, (0.1, 0.2, 0.3))
    raise RuntimeError('items() failed part way')

# (keyword, value) overrides whose Mappings hand evaluate_geometry odd items.
def odd_overrides():
    weights = (0.1, 0.2, 0.3)
    translation = OddItems([['translation', (1, 2, 3)]], {'translation': (1, 2, 3)})
    out = [('morph_weights', OddItems(v)) for v in ([['a', 1]], [[5, weights]], [[5, list(weights)]], [(5,)], [(5, weights, 0)],
                                                     [5], ['ab'], [iter([5, weights])], [[1, weights]], [[5, weights], (6,)],
                                                     5, None, _pairs_then_raise, [[0, weights], 5], [])]
    out += [('node_transforms', OddItems(v)) for v in ([['a', 1]], [[3, translation]], [[3, OddItems([], {'translation': (1, 2)})]],
                                                        [[3, OddItems([], {'bogus': 1})]], [[3, {'translation': (1, 2, 3)}], 7],
                                                        [[99, translation]], [[3, OddItems([], {'translation': None})]])]
    return out

def edge_odd_mappings(raw):
    s = m.inspect_asset(raw, 'gltf').value
    from types import MappingProxyType
    out = [exact(m.evaluate_geometry, s, **{keyword: value}) for keyword, value in odd_overrides()]
    out += [exact(m.evaluate_geometry, s, morph_weights=OddItems([[5, (0.1, 0.2, 0.3)]]), node_transforms=OddItems(5))]
    out += [exact(m.evaluate_geometry, s, morph_weights=OddItems([[2, (0.1,)]]), node_transforms=OddItems(5))]
    for items in ([['a', 1]], [('a', 1, 2)], [('a',)], [('a', 1)], [[1, 2]], [], 'ab'):
        out.append(exact(m.canonical_json, MappingProxyType(OddItems(items, {'a': 1}))))
        out.append(exact(m.canonical_json, {'outer': MappingProxyType(OddItems(items, {'a': 1}))}))
    return out

def edge_timestamps(raw):
    s = m.inspect_asset(raw, 'gltf').value
    out = []
    for t in (2**53 + 1, 10**400, float('nan'), -0.0, 0.5, 2**60, 1e308, 5e-324):
        out.append(exact(m.sample_animation, s, 0, t))
        out.append(exact(m.evaluate_geometry, s, timestamp=t, animation_id=0))
    for a in (2**70, False, '0', 0.0, -1):
        out.append(exact(m.sample_animation, s, a, 0.5))
        out.append(exact(m.evaluate_geometry, s, animation_id=a))
    for i in (2**70, '0', None, False, 1.0, -2**70):
        out.append(exact(m.decode_accessor, s, i))
    return out

def edge_overrides(raw):
    s = m.inspect_asset(raw, 'gltf').value
    nodes = s.document.get('nodes', ())
    out = []
    from types import MappingProxyType
    for weights in ([], (0.5,), {True: [0.5]}, {0.0: [0.5]}, {2**70: [0.5]}, {'0': [0.5]}, MappingProxyType({0: (0.5,)}),
                    {0: [0.5, 0.25]}, {0: (2**1100,)}, {0: [float('inf')]}, {0: 'ab'}, {0: None}, 7):
        for n in range(min(len(nodes), 6)):
            w = {n: v for v in weights.values()} if isinstance(weights, dict) and list(weights) == [0] else weights
            out.append(exact(m.evaluate_geometry, s, morph_weights=w))
    for transform in ({'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], 'scale': [1, 1, 1]}, {1: 2}, [], {},
                      {'translation': (1, 2, 3)}, {'translation': [1, 2]}, {'rotation': [0, 0, 0, 0]}, {'scale': [0, 1, 1]},
                      {'matrix': [2, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}, {'extra': 1}, {'translation': [1e308, 1e308, 0]}):
        for n in range(min(len(nodes), 6)):
            out.append(exact(m.evaluate_geometry, s, node_transforms={n: transform}))
    out.append(exact(m.evaluate_geometry, s, morph_weights={5: [0.1, 0.2, 0.3]}, animation_id=0, timestamp=0.5))
    out.append(exact(m.evaluate_geometry, s, node_transforms={3: {'translation': [0, 0, 0]}}, animation_id=0))
    out.append(exact(m.evaluate_geometry, s, attributes='POSITION'))
    out.append(exact(m.evaluate_geometry, s, attributes=5))
    return out

def edge_extensions(raw):
    out = []
    for where in ('primitive', 'view'):
        for value in (5, None, True, 1.5, 'xxKHR_draco_mesh_compressionxx', 'EXT_meshopt_compression', ['KHR_draco_mesh_compression'],
                      ['EXT_meshopt_compression'], {'EXT_meshopt_compression': {}}, {'KHR_draco_mesh_compression': {}}, []):
            doc = _json.loads(raw)
            target = doc['meshes'][0]['primitives'][0] if where == 'primitive' else doc['bufferViews'][0]
            target['extensions'] = value
            result = m.inspect_asset(_json.dumps(doc).encode(), 'gltf')
            out.append(encode(result.report))
            if result.ok:
                out.append(exact(m.evaluate_geometry, result.value))
    return out

def edge_documents(raw):
    out = []
    # Past 200 levels the parser refuses where 0.3.0's depended on the stack (CHANGELOG).
    deep = b'{"asset":{"version":"2.0"},"extras":' + b'[' * 199 + b']' * 199 + b'}'
    shallow = b'{"asset":{"version":"2.0"},"extras":' + b'[' * 127 + b']' * 127 + b'}'
    texts = [b'\xef\xbb\xbf' + raw, raw[:-3], raw + b'x', b'\xff' + raw, raw.replace(b'"asset"', b'"asset":1,"asset"', 1), deep, shallow,
             b'{"asset":{"version":"2.0"},"extras":{"\\ud800":1}}', b'{"asset":{"version":"2.0"},"extras":"\\udfff"}',
             b'{"asset":{"version":"2.0"},"extras":{"\\ud800":1,"\\ud800":2}}', b'{"asset":{"version":"2.0"},"extras":NaN}',
             b'{"asset":{"version":"2.0"},"extras":1e400}', b'{"asset":{"version":"2.0"},"scene":1.5}', b'[]', b'"x"', b'',
             b'{"asset":{"version":"2.0"},"extras":' + b'1' * 400 + b'}', b'{"asset":{"version":"2.0"}}  \n',
             b'{"asset":{"version":"2.0"},"extras":"\xed\xa0\x80"}']
    # References into lists the document leaves out.
    head = b'{"asset":{"version":"2.0"},'
    texts += [head + b'"accessors":[{"componentType":5126,"count":1,"type":"SCALAR","bufferView":0}]}',
              head + b'"accessors":[{"componentType":5126,"count":1,"type":"SCALAR","sparse":{"count":1,'
                     b'"indices":{"bufferView":0,"componentType":5125},"values":{"bufferView":0}}}]}',
              head + b'"bufferViews":[{"buffer":0,"byteLength":4}]}',
              head + b'"meshes":[{"primitives":[{"attributes":{"POSITION":0}}]}]}',
              head + b'"animations":[{"channels":[{"sampler":0,"target":{"node":0,"path":"translation"}}],'
                     b'"samplers":[{"input":0,"output":1}]}]}',
              head + b'"skins":[{"joints":[0]}]}']
    for text in texts:
        out.append(exact(m.inspect_asset, text, 'gltf'))
        out.append(exact(m.inspect_asset, text, 'GLTF2'))
    for fmt in ('glb', 'Glb', 'json', 'obj', 7):
        out.append(exact(m.inspect_asset, raw, fmt))
    return out

def edge_resolvers(raw, blobs):
    out = []
    for resolver in (lambda uri: bytearray(blobs[uri]), lambda uri: None, lambda uri: 1 / 0, lambda uri: blobs[uri] + b'\0' * 3,
                     lambda uri: blobs[uri][:4], Falsy(blobs), lambda uri: memoryview(blobs[uri]), 'not callable',
                     lambda uri: m.LocalResolver('/')(uri)):
        out.append(exact(m.inspect_asset, raw, 'gltf', resolver))
    return out
"""
