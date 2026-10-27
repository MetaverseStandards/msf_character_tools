# SPDX-License-Identifier: MIT
"""Random inputs for the source helpers (path grammar, matrix decomposition,
influence rows and the GLB writer), run on both sides of the oracle."""
import math
import random

SPECIAL = '%/#[]:\x00\x01\x1f\x7f'
ALPHABET = SPECIAL + 'abcXYZ09 .-_é漢\U0001F600\ud800'
PIECES = ['%2F', '%25', '%41', '%2f', '%', '%0', '[0]', '[12]', '[01]', '[x]', '[', ']', '#', '/', '#helper:geometry',
          '#helper:scale[2]', '#helper:scale[]', '#helper:other', 'helper:', '']


def text(rng):
    parts = []
    for _ in range(rng.randint(0, 5)):
        parts.append(rng.choice(PIECES) if rng.random() < 0.4 else rng.choice(ALPHABET))
    return ''.join(parts)


def path_cases(rng, count):
    out = []
    for _ in range(count):
        name = text(rng)
        components = [(text(rng), rng.choice([None, 0, 3, 10**30, True])) for _ in range(rng.randint(0, 3))]
        helper = rng.choice([None, ('geometry', None), ('scale', 1), ('other', None), ('scale', 10**20)])
        candidate = rng.choice(['/', '', 'x']) + '/'.join(text(rng) for _ in range(rng.randint(1, 3)))
        out.append((name, components, helper, candidate))
    return out


def quaternion(rng):
    kind = rng.random()
    if kind < 0.3:  # half turns about an axis reach every branch of the matrix-to-quaternion conversion
        axis = rng.randrange(3)
        q = [0.0, 0.0, 0.0, rng.choice([0.0, 1e-9, -1e-9])]
        q[axis] = 1.0
    else:
        q = [rng.gauss(0, 1) for _ in range(4)]
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return [x / n for x in q]


def matrix(rng):
    x, y, z, w = quaternion(rng)
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    scale = [rng.choice([1.0, 2.5, -1.0, 1e-160, 1e200, 0.0, 0.5]) if rng.random() < 0.3 else rng.uniform(0.1, 3) for _ in range(3)]
    m = [r[row][col] * scale[col] for col in range(3) for row in range(3)]
    columns = [m[0:3] + [0.0], m[3:6] + [0.0], m[6:9] + [0.0], [rng.uniform(-5, 5) for _ in range(3)] + [1.0]]
    flat = [v for col in columns for v in col]
    if rng.random() < 0.15:  # shear
        flat[4] += rng.choice([1e-7, 1e-5, 0.3])
    if rng.random() < 0.05:
        flat[rng.randrange(16)] = rng.choice([float('inf'), float('nan'), 1e-320, 2.0])
    if rng.random() < 0.05:
        flat[rng.randrange(12)] = rng.choice([1e-170, -1e-170])
    return flat


def influence_cases(rng, count):
    out = []
    for _ in range(count):
        rows = []
        for _ in range(rng.randint(1, 6)):
            pairs = []
            for _ in range(rng.randint(0, 9)):
                weight = rng.choice([0.0, 1.0, 0.5, 1e-12, rng.random(), rng.random(), 3.0])
                if rng.random() < 0.02:
                    weight = rng.choice([-0.1, float('inf'), float('nan'), 1e308])
                pairs.append((rng.randrange(12), weight))
            rows.append(pairs)
        out.append((rows, rng.randrange(12), rng.choice(['faithful', 'top4'])))
    return out


DAMAGE = [0.0]  # the share of damaged numbers and shapes in the scene being built


def number(rng, scale=1.0):
    r = rng.random()
    if r < DAMAGE[0]:
        return rng.choice([float('inf'), float('nan'), 1e39, -1e39])
    if r < 0.05:
        return rng.choice([0.0, -0.0, 1e-46, 1, 2**60, 3.4028235e38 * scale])
    return rng.uniform(-scale, scale)


def rows(rng, count, width):
    out = []
    for _ in range(count):
        n = width if rng.random() >= DAMAGE[0] else width + rng.choice([-1, 1])
        out.append([number(rng) for _ in range(n)])
    return out


def hit(rng, p):
    """A structural defect, only in damaged scenes."""
    return DAMAGE[0] > 0 and rng.random() < p


def scene_spec(rng):
    DAMAGE[0] = rng.choice([0.0, 0.0, 0.0, 0.001, 0.01])
    meshes = []
    for _ in range(rng.randint(1, 3)):
        points = rng.randint(0 if hit(rng, 0.02) else 1, 30)
        triangles = []
        if rng.random() < 0.7:
            triangles = [rng.randrange(points or 1) for _ in range(3 * rng.randint(1, 10))]
            if hit(rng, 0.03):
                triangles[0] = rng.choice([points, -1, 1.0, True, 2**70])
            if hit(rng, 0.02):
                triangles.append(0)
        targets = []
        for _ in range(rng.randint(0, 3)):
            density = rng.choice([0.0, 0.2, 0.5, 0.9, 1.0])
            targets.append([[number(rng, 0.1) for _ in range(3)] if rng.random() < density else [0.0, -0.0, 0.0] for _ in range(points)])
            if hit(rng, 0.02):
                targets[-1] = targets[-1][:-1]
        influences = None
        if rng.random() < 0.5:
            influences = []
            for _ in range(points + (1 if hit(rng, 0.02) else 0)):
                pairs = [(rng.randrange(6), rng.choice([0.0, 0.25, 0.5, 1.0, rng.random(), 1e-9])) for _ in range(rng.randint(1, 9))]
                pairs.append((rng.randrange(6), 0.5))
                if hit(rng, 0.01):
                    pairs = [(0, 0.0)]
                if hit(rng, 0.01):
                    pairs[0] = rng.choice([(-1, 1.0), (70000, 1.0), (0, float('inf')), (0, -1.0), (True, 1.0), (1.5, 1.0), (0, 1e308), (1, 1e308)])
                influences.append(pairs)
        weights = [rng.random() for _ in targets] if rng.random() < 0.5 else []
        if hit(rng, 0.02):
            weights.append(0.5)
        meshes.append({'points': rows(rng, points, 3), 'triangles': triangles, 'targets': targets, 'influences': influences, 'weights': weights})
    nodes = []
    count = rng.randint(1, 6)
    for i in range(count):
        node = {'name': rng.choice([None, f'n{i}', 'é漢', ''] + ['bad\ud800'] * hit(rng, 0.2)),
                'children': sorted(rng.sample(range(i + 1, count), rng.randint(0, min(2, count - i - 1)))) if i + 1 < count else []}
        for field, default in (('translation', [0.0, 0.0, 0.0]), ('rotation', [0.0, 0.0, 0.0, 1.0]), ('scale', [1.0, 1.0, 1.0])):
            node[field] = default if rng.random() < 0.5 else [number(rng) for _ in default]
            if hit(rng, 0.05):
                node[field] = [-0.0 if x == 0 else x for x in default]
        if rng.random() < 0.6:
            node['mesh'] = rng.randrange(len(meshes))
        if 'mesh' in node and rng.random() < 0.3:
            node['skin'] = 0
        if 'mesh' in node and rng.random() < 0.3:
            node['weights'] = [rng.random() for _ in meshes[node['mesh']]['targets']]
        nodes.append(node)
    skins = []
    if rng.random() < 0.5:
        joints = list(range(min(count, 4)))
        matrices = rows(rng, len(joints) + (1 if hit(rng, 0.03) else 0), 16)
        skins.append({'joints': joints, 'inverse_bind_matrices': matrices, 'skeleton': rng.choice([None, 0])})
    animations = []
    for a in range(rng.randint(0, 2)):
        channels = []
        shared = sorted(rng.sample(range(1, 50), rng.randint(1, 5)))
        for _ in range(rng.randint(1, 4)):
            node = rng.randrange(count) if rng.random() > 0.03 else rng.choice([count, -1, 1.0])
            target = nodes[node] if type(node) is int and 0 <= node < count else {}
            morphs = 'mesh' in target and meshes[target['mesh']]['targets']
            path = rng.choice(['translation', 'rotation', 'scale'] + ['weights'] * (2 if morphs or hit(rng, 0.3) else 0)
                              + (['matrix'] if hit(rng, 0.03) else []))
            times = [t / 10 for t in shared] if rng.random() < 0.5 else sorted(rng.sample(range(0, 50), rng.randint(1, 5)))
            if hit(rng, 0.03):
                times = list(reversed(times)) if len(times) > 1 else [-1.0]
            if hit(rng, 0.02):
                times = [0.1, 0.1 + 1e-10]
            width = {'translation': 3, 'rotation': 4, 'scale': 3}.get(path, len(meshes[target['mesh']]['targets']) if 'mesh' in target else 1)
            values = rows(rng, len(times) + (1 if hit(rng, 0.02) else 0), width)
            channels.append({'node': node, 'path': path, 'times': times, 'values': values,
                             'interpolation': rng.choice(['LINEAR', 'STEP', 'LINEAR'] + (['CUBICSPLINE'] if hit(rng, 0.05) else []))})
        animations.append({'channels': channels, 'name': rng.choice([None, f'clip{a}'])})
    return {'nodes': nodes, 'meshes': meshes, 'skins': skins, 'animations': animations}


DEFINITIONS = r"""
from msf_tools.sources import paths as _paths, skinning as _skinning, transforms as _transforms

def exact(fn, *args, **kwargs):
    try:
        return ('value', encode(fn(*args, **kwargs)))
    except Exception as exc:
        diagnostic = getattr(exc, 'diagnostic', None)
        if diagnostic is not None:
            return ('fault', diagnostic.code, diagnostic.ref, diagnostic.message)
        return ('error', type(exc).__name__, str(exc))

def path_battery(name, components, helper, candidate):
    out = [exact(_paths.escape, name), exact(_paths.unescape, name), exact(_paths.unescape, _paths.escape(name))]
    out.append(exact(_paths.node_path, components, helper))
    out.append(exact(_paths.target_key, components))
    for value in (candidate, name, '/' + name):
        out.append(exact(_paths.parse_node_path, value))
        out.append(exact(_paths.parse_target_key, value))
        out.append(exact(_paths.split_locator, value))
        out.append(exact(_paths.sort_key, value))
    made = exact(_paths.node_path, components, helper)
    if made[0] == 'value':
        path = _paths.node_path(components, helper)
        out.append(exact(_paths.parse_node_path, path))
        out.append(exact(_paths.sort_key, path))
        key = _paths.target_key(components)
        out.append(exact(_paths.split_locator, _paths.locator(path, key)))
    return out

def transform_battery(matrices):
    out = []
    for m in matrices:
        for fn in (_transforms.is_affine, _transforms.has_shear, _transforms.determinant, _transforms.decompose):
            out.append(exact(fn, m))
    return out

def skinning_battery(rows, root, mode):
    merged = [exact(_skinning.merge, pairs, '/p') for pairs in rows]
    out = [merged]
    good = [_skinning.merge(pairs, '/p') for pairs, m in zip(rows, merged) if m[0] == 'value']
    out.append(exact(_skinning.influence_rows, good, root, mode, '/p'))
    out.append(exact(_skinning.influence_rows, good, root, mode, '/p', 'the nearest ancestor joint'))
    return out

def glb_battery(spec):
    from msf_tools.sources import glb as _glb
    meshes = tuple(_glb.Mesh(points=tuple(map(tuple, m['points'])), triangles=tuple(m['triangles']),
                             targets=tuple(tuple(map(tuple, t)) for t in m['targets']),
                             influences=None if m['influences'] is None else tuple(tuple(p) for p in m['influences']),
                             weights=tuple(m['weights'])) for m in spec['meshes'])
    nodes = tuple(_glb.Node(**{k: tuple(v) if isinstance(v, list) else v for k, v in n.items()}) for n in spec['nodes'])
    skins = tuple(_glb.Skin(joints=tuple(s['joints']), inverse_bind_matrices=tuple(map(tuple, s['inverse_bind_matrices'])),
                            skeleton=s['skeleton']) for s in spec['skins'])
    animations = tuple(_glb.Animation(channels=tuple(_glb.Channel(node=c['node'], path=c['path'], times=tuple(c['times']),
                                                                  values=tuple(map(tuple, c['values'])), interpolation=c['interpolation'])
                                                     for c in a['channels']), name=a['name']) for a in spec['animations'])
    out = exact(_glb.write_glb, nodes, meshes, skins, animations, generator='fuzz 1')
    if out[0] == 'value':
        raw = _glb.write_glb(nodes, meshes, skins, animations, generator='fuzz 1')
        out = (out, encode(m.inspect_asset(raw, 'glb')))
    return out

def path_order(candidates):
    keyed = []
    for c in candidates:
        try:
            keyed.append((_paths.sort_key(c), c))
        except ValueError:
            pass
    return [c for _, c in sorted(keyed)]
"""
