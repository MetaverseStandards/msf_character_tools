// SPDX-License-Identifier: MIT
#include "msf/expression.hpp"
#include <cmath>
#include <set>

namespace msf {
namespace {
Result<std::vector<double>> error(const char* code,const char* message) {
  return {{},{{code,message}}};
}
bool in_domain(double v,const Domain& d) {
  return std::isfinite(v)&&(!d.minimum||v>=*d.minimum)&&(!d.maximum||v<=*d.maximum);
}
}
Result<std::vector<double>> evaluate_scalars(const ScalarProgram& p,
 const std::vector<double>& values,const std::vector<bool>& validity) {
  if(values.size()!=p.domains.size()||validity.size()!=values.size())return error("shape","Sample shape mismatch");
  for(const auto& d:p.domains)
    if((d.minimum&&!std::isfinite(*d.minimum))||(d.maximum&&!std::isfinite(*d.maximum))||(d.minimum&&d.maximum&&*d.minimum>*d.maximum))
      return error("domain","Invalid domain");
  std::set<std::size_t> program_outputs;
  for(const auto& ins:p.instructions) {
    if(ins.output>=values.size()||!program_outputs.insert(ins.output).second)
      return error("binding","Invalid output or multiple writers");
  }
  auto output=values;auto valid=validity;std::set<std::size_t> writers;
  for(const auto& ins:p.instructions) {
    if(ins.output>=values.size()||ins.inputs.empty()||!writers.insert(ins.output).second)return error("binding","Invalid output or multiple writers");
    if(ins.operation!=Operator::identity&&ins.operation!=Operator::affine&&ins.operation!=Operator::weighted_sum)return error("operator","Unsupported operator");
    if(ins.operation!=Operator::weighted_sum&&ins.inputs.size()!=1)return error("shape","Unary operator requires one input");
    if(ins.operation==Operator::weighted_sum&&ins.weights.size()!=ins.inputs.size())return error("shape","Weight count mismatch");
    if(!std::isfinite(ins.scale)||!std::isfinite(ins.offset))return error("nonfinite","Operator coefficients must be finite");
    double value=0;
    for(std::size_t k=0;k<ins.inputs.size();++k) {
      const auto i=ins.inputs[k];
      if(i>=values.size()||i==ins.output)return error("binding","Invalid input binding");
      if(program_outputs.count(i)&&!writers.count(i))return error("cycle","Instructions must be topologically ordered without cycles");
      if(!valid[i])return error("invalid_sample","Required sample is invalid");
      if(!in_domain(output[i],p.domains[i]))return error("domain","Required sample outside domain");
      if(ins.operation==Operator::weighted_sum) {
        if(!std::isfinite(ins.weights[k]))return error("nonfinite","Weights must be finite");
        value+=ins.weights[k]*output[i];
      } else value=output[i];
    }
    if(ins.operation==Operator::affine)value=value*ins.scale+ins.offset;
    if(!in_domain(value,p.domains[ins.output]))return error("domain","Mapped value outside output domain");
    output[ins.output]=value;valid[ins.output]=true;
  }
  return {std::move(output),{}};
}
} // namespace msf
