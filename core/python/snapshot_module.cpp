// SPDX-License-Identifier: MIT
// glTF snapshots across the boundary: inspection with the caller's resolver,
// the immutable Snapshot handle AssetSnapshot records own, and geometry.
#include <nanobind/nanobind.h>
#include "limited_api.hpp"
#include <nanobind/stl/string.h>

#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "bridge.hpp"
#include "msf/diagnostics.hpp"
#include "msf/gltf.hpp"
#include "msf/json.hpp"
#include "msf/sha256.hpp"

namespace nb = nanobind;
namespace gltf = msf::gltf;
using msf::json::Value;
using Kind = Value::Kind;

namespace {

PyObject* imported(const char* module, const char* name) {
    // Never released: a static nb::object would be released after interpreter shutdown.
    return nb::object(nb::module_::import_(module).attr(name)).release().ptr();
}

[[noreturn]] void raise(PyObject* type, const std::string& message) {
    PyErr_SetString(type, message.c_str());
    throw nb::python_error();
}

// The exception Python raised for text the core could not decode or parse:
// str.decode's UnicodeDecodeError, or json.loads's JSONDecodeError.
[[noreturn]] void raise_decode_error(const std::string& text) {
    nb::object decoded = nb::steal(PyUnicode_DecodeUTF8(text.data(), static_cast<Py_ssize_t>(text.size()), "strict"));
    if (!decoded.is_valid()) throw nb::python_error();
    static PyObject* loads = imported("json", "loads");
    nb::object parsed = nb::steal(PyObject_CallFunctionObjArgs(loads, decoded.ptr(), nullptr));
    if (!parsed.is_valid()) throw nb::python_error();
    raise(PyExc_ValueError, "Invalid JSON document.");
}

gltf::Bytes python_bytes(nb::handle b) {
    PyObject* o = b.ptr();
    Py_INCREF(o);
    gltf::Bytes out;
    out.view = std::string_view(PyBytes_AS_STRING(o), static_cast<std::size_t>(PyBytes_GET_SIZE(o)));
    out.keep = std::shared_ptr<const void>(o, [](PyObject* p) {
        nb::gil_scoped_acquire gil;
        Py_DECREF(p);
    });
    out.origin = o;
    return out;
}

nb::object bytes_object(const gltf::Bytes& b) {
    if (b.origin) return nb::borrow(static_cast<PyObject*>(const_cast<void*>(b.origin)));
    return nb::bytes(b.view.data(), b.view.size());
}

nb::tuple diagnostics_of(const std::vector<msf::Diagnostic>& diagnostics) {
    nb::list out;
    for (const msf::Diagnostic& d : diagnostics)
        out.append(nb::make_tuple(msf::info(d.code).name, msf::severity_name(d.severity()), bridge::decode(d.ref),
                                  bridge::decode(d.message), bridge::decode(d.remediation)));
    return nb::tuple(out);
}

// An index argument as the reference's integer() check sees it.
Value index_value(nb::handle o) {
    if (PyLong_CheckExact(o.ptr())) {
        nb::object text = nb::steal(PyObject_Str(o.ptr()));
        if (!text.is_valid()) throw nb::python_error();
        return Value::make_integer(bridge::wtf8_of(text));
    }
    Value v;
    v.kind = Kind::other;
    return v;
}

gltf::Time time_of(nb::handle o) {
    if (PyFloat_CheckExact(o.ptr())) return {Value::make_real(PyFloat_AS_DOUBLE(o.ptr())), PyFloat_AS_DOUBLE(o.ptr())};
    double seconds = PyLong_AsDouble(o.ptr());
    if (seconds == -1.0 && PyErr_Occurred()) throw nb::python_error();
    return {index_value(o), seconds};
}

// A Python error kept until evaluate_geometry reaches the point where 0.3.0 raised it.
struct SavedError {
    PyObject *type = nullptr, *value = nullptr, *trace = nullptr;
    SavedError() = default;
    SavedError(const SavedError&) = delete;
    SavedError& operator=(const SavedError&) = delete;
    ~SavedError() {
        Py_XDECREF(type);
        Py_XDECREF(value);
        Py_XDECREF(trace);
    }
    void fetch() { PyErr_Fetch(&type, &value, &trace); }
    [[noreturn]] void raise() {
        PyErr_Restore(type, value, trace);
        type = value = trace = nullptr;
        throw nb::python_error();
    }
};

// Python's `key, value = item`: an exact tuple or list of two, or an iterable
// that yields exactly two values. False with the error set otherwise.
bool unpack_pair(PyObject* item, nb::object& key, nb::object& value) {
    if (PyTuple_CheckExact(item) || PyList_CheckExact(item)) {
        Py_ssize_t n = PyTuple_CheckExact(item) ? PyTuple_GET_SIZE(item) : PyList_GET_SIZE(item);
        if (n != 2) {
            if (n > 2) PyErr_SetString(PyExc_ValueError, "too many values to unpack (expected 2)");
            else PyErr_Format(PyExc_ValueError, "not enough values to unpack (expected 2, got %zd)", n);
            return false;
        }
        auto at = [&](Py_ssize_t i) { return PyTuple_CheckExact(item) ? PyTuple_GET_ITEM(item, i) : PyList_GET_ITEM(item, i); };
        key = nb::borrow(at(0));
        value = nb::borrow(at(1));
        return true;
    }
    nb::object it = nb::steal(PyObject_GetIter(item));
    if (!it.is_valid()) {
        if (PyErr_ExceptionMatches(PyExc_TypeError)) {
            PyErr_Clear();
            nb::object type_name = nb::steal(PyObject_GetAttrString(reinterpret_cast<PyObject*>(Py_TYPE(item)), "__name__"));
            if (!type_name.is_valid()) return false;
            PyErr_Format(PyExc_TypeError, "cannot unpack non-iterable %U object", type_name.ptr());
        }
        return false;
    }
    nb::object parts[2];
    for (int k = 0; k < 2; ++k) {
        parts[k] = nb::steal(PyIter_Next(it.ptr()));
        if (!parts[k].is_valid()) {
            if (!PyErr_Occurred()) PyErr_Format(PyExc_ValueError, "not enough values to unpack (expected 2, got %d)", k);
            return false;
        }
    }
    nb::object extra = nb::steal(PyIter_Next(it.ptr()));
    if (extra.is_valid()) {
        PyErr_SetString(PyExc_ValueError, "too many values to unpack (expected 2)");
        return false;
    }
    if (PyErr_Occurred()) return false;
    key = std::move(parts[0]);
    value = std::move(parts[1]);
    return true;
}

// An override value as 0.3.0's checks read it: a Mapping through its keys and
// item lookups (keys() and item[field]), anything else as a JSON-like value.
// False with the error set when the caller's code raised.
bool override_value(PyObject* o, Value& v, PyObject* mapping) {
    try {
        int is_mapping = PyDict_CheckExact(o) ? 0 : PyObject_IsInstance(o, mapping);
        if (is_mapping < 0) return false;
        if (!is_mapping) {
            bridge::from_any(o, v, 0);
            return true;
        }
        v = Value();
        v.kind = Kind::object;
        nb::object it = nb::steal(PyObject_GetIter(o));
        if (!it.is_valid()) return false;
        while (PyObject* raw = PyIter_Next(it.ptr())) {
            nb::object key = nb::steal(raw);
            nb::object field = nb::steal(PyObject_GetItem(o, key.ptr()));
            if (!field.is_valid()) return false;
            auto& member = v.members.emplace_back();
            member.first = PyUnicode_CheckExact(key.ptr()) ? bridge::wtf8_of(key) : std::string("\xFF");
            bridge::from_any(field.ptr(), member.second, 1);
        }
        return !PyErr_Occurred();
    } catch (nb::python_error& e) {
        e.restore();
        return false;
    }
}

// 0.3.0's `for ni, item in supplied.items()`, read ahead of evaluate_geometry;
// an error the caller's code raises is saved in `error` for later.
gltf::Overrides overrides_of(nb::handle o, SavedError& error) {
    gltf::Overrides out;
    if (o.is_none()) return out;
    out.present = true;
    static PyObject* mapping = imported("collections.abc", "Mapping");
    int is_mapping = PyObject_IsInstance(o.ptr(), mapping);
    if (is_mapping < 0) throw nb::python_error();
    if (!is_mapping) return out;
    out.mapping = true;
    nb::object items = nb::steal(PyObject_CallMethod(o.ptr(), "items", nullptr));
    nb::object it = items.is_valid() ? nb::steal(PyObject_GetIter(items.ptr())) : nb::object();
    if (!it.is_valid()) {
        error.fetch();
        out.broken_tail = true;
        return out;
    }
    while (true) {
        nb::object item = nb::steal(PyIter_Next(it.ptr()));
        nb::object key, value;
        if (!item.is_valid() && !PyErr_Occurred()) break;
        if (!item.is_valid() || !unpack_pair(item.ptr(), key, value)) {
            error.fetch();
            out.broken_tail = true;
            break;
        }
        Value v;
        bool read = override_value(value.ptr(), v, mapping);
        out.items.emplace_back(index_value(key), std::move(v));
        if (!read) {
            error.fetch();
            out.broken_value = out.items.size() - 1;
            break;
        }
    }
    return out;
}

nb::object proxy(nb::handle dict) { return nb::steal(PyDictProxy_New(dict.ptr())); }

nb::object float_tuple(const double* values, std::size_t n) {
    nb::object out = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(n)));
    for (std::size_t i = 0; i < n; ++i) PyTuple_SET_ITEM(out.ptr(), static_cast<Py_ssize_t>(i), PyFloat_FromDouble(values[i]));
    return out;
}

// GeometryValues' handle: the evaluated instances view it built.
struct Positions {
    nb::object view;
    bool check_view(nb::handle candidate) const { return candidate.ptr() == view.ptr(); }
    nb::bytes state() const { return nb::bytes("positions", 9); }
};

// The record's handle: the inspected asset, or a profile document. Immutable;
// the record's views are the objects this handle built.
struct Snapshot {
    std::shared_ptr<const gltf::Asset> asset;
    std::string format, sha256;
    nb::object original, document_view;
    nb::object views, items;  // adopted once: the record's view fields, and its resource and chunk fields
    mutable std::optional<std::string> state_;

    nb::object document() {
        if (!document_view.is_valid()) document_view = bridge::frozen(asset->doc);
        return document_view;
    }

    nb::tuple resources() const {
        nb::list out;
        for (const gltf::Resource& r : asset->resources)
            out.append(nb::make_tuple(bridge::decode(r.id), r.has_uri ? bridge::decode(r.uri) : nb::object(nb::none()),
                                      bridge::to_python(r.byte_length), r.has_data ? nb::object(nb::str(r.sha256.c_str())) : nb::object(nb::none()),
                                      r.has_data ? bytes_object(r.data) : nb::object(nb::none())));
        return nb::tuple(out);
    }

    nb::tuple chunks() const {
        nb::list out;
        for (const gltf::Chunk& c : asset->chunks) out.append(nb::make_tuple(c.type, nb::bytes(c.data.data(), c.data.size())));
        return nb::tuple(out);
    }

    void adopt(nb::tuple record_views, nb::tuple record_items) {
        if (views.is_valid()) raise(PyExc_RuntimeError, "Snapshot views are already adopted.");
        views = record_views;
        items = record_items;
    }

    // A fresh handle on the same asset, for another record.
    Snapshot fork() const {
        Snapshot out;
        out.asset = asset;
        out.format = format;
        out.sha256 = sha256;
        out.original = original;
        out.document_view = document_view;
        return out;
    }

    // Identity, item by item: every adopted object is immutable or one the
    // record keeps, so the same objects mean the same state.
    static bool same(const nb::object& adopted, nb::handle candidate) {
        if (!adopted.is_valid() || !PyTuple_CheckExact(candidate.ptr())) return false;
        Py_ssize_t n = PyTuple_GET_SIZE(adopted.ptr());
        if (PyTuple_GET_SIZE(candidate.ptr()) != n) return false;
        for (Py_ssize_t i = 0; i < n; ++i)
            if (PyTuple_GET_ITEM(adopted.ptr(), i) != PyTuple_GET_ITEM(candidate.ptr(), i)) return false;
        return true;
    }
    bool check(nb::handle record_views) const { return same(views, record_views); }
    bool check_items(nb::handle record_items) const { return same(items, record_items); }

    nb::bytes state() const {
        if (!state_) state_ = format + "\n" + sha256;
        return nb::bytes(state_->data(), state_->size());
    }

    // The fingerprint's UnicodeEncodeError for the first lone surrogate in the document.
    void check_encodable() const { first_surrogate(asset->doc); }
    static void first_surrogate(const Value& v) {
        if (v.kind == Kind::string) bridge::utf8_bytes(v.text);
        for (const auto& [key, child] : v.members) {
            bridge::utf8_bytes(key);
            first_surrogate(child);
        }
        for (const Value& item : v.items) first_surrogate(item);
    }

    void validate(long long accessor, long long total) const { gltf::validate_document(asset->doc, gltf::Caps{accessor, total}); }

    nb::tuple morph_counts() const {
        nb::list out;
        if (const Value* meshes = msf::json::find(asset->doc, "meshes"))
            for (const Value& mesh : meshes->items) out.append(gltf::morph_count(mesh));
        return nb::tuple(out);
    }

    nb::tuple decode(nb::handle id, const std::string& ref) const {
        gltf::Rows rows = gltf::decode_accessor(*asset, index_value(id), ref);
        nb::object out = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(rows.count)));
        for (std::size_t r = 0; r < rows.count; ++r) {
            nb::object row = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(rows.width)));
            for (std::size_t k = 0; k < rows.width; ++k) {
                double v = rows.at(r, k);
                PyObject* item = rows.integers ? PyLong_FromLongLong(static_cast<long long>(v)) : PyFloat_FromDouble(v);
                PyTuple_SET_ITEM(row.ptr(), static_cast<Py_ssize_t>(k), item);
            }
            PyTuple_SET_ITEM(out.ptr(), static_cast<Py_ssize_t>(r), row.release().ptr());
        }
        return nb::borrow<nb::tuple>(out);
    }

    nb::object sample(nb::handle animation_id, nb::handle timestamp) const {
        gltf::Pose pose = gltf::sample_animation(*asset, index_value(animation_id), time_of(timestamp));
        nb::object out = nb::steal(PyDict_New());
        for (const auto& [node, paths] : pose) {
            nb::object values = nb::steal(PyDict_New());
            for (const auto& [path, value] : paths)
                PyDict_SetItem(values.ptr(), bridge::decode(path).ptr(), float_tuple(value.data(), value.size()).ptr());
            PyDict_SetItem(out.ptr(), nb::int_(node).ptr(), proxy(values).ptr());
        }
        return proxy(out);
    }

    // (diagnostics, Positions or None)
    nb::tuple evaluate(nb::handle timestamp, nb::handle animation_id, nb::handle morph_weights, nb::handle node_transforms,
                       long long budget) const {
        gltf::Time t = time_of(timestamp);
        std::optional<Value> animation;
        if (!animation_id.is_none()) animation = index_value(animation_id);
        SavedError morph_error, transforms_error;
        gltf::Overrides morph = overrides_of(morph_weights, morph_error), transforms = overrides_of(node_transforms, transforms_error);
        gltf::Geometry geometry;
        try {
            geometry = gltf::evaluate_geometry(*asset, t, animation ? &*animation : nullptr, morph, transforms, budget);
        } catch (const gltf::OverridesBroken& broken) {
            (broken.label == "morph_weights" ? morph_error : transforms_error).raise();
        }
        if (!geometry.diagnostics.empty()) return nb::make_tuple(diagnostics_of(geometry.diagnostics), nb::none());
        return nb::make_tuple(nb::tuple(), nb::cast(Positions{instances_view(geometry)}));
    }

    // Test hook: (world matrices, {joint: palette}) as evaluate built them.
    nb::tuple witness(nb::handle timestamp, nb::handle animation_id, long long budget) const {
        std::optional<Value> animation;
        if (!animation_id.is_none()) animation = index_value(animation_id);
        gltf::Geometry geometry = gltf::evaluate_geometry(*asset, time_of(timestamp), animation ? &*animation : nullptr, {}, {}, budget);
        auto rows = [](const std::array<std::array<double, 4>, 4>& m) {
            return nb::make_tuple(float_tuple(m[0].data(), 4), float_tuple(m[1].data(), 4), float_tuple(m[2].data(), 4), float_tuple(m[3].data(), 4));
        };
        nb::list worlds;
        for (const auto& m : geometry.worlds) worlds.append(rows(m));
        nb::dict palettes;
        for (const auto& [j, m] : geometry.palettes) palettes[nb::int_(j)] = rows(m);
        return nb::make_tuple(nb::tuple(worlds), palettes);
    }

    static nb::object instances_view(const gltf::Geometry& geometry) {
        static PyObject* k_node = PyUnicode_InternFromString("node");
        static PyObject* k_mesh = PyUnicode_InternFromString("mesh");
        static PyObject* k_primitives = PyUnicode_InternFromString("primitives");
        static PyObject* k_primitive = PyUnicode_InternFromString("primitive");
        static PyObject* k_positions = PyUnicode_InternFromString("positions");
        nb::object instances = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(geometry.instances.size())));
        for (std::size_t i = 0; i < geometry.instances.size(); ++i) {
            const gltf::Instance& instance = geometry.instances[i];
            nb::object primitives = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(instance.primitives.size())));
            for (std::size_t p = 0; p < instance.primitives.size(); ++p) {
                const gltf::PrimitivePositions& primitive = instance.primitives[p];
                nb::object positions = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(primitive.positions.size())));
                for (std::size_t v = 0; v < primitive.positions.size(); ++v)
                    PyTuple_SET_ITEM(positions.ptr(), static_cast<Py_ssize_t>(v), float_tuple(primitive.positions[v].data(), 3).release().ptr());
                nb::object entry = nb::steal(PyDict_New());
                PyDict_SetItem(entry.ptr(), k_primitive, nb::int_(primitive.primitive).ptr());
                PyDict_SetItem(entry.ptr(), k_positions, positions.ptr());
                PyTuple_SET_ITEM(primitives.ptr(), static_cast<Py_ssize_t>(p), proxy(entry).release().ptr());
            }
            nb::object entry = nb::steal(PyDict_New());
            PyDict_SetItem(entry.ptr(), k_node, nb::int_(instance.node).ptr());
            PyDict_SetItem(entry.ptr(), k_mesh, nb::int_(instance.mesh).ptr());
            PyDict_SetItem(entry.ptr(), k_primitives, primitives.ptr());
            PyTuple_SET_ITEM(instances.ptr(), static_cast<Py_ssize_t>(i), proxy(entry).release().ptr());
        }
        return instances;
    }
};

// (diagnostics, Snapshot) from _inspect_gltf's pipeline after its size and
// resolver checks; the caller handles the sidecar and admission.
nb::tuple inspect(nb::bytes raw, bool glb, nb::object resolver, long long accessor_cap, long long total_cap, bool generated) {
    gltf::Resolve resolve = [&](const std::string& uri, const std::string& ref, bool image) -> std::optional<gltf::Bytes> {
        if (image) {
            int truth = PyObject_IsTrue(resolver.ptr());
            if (truth < 0) throw nb::python_error();
            if (!truth) return std::nullopt;
        }
        nb::object data = resolver(bridge::decode(uri));
        if (image && data.is_none()) return std::nullopt;
        if (!PyBytes_CheckExact(data.ptr())) msf::fail(msf::Code::E_RESOLVER, ref, "Resolver must return immutable bytes.");
        return python_bytes(data);
    };
    gltf::Inspection result;
    try {
        result = gltf::inspect(python_bytes(raw), glb, resolver.is_none() ? nullptr : &resolve, gltf::Caps{accessor_cap, total_cap}, generated);
    } catch (const gltf::DuplicateKey& e) {
        nb::object key = nb::steal(PyObject_Repr(bridge::decode(e.key).ptr()));
        if (!key.is_valid()) throw nb::python_error();
        msf::fail(msf::Code::E_DUPLICATE_KEY, "/", "Duplicate JSON key " + bridge::wtf8_of(key) + ".");
    }
    Snapshot handle;
    handle.format = result.asset->format;
    handle.sha256 = result.asset->sha256;
    handle.original = raw;
    handle.asset = result.asset;
    return nb::make_tuple(diagnostics_of(result.diagnostics), nb::cast(std::move(handle)));
}

nb::object profile(nb::bytes raw, const std::string& sha256, nb::handle document) {
    Snapshot handle;
    handle.format = "profile";
    handle.sha256 = sha256;
    handle.original = raw;
    handle.document_view = nb::borrow(document);
    return nb::cast(std::move(handle));
}

}  // namespace

void bind_snapshot(nb::module_& m) {
    nb::register_exception_translator([](const std::exception_ptr& p, void*) {
        try {
            std::rethrow_exception(p);
        } catch (const gltf::DecodeError& e) {
            try {
                raise_decode_error(e.text);
            } catch (nb::python_error& error) {
                error.restore();
            }
        } catch (const gltf::TooDeep&) {
            PyErr_SetString(PyExc_RecursionError, msf::json::kTooDeep);
        } catch (const gltf::InternalError& e) {
            static PyObject* struct_error = imported("struct", "error");
            PyErr_SetString(struct_error, e.what.c_str());
        } catch (const gltf::TypeError& e) {
            PyErr_SetString(PyExc_TypeError, e.what.c_str());
        }
    });
    nb::class_<Snapshot>(m, "Snapshot")
        .def_ro("format", &Snapshot::format)
        .def_ro("sha256", &Snapshot::sha256)
        .def_ro("original", &Snapshot::original)
        .def("document", &Snapshot::document)
        .def("resources", &Snapshot::resources)
        .def("chunks", &Snapshot::chunks)
        .def("adopt", &Snapshot::adopt)
        .def("fork", &Snapshot::fork)
        .def("check", &Snapshot::check)
        .def("check_items", &Snapshot::check_items)
        .def("__msf_state__", &Snapshot::state)
        .def("check_encodable", &Snapshot::check_encodable)
        .def("validate", &Snapshot::validate)
        .def("morph_counts", &Snapshot::morph_counts)
        .def("decode", &Snapshot::decode, nb::arg("index").none(), nb::arg("ref"))
        .def("sample", &Snapshot::sample, nb::arg("animation_id").none(), nb::arg("timestamp"))
        .def("_witness", &Snapshot::witness, nb::arg("timestamp"), nb::arg("animation_id").none(), nb::arg("budget"))
        .def("evaluate", &Snapshot::evaluate, nb::arg("timestamp"), nb::arg("animation_id").none(), nb::arg("morph_weights").none(),
             nb::arg("node_transforms").none(), nb::arg("budget"));
    nb::class_<Positions>(m, "Positions")
        .def_ro("view", &Positions::view)
        .def("check_view", &Positions::check_view)
        .def("__msf_state__", &Positions::state);
    m.def("inspect_gltf", &inspect, nb::arg("raw"), nb::arg("glb"), nb::arg("resolver").none(), nb::arg("accessor_cap"),
          nb::arg("total_cap"), nb::arg("generated"));
    m.def("profile_snapshot", &profile, nb::arg("raw"), nb::arg("sha256"), nb::arg("document"));
}
