// SPDX-License-Identifier: MIT
// A compiled scalar mapping: rules in dependency order over numbered value slots.
#pragma once
#include <cstddef>
#include <vector>

namespace msf {

struct Domain {
    bool has_min = false, has_max = false;
    double min = 0.0, max = 0.0;
    bool contains(double v) const { return !((has_min && v < min) || (has_max && v > max)); }
};

enum class Op { identity, affine, weighted_sum, piecewise_linear };

struct Instruction {
    Op op = Op::identity;
    std::vector<std::size_t> inputs;
    std::size_t output = 0;
    Domain output_domain;
    double scale = 0.0, offset = 0.0;
    std::vector<double> weights, xs, ys;
};

struct Program {
    std::size_t slots = 0;
    std::vector<Instruction> instructions;
    // Runs every instruction over `values` (one double per slot). False means a
    // checked operation refused or a value left its domain; the caller then
    // falls back to the reference path, which reports the diagnostic.
    bool run(double* values) const;
};

double piecewise_clamp(double value, double ya, double yb);

}  // namespace msf
