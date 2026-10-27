// SPDX-License-Identifier: MIT
// Authoring and pack across the boundary: any Python value to json::Value for
// validation, and the Document handle that validated and compiled packs own.
#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>

#include <cmath>
#include <optional>
#include <string>
#include <utility>

#include "bridge.hpp"
#include "document.hpp"
#include "msf/authoring.hpp"
#include "msf/diagnostics.hpp"
#include "msf/json.hpp"
#include "msf/pack.hpp"
#include "msf/sha256.hpp"

namespace nb = nanobind;
using msf::json::Value;
using Kind = Value::Kind;

namespace bridge {

// json_value refuses anything at depth 129 before looking inside it, and no
// other check reaches that deep, so deeper contents (or cycles) never matter.
constexpr int kDeepest = 129;

static PyObject* mapping_abc() {
    // Never released: a static nb::object would be released after interpreter shutdown.
    static PyObject* abc = nb::object(nb::module_::import_("collections.abc").attr("Mapping")).release().ptr();
    return abc;
}

static bool is_mapping(PyObject* o) {
    if (PyDict_Check(o) || Py_TYPE(o) == &PyDictProxy_Type) return true;
    int found = PyObject_IsInstance(o, mapping_abc());
    if (found < 0) throw nb::python_error();
    return found == 1;
}

// The value as validate_authoring sees it: exact JSON types keep their kind,
// Mappings are objects, lists and tuples (and subclasses) are arrays, and
// everything else is Kind::other.
void from_any(PyObject* o, Value& v, int depth) {
    if (o == Py_None) {
        v = Value::null_value();
    } else if (o == Py_True || o == Py_False) {
        v = Value::make_boolean(o == Py_True);
    } else if (PyFloat_CheckExact(o)) {
        v = Value::make_real(PyFloat_AS_DOUBLE(o));
    } else if (PyLong_CheckExact(o)) {
        double d = PyLong_AsDouble(o);
        if (d == -1.0 && PyErr_Occurred()) {
            // number() is False for ints past binary64's range; their digits never matter.
            PyErr_Clear();
            v = Value();
            v.kind = Kind::integer;
            nb::object zero = nb::int_(0);
            int negative = PyObject_RichCompareBool(o, zero.ptr(), Py_LT);
            if (negative < 0) throw nb::python_error();
            v.number = negative ? -HUGE_VAL : HUGE_VAL;
            return;
        }
        nb::object text = nb::steal(PyObject_Str(o));
        if (!text.is_valid()) throw nb::python_error();
        v = Value::make_integer(bridge::wtf8_of(text));
    } else if (PyUnicode_CheckExact(o)) {
        v = Value::make_string(bridge::wtf8_of(o));
    } else if (is_mapping(o)) {
        v = Value();
        v.kind = Kind::object;
        if (depth >= kDeepest) return;
        nb::object items = nb::steal(PyMapping_Items(o));
        if (!items.is_valid()) throw nb::python_error();
        nb::object pairs = nb::steal(PySequence_Tuple(items.ptr()));
        if (!pairs.is_valid()) throw nb::python_error();
        Py_ssize_t n = PyTuple_GET_SIZE(pairs.ptr());
        v.members.resize(static_cast<std::size_t>(n));
        for (Py_ssize_t i = 0; i < n; ++i) {
            PyObject* pair = PyTuple_GET_ITEM(pairs.ptr(), i);
            if (!PyTuple_Check(pair) || PyTuple_GET_SIZE(pair) != 2) {
                PyErr_SetString(PyExc_TypeError, "Mapping items must be key-value pairs.");
                throw nb::python_error();
            }
            PyObject* key = PyTuple_GET_ITEM(pair, 0);
            auto& member = v.members[static_cast<std::size_t>(i)];
            member.first = PyUnicode_CheckExact(key) ? bridge::wtf8_of(key) : std::string("\xFF");
            from_any(PyTuple_GET_ITEM(pair, 1), member.second, depth + 1);
        }
    } else if (PyList_Check(o) || PyTuple_Check(o)) {
        v = Value();
        v.kind = Kind::array;
        v.is_list = PyList_Check(o);
        if (depth >= kDeepest) return;
        nb::object items = nb::steal(PySequence_Tuple(o));
        if (!items.is_valid()) throw nb::python_error();
        Py_ssize_t n = PyTuple_GET_SIZE(items.ptr());
        v.items.resize(static_cast<std::size_t>(n));
        for (Py_ssize_t i = 0; i < n; ++i) from_any(PyTuple_GET_ITEM(items.ptr(), i), v.items[static_cast<std::size_t>(i)], depth + 1);
    } else {
        v = Value();
        v.kind = Kind::other;
    }
}

// The record view: what records._owned made of a valid document in 0.3.0.
nb::object frozen(const Value& v) {
    switch (v.kind) {
        case Kind::array: {
            nb::object out = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(v.items.size())));
            for (std::size_t i = 0; i < v.items.size(); ++i)
                PyTuple_SET_ITEM(out.ptr(), static_cast<Py_ssize_t>(i), frozen(v.items[i]).release().ptr());
            return out;
        }
        case Kind::object: {
            nb::object dict = nb::steal(PyDict_New());
            for (const auto& [key, child] : v.members)
                if (PyDict_SetItem(dict.ptr(), bridge::decode(key).ptr(), frozen(child).ptr()) < 0) throw nb::python_error();
            return nb::steal(PyDictProxy_New(dict.ptr()));
        }
        default:
            return bridge::to_python(v);
    }
}

}  // namespace bridge

namespace {

using bridge::from_any;
using bridge::frozen;

const std::string* first_surrogate(const Value& v) {
    if (v.kind == Kind::string) return msf::json::has_surrogate(v.text) ? &v.text : nullptr;
    for (const auto& [key, child] : v.members) {
        if (msf::json::has_surrogate(key)) return &key;
        if (const std::string* found = first_surrogate(child)) return found;
    }
    for (const Value& item : v.items)
        if (const std::string* found = first_surrogate(item)) return found;
    return nullptr;
}

// (diagnostics, Document or None), diagnostics as (code, severity, ref, message, remediation).
nb::tuple outcome(Value document) {
    msf::Report report = msf::authoring::validate(document);
    // 0.3.0 hashed a valid document's strings as UTF-8 when admitting it.
    if (report.ok())
        if (const std::string* text = first_surrogate(document)) bridge::utf8_bytes(*text);
    nb::list diagnostics;
    for (const msf::Diagnostic& d : report.diagnostics)
        diagnostics.append(nb::make_tuple(msf::info(d.code).name, msf::severity_name(d.severity()), bridge::decode(d.ref),
                                          bridge::decode(d.message), bridge::decode(d.remediation)));
    nb::object handle = nb::none();
    if (report.ok()) handle = nb::cast(Document(std::move(document)));
    return nb::make_tuple(nb::tuple(diagnostics), handle);
}

nb::tuple validate_authoring(nb::handle document) {
    Value v;
    from_any(document.ptr(), v, 0);
    return outcome(std::move(v));
}

struct Merger {
    msf::authoring::Merger merger;
    void add(nb::handle relative, nb::handle fragment) {
        Value v;
        from_any(fragment.ptr(), v, 0);
        merger.add(bridge::wtf8_of(relative), v);
    }
    nb::tuple validate() const { return outcome(merger.document()); }
};

}  // namespace

void bind_authoring(nb::module_& m) {
    nb::class_<Document>(m, "Document")
        .def("view", &Document::view)
        .def("check_view", &Document::check_view)
        .def("__msf_state__", &Document::state)
        .def("canonical", &Document::canonical)
        .def("sha256", &Document::sha256)
        .def("survey_csv", &Document::survey_csv)
        .def("coverage", &Document::coverage)
        .def("profile", [](const Document& d, nb::handle id) {
            msf::pack::Profile p = msf::pack::profile_snapshot(d.value, bridge::wtf8_of(id), d.sha256());
            std::string raw = msf::json::write_canonical(p.document, true);
            nb::bytes encoded = bridge::utf8_bytes(raw);
            return nb::make_tuple(encoded, msf::sha256_hex(raw), bridge::to_python(p.document), bridge::to_python(p.channels));
        });
    nb::class_<Merger>(m, "Merger")
        .def(nb::init<>())
        .def("add", &Merger::add, nb::arg("relative"), nb::arg("fragment").none())
        .def("validate", &Merger::validate);
    m.def("validate_authoring", &validate_authoring, nb::arg("document").none());
    m.def("_sha256", [](nb::bytes data) { return msf::sha256_hex(std::string_view(data.c_str(), data.size())); });
}
