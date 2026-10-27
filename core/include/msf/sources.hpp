// SPDX-License-Identifier: MIT
// The helpers source adapters share, as msf_tools.sources.transforms,
// skinning and glb defined them in 0.3.0: matrix decomposition, influence
// rows and their declared losses, and the deterministic GLB writer.
#pragma once
#include <array>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "msf/diagnostics.hpp"
#include "msf/pyerror.hpp"

namespace msf::sources {

// ---------------------------------------------------------------- transforms
// Matrices are 16 numbers in glTF column-major order.
using Matrix = std::array<double, 16>;

bool is_affine(const Matrix& m);
bool has_shear(const Matrix& m);
double determinant(const Matrix& m);
struct Trs {
    std::array<double, 3> translation;
    std::array<double, 4> rotation;  // xyzw
    std::array<double, 3> scale;
};
struct Singular {};  // the reference's ValueError("Transform is singular.")
Trs decompose(const Matrix& m);

// ---------------------------------------------------------------- skinning
using Influences = std::vector<std::pair<long long, double>>;  // (joint, weight)

std::string count(long long n, const std::string& one, const std::string& many);
Diagnostic warning(Code code, const std::string& ref, const std::string& message);
// Sums weights per joint in first-seen order, dropping zeros; E_SOURCE_VALUE for
// a negative or non-finite weight.
Influences merge(const Influences& pairs, const std::string& path);
struct Rows {
    std::vector<Influences> rows;  // sorted by joint
    std::vector<Diagnostic> losses;
};
Rows influence_rows(const std::vector<Influences>& merged_rows, long long root, bool top4, const std::string& path,
                    const std::string& unweighted_to = "the skeleton root joint");
Diagnostic method_loss(const std::string& path, const std::string& method);

}  // namespace msf::sources
