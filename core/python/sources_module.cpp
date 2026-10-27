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

namespace nb = nanobind;
namespace paths = msf::paths;

namespace {

PyObject* path_error = nullptr;

nb::list components_to_python(const std::vector<paths::Component>& in) {
    nb::list out;
    for (const auto& c : in) out.append(nb::make_tuple(bridge::decode(c.name), c.k ? nb::object(nb::str(c.k->c_str())) : nb::object(nb::none())));
    return out;
}

std::string text_of(nb::handle s) { return bridge::wtf8_of(s); }

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
        }
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
