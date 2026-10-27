// SPDX-License-Identifier: MIT
#include "msf/program.hpp"

#include <algorithm>

#include "msf/checked.hpp"

namespace msf {

// Python's min/max keep the first argument on ties; that decides signed zeros.
static double py_max(double a, double b) { return b > a ? b : a; }
static double py_min(double a, double b) { return b < a ? b : a; }

double piecewise_clamp(double value, double ya, double yb) {
    return py_min(py_max(value, py_min(ya, yb)), py_max(ya, yb));
}

static bool piecewise(const Instruction& ins, double x, double& out) {
    const auto& xs = ins.xs;
    auto upper = std::upper_bound(xs.begin(), xs.end(), x);
    if (upper == xs.begin()) return false;
    std::size_t i = static_cast<std::size_t>(upper - xs.begin()) - 1;
    if (xs[i] == x) {
        out = ins.ys[i];
        return true;
    }
    if (i + 1 >= xs.size()) return false;
    double xa = xs[i], xb = xs[i + 1], ya = ins.ys[i], yb = ins.ys[i + 1];
    double dx_in, dx, t, dy, step, value;
    if (!sub(x, xa, dx_in) || !sub(xb, xa, dx) || !divide(dx_in, dx, t)) return false;
    if (!sub(yb, ya, dy) || !product(t, dy, step) || !add(ya, step, value)) return false;
    out = piecewise_clamp(value, ya, yb);
    return true;
}

bool Program::run(double* values) const {
    for (const Instruction& ins : instructions) {
        double value = 0.0;
        switch (ins.op) {
            case Op::identity:
                value = values[ins.inputs[0]];
                break;
            case Op::affine: {
                double scaled;
                if (!product(ins.scale, values[ins.inputs[0]], scaled) || !add(scaled, ins.offset, value)) return false;
                break;
            }
            case Op::weighted_sum: {
                double total = 0.0;
                for (std::size_t k = 0; k < ins.inputs.size(); ++k) {
                    double term;
                    if (!product(ins.weights[k], values[ins.inputs[k]], term) || !add(total, term, total)) return false;
                }
                value = total;
                break;
            }
            case Op::piecewise_linear:
                if (!piecewise(ins, values[ins.inputs[0]], value)) return false;
                break;
        }
        if (!ins.output_domain.contains(value)) return false;
        values[ins.output] = value;
    }
    return true;
}

}  // namespace msf
