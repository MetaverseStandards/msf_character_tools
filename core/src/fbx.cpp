// SPDX-License-Identifier: MIT
// ufbx loads the file from memory already in metres and right-handed +Y up,
// applies geometric transforms to the points, compensates inherit modes and
// moves pivots into the node matrices (adding helper nodes where it must).
// Static and animated node TRS both come from ufbx's node-to-parent matrices.
#include "msf/fbx.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <map>
#include <memory>
#include <set>
#include <tuple>

#include "msf/json.hpp"
#include "msf/math3d.hpp"
#include "msf/paths.hpp"
#include "msf/pyerror.hpp"
#include "msf/sources.hpp"
#include "msf_ufbx_shim.h"

namespace msf::fbx {

namespace src = msf::sources;

std::string decode_replace(std::string_view s) {
    static const char* replacement = "\xEF\xBF\xBD";
    std::string out;
    std::size_t i = 0, n = s.size();
    auto byte = [&](std::size_t k) { return static_cast<unsigned char>(s[k]); };
    while (i < n) {
        unsigned char b = byte(i);
        if (b < 0x80) {
            out += static_cast<char>(b);
            ++i;
            continue;
        }
        std::size_t need;
        unsigned char lo = 0x80, hi = 0xBF;
        if (b >= 0xC2 && b <= 0xDF) need = 1;
        else if (b == 0xE0) { need = 2; lo = 0xA0; }
        else if (b >= 0xE1 && b <= 0xEC) need = 2;
        else if (b == 0xED) { need = 2; hi = 0x9F; }
        else if (b >= 0xEE && b <= 0xEF) need = 2;
        else if (b == 0xF0) { need = 3; lo = 0x90; }
        else if (b >= 0xF1 && b <= 0xF3) need = 3;
        else if (b == 0xF4) { need = 3; hi = 0x8F; }
        else {
            out += replacement;
            ++i;
            continue;
        }
        std::size_t k = 1;
        bool ok = true;
        for (; k <= need; ++k) {
            unsigned char lower = k == 1 ? lo : 0x80, upper = k == 1 ? hi : 0xBF;
            if (i + k >= n || byte(i + k) < lower || byte(i + k) > upper) {
                ok = false;
                break;
            }
        }
        if (ok) {
            out.append(s.substr(i, need + 1));
            i += need + 1;
        } else {
            // The maximal valid prefix is replaced as one character.
            out += replacement;
            i += k;
        }
    }
    return out;
}

std::string ufbx_version() {
    uint32_t packed = msf_fbx_ufbx_version();
    return std::to_string(packed / 1000000) + "." + std::to_string(packed / 1000 % 1000) + "." + std::to_string(packed % 1000);
}

std::string& failing_call() {
    static std::string name;
    return name;
}

namespace {

constexpr long long kMaxSamples = 100000;

// A shim call's result, or 0 when a test has made that call fail.
int ok(const char* name, int result) { return failing_call() == name ? 0 : result; }
const char* const kNoAction = "No action needed.";

// The first n code points of UTF-8 text.
std::string prefix(const std::string& text, std::size_t n) {
    std::size_t count = 0, i = 0;
    while (i < text.size() && count < n) {
        unsigned char b = static_cast<unsigned char>(text[i]);
        i += b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
        ++count;
    }
    return text.substr(0, std::min(i, text.size()));
}

// str.strip() on UTF-8 text: Python's whitespace characters.
std::string strip(const std::string& text) {
    static const char* const spaces[] = {"\t", "\n", "\v", "\f", "\r", "\x1c", "\x1d", "\x1e", "\x1f", " ", "\xC2\x85", "\xC2\xA0",
                                         "\xE1\x9A\x80", "\xE2\x80\x80", "\xE2\x80\x81", "\xE2\x80\x82", "\xE2\x80\x83", "\xE2\x80\x84",
                                         "\xE2\x80\x85", "\xE2\x80\x86", "\xE2\x80\x87", "\xE2\x80\x88", "\xE2\x80\x89", "\xE2\x80\x8A",
                                         "\xE2\x80\xA8", "\xE2\x80\xA9", "\xE2\x80\xAF", "\xE2\x81\x9F", "\xE3\x80\x80"};
    std::size_t begin = 0, end = text.size();
    bool moved = true;
    while (moved && begin < end) {
        moved = false;
        for (const char* sp : spaces) {
            std::size_t len = std::char_traits<char>::length(sp);
            if (end - begin >= len && text.compare(begin, len, sp) == 0) {
                begin += len;
                moved = true;
                break;
            }
        }
    }
    moved = true;
    while (moved && begin < end) {
        moved = false;
        for (const char* sp : spaces) {
            std::size_t len = std::char_traits<char>::length(sp);
            if (end - begin >= len && text.compare(end - len, len, sp) == 0) {
                end -= len;
                moved = true;
                break;
            }
        }
    }
    return text.substr(begin, end - begin);
}

std::string lower_ascii(std::string s) {
    for (char& c : s)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return s;
}

std::string format_g(double x) {
    char buffer[64];
    std::snprintf(buffer, sizeof buffer, "%g", x);
    return buffer;
}

double binary32(double x) {
    float f;
    if (!json::to_float32(x, f)) throw PyError{PyError::Type::overflow, "float too large to pack with f format"};
    return f;
}

double fsum(const std::vector<double>& values) {
    math3d::FsumOutcome r = math3d::fsum(values.data(), values.size());
    if (r.status == math3d::FsumOutcome::Status::overflow) throw PyError{PyError::Type::overflow, "intermediate overflow in fsum"};
    if (r.status == math3d::FsumOutcome::Status::inf_minus_inf) throw PyError{PyError::Type::value, "-inf + inf in fsum"};
    return r.value;
}

bool near(const std::vector<double>& row, const std::vector<double>& rest) {
    for (std::size_t i = 0; i < std::min(row.size(), rest.size()); ++i) {
        double y = rest[i];
        double bound = std::fabs(y) > 1.0 ? std::fabs(y) : 1.0;
        if (!(std::fabs(row[i] - y) <= 1e-6 * bound)) return false;
    }
    return true;
}

[[noreturn]] void shear(const std::string& path) {
    fail(Code::E_SHEAR_UNSUPPORTED, path, "Transform has shear, which glTF TRS cannot represent.",
         "Remove the shear, or keep it only on static unskinned leaf meshes, where it is baked into the points.");
}

struct Trs {
    std::vector<double> translation, rotation, scale;
    const std::vector<double>& field(int f) const { return f == 0 ? translation : f == 1 ? rotation : scale; }
};

Trs trs_of(const src::Matrix& matrix, const std::string& path) {
    for (double x : matrix)
        if (!std::isfinite(x)) fail(Code::E_SOURCE_VALUE, path, "Transform has a non-finite number.");
    src::Trs t;
    try {
        t = src::decompose(matrix);
    } catch (const src::Singular&) {
        fail(Code::E_SOURCE_VALUE, path, "Transform is singular.");
    } catch (const PyError& e) {
        if (e.type != PyError::Type::value) throw;
        fail(Code::E_SOURCE_VALUE, path, "Transform is singular.");
    }
    return {{t.translation.begin(), t.translation.end()}, {t.rotation.begin(), t.rotation.end()}, {t.scale.begin(), t.scale.end()}};
}

std::vector<double> apply_matrix(const src::Matrix& m, const std::vector<double>& p) {
    std::vector<double> out;
    for (int r = 0; r < 3; ++r) {
        std::vector<double> terms;
        for (int c = 0; c < 3; ++c) terms.push_back(m[static_cast<std::size_t>(4 * c + r)] * p[static_cast<std::size_t>(c)]);
        out.push_back(fsum(terms) + m[static_cast<std::size_t>(12 + r)]);
    }
    return out;
}

std::vector<std::vector<double>> quaternions(const std::vector<std::vector<double>>& rows) {
    std::vector<std::vector<double>> out{rows[0]};
    for (std::size_t i = 1; i < rows.size(); ++i) {
        std::vector<double> products;
        for (std::size_t k = 0; k < 4; ++k) products.push_back(out.back()[k] * rows[i][k]);
        if (fsum(products) >= 0) {
            out.push_back(rows[i]);
        } else {
            std::vector<double> negated;
            for (double x : rows[i]) negated.push_back(-x);
            out.push_back(negated);
        }
    }
    return out;
}

struct NodeInfo {
    int32_t parent;
    std::string name;
    int32_t mesh;
    int helper;
    int pivots;
    src::Matrix to_parent;
    std::optional<std::string> skipped;
};

struct Frame {
    double target;
    std::vector<std::pair<uint32_t, std::array<double, 3>>> offsets;
};

struct BlendChannel {
    uint32_t deformer;
    std::string deformer_name, channel_name;
    std::vector<Frame> frames;
    double weight;
};

struct Handle {
    msf_fbx* h = nullptr;
    ~Handle() {
        if (h) msf_fbx_close(h);
    }
};

class Scene {
public:
    Scene(msf_fbx* h, const Options& options, const Limits& limits) : h_(h), options_(options), limits_(limits) {
        msf_fbx_info_get(h, &info_);
        for (uint32_t i = 0; i < info_.nodes; ++i) {
            msf_fbx_node node;
            if (!ok("msf_fbx_node_get", msf_fbx_node_get(h, i, &node))) fail(Code::E_SOURCE_VALUE, "/", "The FBX reader could not report a node.");
            NodeInfo n{node.parent, decode_replace(std::string_view(node.name, node.name_len)), node.mesh, node.helper, node.pivots, {}, std::nullopt};
            for (int k = 0; k < 16; ++k) n.to_parent[static_cast<std::size_t>(k)] = node.to_parent[k];
            if (node.skipped) n.skipped = std::string(node.skipped);
            nodes_.push_back(std::move(n));
        }
        skipped_ = {{"empty mesh", 0}, {"hole face", 0}, {"point or line face", 0}};
        uint32_t sizes[8];
        for (uint32_t m = 0; m < info_.meshes; ++m)
            if (ok("msf_fbx_mesh_sizes", msf_fbx_mesh_sizes(h, m, sizes)) && sizes[0] == 0) empty_.insert(static_cast<int32_t>(m));
        skipped_[0].second = static_cast<long long>(empty_.size());
    }

    Generated convert(const std::string& generator) {
        std::vector<Diagnostic> conversion;
        if (info_.unit_meters > 0 && info_.unit_meters != 1.0)  // ufbx leaves a nonpositive unit unconverted
            conversion.push_back({Code::I_UNITS_CONVERTED, "/", "Converted " + format_g(info_.unit_meters) + " metres per unit to metres.", kNoAction});
        if (info_.axes_converted)
            conversion.push_back({Code::I_AXES_CONVERTED, "/", "Converted the file's axes to right-handed +Y up.", kNoAction});
        if (std::any_of(nodes_.begin(), nodes_.end(), [](const NodeInfo& n) { return n.pivots != 0; }))
            conversion.push_back({Code::I_PIVOTS_BAKED, "/", "Pivots, offsets and pre/post rotations are baked into node TRS.", kNoAction});
        if (info_.helper_nodes)
            conversion.push_back(src::warning(Code::W_HELPER_NODES, "/",
                                              "The reader added " + src::count(info_.helper_nodes, "helper node", "helper nodes") +
                                                  " for geometric transforms or inherited scale it could not fold into the nodes."));
        std::vector<std::string> node_paths = paths();
        std::vector<paths::NodePath> parsed;
        for (const std::string& p : node_paths) parsed.push_back(paths::parse_node_path(p));
        std::vector<std::size_t> order(nodes_.size());
        for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
        std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) { return paths::compare(parsed[a], parsed[b]) < 0; });
        std::vector<long long> index(nodes_.size());
        for (std::size_t k = 0; k < order.size(); ++k) index[order[k]] = static_cast<long long>(k);
        std::vector<std::vector<long long>> children(order.size());
        for (std::size_t shim = 0; shim < nodes_.size(); ++shim)
            if (nodes_[shim].parent >= 0) children[static_cast<std::size_t>(index[static_cast<std::size_t>(nodes_[shim].parent)])].push_back(index[shim]);
        std::vector<src::Animation> animation;
        std::vector<Diagnostic> time_losses;
        std::set<std::size_t> animated;
        this->animation(order, node_paths, animation, time_losses, animated);
        std::vector<src::Mesh> meshes;
        std::map<std::size_t, std::pair<long long, std::optional<long long>>> mesh_of_shim;
        std::vector<src::Skin> skins;
        std::vector<std::vector<std::string>> target_keys;
        this->meshes(order, node_paths, index, animated, meshes, mesh_of_shim, skins, target_keys);
        std::vector<src::Node> nodes;
        for (std::size_t k = 0; k < order.size(); ++k) {
            std::size_t shim = order[k];
            const NodeInfo& node = nodes_[shim];
            const std::string& path = node_paths[shim];
            const src::Matrix& matrix = node.to_parent;
            src::Node out;
            if (src::has_shear(matrix)) {
                if (!baked_.count(shim)) shear(path);
            } else {
                Trs t = trs_of(matrix, path);
                out.translation = t.translation;
                out.rotation = t.rotation;
                out.scale = t.scale;
                if (src::determinant(matrix) < 0)
                    losses_.push_back({Code::I_MIRRORED, path, "Mirrored transform stored as a negative X scale.", kNoAction});
            }
            auto found = mesh_of_shim.find(shim);
            if (found != mesh_of_shim.end()) {
                out.mesh = found->second.first;
                out.skin = found->second.second;
                const src::Mesh& mesh = meshes[static_cast<std::size_t>(found->second.first)];
                if (std::any_of(mesh.weights.begin(), mesh.weights.end(), [](double w) { return w != 0; })) out.weights = mesh.weights;
            }
            if (!node.helper) out.name = node.name;
            out.children = children[k];
            nodes.push_back(std::move(out));
        }
        std::vector<std::pair<std::string, long long>> kinds;
        auto add = [&](const std::string& kind, long long n, bool update) {
            for (auto& entry : kinds)
                if (entry.first == kind) {
                    entry.second = update ? n : entry.second + n;
                    return;
                }
            kinds.emplace_back(kind, n);
        };
        for (const NodeInfo& node : nodes_)
            if (node.skipped) add(*node.skipped, 1, false);
        add("material", info_.materials, true);
        add("texture", info_.textures, true);
        for (const auto& [kind, n] : skipped_) add(kind, n, true);
        std::vector<std::string> parts;
        for (const auto& [kind, n] : kinds) {
            if (!n) continue;
            char last = kind.empty() ? '\0' : kind.back();
            parts.push_back(std::to_string(n) + " " + kind + (n == 1 ? "" : (last == 'h' || last == 'x') ? "es" : "s"));
        }
        if (!parts.empty()) {
            std::string text = parts[0];
            if (parts.size() > 1) {
                text = parts[0];
                for (std::size_t i = 1; i + 1 < parts.size(); ++i) text += ", " + parts[i];
                text += " and " + parts.back();
            }
            losses_.push_back(src::warning(Code::W_SKIPPED, "/", "Skipped " + text + "."));
        }
        Generated out;
        try {
            out.glb = src::write_glb(nodes, meshes, skins, animation, generator);
        } catch (const src::WriteError& e) {
            fail(Code::E_SOURCE_VALUE, "/", e.message);
        }
        for (std::size_t shim : order) out.node_paths.push_back(node_paths[shim]);
        out.target_keys = std::move(target_keys);
        out.losses = conversion;
        out.losses.insert(out.losses.end(), time_losses.begin(), time_losses.end());
        out.losses.insert(out.losses.end(), losses_.begin(), losses_.end());
        return out;
    }

private:
    msf_fbx* h_;
    const Options& options_;
    const Limits& limits_;
    msf_fbx_info info_{};
    std::vector<NodeInfo> nodes_;
    std::vector<std::pair<std::string, long long>> skipped_;
    std::set<int32_t> empty_;
    std::vector<Diagnostic> losses_;
    std::set<std::size_t> baked_;

    long long skipped_count(const std::string& kind) {
        for (auto& e : skipped_)
            if (e.first == kind) return e.second;
        return 0;
    }
    void add_skipped(const std::string& kind, long long n) {
        for (auto& e : skipped_)
            if (e.first == kind) e.second += n;
    }

    int32_t logical_parent(std::size_t i) const {
        int32_t parent = nodes_[i].parent;
        while (parent >= 0 && nodes_[static_cast<std::size_t>(parent)].helper) parent = nodes_[static_cast<std::size_t>(parent)].parent;
        return parent;
    }

    // Node paths per the path-sorted-v2 grammar: escaped names, [k] for duplicate siblings, helper suffixes.
    std::vector<std::string> paths() const {
        std::size_t n = nodes_.size();
        std::vector<int32_t> logical(n);
        for (std::size_t i = 0; i < n; ++i) logical[i] = logical_parent(i);
        std::vector<std::pair<std::pair<int32_t, std::string>, std::vector<std::size_t>>> groups;
        for (std::size_t i = 0; i < n; ++i) {
            if (nodes_[i].helper) continue;
            auto key = std::make_pair(logical[i], nodes_[i].name);
            auto found = std::find_if(groups.begin(), groups.end(), [&](const auto& g) { return g.first == key; });
            if (found == groups.end()) groups.push_back({key, {i}});
            else found->second.push_back(i);
        }
        std::vector<paths::Component> component(n);
        for (const auto& [key, members] : groups)
            for (std::size_t k = 0; k < members.size(); ++k)
                component[members[k]] = {nodes_[members[k]].name, members.size() > 1 ? std::optional<std::string>(std::to_string(k)) : std::nullopt};
        auto chain = [&](int32_t i) {
            std::vector<paths::Component> parts;
            while (i >= 0) {
                parts.push_back(component[static_cast<std::size_t>(i)]);
                i = logical[static_cast<std::size_t>(i)];
            }
            std::reverse(parts.begin(), parts.end());
            return parts;
        };
        static const char* kinds[] = {"", "geometry", "scale"};
        struct Helper {
            int32_t owner;
            std::string kind;
            long long k;
        };
        std::vector<std::optional<Helper>> helpers(n);
        std::vector<std::string> out(n);
        std::vector<std::pair<std::pair<int32_t, std::string>, long long>> counters;
        for (std::size_t i = 0; i < n; ++i) {
            if (nodes_[i].helper) {
                int32_t owner = logical_parent(i);  // a helper can sit under another helper of the same owner
                std::string kind = kinds[nodes_[i].helper];
                auto key = std::make_pair(owner, kind);
                auto found = std::find_if(counters.begin(), counters.end(), [&](const auto& c) { return c.first == key; });
                if (found == counters.end()) {
                    counters.push_back({key, 0});
                    found = counters.end() - 1;
                }
                helpers[i] = Helper{owner, kind, found->second};
                found->second += 1;
            } else {
                out[i] = paths::node_path(chain(static_cast<int32_t>(i)));
            }
        }
        // As the reference did, a helper counts only the same-owner, same-kind helpers not yet named.
        for (std::size_t i = 0; i < n; ++i) {
            if (!helpers[i]) continue;
            const Helper& value = *helpers[i];
            long long remaining = 0;
            for (std::size_t j = i; j < n; ++j)
                if (helpers[j] && helpers[j]->owner == value.owner && helpers[j]->kind == value.kind) ++remaining;
            bool many = remaining > 1;
            out[i] = paths::node_path(chain(value.owner),
                                      paths::Component{value.kind, many ? std::optional<std::string>(std::to_string(value.k)) : std::nullopt});
            helpers[i].reset();
        }
        return out;
    }

    void meshes(const std::vector<std::size_t>& order, const std::vector<std::string>& node_paths, const std::vector<long long>& index,
                const std::set<std::size_t>& animated, std::vector<src::Mesh>& meshes,
                std::map<std::size_t, std::pair<long long, std::optional<long long>>>& mesh_of_shim, std::vector<src::Skin>& skins,
                std::vector<std::vector<std::string>>& target_keys) {
        std::map<int32_t, std::pair<long long, std::optional<long long>>> mesh_index;
        for (std::size_t shim : order) {
            const NodeInfo& node = nodes_[shim];
            int32_t m = node.mesh;
            if (m < 0 || empty_.count(m)) continue;
            const std::string& path = node_paths[shim];
            if (!mesh_index.count(m)) {
                std::vector<std::string> keys;
                std::optional<src::Skin> skin;
                src::Mesh mesh = this->mesh(m, shim, path, index, keys, skin);
                if (src::has_shear(node.to_parent)) {
                    bool leaf = std::none_of(nodes_.begin(), nodes_.end(), [&](const NodeInfo& n) { return n.parent == static_cast<int32_t>(shim); });
                    if (!leaf || skin || animated.count(shim)) shear(path);
                    baked_.insert(shim);
                    src::Matrix linear = node.to_parent;
                    linear[12] = linear[13] = linear[14] = 0.0;
                    linear[15] = 1.0;
                    for (auto& p : mesh.points) p = apply_matrix(node.to_parent, p);
                    for (auto& t : mesh.targets)
                        for (auto& o : t) o = apply_matrix(linear, o);
                    losses_.push_back(src::warning(Code::W_SHEAR_BAKED, path, "Sheared transform baked into the mesh points."));
                }
                std::optional<long long> skin_index;
                if (skin) {
                    skin_index = static_cast<long long>(skins.size());
                    skins.push_back(*skin);
                }
                mesh_index[m] = {static_cast<long long>(meshes.size()), skin_index};
                meshes.push_back(std::move(mesh));
                target_keys.push_back(std::move(keys));
            } else if (src::has_shear(node.to_parent)) {
                shear(path);
            }
            mesh_of_shim[shim] = mesh_index[m];
        }
    }

    src::Mesh mesh(int32_t m, std::size_t shim, const std::string& path, const std::vector<long long>& index, std::vector<std::string>& keys,
                   std::optional<src::Skin>& skin) {
        uint32_t sizes[8];
        if (!ok("msf_fbx_mesh_sizes", msf_fbx_mesh_sizes(h_, static_cast<uint32_t>(m), sizes))) fail(Code::E_SOURCE_VALUE, path, "The FBX reader could not report a mesh.");
        uint32_t points = sizes[0], triangles = sizes[1];
        add_skipped("hole face", sizes[2]);
        add_skipped("point or line face", sizes[3]);
        if (sizes[7]) losses_.push_back(src::warning(Code::W_SUBDIV_CAGE, path, "Subdivision surface uses its control cage."));
        if (sizes[6])
            losses_.push_back(src::warning(Code::W_POINTS_ANIMATION_DROPPED, path,
                                           "Dropped the vertex cache animation; the mesh's own points are used."));
        std::vector<double> positions(3 * static_cast<std::size_t>(points) + (points ? 0 : 1));
        std::vector<uint32_t> tri(3 * static_cast<std::size_t>(triangles) + (triangles ? 0 : 1));
        if (!ok("msf_fbx_mesh_fill", msf_fbx_mesh_fill(h_, static_cast<uint32_t>(m), positions.data(), points, tri.data(), triangles)))
            fail(Code::E_SOURCE_VALUE, path, "The FBX reader could not fill a mesh.");
        src::Mesh mesh;
        for (uint32_t v = 0; v < points; ++v) mesh.points.push_back({positions[3 * v], positions[3 * v + 1], positions[3 * v + 2]});
        std::vector<double> weights;
        blend(m, sizes[5], points, path, keys, mesh.targets, weights);
        if (sizes[4] > 1) fail(Code::E_SOURCE_VALUE, path, "A mesh with more than one skin deformer is not supported.");
        if (sizes[4] == 1) {
            mesh.skinned = true;
            mesh.influences = this->skin(m, shim, points, path, index, skin);
        }
        for (std::size_t t = 0; t < 3 * static_cast<std::size_t>(triangles); ++t) mesh.triangles.push_back(tri[t]);
        if (!mesh.targets.empty()) mesh.weights = weights;
        return mesh;
    }

    std::vector<src::Influences> skin(int32_t m, std::size_t shim, uint32_t points, const std::string& path, const std::vector<long long>& index,
                                      std::optional<src::Skin>& skin) {
        uint32_t sizes[2];
        if (!ok("msf_fbx_skin_sizes", msf_fbx_skin_sizes(h_, static_cast<uint32_t>(m), 0, sizes))) fail(Code::E_SOURCE_VALUE, path, "The FBX reader could not report a skin.");
        uint32_t clusters = sizes[0], entries = sizes[1];
        std::vector<uint32_t> offsets(points + 1), which(entries ? entries : 1);
        std::vector<double> weights(entries ? entries : 1), binds(clusters ? 16 * static_cast<std::size_t>(clusters) : 1);
        std::vector<int32_t> bones(clusters ? clusters : 1);
        int method = 0;
        if (!ok("msf_fbx_skin_fill", msf_fbx_skin_fill(h_, static_cast<uint32_t>(m), 0, offsets.data(), points, which.data(), weights.data(), entries, bones.data(),
                               binds.data(), clusters, &method)))
            fail(Code::E_SOURCE_VALUE, path, "The FBX reader could not fill a skin.");
        std::map<int32_t, long long> slot_of_bone;
        std::vector<int32_t> joints;
        std::vector<std::vector<double>> matrices;
        std::vector<long long> slot_of_cluster;
        for (uint32_t c = 0; c < clusters; ++c) {
            int32_t bone = bones[c];
            if (bone < 0) fail(Code::E_SOURCE_VALUE, path, "A skin cluster has no bone node.");
            std::vector<double> matrix(binds.begin() + 16 * c, binds.begin() + 16 * (c + 1));
            auto found = slot_of_bone.find(bone);
            if (found != slot_of_bone.end()) {
                if (matrices[static_cast<std::size_t>(found->second)] != matrix)
                    fail(Code::E_SOURCE_VALUE, path, "Two skin clusters bind the same bone differently.");
            } else {
                slot_of_bone[bone] = static_cast<long long>(joints.size());
                joints.push_back(bone);
                matrices.push_back(matrix);
            }
            slot_of_cluster.push_back(slot_of_bone[bone]);
        }
        std::vector<src::Influences> merged_rows;
        for (uint32_t v = 0; v < points; ++v) {
            src::Influences pairs;
            for (uint32_t k = offsets[v]; k < offsets[v + 1]; ++k) {
                if (which[k] >= slot_of_cluster.size()) throw PyError{PyError::Type::index, "list index out of range"};
                pairs.emplace_back(slot_of_cluster[which[k]], weights[k]);
            }
            merged_rows.push_back(src::merge(pairs, path));
        }
        long long root = unweighted_slot(shim, slot_of_bone);
        src::Rows rows = src::influence_rows(merged_rows, root, options_.top4, path, "the nearest ancestor joint of the mesh, or the skeleton root");
        losses_.insert(losses_.end(), rows.losses.begin(), rows.losses.end());
        static const char* methods[] = {nullptr, "rigid", "dual quaternion", "blended dual quaternion and linear"};
        const char* name = method >= 0 && method <= 3 ? methods[method] : "unknown";
        if (name) losses_.push_back(src::method_loss(path, name));
        src::Skin out;
        for (int32_t b : joints) out.joints.push_back(index[static_cast<std::size_t>(b)]);
        out.inverse_bind_matrices = matrices;
        skin = out;
        return rows.rows;
    }

    long long unweighted_slot(std::size_t shim, const std::map<int32_t, long long>& slot_of_bone) const {
        int32_t parent = nodes_[shim].parent;
        while (parent >= 0) {
            auto found = slot_of_bone.find(parent);
            if (found != slot_of_bone.end()) return found->second;
            parent = nodes_[static_cast<std::size_t>(parent)].parent;
        }
        std::vector<std::pair<int32_t, long long>> by_slot(slot_of_bone.begin(), slot_of_bone.end());
        std::stable_sort(by_slot.begin(), by_slot.end(), [](const auto& a, const auto& b) { return a.second < b.second; });
        for (const auto& [bone, slot] : by_slot) {
            int32_t ancestor = nodes_[static_cast<std::size_t>(bone)].parent;
            while (ancestor >= 0 && !slot_of_bone.count(ancestor)) ancestor = nodes_[static_cast<std::size_t>(ancestor)].parent;
            if (ancestor < 0) return slot;
        }
        return 0;
    }

    BlendChannel channel(int32_t m, uint32_t c, const std::string& path) {
        uint32_t sizes[2];
        if (!ok("msf_fbx_blend_sizes", msf_fbx_blend_sizes(h_, static_cast<uint32_t>(m), c, sizes)))
            fail(Code::E_SOURCE_VALUE, path, "The FBX reader could not report a blend channel.");
        uint32_t keyframes = sizes[0], total = sizes[1];
        uint32_t deformer = 0;
        std::vector<uint32_t> counts(keyframes ? keyframes : 1), indices(total ? total : 1);
        std::vector<double> values(total ? 3 * static_cast<std::size_t>(total) : 1), targets(keyframes ? keyframes : 1);
        double weight = 0;
        const char* names[2] = {nullptr, nullptr};
        size_t lengths[2] = {0, 0};
        if (!ok("msf_fbx_blend_fill", msf_fbx_blend_fill(h_, static_cast<uint32_t>(m), c, &deformer, counts.data(), indices.data(), values.data(), targets.data(), keyframes,
                                total, &weight, names, lengths)))
            fail(Code::E_SOURCE_VALUE, path, "The FBX reader could not fill a blend channel.");
        BlendChannel out;
        out.deformer = deformer;
        out.deformer_name = decode_replace(std::string_view(names[0], lengths[0]));
        out.channel_name = decode_replace(std::string_view(names[1], lengths[1]));
        out.weight = weight;
        std::size_t start = 0;
        for (uint32_t k = 0; k < keyframes; ++k) {
            Frame frame{targets[k], {}};
            for (uint32_t i = 0; i < counts[k]; ++i)
                frame.offsets.push_back({indices[start + i], {values[3 * (start + i)], values[3 * (start + i) + 1], values[3 * (start + i) + 2]}});
            start += counts[k];
            out.frames.push_back(std::move(frame));
        }
        return out;
    }

    void blend(int32_t m, uint32_t channels, uint32_t points, const std::string& path, std::vector<std::string>& keys,
               std::vector<std::vector<std::vector<double>>>& offsets, std::vector<double>& weights) {
        long long dropped = 0, partial = 0;
        std::vector<std::tuple<uint32_t, std::string, std::string>> names;
        for (uint32_t c = 0; c < channels; ++c) {
            BlendChannel ch = channel(m, c, path);
            names.emplace_back(ch.deformer, ch.deformer_name, ch.channel_name);
            std::vector<std::vector<double>> dense(points, std::vector<double>{0.0, 0.0, 0.0});
            if (!ch.frames.empty()) {
                const Frame* main = nullptr;
                for (const Frame& f : ch.frames)
                    if (std::fabs(f.target - 1.0) < 1e-9) {
                        main = &f;
                        break;
                    }
                bool full = main != nullptr;
                double scale = 1.0;
                if (!full) {
                    main = &ch.frames[0];
                    for (const Frame& f : ch.frames)
                        if (f.target > main->target) main = &f;
                    if (main->target <= 0) fail(Code::E_SOURCE_VALUE, path, "A blend channel has no keyframe with a positive weight.");
                    partial += 1;
                    scale = 1.0 / main->target;
                }
                dropped += static_cast<long long>(ch.frames.size()) - 1;
                for (const auto& [i, o] : main->offsets) {
                    if (i >= points) fail(Code::E_SOURCE_VALUE, path, "A blend shape offset names a point the mesh does not have.");
                    dense[i] = {o[0] * scale, o[1] * scale, o[2] * scale};
                }
            }
            offsets.push_back(std::move(dense));
            weights.push_back(ch.weight);
        }
        std::map<uint32_t, std::string> deformer_names;
        for (const auto& [d, dn, cn] : names) deformer_names.emplace(d, dn);
        // _dedupe: (name, k) with k only where names repeat, numbering deformers in id order.
        std::map<uint32_t, paths::Component> deformer_k;
        for (const auto& [d, name] : deformer_names) {
            std::vector<uint32_t> group;
            for (const auto& [other, other_name] : deformer_names)
                if (other_name == name) group.push_back(other);
            long long k = std::find(group.begin(), group.end(), d) - group.begin();
            deformer_k[d] = {name, group.size() > 1 ? std::optional<std::string>(std::to_string(k)) : std::nullopt};
        }
        for (std::size_t c = 0; c < names.size(); ++c) {
            const auto& [d, dn, cn] = names[c];
            std::vector<std::size_t> group;
            for (std::size_t o = 0; o < names.size(); ++o)
                if (std::get<0>(names[o]) == d && std::get<2>(names[o]) == cn) group.push_back(o);
            long long k = std::find(group.begin(), group.end(), c) - group.begin();
            keys.push_back(paths::target_key({deformer_k[d], {cn, group.size() > 1 ? std::optional<std::string>(std::to_string(k)) : std::nullopt}}));
        }
        if (dropped)
            losses_.push_back(src::warning(Code::W_INBETWEENS_DROPPED, path,
                                           "Dropped " + src::count(dropped, "in-between shape", "in-between shapes") + "; the main shapes are kept."));
        if (partial)
            losses_.push_back(src::warning(Code::W_INBETWEEN_PARTIAL, path,
                                           src::count(partial, "blend channel has", "blend channels have") +
                                               " no full-weight shape; the largest-weight shape is scaled up to full weight."));
    }

    // One glTF animation sampled from the chosen stack.
    void animation(const std::vector<std::size_t>& order, const std::vector<std::string>& node_paths, std::vector<src::Animation>& animations,
                   std::vector<Diagnostic>& losses, std::set<std::size_t>& animated) {
        uint32_t stacks = info_.anim_stacks;
        if (!stacks) return;
        struct StackInfo {
            std::string name;
            double begin, end;
        };
        std::vector<StackInfo> names;
        for (uint32_t s = 0; s < stacks; ++s) {
            msf_fbx_stack stack;
            if (!ok("msf_fbx_stack_get", msf_fbx_stack_get(h_, s, &stack))) fail(Code::E_SOURCE_VALUE, "/", "The FBX reader could not report an animation stack.");
            names.push_back({decode_replace(std::string_view(stack.name, stack.name_len)), stack.time_begin, stack.time_end});
        }
        std::size_t chosen = 0;
        if (options_.animation_name) {
            auto found = std::find_if(names.begin(), names.end(), [&](const StackInfo& s) { return s.name == *options_.animation_name; });
            if (found == names.end()) throw NoStack{};
            chosen = static_cast<std::size_t>(found - names.begin());
        } else {
            if (options_.animation_index >= static_cast<long long>(stacks))
                fail(Code::E_SOURCE_OPTIONS, "/options/animation", "The file has " + std::to_string(stacks) + " animation stacks.");
            chosen = static_cast<std::size_t>(options_.animation_index);
        }
        if (stacks > 1)
            losses.push_back(src::warning(Code::W_ANIMATIONS_SKIPPED, "/",
                                          "Used animation stack " + options_.repr(names[chosen].name) + "; skipped " +
                                              src::count(stacks - 1, "other stack", "other stacks") + "."));
        double begin = names[chosen].begin, end = names[chosen].end;
        double rate = options_.sample_rate ? *options_.sample_rate : (info_.fps > 0 ? info_.fps : 30.0);
        if (!(std::isfinite(begin) && std::isfinite(end)) || end <= begin) return;
        double span = std::floor((end - begin) * rate + 1e-9);
        if (!std::isfinite(span)) throw PyError{PyError::Type::overflow, "cannot convert float infinity to integer"};
        double count = span + 1;
        // The reference built the sample list before checking its length; a list too long to build never reaches the check.
        double last = count <= 9e15 ? begin + (count - 1) / rate : begin;
        bool stop = count <= 9e15 && binary32(end) > binary32(last);
        double samples = count + (stop ? 1 : 0);
        if (samples > kMaxSamples) {
            char text[64];
            std::snprintf(text, sizeof text, "%.0f", samples);
            fail(Code::E_RESOURCE_LIMIT, "/", std::string("The animation needs ") + text + " samples, over the " + std::to_string(kMaxSamples) + " limit.",
                 "Lower options.sample_rate.");
        }
        std::vector<double> times;
        for (long long k = 0; k < static_cast<long long>(count); ++k) times.push_back(begin + static_cast<double>(k) / rate);
        if (stop) times.push_back(end);
        long long node_count = static_cast<long long>(nodes_.size()), channels = info_.blend_channels;
        long long values = static_cast<long long>(times.size()) * (16 * node_count + channels);
        if (values > limits_.max_animation_values)
            fail(Code::E_RESOURCE_LIMIT, "/",
                 "The animation needs " + std::to_string(values) + " sampled values (" + std::to_string(times.size()) + " samples of " +
                     std::to_string(node_count) + " nodes and " + std::to_string(channels) + " blend channels), over the " +
                     limits_.max_animation_values_text + " limit.",
                 "Lower options.sample_rate, or raise limits.max_animation_values.");
        std::vector<double> to_parent(node_count ? 16 * static_cast<std::size_t>(node_count) : 1);
        std::vector<double> weights(channels ? static_cast<std::size_t>(channels) : 1);
        char err[512] = {0};
        std::vector<std::vector<double>> matrices(static_cast<std::size_t>(node_count));
        std::vector<double> weight_values;
        for (double t : times) {
            if (!ok("msf_fbx_evaluate", msf_fbx_evaluate(h_, static_cast<uint32_t>(chosen), t, to_parent.data(), nullptr, static_cast<uint32_t>(node_count), weights.data(),
                                  static_cast<uint32_t>(channels), err, sizeof err)))
                fail(Code::E_SOURCE_VALUE, "/", "The FBX reader could not evaluate the animation: " + prefix(decode_replace(err), 300));
            for (long long i = 0; i < node_count; ++i)
                matrices[static_cast<std::size_t>(i)].insert(matrices[static_cast<std::size_t>(i)].end(), to_parent.begin() + 16 * i,
                                                            to_parent.begin() + 16 * (i + 1));
            weight_values.insert(weight_values.end(), weights.begin(), weights.begin() + channels);
        }
        double shift = std::min(0.0, times[0]);
        if (shift < 0)
            losses.push_back(src::warning(Code::W_TIME_SHIFTED, "/", "Shifted the animation by " + format_g(-shift) + " seconds so it starts at 0."));
        std::vector<double> seconds;
        for (double t : times) seconds.push_back(t - shift);
        std::vector<src::Channel> out;
        // A constant channel is left out only when it matches the static pose, since a stack can hold a node at a
        // value that differs from it. Curves store float32, so matching allows float32 rounding.
        static const char* fields[] = {"translation", "rotation", "scale"};
        for (std::size_t k = 0; k < order.size(); ++k) {
            std::size_t shim = order[k];
            const std::string& path = node_paths[shim];
            const std::vector<double>& flat = matrices[shim];
            const src::Matrix& stat = nodes_[shim].to_parent;
            bool same = true;
            for (std::size_t j = 0; j < flat.size() && same; j += 16)
                for (std::size_t q = 0; q < 16 && same; ++q) same = flat[j + q] == stat[q];
            if (same) continue;
            std::vector<src::Matrix> series;
            for (std::size_t j = 0; j < flat.size(); j += 16) {
                src::Matrix m{};
                std::copy(flat.begin() + static_cast<std::ptrdiff_t>(j), flat.begin() + static_cast<std::ptrdiff_t>(j + 16), m.begin());
                series.push_back(m);
            }
            animated.insert(shim);
            for (const auto& s : series)
                if (src::has_shear(s)) shear(path);
            std::vector<Trs> samples;
            for (const auto& s : series) samples.push_back(trs_of(s, path));
            std::optional<Trs> rest;
            if (!src::has_shear(stat)) rest = trs_of(stat, path);
            for (int f = 0; f < 3; ++f) {
                std::vector<std::vector<double>> rows;
                for (const Trs& sample : samples) rows.push_back(sample.field(f));
                if (f == 1) rows = quaternions(rows);
                bool varies = std::any_of(rows.begin(), rows.end(), [&](const std::vector<double>& row) { return row != rows[0]; });
                bool matches = false;
                if (rest) {
                    std::vector<double> negated;
                    for (double x : rest->field(f)) negated.push_back(-x);
                    matches = near(rows[0], rest->field(f)) || (f == 1 && near(rows[0], negated));
                }
                if (varies || !rest || !matches) out.push_back({static_cast<long long>(k), true, fields[f], seconds, rows, "LINEAR"});
            }
        }
        for (std::size_t k = 0; k < order.size(); ++k) {
            std::size_t shim = order[k];
            int32_t m = nodes_[shim].mesh;
            if (m < 0 || empty_.count(m)) continue;
            uint32_t sizes[8];
            if (!ok("msf_fbx_mesh_sizes", msf_fbx_mesh_sizes(h_, static_cast<uint32_t>(m), sizes))) fail(Code::E_SOURCE_VALUE, "/", "The FBX reader could not report a mesh.");
            std::vector<uint32_t> ids;
            for (uint32_t c = 0; c < sizes[5]; ++c) {
                uint32_t cid = 0;
                if (!ok("msf_fbx_blend_channel_id", msf_fbx_blend_channel_id(h_, static_cast<uint32_t>(m), c, &cid)))
                    fail(Code::E_SOURCE_VALUE, "/", "The FBX reader could not identify a blend channel.");
                ids.push_back(cid);
            }
            if (ids.empty()) continue;
            std::vector<std::vector<double>> rows;
            for (std::size_t r = 0; r < times.size(); ++r) {
                std::vector<double> row;
                for (uint32_t i : ids) {
                    std::size_t at = r * static_cast<std::size_t>(channels) + i;
                    if (at >= weight_values.size()) throw PyError{PyError::Type::index, "array index out of range"};
                    row.push_back(weight_values[at]);
                }
                rows.push_back(row);
            }
            std::vector<double> stat;
            for (uint32_t c = 0; c < sizes[5]; ++c) stat.push_back(channel(m, c, node_paths[shim]).weight);
            bool varies = std::any_of(rows.begin(), rows.end(), [&](const std::vector<double>& row) { return row != rows[0]; });
            if (varies || !near(rows[0], stat)) out.push_back({static_cast<long long>(k), true, "weights", seconds, rows, "LINEAR"});
        }
        if (!out.empty()) animations.push_back({out, std::nullopt});
    }
};

}  // namespace

Generated convert(std::string_view data, const Options& options, const Limits& limits, const std::string& generator) {
    static const uint8_t empty = 0;
    msf_fbx_limits limit{static_cast<size_t>(limits.max_reader_memory), 0};
    Handle handle;
    char err[1024] = {0};
    const uint8_t* bytes = data.empty() ? &empty : reinterpret_cast<const uint8_t*>(data.data());
    if (!msf_fbx_open(bytes, data.size(), &limit, &handle.h, err, sizeof err)) {
        handle.h = nullptr;
        std::string message = strip(decode_replace(err));
        if (lower_ascii(message).find("memory limit") != std::string::npos)
            fail(Code::E_SOURCE_MEMORY, "/", "The FBX reader went over max_reader_memory: " + prefix(message, 400),
                 "Raise limits.max_reader_memory, or reduce the source.");
        throw ParseError{message.empty() ? "ufbx could not read the file." : message};
    }
    Scene scene(handle.h, options, limits);
    return scene.convert(generator);
}

}  // namespace msf::fbx
