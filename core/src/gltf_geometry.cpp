// SPDX-License-Identifier: MIT
// geometry.evaluate_geometry: overrides, world transforms, morph targets and
// linear blend skinning, in the reference's order and arithmetic.
#include <algorithm>
#include <cmath>
#include <map>
#include <set>

#include "gltf_detail.hpp"
#include "msf/authoring.hpp"
#include "msf/math3d.hpp"

namespace msf::gltf {

using namespace detail;
namespace m3 = msf::math3d;

namespace {

constexpr long long kMaxEvaluationComponents = kMaxTotalAccessorComponents;

// One node's overrides, as the reference's dict: key -> value, in insertion order.
using NodeOverride = std::vector<std::pair<std::string, m3::Vec>>;

const m3::Vec* find(const NodeOverride& o, const std::string& key) {
    for (const auto& [k, v] : o)
        if (k == key) return &v;
    return nullptr;
}
void set(NodeOverride& o, const std::string& key, m3::Vec value) {
    for (auto& [k, v] : o)
        if (k == key) {
            v = std::move(value);
            return;
        }
    o.emplace_back(key, std::move(value));
}

m3::Vec numbers(const Value& list) {
    m3::Vec out;
    for (const Value& x : list.items) out.push_back(x.number);
    return out;
}

const char* type_name(const Value& v) {
    switch (v.kind) {
        case Kind::null: return "NoneType";
        case Kind::boolean: return "bool";
        case Kind::integer: return "int";
        default: return "float";
    }
}

// Python's `key in container` for a JSON value.
bool contains(const Value& container, const std::string& key) {
    switch (container.kind) {
        case Kind::object: return json::find(container, key) != nullptr;
        case Kind::array:
            return std::any_of(container.items.begin(), container.items.end(),
                               [&](const Value& x) { return x.kind == Kind::string && x.text == key; });
        case Kind::string: return container.text.find(key) != std::string::npos;
        default: throw TypeError{std::string("argument of type '") + type_name(container) + "' is not iterable"};
    }
}
bool extension_in(const Value& obj, const std::string& key) {
    const Value* extensions = get(obj, "extensions");
    return extensions && contains(*extensions, key);
}

m3::Mat column_major(const m3::Vec& v) {
    m3::Mat out{};
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) out[r][c] = v[static_cast<std::size_t>(c * 4 + r)];
    return out;
}

BigInt evaluation_components(const Value& doc) {
    const Value* accessors = get(doc, "accessors");
    const Value* meshes = get(doc, "meshes");
    std::vector<BigInt> per_mesh, per_skinned_mesh;
    for (std::size_t mi = 0; mi < size_of(meshes); ++mi) {
        BigInt components = 0, influences = 0;
        for (const Value& primitive : item(meshes->items[mi], "primitives").items) {
            const Value& attrs = item(primitive, "attributes");
            const Value* position = get(attrs, "POSITION");
            if (!is_int(position) || big(*position) < BigInt(0) || big(*position) >= BigInt(static_cast<long long>(size_of(accessors)))) continue;
            BigInt count = big(item(accessors->items[static_cast<std::size_t>(big(*position).to_int64())], "count"));
            long long targets = 0;
            if (const Value* list = get(primitive, "targets"))
                for (const Value& target : list->items) targets += has(target, "POSITION");
            components = components + BigInt(3) * count * BigInt(1 + targets);
            long long sets = 0;
            for (const auto& member : attrs.members) sets += member.first.compare(0, 7, "JOINTS_") == 0;
            influences = influences + BigInt(8) * count * BigInt(sets);
        }
        per_mesh.push_back(components);
        per_skinned_mesh.push_back(components + influences);
    }
    const Value* nodes = get(doc, "nodes");
    const Value* skins = get(doc, "skins");
    BigInt total = 0;
    std::set<std::string> used_skins;
    for (std::size_t i = 0; i < size_of(nodes); ++i) {
        const Value& node = nodes->items[i];
        const Value* mesh = get(node, "mesh");
        if (!mesh) continue;
        std::size_t m = static_cast<std::size_t>(big(*mesh).to_int64());
        total = total + (has(node, "skin") ? per_skinned_mesh[m] : per_mesh[m]);
        if (const Value* skin = get(node, "skin")) used_skins.insert(skin->text);
    }
    for (const std::string& digits : used_skins) {
        BigInt i = BigInt::from_digits(digits);
        if (i >= BigInt(0) && i < BigInt(static_cast<long long>(size_of(skins))))
            total = total + BigInt(16 * static_cast<long long>(item(skins->items[static_cast<std::size_t>(i.to_int64())], "joints").items.size()));
    }
    return total;
}

std::map<std::size_t, m3::Mat> worlds(const Value& doc, const std::map<std::size_t, NodeOverride>& overrides) {
    const Value* nodes = get(doc, "nodes");
    std::map<std::size_t, std::size_t> parents;
    for (std::size_t i = 0; i < size_of(nodes); ++i)
        if (const Value* children = get(nodes->items[i], "children"))
            for (const Value& child : children->items) parents[static_cast<std::size_t>(big(child).to_int64())] = i;
    std::vector<m3::Mat> locals;
    static const NodeOverride none;
    for (std::size_t i = 0; i < size_of(nodes); ++i) {
        const Value& node = nodes->items[i];
        auto found = overrides.find(i);
        const NodeOverride& o = found == overrides.end() ? none : found->second;
        auto value = [&](const char* key, m3::Vec fallback) {
            if (const m3::Vec* v = find(o, key)) return *v;
            if (const Value* v = get(node, key)) return numbers(*v);
            return fallback;
        };
        std::string ref = "/nodes/" + std::to_string(i);
        if (find(o, "matrix") || has(node, "matrix")) {
            m3::Mat local = column_major(value("matrix", {}));
            m3::check_affine(local, 1e-12, ref);
            m3::check_trs(local, 1e-9, ref);
            locals.push_back(local);
        } else {
            m3::Vec rotation = value("rotation", {0, 0, 0, 1});
            m3::check_authored_quaternion(rotation, ref + "/rotation");
            locals.push_back(m3::trs(value("translation", {0, 0, 0}), rotation, value("scale", {1, 1, 1})));
        }
    }
    std::map<std::size_t, m3::Mat> out;
    for (std::size_t i = 0; i < size_of(nodes); ++i) {
        std::vector<std::size_t> chain;
        std::size_t j = i;
        while (!out.count(j)) {
            chain.push_back(j);
            auto parent = parents.find(j);
            if (parent == parents.end()) break;
            j = parent->second;
        }
        for (auto it = chain.rbegin(); it != chain.rend(); ++it) {
            auto parent = parents.find(*it);
            out[*it] = parent != parents.end() ? m3::multiply(out[parent->second], locals[*it]) : locals[*it];
        }
    }
    return out;
}

// geometry._accessor
Rows geometry_accessor(const Asset& asset, const Value& aid, const char* shape, std::initializer_list<long long> components,
                       const BigInt* count, int normalized, const std::string& ref) {
    const Value* accessors = get(asset.doc, "accessors");
    const Value& a = accessors->items[index(&aid, size_of(accessors), ref)];
    long long ct = big(item(a, "componentType")).to_int64();
    bool ct_ok = std::find(components.begin(), components.end(), ct) != components.end();
    if (item(a, "type").text != shape || !ct_ok || (count && big(item(a, "count")) != *count) ||
        (normalized >= 0 && is_true(get(a, "normalized")) != (normalized == 1)))
        fail(Code::E_GEOMETRY_TYPE, ref, "Geometry accessor has incompatible binary type, shape, count or normalization.");
    return decode_accessor(asset, aid, "/accessors/" + aid.text);
}

// math3d's linear blend: per vertex, each nonzero weight's palette (built on
// first use as mesh_inverse * worlds[skin_joints[j]] * ibms[j]) transforms
// the point, then each component sums weight * point over the influences.
std::vector<std::array<double, 3>> skin(const std::vector<std::array<double, 3>>& positions, const std::vector<std::vector<double>>& joints,
                                        const std::vector<std::vector<double>>& weights, const m3::Mat& mesh_inverse,
                                        const std::map<std::size_t, m3::Mat>& worlds, const Value& skin_joints,
                                        const std::vector<m3::Mat>& ibms, const std::string& ref) {
    std::vector<std::pair<long long, m3::Mat>> palettes;
    std::vector<std::array<double, 3>> out;
    out.reserve(positions.size());
    for (std::size_t v = 0; v < positions.size(); ++v) {
        std::vector<std::pair<double, std::array<double, 3>>> contributions;
        for (std::size_t k = 0; k < std::min(joints[v].size(), weights[v].size()); ++k) {
            double w = weights[v][k];
            if (w == 0) continue;
            long long j = static_cast<long long>(joints[v][k]);
            const m3::Mat* palette = nullptr;
            for (const auto& entry : palettes)
                if (entry.first == j) palette = &entry.second;
            if (!palette) {
                std::size_t node = static_cast<std::size_t>(big(skin_joints.items[static_cast<std::size_t>(j)]).to_int64());
                m3::Mat first = m3::multiply(mesh_inverse, worlds.at(node));
                palettes.emplace_back(j, m3::multiply(first, ibms[static_cast<std::size_t>(j)]));
                palette = &palettes.back().second;
            }
            m3::check_affine(*palette, 1e-7, "/transforms");
            contributions.emplace_back(w, m3::transform(*palette, positions[v].data()));
        }
        std::array<double, 3> point{};
        for (int c = 0; c < 3; ++c) {
            double total = 0.0;
            for (const auto& [w, q] : contributions) total = m3::add(total, m3::product(w, q[static_cast<std::size_t>(c)], ref), ref);
            point[static_cast<std::size_t>(c)] = total;
        }
        out.push_back(point);
    }
    return out;
}

}  // namespace

Geometry evaluate_geometry(const Asset& asset, const Time& ts, const Value* animation_id, const Overrides& morph_weights,
                           const Overrides& node_transforms) {
    const Value& doc = asset.doc;
    BigInt components = evaluation_components(doc);
    long long budget = asset.generated ? asset.caps.total : kMaxEvaluationComponents;
    if (components > BigInt(budget))
        fail(Code::E_RESOURCE_LIMIT, "/nodes",
             "Mesh instances need " + components.to_string() + " position and morph-target components; the budget is " +
                 std::to_string(budget) + ".",
             "Reduce mesh instances or vertices, or evaluate a smaller asset.");
    if (animation_id && animation_id->kind != Kind::integer)
        fail(Code::E_ANIMATION_REFERENCE, "/animation_id", "Select one explicit integer clip index.");
    std::map<std::size_t, NodeOverride> overrides;
    if (animation_id)
        for (auto& [node, paths] : sample_animation(asset, *animation_id, ts))
            for (auto& [path, value] : paths) set(overrides[node], path, std::move(value));
    const Value* nodes = get(doc, "nodes");
    const Value* meshes = get(doc, "meshes");
    for (const auto& [label, supplied] : {std::pair<std::string, const Overrides*>{"morph_weights", &morph_weights},
                                          std::pair<std::string, const Overrides*>{"node_transforms", &node_transforms}}) {
        if (!supplied->present) continue;
        if (!supplied->mapping) fail(Code::E_GEOMETRY_TYPE, "/" + label, "Overrides must map integer node indices to values.");
        for (const auto& [ni, value] : supplied->items) {
            std::size_t n = index(&ni, size_of(nodes), "/" + label);
            const Value& node = nodes->items[n];
            NodeOverride item_override;
            if (label == "morph_weights") {
                if (!has(node, "mesh")) fail(Code::E_MORPH, "/morph_weights", "Morph override needs a mesh node.");
                std::size_t count = morph_count(meshes->items[static_cast<std::size_t>(big(item(node, "mesh")).to_int64())]);
                vector(&value, count, "/morph_weights");
                item_override.emplace_back("weights", numbers(value));
            } else {
                authoring::keys(value, {}, {"matrix", "translation", "rotation", "scale"}, "/node_transforms");
                bool matrix = has(value, "matrix");
                bool node_trs = has(node, "translation") || has(node, "rotation") || has(node, "scale");
                if ((matrix && value.members.size() != 1) || (has(node, "matrix") && !matrix) || (matrix && node_trs))
                    fail(Code::E_NODE_TRANSFORM, "/node_transforms", "Matrix/TRS overrides must use the authored transform representation.");
                for (const auto& [field, count] : {std::pair{"matrix", 16}, std::pair{"translation", 3}, std::pair{"rotation", 4}, std::pair{"scale", 3}})
                    if (const Value* v = get(value, field)) vector(v, static_cast<std::size_t>(count), std::string("/node_transforms/") + field);
                for (const auto& [key, v] : value.members) item_override.emplace_back(key, numbers(v));
            }
            static const NodeOverride none;
            auto existing = overrides.find(n);
            const NodeOverride& current = existing == overrides.end() ? none : existing->second;
            bool shared = std::any_of(item_override.begin(), item_override.end(), [&](const auto& e) { return find(current, e.first) != nullptr; });
            bool matrix_conflict = find(item_override, "matrix") &&
                                   std::any_of(current.begin(), current.end(), [](const auto& e) { return e.first != "weights"; });
            if (shared || matrix_conflict)
                fail(Code::E_MULTIPLE_WRITERS, "/nodes/" + ni.text, "Animation and explicit overrides drive the same property.");
            NodeOverride& target = overrides[n];
            for (auto& [key, v] : item_override) set(target, key, std::move(v));
        }
    }
    std::map<std::size_t, m3::Mat> world = worlds(doc, overrides);
    Geometry out;
    std::map<std::string, std::pair<std::vector<m3::Mat>, bool>> skin_matrices;
    const Value* accessors = get(doc, "accessors");
    const Value* views = get(doc, "bufferViews");
    for (std::size_t ni = 0; ni < size_of(nodes); ++ni) {
        const Value& node = nodes->items[ni];
        const Value* mesh_id = get(node, "mesh");
        if (!mesh_id) continue;
        const Value& mesh = meshes->items[static_cast<std::size_t>(big(*mesh_id).to_int64())];
        Instance instance{ni, static_cast<std::size_t>(big(*mesh_id).to_int64()), {}};
        const Value& primitives = item(mesh, "primitives");
        for (std::size_t pi = 0; pi < primitives.items.size(); ++pi) {
            const Value& primitive = primitives.items[pi];
            std::string ref = "/nodes/" + std::to_string(ni) + "/meshes/" + mesh_id->text + "/primitives/" + std::to_string(pi);
            try {
                const Value& attrs = item(primitive, "attributes");
                if (!has(attrs, "POSITION")) fail(Code::E_GEOMETRY_CAPABILITY, ref, "Primitive has no supported POSITION accessor.");
                if (extension_in(primitive, "KHR_draco_mesh_compression"))
                    fail(Code::E_GEOMETRY_CAPABILITY, ref, "Compressed geometry requires an unsupported decoder.");
                for (std::size_t v = 0; v < size_of(views); ++v)
                    if (extension_in(views->items[v], "EXT_meshopt_compression"))
                        fail(Code::E_GEOMETRY_CAPABILITY, ref, "Compressed bufferViews require an unsupported decoder.");
                Rows basis = geometry_accessor(asset, item(attrs, "POSITION"), "VEC3", {5126}, nullptr, 0, ref);
                std::size_t count = basis.count;
                if (const Value* ix = get(primitive, "indices")) {
                    Rows indices = decode_accessor(asset, *ix, "/accessors/" + ix->text);
                    for (std::size_t r = 0; r < indices.count; ++r)
                        if (indices.at(r, 0) >= static_cast<double>(count)) fail(Code::E_INDEX_BOUNDS, ref, "Primitive index exceeds vertex count.");
                }
                std::vector<double> weights;
                auto found = overrides.find(ni);
                const m3::Vec* override_weights = found == overrides.end() ? nullptr : find(found->second, "weights");
                if (override_weights) weights = *override_weights;
                else if (const Value* w = get(node, "weights")) weights = numbers(*w);
                else if (const Value* w = get(mesh, "weights")) weights = numbers(*w);
                else weights.assign(morph_count(mesh), 0.0);
                std::vector<std::array<double, 3>> positions(count);
                for (std::size_t v = 0; v < count; ++v)
                    for (std::size_t k = 0; k < 3; ++k) positions[v][k] = basis.at(v, k);
                const Value* targets = get(primitive, "targets");
                BigInt big_count(static_cast<long long>(count));
                for (std::size_t t = 0; t < std::min(weights.size(), size_of(targets)); ++t) {
                    const Value* delta_id = get(targets->items[t], "POSITION");
                    if (!delta_id) continue;
                    Rows deltas = geometry_accessor(asset, *delta_id, "VEC3", {5126}, &big_count, 0, ref);
                    for (std::size_t v = 0; v < std::min(count, deltas.count); ++v)
                        for (std::size_t k = 0; k < 3; ++k)
                            positions[v][k] = m3::add(positions[v][k], m3::product(weights[t], deltas.at(v, k), ref), ref);
                }
                if (const Value* skin_id = get(node, "skin")) {
                    if (!has(attrs, "JOINTS_0") || !has(attrs, "WEIGHTS_0")) fail(Code::E_SKIN, ref, "Skinned primitive needs JOINTS_0 and WEIGHTS_0.");
                    std::size_t sets = 0;
                    for (const auto& member : attrs.members) sets += member.first.compare(0, 7, "JOINTS_") == 0;
                    for (std::size_t s = 0; s < sets; ++s)
                        if (!has(attrs, "JOINTS_" + std::to_string(s)) || !has(attrs, "WEIGHTS_" + std::to_string(s)))
                            fail(Code::E_SKIN, ref, "Influence sets must be paired and numbered from 0.");
                    const Value& skin_value = item(doc, "skins").items[static_cast<std::size_t>(big(*skin_id).to_int64())];
                    const Value& skin_joints = item(skin_value, "joints");
                    std::vector<std::vector<double>> joints(count), skin_weights(count);
                    for (std::size_t s = 0; s < sets; ++s) {
                        Rows set_joints = geometry_accessor(asset, item(attrs, "JOINTS_" + std::to_string(s)), "VEC4", {5121, 5123}, &big_count, 0, ref);
                        const Value& weights_id = item(attrs, "WEIGHTS_" + std::to_string(s));
                        bool normalized = !numeric_equals(get(accessors->items[static_cast<std::size_t>(big(weights_id).to_int64())], "componentType"), 5126);
                        Rows set_weights = geometry_accessor(asset, weights_id, "VEC4", {5121, 5123, 5126}, &big_count, normalized ? 1 : 0, ref);
                        for (std::size_t v = 0; v < count; ++v)
                            for (std::size_t k = 0; k < 4; ++k) {
                                joints[v].push_back(set_joints.at(v, k));
                                skin_weights[v].push_back(set_weights.at(v, k));
                            }
                    }
                    auto cached = skin_matrices.find(skin_id->text);
                    if (cached == skin_matrices.end()) {
                        std::vector<m3::Mat> ibms;
                        if (const Value* ibm = get(skin_value, "inverseBindMatrices")) {
                            Rows rows = decode_accessor(asset, *ibm, "/accessors/" + ibm->text);
                            for (std::size_t r = 0; r < rows.count; ++r)
                                ibms.push_back(column_major(m3::Vec(rows.values.begin() + static_cast<std::ptrdiff_t>(r * 16),
                                                                    rows.values.begin() + static_cast<std::ptrdiff_t>((r + 1) * 16))));
                        } else {
                            ibms.assign(skin_joints.items.size(), m3::kIdentity);
                        }
                        bool affine = std::all_of(ibms.begin(), ibms.end(), [](const m3::Mat& m) { return m[3] == m3::kIdentity[3]; });
                        cached = skin_matrices.emplace(skin_id->text, std::make_pair(std::move(ibms), affine)).first;
                    }
                    if (!cached->second.second) fail(Code::E_SKIN_TYPE, ref, "Inverse bind matrices must be affine.");
                    m3::Mat mesh_inverse = m3::inverse(world.at(ni));
                    double palette = static_cast<double>(skin_joints.items.size());
                    for (std::size_t v = 0; v < count; ++v) {
                        for (double j : joints[v])
                            if (j >= palette) fail(Code::E_JOINT_BOUNDS, ref, "Joint index exceeds skin palette; unknown weighted joints are never deleted.");
                        bool negative = std::any_of(skin_weights[v].begin(), skin_weights[v].end(), [](double w) { return w < 0; });
                        bool bad = negative;
                        if (!negative) {
                            double total = 0.0;
                            for (double w : skin_weights[v]) total = m3::add(total, w, ref);
                            bad = std::fabs(m3::sub(total, 1.0, ref)) > 1e-6;
                        }
                        if (bad)
                            fail(Code::E_SKIN_WEIGHTS, ref,
                                 std::string(sets == 1 ? "Four" : "All") + " skin weights must be nonnegative and sum to one; no implicit normalization.");
                    }
                    positions = skin(positions, joints, skin_weights, mesh_inverse, world, skin_joints, cached->second.first, ref);
                }
                for (const auto& p : positions)
                    for (double x : p)
                        if (!std::isfinite(x)) fail(Code::E_NONFINITE, ref, "Geometry result overflows binary64.");
                instance.primitives.push_back({pi, std::move(positions)});
            } catch (const Fault& fault) {
                out.diagnostics.push_back(fault.diagnostic());
            }
        }
        out.instances.push_back(std::move(instance));
    }
    if (out.instances.empty()) fail(Code::E_GEOMETRY_EMPTY, "/nodes", "Asset has no mesh instances.");
    return out;
}

}  // namespace msf::gltf
