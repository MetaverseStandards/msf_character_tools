// SPDX-License-Identifier: MIT
#pragma once
#include "msf/common.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace msf::detail {
class Failure : public std::runtime_error {
public:
  std::string code;
  Failure(const char* code, const char* message) : std::runtime_error(message), code(code) {}
};
[[noreturn]] inline void refuse(const char* code, const char* message) {
  throw Failure(code, message);
}
template<class T, class F> Result<T> compute(F&& operation) {
  try { return {operation(), {}}; }
  catch (const Failure& failure) { return {{}, {{failure.code, failure.what()}}}; }
}
template<class T> T take(Result<T> result) {
  if (!result) throw Failure(result.errors.front().code.c_str(), result.errors.front().message.c_str());
  return std::move(result.value);
}
inline double number(double value) {
  if (!std::isfinite(value)) refuse("nonfinite", "Input or intermediate is not finite binary64");
  return value;
}
template<class T> void numbers(const T& values) {
  for (double value : values) number(value);
}
inline double add(double a, double b) { return number(a + b); }
inline double sub(double a, double b) { return number(a - b); }
inline double product(double a, double b) {
  const double value = number(a * b);
  if (value == 0 && a != 0 && b != 0)
    refuse("nonfinite", "Nonzero product underflows binary64 to zero");
  return value;
}
inline double divide(double a, double b) {
  if (b == 0) refuse("singular", "Division requires a nonzero divisor");
  const double value = number(a / b);
  if (value == 0 && a != 0) refuse("nonfinite", "Nonzero quotient underflows binary64 to zero");
  return value;
}
template<class A, class B> double dot(const A& a, const B& b) {
  double value = 0;
  for (std::size_t i = 0; i < a.size(); ++i) value = add(value, product(a[i], b[i]));
  return value;
}
inline void affine(const Mat4& m, double tolerance = 1e-10) {
  numbers(m);
  if (std::abs(m[12]) > tolerance || std::abs(m[13]) > tolerance ||
      std::abs(m[14]) > tolerance || std::abs(sub(m[15], 1)) > tolerance)
    refuse("nonaffine", "Matrix must have affine bottom row [0,0,0,1]");
}
} // namespace msf::detail
