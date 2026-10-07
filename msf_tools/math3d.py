# SPDX-License-Identifier: MIT
"""Binary64 column-vector math. Matrices are row tuples internally."""
import math
from .report import fail

IDENTITY = tuple(tuple(float(i == j) for j in range(4)) for i in range(4))


def matrix(values):
    return tuple(tuple(float(values[c * 4 + r]) for c in range(4)) for r in range(4))


def column_major(m):
    return [m[r][c] for c in range(4) for r in range(4)]


def multiply(a, b):
    return tuple(tuple(sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)) for r in range(4))


def inverse(m):
    a = [list(row) + list(IDENTITY[i]) for i, row in enumerate(m)]
    for i in range(4):
        pivot = max(range(i, 4), key=lambda j: abs(a[j][i]))
        if a[pivot][i] == 0 or not math.isfinite(a[pivot][i]):
            fail("E_SINGULAR", "/transforms", "Matrix has no finite inverse.")
        a[i], a[pivot] = a[pivot], a[i]
        v = a[i][i]
        a[i] = [x / v for x in a[i]]
        for j in range(4):
            if j != i:
                v = a[j][i]
                a[j] = [x - v * y for x, y in zip(a[j], a[i])]
    result = tuple(tuple(row[4:]) for row in a)
    if not all(math.isfinite(x) for row in result for x in row):
        fail("E_SINGULAR", "/transforms", "Inverse overflows binary64.")
    return result


def transform(m, p):
    v = tuple(p) + (1.0,)
    out = tuple(sum(m[r][c] * v[c] for c in range(4)) for r in range(4))
    if abs(out[3] - 1.0) > 1e-7:
        fail("E_TRANSFORM", "/transforms", "Position transform must be affine.")
    return out[:3]


def normalize(q):
    length = math.sqrt(sum(x * x for x in q))
    if not length or not math.isfinite(length):
        fail("E_QUATERNION", "/rotation", "Quaternion normalization is undefined.")
    return tuple(x / length for x in q)


def trs(t=(0, 0, 0), q=(0, 0, 0, 1), s=(1, 1, 1)):
    x, y, z, w = normalize(q)
    rot = ((1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)),
           (2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)),
           (2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)))
    return tuple(tuple(rot[r][c] * s[c] for c in range(3)) + (float(t[r]),) for r in range(3)) + ((0.0, 0.0, 0.0, 1.0),)


def slerp(a, b, t):
    a, b = normalize(a), normalize(b)
    dot = sum(x*y for x, y in zip(a, b))
    if dot < 0:
        b = tuple(-x for x in b)
        dot = -dot
    dot = min(1.0, dot)
    if dot > 0.9995:
        return normalize(tuple(x + t * (y-x) for x, y in zip(a, b)))
    angle = math.acos(dot)
    a_weight, b_weight = math.sin((1-t)*angle) / math.sin(angle), math.sin(t*angle) / math.sin(angle)
    return tuple(a_weight*x + b_weight*y for x, y in zip(a, b))
