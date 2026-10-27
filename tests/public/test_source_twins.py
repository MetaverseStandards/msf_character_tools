# SPDX-License-Identifier: MIT
"""Khronos sample assets re-authored as ASCII FBX by the test writer, compared with the glTF originals.

Set MSF_KHRONOS_ASSETS to a glTF-Sample-Assets checkout (its Models folder holds
the assets; they are never committed here). Each asset is decoded with
msf-tools, written as FBX with the same nodes, meshes, skins, morph targets and
first animation, read back through the FBX adapter, and every primitive's
world-space points must match the original within 1e-5 of the bounding-box
diagonal at every keyframe time.
"""
import math
import os
from pathlib import Path
import unittest

import msf_tools as m
from support import capabilities
from support.fbx_ascii import Scene
from test_source_usd import trs

HAVE_FBX = capabilities.FBX

ROOT = Path(os.environ['MSF_KHRONOS_ASSETS']) if os.environ.get('MSF_KHRONOS_ASSETS') else None
PRESENT = HAVE_FBX and ROOT is not None and (ROOT / 'Models').is_dir()
MODELS = ('AnimatedMorphCube', 'Fox', 'MorphPrimitivesTest', 'RiggedFigure', 'SimpleSkin')


def quaternion_matrix(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def euler_xyz(q):
    """FBX Euler degrees (rotation order XYZ, so R = Rz * Ry * Rx) for a glTF quaternion."""
    # Authored glTF quaternions may be slightly off unit length (SimpleSkin is); evaluation normalizes them.
    length = math.sqrt(sum(c * c for c in q))
    r = quaternion_matrix([c / length for c in q])
    ry = math.asin(max(-1.0, min(1.0, -r[2][0])))
    return tuple(math.degrees(a) for a in (math.atan2(r[2][1], r[2][2]), ry, math.atan2(r[1][0], r[0][0])))


def inverse_affine(m16):
    """Inverse of a column-major affine 4x4."""
    a = [[m16[4 * c + r] for c in range(3)] for r in range(3)]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    inv = [[(a[(c + 1) % 3][(r + 1) % 3] * a[(c + 2) % 3][(r + 2) % 3] - a[(c + 1) % 3][(r + 2) % 3] * a[(c + 2) % 3][(r + 1) % 3]) / det
            for c in range(3)] for r in range(3)]
    t = [-sum(inv[r][k] * m16[12 + k] for k in range(3)) for r in range(3)]
    return [inv[r][c] for c in range(3) for r in range(3)][:0] + [x for c in range(3) for x in (inv[0][c], inv[1][c], inv[2][c], 0.0)] + t + [1.0]


def values(snapshot, accessor):
    return [tuple(row) for row in m.decode_accessor(snapshot, accessor).value]


def twin(snapshot):
    """FBX bytes re-authoring the snapshot, and (glTF node, primitive, FBX path of the mesh holder) rows."""
    doc = snapshot.document
    nodes = doc['nodes']
    parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', ())}
    joints = {j for skin in doc.get('skins', ()) for j in skin['joints']}
    scene, ids, path = Scene(), {}, {}

    def make(i):
        if i in ids:
            return
        if i in parent:
            make(parent[i])
        node = nodes[i]
        props = {'translation': node.get('translation', (0, 0, 0)), 'rotation': euler_xyz(node.get('rotation', (0, 0, 0, 1))),
                 'scale': node.get('scale', (1, 1, 1)), 'inherit_type': 1}
        ids[i] = scene.model(f'node{i}', ids.get(parent.get(i), 0), kind='LimbNode' if i in joints else 'Null', **props)
        path[i] = (path[parent[i]] if i in parent else '') + f'/node{i}'
    for i in range(len(nodes)):
        make(i)
    rows, channels = [], {}
    for i, node in enumerate(nodes):
        if 'mesh' not in node:
            continue
        mesh = doc['meshes'][node['mesh']]
        for p, primitive in enumerate(mesh['primitives']):
            holder = scene.model(f'prim{p}', ids[i], kind='Mesh')
            points = values(snapshot, primitive['attributes']['POSITION'])
            indices = [r[0] for r in values(snapshot, primitive['indices'])] if 'indices' in primitive else list(range(len(points)))
            geometry = scene.mesh(holder, f'mesh{i}_{p}', points, [indices[k:k + 3] for k in range(0, len(indices), 3)])
            weights = node.get('weights', mesh.get('weights', [0.0] * len(primitive.get('targets', ()))))
            if primitive.get('targets'):
                shapes = []
                for t, target in enumerate(primitive['targets']):
                    offsets = values(snapshot, target['POSITION'])
                    shapes.append((f't{t}', 100.0 * weights[t], [(100, list(range(len(offsets))), offsets)]))
                channels[(i, p)] = scene.blend(geometry, 'Morph', shapes)
            if 'skin' in node:
                skin = doc['skins'][node['skin']]
                ibms = values(snapshot, skin['inverseBindMatrices'])
                per = {}
                s = 0
                while f'JOINTS_{s}' in primitive['attributes']:
                    js = values(snapshot, primitive['attributes'][f'JOINTS_{s}'])
                    ws = values(snapshot, primitive['attributes'][f'WEIGHTS_{s}'])
                    for v, (jrow, wrow) in enumerate(zip(js, ws)):
                        for j, w in zip(jrow, wrow):
                            if w:
                                per.setdefault(j, ([], []))
                                per[j][0].append(v)
                                per[j][1].append(w)
                    s += 1
                clusters = [(ids[skin['joints'][j]], per[j][0], per[j][1], list(ibms[j]), inverse_affine(list(ibms[j])))
                            for j in sorted(per)]
                scene.skin(geometry, clusters)
            rows.append((i, p, path[i] + f'/prim{p}'))
    keys = set()
    if doc.get('animations'):
        animation = doc['animations'][0]
        curves = []
        times_all = []
        for channel in animation['channels']:
            sampler = animation['samplers'][channel['sampler']]
            times = [t for (t,) in values(snapshot, sampler['input'])]
            output = values(snapshot, sampler['output'])
            times_all += times
            target, kind = channel['target']['node'], channel['target']['path']
            if kind == 'translation' or kind == 'scale':
                prop = 'Lcl Translation' if kind == 'translation' else 'Lcl Scaling'
                curves.append((ids[target], prop, {c: [(t, v[k]) for t, v in zip(times, output)] for k, c in enumerate('XYZ')}))
            elif kind == 'rotation':
                eulers = [euler_xyz(q) for q in output]
                curves.append((ids[target], 'Lcl Rotation', {c: [(t, e[k]) for t, e in zip(times, eulers)] for k, c in enumerate('XYZ')}))
            else:
                mesh = doc['meshes'][nodes[target]['mesh']]
                count = len(mesh['primitives'][0]['targets'])
                flat = [v[0] for v in output]
                for p in range(len(mesh['primitives'])):
                    for t_index, channel_id in enumerate(channels[(target, p)]):
                        curves.append((channel_id, 'DeformPercent',
                                       {'DeformPercent': [(t, 100.0 * flat[k * count + t_index]) for k, t in enumerate(times)]}))
        keys = sorted(set(times_all))
        scene.animation('Take', keys[0], keys[-1], curves)
    return scene.text(), rows, keys


def world_points(snapshot, node, primitive, seconds, path_of=None):
    nodes = snapshot.document['nodes']
    animated = bool(snapshot.document.get('animations'))
    overrides = m.sample_animation(snapshot, 0, seconds).value if animated else {}
    parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', ())}
    index = node if path_of is None else snapshot.source['node_paths'].index(path_of)
    kwargs = {'timestamp': seconds, 'animation_id': 0} if animated else {}
    result = m.evaluate_geometry(snapshot, **kwargs)
    assert result.ok, result.report.to_dict()
    instance = next(i for i in result.value.to_dict()['instances'] if i['node'] == index)
    points = instance['primitives'][primitive if path_of is None else 0]['positions']
    while index is not None:
        t = trs(dict(nodes[index], **dict(overrides.get(index, {}))))
        points = [[sum(t[r][c] * p[c] for c in range(3)) + t[r][3] for r in range(3)] for p in points]
        index = parent.get(index)
    return points


@unittest.skipUnless(PRESENT, 'set MSF_KHRONOS_ASSETS to a glTF-Sample-Assets checkout to run this tier')
class KhronosFbxTwins(unittest.TestCase):
    def check(self, name):
        folder = ROOT / 'Models' / name / 'glTF'
        original = m.inspect_asset(next(folder.glob('*.gltf')).read_bytes(), 'gltf', resolver=m.LocalResolver(folder))
        self.assertTrue(original.ok, original.report.to_dict())
        data, rows, keys = twin(original.value)
        options = {}
        if keys:
            steps = [b - a for a, b in zip(keys, keys[1:])]
            options['sample_rate'] = round(1.0 / min(steps), 6)
        result = m.inspect_asset(data, 'fbx', options=options)
        self.assertTrue(result.ok, result.report.to_dict())
        for seconds in (keys[::max(1, len(keys) // 6)] + keys[-1:] if keys else [0.0]):
            for node, primitive, path in rows:
                wanted = world_points(original.value, node, primitive, seconds)
                actual = world_points(result.value, None, None, seconds, path_of=path)
                diagonal = math.dist([min(c) for c in zip(*wanted)], [max(c) for c in zip(*wanted)]) or 1.0
                worst = max(math.dist(a, w) for a, w in zip(actual, wanted))
                self.assertLess(worst, 1e-5 * diagonal, (name, path, seconds, worst))


for _name in MODELS:
    setattr(KhronosFbxTwins, f'test_{_name}', lambda self, name=_name: self.check(name))


if __name__ == '__main__':
    unittest.main()
