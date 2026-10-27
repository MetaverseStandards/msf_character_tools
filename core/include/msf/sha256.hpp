// SPDX-License-Identifier: MIT
// SHA-256 (FIPS 180-4), as lowercase hex.
#pragma once
#include <string>
#include <string_view>

namespace msf {

std::string sha256_hex(std::string_view data);

}  // namespace msf
