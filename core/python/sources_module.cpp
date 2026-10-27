// SPDX-License-Identifier: MIT
// Source conversion helpers across the boundary: the path grammar, matrix
// decomposition, influence rows, the GLB writer and the FBX adapter.
#include <nanobind/nanobind.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "bridge.hpp"
#include "msf/paths.hpp"
#include "msf/pyerror.hpp"
#include "msf/sources.hpp"

namespace nb = nanobind;
namespace paths = msf::paths;
namespace sources = msf::sources;

namespace {

PyObject* path_error = nullptr;

nb::list components_to_python(const std::vector<paths::Component>& in) {
    nb::list out;
    for (const auto& c : in) out.append(nb::make_tuple(bridge::decode(c.name), c.k ? nb::object(nb::str(c.k->c_str())) : nb::object(nb::none())));
    return out;
}

std::string text_of(nb::handle s) { return bridge::wtf8_of(s); }

sources::Matrix matrix_of(nb::handle m) {
    sources::Matrix out{};
    std::size_t i = 0;
    for (nb::handle x : m) {
        if (i == 16) throw nb::value_error("Matrices have 16 numbers.");
        out[i++] = nb::cast<double>(nb::float_(x));
    }
    if (i != 16) throw nb::value_error("Matrices have 16 numbers.");
    return out;
}

nb::tuple floats(const double* v, std::size_t n) {
    nb::list out;
    for (std::size_t i = 0; i < n; ++i) out.append(v[i]);
    return nb::tuple(out);
}

nb::tuple diagnostics_of(const std::vector<msf::Diagnostic>& diagnostics) {
    nb::list out;
    for (const msf::Diagnostic& d : diagnostics)
        out.append(nb::make_tuple(msf::info(d.code).name, msf::severity_name(d.severity()), bridge::decode(d.ref),
                                  bridge::decode(d.message), bridge::decode(d.remediation)));
    return nb::tuple(out);
}

sources::Influences influences_of(nb::handle pairs) {
    sources::Influences out;
    for (nb::handle pair : pairs) out.emplace_back(nb::cast<long long>(pair[0]), nb::cast<double>(nb::float_(pair[1])));
    return out;
}

}  // namespace

void bind_sources(nb::module_& m) {
    path_error = PyErr_NewException("msf_tools._core.PathError", PyExc_ValueError, nullptr);
    m.attr("PathError") = nb::borrow(path_error);
    nb::register_exception_translator([](const std::exception_ptr& p, void*) {
        try {
            std::rethrow_exception(p);
        } catch (const paths::Error& e) {
            nb::object args = nb::make_tuple(nb::str(e.kind.c_str()), bridge::decode(e.text));
            PyErr_SetObject(path_error, args.ptr());
        } catch (const sources::Singular&) {
            PyErr_SetString(PyExc_ValueError, "Transform is singular.");
        } catch (const msf::PyError& e) {
            PyObject* type = e.type == msf::PyError::Type::overflow        ? PyExc_OverflowError
                             : e.type == msf::PyError::Type::zero_division ? PyExc_ZeroDivisionError
                             : e.type == msf::PyError::Type::type          ? PyExc_TypeError
                                                                           : PyExc_ValueError;
            PyErr_SetString(type, e.message.c_str());
        }
    });
    m.def("_is_affine", [](nb::handle m) { return sources::is_affine(matrix_of(m)); });
    m.def("_has_shear", [](nb::handle m) { return sources::has_shear(matrix_of(m)); });
    m.def("_determinant", [](nb::handle m) { return sources::determinant(matrix_of(m)); });
    m.def("_decompose", [](nb::handle m) {
        sources::Trs trs = sources::decompose(matrix_of(m));
        return nb::make_tuple(floats(trs.translation.data(), 3), floats(trs.rotation.data(), 4), floats(trs.scale.data(), 3));
    });
    m.def("_merge", [](nb::handle pairs, const std::string& path) {
        nb::list out;
        for (const auto& [joint, weight] : sources::merge(influences_of(pairs), path)) out.append(nb::make_tuple(joint, weight));
        return out;
    });
    m.def("_influence_rows", [](nb::handle merged_rows, long long root, bool top4, const std::string& path, const std::string& unweighted_to) {
        std::vector<sources::Influences> rows;
        for (nb::handle row : merged_rows) rows.push_back(influences_of(row));
        sources::Rows result = sources::influence_rows(rows, root, top4, path, unweighted_to);
        nb::list out;
        for (const auto& row : result.rows) {
            nb::list pairs;
            for (const auto& [joint, weight] : row) pairs.append(nb::make_tuple(joint, weight));
            out.append(nb::tuple(pairs));
        }
        return nb::make_tuple(nb::tuple(out), diagnostics_of(result.losses));
    });
    m.def("_paths_escape", [](nb::handle name) { return bridge::decode(paths::escape(text_of(name))); });
    m.def("_paths_unescape", [](nb::handle text) { return bridge::decode(paths::unescape(text_of(text))); });
    m.def("_paths_node_path", [](nb::handle components, nb::handle helper) {
        std::vector<paths::Component> parts;
        for (nb::handle c : components) {
            nb::handle k = c[1];
            parts.push_back({text_of(c[0]), k.is_none() ? std::nullopt : std::optional<std::string>(text_of(k))});
        }
        std::optional<paths::Component> h;
        if (!helper.is_none()) {
            nb::handle k = helper[1];
            h = paths::Component{text_of(helper[0]), k.is_none() ? std::nullopt : std::optional<std::string>(text_of(k))};
        }
        return bridge::decode(paths::node_path(parts, h));
    }, nb::arg("components"), nb::arg("helper").none());
    m.def("_paths_target_key", [](nb::handle components) {
        std::vector<paths::Component> parts;
        for (nb::handle c : components) {
            nb::handle k = c[1];
            parts.push_back({text_of(c[0]), k.is_none() ? std::nullopt : std::optional<std::string>(text_of(k))});
        }
        return bridge::decode(paths::target_key(parts));
    });
    m.def("_paths_parse_node_path", [](nb::handle path) {
        paths::NodePath parsed = paths::parse_node_path(text_of(path));
        nb::object helper = nb::none();
        if (parsed.helper)
            helper = nb::make_tuple(nb::str(parsed.helper->name.c_str()),
                                    parsed.helper->k ? nb::object(nb::str(parsed.helper->k->c_str())) : nb::object(nb::none()));
        return nb::make_tuple(components_to_python(parsed.components), helper);
    });
    m.def("_paths_parse_target_key", [](nb::handle key) { return components_to_python(paths::parse_target_key(text_of(key))); });
}
