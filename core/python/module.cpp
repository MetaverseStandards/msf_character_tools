// SPDX-License-Identifier: MIT
// msf_tools._core: the nanobind boundary. Python keeps the record shells; these
// handles are immutable once built, and only samples and results cross per call.
#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>

#include <algorithm>
#include <cmath>
#include <functional>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include "msf/program.hpp"

namespace nb = nanobind;

void bind_json(nb::module_& m);

namespace {

constexpr long long kExactInteger = 1LL << 53;

// Python's number() and float() for one sample value, on the fast path only:
// exact float or an int that binary64 holds exactly. Anything else goes back
// to the reference path, which owns every diagnostic.
bool exact_number(PyObject* o, double& out) {
    if (PyFloat_CheckExact(o)) {
        out = PyFloat_AS_DOUBLE(o);
        return std::isfinite(out);
    }
    if (PyLong_CheckExact(o)) {
        int overflow = 0;
        long long v = PyLong_AsLongLongAndOverflow(o, &overflow);
        if (overflow || (v == -1 && PyErr_Occurred())) {
            PyErr_Clear();
            return false;
        }
        if (v > kExactInteger || v < -kExactInteger) return false;
        out = static_cast<double>(v);
        return true;
    }
    return false;
}

bool same_double(double a, double b) { return std::memcmp(&a, &b, sizeof a) == 0; }

bool str_keys(PyObject* dict) {
    Py_ssize_t pos = 0;
    PyObject *key, *value;
    while (PyDict_Next(dict, &pos, &key, &value))
        if (!PyUnicode_CheckExact(key)) return false;
    return true;
}

struct Frames {
    std::size_t count = 0;
    std::vector<double> timestamps, values;  // values: count rows of len(names)
    nb::tuple names;
    nb::object key_timestamp, key_values, key_validity;

    nb::object frame(std::size_t i) const {
        std::size_t k = names.size();
        nb::object values_dict = nb::steal(PyDict_New());
        nb::object validity_dict = nb::steal(PyDict_New());
        for (std::size_t j = 0; j < k; ++j) {
            nb::object v = nb::steal(PyFloat_FromDouble(this->values[i * k + j]));
            PyDict_SetItem(values_dict.ptr(), names[j].ptr(), v.ptr());
            PyDict_SetItem(validity_dict.ptr(), names[j].ptr(), Py_True);
        }
        nb::object frame = nb::steal(PyDict_New());
        nb::object ts = nb::steal(PyFloat_FromDouble(timestamps[i]));
        PyDict_SetItem(frame.ptr(), key_timestamp.ptr(), ts.ptr());
        nb::object values_proxy = nb::steal(PyDictProxy_New(values_dict.ptr()));
        nb::object validity_proxy = nb::steal(PyDictProxy_New(validity_dict.ptr()));
        PyDict_SetItem(frame.ptr(), key_values.ptr(), values_proxy.ptr());
        PyDict_SetItem(frame.ptr(), key_validity.ptr(), validity_proxy.ptr());
        return nb::steal(PyDictProxy_New(frame.ptr()));
    }

    nb::tuple view() const {
        nb::object out = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(count)));
        for (std::size_t i = 0; i < count; ++i)
            PyTuple_SET_ITEM(out.ptr(), static_cast<Py_ssize_t>(i), frame(i).release().ptr());
        return nb::borrow<nb::tuple>(out);
    }

    // Item lookups only: a proxy's keys cannot change, so equal sizes and equal
    // items mean the view still says exactly what this handle holds.
    bool check_view(nb::handle view) const {
        if (!PyTuple_CheckExact(view.ptr()) || static_cast<std::size_t>(PyTuple_GET_SIZE(view.ptr())) != count) return false;
        std::size_t k = names.size();
        for (std::size_t i = 0; i < count; ++i) {
            PyObject* frame = PyTuple_GET_ITEM(view.ptr(), static_cast<Py_ssize_t>(i));
            if (Py_TYPE(frame) != &PyDictProxy_Type || PyObject_Size(frame) != 3) return false;
            nb::object ts = nb::steal(PyObject_GetItem(frame, key_timestamp.ptr()));
            nb::object vals = nb::steal(PyObject_GetItem(frame, key_values.ptr()));
            nb::object valid = nb::steal(PyObject_GetItem(frame, key_validity.ptr()));
            if (!ts.is_valid() || !vals.is_valid() || !valid.is_valid()) {
                PyErr_Clear();
                return false;
            }
            if (!PyFloat_CheckExact(ts.ptr()) || !same_double(PyFloat_AS_DOUBLE(ts.ptr()), timestamps[i])) return false;
            if (Py_TYPE(vals.ptr()) != &PyDictProxy_Type || Py_TYPE(valid.ptr()) != &PyDictProxy_Type) return false;
            if (static_cast<std::size_t>(PyObject_Size(vals.ptr())) != k || static_cast<std::size_t>(PyObject_Size(valid.ptr())) != k)
                return false;
            for (std::size_t j = 0; j < k; ++j) {
                nb::object v = nb::steal(PyObject_GetItem(vals.ptr(), names[j].ptr()));
                nb::object ok = nb::steal(PyObject_GetItem(valid.ptr(), names[j].ptr()));
                if (!v.is_valid() || !ok.is_valid()) {
                    PyErr_Clear();
                    return false;
                }
                if (!PyFloat_CheckExact(v.ptr()) || !same_double(PyFloat_AS_DOUBLE(v.ptr()), values[i * k + j]) || ok.ptr() != Py_True)
                    return false;
            }
        }
        return true;
    }

    nb::bytes state() const {
        std::string out;
        std::uint64_t header[2] = {count, names.size()};
        out.append(reinterpret_cast<const char*>(header), sizeof header);
        out.append(reinterpret_cast<const char*>(timestamps.data()), timestamps.size() * sizeof(double));
        out.append(reinterpret_cast<const char*>(values.data()), values.size() * sizeof(double));
        return nb::bytes(out.data(), out.size());
    }
};

struct CompiledProgram {
    msf::Program program;
    nb::dict source_slots;  // source channel ID -> slot; slots below sources.size() are source channels
    std::vector<msf::Domain> source_domains;
    std::vector<std::size_t> required, output_slots;
    nb::tuple output_names;
    nb::bytes document;
    nb::object key_timestamp = nb::steal(PyUnicode_InternFromString("timestamp"));
    nb::object key_values = nb::steal(PyUnicode_InternFromString("values"));
    nb::object key_validity = nb::steal(PyUnicode_InternFromString("validity"));

    // Frames when every sample takes the fast path, else None. Only exact str
    // keys and exact containers are accepted, so no Python code runs while the
    // borrowed references below are in use.
    nb::object evaluate(nb::handle samples) const {
        nb::object items;
        if (PyTuple_CheckExact(samples.ptr()))
            items = nb::borrow(samples);
        else if (PyList_CheckExact(samples.ptr()))
            items = nb::steal(PyList_AsTuple(samples.ptr()));
        else
            return nb::none();
        std::size_t n = static_cast<std::size_t>(PyTuple_GET_SIZE(items.ptr()));
        std::size_t k = output_slots.size(), sources = source_domains.size();
        Frames result;
        result.count = n;
        result.timestamps.resize(n);
        result.values.resize(n * k);
        std::vector<double> slots(program.slots);
        std::vector<char> present(sources);
        for (std::size_t i = 0; i < n; ++i) {
            PyObject* frame = PyTuple_GET_ITEM(items.ptr(), static_cast<Py_ssize_t>(i));
            if (!PyDict_CheckExact(frame) || PyDict_GET_SIZE(frame) != 3 || !str_keys(frame)) return nb::none();
            PyObject* ts = PyDict_GetItem(frame, key_timestamp.ptr());
            PyObject* vals = PyDict_GetItem(frame, key_values.ptr());
            PyObject* valid = PyDict_GetItem(frame, key_validity.ptr());
            if (!ts || !vals || !valid) return nb::none();
            double t;
            if (!exact_number(ts, t) || !(t >= 0.0)) return nb::none();
            if (!PyDict_CheckExact(vals) || !PyDict_CheckExact(valid) || PyDict_GET_SIZE(vals) != PyDict_GET_SIZE(valid) ||
                !str_keys(vals) || !str_keys(valid))
                return nb::none();
            std::fill(present.begin(), present.end(), 0);
            Py_ssize_t pos = 0;
            PyObject *key, *value;
            while (PyDict_Next(vals, &pos, &key, &value)) {
                PyObject* slot_obj = PyDict_GetItem(source_slots.ptr(), key);
                if (!slot_obj) return nb::none();
                std::size_t slot = PyLong_AsSize_t(slot_obj);
                double d;
                if (PyDict_GetItem(valid, key) != Py_True || !exact_number(value, d) || !source_domains[slot].contains(d))
                    return nb::none();
                slots[slot] = d;
                present[slot] = 1;
            }
            for (std::size_t slot : required)
                if (!present[slot]) return nb::none();
            if (!program.run(slots.data())) return nb::none();
            result.timestamps[i] = t;
            for (std::size_t j = 0; j < k; ++j) result.values[i * k + j] = slots[output_slots[j]];
        }
        result.names = output_names;
        result.key_timestamp = key_timestamp;
        result.key_values = key_values;
        result.key_validity = key_validity;
        return nb::cast(std::move(result));
    }
};

// A spec that does not describe a valid program: always a bug in mapping.py,
// reported as E_INTERNAL rather than crashing or leaking a C++ exception.
struct SpecError {
    std::string what;
};

[[noreturn]] void bad_spec(const std::string& what) { throw SpecError{what}; }

void require(bool ok, const char* what) {
    if (!ok) bad_spec(what);
}

// Readers for the spec's Python values. Each accepts exactly one shape.
PyObject* item(PyObject* dict, const char* key) {
    PyObject* value = PyDict_GetItemString(dict, key);  // borrowed; the spec dict keeps it alive
    if (!value) bad_spec(std::string("missing ") + key);
    return value;
}

std::vector<PyObject*> sequence(PyObject* o, const char* what) {
    if (!PyList_Check(o) && !PyTuple_Check(o)) bad_spec(std::string(what) + " must be a list or tuple");
    Py_ssize_t n = PySequence_Fast_GET_SIZE(o);
    PyObject** items = PySequence_Fast_ITEMS(o);
    return std::vector<PyObject*>(items, items + n);
}

std::vector<PyObject*> tuple_of(PyObject* o, std::size_t size, const char* what) {
    if (!PyTuple_Check(o) || static_cast<std::size_t>(PyTuple_GET_SIZE(o)) != size)
        bad_spec(std::string(what) + " must be a tuple of " + std::to_string(size));
    return sequence(o, what);
}

std::size_t index(PyObject* o, std::size_t limit, const char* what) {
    if (!PyLong_CheckExact(o)) bad_spec(std::string(what) + " must be an int");
    std::size_t v = PyLong_AsSize_t(o);
    if (v == static_cast<std::size_t>(-1) && PyErr_Occurred()) {
        PyErr_Clear();
        bad_spec(std::string(what) + " is out of range");
    }
    if (v >= limit) bad_spec(std::string(what) + " is out of range");
    return v;
}

double finite(PyObject* o, const char* what) {
    if (!PyFloat_CheckExact(o)) bad_spec(std::string(what) + " must be a float");
    double v = PyFloat_AS_DOUBLE(o);
    if (!std::isfinite(v)) bad_spec(std::string(what) + " must be finite");
    return v;
}

bool flag(PyObject* o, const char* what) {
    if (o != Py_True && o != Py_False) bad_spec(std::string(what) + " must be a bool");
    return o == Py_True;
}

std::vector<double> doubles(PyObject* o, const char* what) {
    std::vector<double> out;
    for (PyObject* x : sequence(o, what)) out.push_back(finite(x, what));
    return out;
}

msf::Domain domain_of(PyObject* o) {
    auto t = tuple_of(o, 4, "domain");
    msf::Domain d;
    d.has_min = flag(t[0], "domain has_min");
    d.min = finite(t[1], "domain min");
    d.has_max = flag(t[2], "domain has_max");
    d.max = finite(t[3], "domain max");
    return d;
}

CompiledProgram compile_spec(PyObject* spec) {
    if (!PyDict_CheckExact(spec)) bad_spec("spec must be a dict");
    CompiledProgram c;
    PyObject* document = item(spec, "document");
    if (!PyBytes_CheckExact(document)) bad_spec("document must be bytes");
    c.document = nb::borrow<nb::bytes>(document);
    auto sources = sequence(item(spec, "sources"), "sources");
    auto instructions = sequence(item(spec, "instructions"), "instructions");
    // Slots are the sources, then one per instruction output.
    std::size_t slots = c.program.slots = index(item(spec, "slots"), sources.size() + instructions.size() + 1, "slots");
    require(sources.size() <= slots, "more sources than slots");
    for (std::size_t i = 0; i < sources.size(); ++i) {
        auto s = tuple_of(sources[i], 2, "source");
        require(PyUnicode_CheckExact(s[0]), "source IDs must be str");
        require(!PyDict_Contains(c.source_slots.ptr(), s[0]), "duplicate source ID");
        c.source_slots[nb::handle(s[0])] = nb::int_(i);
        c.source_domains.push_back(domain_of(s[1]));
    }
    for (PyObject* r : sequence(item(spec, "required"), "required")) c.required.push_back(index(r, sources.size(), "required slot"));
    // Every slot an instruction reads holds this frame's value: a required source or an earlier output.
    std::vector<char> defined(slots);
    for (std::size_t s : c.required) defined[s] = 1;
    for (PyObject* h : instructions) {
        auto t = tuple_of(h, 9, "instruction");
        msf::Instruction ins;
        require(PyUnicode_CheckExact(t[0]), "operator must be str");
        std::string op = PyUnicode_AsUTF8(t[0]) ? PyUnicode_AsUTF8(t[0]) : "";
        PyErr_Clear();
        require(op == "identity" || op == "affine" || op == "weighted_sum" || op == "piecewise_linear", "unknown operator");
        ins.op = op == "identity" ? msf::Op::identity : op == "affine" ? msf::Op::affine
                 : op == "weighted_sum" ? msf::Op::weighted_sum : msf::Op::piecewise_linear;
        for (PyObject* s : sequence(t[1], "inputs")) ins.inputs.push_back(index(s, slots, "input slot"));
        ins.output = index(t[2], slots, "output slot");
        ins.output_domain = domain_of(t[3]);
        ins.scale = finite(t[4], "scale");
        ins.offset = finite(t[5], "offset");
        ins.weights = doubles(t[6], "weights");
        ins.xs = doubles(t[7], "knot x");
        ins.ys = doubles(t[8], "knot y");
        require(!ins.inputs.empty() && (ins.op == msf::Op::weighted_sum || ins.inputs.size() == 1), "operator arity");
        require(ins.op != msf::Op::weighted_sum || ins.weights.size() == ins.inputs.size(), "one weight per input");
        require(ins.op != msf::Op::piecewise_linear ||
                    (ins.xs.size() >= 2 && ins.xs.size() == ins.ys.size() &&
                     std::adjacent_find(ins.xs.begin(), ins.xs.end(), std::greater_equal<double>()) == ins.xs.end()),
                "piecewise knots");
        require(ins.output >= sources.size() && !defined[ins.output], "output slot");
        for (std::size_t s : ins.inputs) require(defined[s], "input slot");
        defined[ins.output] = 1;
        c.program.instructions.push_back(std::move(ins));
    }
    nb::list names;
    nb::dict seen;
    for (PyObject* h : sequence(item(spec, "outputs"), "outputs")) {
        auto t = tuple_of(h, 2, "output");
        require(PyUnicode_CheckExact(t[0]) && !PyDict_Contains(seen.ptr(), t[0]), "output IDs must be distinct str");
        seen[nb::handle(t[0])] = nb::none();
        names.append(nb::handle(t[0]));
        c.output_slots.push_back(index(t[1], slots, "output slot"));
        require(defined[c.output_slots.back()], "output slot");
    }
    c.output_names = nb::tuple(names);
    return c;
}

CompiledProgram compile(nb::handle spec) {
    try {
        return compile_spec(spec.ptr());
    } catch (const SpecError& error) {
        nb::object report = nb::module_::import_("msf_tools.report");
        nb::object fault = report.attr("Fault")("E_INTERNAL", "_core.compile", "Malformed core program spec: " + error.what + ".",
                                                "Report this diagnostic with a minimal reproducible input.");
        PyErr_SetObject(reinterpret_cast<PyObject*>(Py_TYPE(fault.ptr())), fault.ptr());
        throw nb::python_error();
    }
}

}  // namespace

NB_MODULE(_core, m) {
    m.doc() = "The msf-tools C++ core: compiled mapping programs and frame evaluation.";
    nb::class_<Frames>(m, "Frames")
        .def("view", &Frames::view)
        .def("check_view", &Frames::check_view)
        .def("__msf_state__", &Frames::state)
        .def("__len__", [](const Frames& f) { return f.count; });
    nb::class_<CompiledProgram>(m, "Program")
        .def("evaluate", &CompiledProgram::evaluate)
        .def("document", [](const CompiledProgram& c) { return c.document; })
        .def("__msf_state__", [](const CompiledProgram& c) { return c.document; });
    m.def("compile", &compile, nb::arg("spec").none());
    m.def("piecewise_clamp", &msf::piecewise_clamp);
    bind_json(m);
}
