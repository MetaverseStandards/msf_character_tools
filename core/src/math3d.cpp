// SPDX-License-Identifier: MIT AND PSF-2.0
#include "msf/math3d.hpp"

#include <cfloat>
#include <cmath>

#include "msf/diagnostics.hpp"

namespace msf::math3d {

const Mat kIdentity = {{{1.0, 0.0, 0.0, 0.0}, {0.0, 1.0, 0.0, 0.0}, {0.0, 0.0, 1.0, 0.0}, {0.0, 0.0, 0.0, 1.0}}};

double finite(double value, const std::string& ref) {
    if (!std::isfinite(value)) fail(Code::E_NONFINITE, ref, "Numeric input or intermediate overflows binary64.");
    return value;
}

double add(double a, double b, const std::string& ref) { return finite(a + b, ref); }

double sub(double a, double b, const std::string& ref) { return finite(a - b, ref); }

double product(double a, double b, const std::string& ref) {
    double result = finite(a * b, ref);
    if (result == 0 && a != 0 && b != 0) fail(Code::E_NONFINITE, ref, "Nonzero product underflows binary64 to zero.");
    return result;
}

double divide(double a, double b, const std::string& ref) {
    if (b == 0) fail(Code::E_SINGULAR, ref, "Division requires a nonzero divisor.");
    double result = finite(a / b, ref);
    if (result == 0 && a != 0) fail(Code::E_NONFINITE, ref, "Nonzero quotient underflows binary64 to zero.");
    return result;
}

double dot(const double* a, const double* b, std::size_t n, const std::string& ref) {
    double result = 0.0;
    for (std::size_t i = 0; i < n; ++i) result = add(result, product(a[i], b[i], ref), ref);
    return result;
}

// ---------------------------------------------------------------- hypot

// Derived from vector_norm() in CPython 3.12.15's Modules/mathmodule.c
// (PSF-2.0; see NOTICE.md and LICENSES/PSF-2.0.txt). Modified: translated to
// C++. It squares losslessly with an explicit fma, which -ffp-contract=off
// leaves alone.
namespace {

struct DoubleLength {
    double hi, lo;
};

DoubleLength fast_sum(double a, double b) {
    double x = a + b;
    return {x, (a - x) + b};
}

DoubleLength exact_product(double x, double y) {
    double z = x * y;
    return {z, std::fma(x, y, -z)};
}

double vector_norm(std::size_t n, double* vec, double max, bool found_nan) {
    if (std::isinf(max)) return max;
    if (found_nan) return NAN;
    if (max == 0.0 || n <= 1) return max;
    int max_e;
    std::frexp(max, &max_e);
    if (max_e < -1023) {
        for (std::size_t i = 0; i < n; ++i) vec[i] /= DBL_MIN;  // subnormals to normals
        return DBL_MIN * vector_norm(n, vec, max / DBL_MIN, found_nan);
    }
    double scale = std::ldexp(1.0, -max_e), csum = 1.0, frac1 = 0.0, frac2 = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        double x = vec[i] * scale;
        DoubleLength pr = exact_product(x, x);
        DoubleLength sm = fast_sum(csum, pr.hi);
        csum = sm.hi;
        frac1 += pr.lo;
        frac2 += sm.lo;
    }
    double h = std::sqrt(csum - 1.0 + (frac1 + frac2));
    DoubleLength pr = exact_product(-h, h);
    DoubleLength sm = fast_sum(csum, pr.hi);
    csum = sm.hi;
    frac1 += pr.lo;
    frac2 += sm.lo;
    double x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    return h / scale;
}

}  // namespace

double hypot(const double* values, std::size_t n) {
    std::vector<double> coordinates(n);
    double max = 0.0;
    bool found_nan = false;
    for (std::size_t i = 0; i < n; ++i) {
        double x = std::fabs(values[i]);
        coordinates[i] = x;
        found_nan |= std::isnan(x);
        if (x > max) max = x;
    }
    return vector_norm(n, coordinates.data(), max, found_nan);
}

// ---------------------------------------------------------------- fsum

// Shewchuk's exact partials (Adaptive Precision Floating-Point Arithmetic,
// 1997), with the final rounding and special-value rules of math_fsum() in
// CPython 3.12.15's Modules/mathmodule.c (PSF-2.0; see NOTICE.md). Modified:
// translated to C++ over an array.
FsumOutcome fsum(const double* values, std::size_t n) {
    std::vector<double> partials;
    double special_sum = 0.0, inf_sum = 0.0;
    for (std::size_t k = 0; k < n; ++k) {
        double x = values[k], xsave = x;
        std::size_t i = 0;
        for (std::size_t j = 0; j < partials.size(); ++j) {
            double y = partials[j];
            if (std::fabs(x) < std::fabs(y)) std::swap(x, y);
            double hi = x + y;
            double lo = y - (hi - x);
            if (lo != 0.0) partials[i++] = lo;
            x = hi;
        }
        partials.resize(i);
        if (x != 0.0) {
            if (!std::isfinite(x)) {
                // From overflow, or from a nan or inf among the summands.
                if (std::isfinite(xsave)) return {FsumOutcome::Status::overflow, 0.0};
                if (std::isinf(xsave)) inf_sum += xsave;
                special_sum += xsave;
                partials.clear();
            } else {
                partials.push_back(x);
            }
        }
    }
    if (special_sum != 0.0) {
        if (std::isnan(inf_sum)) return {FsumOutcome::Status::inf_minus_inf, 0.0};
        return {FsumOutcome::Status::ok, special_sum};
    }
    double hi = 0.0, lo = 0.0;
    std::size_t m = partials.size();
    if (m > 0) {
        hi = partials[--m];
        // Add from the top while the sum stays exact.
        while (m > 0) {
            double x = hi, y = partials[--m];
            hi = x + y;
            lo = y - (hi - x);
            if (lo != 0.0) break;
        }
        // Round half-even across partials: a remaining partial with the sign of
        // lo means the true sum lies beyond the halfway point.
        if (m > 0 && ((lo < 0.0 && partials[m - 1] < 0.0) || (lo > 0.0 && partials[m - 1] > 0.0))) {
            double y = lo * 2.0;
            double x = hi + y;
            if (y == x - hi) hi = x;
        }
    }
    return {FsumOutcome::Status::ok, hi};
}

// ---------------------------------------------------------------- matrices

Mat multiply(const Mat& a, const Mat& b) {
    Mat out{};
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) {
            double column[4] = {b[0][c], b[1][c], b[2][c], b[3][c]};
            out[r][c] = dot(a[r].data(), column, 4, "/transforms");
        }
    return out;
}

Mat inverse(const Mat& m) {
    const std::string ref = "/transforms";
    double a[4][8];
    for (int i = 0; i < 4; ++i)
        for (int k = 0; k < 4; ++k) {
            a[i][k] = m[i][k];
            a[i][k + 4] = kIdentity[i][k];
        }
    for (int i = 0; i < 4; ++i) {
        int pivot = i;
        for (int j = i + 1; j < 4; ++j)
            if (std::fabs(a[j][i]) > std::fabs(a[pivot][i])) pivot = j;  // max() keeps the first largest
        if (a[pivot][i] == 0) fail(Code::E_SINGULAR, ref, "Matrix has no inverse.");
        for (int k = 0; k < 8; ++k) std::swap(a[i][k], a[pivot][k]);
        double divisor = a[i][i];
        for (int k = 0; k < 8; ++k) a[i][k] = divide(a[i][k], divisor, ref);
        for (int j = 0; j < 4; ++j) {
            if (j == i) continue;
            double factor = a[j][i];
            for (int k = 0; k < 8; ++k) a[j][k] = sub(a[j][k], product(factor, a[i][k], ref), ref);
        }
    }
    Mat out{};
    for (int i = 0; i < 4; ++i)
        for (int k = 0; k < 4; ++k) out[i][k] = a[i][k + 4];
    return out;
}

void check_affine(const Mat& m, double tolerance, const std::string& ref) {
    if (tolerance < 0) fail(Code::E_TRANSFORM, ref, "Affine tolerance must be nonnegative.");
    for (int k = 0; k < 4; ++k)
        if (std::fabs(sub(m[3][k], kIdentity[3][k], ref)) > tolerance)
            fail(Code::E_TRANSFORM, ref, "Position matrix must have affine bottom row [0,0,0,1].");
}

std::array<double, 3> transform(const Mat& m, const double* p) {
    const double point[4] = {p[0], p[1], p[2], 1.0};
    return {dot(m[0].data(), point, 4, "/transforms"), dot(m[1].data(), point, 4, "/transforms"),
            dot(m[2].data(), point, 4, "/transforms")};
}

namespace {

double norm(const double* values, std::size_t n, const std::string& ref, Code zero_code) {
    double length = finite(hypot(values, n), ref);
    if (length == 0) fail(zero_code, ref, "Normalization requires a nonzero length.");
    return length;
}

}  // namespace

Vec normalize(const Vec& q) {
    double length = norm(q.data(), q.size(), "/rotation", Code::E_QUATERNION);
    Vec out;
    for (double x : q) out.push_back(divide(x, length, "/rotation"));
    return out;
}

void check_authored_quaternion(const Vec& q, const std::string& ref) {
    double length = hypot(q.data(), q.size());
    if (!std::isfinite(length) || std::fabs(length - 1.0) > kUnitQuaternionTolerance)
        fail(Code::E_QUATERNION, ref, "Authored quaternion must be unit length.");
}

void check_trs(const Mat& m, double tolerance, const std::string& ref) {
    if (tolerance <= 0) fail(Code::E_TRANSFORM, ref, "TRS tolerance must be positive.");
    double axes[3][3], lengths[3], unit[3][3];
    for (int c = 0; c < 3; ++c)
        for (int r = 0; r < 3; ++r) axes[c][r] = m[r][c];
    for (int c = 0; c < 3; ++c) lengths[c] = norm(axes[c], 3, ref, Code::E_SINGULAR);
    for (int c = 0; c < 3; ++c)
        for (int r = 0; r < 3; ++r) unit[c][r] = divide(axes[c][r], lengths[c], ref);
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < i; ++j)
            if (std::fabs(dot(unit[i], unit[j], 3, ref)) > tolerance)
                fail(Code::E_SHEAR, ref, "Matrix cannot be represented by TRS without shear.");
    const double* b = unit[1];
    const double* c = unit[2];
    // C++ leaves argument order unspecified, so each operand gets its own
    // statement: a refusal must come from the same operation as in Python.
    double cross[3];
    const int i1[3] = {1, 2, 0}, i2[3] = {2, 0, 1};
    for (int k = 0; k < 3; ++k) {
        double left = product(b[i1[k]], c[i2[k]], ref);
        double right = product(b[i2[k]], c[i1[k]], ref);
        cross[k] = sub(left, right, ref);
    }
    double determinant = dot(unit[0], cross, 3, ref);
    if (determinant == 0) fail(Code::E_SINGULAR, ref, "Normalized matrix determinant is zero.");
    if (std::fabs(sub(std::fabs(determinant), 1.0, ref)) > tolerance)
        fail(Code::E_SHEAR, ref, "Normalized matrix determinant must have magnitude near one.");
}

Mat trs(const Vec& t, const Vec& q, const Vec& s) {
    Vec n = normalize(q);
    double x = n[0], y = n[1], z = n[2], w = n[3];
    const std::string ref = "/rotation";
    double xx = product(x, x, ref), yy = product(y, y, ref), zz = product(z, z, ref);
    double xy = product(x, y, ref), xz = product(x, z, ref), yz = product(y, z, ref);
    double xw = product(x, w, ref), yw = product(y, w, ref), zw = product(z, w, ref);
    auto diagonal = [&](double a, double b) { return sub(1.0, product(2.0, add(a, b, ref), ref), ref); };
    auto twice = [&](double v) { return product(2.0, v, ref); };
    double rot[3][3];
    // In the reference's evaluation order, row by row.
    rot[0][0] = diagonal(yy, zz);
    rot[0][1] = twice(sub(xy, zw, ref));
    rot[0][2] = twice(add(xz, yw, ref));
    rot[1][0] = twice(add(xy, zw, ref));
    rot[1][1] = diagonal(xx, zz);
    rot[1][2] = twice(sub(yz, xw, ref));
    rot[2][0] = twice(sub(xz, yw, ref));
    rot[2][1] = twice(add(yz, xw, ref));
    rot[2][2] = diagonal(xx, yy);
    Mat out{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) out[r][c] = product(rot[r][c], s[c], "/transforms");
        out[r][3] = t[r];
    }
    out[3] = kIdentity[3];
    return out;
}

// ---------------------------------------------------------------- curves

double fraction(double value) {
    if (!(0 <= value && value <= 1)) fail(Code::E_FRACTION, "/animations", "Interpolation fraction must lie in [0,1].");
    return value;
}

Vec linear(const Vec& a, const Vec& b, double t) {
    if (t == 0) return a;
    if (t == 1) return b;
    const std::string ref = "/animations";
    Vec out;
    for (std::size_t i = 0; i < a.size(); ++i) out.push_back(add(a[i], product(t, sub(b[i], a[i], ref), ref), ref));
    return out;
}

namespace {

// The endpoint hemisphere: an ordered rounded dot whose sign alone matters.
// Products known to round to zero are skipped rather than refused.
bool endpoint_negative_dot(const Vec& a, const Vec& b) {
    double total = 0.0;
    for (std::size_t i = 0; i < a.size(); ++i) {
        double x = a[i], y = b[i], term;
        int ex = 0, ey = 0;
        if (x != 0) std::frexp(x, &ex);
        if (y != 0) std::frexp(y, &ey);
        if (x == 0 || y == 0 || ex + ey <= -1075)
            term = 0.0;
        else
            term = x * y;
        total = add(total, term, "/rotation");
    }
    return total < 0;
}

Vec negated(const Vec& v) {
    Vec out;
    for (double x : v) out.push_back(-x);
    return out;
}

}  // namespace

Vec slerp(const Vec& a, const Vec& b_in, double t) {
    if (t == 0) return a;
    if (t == 1) return endpoint_negative_dot(a, b_in) ? negated(b_in) : b_in;
    const std::string ref = "/rotation";
    Vec b = b_in;
    double cosine = dot(a.data(), b.data(), a.size(), ref);
    if (cosine < 0) {
        b = negated(b);
        cosine = -cosine;
    }
    cosine = cosine < 1.0 ? cosine : 1.0;  // min(1.0, cosine)
    if (cosine > 0.9995) return normalize(linear(a, b, t));
    double angle = finite(std::acos(cosine), ref);
    double divisor = finite(std::sin(angle), ref);
    double a_weight = divide(std::sin(product(sub(1.0, t, ref), angle, ref)), divisor, ref);
    double b_weight = divide(std::sin(product(t, angle, ref)), divisor, ref);
    Vec out;
    for (std::size_t i = 0; i < a.size(); ++i) {
        double left = product(a_weight, a[i], ref);
        double right = product(b_weight, b[i], ref);
        out.push_back(add(left, right, ref));
    }
    return normalize(out);
}

Vec hermite(const Vec& p0, const Vec& out0, const Vec& p1, const Vec& in1, double t, double duration, bool quaternion) {
    const std::string ref = "/animations";
    double dt = duration;
    if (dt <= 0) fail(Code::E_CURVE, ref, "Hermite duration must be positive.");
    double t2 = product(t, t, ref), t3 = product(t2, t, ref);
    double twice_t2 = product(2.0, t2, ref), thrice_t2 = product(3.0, t2, ref), twice_t3 = product(2.0, t3, ref);
    double h00 = add(sub(twice_t3, thrice_t2, ref), 1.0, ref);
    double h10 = add(sub(t3, twice_t2, ref), t, ref);
    double h01 = add(-twice_t3, thrice_t2, ref);
    double h11 = sub(t3, t2, ref);
    Vec result;
    for (std::size_t i = 0; i < p0.size(); ++i) {
        // All four terms, then their sum, as the reference builds a tuple first.
        double terms[4] = {product(h00, p0[i], ref), out0[i] == 0 ? 0.0 : product(product(h10, dt, ref), out0[i], ref),
                           product(h01, p1[i], ref), in1[i] == 0 ? 0.0 : product(product(h11, dt, ref), in1[i], ref)};
        double total = 0.0;
        for (double term : terms) total = add(total, term, ref);
        result.push_back(total);
    }
    return quaternion ? normalize(result) : result;
}

}  // namespace msf::math3d
