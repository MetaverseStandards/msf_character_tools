// SPDX-License-Identifier: MIT
// The deterministic GLB writer source adapters share. Each source point is one
// glTF vertex and triangle indices refer to points, because the reference
// evaluator reads POSITION only.
#include <algorithm>
#include <cmath>
#include <cstring>
#include <map>
#include <set>

#include "msf/json.hpp"
#include "msf/math3d.hpp"
#include "msf/sources.hpp"

namespace msf::sources {

namespace {

using json::Value;

[[noreturn]] void error(const std::string& message) { throw WriteError{message}; }

double f32(double value) {
    if (!std::isfinite(value)) error("Source data contains a non-finite number.");
    float rounded;
    if (!json::to_float32(value, rounded)) throw PyError{PyError::Type::overflow, "float too large to pack with f format"};
    return rounded;
}

double fsum(const std::vector<double>& values) {
    math3d::FsumOutcome r = math3d::fsum(values.data(), values.size());
    if (r.status == math3d::FsumOutcome::Status::overflow) throw PyError{PyError::Type::overflow, "intermediate overflow in fsum"};
    if (r.status == math3d::FsumOutcome::Status::inf_minus_inf) throw PyError{PyError::Type::value, "-inf + inf in fsum"};
    return r.value;
}

std::vector<std::vector<double>> vectors(const std::vector<std::vector<double>>& rows, std::size_t size, const std::string& what) {
    std::vector<std::vector<double>> out;
    for (const auto& row : rows) {
        if (row.size() != size) error(what + " needs " + std::to_string(size) + " components per element.");
        std::vector<double> rounded;
        for (double x : row) rounded.push_back(f32(x));
        out.push_back(std::move(rounded));
    }
    return out;
}

Influences normalized(const Influences& pairs) {
    std::vector<std::pair<long long, double>> merged;
    for (const auto& pair : pairs) {
        long long joint = pair.first;
        double weight = pair.second;
        if (joint < 0 || !std::isfinite(weight) || weight < 0)
            error("Influences need nonnegative joint indices and finite nonnegative weights.");
        auto found = std::find_if(merged.begin(), merged.end(), [&](const auto& e) { return e.first == joint; });
        if (found == merged.end()) merged.emplace_back(joint, 0.0 + weight);
        else found->second += weight;
    }
    Influences positive;
    for (const auto& e : merged)
        if (e.second > 0) positive.push_back(e);
    std::sort(positive.begin(), positive.end());
    std::vector<double> ws;
    for (const auto& e : positive) ws.push_back(e.second);
    double total = fsum(ws);
    if (positive.empty() || !std::isfinite(total)) error("Every skinned point needs a positive finite weight.");
    std::vector<double> weights;
    for (const auto& e : positive) weights.push_back(f32(e.second / total));
    // Fold the binary32 rounding residual into the largest weight (lower joint on ties).
    std::size_t largest = 0;
    for (std::size_t i = 1; i < weights.size(); ++i)
        if (weights[i] > weights[largest] || (weights[i] == weights[largest] && -positive[i].first > -positive[largest].first)) largest = i;
    weights[largest] = f32(weights[largest] + (1.0 - fsum(weights)));
    Influences out;
    for (std::size_t i = 0; i < positive.size(); ++i) out.emplace_back(positive[i].first, weights[i]);
    return out;
}

void put_f32(std::string& out, double v) {
    float f = static_cast<float>(v);
    char bytes[4];
    std::memcpy(bytes, &f, 4);
    out.append(bytes, 4);
}
template <class T>
void put(std::string& out, T v) {
    char bytes[sizeof(T)];
    std::memcpy(bytes, &v, sizeof(T));
    out.append(bytes, sizeof(T));
}

Value integer(long long n) { return Value::make_integer(std::to_string(n)); }
Value real(double d) { return Value::make_real(d); }
Value text(const std::string& s) { return Value::make_string(s); }
Value list(std::vector<Value> items) {
    Value v;
    v.kind = Value::Kind::array;
    v.items = std::move(items);
    return v;
}
Value reals(const std::vector<double>& values) {
    std::vector<Value> items;
    for (double d : values) items.push_back(real(d));
    return list(std::move(items));
}
struct Object {
    Value v;
    Object() { v.kind = Value::Kind::object; }
    Object& set(const std::string& key, Value value) {
        v.members.emplace_back(key, std::move(value));
        return *this;
    }
};

struct Buffer {
    std::string data;
    std::vector<Value> views, accessors;

    long long view(const std::string& payload) {
        while (data.size() % 4) data += '\0';
        views.push_back(Object()
                            .set("buffer", integer(0))
                            .set("byteOffset", integer(static_cast<long long>(data.size())))
                            .set("byteLength", integer(static_cast<long long>(payload.size())))
                            .v);
        data += payload;
        return static_cast<long long>(views.size()) - 1;
    }
    long long accessor(Value fields) {
        accessors.push_back(std::move(fields));
        return static_cast<long long>(accessors.size()) - 1;
    }
    static void bounds(Object& o, const std::vector<std::vector<double>>& rows) {
        std::vector<double> lo(3), hi(3);
        for (std::size_t k = 0; k < 3; ++k) {
            lo[k] = hi[k] = rows[0][k];
            for (const auto& r : rows) {
                if (r[k] < lo[k]) lo[k] = r[k];
                if (r[k] > hi[k]) hi[k] = r[k];
            }
        }
        o.set("min", reals(lo)).set("max", reals(hi));
    }
    long long vec3(const std::vector<std::vector<double>>& rows) {
        std::string payload;
        for (const auto& r : rows)
            for (double x : r) put_f32(payload, x);
        long long v = view(payload);
        Object o;
        o.set("bufferView", integer(v)).set("componentType", integer(5126)).set("type", text("VEC3"));
        o.set("count", integer(static_cast<long long>(rows.size())));
        bounds(o, rows);
        return accessor(o.v);
    }
    long long target(const std::vector<std::vector<double>>& offsets) {
        std::vector<std::size_t> nonzero;
        for (std::size_t i = 0; i < offsets.size(); ++i)
            if (offsets[i][0] != 0 || offsets[i][1] != 0 || offsets[i][2] != 0) nonzero.push_back(i);
        if (nonzero.empty()) {
            Object o;
            o.set("componentType", integer(5126)).set("type", text("VEC3")).set("count", integer(static_cast<long long>(offsets.size())));
            bounds(o, offsets);
            return accessor(o.v);
        }
        // Sparse entries cost 16 bytes against 12 dense; two thirds keeps a margin.
        if (3 * nonzero.size() > 2 * offsets.size()) return vec3(offsets);
        std::string index_bytes, value_bytes;
        for (std::size_t i : nonzero) put<std::uint32_t>(index_bytes, static_cast<std::uint32_t>(i));
        long long indices = view(index_bytes);
        for (std::size_t i : nonzero)
            for (double x : offsets[i]) put_f32(value_bytes, x);
        long long values = view(value_bytes);
        Object sparse;
        sparse.set("count", integer(static_cast<long long>(nonzero.size())))
            .set("indices", Object().set("bufferView", integer(indices)).set("componentType", integer(5125)).v)
            .set("values", Object().set("bufferView", integer(values)).v);
        Object o;
        o.set("componentType", integer(5126)).set("type", text("VEC3")).set("count", integer(static_cast<long long>(offsets.size())));
        o.set("sparse", sparse.v);
        bounds(o, offsets);
        return accessor(o.v);
    }
};

Value primitive(Buffer& buffer, const Mesh& mesh) {
    std::vector<std::vector<double>> points = vectors(mesh.points, 3, "Points");
    if (points.empty()) error("Mesh needs at least one point.");
    Object attributes;
    attributes.set("POSITION", integer(buffer.vec3(points)));
    Object out;
    std::optional<long long> indices;
    if (!mesh.triangles.empty()) {
        long long n = static_cast<long long>(points.size());
        if (mesh.triangles.size() % 3 || std::any_of(mesh.triangles.begin(), mesh.triangles.end(), [&](long long i) { return i < 0 || i >= n; }))
            error("Triangles must be point-index triples within the mesh.");
        bool wide = points.size() >= 65535;
        std::string payload;
        for (long long i : mesh.triangles) {
            if (wide) put<std::uint32_t>(payload, static_cast<std::uint32_t>(i));
            else put<std::uint16_t>(payload, static_cast<std::uint16_t>(i));
        }
        long long v = buffer.view(payload);
        indices = buffer.accessor(Object()
                                      .set("bufferView", integer(v))
                                      .set("componentType", integer(wide ? 5125 : 5123))
                                      .set("type", text("SCALAR"))
                                      .set("count", integer(static_cast<long long>(mesh.triangles.size())))
                                      .v);
    }
    if (mesh.skinned) {
        if (mesh.influences.size() != points.size()) error("Influences need one entry per point.");
        std::vector<Influences> rows;
        for (const Influences& pairs : mesh.influences) rows.push_back(normalized(pairs));
        long long top = -1;
        std::size_t widest = 0;
        for (const auto& row : rows) {
            for (const auto& e : row) top = std::max(top, e.first);
            widest = std::max(widest, row.size());
        }
        if (top > 65535) error("Joint indices must fit unsigned 16-bit storage.");
        for (std::size_t s = 0; s < (widest + 3) / 4; ++s) {
            std::string joints, weights;
            for (const auto& row : rows)
                for (std::size_t k = 4 * s; k < 4 * s + 4; ++k) {
                    put<std::uint16_t>(joints, k < row.size() ? static_cast<std::uint16_t>(row[k].first) : 0);
                    put_f32(weights, k < row.size() ? row[k].second : 0.0);
                }
            long long jv = buffer.view(joints);
            long long wv = buffer.view(weights);
            long long count = static_cast<long long>(rows.size());
            attributes.set("JOINTS_" + std::to_string(s), integer(buffer.accessor(Object()
                                                                                      .set("bufferView", integer(jv))
                                                                                      .set("componentType", integer(5123))
                                                                                      .set("type", text("VEC4"))
                                                                                      .set("count", integer(count))
                                                                                      .v)));
            attributes.set("WEIGHTS_" + std::to_string(s), integer(buffer.accessor(Object()
                                                                                       .set("bufferView", integer(wv))
                                                                                       .set("componentType", integer(5126))
                                                                                       .set("type", text("VEC4"))
                                                                                       .set("count", integer(count))
                                                                                       .v)));
        }
    }
    out.set("attributes", attributes.v);
    if (indices) out.set("indices", integer(*indices));
    else out.set("mode", integer(0));
    if (!mesh.targets.empty()) {
        std::vector<std::vector<std::vector<double>>> targets;
        for (const auto& t : mesh.targets) targets.push_back(vectors(t, 3, "Morph offsets"));
        for (const auto& t : targets)
            if (t.size() != points.size()) error("Morph targets need one offset per point.");
        std::vector<Value> list_targets;
        for (const auto& t : targets) list_targets.push_back(Object().set("POSITION", integer(buffer.target(t))).v);
        out.set("targets", list(std::move(list_targets)));
    }
    return out.v;
}

std::size_t width_of(const std::string& path) { return path == "rotation" ? 4 : 3; }

Value animation(Buffer& buffer, const Animation& anim, const std::vector<Node>& nodes, const std::vector<Mesh>& meshes,
                std::vector<std::pair<std::vector<double>, long long>>& inputs) {
    std::vector<Value> samplers, channels;
    for (const Channel& channel : anim.channels) {
        if (!channel.node_ok || channel.node < 0 || channel.node >= static_cast<long long>(nodes.size()))
            error("Animation channels must target a node.");
        if (channel.interpolation != "LINEAR" && channel.interpolation != "STEP") error("Animation interpolation must be LINEAR or STEP.");
        std::size_t width;
        if (channel.path == "weights") {
            const auto& mesh = nodes[static_cast<std::size_t>(channel.node)].mesh;
            width = mesh ? meshes[static_cast<std::size_t>(*mesh)].targets.size() : 0;
            if (!width) error("Weight channels need a node whose mesh has morph targets.");
        } else if (channel.path == "translation" || channel.path == "rotation" || channel.path == "scale") {
            width = width_of(channel.path);
        } else {
            error("Animation path must be translation, rotation, scale or weights.");
        }
        std::vector<double> times;
        for (double t : channel.times) times.push_back(f32(t));
        bool increasing = true;
        for (std::size_t i = 1; i < times.size(); ++i) increasing = increasing && times[i - 1] < times[i];
        if (times.empty() || times[0] < 0 || !increasing) error("Animation times must be nonnegative and strictly increasing in binary32.");
        std::vector<std::vector<double>> values = vectors(channel.values, width, "Animation " + channel.path + " values");
        if (values.size() != times.size()) error("Animation channels need one value row per time.");
        auto found = std::find_if(inputs.begin(), inputs.end(), [&](const auto& e) { return e.first == times; });
        long long input;
        if (found != inputs.end()) {
            input = found->second;
        } else {
            std::string payload;
            for (double t : times) put_f32(payload, t);
            long long v = buffer.view(payload);
            input = buffer.accessor(Object()
                                        .set("bufferView", integer(v))
                                        .set("componentType", integer(5126))
                                        .set("type", text("SCALAR"))
                                        .set("count", integer(static_cast<long long>(times.size())))
                                        .set("min", reals({times.front()}))
                                        .set("max", reals({times.back()}))
                                        .v);
            inputs.emplace_back(times, input);
        }
        std::string payload;
        std::size_t flat = 0;
        for (const auto& row : values)
            for (double x : row) {
                put_f32(payload, x);
                ++flat;
            }
        long long v = buffer.view(payload);
        bool scalar = channel.path == "weights";
        long long output = buffer.accessor(Object()
                                               .set("bufferView", integer(v))
                                               .set("componentType", integer(5126))
                                               .set("count", integer(static_cast<long long>(scalar ? flat : values.size())))
                                               .set("type", text(scalar ? "SCALAR" : "VEC" + std::to_string(width)))
                                               .v);
        samplers.push_back(Object().set("input", integer(input)).set("output", integer(output)).set("interpolation", text(channel.interpolation)).v);
        channels.push_back(Object()
                               .set("sampler", integer(static_cast<long long>(samplers.size()) - 1))
                               .set("target", Object().set("node", integer(channel.node)).set("path", text(channel.path)).v)
                               .v);
    }
    Object row;
    row.set("samplers", list(std::move(samplers))).set("channels", list(std::move(channels)));
    if (anim.name) row.set("name", text(*anim.name));
    return row.v;
}

}  // namespace

std::string write_glb(const std::vector<Node>& nodes, const std::vector<Mesh>& meshes, const std::vector<Skin>& skins,
                      const std::vector<Animation>& animations, const std::string& generator) {
    Buffer buffer;
    std::vector<Value> gltf_meshes;
    for (const Mesh& mesh : meshes) {
        Object row;
        row.set("primitives", list({primitive(buffer, mesh)}));
        if (!mesh.weights.empty()) {
            if (mesh.weights.size() != mesh.targets.size()) error("Default morph weights need one value per target.");
            std::vector<double> weights;
            for (double w : mesh.weights) weights.push_back(f32(w));
            row.set("weights", reals(weights));
        }
        gltf_meshes.push_back(row.v);
    }
    std::vector<Value> gltf_skins;
    for (const Skin& skin : skins) {
        std::vector<std::vector<double>> matrices = vectors(skin.inverse_bind_matrices, 16, "Inverse bind matrices");
        if (matrices.size() != skin.joints.size()) error("Skins need one inverse bind matrix per joint.");
        std::string payload;
        for (const auto& m : matrices)
            for (double x : m) put_f32(payload, x);
        long long v = buffer.view(payload);
        std::vector<Value> joints;
        for (long long j : skin.joints) joints.push_back(integer(j));
        Object row;
        row.set("joints", list(std::move(joints)));
        row.set("inverseBindMatrices", integer(buffer.accessor(Object()
                                                                   .set("bufferView", integer(v))
                                                                   .set("componentType", integer(5126))
                                                                   .set("type", text("MAT4"))
                                                                   .set("count", integer(static_cast<long long>(matrices.size())))
                                                                   .v)));
        if (skin.skeleton) row.set("skeleton", integer(*skin.skeleton));
        gltf_skins.push_back(row.v);
    }
    std::vector<Value> gltf_nodes;
    std::set<long long> children;
    for (const Node& node : nodes) {
        Object row;
        if (node.name) row.set("name", text(*node.name));
        if (!node.children.empty()) {
            std::vector<long long> sorted = node.children;
            std::sort(sorted.begin(), sorted.end());
            std::vector<Value> items;
            for (long long c : sorted) items.push_back(integer(c));
            row.set("children", list(std::move(items)));
            children.insert(node.children.begin(), node.children.end());
        }
        const std::pair<const char*, const std::vector<double>*> fields[] = {
            {"translation", &node.translation}, {"rotation", &node.rotation}, {"scale", &node.scale}};
        static const std::vector<double> defaults[] = {{0.0, 0.0, 0.0}, {0.0, 0.0, 0.0, 1.0}, {1.0, 1.0, 1.0}};
        for (int f = 0; f < 3; ++f) {
            const std::vector<double>& value = *fields[f].second;
            if (std::any_of(value.begin(), value.end(), [](double x) { return !std::isfinite(x); })) error("Node transforms must be finite.");
            if (value != defaults[f]) row.set(fields[f].first, reals(value));
        }
        if (node.mesh) row.set("mesh", integer(*node.mesh));
        if (node.skin) row.set("skin", integer(*node.skin));
        if (node.weights) {
            std::vector<double> weights;
            for (double w : *node.weights) weights.push_back(f32(w));
            row.set("weights", reals(weights));
        }
        gltf_nodes.push_back(row.v);
    }
    std::vector<std::pair<std::vector<double>, long long>> inputs;
    std::vector<Value> gltf_animations;
    for (const Animation& anim : animations) gltf_animations.push_back(animation(buffer, anim, nodes, meshes, inputs));
    std::vector<Value> roots;
    for (long long i = 0; i < static_cast<long long>(gltf_nodes.size()); ++i)
        if (!children.count(i)) roots.push_back(integer(i));
    Object document;
    document.set("asset", Object().set("version", text("2.0")).set("generator", text(generator)).v);
    document.set("scene", integer(0));
    document.set("scenes", list({Object().set("nodes", list(std::move(roots))).v}));
    document.set("nodes", list(std::move(gltf_nodes)));
    document.set("meshes", list(std::move(gltf_meshes)));
    document.set("accessors", list(std::move(buffer.accessors)));
    if (!gltf_skins.empty()) document.set("skins", list(std::move(gltf_skins)));
    if (!gltf_animations.empty()) document.set("animations", list(std::move(gltf_animations)));
    if (!buffer.data.empty()) {
        while (buffer.data.size() % 4) buffer.data += '\0';
        document.set("buffers", list({Object().set("byteLength", integer(static_cast<long long>(buffer.data.size()))).v}));
        document.set("bufferViews", list(std::move(buffer.views)));
    }
    std::string text_chunk = json::write_canonical(document.v, true);
    while (text_chunk.size() % 4) text_chunk += ' ';
    std::string chunks;
    put<std::uint32_t>(chunks, static_cast<std::uint32_t>(text_chunk.size()));
    put<std::uint32_t>(chunks, 0x4E4F534A);
    chunks += text_chunk;
    if (!buffer.data.empty()) {
        put<std::uint32_t>(chunks, static_cast<std::uint32_t>(buffer.data.size()));
        put<std::uint32_t>(chunks, 0x004E4942);
        chunks += buffer.data;
    }
    std::string out;
    put<std::uint32_t>(out, 0x46546C67);
    put<std::uint32_t>(out, 2);
    put<std::uint32_t>(out, static_cast<std::uint32_t>(12 + chunks.size()));
    return out + chunks;
}

}  // namespace msf::sources
