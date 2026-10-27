# SPDX-License-Identifier: MIT
"""Matrix decomposition shared by source adapters.

Matrices are 16 numbers in glTF column-major order. That is also USD's
row-major order for its row-vector matrices, so `GfMatrix4d` entries can be
passed straight through.
"""
import math

SHEAR_TOLERANCE = 1e-6
TINY = 1e-150


def columns(matrix):
    return [matrix[4 * c:4 * c + 3] for c in range(3)]


def is_affine(matrix):
    return tuple(matrix[3::4]) == (0.0, 0.0, 0.0, 1.0)


def has_shear(matrix):
    """True when two axes of the linear part are not perpendicular.

    Rotation combined with uniform or non-uniform scale keeps the axes
    perpendicular, so it never counts as shear.
    """
    axes = columns(matrix)
    norms = [math.sqrt(math.fsum(x * x for x in a)) for a in axes]
    if min(norms) == 0:
        return False
    for i, j in ((0, 1), (0, 2), (1, 2)):
        cosine = math.fsum(a * b for a, b in zip(axes[i], axes[j])) / (norms[i] * norms[j])
        if abs(cosine) > SHEAR_TOLERANCE:
            return True
    return False


def determinant(matrix):
    a, b, c = columns(matrix)
    return (a[0] * (b[1] * c[2] - b[2] * c[1]) - b[0] * (a[1] * c[2] - a[2] * c[1])
            + c[0] * (a[1] * b[2] - a[2] * b[1]))


def _quaternion(r):
    """Unit quaternion (x, y, z, w) of a rotation matrix given as r[row][column]."""
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0:
        s = 2 * math.sqrt(trace + 1)
        q = ((r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s, s / 4)
    elif r[0][0] >= r[1][1] and r[0][0] >= r[2][2]:
        s = 2 * math.sqrt(1 + r[0][0] - r[1][1] - r[2][2])
        q = (s / 4, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s, (r[2][1] - r[1][2]) / s)
    elif r[1][1] >= r[2][2]:
        s = 2 * math.sqrt(1 + r[1][1] - r[0][0] - r[2][2])
        q = ((r[0][1] + r[1][0]) / s, s / 4, (r[1][2] + r[2][1]) / s, (r[0][2] - r[2][0]) / s)
    else:
        s = 2 * math.sqrt(1 + r[2][2] - r[0][0] - r[1][1])
        q = ((r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, s / 4, (r[1][0] - r[0][1]) / s)
    norm = math.sqrt(math.fsum(x * x for x in q))
    q = tuple(x / norm for x in q)
    return q if q[3] >= 0 else tuple(-x for x in q)


def decompose(matrix):
    """Return (translation, rotation xyzw, scale) for an affine, shear-free, nonsingular matrix.

    A negative determinant becomes a negative X scale, which is lossless. Callers
    check `is_affine` and `has_shear` first; a singular matrix raises ValueError.
    """
    axes = columns(matrix)
    scale = [math.sqrt(math.fsum(x * x for x in a)) for a in axes]
    if min(scale) == 0:
        raise ValueError("Transform is singular.")
    if determinant(matrix) < 0:
        scale[0] = -scale[0]
    unit = [[x / s for x in a] for a, s in zip(axes, scale)]
    rotation = [[unit[c][r] for c in range(3)] for r in range(3)]
    return _clean(matrix[12:15]), _clean(_quaternion(rotation)), _clean(scale)


def _clean(values):
    # Components this small are rounding noise; squaring them would underflow binary64 in later checks.
    return tuple(0.0 if abs(x) < TINY else float(x) for x in values)
