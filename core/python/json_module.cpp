// SPDX-License-Identifier: MIT
// JSON across the boundary: Python objects to json::Value and back, and the
// translation of msf::Fault into msf_tools.report.Fault.
#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>

#include <array>
#include <cstring>
#include <string>
#include <vector>

#include "msf/diagnostics.hpp"
#include "msf/json.hpp"

namespace nb = nanobind;
using msf::json::Value;

namespace {

// Deeper Python structures go to the reference path, where the interpreter's
// recursion limit decides what happens.
constexpr int kMaxConvertDepth = 512;

nb::object decode(const std::string& wtf8) {
    return nb::steal(PyUnicode_DecodeUTF8(wtf8.data(), static_cast<Py_ssize_t>(wtf8.size()), "surrogatepass"));
}

bool utf8_of(PyObject* str, std::string& out) {
    Py_ssize_t n;
    const char* s = PyUnicode_AsUTF8AndSize(str, &n);
    if (!s) {
        PyErr_Clear();  // lone surrogates: the reference path raises Python's own error
        return false;
    }
    out.assign(s, static_cast<std::size_t>(n));
    return true;
}

// common.thaw for the exact JSON types; anything else (records with to_dict,
// subclasses, non-str keys, other objects) returns false for the reference path.
bool from_python(PyObject* o, Value& v, int depth) {
    if (depth > kMaxConvertDepth) return false;
    if (o == Py_None) {
        v = Value::null_value();
    } else if (o == Py_True || o == Py_False) {
        v = Value::make_boolean(o == Py_True);
    } else if (PyFloat_CheckExact(o)) {
        v = Value::make_real(PyFloat_AS_DOUBLE(o));
    } else if (PyLong_CheckExact(o)) {
        int overflow = 0;
        long long x = PyLong_AsLongLongAndOverflow(o, &overflow);
        if (!overflow) {
            v = Value::make_integer(std::to_string(x));
        } else {
            nb::object text = nb::steal(PyObject_Str(o));
            std::string digits;
            if (!text.is_valid() || !utf8_of(text.ptr(), digits)) {
                PyErr_Clear();
                return false;
            }
            v = Value::make_integer(std::move(digits));
        }
    } else if (PyUnicode_CheckExact(o)) {
        std::string s;
        if (!utf8_of(o, s)) return false;
        v = Value::make_string(std::move(s));
    } else if (PyList_CheckExact(o) || PyTuple_CheckExact(o)) {
        nb::object items = nb::steal(PySequence_Tuple(o));
        if (!items.is_valid()) {
            PyErr_Clear();
            return false;
        }
        v = Value();
        v.kind = Value::Kind::array;
        Py_ssize_t n = PyTuple_GET_SIZE(items.ptr());
        v.items.resize(static_cast<std::size_t>(n));
        for (Py_ssize_t i = 0; i < n; ++i)
            if (!from_python(PyTuple_GET_ITEM(items.ptr(), i), v.items[static_cast<std::size_t>(i)], depth + 1)) return false;
    } else if (PyDict_CheckExact(o) || Py_TYPE(o) == &PyDictProxy_Type) {
        nb::object items = nb::steal(PyMapping_Items(o));
        if (!items.is_valid() || !PyList_CheckExact(items.ptr())) {
            PyErr_Clear();
            return false;
        }
        v = Value();
        v.kind = Value::Kind::object;
        Py_ssize_t n = PyList_GET_SIZE(items.ptr());
        v.members.resize(static_cast<std::size_t>(n));
        for (Py_ssize_t i = 0; i < n; ++i) {
            PyObject* pair = PyList_GET_ITEM(items.ptr(), i);
            PyObject* key = PyTuple_GET_ITEM(pair, 0);
            auto& member = v.members[static_cast<std::size_t>(i)];
            if (!PyUnicode_CheckExact(key) || !utf8_of(key, member.first)) return false;
            if (!from_python(PyTuple_GET_ITEM(pair, 1), member.second, depth + 1)) return false;
        }
    } else {
        return false;
    }
    return true;
}

nb::object to_python(const Value& v) {
    switch (v.kind) {
        case Value::Kind::null: return nb::none();
        case Value::Kind::boolean: return nb::bool_(v.boolean);
        case Value::Kind::integer: return nb::steal(PyLong_FromString(v.text.c_str(), nullptr, 10));
        case Value::Kind::real: return nb::steal(PyFloat_FromDouble(v.number));
        case Value::Kind::string: return decode(v.text);
        case Value::Kind::array: {
            nb::object list = nb::steal(PyList_New(static_cast<Py_ssize_t>(v.items.size())));
            for (std::size_t i = 0; i < v.items.size(); ++i)
                PyList_SET_ITEM(list.ptr(), static_cast<Py_ssize_t>(i), to_python(v.items[i]).release().ptr());
            return list;
        }
        case Value::Kind::object: {
            nb::object dict = nb::steal(PyDict_New());
            for (const auto& [key, child] : v.members)
                if (PyDict_SetItem(dict.ptr(), decode(key).ptr(), to_python(child).ptr()) < 0) throw nb::python_error();
            return dict;
        }
    }
    return nb::none();
}

[[noreturn]] void raise_fault(const msf::Diagnostic& d) {
    nb::object report = nb::module_::import_("msf_tools.report");
    nb::object fault = report.attr("Fault")(msf::info(d.code).name, decode(d.ref), decode(d.message), decode(d.remediation));
    PyErr_SetObject(reinterpret_cast<PyObject*>(Py_TYPE(fault.ptr())), fault.ptr());
    throw nb::python_error();
}

// common.canonical_json's bytes, or None when the reference path must decide.
nb::object canonical_json(nb::handle value) {
    Value v;
    if (!from_python(value.ptr(), v, 0)) return nb::none();
    std::string out;
    try {
        out = msf::json::write_canonical(v);
    } catch (const std::domain_error&) {
        return nb::none();  // non-finite floats: Python raises its own ValueError
    }
    return nb::bytes(out.data(), out.size());
}

// (value,) as common.parse_json returns it, or None when the reference path must
// report the input (syntax, encoding, BOM in str, depth). Raises its faults.
nb::object parse_json(nb::handle data) {
    std::string text;
    if (PyBytes_CheckExact(data.ptr())) {
        text.assign(PyBytes_AS_STRING(data.ptr()), static_cast<std::size_t>(PyBytes_GET_SIZE(data.ptr())));
        // json.loads decodes bytes with 'utf-8-sig' semantics when they start with a BOM.
        if (text.compare(0, 3, "\xEF\xBB\xBF") == 0) text.erase(0, 3);
        if (!msf::json::validate_wtf8(text)) return nb::none();
    } else if (PyUnicode_CheckExact(data.ptr())) {
        if (!utf8_of(data.ptr(), text) || text.compare(0, 3, "\xEF\xBB\xBF") == 0) return nb::none();
    } else {
        return nb::none();
    }
    msf::json::ParseOutcome parsed = msf::json::parse(text);
    using Status = msf::json::ParseOutcome::Status;
    switch (parsed.status) {
        case Status::ok: return nb::make_tuple(to_python(parsed.value));
        case Status::syntax: return nb::none();
        case Status::constant:
            msf::fail(msf::Code::E_NONFINITE, "/", "Invalid JSON constant " + parsed.detail + ".");
        case Status::duplicate_key: {
            nb::object key = nb::steal(PyObject_Repr(decode(parsed.detail).ptr()));
            std::string shown;
            if (!key.is_valid() || !utf8_of(key.ptr(), shown)) throw nb::python_error();
            msf::fail(msf::Code::E_DUPLICATE_KEY, "/", "Duplicate JSON key " + shown + ".");
        }
    }
    return nb::none();
}

// Test hooks: Python repr of each float64 in a native-endian buffer, joined by \n.
nb::bytes repr_floats(nb::bytes data) {
    std::size_t n = data.size() / sizeof(double);
    std::string out;
    out.reserve(n * 24);
    for (std::size_t i = 0; i < n; ++i) {
        double d;
        std::memcpy(&d, static_cast<const char*>(data.c_str()) + i * sizeof(double), sizeof d);
        if (i) out += '\n';
        msf::json::append_python_repr(out, d);
    }
    return nb::bytes(out.data(), out.size());
}

}  // namespace

void bind_json(nb::module_& m) {
    nb::register_exception_translator([](const std::exception_ptr& p, void*) {
        try {
            std::rethrow_exception(p);
        } catch (const msf::Fault& fault) {
            try {
                raise_fault(fault.diagnostic());
            } catch (nb::python_error& e) {
                e.restore();
            }
        }
    });
    m.def("_codes", [] {
        nb::list out;
        for (int i = 0; i < static_cast<int>(msf::Code::NONE); ++i) {
            const msf::CodeInfo& code = msf::info(static_cast<msf::Code>(i));
            out.append(nb::make_tuple(code.name, msf::severity_name(code.severity),
                                      code.strict == msf::Code::NONE ? nb::object(nb::none()) : nb::object(nb::str(msf::info(code.strict).name))));
        }
        return out;
    });
    m.def("canonical_json", &canonical_json, nb::arg("value").none());
    m.def("parse_json", &parse_json, nb::arg("data").none());
    m.def("_repr_floats", &repr_floats);
    m.def("_exact_integer", [](const std::string& lexeme) -> nb::object {
        std::string digits;
        if (!msf::json::exact_integer(lexeme, digits)) return nb::none();
        return nb::str(digits.c_str());
    });
    m.def("_float32", [](double value) -> nb::object {
        float f;
        if (!msf::json::to_float32(value, f)) return nb::none();
        return nb::float_(static_cast<double>(f));
    });
    m.def("_parse_status", [](nb::bytes data) {
        msf::json::ParseOutcome parsed = msf::json::parse(std::string_view(data.c_str(), data.size()));
        static const char* names[] = {"ok", "syntax", "constant", "duplicate_key"};
        return std::string(names[static_cast<int>(parsed.status)]);
    });
}
