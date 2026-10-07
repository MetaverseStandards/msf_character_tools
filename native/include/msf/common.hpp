// SPDX-License-Identifier: MIT
#pragma once
#include <array>
#include <string>
#include <vector>

namespace msf {
using Vec3 = std::array<double, 3>;
using Quat = std::array<double, 4>; // XYZW
using Mat4 = std::array<double, 16>; // row storage, column vectors
struct Diagnostic { std::string code; std::string message; };
template<class T> struct Result {
  T value{};
  std::vector<Diagnostic> errors;
  explicit operator bool() const { return errors.empty(); }
};
Mat4 identity();
Mat4 multiply(const Mat4& a, const Mat4& b);
Result<Mat4> inverse(const Mat4& a);
Result<Vec3> transform_point(const Mat4& m, const Vec3& p);
Result<Quat> normalize(const Quat& q);
Result<Mat4> compose_trs(const Vec3& translation, const Quat& rotation, const Vec3& scale);
Result<Mat4> reparent_local(const Mat4& new_parent_world, const Mat4& child_world);
Result<bool> validate_trs(const Mat4& m, double tolerance = 1e-10);
Result<Quat> slerp(const Quat& a, const Quat& b, double fraction);
Result<std::vector<double>> hermite(const std::vector<double>& p0,
  const std::vector<double>& out0, const std::vector<double>& p1,
  const std::vector<double>& in1, double fraction, double duration,
  bool quaternion = false);
bool finite(const Mat4& m);
} // namespace msf
