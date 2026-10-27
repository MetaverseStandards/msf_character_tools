// SPDX-License-Identifier: MIT
#include <algorithm>
#include <cmath>
#include <cstdio>

#include "msf/math3d.hpp"
#include "msf/sources.hpp"

namespace msf::sources {

namespace {

constexpr double kShearTolerance = 1e-6;
constexpr double kTiny = 1e-150;

double fsum(const std::vector<double>& values) {
    math3d::FsumOutcome r = math3d::fsum(values.data(), values.size());
    if (r.status == math3d::FsumOutcome::Status::overflow) throw PyError{PyError::Type::overflow, "intermediate overflow in fsum"};
    if (r.status == math3d::FsumOutcome::Status::inf_minus_inf) throw PyError{PyError::Type::value, "-inf + inf in fsum"};
    return r.value;
}

double divide(double a, double b) {
    if (b == 0) throw PyError{PyError::Type::zero_division, "float division by zero"};
    return a / b;
}

double root(double x) {
    if (x < 0) throw PyError{PyError::Type::value, "math domain error"};
    return std::sqrt(x);
}

// Python's min(): the first element unless a later one compares less.
double python_min(const double* v, std::size_t n) {
    double out = v[0];
    for (std::size_t i = 1; i < n; ++i)
        if (v[i] < out) out = v[i];
    return out;
}

std::array<double, 3> norms(const Matrix& m) {
    std::array<double, 3> out{};
    for (int c = 0; c < 3; ++c) {
        std::vector<double> squares;
        for (int r = 0; r < 3; ++r) squares.push_back(m[static_cast<std::size_t>(4 * c + r)] * m[static_cast<std::size_t>(4 * c + r)]);
        out[static_cast<std::size_t>(c)] = root(fsum(squares));
    }
    return out;
}

double at(const Matrix& m, int c, int r) { return m[static_cast<std::size_t>(4 * c + r)]; }

std::array<double, 4> quaternion(const double r[3][3]) {
    double trace = r[0][0] + r[1][1] + r[2][2];
    std::array<double, 4> q{};
    if (trace > 0) {
        double s = 2 * root(trace + 1);
        q = {divide(r[2][1] - r[1][2], s), divide(r[0][2] - r[2][0], s), divide(r[1][0] - r[0][1], s), s / 4};
    } else if (r[0][0] >= r[1][1] && r[0][0] >= r[2][2]) {
        double s = 2 * root(1 + r[0][0] - r[1][1] - r[2][2]);
        q = {s / 4, divide(r[0][1] + r[1][0], s), divide(r[0][2] + r[2][0], s), divide(r[2][1] - r[1][2], s)};
    } else if (r[1][1] >= r[2][2]) {
        double s = 2 * root(1 + r[1][1] - r[0][0] - r[2][2]);
        q = {divide(r[0][1] + r[1][0], s), s / 4, divide(r[1][2] + r[2][1], s), divide(r[0][2] - r[2][0], s)};
    } else {
        double s = 2 * root(1 + r[2][2] - r[0][0] - r[1][1]);
        q = {divide(r[0][2] + r[2][0], s), divide(r[1][2] + r[2][1], s), s / 4, divide(r[1][0] - r[0][1], s)};
    }
    std::vector<double> squares;
    for (double x : q) squares.push_back(x * x);
    double norm = root(fsum(squares));
    for (double& x : q) x = divide(x, norm);
    if (!(q[3] >= 0))
        for (double& x : q) x = -x;
    return q;
}

double clean(double x) { return std::fabs(x) < kTiny ? 0.0 : x; }

std::string format_g6(double x) {
    char buffer[64];
    std::snprintf(buffer, sizeof buffer, "%.6g", x);
    return buffer;
}

}  // namespace

bool is_affine(const Matrix& m) { return m[3] == 0.0 && m[7] == 0.0 && m[11] == 0.0 && m[15] == 1.0; }

bool has_shear(const Matrix& m) {
    std::array<double, 3> n = norms(m);
    if (python_min(n.data(), 3) == 0) return false;
    static const int pairs[3][2] = {{0, 1}, {0, 2}, {1, 2}};
    for (const auto& pair : pairs) {
        int i = pair[0], j = pair[1];
        std::vector<double> products;
        for (int r = 0; r < 3; ++r) products.push_back(at(m, i, r) * at(m, j, r));
        double cosine = divide(fsum(products), n[static_cast<std::size_t>(i)] * n[static_cast<std::size_t>(j)]);
        if (std::fabs(cosine) > kShearTolerance) return true;
    }
    return false;
}

double determinant(const Matrix& m) {
    double a0 = at(m, 0, 0), a1 = at(m, 0, 1), a2 = at(m, 0, 2);
    double b0 = at(m, 1, 0), b1 = at(m, 1, 1), b2 = at(m, 1, 2);
    double c0 = at(m, 2, 0), c1 = at(m, 2, 1), c2 = at(m, 2, 2);
    double first = a0 * (b1 * c2 - b2 * c1);
    double second = b0 * (a1 * c2 - a2 * c1);
    double third = c0 * (a1 * b2 - a2 * b1);
    return first - second + third;
}

Trs decompose(const Matrix& m) {
    std::array<double, 3> scale = norms(m);
    if (python_min(scale.data(), 3) == 0) throw Singular{};
    if (determinant(m) < 0) scale[0] = -scale[0];
    double unit[3][3];
    for (int c = 0; c < 3; ++c)
        for (int r = 0; r < 3; ++r) unit[c][r] = divide(at(m, c, r), scale[static_cast<std::size_t>(c)]);
    double rotation[3][3];
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 3; ++c) rotation[r][c] = unit[c][r];
    std::array<double, 4> q = quaternion(rotation);
    Trs out;
    out.translation = {clean(m[12]), clean(m[13]), clean(m[14])};
    out.rotation = {clean(q[0]), clean(q[1]), clean(q[2]), clean(q[3])};
    out.scale = {clean(scale[0]), clean(scale[1]), clean(scale[2])};
    return out;
}

std::string count(long long n, const std::string& one, const std::string& many) { return std::to_string(n) + " " + (n == 1 ? one : many); }

Diagnostic warning(Code code, const std::string& ref, const std::string& message) { return {code, ref, message, "Review the declared loss."}; }

Influences merge(const Influences& pairs, const std::string& path) {
    Influences merged;
    for (const auto& pair : pairs) {
        long long joint = pair.first;
        double weight = pair.second;
        if (!std::isfinite(weight) || weight < 0) fail(Code::E_SOURCE_VALUE, path, "Joint influences need finite nonnegative weights.");
        if (weight > 0) {
            auto found = std::find_if(merged.begin(), merged.end(), [&](const auto& e) { return e.first == joint; });
            if (found == merged.end()) merged.emplace_back(joint, 0.0 + weight);
            else found->second += weight;
        }
    }
    return merged;
}

Rows influence_rows(const std::vector<Influences>& merged_rows, long long root_joint, bool top4, const std::string& path,
                    const std::string& unweighted_to) {
    Rows out;
    long long normalized = 0, unweighted = 0, truncated = 0;
    std::size_t widest = 0;
    double dropped = 0.0;
    for (Influences merged : merged_rows) {
        std::vector<double> weights;
        for (const auto& e : merged) weights.push_back(e.second);
        double total = fsum(weights);
        if (total == 0) {
            unweighted += 1;
            merged = {{root_joint, 1.0}};
        } else if (std::fabs(total - 1) > 1e-6) {
            normalized += 1;
        }
        std::stable_sort(merged.begin(), merged.end(), [](const auto& a, const auto& b) {
            if (-a.second != -b.second) return -a.second < -b.second;
            return a.first < b.first;
        });
        if (merged.size() > 4 && top4) {
            truncated += 1;
            double share = merged[4].second / total;
            if (share > dropped) dropped = share;
            merged.resize(4);
        }
        widest = std::max(widest, merged.size());
        std::sort(merged.begin(), merged.end());
        out.rows.push_back(std::move(merged));
    }
    if (widest > 4)
        out.losses.push_back({Code::I_INFLUENCES_N, path,
                              "Vertices have up to " + std::to_string(widest) + " joint influences, stored in " + std::to_string((widest + 3) / 4) +
                                  " JOINTS/WEIGHTS sets.",
                              "No action needed."});
    if (truncated)
        out.losses.push_back(warning(Code::W_INFLUENCES_TRUNCATED, path,
                                     count(truncated, "vertex", "vertices") + " kept only their four largest influences; the largest dropped weight is " +
                                         format_g6(dropped) + "."));
    if (normalized)
        out.losses.push_back(warning(Code::W_WEIGHTS_NORMALIZED, path,
                                     "Normalized the weights of " + count(normalized, "vertex", "vertices") + " that did not sum to 1."));
    if (unweighted)
        out.losses.push_back(warning(Code::W_UNWEIGHTED_VERTICES, path,
                                     "Bound " + count(unweighted, "unweighted vertex", "unweighted vertices") + " to " + unweighted_to + "."));
    return out;
}

Diagnostic method_loss(const std::string& path, const std::string& method) {
    return warning(Code::W_SKINNING_METHOD, path, "Skinning method " + method + " is stored as linear blend skinning.");
}

}  // namespace msf::sources
