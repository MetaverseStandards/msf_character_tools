// SPDX-License-Identifier: MIT
// The derived outputs of a validated pack document, as msf_tools.pack wrote
// them in 0.3.0. The document must have passed authoring::validate.
#pragma once
#include <string>

#include "msf/json.hpp"

namespace msf::pack {

// survey_csv's text (csv.writer, QUOTE_MINIMAL, "\n" line ends), as WTF-8.
std::string survey_csv(const json::Value& document);

// coverage()'s value, in the same key order; thawed parts carry 0.0 for -0.0.
json::Value coverage(const json::Value& document, const std::string& pack_sha256);

}  // namespace msf::pack
