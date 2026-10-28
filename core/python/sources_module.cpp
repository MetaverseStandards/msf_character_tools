// SPDX-License-Identifier: MIT
// Source conversion helpers across the boundary: the path grammar, matrix
// decomposition, influence rows, the GLB writer and the FBX adapter.
#include <nanobind/nanobind.h>
#include "limited_api.hpp"
#include <nanobind/stl/optional.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <limits>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <cstdint>
#include <cstring>

#include "bridge.hpp"
#include "msf/json.hpp"
#include "msf/fbx.hpp"
#include "msf/paths.hpp"
#include "msf_ufbx_shim.h"
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

double float_of(nb::handle x) {
    nb::object f = nb::steal(PyNumber_Float(x.ptr()));
    if (!f.is_valid()) throw nb::python_error();
    return PyFloat_AS_DOUBLE(f.ptr());
}

// An exact Python int that fits, else -1: the writer refuses both the same way.
long long int_of(nb::handle x) {
    if (!PyLong_CheckExact(x.ptr())) return -1;
    int overflow = 0;
    long long v = PyLong_AsLongLongAndOverflow(x.ptr(), &overflow);
    if (overflow) return overflow > 0 ? std::numeric_limits<long long>::max() : -1;
    return v;
}

std::optional<long long> optional_int(nb::handle x) {
    if (x.is_none()) return std::nullopt;
    return int_of(x);
}

std::vector<double> floats_of(nb::handle values) {
    std::vector<double> out;
    for (nb::handle x : values) out.push_back(float_of(x));
    return out;
}

std::vector<std::vector<double>> rows_of(nb::handle rows) {
    std::vector<std::vector<double>> out;
    for (nb::handle row : rows) out.push_back(floats_of(row));
    return out;
}

std::vector<long long> ints_of(nb::handle values) {
    std::vector<long long> out;
    for (nb::handle x : values) out.push_back(int_of(x));
    return out;
}

std::optional<std::string> optional_text(nb::handle x) {
    if (x.is_none()) return std::nullopt;
    return text_of(x);
}

// The ufbx shim for tests: each method mirrors one shim call, returning None
// (or the error text) where the call returns 0.
struct FbxScene {
    msf_fbx* h = nullptr;
    nb::object data;  // the bytes ufbx read, kept for the scene's lifetime
    ~FbxScene() {
        if (h) msf_fbx_close(h);
    }
    FbxScene() = default;
    FbxScene(const FbxScene&) = delete;
    FbxScene(FbxScene&& o) noexcept : h(o.h), data(std::move(o.data)) { o.h = nullptr; }

    nb::dict info() const {
        msf_fbx_info i;
        msf_fbx_info_get(h, &i);
        nb::dict out;
        out["nodes"] = i.nodes;
        out["meshes"] = i.meshes;
        out["anim_stacks"] = i.anim_stacks;
        out["helper_nodes"] = i.helper_nodes;
        out["unit_meters"] = i.unit_meters;
        out["fps"] = i.fps;
        out["ascii"] = i.ascii;
        out["version"] = i.version;
        out["axes_converted"] = i.axes_converted;
        out["blend_channels"] = i.blend_channels;
        out["materials"] = i.materials;
        out["textures"] = i.textures;
        return out;
    }
    nb::object node(uint32_t i) const {
        msf_fbx_node n;
        if (!msf_fbx_node_get(h, i, &n)) return nb::none();
        nb::dict out;
        out["parent"] = n.parent;
        out["name"] = nb::bytes(n.name, n.name_len);
        out["mesh"] = n.mesh;
        out["is_bone"] = n.is_bone;
        out["helper"] = n.helper;
        out["inherit_mode"] = n.inherit_mode;
        out["original_inherit_mode"] = n.original_inherit_mode;
        out["pivots"] = n.pivots;
        out["skipped"] = n.skipped ? nb::object(nb::str(n.skipped)) : nb::object(nb::none());
        out["to_parent"] = floats(n.to_parent, 16);
        out["to_world"] = floats(n.to_world, 16);
        return out;
    }
    nb::object mesh_sizes(uint32_t m) const {
        uint32_t sizes[8];
        if (!msf_fbx_mesh_sizes(h, m, sizes)) return nb::none();
        return nb::make_tuple(sizes[0], sizes[1], sizes[2], sizes[3], sizes[4], sizes[5], sizes[6], sizes[7]);
    }
    nb::object mesh_fill(uint32_t m, uint32_t points, uint32_t triangles) const {
        std::vector<double> positions(3 * static_cast<std::size_t>(points) + 1);
        std::vector<uint32_t> tri(3 * static_cast<std::size_t>(triangles) + 1);
        if (!msf_fbx_mesh_fill(h, m, positions.data(), points, tri.data(), triangles)) return nb::none();
        nb::list p, t;
        for (std::size_t i = 0; i < 3 * static_cast<std::size_t>(points); ++i) p.append(positions[i]);
        for (std::size_t i = 0; i < 3 * static_cast<std::size_t>(triangles); ++i) t.append(tri[i]);
        return nb::make_tuple(p, t);
    }
    nb::object skin_sizes(uint32_t m, uint32_t d) const {
        uint32_t sizes[2];
        if (!msf_fbx_skin_sizes(h, m, d, sizes)) return nb::none();
        return nb::make_tuple(sizes[0], sizes[1]);
    }
    nb::object skin_fill(uint32_t m, uint32_t d, uint32_t points, uint32_t entries, uint32_t clusters) const {
        std::vector<uint32_t> offsets(points + 1), which(entries + 1);
        std::vector<double> weights(entries + 1), binds(16 * static_cast<std::size_t>(clusters) + 1);
        std::vector<int32_t> nodes(clusters + 1);
        int method = 0;
        if (!msf_fbx_skin_fill(h, m, d, offsets.data(), points, which.data(), weights.data(), entries, nodes.data(), binds.data(), clusters, &method))
            return nb::none();
        nb::list o, w, wt, n, b;
        for (uint32_t i = 0; i <= points; ++i) o.append(offsets[i]);
        for (uint32_t i = 0; i < entries; ++i) {
            w.append(which[i]);
            wt.append(weights[i]);
        }
        for (uint32_t i = 0; i < clusters; ++i) n.append(nodes[i]);
        for (std::size_t i = 0; i < 16 * static_cast<std::size_t>(clusters); ++i) b.append(binds[i]);
        return nb::make_tuple(o, w, wt, n, b, method);
    }
    nb::object blend_sizes(uint32_t m, uint32_t c) const {
        uint32_t sizes[2];
        if (!msf_fbx_blend_sizes(h, m, c, sizes)) return nb::none();
        return nb::make_tuple(sizes[0], sizes[1]);
    }
    nb::object blend_fill(uint32_t m, uint32_t c, uint32_t keyframes, uint32_t total) const {
        uint32_t deformer = 0;
        std::vector<uint32_t> counts(keyframes + 1), indices(total + 1);
        std::vector<double> offsets(3 * static_cast<std::size_t>(total) + 1), targets(keyframes + 1);
        double weight = 0;
        const char* names[2] = {nullptr, nullptr};
        size_t lengths[2] = {0, 0};
        if (!msf_fbx_blend_fill(h, m, c, &deformer, counts.data(), indices.data(), offsets.data(), targets.data(), keyframes, total, &weight, names,
                                lengths))
            return nb::none();
        nb::dict out;
        nb::list k, i, o, t;
        for (uint32_t x = 0; x < keyframes; ++x) {
            k.append(counts[x]);
            t.append(targets[x]);
        }
        for (uint32_t x = 0; x < total; ++x) i.append(indices[x]);
        for (std::size_t x = 0; x < 3 * static_cast<std::size_t>(total); ++x) o.append(offsets[x]);
        out["deformer"] = deformer;
        out["counts"] = k;
        out["indices"] = i;
        out["offsets"] = o;
        out["targets"] = t;
        out["weight"] = weight;
        out["names"] = nb::make_tuple(nb::bytes(names[0], lengths[0]), nb::bytes(names[1], lengths[1]));
        return out;
    }
    nb::object stack(uint32_t s) const {
        msf_fbx_stack st;
        if (!msf_fbx_stack_get(h, s, &st)) return nb::none();
        return nb::make_tuple(nb::bytes(st.name, st.name_len), st.time_begin, st.time_end);
    }
    nb::object blend_channel_id(uint32_t m, uint32_t c) const {
        uint32_t id = 0;
        if (!msf_fbx_blend_channel_id(h, m, c, &id)) return nb::none();
        return nb::int_(id);
    }
    // (to_parent, to_world or None, channel weights), or the error text.
    nb::object evaluate(uint32_t s, double time, uint32_t nodes, uint32_t channels, bool world) const {
        std::vector<double> to_parent(16 * static_cast<std::size_t>(nodes) + 1), to_world(16 * static_cast<std::size_t>(nodes) + 1),
            weights(channels + 1);
        char err[512] = {0};
        if (!msf_fbx_evaluate(h, s, time, to_parent.data(), world ? to_world.data() : nullptr, nodes, weights.data(), channels, err, sizeof err))
            return nb::bytes(err, std::strlen(err));
        return nb::make_tuple(floats(to_parent.data(), 16 * static_cast<std::size_t>(nodes)),
                              world ? nb::object(floats(to_world.data(), 16 * static_cast<std::size_t>(nodes))) : nb::object(nb::none()),
                              floats(weights.data(), channels));
    }
    // ufbx's own world-space skinned positions, or the error text.
    nb::object skinned_points(int32_t s, double time, uint32_t m, uint32_t points) const {
        std::vector<double> world(3 * static_cast<std::size_t>(points) + 1);
        char err[256] = {0};
        if (!msf_fbx_skinned_points(h, s, time, m, world.data(), points, err, sizeof err)) return nb::bytes(err, std::strlen(err));
        return floats(world.data(), 3 * static_cast<std::size_t>(points));
    }
};

}  // namespace

void bind_sources(nb::module_& m) {
    path_error = PyErr_NewException("msf_character_tools._core.PathError", PyExc_ValueError, nullptr);
    m.attr("PathError") = nb::borrow(path_error);
    nb::register_exception_translator([](const std::exception_ptr& p, void*) {
        try {
            std::rethrow_exception(p);
        } catch (const paths::Error& e) {
            nb::object args = nb::make_tuple(nb::str(e.kind.c_str()), bridge::decode(e.text));
            PyErr_SetObject(path_error, args.ptr());
        } catch (const sources::WriteError& e) {
            PyErr_SetString(PyExc_ValueError, e.message.c_str());
        } catch (const sources::Singular&) {
            PyErr_SetString(PyExc_ValueError, "Transform is singular.");
        } catch (const msf::PyError& e) {
            PyObject* type = e.type == msf::PyError::Type::overflow        ? PyExc_OverflowError
                             : e.type == msf::PyError::Type::zero_division ? PyExc_ZeroDivisionError
                             : e.type == msf::PyError::Type::type          ? PyExc_TypeError
                             : e.type == msf::PyError::Type::index         ? PyExc_IndexError
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
    m.def("_write_glb", [](nb::handle nodes, nb::handle meshes, nb::handle skins, nb::handle animations, nb::handle generator) {
        std::vector<sources::Mesh> mesh_list;
        for (nb::handle mesh : meshes) {
            sources::Mesh m;
            m.points = rows_of(mesh.attr("points"));
            m.triangles = ints_of(mesh.attr("triangles"));
            for (nb::handle t : mesh.attr("targets")) m.targets.push_back(rows_of(t));
            nb::object influences = mesh.attr("influences");
            if (!influences.is_none()) {
                m.skinned = true;
                for (nb::handle pairs : influences) {
                    sources::Influences row;
                    for (nb::handle pair : pairs) row.emplace_back(int_of(pair[0]), float_of(pair[1]));
                    m.influences.push_back(std::move(row));
                }
            }
            m.weights = floats_of(mesh.attr("weights"));
            mesh_list.push_back(std::move(m));
        }
        std::vector<sources::Skin> skin_list;
        for (nb::handle skin : skins)
            skin_list.push_back({ints_of(skin.attr("joints")), rows_of(skin.attr("inverse_bind_matrices")), optional_int(skin.attr("skeleton"))});
        std::vector<sources::Node> node_list;
        for (nb::handle node : nodes) {
            sources::Node n;
            n.name = optional_text(node.attr("name"));
            n.children = ints_of(node.attr("children"));
            n.translation = floats_of(node.attr("translation"));
            n.rotation = floats_of(node.attr("rotation"));
            n.scale = floats_of(node.attr("scale"));
            n.mesh = optional_int(node.attr("mesh"));
            n.skin = optional_int(node.attr("skin"));
            nb::object weights = node.attr("weights");
            if (!weights.is_none()) n.weights = floats_of(weights);
            node_list.push_back(std::move(n));
        }
        std::vector<sources::Animation> animation_list;
        for (nb::handle anim : animations) {
            sources::Animation a;
            for (nb::handle channel : anim.attr("channels")) {
                sources::Channel c;
                nb::object node = channel.attr("node");
                c.node = int_of(node);
                c.node_ok = PyLong_CheckExact(node.ptr());
                c.path = text_of(channel.attr("path"));
                c.times = floats_of(channel.attr("times"));
                c.values = rows_of(channel.attr("values"));
                c.interpolation = text_of(channel.attr("interpolation"));
                a.channels.push_back(std::move(c));
            }
            a.name = optional_text(anim.attr("name"));
            animation_list.push_back(std::move(a));
        }
        std::string glb = sources::write_glb(node_list, mesh_list, skin_list, animation_list, text_of(generator));
        std::uint32_t length;
        std::memcpy(&length, glb.data() + 12, 4);
        std::string chunk = glb.substr(20, length);
        if (msf::json::has_surrogate(chunk)) bridge::utf8_bytes(chunk);
        return nb::bytes(glb.data(), glb.size());
    });
    static PyObject* parse_error = PyErr_NewException("msf_character_tools._core.FbxParseError", PyExc_Exception, nullptr);
    m.attr("FbxParseError") = nb::borrow(parse_error);
    m.attr("UFBX_VERSION") = msf::fbx::ufbx_version();
    m.def("_fbx_convert", [](nb::bytes data, bool top4, nb::handle animation, nb::handle sample_rate, unsigned long long max_reader_memory,
                             nb::handle max_animation_values, nb::handle generator) {
        msf::fbx::Options options;
        options.top4 = top4;
        if (PyUnicode_Check(animation.ptr())) options.animation_name = text_of(animation);
        else if (!animation.is_none()) options.animation_index = int_of(animation);
        if (!sample_rate.is_none()) options.sample_rate = float_of(sample_rate);
        options.repr = [](const std::string& text) {
            nb::object shown = nb::steal(PyObject_Repr(bridge::decode(text).ptr()));
            if (!shown.is_valid()) throw nb::python_error();
            return bridge::wtf8_of(shown);
        };
        msf::fbx::Limits limits;
        limits.max_reader_memory = max_reader_memory;
        int overflow = 0;
        limits.max_animation_values = PyLong_AsLongLongAndOverflow(max_animation_values.ptr(), &overflow);
        if (overflow) limits.max_animation_values = std::numeric_limits<long long>::max();
        limits.max_animation_values_text = text_of(nb::str(max_animation_values));
        msf::fbx::Generated generated;
        try {
            generated = msf::fbx::convert(std::string_view(data.c_str(), data.size()), options, limits, text_of(generator));
        } catch (const msf::fbx::ParseError& e) {
            PyErr_SetString(parse_error, e.message.c_str());
            throw nb::python_error();
        } catch (const msf::fbx::NoStack&) {
            nb::object shown = nb::steal(PyObject_Repr(animation.ptr()));
            if (!shown.is_valid()) throw nb::python_error();
            msf::fail(msf::Code::E_SOURCE_OPTIONS, "/options/animation", "The file has no animation stack named " + text_of(shown) + ".");
        }
        nb::list node_paths, target_keys;
        for (const auto& p : generated.node_paths) node_paths.append(bridge::decode(p));
        for (const auto& keys : generated.target_keys) {
            nb::list row;
            for (const auto& k : keys) row.append(bridge::decode(k));
            target_keys.append(row);
        }
        return nb::make_tuple(nb::bytes(generated.glb.data(), generated.glb.size()), node_paths, target_keys, diagnostics_of(generated.losses));
    }, nb::arg("data"), nb::arg("top4"), nb::arg("animation").none(), nb::arg("sample_rate").none(), nb::arg("max_reader_memory"),
       nb::arg("max_animation_values"), nb::arg("generator"));
    nb::class_<FbxScene>(m, "_FbxScene")
        .def("info", &FbxScene::info)
        .def("node", &FbxScene::node)
        .def("mesh_sizes", &FbxScene::mesh_sizes)
        .def("mesh_fill", &FbxScene::mesh_fill)
        .def("skin_sizes", &FbxScene::skin_sizes)
        .def("skin_fill", &FbxScene::skin_fill)
        .def("blend_sizes", &FbxScene::blend_sizes)
        .def("blend_fill", &FbxScene::blend_fill)
        .def("stack", &FbxScene::stack)
        .def("blend_channel_id", &FbxScene::blend_channel_id)
        .def("evaluate", &FbxScene::evaluate, nb::arg("stack"), nb::arg("time"), nb::arg("nodes"), nb::arg("channels"), nb::arg("world") = false)
        .def("skinned_points", &FbxScene::skinned_points);
    // (scene, "") or (None, error text), as msf_fbx_open reports them.
    m.def("_fbx_open", [](nb::bytes data, std::size_t memory_limit, std::size_t allocation_limit) {
        static const uint8_t empty = 0;
        msf_fbx_limits limits{memory_limit, allocation_limit};
        FbxScene scene;
        scene.data = data;
        char err[512] = {0};
        const uint8_t* bytes = data.size() ? reinterpret_cast<const uint8_t*>(data.c_str()) : &empty;
        if (!msf_fbx_open(bytes, data.size(), &limits, &scene.h, err, sizeof err)) {
            scene.h = nullptr;
            return nb::make_tuple(nb::none(), nb::bytes(err, std::strlen(err)));
        }
        return nb::make_tuple(nb::cast(std::move(scene)), nb::bytes("", 0));
    }, nb::arg("data"), nb::arg("memory_limit") = 0, nb::arg("allocation_limit") = 0);
    m.def("_fbx_fail_call", [](const std::string& name) { msf::fbx::failing_call() = name; });
    m.def("_fbx_shim_abi", [] { return msf_fbx_shim_abi(); });
    m.def("_fbx_ufbx_version", [] { return msf_fbx_ufbx_version(); });
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
