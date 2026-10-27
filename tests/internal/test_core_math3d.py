# SPDX-License-Identifier: MIT
"""msf_tools.math3d (the C++ core) against the 0.3.0 oracle and CPython's math.

Each case is an expression over `h` (msf_tools.math3d) evaluated here and in
the oracle venv; values, faults and their messages must be identical, floats
bit for bit. hypot and fsum are checked against math.hypot and math.fsum in
process. MSF_GATE=1 runs 10**6 vectors per arity and 10**5 oracle cases.
"""
from array import array
import math
import os
import random
import unittest

from msf_tools import _native
from internal import oracle

GATE = os.environ.get('MSF_GATE') == '1'
core = _native.built
TINY, HUGE = 2.0**-800, 1.5e308
SCALARS = [0, 1, -1, 0.0, -0.0, 0.5, 2, 1e-300, 1e300, HUGE, -HUGE, TINY, 2**-1074, 2**-1022, 1e200, 1e-200,
           math.nan, math.inf, -math.inf, True, False, '1', None, 10**400, 2**53 + 1]


def diag(x, y=1, z=1):
    return ((x, 0, 0, 0), (0, y, 0, 0), (0, 0, z, 0), (0, 0, 0, 1))


def rotation(rng):
    q = [rng.gauss(0, 1) for _ in range(4)]
    n = math.sqrt(sum(v * v for v in q))
    x, y, z, w = (v / n for v in q)
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def scalar(rng):
    roll = rng.random()
    if roll < 0.15:
        return rng.choice(SCALARS)
    if roll < 0.3:
        return rng.randrange(-5, 6)
    if roll < 0.4:
        return math.ldexp(rng.uniform(0.5, 1), rng.randrange(-1074, 1024)) * rng.choice((-1, 1))
    return rng.uniform(-3, 3)


def matrix(rng):
    roll = rng.random()
    if roll < 0.4:
        r = rotation(rng)
        s = [rng.choice((1, 2, 0.5, -1, 1e-3, 1e100, 0)) if rng.random() < 0.3 else rng.uniform(0.1, 3) for _ in range(3)]
        rows = [[r[i][c] * s[c] for c in range(3)] + [rng.uniform(-10, 10)] for i in range(3)] + [[0, 0, 0, 1]]
        if rng.random() < 0.2:
            rows[rng.randrange(4)][rng.randrange(4)] += rng.choice((1e-12, 1e-9, 1e-7, 2e-7, 0.5, -1e-10))
    elif roll < 0.55:
        rows = [list(r) for r in diag(*(rng.choice((1, 2, HUGE, TINY, 1e200, 1e-200, 2**-1074, 0, -2)) for _ in range(3)))]
    elif roll < 0.85:
        rows = [[scalar(rng) if rng.random() < 0.1 else rng.uniform(-2, 2) for _ in range(4)] for _ in range(4)]
    else:
        rows = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        rows[rng.randrange(4)][rng.randrange(4)] = scalar(rng)
    shape = rng.random()
    if shape < 0.03:
        rows = rows[:3]
    elif shape < 0.06:
        rows[rng.randrange(4)] = rows[0][:3]
    elif shape < 0.08:
        rows = rows + [rows[0]]
    return tuple(map(tuple, rows)) if rng.random() < 0.5 else rows


def vector(rng, n):
    roll = rng.random()
    if roll < 0.5:
        v = [rng.uniform(-2, 2) for _ in range(n)]
    elif roll < 0.8:
        v = [scalar(rng) if rng.random() < 0.3 else rng.uniform(-2, 2) for _ in range(n)]
    else:
        v = [rng.choice((0, 0.0, -0.0, TINY, HUGE, 1)) for _ in range(n)]
    if rng.random() < 0.04:
        v = v[:-1] if v else v
    return tuple(v) if rng.random() < 0.5 else v


def quaternion(rng):
    roll = rng.random()
    if roll < 0.5:
        q = [rng.gauss(0, 1) for _ in range(4)]
        n = math.sqrt(sum(x * x for x in q)) * rng.choice((1, 1, 1, 1.0076, 0.9924, 1.0078, 0.9922, 2, 1e-200, 1e200))
        return tuple(x / n for x in q)
    if roll < 0.7:
        return rng.choice([(0, 0, 0, 1), (0, 0, 0, 2), (0, 0, 0, -2), (0, 0, 0, 0), (TINY, 0, 0, 1), (TINY, 0, 0, -1),
                           (HUGE, HUGE, 0, 0), (1e200, 0, 0, 1e200), (0, 0, -2, -2), (0, 0, -2, 0), (TINY, 1, 0, 0),
                           (-TINY, 0, 1, 0), (0, 0, 0, 1.0076)])
    return vector(rng, 4)


def fraction(rng):
    return rng.choice([0, 1, 0.5, 0.25, 0.9999, 1e-17, rng.random(), rng.random(), -0.1, 1.1, True, math.inf, TINY, 0.0])


def cases(count, seed):
    rng = random.Random(seed)
    out = [('h.IDENTITY', {}), ('h.UNIT_QUATERNION_TOLERANCE', {}), ('h.trs()', {}), ('h.trs(s=(0, 2, 3))', {}),
           ('h.inverse(h.trs(s=(0, 2, 3)))', {}), ('h.multiply(h.trs(t=(1, 2, 3)), h.IDENTITY)', {}),
           ('h.hermite((0,), (2,), (0,), (0,), .5, 2)', {}), ('h.slerp((0, 0, 0, 2), (0, 0, 0, -2), .5)', {})]
    for x in SCALARS:
        out += [('h._number(x, "/n")', {'x': x}), ('h._fraction(x)', {'x': x}), ('h.linear((0,), (1,), x)', {'x': x}),
                ('h.affine(h.IDENTITY, x)', {'x': x}), ('h.validate_trs(h.IDENTITY, tolerance=x)', {'x': x}),
                ('h.hermite((0,), (0,), (0,), (0,), .5, x)', {'x': x}), ('h.hermite((0,), (0,), (0,), (0,), .5, 2, x)', {'x': x})]
    makers = [
        lambda: ('h.matrix(v)', {'v': vector(rng, 16)}),
        lambda: ('h.column_major(a)', {'a': matrix(rng)}),
        lambda: ('h.multiply(a, b)', {'a': matrix(rng), 'b': matrix(rng)}),
        lambda: ('h.inverse(a)', {'a': matrix(rng)}),
        lambda: ('h.affine(a)', {'a': matrix(rng)}),
        lambda: ('h.affine(a, t, "/x")', {'a': matrix(rng), 't': rng.choice((0, 1e-9, 1e-7, 0.5, -1))}),
        lambda: ('h.transform(a, p)', {'a': matrix(rng), 'p': vector(rng, 3)}),
        lambda: ('h.normalize(q)', {'q': quaternion(rng)}),
        lambda: ('h.authored_quaternion(q)', {'q': quaternion(rng)}),
        lambda: ('h.authored_quaternion(q, "/nodes/1/rotation")', {'q': quaternion(rng)}),
        lambda: ('h.validate_trs(a)', {'a': matrix(rng)}),
        lambda: ('h.validate_trs(a, affine_tolerance=1e-12, ref="/nodes/0")', {'a': matrix(rng)}),
        lambda: ('h.validate_trs(a, tolerance=t)', {'a': matrix(rng), 't': rng.choice((1e-9, 1e-6, 0.5, 0, -1))}),
        lambda: ('h.trs(t, q, s)', {'t': vector(rng, 3), 'q': quaternion(rng), 's': vector(rng, 3)}),
        lambda: ('h.linear(a, b, t)', {'a': vector(rng, k), 'b': vector(rng, k), 't': fraction(rng)})
        if (k := rng.randrange(0, 5)) or True else None,
        lambda: ('h.slerp(a, b, t)', {'a': quaternion(rng), 'b': quaternion(rng), 't': fraction(rng)}),
        lambda: ('h.slerp(a, a, t)', {'a': quaternion(rng), 't': fraction(rng)}),
        lambda: ('h.hermite(a, b, c, d, t, dt)', {**dict(zip('abcd', (vector(rng, k) for _ in range(4)))),
                                                 't': fraction(rng), 'dt': rng.choice((2, 0.5, 2**-1074, HUGE, 16, 0, -1))})
        if (k := rng.randrange(0, 4)) or True else None,
        lambda: ('h.hermite(a, b, c, d, t, dt, quaternion=True)', {'a': quaternion(rng), 'b': vector(rng, 4), 'c': quaternion(rng),
                                                                   'd': vector(rng, 4), 't': fraction(rng), 'dt': rng.choice((2, 1e-3))}),
        lambda: (f'h.{rng.choice(("_add", "_sub", "_product", "_divide"))}(a, b, "/r")', {'a': scalar_float(rng), 'b': scalar_float(rng)}),
        lambda: ('h._sum(v, "/r")', {'v': [scalar_float(rng) for _ in range(rng.randrange(5))]}),
        lambda: ('h._vector(v, n, "/v")', {'v': vector(rng, 3), 'n': 3}),
        lambda: ('h._matrix(a)', {'a': matrix(rng)}),
    ]
    while len(out) < count:
        out.append(rng.choice(makers)())
    return out


def regressions():
    """The cases of the 0.3.0 math3d internal tests, retired with the Python module."""
    from test_core_semantic_fixes import encode, morph_asset
    from test_numerical_boundaries import COLUMNS, ROWS, node_asset
    bad_rows = lambda bad: [[bad, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    out = []
    for bad in (True, '1', math.inf, math.nan, 10**400):
        cols = list(COLUMNS); cols[0] = bad
        rows = [list(r) for r in ROWS]; rows[0][0] = bad
        out += [(e, {'rows': rows, 'cols': cols, 'bad': bad, 'b': bad_rows(bad)}) for e in (
            'h.matrix(cols)', 'h.column_major(rows)', 'h.multiply(rows, h.IDENTITY)', 'h.multiply(h.IDENTITY, rows)',
            'h.inverse(rows)', 'h.transform(rows, (0, 0, 0))', 'h.transform(h.IDENTITY, (bad, 0, 0))',
            'h.normalize((bad, 0, 0, 1))', 'h.trs((bad, 0, 0))', 'h.trs((0, 0, 0), (0, 0, 0, 1), (bad, 1, 1))',
            'h.slerp((0, 0, 0, 1), (bad, 0, 0, 1), .5)', 'h.affine(b)', 'h.validate_trs(b)', 'h.authored_quaternion((bad, 0, 0, 1))',
            'h.linear((bad,), (0,), .5)', 'h.hermite((0,), (bad,), (0,), (0,), .5, 2)', 'h.affine(h.IDENTITY, bad)',
            'h.validate_trs(h.IDENTITY, tolerance=bad)', 'h.hermite((0,), (0,), (0,), (0,), .5, bad)',
            'h.linear((bad,), (0,), 1)', 'h.linear((0,), (bad,), 0)', 'h.slerp((bad, 0, 0, 1), (0, 0, 0, 1), 1)',
            'h.slerp((0, 0, 0, 1), (bad, 0, 0, 1), 0)')]
    shapes = ['h.matrix([1] * 15)', 'h.matrix([1] * 17)', 'h.column_major([[1] * 4] * 3)', 'h.inverse([[1] * 3] * 4)',
              'h.multiply(h.IDENTITY, [[1] * 4] * 5)', 'h.transform(h.IDENTITY, (1, 2))', 'h.normalize((0, 0, 1))', 'h.trs((0, 0))',
              'h.slerp((0, 0, 1), (0, 0, 0, 1), .5)', 'h.affine([[1] * 4] * 3)', 'h.validate_trs([[1] * 4] * 3)',
              'h.authored_quaternion((0, 0, 1))', 'h.linear((1,), (1, 2), .5)', 'h.hermite((0,), (0, 0), (0,), (0,), .5, 2)',
              'h.hermite((), (), (), (), .5, 2)', 'h.hermite((1,), (0,), (1,), (0,), .5, 2, True)']
    out += [(e, {}) for e in shapes]
    controls = [
        'h.affine(h.IDENTITY, -1)', 'h.validate_trs(h.IDENTITY, tolerance=0)', 'h.linear((1e308,), (-1e308,), .5)',
        'h.hermite((0,), (0,), (0,), (0,), .5, True)', 'h.hermite((0,), (0,), (0,), (0,), .5, -1)',
        'h.normalize((1.5e308, 1.5e308, 0, 0))', 'h.trs((0, 0, 0), (2**-800, 0, 0, 1))',
        'h.validate_trs(((1, 2**-800, 0, 0), (2**-800, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))',
        'h.multiply(((1.5e308,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)), h.IDENTITY)',
        'h.multiply(((1.5e308,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)), ((2,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))',
        'h.multiply(((2**-800,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)), ((2**-800,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))',
        'h.multiply(((2**-1022,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)), ((.5,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))',
        'h.inverse(((2**-1074,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))',
        'h.inverse(((1e308,1e308,0,0),(-1e308,1e308,0,0),(0,0,1,0),(0,0,0,1)))',
        'h.inverse(((1e200,0,0,0),(0,1e200,0,0),(0,0,1e200,0),(0,0,0,1)))', 'h.inverse(((1e-200,0,0,0),(0,1e-200,0,0),(0,0,1e-200,0),(0,0,0,1)))',
        'h.normalize((1e200, 0, 0, 1e200))', 'h.normalize((0, 0, 0, 2))', 'h.normalize((0, 0, 0, 0))',
        'h.slerp((0, 0, 0, 2), (0, 0, 0, -2), .5)', 'h.slerp((0, 0, 0, 2), (0, 0, -2, -2), 1)', 'h.slerp((0, 0, 0, 2), (0, 0, -2, 0), 1)',
        'h.slerp((0, 0, 0, 2), (0, 0, 0, -2), 0)', 'h.slerp((2**-800, 1, 0, 0), (-2**-800, 0, 1, 0), 0)',
        'h.slerp((2**-800, 1, 0, 0), (-2**-800, 0, 1, 0), 1)', 'h.slerp((2**-800, 0, 0, 1), (2**-800, 0, 0, 1), .5)',
        'h.hermite((0,), (2,), (0,), (0,), .5, 2)', 'h.hermite((0, 0, 0, 2), (0, 0, 0, 0), (0, 0, 0, 2), (0, 0, 0, 0), .5, 2, True)',
        'h.hermite((0,), (2,), (0,), (0,), -.1, 2)', 'h.hermite((0,), (2,), (0,), (0,), .5, 0)', 'h.hermite((0,), (2,), (0,), (0,), .5, 2, 1)',
        'h.hermite((0,), (1.5e308,), (0,), (1.5e308,), .5, 16)', 'h.hermite((1,), (0,), (1,), (-0.,), .5, 2**-1074)',
        'h.hermite((1,), (0,), (1,), (-0.,), .5, 1.5e308)', 'h.hermite((2,), (0,), (3,), (0,), 0, 2**-1074)',
        'h.hermite((2,), (0,), (3,), (0,), 1, 2**-1074)', 'h.hermite((1, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0), (0, 0, 0, 0), .5, 2**-1074, True)',
        'h.hermite((0,), (-2,), (0,), (4,), .5, 2)', 'h.hermite((0, 0, 0, 1), (0, 0, 2, 0), (0, 0, 0, 1), (0, 0, -2, 0), .5, 2, True)',
        'h.hermite((1,), (1,), (1,), (0,), .5, 2**-1074)', 'h.hermite((1,), (0,), (1,), (1,), .5, 2**-1074)',
        'h.hermite((1,), (1.5e308,), (1,), (0,), .5, 16)', 'h.hermite((1,), (0,), (1,), (1.5e308,), .5, 16)',
        'h.hermite((1,), (0,), (1,), (0,), quaternion=1, fraction=.5, duration=2)', 'h.hermite((1,), (0,), (1,), (0,), fraction=True, duration=2)',
        'h.linear((1.5e308,), (-1.5e308,), 0)', 'h.linear((1.5e308,), (-1.5e308,), 1)', 'h.linear((2, 4), (6, 8), .5)',
        'h.linear((0,), (2**-800,), 2**-800)', 'h.trs(s=(0, 2, 3))', 'h.column_major(h.matrix(c))', 'h.transform(h.matrix(c), (1, 2, 3))',
        'h.transform(h.inverse(h.matrix(c)), (5, -2, 17))', 'h.transform(((1,0,0,0),(0,1,0,0),(0,0,1,0),(.5e-7,0,0,1)), (0, 0, 0))',
        'h.transform(((1,0,0,0),(0,1,0,0),(0,0,1,0),(2e-7,0,0,1)), (0, 0, 0))', 'h.transform(((1,0,0,0),(0,1,0,0),(0,0,1,0),(.5,0,0,1)), (0, 0, 0))',
        'h.validate_trs(((1,.5e-9,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))', 'h.validate_trs(((1,2e-9,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))',
        'h.authored_quaternion((0, 0, 0, 1.0076))', 'h.authored_quaternion((0, 0, 0, 0.9924))', 'h.authored_quaternion((0, 0, 0, 1.0078))',
        'h.authored_quaternion((0, 0, 0, 0.9922))']
    out += [(e, {'c': list(COLUMNS)}) for e in controls]
    for size in (1e200, 1.5e308):
        a = (size, size, 0, 0, size, size, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        out.append(('m.reparent_local(a, (1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1))', {'a': a}))
    for a in ((-2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0, 0, 0, 0, 1), (1e200, 0, 0, 0, 0, 1e200, 0, 0, 0, 0, 1e200, 0, 0, 0, 0, 1),
              (1e-200, 0, 0, 0, 0, 1e-200, 0, 0, 0, 0, 1e-200, 0, 0, 0, 0, 1)):
        out.append(('m.reparent_local(a, h.column_major(h.IDENTITY))', {'a': a}))
    for value in (.5e-12, 2e-12):
        cols = [1, 0, 0, value, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        out.append(("m.inspect_asset(raw, 'gltf')", {'raw': encode(node_asset({'matrix': cols}))}))
    out.append(("m.evaluate_geometry(m.inspect_asset(raw, 'gltf').value)", {'raw': encode(node_asset({'scale': [0, 2, 3]}))}))
    d = morph_asset(skin=True); d['nodes'][0]['scale'] = [0, 1, 1]
    out.append(("m.evaluate_geometry(m.inspect_asset(raw, 'gltf').value)", {'raw': encode(d)}))
    return out


def skinned_asset(rng):
    """A random skinned glTF: 1-3 influence sets, palette joints in a TRS hierarchy, some invalid on purpose."""
    from test_core_semantic_fixes import AssetBytes, encode
    b = AssetBytes()
    vertices, joints, sets = rng.randrange(1, 6), rng.randrange(1, 6), rng.randrange(1, 4)
    attrs = {'POSITION': b.rows([tuple(rng.uniform(-2, 2) for _ in range(3)) for _ in range(vertices)], 'VEC3', bounds=True)}
    influence = []
    for _ in range(vertices):
        # Distinct joints carry the positive weights, which are dyadic so they sum to one exactly.
        positive = rng.sample(range(joints), rng.randrange(1, min(4 * sets, joints) + 1))
        shares = [1.0]
        while len(shares) < len(positive):
            shares.sort()
            half = shares.pop() / 2
            shares += [half, half]
        slots = rng.sample(range(4 * sets), len(positive))
        indices = [rng.randrange(joints) for _ in range(4 * sets)]
        weights = [0.0] * (4 * sets)
        for slot, joint, share in zip(slots, positive, shares):
            indices[slot], weights[slot] = joint, share
        if rng.random() < 0.03:
            weights[slots[0]] += 0.01
        if rng.random() < 0.03:
            indices[rng.randrange(4 * sets)] = joints
        influence.append((indices, weights))
    for s in range(sets):
        attrs[f'JOINTS_{s}'] = b.rows([tuple(i[4 * s:4 * s + 4]) for i, _ in influence], 'VEC4', rng.choice((5121, 5123)))
        attrs[f'WEIGHTS_{s}'] = b.rows([tuple(w[4 * s:4 * s + 4]) for _, w in influence], 'VEC4')
    def trs_node(**extra):
        node = dict(extra)
        if rng.random() < 0.7:
            node['translation'] = [rng.uniform(-3, 3) for _ in range(3)]
        if rng.random() < 0.7:
            q = [rng.gauss(0, 1) for _ in range(4)]
            n = math.sqrt(sum(x * x for x in q))
            node['rotation'] = [x / n for x in q]
        if rng.random() < 0.5:
            node['scale'] = [rng.choice((1, 2, 0.5, rng.uniform(0.2, 3), 0 if rng.random() < 0.05 else 1)) for _ in range(3)]
        return node
    ibms = []
    for _ in range(joints):
        r = rotation(rng)
        m = [r[i][c] * rng.choice((1, 2, 0.5)) for c in range(3) for i in range(3)]
        cols = m[0:3] + [0] + m[3:6] + [0] + m[6:9] + [0] + [rng.uniform(-2, 2) for _ in range(3)] + [1]
        if rng.random() < 0.03:
            cols[3] = 0.5
        ibms.append(tuple(cols))
    ibm = b.rows(ibms, 'MAT4')
    nodes = [trs_node(mesh=0, skin=0)] + [trs_node() for _ in range(joints)]
    for j in range(2, joints + 1):
        nodes[rng.randrange(1, j)].setdefault('children', []).append(j)
    roots = [i for i in range(len(nodes)) if not any(i in n.get('children', ()) for n in nodes)]
    skin = {'joints': list(range(1, joints + 1))}
    if rng.random() < 0.9:
        skin['inverseBindMatrices'] = ibm
    d = b.document(meshes=[{'primitives': [{'mode': 0, 'attributes': attrs}]}], nodes=nodes, skins=[skin], scenes=[{'nodes': roots}])
    return encode(d)


def scalar_float(rng):
    x = scalar(rng)
    return float(x) if type(x) in (int, float) and abs(x) < 1e308 else rng.uniform(-1, 1)


class ExactAlgorithms(unittest.TestCase):
    def hypot_mismatches(self, count, n, seed):
        rng = random.Random(seed)
        values = array('d', rng.randbytes(8 * n * count))
        for i, x in enumerate(values):
            if not math.isfinite(x) or rng.random() < 0.5:
                values[i] = rng.choice((rng.uniform(-1, 1), math.ldexp(rng.random(), rng.randrange(-1074, 1024)), 0.0, -0.0))
        if rng.random() < 0.5:
            values[0] = math.inf
        actual = array('d', core._hypot_batch(values.tobytes(), n))
        return sum(a != math.hypot(*values[i * n:(i + 1) * n]) and not (math.isnan(a) and math.isnan(math.hypot(*values[i * n:(i + 1) * n])))
                   for i, a in enumerate(actual))

    def test_hypot_matches_math_hypot(self):
        for n in (2, 3, 4, 7):
            with self.subTest(n=n):
                self.assertEqual(self.hypot_mismatches(5000, n, n), 0)
        for v in ([], [3], [-0.0], [math.nan, math.inf], [math.inf, math.nan], [math.nan, 1], [2**-1074] * 4, [1e308] * 4):
            self.assertEqual(repr(core._hypot(v)), repr(math.hypot(*v)), v)

    @unittest.skipUnless(GATE, 'gate tier: MSF_GATE=1')
    def test_a_million_vectors_per_arity_match_math_hypot(self):
        for n in (3, 4):
            with self.subTest(n=n):
                self.assertEqual(self.hypot_mismatches(10**6, n, 100 + n), 0)

    def test_fsum_matches_math_fsum(self):
        rng = random.Random(11)
        pools = [[1e308, -1e308, 1e308], [1e308, 1e308, -1e308], [1e-16, 1, 1e16], [math.inf, -math.inf], [math.inf, 1],
                 [math.nan], [0.1] * 10, [], [-0.0], [-0.0, -0.0], [2**-1074, -2**-1074], [1e100, 1, -1e100, 1e-100]]
        for _ in range(3000 if not GATE else 100000):
            pools.append([rng.choice((rng.uniform(-1, 1) * 10**rng.randrange(-20, 20), math.ldexp(rng.uniform(-1, 1), rng.randrange(-1074, 1024)),
                                      0.1, -0.1, 1e16, 1.0, -1.0)) for _ in range(rng.randrange(12))])
        for values in pools:
            try:
                expected = ('value', repr(math.fsum(values)))
            except (OverflowError, ValueError) as exc:
                expected = ('error', type(exc).__name__, str(exc))
            try:
                actual = ('value', repr(core._fsum(values)))
            except (OverflowError, ValueError) as exc:
                actual = ('error', type(exc).__name__, str(exc))
            self.assertEqual(actual, expected, values)


@unittest.skipIf(oracle.skip_reason(), oracle.skip_reason())
class AgainstTheOracle(unittest.TestCase):
    def test_retired_internal_cases_match_the_oracle(self):
        self.assertEqual(oracle.differ(regressions())[:3], [])

    def test_n_influence_skinning_matches_the_oracle(self):
        rng = random.Random(31)
        expression = "(lambda r: m.evaluate_geometry(r.value) if r.ok else r)(m.inspect_asset(raw, 'gltf'))"
        cases = [(expression, {'raw': skinned_asset(rng)}) for _ in range(3000 if GATE else 25)]
        for name in ('eight-influence.gltf', 'eight-weighted.gltf', 'simple-skin.gltf'):
            cases.append((expression, {'raw': (oracle.ROOT / 'tests/public/fixtures' / name).read_bytes()}))
        self.assertEqual(oracle.differ(cases)[:3], [])
        evaluated = sum(oracle.outcome(*case)[1][1][0] == 'record' for case in cases)
        self.assertGreater(evaluated, len(cases) // 2, 'too few random assets evaluated')

    def test_math3d_matches_the_oracle(self):
        mismatches = oracle.differ(cases(100000 if GATE else 1500, 20261027))
        self.assertEqual(mismatches[:3], [])


if __name__ == '__main__':
    unittest.main()
