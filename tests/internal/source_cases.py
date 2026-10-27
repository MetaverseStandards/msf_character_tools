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

def path_order(candidates):
    keyed = []
    for c in candidates:
        try:
            keyed.append((_paths.sort_key(c), c))
        except ValueError:
            pass
    return [c for _, c in sorted(keyed)]
"""
