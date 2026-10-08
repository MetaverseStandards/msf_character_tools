// SPDX-License-Identifier: MIT
#include "msf/expression.hpp"
#include "numeric.hpp"
#include <set>

namespace msf {
using namespace detail;
namespace {
bool in_domain(double value, const Domain& domain) {
  return (!domain.minimum || value >= *domain.minimum) && (!domain.maximum || value <= *domain.maximum);
}
}
Result<std::vector<double>> evaluate_scalars(const ScalarProgram& p,
 const std::vector<double>& values, const std::vector<bool>& validity) {
  return compute<std::vector<double>>([&] {
    if (values.size()!=p.domains.size() || validity.size()!=values.size())
      refuse("shape", "Sample shape mismatch");
    for (const auto& domain : p.domains) {
      if (domain.minimum) number(*domain.minimum);
      if (domain.maximum) number(*domain.maximum);
      if (domain.minimum && domain.maximum && *domain.minimum > *domain.maximum)
        refuse("domain", "Invalid domain bounds");
    }
    std::set<std::size_t> outputs;
    for (const auto& ins : p.instructions)
      if (ins.output >= values.size() || !outputs.insert(ins.output).second)
        refuse("binding", "Invalid output or multiple writers");
    std::set<std::size_t> prior_outputs;
    for (const auto& ins : p.instructions) {
      if (ins.inputs.empty()) refuse("binding", "Instruction requires inputs");
      if (ins.operation!=Operator::identity && ins.operation!=Operator::affine && ins.operation!=Operator::weighted_sum)
        refuse("operator", "Unsupported operator");
      if (ins.operation!=Operator::weighted_sum && ins.inputs.size()!=1)
        refuse("shape", "Unary operator requires one input");
      if (ins.operation==Operator::weighted_sum && ins.weights.size()!=ins.inputs.size())
        refuse("shape", "Weight count mismatch");
      number(ins.scale); number(ins.offset); numbers(ins.weights);
      for (const auto index : ins.inputs) {
        if (index >= values.size() || index==ins.output) refuse("binding", "Invalid input binding");
        if (outputs.count(index) && !prior_outputs.count(index))
          refuse("cycle", "Instructions must be topologically ordered without cycles");
      }
      prior_outputs.insert(ins.output);
    }
    numbers(values);
    auto output=values; auto valid=validity;
    for (const auto& ins : p.instructions) {
      double value=0;
      for (std::size_t k=0; k<ins.inputs.size(); ++k) {
        const auto index=ins.inputs[k];
        if (!valid[index]) refuse("invalid_sample", "Required sample is invalid");
        if (!in_domain(output[index],p.domains[index])) refuse("domain", "Required sample outside domain");
        if (ins.operation==Operator::weighted_sum)
          value=add(value,product(ins.weights[k],output[index]));
        else value=output[index];
      }
      if (ins.operation==Operator::affine) value=add(product(value,ins.scale),ins.offset);
      if (!in_domain(value,p.domains[ins.output])) refuse("domain", "Mapped value outside output domain");
      output[ins.output]=value; valid[ins.output]=true;
    }
    return output;
  });
}
} // namespace msf
