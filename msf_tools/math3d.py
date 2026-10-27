# SPDX-License-Identifier: MIT
"""Checked binary64 column-vector math; internal matrices contain row tuples.

Implemented in the C++ core (core/src/math3d.cpp, core/python/math_module.cpp).
"""
from ._core import (IDENTITY, UNIT_QUATERNION_TOLERANCE, _add, _divide, _finite, _fraction, _matrix, _number,  # noqa: F401
                    _product, _sub, _sum, _vector, affine, authored_quaternion, column_major, hermite, inverse, linear,
                    matrix, multiply, normalize, slerp, transform, trs, validate_trs)
