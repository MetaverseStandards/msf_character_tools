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

// Any Python value as validate_authoring sees it: exact JSON types keep their
// kind, Mappings are objects, lists and tuples (and subclasses) are arrays,
// anything else is Kind::other. Contents past depth 129 are left out.
void from_any(PyObject* o, msf::json::Value& v, int depth = 0);

// What records._owned made of a valid document: proxies, tuples, scalars.
nb::object frozen(const msf::json::Value& v);

// Plain dicts, lists and scalars.
nb::object to_python(const msf::json::Value& v);

}  // namespace bridge
