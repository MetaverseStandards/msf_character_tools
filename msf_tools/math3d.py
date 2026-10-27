# SPDX-License-Identifier: MIT
"""Checked binary64 column-vector math; internal matrices contain row tuples."""
import math
from .report import fail

IDENTITY = tuple(tuple(float(i == j) for j in range(4)) for i in range(4))


def _number(value, ref):
    if type(value) not in (int, float):
        fail('E_TYPE', ref, 'Expected an integer or float; booleans are not numeric.')
    try:
        result = float(value)
    except OverflowError:
        fail('E_NONFINITE', ref, 'Value is not representable in binary64.')
    return _finite(result, ref)


def _finite(value, ref):
    if not math.isfinite(value):
        fail('E_NONFINITE', ref, 'Numeric input or intermediate overflows binary64.')
    return value


def _vector(values, count, ref):
    if not isinstance(values, (list, tuple)) or len(values) != count:
        fail('E_SHAPE', ref, f'Expected exactly {count} numeric components.')
    return tuple(_number(x, ref) for x in values)


def _matrix(rows, ref='/transforms'):
    if not isinstance(rows, (list, tuple)) or len(rows) != 4:
        fail('E_SHAPE', ref, 'Expected four matrix rows.')
    return tuple(_vector(row, 4, ref) for row in rows)


def _add(a, b, ref):
    return _finite(a + b, ref)


def _sub(a, b, ref):
    return _finite(a - b, ref)


def _product(a, b, ref):
    result = _finite(a * b, ref)
    if result == 0 and a != 0 and b != 0:
        fail('E_NONFINITE', ref, 'Nonzero product underflows binary64 to zero.')
    return result


def _divide(a, b, ref):
    if b == 0:
        fail('E_SINGULAR', ref, 'Division requires a nonzero divisor.')
    result = _finite(a / b, ref)
    if result == 0 and a != 0:
        fail('E_NONFINITE', ref, 'Nonzero quotient underflows binary64 to zero.')
    return result


def _sum(values, ref):
    result = 0.0
    for value in values:
        result = _add(result, value, ref)
    return result


def _dot(a, b, ref):
    return _sum((_product(x, y, ref) for x, y in zip(a, b)), ref)


def matrix(values):
    """Convert exactly 16 glTF column-major values into detached row tuples."""
    values = _vector(values, 16, '/transforms')
    return tuple(tuple(values[c * 4 + r] for c in range(4)) for r in range(4))


def column_major(m):
    """Convert a row matrix into a detached glTF column-major list."""
    m = _matrix(m)
    return [m[r][c] for c in range(4) for r in range(4)]


def multiply(a, b):
    """Generic matrix product a*b; b acts first on a column vector."""
    a, b = _matrix(a), _matrix(b)
    return tuple(tuple(_dot(a[r], tuple(b[k][c] for k in range(4)), '/transforms')
                       for c in range(4)) for r in range(4))


def inverse(m):
    """Partial-pivot inverse; exact zero pivots and unsafe arithmetic refuse."""
    m = _matrix(m)
    a = [list(row) + list(IDENTITY[i]) for i, row in enumerate(m)]
    for i in range(4):
        pivot = max(range(i, 4), key=lambda j: abs(a[j][i]))
        if a[pivot][i] == 0:
            fail('E_SINGULAR', '/transforms', 'Matrix has no inverse.')
        a[i], a[pivot] = a[pivot], a[i]
        divisor = a[i][i]
        a[i] = [_divide(x, divisor, '/transforms') for x in a[i]]
        for j in range(4):
            if j != i:
                factor = a[j][i]
                a[j] = [_sub(x, _product(factor, y, '/transforms'), '/transforms')
                        for x, y in zip(a[j], a[i])]
    return tuple(tuple(row[4:]) for row in a)


def affine(m, tolerance=1e-7, ref='/transforms'):
    """Validate the complete affine bottom row, independently of any point."""
    m = _matrix(m, ref)
    tolerance = _number(tolerance, ref)
    if tolerance < 0:
        fail('E_TRANSFORM', ref, 'Affine tolerance must be nonnegative.')
    if any(abs(_sub(x, y, ref)) > tolerance for x, y in zip(m[3], IDENTITY[3])):
        fail('E_TRANSFORM', ref, 'Position matrix must have affine bottom row [0,0,0,1].')
    return m


def transform(m, p):
    m, p = affine(m), _vector(p, 3, '/transforms')
    return tuple(_dot(row, p + (1.0,), '/transforms') for row in m[:3])


def _norm(values, ref, zero_code):
    length = _finite(math.hypot(*values), ref)
    if length == 0:
        fail(zero_code, ref, 'Normalization requires a nonzero length.')
    return length


def normalize(q):
    """Normalize XYZW, retaining the existing finite nonunit helper policy."""
    q = _vector(q, 4, '/rotation')
    length = _norm(q, '/rotation', 'E_QUATERNION')
    return tuple(_divide(x, length, '/rotation') for x in q)


# The Khronos glTF-Validator's unit-length limit for quaternions (unitLengthThresholdVec4).
UNIT_QUATERNION_TOLERANCE = 0.00769


def authored_quaternion(q, ref='/rotation'):
    """Check an authored quaternion is unit length within the glTF-Validator's limit.

    The value is returned as authored; trs() and slerp normalize it before use.
    """
    q = _vector(q, 4, ref)
    length = math.hypot(*q)
    if not math.isfinite(length) or abs(length - 1.0) > UNIT_QUATERNION_TOLERANCE:
        fail('E_QUATERNION', ref, 'Authored quaternion must be unit length.')
    return q


def validate_trs(m, *, affine_tolerance=1e-9, tolerance=1e-9, ref='/transforms'):
    """Validate nonzero normalized axes, orthogonality and |det| near one.

    Reflections are decomposable with signed scale. No condition-number cutoff or
    raw determinant of potentially huge/tiny columns is used.
    """
    m = affine(m, affine_tolerance, ref)
    tolerance = _number(tolerance, ref)
    if tolerance <= 0:
        fail('E_TRANSFORM', ref, 'TRS tolerance must be positive.')
    axes = [tuple(m[r][c] for r in range(3)) for c in range(3)]
    lengths = [_norm(axis, ref, 'E_SINGULAR') for axis in axes]
    unit = [tuple(_divide(x, length, ref) for x in axis) for axis, length in zip(axes, lengths)]
    if any(abs(_dot(unit[i], unit[j], ref)) > tolerance for i in range(3) for j in range(i)):
        fail('E_SHEAR', ref, 'Matrix cannot be represented by TRS without shear.')
    a, b, c = unit
    cross = (_sub(_product(b[1], c[2], ref), _product(b[2], c[1], ref), ref),
             _sub(_product(b[2], c[0], ref), _product(b[0], c[2], ref), ref),
             _sub(_product(b[0], c[1], ref), _product(b[1], c[0], ref), ref))
    determinant = _dot(a, cross, ref)
    if determinant == 0:
        fail('E_SINGULAR', ref, 'Normalized matrix determinant is zero.')
    if abs(_sub(abs(determinant), 1.0, ref)) > tolerance:
        fail('E_SHEAR', ref, 'Normalized matrix determinant must have magnitude near one.')
    return m


def trs(t=(0, 0, 0), q=(0, 0, 0, 1), s=(1, 1, 1)):
    t, s = _vector(t, 3, '/transforms'), _vector(s, 3, '/transforms')
    x, y, z, w = normalize(q)
    ref = '/rotation'
    xx, yy, zz = (_product(v, v, ref) for v in (x, y, z))
    xy, xz, yz = (_product(a, b, ref) for a, b in ((x,y),(x,z),(y,z)))
    xw, yw, zw = (_product(a, w, ref) for a in (x,y,z))
    def diagonal(a, b):
        return _sub(1.0, _product(2.0, _add(a, b, ref), ref), ref)
    def twice(value):
        return _product(2.0, value, ref)
    rot = ((diagonal(yy, zz), twice(_sub(xy, zw, ref)), twice(_add(xz, yw, ref))),
           (twice(_add(xy, zw, ref)), diagonal(xx, zz), twice(_sub(yz, xw, ref))),
           (twice(_sub(xz, yw, ref)), twice(_add(yz, xw, ref)), diagonal(xx, yy)))
    return tuple(tuple(_product(rot[r][c], s[c], '/transforms') for c in range(3)) +
                 (t[r],) for r in range(3)) + (IDENTITY[3],)


def _fraction(value):
    value = _number(value, '/animations')
    if not 0 <= value <= 1:
        fail('E_FRACTION', '/animations', 'Interpolation fraction must lie in [0,1].')
    return value


def linear(a, b, fraction):
    """Ordered component interpolation with checked subtraction and products."""
    if not isinstance(a, (tuple, list)) or not a:
        fail('E_SHAPE', '/animations', 'Curve components must be nonempty.')
    a, b = _vector(a, len(a), '/animations'), _vector(b, len(a), '/animations')
    t = _fraction(fraction)
    if t == 0:
        return a
    if t == 1:
        return b
    return tuple(_add(x, _product(t, _sub(y, x, '/animations'), '/animations'), '/animations')
                 for x, y in zip(a, b))


def _endpoint_negative_dot(a, b):
    """Endpoint hemisphere: ordered rounded dot; a zero tie retains b's sign.

    Certain rounded-zero products need no multiplication. The remaining bounded
    products select a sign only; interior interpolation still uses checked _dot.
    """
    dot = 0.0
    for x, y in zip(a, b):
        if x == 0 or y == 0 or math.frexp(x)[1] + math.frexp(y)[1] <= -1075:
            term = 0.0
        else:
            term = x * y
        dot = _add(dot, term, '/rotation')
    return dot < 0


def slerp(a, b, t):
    a, b, t = normalize(a), normalize(b), _fraction(t)
    if t == 0:
        return a
    if t == 1:
        return tuple(-x for x in b) if _endpoint_negative_dot(a, b) else b
    ref = '/rotation'
    dot = _dot(a, b, ref)
    if dot < 0:
        b = tuple(-x for x in b)
        dot = -dot
    dot = min(1.0, dot)
    if dot > 0.9995:
        return normalize(linear(a, b, t))
    angle = _finite(math.acos(dot), ref)
    divisor = _finite(math.sin(angle), ref)
    a_weight = _divide(math.sin(_product(_sub(1.0, t, ref), angle, ref)), divisor, ref)
    b_weight = _divide(math.sin(_product(t, angle, ref)), divisor, ref)
    return normalize(tuple(_add(_product(a_weight, x, ref), _product(b_weight, y, ref), ref)
                           for x, y in zip(a, b)))


def hermite(p0, out0, p1, in1, fraction, duration, quaternion=False):
    """Duration-scaled cubic Hermite; quaternion tangents remain raw."""
    ref = '/animations'
    if type(quaternion) is not bool:
        fail('E_TYPE', ref, 'Quaternion mode must be an exact bool.')
    if not isinstance(p0, (list, tuple)) or not p0 or quaternion and len(p0) != 4:
        fail('E_SHAPE', ref, 'Curve needs nonempty matching components (four for quaternion).')
    p0, out0, p1, in1 = (_vector(v, len(p0), ref) for v in (p0, out0, p1, in1))
    t, dt = _fraction(fraction), _number(duration, ref)
    if dt <= 0:
        fail('E_CURVE', ref, 'Hermite duration must be positive.')
    t2 = _product(t, t, ref); t3 = _product(t2, t, ref)
    twice_t2 = _product(2.0, t2, ref)
    thrice_t2 = _product(3.0, t2, ref)
    twice_t3 = _product(2.0, t3, ref)
    h00 = _add(_sub(twice_t3, thrice_t2, ref), 1.0, ref)
    h10 = _add(_sub(t3, twice_t2, ref), t, ref)
    h01 = _add(-twice_t3, thrice_t2, ref)
    h11 = _sub(t3, t2, ref)
    result = tuple(_sum((_product(h00,a,ref),
                         0.0 if b == 0 else _product(_product(h10,dt,ref),b,ref),
                         _product(h01,c,ref),
                         0.0 if d == 0 else _product(_product(h11,dt,ref),d,ref)),ref)
                   for a,b,c,d in zip(p0,out0,p1,in1))
    return normalize(result) if quaternion else result
