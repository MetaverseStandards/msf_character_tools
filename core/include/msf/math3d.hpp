// SPDX-License-Identifier: MIT
// Checked binary64 column-vector maths, as msf_tools.math3d defined it in
// 0.3.0: every result is finite, nonzero products and quotients never
// underflow to zero, and operations run in the reference's order, so faults
// and their refs match too. Matrices hold rows.
#pragma once
#include <array>
#include <cstddef>
#include <string>
#include <vector>

namespace msf::math3d {

using Mat = std::array<std::array<double, 4>, 4>;
using Vec = std::vector<double>;

extern const Mat kIdentity;
constexpr double kUnitQuaternionTolerance = 0.00769;  // the Khronos glTF-Validator's unitLengthThresholdVec4

double finite(double value, const std::string& ref);
double add(double a, double b, const std::string& ref);
double sub(double a, double b, const std::string& ref);
double product(double a, double b, const std::string& ref);
double divide(double a, double b, const std::string& ref);
double dot(const double* a, const double* b, std::size_t n, const std::string& ref);

// math.hypot(*values) and math.fsum(values), bit for bit.
double hypot(const double* values, std::size_t n);
struct FsumOutcome {
    enum class Status { ok, overflow, inf_minus_inf } status = Status::ok;
    double value = 0.0;
};
FsumOutcome fsum(const double* values, std::size_t n);

// The functions below take values already read as the reference reads them
// (msf_tools.math3d's _number/_vector/_matrix), and fail with its codes.
Mat multiply(const Mat& a, const Mat& b);
Mat inverse(const Mat& m);
void check_affine(const Mat& m, double tolerance, const std::string& ref);  // affine(), after its reads
void check_trs(const Mat& m, double tolerance, const std::string& ref);     // validate_trs(), after affine()
std::array<double, 3> transform(const Mat& m, const double* p);            // after affine() and the point read
Vec normalize(const Vec& q);                                               // ref /rotation
void check_authored_quaternion(const Vec& q, const std::string& ref);
Mat trs(const Vec& t, const Vec& q, const Vec& s);                         // q not yet normalized
double fraction(double value);                                             // ref /animations
Vec linear(const Vec& a, const Vec& b, double t);                          // t from fraction()
Vec slerp(const Vec& a, const Vec& b, double t);                           // a, b normalized; t from fraction()
Vec hermite(const Vec& p0, const Vec& out0, const Vec& p1, const Vec& in1, double t, double duration, bool quaternion);

}  // namespace msf::math3d
