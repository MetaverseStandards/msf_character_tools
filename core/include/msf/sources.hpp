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

// ---------------------------------------------------------------- GLB writer
// glb.write_glb's inputs, as numbers already read with float(). Integers that
// were not exact Python ints, or did not fit, are -1 (or `node_ok` false).
struct Mesh {
    std::vector<std::vector<double>> points;
    std::vector<long long> triangles;
    std::vector<std::vector<std::vector<double>>> targets;
    bool skinned = false;
    std::vector<Influences> influences;  // one entry per point, when skinned
    std::vector<double> weights;
};
struct Node {
    std::optional<std::string> name;
    std::vector<long long> children;
    std::vector<double> translation{0.0, 0.0, 0.0}, rotation{0.0, 0.0, 0.0, 1.0}, scale{1.0, 1.0, 1.0};
    std::optional<long long> mesh, skin;
    std::optional<std::vector<double>> weights;
};
struct Skin {
    std::vector<long long> joints;
    std::vector<std::vector<double>> inverse_bind_matrices;
    std::optional<long long> skeleton;
};
struct Channel {
    long long node = -1;
    bool node_ok = true;
    std::string path;
    std::vector<double> times;
    std::vector<std::vector<double>> values;
    std::string interpolation = "LINEAR";
};
struct Animation {
    std::vector<Channel> channels;
    std::optional<std::string> name;
};
// The writer's ValueError.
struct WriteError {
    std::string message;
};
// GLB bytes for nodes, meshes and skins in final glTF index order. The JSON
// chunk is canonical JSON in WTF-8: names may carry lone surrogates, which the
// caller refuses as the reference's encode() did.
std::string write_glb(const std::vector<Node>& nodes, const std::vector<Mesh>& meshes, const std::vector<Skin>& skins,
                      const std::vector<Animation>& animations, const std::string& generator);

}  // namespace msf::sources
