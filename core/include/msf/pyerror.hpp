// SPDX-License-Identifier: MIT
// A Python exception the reference raised outside msf's diagnostics, such as
// math.fsum's OverflowError; the binding raises it with the same message.
#pragma once
#include <string>

namespace msf {

struct PyError {
    enum class Type { value, overflow, zero_division, type, index } type;
    std::string message;
};

}  // namespace msf
