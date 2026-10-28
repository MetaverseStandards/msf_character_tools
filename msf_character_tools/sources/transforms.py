# SPDX-License-Identifier: MIT
"""Matrix decomposition shared by source adapters.

Matrices are 16 numbers in glTF column-major order. That is also USD's
row-major order for its row-vector matrices, so `GfMatrix4d` entries can be
passed straight through. Implemented in the C++ core (core/src/source_helpers.cpp).
"""
from .. import _native

_core = _native.built


def is_affine(matrix):
    return _core._is_affine(matrix)


def has_shear(matrix):
    """True when two axes of the linear part are not perpendicular.

    Rotation combined with uniform or non-uniform scale keeps the axes
    perpendicular, so it never counts as shear.
    """
    return _core._has_shear(matrix)


def determinant(matrix):
    return _core._determinant(matrix)


def decompose(matrix):
    """Return (translation, rotation xyzw, scale) for an affine, shear-free, nonsingular matrix.

    A negative determinant becomes a negative X scale, which is lossless. Callers
    check `is_affine` and `has_shear` first; a singular matrix raises ValueError.
    """
    return _core._decompose(matrix)
