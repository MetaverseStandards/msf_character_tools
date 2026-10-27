// SPDX-License-Identifier: MIT
// msf_tools._core: the nanobind boundary. Python keeps the record shells; these
// handles are immutable once built, and only samples and results cross per call.
#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>

#include <algorithm>
#include <cmath>
#include <functional>
#include <optional>
#include <stdexcept>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include "msf/diagnostics.hpp"
#include "msf/mapping.hpp"
#include "msf/program.hpp"
#include "bridge.hpp"
#include "document.hpp"

namespace nb = nanobind;

void bind_json(nb::module_& m);
void bind_math3d(nb::module_& m);
void bind_authoring(nb::module_& m);

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

// A snapshot's channels (a Mapping or None) as compile_mapping reads them.
class PyChannels : public msf::mapping::Channels {
public:
    explicit PyChannels(nb::handle channels) : channels_(channels) {}

    bool has(const std::string& sid) const override {
        if (channels_.is_none()) return false;
        int found = PySequence_Contains(channels_.ptr(), bridge::decode(sid).ptr());
        if (found < 0) throw nb::python_error();
        return found == 1;
    }

    bool differs(const std::string& sid, const msf::json::Value& signal) const override {
        nb::object actual = nb::steal(PyObject_GetItem(channels_.ptr(), bridge::decode(sid).ptr()));
        if (!actual.is_valid()) throw nb::python_error();
        for (const char* key : {"value_type", "units", "domain", "calibration"}) {
            nb::object value = nb::steal(PyObject_GetItem(actual.ptr(), nb::str(key).ptr()));
            if (!value.is_valid()) throw nb::python_error();
            nb::object expected = bridge::frozen(*msf::json::find(signal, key));
            int differ = PyObject_RichCompareBool(value.ptr(), expected.ptr(), Py_NE);
            if (differ < 0) throw nb::python_error();
            if (differ) return true;
        }
        return false;
    }

    // The str keys, in iteration order.
    std::vector<std::string> ids() const {
        std::vector<std::string> out;
        if (channels_.is_none()) return out;
        nb::object it = nb::steal(PyObject_GetIter(channels_.ptr()));
        if (!it.is_valid()) throw nb::python_error();
        while (PyObject* key = PyIter_Next(it.ptr())) {
            nb::object owned = nb::steal(key);
            if (PyUnicode_CheckExact(key)) out.push_back(bridge::wtf8_of(owned));
        }
        if (PyErr_Occurred()) throw nb::python_error();
        return out;
    }

private:
    nb::handle channels_;
};

nb::tuple diagnostics_of(const std::vector<msf::Diagnostic>& diagnostics) {
    nb::list out;
    for (const msf::Diagnostic& d : diagnostics)
        out.append(nb::make_tuple(msf::info(d.code).name, msf::severity_name(d.severity()), bridge::decode(d.ref),
                                  bridge::decode(d.message), bridge::decode(d.remediation)));
    return nb::tuple(out);
}

nb::tuple strings_of(const std::vector<std::string>& items) {
    nb::list out;
    for (const std::string& item : items) out.append(bridge::decode(item));
    return nb::tuple(out);
}

// A compiled mapping: the pack it came from, its rules in execution order and,
// when every domain bound is exact in binary64, the fast program.
struct CompiledRules {
    nb::object pack;  // the Document handle, which owns the values below
    std::string mapping_id;
    msf::mapping::Compiled compiled;
    std::vector<std::string> source_channels;
    std::optional<msf::mapping::Fast> fast;
    nb::dict source_slots;
    nb::tuple output_names;
    nb::object instructions, required, outputs;  // the record's views
    nb::object key_timestamp = nb::steal(PyUnicode_InternFromString("timestamp"));
    nb::object key_values = nb::steal(PyUnicode_InternFromString("values"));
    nb::object key_validity = nb::steal(PyUnicode_InternFromString("validity"));

    const Document& document() const { return nb::cast<const Document&>(pack); }

    nb::tuple views() const { return nb::make_tuple(instructions, required, outputs); }

    // Views are deeply immutable, so being the objects built here binds them.
    bool check_views(nb::handle i, nb::handle r, nb::handle o) const {
        return i.ptr() == instructions.ptr() && r.ptr() == required.ptr() && o.ptr() == outputs.ptr();
    }

    bool compiled_from(nb::handle pack_handle, nb::handle id) const {
        return pack_handle.ptr() == pack.ptr() && PyUnicode_CheckExact(id.ptr()) && bridge::wtf8_of(id) == mapping_id;
    }

    nb::bytes state() const {
        msf::json::Value state;
        state.kind = msf::json::Value::Kind::array;
        for (const msf::json::Value* rule : compiled.instructions) state.items.push_back(*rule);
        for (const auto* list : {&compiled.required, &compiled.outputs}) {
            msf::json::Value names;
            names.kind = msf::json::Value::Kind::array;
            for (const std::string& sid : *list) names.items.push_back(msf::json::Value::make_string(sid));
            state.items.push_back(std::move(names));
        }
        std::string out = msf::json::write_exact(state);
        return nb::bytes(out.data(), out.size());
    }

    Frames frames(std::size_t count) const {
        Frames result;
        result.count = count;
        result.names = output_names;
        result.key_timestamp = key_timestamp;
        result.key_values = key_values;
        result.key_validity = key_validity;
        return result;
    }

    // Frames when every sample takes the fast path, else None. Only exact str
    // keys and exact containers are accepted, so no Python code runs while the
    // borrowed references below are in use.
    nb::object evaluate(nb::handle samples) const {
        if (!fast) return nb::none();
        const msf::Program& program = fast->program;
        nb::object items;
        if (PyTuple_CheckExact(samples.ptr()))
            items = nb::borrow(samples);
        else if (PyList_CheckExact(samples.ptr()))
            items = nb::steal(PyList_AsTuple(samples.ptr()));
        else
            return nb::none();
        std::size_t n = static_cast<std::size_t>(PyTuple_GET_SIZE(items.ptr()));
        std::size_t k = fast->output_slots.size(), sources = fast->source_domains.size();
        Frames result = frames(n);
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
                if (PyDict_GetItem(valid, key) != Py_True || !exact_number(value, d) || !fast->source_domains[slot].contains(d))
                    return nb::none();
                slots[slot] = d;
                present[slot] = 1;
            }
            for (std::size_t slot : fast->required)
                if (!present[slot]) return nb::none();
            if (!program.run(slots.data())) return nb::none();
            result.timestamps[i] = t;
            for (std::size_t j = 0; j < k; ++j) result.values[i * k + j] = slots[fast->output_slots[j]];
        }
        return nb::cast(std::move(result));
    }

    // evaluate_mapping's reference semantics for any samples: (diagnostics,
    // Frames or None).
    nb::tuple evaluate_exact(nb::handle samples) const {
        nb::object items = nb::steal(PySequence_Tuple(samples.ptr()));
        if (!items.is_valid()) throw nb::python_error();
        msf::mapping::Evaluator evaluator(document().value, compiled, source_channels);
        Py_ssize_t n = PyTuple_GET_SIZE(items.ptr());
        for (Py_ssize_t i = 0; i < n; ++i) {
            PyObject* frame = PyTuple_GET_ITEM(items.ptr(), i);
            msf::json::Value value;
            bridge::from_any(frame, value);
            std::vector<msf::mapping::Key> order = union_order(frame);
            try {
                evaluator.frame(value, order, static_cast<std::size_t>(i));
            } catch (const std::out_of_range& missing) {
                PyErr_SetObject(PyExc_KeyError, bridge::decode(missing.what()).ptr());
                throw nb::python_error();
            }
        }
        nb::object handle = nb::none();
        if (evaluator.diagnostics.empty()) {
            Frames result = frames(evaluator.timestamps.size());
            result.timestamps = std::move(evaluator.timestamps);
            result.values = std::move(evaluator.values);
            handle = nb::cast(std::move(result));
        }
        return nb::make_tuple(diagnostics_of(evaluator.diagnostics), handle);
    }

    // set(frame["values"]) | set(frame["validity"]) in Python's iteration
    // order, which hashing decides; empty when the frame has no such Mappings.
    std::vector<msf::mapping::Key> union_order(PyObject* frame) const {
        std::vector<msf::mapping::Key> out;
        if (!PyMapping_Check(frame) || PyUnicode_Check(frame) || PyList_Check(frame) || PyTuple_Check(frame)) return out;
        nb::object values = nb::steal(PyObject_GetItem(frame, key_values.ptr()));
        nb::object validity = values.is_valid() ? nb::steal(PyObject_GetItem(frame, key_validity.ptr())) : nb::object();
        if (!values.is_valid() || !validity.is_valid()) {
            PyErr_Clear();
            return out;
        }
        nb::object a = nb::steal(PySet_New(values.ptr()));
        nb::object b = a.is_valid() ? nb::steal(PySet_New(validity.ptr())) : nb::object();
        if (!a.is_valid() || !b.is_valid()) {
            PyErr_Clear();
            return out;
        }
        nb::object both = nb::steal(PyNumber_Or(a.ptr(), b.ptr()));
        if (!both.is_valid()) throw nb::python_error();
        nb::object it = nb::steal(PyObject_GetIter(both.ptr()));
        while (PyObject* key = PyIter_Next(it.ptr())) {
            nb::object owned = nb::steal(key);
            msf::mapping::Key k;
            k.is_str = PyUnicode_CheckExact(key);
            if (k.is_str) {
                k.text = bridge::wtf8_of(owned);
            } else {
                nb::object shown = nb::steal(PyObject_Str(key));
                if (!shown.is_valid()) throw nb::python_error();
                k.text = bridge::wtf8_of(shown);
            }
            out.push_back(std::move(k));
        }
        if (PyErr_Occurred()) throw nb::python_error();
        return out;
    }
};

// compile_mapping after its type and record checks: (diagnostics, losses,
// CompiledRules or None); losses as (category, effect, reason, refs, units, bound).
nb::tuple compile_mapping(nb::handle pack, nb::handle mapping_id, bool allow_approximation, nb::handle source, nb::handle target) {
    const Document& document = nb::cast<const Document&>(pack);
    PyChannels source_channels(source), target_channels(target);
    std::string id = bridge::wtf8_of(mapping_id);
    msf::mapping::Compiled compiled = msf::mapping::compile(document.value, id, allow_approximation, source_channels, target_channels);
    nb::list losses;
    for (const msf::mapping::Loss& loss : compiled.losses) {
        const msf::json::Value& row = *loss.row;
        nb::list refs;
        for (const msf::json::Value& r : msf::json::find(row, "refs")->items) refs.append(bridge::decode(r.text));
        const msf::json::Value* units = msf::json::find(row, "units");
        const msf::json::Value* bound = msf::json::find(row, "bound");
        losses.append(nb::make_tuple(bridge::decode(msf::json::find(row, "category")->text), bridge::decode(msf::json::find(row, "effect")->text),
                                     bridge::decode(msf::json::find(row, "reason")->text), nb::tuple(refs),
                                     units ? bridge::decode(units->text) : nb::object(nb::none()),
                                     bound ? bridge::to_python(*bound) : nb::object(nb::none())));
    }
    nb::tuple diagnostics = diagnostics_of(compiled.diagnostics);
    if (!compiled.ok()) return nb::make_tuple(diagnostics, nb::tuple(losses), nb::none());
    CompiledRules rules;
    rules.pack = nb::borrow(pack);
    rules.mapping_id = id;
    rules.source_channels = source_channels.ids();
    rules.fast = msf::mapping::fast_program(document.value, compiled, rules.source_channels);
    if (rules.fast)
        for (std::size_t i = 0; i < rules.fast->sources.size(); ++i) rules.source_slots[bridge::decode(rules.fast->sources[i])] = nb::int_(i);
    nb::list instructions;
    for (const msf::json::Value* rule : compiled.instructions) instructions.append(bridge::frozen(*rule));
    rules.instructions = nb::tuple(instructions);
    rules.required = strings_of(compiled.required);
    rules.outputs = strings_of(compiled.outputs);
    rules.output_names = nb::borrow<nb::tuple>(rules.outputs);
    rules.compiled = std::move(compiled);
    return nb::make_tuple(diagnostics, nb::tuple(losses), nb::cast(std::move(rules)));
}

}  // namespace

NB_MODULE(_core, m) {
    m.doc() = "The msf-tools C++ core.";
    nb::class_<Frames>(m, "Frames")
        .def("view", &Frames::view)
        .def("check_view", &Frames::check_view)
        .def("__msf_state__", &Frames::state)
        .def("__len__", [](const Frames& f) { return f.count; });
    nb::class_<CompiledRules>(m, "CompiledRules")
        .def("views", &CompiledRules::views)
        .def("check_views", &CompiledRules::check_views)
        .def("compiled_from", &CompiledRules::compiled_from)
        .def("evaluate", &CompiledRules::evaluate)
        .def("evaluate_exact", &CompiledRules::evaluate_exact)
        .def("__msf_state__", &CompiledRules::state);
    m.def("compile_mapping", &compile_mapping, nb::arg("pack"), nb::arg("mapping_id").none(), nb::arg("allow_approximation"),
          nb::arg("source").none(), nb::arg("target").none());
    bind_json(m);
    bind_math3d(m);
    bind_authoring(m);
}
