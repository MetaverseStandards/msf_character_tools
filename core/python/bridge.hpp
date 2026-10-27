// SPDX-License-Identifier: MIT
// Conversions shared by the binding files.
#pragma once
#include <nanobind/nanobind.h>

#include <string>

#include "msf/json.hpp"

namespace bridge {

namespace nb = nanobind;

// A str from WTF-8 (UTF-8 with lone surrogates), as 'surrogatepass' decodes it.
nb::object decode(const std::string& wtf8);

// A str's WTF-8, lone surrogates included.
std::string wtf8_of(nb::handle str);

// UTF-8 bytes of WTF-8 text; with a lone surrogate, raises the UnicodeEncodeError
// that str.encode("utf-8") raises for the decoded text.
nb::bytes utf8_bytes(const std::string& wtf8);

// Plain dicts, lists and scalars.
nb::object to_python(const msf::json::Value& v);

}  // namespace bridge
