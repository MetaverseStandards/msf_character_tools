// SPDX-License-Identifier: MIT
#pragma once
#include "msf/common.hpp"
#include <optional>

namespace msf {
struct Domain { std::optional<double> minimum; std::optional<double> maximum; };
enum class Operator { identity, affine, weighted_sum };
struct Instruction {
  std::vector<std::size_t> inputs;
  std::size_t output{};
  Operator operation{Operator::identity};
  double scale{1}, offset{0};
  std::vector<double> weights;
};
// The Python compiler resolves references/evidence. This kernel owns a copy of all values.
struct ScalarProgram { std::vector<Domain> domains; std::vector<Instruction> instructions; };
Result<std::vector<double>> evaluate_scalars(const ScalarProgram& program,
  const std::vector<double>& values,const std::vector<bool>& validity);
} // namespace msf
