// SPDX-License-Identifier: MIT
#include "msf/skeletal.hpp"
#include <cmath>

namespace msf {
namespace {
Result<std::vector<Vec3>> error(const char* code,const char* message) {return {{},{{code,message}}};}
bool finite3(const Vec3& p){return std::isfinite(p[0])&&std::isfinite(p[1])&&std::isfinite(p[2]);}
}
Result<std::vector<Vec3>> morph_positions(const std::vector<Vec3>& basis,
 const std::vector<std::vector<Vec3>>& deltas,const std::vector<double>& weights) {
  if(deltas.size()!=weights.size())return error("shape","Morph weight count mismatch");
  for(const auto& p:basis)if(!finite3(p))return error("nonfinite","Basis must be finite");
  for(std::size_t i=0;i<deltas.size();++i) {
    if(deltas[i].size()!=basis.size())return error("shape","Morph vertex count mismatch");
    if(!std::isfinite(weights[i]))return error("nonfinite","Morph weights must be finite");
    for(const auto& d:deltas[i])if(!finite3(d))return error("nonfinite","Morph delta must be finite");
  }
  auto result=basis;
  for(std::size_t m=0;m<deltas.size();++m)for(std::size_t v=0;v<basis.size();++v)for(int k=0;k<3;++k)
    result[v][k]+=weights[m]*deltas[m][v][k];
  for(const auto& p:result)if(!finite3(p))return error("nonfinite","Morph overflowed");
  return {std::move(result),{}};
}
Result<std::vector<Vec3>> skin_positions(const std::vector<SkinVertex>& vertices,
 const Mat4& mesh_world,const std::vector<Mat4>& joint_worlds,const std::vector<Mat4>& ibms) {
  if(joint_worlds.empty()||joint_worlds.size()!=ibms.size())return error("shape","Joint/bind count mismatch");
  auto inv=inverse(mesh_world);if(!inv)return {{},inv.errors};
  std::vector<Mat4> matrices;
  for(std::size_t i=0;i<joint_worlds.size();++i) {
    if(!finite(joint_worlds[i])||!finite(ibms[i]))return error("nonfinite","Joint and bind matrices must be finite");
    matrices.push_back(multiply(multiply(inv.value,joint_worlds[i]),ibms[i]));
  }
  Result<std::vector<Vec3>> result;
  for(const auto& v:vertices) {
    if(!finite3(v.position))return error("nonfinite","Skin position must be finite");
    double sum=0;Vec3 position{};
    for(int k=0;k<4;++k) {
      const double weight=v.weights[k];
      if(!std::isfinite(weight)||weight<0||v.joints[k]>=matrices.size())return error("influence","Invalid four-influence joint/weight");
      sum+=weight;
      auto p=transform_point(matrices[v.joints[k]],v.position);if(!p)return {{},p.errors};
      for(int d=0;d<3;++d)position[d]+=weight*p.value[d];
    }
    if(std::abs(sum-1)>1e-6)return error("weights","Skin weights must sum to one; no implicit normalization");
    if(!finite3(position))return error("nonfinite","Skin overflowed");
    result.value.push_back(position);
  }
  return result;
}
} // namespace msf
