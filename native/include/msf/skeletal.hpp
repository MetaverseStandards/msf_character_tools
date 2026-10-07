// SPDX-License-Identifier: MIT
#pragma once
#include "msf/common.hpp"

namespace msf {
struct SkinVertex { Vec3 position; std::array<std::size_t,4> joints; std::array<double,4> weights; };
Result<std::vector<Vec3>> morph_positions(const std::vector<Vec3>& basis,
  const std::vector<std::vector<Vec3>>& deltas,const std::vector<double>& weights);
Result<std::vector<Vec3>> skin_positions(const std::vector<SkinVertex>& vertices,
  const Mat4& mesh_world,const std::vector<Mat4>& joint_worlds,
  const std::vector<Mat4>& inverse_bind_matrices);
} // namespace msf
