// SPDX-License-Identifier: MIT
#include "msf/skeletal.hpp"
#include "numeric.hpp"
#include <optional>

namespace msf {
using namespace detail;
Result<std::vector<Vec3>> morph_positions(const std::vector<Vec3>& basis,
 const std::vector<std::vector<Vec3>>& deltas, const std::vector<double>& weights) {
  return compute<std::vector<Vec3>>([&] {
    if (deltas.size()!=weights.size()) refuse("shape", "Morph weight count mismatch");
    for (const auto& point : basis) numbers(point);
    numbers(weights);
    for (const auto& target : deltas) {
      if (target.size()!=basis.size()) refuse("shape", "Morph vertex count mismatch");
      for (const auto& delta : target) numbers(delta);
    }
    auto result=basis;
    for (std::size_t m=0; m<deltas.size(); ++m) {
      if (weights[m]==0) continue;
      for (std::size_t v=0; v<basis.size(); ++v) for (int k=0; k<3; ++k)
        result[v][k]=add(result[v][k],product(weights[m],deltas[m][v][k]));
    }
    return result;
  });
}
Result<std::vector<Vec3>> skin_positions(const std::vector<SkinVertex>& vertices,
 const Mat4& mesh_world, const std::vector<Mat4>& joint_worlds, const std::vector<Mat4>& ibms) {
  return compute<std::vector<Vec3>>([&] {
    if (joint_worlds.empty() || joint_worlds.size()!=ibms.size())
      refuse("shape", "Joint/bind count mismatch");
    affine(mesh_world);
    for (std::size_t i=0; i<joint_worlds.size(); ++i) { affine(joint_worlds[i]); affine(ibms[i]); }
    for (const auto& vertex : vertices) {
      numbers(vertex.position); numbers(vertex.weights);
      double sum=0;
      for (int k=0; k<4; ++k) {
        if (vertex.weights[k]<0 || vertex.joints[k]>=joint_worlds.size())
          refuse("influence", "Invalid four-influence joint/weight");
        sum=add(sum,vertex.weights[k]);
      }
      if (std::abs(sub(sum,1))>1e-6) refuse("weights", "Skin weights must sum to one; no implicit normalization");
    }
    const auto mesh_inverse=take(inverse(mesh_world));
    std::vector<std::optional<Mat4>> palettes(joint_worlds.size());
    std::vector<Vec3> result;
    result.reserve(vertices.size());
    for (const auto& vertex : vertices) {
      Vec3 position{};
      for (int k=0; k<4; ++k) {
        const double weight=vertex.weights[k];
        if (weight==0) continue;
        const auto joint=vertex.joints[k];
        if (!palettes[joint])
          palettes[joint]=take(multiply(take(multiply(mesh_inverse,joint_worlds[joint])),ibms[joint]));
        const auto point=take(transform_point(*palettes[joint],vertex.position));
        for (int d=0; d<3; ++d) position[d]=add(position[d],product(weight,point[d]));
      }
      result.push_back(position);
    }
    return result;
  });
}
} // namespace msf
