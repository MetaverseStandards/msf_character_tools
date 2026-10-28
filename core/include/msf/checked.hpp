// SPDX-License-Identifier: MIT
// Checked binary64 arithmetic, the same refusals as msf_character_tools/math3d.py.
// Built with -ffp-contract=off: a fused multiply-add would round differently.
#pragma once
#include <cmath>

namespace msf {

inline bool add(double a, double b, double& out) {
    out = a + b;
    return std::isfinite(out);
}

inline bool sub(double a, double b, double& out) {
    out = a - b;
    return std::isfinite(out);
}

inline bool product(double a, double b, double& out) {
    out = a * b;
    return std::isfinite(out) && !(out == 0.0 && a != 0.0 && b != 0.0);
}

inline bool divide(double a, double b, double& out) {
    if (b == 0.0) return false;
    out = a / b;
    return std::isfinite(out) && !(out == 0.0 && a != 0.0);
}

}  // namespace msf
