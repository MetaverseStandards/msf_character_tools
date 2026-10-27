// SPDX-License-Identifier: MIT
// The GLB container, parse_document's exact integer slots, data URIs and
// _validate_document with gltf_semantics' structural checks.
#include <algorithm>
#include <cstring>
#include <set>
#include <unordered_map>
#include <unordered_set>

#include "gltf_detail.hpp"
#include "msf/authoring.hpp"
#include "msf/math3d.hpp"

namespace msf::gltf {

using namespace detail;

Bytes Bytes::own(std::string data) {
    auto owner = std::make_shared<const std::string>(std::move(data));
    return Bytes{std::string_view(*owner), owner};
}

namespace {

constexpr std::uint32_t kJson = 0x4E4F534A, kBin = 0x004E4942;

std::uint32_t u32(std::string_view raw, std::size_t at) {
    std::uint32_t v;
    std::memcpy(&v, raw.data() + at, 4);
    return v;  // GLB is little-endian, as is every platform this builds for
}

// ---------------------------------------------------------------- parse_document

const char* const kIntegral = "Core glTF integer field must have an exact integral numeric value.";

void field(Value& obj, std::string_view key, const std::string& ref) {
    if (obj.kind != Kind::object) return;
    for (auto& [k, v] : obj.members) {
        if (k != key) continue;
        if (v.kind == Kind::integer) return;
        std::string digits;
        if (v.kind == Kind::real && json::exact_integer(v.text, digits)) {
            v = Value::make_integer(digits);
            return;
        }
        fail(Code::E_TYPE, ref + "/" + std::string(key), kIntegral);
    }
}

Value* slot(Value& obj, const char* key) {
    if (obj.kind != Kind::object) return nullptr;
    for (auto& [k, v] : obj.members)
        if (k == key) return &v;
    return nullptr;
}

void array_field(Value& obj, const char* key, const std::string& ref) {
    Value* list = slot(obj, key);
    if (!list || list->kind != Kind::array) return;
    for (std::size_t i = 0; i < list->items.size(); ++i) {
        Value& v = list->items[i];
        if (v.kind == Kind::integer) continue;
        std::string digits;
        if (v.kind == Kind::real && json::exact_integer(v.text, digits)) {
            v = Value::make_integer(digits);
            continue;
        }
        fail(Code::E_TYPE, ref + "/" + key + "/" + std::to_string(i) + "/value", kIntegral);
    }
}

void normalize_slots(Value& doc) {
    if (doc.kind != Kind::object) return;
    field(doc, "scene", "");
    static const std::vector<std::pair<const char*, std::vector<const char*>>> slots = {
        {"buffers", {"byteLength"}},
        {"bufferViews", {"buffer", "byteOffset", "byteLength", "byteStride", "target"}},
        {"accessors", {"bufferView", "byteOffset", "componentType", "count"}},
        {"nodes", {"camera", "skin", "mesh"}},
        {"skins", {"inverseBindMatrices", "skeleton"}},
        {"images", {"bufferView"}},
        {"textures", {"sampler", "source"}},
        {"samplers", {"magFilter", "minFilter", "wrapS", "wrapT"}}};
    for (const auto& [name, fields] : slots) {
        Value* list = slot(doc, name);
        if (!list || list->kind != Kind::array) continue;
        for (std::size_t i = 0; i < list->items.size(); ++i) {
            Value& obj = list->items[i];
            if (obj.kind != Kind::object) continue;
            std::string ref = std::string("/") + name + "/" + std::to_string(i);
            for (const char* key : fields) field(obj, key, ref);
            std::string n = name;
            if (n == "nodes") array_field(obj, "children", ref);
            if (n == "skins") array_field(obj, "joints", ref);
            if (n == "accessors") {
                const Value* ct = get(obj, "componentType");
                bool integer_type = is_int(ct) && (int_is(ct, 5120) || int_is(ct, 5121) || int_is(ct, 5122) || int_is(ct, 5123) || int_is(ct, 5125));
                if (integer_type)
                    for (const char* key : {"min", "max"}) {
                        Value* bounds = slot(obj, key);
                        if (!bounds || bounds->kind != Kind::array) continue;
                        for (Value& v : bounds->items) {
                            if (v.kind != Kind::real) continue;
                            std::string digits;
                            if (!json::exact_integer(v.text, digits))
                                fail(Code::E_ACCESSOR_DOMAIN, ref, "Integer bounds must be raw integral component values.");
                            v = Value::make_integer(digits);
                        }
                    }
                Value* sparse = slot(obj, "sparse");
                if (sparse && sparse->kind == Kind::object) {
                    field(*sparse, "count", ref + "/sparse");
                    for (const char* key : {"indices", "values"}) {
                        Value* part = slot(*sparse, key);
                        if (part && part->kind == Kind::object)
                            for (const char* s : {"bufferView", "byteOffset", "componentType"})
                                field(*part, s, ref + "/sparse/" + key);
                    }
                }
            }
        }
    }
    if (Value* scenes = slot(doc, "scenes"); scenes && scenes->kind == Kind::array)
        for (std::size_t i = 0; i < scenes->items.size(); ++i)
            if (scenes->items[i].kind == Kind::object) array_field(scenes->items[i], "nodes", "/scenes/" + std::to_string(i));
    if (Value* meshes = slot(doc, "meshes"); meshes && meshes->kind == Kind::array)
        for (std::size_t i = 0; i < meshes->items.size(); ++i) {
            Value* primitives = slot(meshes->items[i], "primitives");
            if (!primitives || primitives->kind != Kind::array) continue;
            for (std::size_t j = 0; j < primitives->items.size(); ++j) {
                Value& p = primitives->items[j];
                if (p.kind != Kind::object) continue;
                std::string ref = "/meshes/" + std::to_string(i) + "/primitives/" + std::to_string(j);
                for (const char* key : {"indices", "material", "mode"}) field(p, key, ref);
                if (Value* attrs = slot(p, "attributes"); attrs && attrs->kind == Kind::object)
                    for (auto& member : attrs->members) field(*attrs, member.first, ref + "/attributes");
                if (Value* targets = slot(p, "targets"); targets && targets->kind == Kind::array)
                    for (std::size_t k = 0; k < targets->items.size(); ++k) {
                        Value& target = targets->items[k];
                        if (target.kind != Kind::object) continue;
                        for (auto& member : target.members) field(target, member.first, ref + "/targets/" + std::to_string(k));
                    }
            }
        }
    if (Value* animations = slot(doc, "animations"); animations && animations->kind == Kind::array)
        for (std::size_t i = 0; i < animations->items.size(); ++i) {
            Value& anim = animations->items[i];
            if (anim.kind != Kind::object) continue;
            for (const char* name : {"samplers", "channels"}) {
                Value* list = slot(anim, name);
                if (!list || list->kind != Kind::array) continue;
                bool samplers = std::string(name) == "samplers";
                for (std::size_t j = 0; j < list->items.size(); ++j) {
                    Value& item = list->items[j];
                    if (item.kind != Kind::object) continue;
                    std::string ref = "/animations/" + std::to_string(i) + "/" + name + "/" + std::to_string(j);
                    if (samplers) {
                        field(item, "input", ref);
                        field(item, "output", ref);
                    } else {
                        field(item, "sampler", ref);
                        if (Value* target = slot(item, "target"); target && target->kind == Kind::object) field(*target, "node", ref + "/target");
                    }
                }
            }
        }
    if (Value* materials = slot(doc, "materials"); materials && materials->kind == Kind::array)
        for (std::size_t i = 0; i < materials->items.size(); ++i) {
            Value& mat = materials->items[i];
            if (mat.kind != Kind::object) continue;
            std::string ref = "/materials/" + std::to_string(i);
            std::vector<std::pair<Value*, std::pair<const char*, std::string>>> infos;
            for (const char* key : {"normalTexture", "occlusionTexture", "emissiveTexture"}) infos.push_back({&mat, {key, ref}});
            if (Value* pbr = slot(mat, "pbrMetallicRoughness"); pbr && pbr->kind == Kind::object)
                for (const char* key : {"baseColorTexture", "metallicRoughnessTexture"}) infos.push_back({pbr, {key, ref + "/pbrMetallicRoughness"}});
            for (auto& [obj, info] : infos) {
                Value* texture = slot(*obj, info.first);
                if (texture && texture->kind == Kind::object)
                    for (const char* s : {"index", "texCoord"}) field(*texture, s, info.second + "/" + info.first);
            }
        }
}

bool strict_utf8(std::string_view text) { return json::validate_wtf8(text) && !json::has_surrogate(text); }

Value parse_document(std::string_view text) {
    if (!strict_utf8(text) || text.compare(0, 3, "\xEF\xBB\xBF") == 0) throw DecodeError{};
    json::ParseOutcome parsed = json::parse(text);
    using Status = json::ParseOutcome::Status;
    switch (parsed.status) {
        case Status::ok: break;
        case Status::syntax: throw DecodeError{};
        case Status::too_deep: throw TooDeep{};
        case Status::constant: fail(Code::E_NONFINITE, "/", "Invalid JSON constant " + parsed.detail + ".");
        case Status::duplicate_key: throw DuplicateKey{parsed.detail};
    }
    normalize_slots(parsed.value);
    return std::move(parsed.value);
}

}  // namespace

Parsed parse_asset(std::string_view raw, const std::string& format) {
    Parsed out;
    if (format == "glb") {
        if (raw.size() < 20) fail(Code::E_GLB_HEADER, "/", "Truncated GLB header.");
        std::uint32_t magic = u32(raw, 0), version = u32(raw, 4), length = u32(raw, 8);
        if (magic != 0x46546C67 || version != 2 || length != raw.size() || length % 4)
            fail(Code::E_GLB_HEADER, "/", "GLB magic/version/total length mismatch.");
        std::size_t cursor = 12;
        while (cursor < raw.size()) {
            if (cursor + 8 > raw.size()) fail(Code::E_GLB_CHUNK, "/", "Truncated chunk header.");
            std::uint64_t size = u32(raw, cursor);
            std::uint32_t kind = u32(raw, cursor + 4);
            cursor += 8;
            if (size % 4 || cursor + size > raw.size()) fail(Code::E_GLB_CHUNK, "/", "Chunk length is unaligned or exceeds GLB.");
            out.chunks.push_back({kind, raw.substr(cursor, static_cast<std::size_t>(size))});
            cursor += static_cast<std::size_t>(size);
        }
        std::size_t json_chunks = 0, bin_chunks = 0;
        for (const Chunk& c : out.chunks) {
            json_chunks += c.type == kJson;
            bin_chunks += c.type == kBin;
        }
        if (out.chunks.empty() || out.chunks[0].type != kJson || json_chunks != 1 || bin_chunks > 1)
            fail(Code::E_GLB_CHUNK, "/", "GLB needs one first JSON chunk and at most one BIN chunk.");
        for (std::size_t i = 0; i < out.chunks.size(); ++i)
            if (out.chunks[i].type == kBin) {
                if (i != 1) fail(Code::E_GLB_CHUNK, "/", "BIN chunk must be second.");
                out.has_bin = true;
                out.bin = out.chunks[i].data;
            }
        out.doc = parse_document(out.chunks[0].data);
        out.kind = "glb";
    } else {
        out.doc = parse_document(raw);
        out.kind = "gltf";
    }
    return out;
}

// ---------------------------------------------------------------- data URIs

namespace {

int base64_value(unsigned char c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
}

// binascii.a2b_base64(strict_mode=True) on base64 alphabet characters and '='.
bool strict_base64(std::string_view in, std::string& out) {
    if (!in.empty() && in[0] == '=') return false;
    int quad = 0, pads = 0;
    bool padding = false;
    unsigned left = 0;
    for (std::size_t i = 0; i < in.size(); ++i) {
        unsigned char c = static_cast<unsigned char>(in[i]);
        if (c == '=') {
            padding = true;
            if (quad == 0) return false;
            if (quad >= 2 && quad + ++pads >= 4) return i + 1 >= in.size();
            continue;
        }
        int v = base64_value(c);
        if (v < 0 || padding) return false;
        pads = 0;
        switch (quad) {
            case 0: quad = 1; left = static_cast<unsigned>(v); break;
            case 1: quad = 2; out.push_back(static_cast<char>((left << 2) | (static_cast<unsigned>(v) >> 4))); left = static_cast<unsigned>(v) & 0x0f; break;
            case 2: quad = 3; out.push_back(static_cast<char>((left << 4) | (static_cast<unsigned>(v) >> 2))); left = static_cast<unsigned>(v) & 0x03; break;
            default: quad = 0; out.push_back(static_cast<char>((left << 6) | static_cast<unsigned>(v))); left = 0; break;
        }
    }
    return quad == 0;
}

}  // namespace

Bytes data_uri(const std::string& uri, const std::string& ref) {
    // re.fullmatch(r"data:[^,]*;base64,[A-Za-z0-9+/=\r\n]*", uri)
    std::size_t comma = uri.find(',');
    bool shaped = uri.compare(0, 5, "data:") == 0 && comma != std::string::npos && comma >= 5 + 7 &&
                  uri.compare(comma - 7, 7, ";base64") == 0;
    std::string payload;
    if (shaped)
        for (std::size_t i = comma + 1; i < uri.size(); ++i) {
            char c = uri[i];
            if (c == '\r' || c == '\n') continue;
            if (base64_value(static_cast<unsigned char>(c)) < 0 && c != '=') {
                shaped = false;
                break;
            }
            payload.push_back(c);
        }
    if (!shaped) fail(Code::E_RESOURCE_URI, ref, "Only explicit base64 data URIs are supported.");
    std::string decoded;
    if (!strict_base64(payload, decoded)) fail(Code::E_RESOURCE_URI, ref, "Invalid base64 resource.");
    return Bytes::own(std::move(decoded));
}

// ---------------------------------------------------------------- semantics

namespace {

const char* const kIndexed[] = {"TEXCOORD", "COLOR", "JOINTS", "WEIGHTS"};

bool starts_with(const std::string& s, const std::string& prefix) { return s.compare(0, prefix.size(), prefix) == 0; }

// gltf_semantics.semantic_type
void semantic_type(const std::string& name, const Value& a, const Value* count, const std::string& ref, bool morph = false,
                   const Value* base = nullptr) {
    std::string family = name;
    for (const char* prefix : kIndexed) {
        std::string p = std::string(prefix) + "_";
        if (!starts_with(name, p)) continue;
        std::string suffix = name.substr(p.size());
        bool ok = !suffix.empty() && suffix.size() <= 9 && std::all_of(suffix.begin(), suffix.end(), [](char c) { return c >= '0' && c <= '9'; }) &&
                  (suffix == "0" || suffix[0] != '0');
        if (!ok) fail(Code::E_ATTRIBUTE_SEMANTIC, ref, "Indexed attribute suffix must be decimal 0..999999999 without leading zeros.");
        family = prefix;
        break;
    }
    const Value* a_count = get(a, "count");
    if (!py_equal(a_count, count)) fail(morph ? Code::E_MORPH : Code::E_GEOMETRY_TYPE, ref, "Attribute count must match primitive vertex count.");
    std::vector<std::string> shapes;
    if (family == "POSITION" || family == "NORMAL") shapes = {"VEC3"};
    else if (family == "TANGENT") shapes = {morph ? "VEC3" : "VEC4"};
    else if (family == "TEXCOORD") shapes = {"VEC2"};
    else if (family == "COLOR") shapes = {"VEC3", "VEC4"};
    else if (family == "JOINTS" || family == "WEIGHTS") shapes = {"VEC4"};
    else return;
    const Value* normalized = get(a, "normalized");
    bool norm_false = !normalized || is_false(normalized);  // a.get('normalized', False) is False
    bool norm_true = is_true(normalized);
    const Value* ct = get(a, "componentType");
    auto ct_in = [&](std::initializer_list<long long> set) {
        for (long long x : set)
            if (numeric_equals(ct, x)) return true;
        return false;
    };
    bool ok;
    if (family == "JOINTS" && !morph) {
        ok = ct_in({5121, 5123}) && norm_false;
    } else if (family == "TEXCOORD" || family == "COLOR" || family == "WEIGHTS") {
        bool wide = morph && family != "WEIGHTS";
        ok = (numeric_equals(ct, 5126) && norm_false) || ((wide ? ct_in({5120, 5121, 5122, 5123}) : ct_in({5121, 5123})) && norm_true);
    } else {
        ok = numeric_equals(ct, 5126) && norm_false;
    }
    if (morph && (family == "JOINTS" || family == "WEIGHTS")) ok = false;
    const Value* type = get(a, "type");
    bool shape_ok = is_str(type) && std::find(shapes.begin(), shapes.end(), type->text) != shapes.end();
    bool color_mismatch = false;
    if (morph && family == "COLOR") {
        color_mismatch = !py_equal(type, get(*base, "type"));
    }
    if (!ok || !shape_ok || color_mismatch)
        fail(morph ? Code::E_MORPH : Code::E_GEOMETRY_TYPE, ref,
             "Core attribute component type, shape or normalization is incompatible with its semantic.");
    if (family == "POSITION" && (!has(a, "min") || !has(a, "max")))
        fail(Code::E_ACCESSOR_BOUNDS, ref, "POSITION accessors require min and max bounds.");
}

const Value& accessor_at(const Value* accessors, const Value* id, const std::string& ref) {
    return accessors->items[index(id, size_of(accessors), ref)];
}

void validate_meshes(const Value& doc) {
    const Value* accessors = get(doc, "accessors");
    const Value* meshes = get(doc, "meshes");
    for (std::size_t mi = 0; mi < size_of(meshes); ++mi) {
        const Value& mesh = meshes->items[mi];
        const Value* primitives = get(mesh, "primitives");
        if (!is_list(primitives) || primitives->items.empty()) fail(Code::E_MESH, "/meshes/" + std::to_string(mi), "Mesh needs nonempty primitives.");
        for (std::size_t pi = 0; pi < primitives->items.size(); ++pi) {
            std::string ref = "/meshes/" + std::to_string(mi) + "/primitives/" + std::to_string(pi);
            const Value& p = primitives->items[pi];
            const Value* attrs = get(p, "attributes");
            if (!is_obj(&p) || !is_obj(attrs) || attrs->members.empty()) fail(Code::E_MESH, ref, "Primitive needs nonempty attributes.");
            const Value& first = accessor_at(accessors, &attrs->members.front().second, ref);
            const Value* count = get(first, "count");
            std::vector<std::set<long long>> indexed(4);
            for (const auto& [name, aid] : attrs->members) {
                const Value& a = accessor_at(accessors, &aid, ref + "/attributes/" + name);
                semantic_type(name, a, count, ref + "/attributes/" + name);
                for (int k = 0; k < 4; ++k) {
                    std::string prefix = std::string(kIndexed[k]) + "_";
                    if (starts_with(name, prefix)) indexed[static_cast<std::size_t>(k)].insert(std::stoll(name.substr(prefix.size())));
                }
            }
            for (const auto& values : indexed)
                if (!values.empty() && (*values.begin() != 0 || *values.rbegin() != static_cast<long long>(values.size()) - 1))
                    fail(Code::E_ATTRIBUTE_SEMANTIC, ref, "Indexed attribute sets must be contiguous from zero.");
            if (indexed[2] != indexed[3]) fail(Code::E_ATTRIBUTE_SEMANTIC, ref, "JOINTS and WEIGHTS sets must be paired.");
            const Value* vertices = count;
            if (has(p, "indices")) vertices = get(accessor_at(accessors, get(p, "indices"), ref), "count");
            const Value* mode_value = get(p, "mode");
            long long mode = 4;
            if (mode_value) {
                if (!is_int(mode_value) || big(*mode_value) < BigInt(0) || big(*mode_value) > BigInt(6))
                    fail(Code::E_PRIMITIVE_MODE, ref, "Invalid primitive mode.");
                mode = big(*mode_value).to_int64();
            }
            if (is_int(vertices) && big(*vertices) > BigInt(0)) {
                BigInt v = big(*vertices);
                if ((mode == 1 && v.mod(2)) || (mode == 4 && v.mod(3)) || ((mode == 2 || mode == 3) && v < BigInt(2)) ||
                    ((mode == 5 || mode == 6) && v < BigInt(3)))
                    fail(Code::E_PRIMITIVE_COUNT, ref, "Primitive vertex count is incompatible with topology mode.");
            }
            const Value* targets = get(p, "targets");
            if (targets && (!is_list(targets) || targets->items.empty())) fail(Code::E_MORPH, ref, "Authored targets array must be nonempty.");
            for (std::size_t ti = 0; ti < size_of(targets); ++ti) {
                const Value& target = targets->items[ti];
                if (!is_obj(&target) || target.members.empty()) fail(Code::E_MORPH, ref, "Morph target must be a nonempty attribute object.");
                for (const auto& [name, aid] : target.members) {
                    const Value* base_id = get(*attrs, name);
                    if (!base_id) fail(Code::E_MORPH, ref, "Morph semantic must have a corresponding base attribute.");
                    const Value& a = accessor_at(accessors, &aid, ref);
                    const Value& base = accessor_at(accessors, base_id, ref);
                    semantic_type(name, a, count, ref + "/targets/" + std::to_string(ti) + "/" + name, true, &base);
                }
            }
        }
        morph_count(mesh);
    }
}

}  // namespace

std::size_t morph_count(const Value& mesh) {
    std::set<std::size_t> counts;
    for (const Value& p : item(mesh, "primitives").items) {
        const Value* targets = get(p, "targets");
        if (truthy(targets)) counts.insert(targets->kind == Kind::array ? targets->items.size() : targets->members.size());
    }
    if (counts.size() > 1) fail(Code::E_MORPH, "/meshes", "Positive morph target counts must agree across primitives.");
    return counts.empty() ? 0 : *counts.begin();
}

std::size_t animation_layout(const Value& doc, const Value& sampler, const Value& target, const std::string& ref) {
    const Value* nodes = get(doc, "nodes");
    const Value* accessors = get(doc, "accessors");
    const Value& node = nodes->items[index(get(target, "node"), size_of(nodes), ref)];
    const std::string& path = item(target, "path").text;
    const Value& times = accessor_at(accessors, get(sampler, "input"), ref);
    const Value& a = accessor_at(accessors, get(sampler, "output"), ref);
    bool weights = path == "weights";
    std::size_t count = weights && has(node, "mesh") ? morph_count(item(doc, "meshes").items[static_cast<std::size_t>(big(item(node, "mesh")).to_int64())])
                        : path == "rotation" ? 4 : 3;
    if (weights && (!has(node, "mesh") || count == 0)) fail(Code::E_ANIMATION, ref, "Weights target needs a mesh with morph targets.");
    const Value* interpolation = get(sampler, "interpolation");
    long long factor = str_is(interpolation, "CUBICSPLINE") ? 3 : 1;
    std::string expected = weights ? "SCALAR" : path == "rotation" ? "VEC4" : "VEC3";
    const Value* ct = get(a, "componentType");
    const Value* normalized = get(a, "normalized");
    bool ok = numeric_equals(ct, 5126) && !truthy(normalized);
    if (path == "rotation" || weights) {
        bool integer = numeric_equals(ct, 5120) || numeric_equals(ct, 5121) || numeric_equals(ct, 5122) || numeric_equals(ct, 5123);
        ok = ok || (integer && is_true(normalized));
    }
    BigInt expected_count = big(item(times, "count")) * BigInt(factor) * BigInt(weights ? static_cast<long long>(count) : 1);
    if (!ok || !str_is(get(a, "type"), expected) || big(item(a, "count")) != expected_count || (factor == 3 && big(item(times, "count")) < BigInt(2)))
        fail(Code::E_ANIMATION_TYPE, ref, "Animation component type, shape, output count or cubic key count disagrees with target.");
    return count;
}

namespace {

std::vector<std::size_t> chain_of(std::size_t node, const std::unordered_map<std::size_t, std::size_t>& parents) {
    std::vector<std::size_t> out{node};
    for (auto it = parents.find(node); it != parents.end(); it = parents.find(node)) {
        node = it->second;
        out.push_back(node);
    }
    return out;
}

void validate_skin_hierarchy(const Value& doc, const std::unordered_map<std::size_t, std::size_t>& parents) {
    const Value* nodes = get(doc, "nodes");
    const Value* skins = get(doc, "skins");
    const Value* scenes = get(doc, "scenes");
    for (std::size_t si = 0; si < size_of(skins); ++si) {
        const Value& skin = skins->items[si];
        std::string ref = "/skins/" + std::to_string(si);
        const Value& joints = item(skin, "joints");
        std::vector<std::vector<std::size_t>> chains;
        for (const Value& j : joints.items) chains.push_back(chain_of(static_cast<std::size_t>(big(j).to_int64()), parents));
        std::set<std::size_t> common(chains[0].begin(), chains[0].end());
        for (std::size_t c = 1; c < chains.size(); ++c) {
            std::set<std::size_t> next;
            for (std::size_t x : chains[c])
                if (common.count(x)) next.insert(x);
            common = std::move(next);
        }
        if (common.empty()) fail(Code::E_SKIN, ref, "Skin joints must have a common root.");
        std::size_t root = *std::find_if(chains[0].begin(), chains[0].end(), [&](std::size_t j) { return common.count(j) > 0; });
        std::vector<std::size_t> root_chain = chain_of(root, parents);
        if (const Value* skeleton = get(skin, "skeleton")) {
            std::size_t s = static_cast<std::size_t>(big(*skeleton).to_int64());
            if (std::find(root_chain.begin(), root_chain.end(), s) == root_chain.end())
                fail(Code::E_SKIN, ref, "Skeleton must be common root or its ancestor.");
        }
        for (std::size_t sc = 0; sc < size_of(scenes); ++sc) {
            std::set<std::size_t> roots;
            if (const Value* list = get(scenes->items[sc], "nodes"))
                for (const Value& r : list->items) roots.insert(static_cast<std::size_t>(big(r).to_int64()));
            auto meets = [&](const std::vector<std::size_t>& chain) {
                return std::any_of(chain.begin(), chain.end(), [&](std::size_t x) { return roots.count(x) > 0; });
            };
            bool referenced = false;
            for (std::size_t i = 0; i < size_of(nodes) && !referenced; ++i) {
                const Value* skin_id = get(nodes->items[i], "skin");
                referenced = skin_id && numeric_equals(skin_id, static_cast<long long>(si)) && meets(chain_of(i, parents));
            }
            if (referenced && !meets(root_chain)) fail(Code::E_SKIN, ref, "Common joint root must belong to every scene referencing this skin.");
        }
    }
}

bool unique_ints(const Value* list) {
    if (!is_list(list)) return false;
    std::unordered_set<std::string> seen;
    for (const Value& x : list->items) {
        if (!is_int(&x)) return false;
        seen.insert(x.text);
    }
    return seen.size() == list->items.size();
}

void string_check(const Value* value, const std::string& ref) {
    static const Value null_value;
    authoring::string(value ? *value : null_value, ref);
}

}  // namespace

void validate_document(const Value& doc, Caps caps) {
    const Value* asset = get(doc, "asset");
    if (!is_obj(&doc) || !is_obj(asset) || !str_is(get(*asset, "version"), "2.0"))
        fail(Code::E_GLTF_VERSION, "/asset", "Expected glTF asset.version 2.0.");
    if (const Value* min_version = get(*asset, "minVersion"); min_version && !str_is(min_version, "2.0"))
        fail(Code::E_GLTF_VERSION, "/asset/minVersion", "Unsupported minimum glTF version.");
    for (const char* name : {"buffers", "bufferViews", "accessors", "nodes", "meshes", "skins", "animations", "scenes", "images", "textures",
                             "samplers", "materials", "cameras"}) {
        const Value* list = get(doc, name);
        if (list && (!is_list(list) || !std::all_of(list->items.begin(), list->items.end(), [](const Value& x) { return is_obj(&x); })))
            fail(Code::E_TYPE, std::string("/") + name, "Expected an array of objects.");
        if (static_cast<long long>(size_of(list)) > kMaxStructuralObjects)
            fail(Code::E_RESOURCE_LIMIT, std::string("/") + name, "Structural inventory exceeds object budget.");
    }
    for (const char* name : {"extensionsUsed", "extensionsRequired"}) {
        const Value* list = get(doc, name);
        if (!list) continue;
        bool ok = is_list(list) && std::all_of(list->items.begin(), list->items.end(), [](const Value& x) { return is_str(&x); });
        if (ok) {
            std::unordered_set<std::string> seen;
            for (const Value& x : list->items) seen.insert(x.text);
            ok = seen.size() == list->items.size();
        }
        if (!ok) fail(Code::E_TYPE, std::string("/") + name, "Expected unique extension strings.");
    }
    {
        std::unordered_set<std::string> used;
        if (const Value* list = get(doc, "extensionsUsed"))
            for (const Value& x : list->items) used.insert(x.text);
        if (const Value* list = get(doc, "extensionsRequired"))
            for (const Value& x : list->items)
                if (!used.count(x.text)) fail(Code::E_EXTENSION, "/extensionsRequired", "Required extensions must also be listed as used.");
    }
    const Value* buffers = get(doc, "buffers");
    const Value* views = get(doc, "bufferViews");
    const Value* accessors = get(doc, "accessors");
    for (std::size_t i = 0; i < size_of(buffers); ++i) {
        const Value& b = buffers->items[i];
        positive_int(get(b, "byteLength"), "/buffers/" + std::to_string(i) + "/byteLength");
        if (const Value* uri = get(b, "uri")) string_check(uri, "/buffers/" + std::to_string(i) + "/uri");
    }
    for (std::size_t i = 0; i < size_of(views); ++i) {
        const Value& v = views->items[i];
        std::string ref = "/bufferViews/" + std::to_string(i);
        const Value& b = buffers->items[index(get(v, "buffer"), size_of(buffers), ref)];
        positive_int(get(v, "byteLength"), ref);
        positive_int(get(v, "byteOffset") ? get(v, "byteOffset") : &kZero, ref, true);
        if (int_or(v, "byteOffset", 0) + big(item(v, "byteLength")) > big(item(b, "byteLength")))
            fail(Code::E_BUFFER_BOUNDS, ref, "bufferView exceeds declared buffer length.");
        if (const Value* stride = get(v, "byteStride");
            stride && (!is_int(stride) || big(*stride) < BigInt(4) || big(*stride) > BigInt(252) || big(*stride).mod(4)))
            fail(Code::E_ACCESSOR_STRIDE, ref, "byteStride must be a multiple of 4 between 4 and 252.");
        if (const Value* target = get(v, "target"); target && !numeric_equals(target, 34962) && !numeric_equals(target, 34963))
            fail(Code::E_TYPE, ref, "Unknown bufferView target.");
    }
    validate_meshes(doc);
    BigInt decoded = 0;
    for (std::size_t i = 0; i < size_of(accessors); ++i) {
        const Value& a = accessors->items[i];
        std::string ref = "/accessors/" + std::to_string(i);
        const Value* ct = get(a, "componentType");
        const Value* type = get(a, "type");
        Component c{};
        int columns = 0, rows = 0;
        if (!is_int(ct) || !big(*ct).fits_int64() || !component(big(*ct).to_int64(), c) || !is_str(type) || !shape(type->text, columns, rows))
            fail(Code::E_ACCESSOR_TYPE, ref, "Unsupported componentType or shape.");
        positive_int(get(a, "count"), ref);
        positive_int(get(a, "byteOffset") ? get(a, "byteOffset") : &kZero, ref, true);
        const Value* normalized = get(a, "normalized");
        long long component_type = big(*ct).to_int64();
        if ((normalized && normalized->kind != Kind::boolean) || (truthy(normalized) && (component_type == 5125 || component_type == 5126)))
            fail(Code::E_ACCESSOR_TYPE, ref, "normalized only supports byte/short components.");
        Layout l = layout(component_type, type->text);
        BigInt components = big(item(a, "count")) * BigInt(static_cast<long long>(l.offsets.size()));
        decoded = decoded + components;
        if (components > BigInt(caps.accessor) || decoded > BigInt(caps.total))
            fail(Code::E_RESOURCE_LIMIT, ref, "Accessor exceeds per-accessor or total decoded component budget.");
        for (const char* f : {"min", "max"})
            if (const Value* bound = get(a, f)) vector(bound, l.offsets.size(), ref + "/" + f);
        validate_bounds(a, nullptr, ref);
        if (has(a, "min") && has(a, "max")) {
            const Value& lo = item(a, "min");
            const Value& hi = item(a, "max");
            for (std::size_t k = 0; k < lo.items.size() && k < hi.items.size(); ++k)
                if (json::compare_numbers(lo.items[k], hi.items[k]) > 0) fail(Code::E_ACCESSOR_DOMAIN, ref, "Accessor min exceeds max.");
        }
        BigInt offset = int_or(a, "byteOffset", 0);
        if (const Value* view_id = get(a, "bufferView")) {
            const Value& v = views->items[index(view_id, size_of(views), ref)];
            BigInt stride = int_or(v, "byteStride", l.element_size);
            BigInt start = int_or(v, "byteOffset", 0) + offset;
            if (offset.mod(l.size) || start.mod(l.size) || (type->text.compare(0, 3, "MAT") == 0 && start.mod(4)))
                fail(Code::E_ACCESSOR_ALIGNMENT, ref, "Misaligned accessor.");
            if (stride < BigInt(l.element_size) || stride.mod(l.size) ||
                offset + (big(item(a, "count")) - BigInt(1)) * stride + BigInt(l.element_size) > big(item(v, "byteLength")))
                fail(Code::E_ACCESSOR_BOUNDS, ref, "Accessor range or stride exceeds bufferView.");
        } else if (!offset.zero()) {
            fail(Code::E_ACCESSOR_BOUNDS, ref, "Accessor without bufferView cannot have a byteOffset.");
        }
        if (const Value* sparse = get(a, "sparse")) {
            authoring::keys(*sparse, {"count", "indices", "values"}, {"extensions", "extras"}, ref);
            positive_int(get(*sparse, "count"), ref);
            BigInt sparse_count = big(item(*sparse, "count"));
            if (sparse_count > big(item(a, "count"))) fail(Code::E_SPARSE_INDEX, ref, "Sparse count exceeds accessor count.");
            for (const char* f : {"indices", "values"}) {
                bool indices = std::string(f) == "indices";
                const Value& part = item(*sparse, f);
                if (indices)
                    authoring::keys(part, {"bufferView", "componentType"}, {"byteOffset", "extensions", "extras"}, ref);
                else
                    authoring::keys(part, {"bufferView"}, {"byteOffset", "extensions", "extras"}, ref);
                const Value& v = views->items[index(get(part, "bufferView"), size_of(views), ref)];
                positive_int(get(part, "byteOffset") ? get(part, "byteOffset") : &kZero, ref, true);
                if (has(v, "byteStride") || has(v, "target")) fail(Code::E_SPARSE_STRIDE, ref, "Sparse bufferView cannot declare stride or target.");
                long long item_size = l.element_size, align = l.size;
                if (indices) {
                    const Value* ict = get(part, "componentType");
                    if (!is_int(ict) || !(int_is(ict, 5121) || int_is(ict, 5123) || int_is(ict, 5125)))
                        fail(Code::E_SPARSE_TYPE, ref, "Sparse indices must be unsigned byte/short/int.");
                    Component ic{};
                    component(big(*ict).to_int64(), ic);
                    item_size = align = ic.size;
                }
                BigInt part_offset = int_or(part, "byteOffset", 0);
                BigInt start = int_or(v, "byteOffset", 0) + part_offset;
                if (start.mod(align) || part_offset.mod(align) || (!indices && type->text.compare(0, 3, "MAT") == 0 && start.mod(4)) ||
                    part_offset + sparse_count * BigInt(item_size) > big(item(v, "byteLength")))
                    fail(Code::E_ACCESSOR_BOUNDS, ref, "Sparse data misaligned or out of bounds.");
            }
        }
    }
    const Value* nodes = get(doc, "nodes");
    const Value* meshes = get(doc, "meshes");
    const Value* skins = get(doc, "skins");
    std::unordered_map<std::size_t, std::size_t> parents;
    std::set<std::size_t> skinned_meshes;
    for (std::size_t i = 0; i < size_of(nodes); ++i) {
        const Value& n = nodes->items[i];
        std::string ref = "/nodes/" + std::to_string(i);
        if (const Value* m = get(n, "matrix")) {
            vector(m, 16, ref);
            math3d::Mat local{};
            for (int r = 0; r < 4; ++r)
                for (int c = 0; c < 4; ++c) local[r][c] = m->items[static_cast<std::size_t>(c * 4 + r)].number;
            math3d::check_affine(local, 1e-12, ref);
            math3d::check_trs(local, 1e-9, ref);
            if (has(n, "translation") || has(n, "rotation") || has(n, "scale"))
                fail(Code::E_NODE_TRANSFORM, ref, "matrix and TRS are mutually exclusive.");
        }
        for (const auto& [k, length] : {std::pair{"translation", 3}, std::pair{"rotation", 4}, std::pair{"scale", 3}})
            if (const Value* v = get(n, k)) vector(v, static_cast<std::size_t>(length), ref + "/" + k);
        if (const Value* q = get(n, "rotation")) {
            math3d::Vec v;
            for (const Value& x : q->items) v.push_back(x.number);
            math3d::check_authored_quaternion(v, ref);
        }
        const Value* cameras = get(doc, "cameras");
        for (const auto& [k, list] : {std::pair{"mesh", meshes}, std::pair{"skin", skins}, std::pair{"camera", cameras}})
            if (const Value* v = get(n, k)) index(v, size_of(list), ref + "/" + k);
        if (has(n, "skin") && !has(n, "mesh")) fail(Code::E_SKIN, ref, "Skinned node must reference a mesh.");
        if (has(n, "skin")) skinned_meshes.insert(static_cast<std::size_t>(big(item(n, "mesh")).to_int64()));
        const Value* children = get(n, "children");
        if (children && !unique_ints(children)) fail(Code::E_HIERARCHY, ref, "Children must be unique integer indices.");
        for (std::size_t c = 0; c < size_of(children); ++c) {
            std::size_t child = index(&children->items[c], size_of(nodes), ref + "/children");
            if (parents.count(child)) fail(Code::E_HIERARCHY, ref, "Node has multiple parents.");
            parents[child] = i;
        }
    }
    {
        std::vector<char> complete(size_of(nodes));
        for (std::size_t i = 0; i < size_of(nodes); ++i) {
            std::set<std::size_t> visiting;
            std::size_t child = i;
            while (!complete[child]) {
                if (visiting.count(child)) fail(Code::E_HIERARCHY_CYCLE, "/nodes/" + std::to_string(i), "Node hierarchy contains a cycle.");
                visiting.insert(child);
                auto parent = parents.find(child);
                if (parent == parents.end()) break;
                child = parent->second;
            }
            for (std::size_t v : visiting) complete[v] = 1;
        }
    }
    const Value* materials = get(doc, "materials");
    for (std::size_t i = 0; i < size_of(meshes); ++i) {
        const Value& mesh = meshes->items[i];
        const Value& primitives = item(mesh, "primitives");
        for (std::size_t j = 0; j < primitives.items.size(); ++j) {
            const Value& p = primitives.items[j];
            std::string ref = "/meshes/" + std::to_string(i) + "/primitives/" + std::to_string(j);
            if (skinned_meshes.count(i) && (!has(item(p, "attributes"), "JOINTS_0") || !has(item(p, "attributes"), "WEIGHTS_0")))
                fail(Code::E_SKIN, ref, "Skinned primitive needs JOINTS_0 and WEIGHTS_0.");
            if (const Value* ix = get(p, "indices")) {
                const Value& a = accessor_at(accessors, ix, ref);
                const Value* act = get(a, "componentType");
                if (!str_is(get(a, "type"), "SCALAR") || !(numeric_equals(act, 5121) || numeric_equals(act, 5123) || numeric_equals(act, 5125)) ||
                    truthy(get(a, "normalized")))
                    fail(Code::E_INDEX_TYPE, ref, "Primitive indices must be unsigned unnormalized scalars.");
            }
            if (const Value* material = get(p, "material")) index(material, size_of(materials), ref);
        }
        if (const Value* weights = get(mesh, "weights")) vector(weights, morph_count(mesh), "/meshes/" + std::to_string(i) + "/weights");
    }
    for (std::size_t i = 0; i < size_of(nodes); ++i) {
        const Value& n = nodes->items[i];
        if (const Value* weights = get(n, "weights")) {
            if (!has(n, "mesh")) fail(Code::E_MORPH, "/nodes/" + std::to_string(i), "Node weights need a mesh.");
            vector(weights, morph_count(meshes->items[static_cast<std::size_t>(big(item(n, "mesh")).to_int64())]),
                   "/nodes/" + std::to_string(i) + "/weights");
        }
    }
    for (std::size_t i = 0; i < size_of(skins); ++i) {
        const Value& skin = skins->items[i];
        std::string ref = "/skins/" + std::to_string(i);
        const Value* joints = get(skin, "joints");
        if (!is_list(joints) || joints->items.empty() || !unique_ints(joints)) fail(Code::E_SKIN, ref, "Skin needs unique joint indices.");
        for (const Value& joint : joints->items) index(&joint, size_of(nodes), ref);
        if (const Value* skeleton = get(skin, "skeleton")) index(skeleton, size_of(nodes), ref);
        if (const Value* ibm = get(skin, "inverseBindMatrices")) {
            const Value& a = accessor_at(accessors, ibm, ref);
            if (!str_is(get(a, "type"), "MAT4") || !numeric_equals(get(a, "componentType"), 5126) ||
                big(item(a, "count")) < BigInt(static_cast<long long>(joints->items.size())) || truthy(get(a, "normalized")))
                fail(Code::E_SKIN_TYPE, ref, "Inverse bind accessor must be unnormalized FLOAT MAT4 with at least one matrix per joint.");
        }
    }
    const Value* scenes = get(doc, "scenes");
    for (std::size_t i = 0; i < size_of(scenes); ++i) {
        std::string ref = "/scenes/" + std::to_string(i);
        const Value* roots = get(scenes->items[i], "nodes");
        if (roots && !unique_ints(roots)) fail(Code::E_SCENE, ref, "Scene nodes must be unique indices.");
        for (std::size_t r = 0; r < size_of(roots); ++r) {
            std::size_t root = index(&roots->items[r], size_of(nodes), ref);
            if (parents.count(root)) fail(Code::E_SCENE, ref, "Scene roots cannot have parents.");
        }
    }
    if (const Value* scene = get(doc, "scene")) index(scene, size_of(scenes), "/scene");
    const Value* animations = get(doc, "animations");
    const Value* used = get(doc, "extensionsUsed");
    for (std::size_t i = 0; i < size_of(animations); ++i) {
        const Value& anim = animations->items[i];
        std::string ref = "/animations/" + std::to_string(i);
        const Value* samplers = get(anim, "samplers");
        const Value* channels = get(anim, "channels");
        if (!is_list(samplers) || samplers->items.empty() || !is_list(channels) || channels->items.empty())
            fail(Code::E_ANIMATION, ref, "Animation requires samplers and channels.");
        for (const Value& sampler : samplers->items) {
            if (!is_obj(&sampler)) fail(Code::E_ANIMATION, ref, "Sampler must be an object.");
            const Value& a = accessor_at(accessors, get(sampler, "input"), ref);
            index(get(sampler, "output"), size_of(accessors), ref);
            if (!str_is(get(a, "type"), "SCALAR") || !numeric_equals(get(a, "componentType"), 5126) || !has(a, "min") || !has(a, "max"))
                fail(Code::E_ANIMATION_TYPE, ref, "Animation times require FLOAT SCALAR with min/max.");
            const Value* interpolation = get(sampler, "interpolation");
            if (str_is(interpolation, "CUBICSPLINE") && big(item(a, "count")) < BigInt(2))
                fail(Code::E_ANIMATION_TYPE, ref, "Cubic samplers require at least two input keys.");
            if (interpolation && !str_is(interpolation, "STEP") && !str_is(interpolation, "LINEAR") && !str_is(interpolation, "CUBICSPLINE"))
                fail(Code::E_ANIMATION, ref, "Unknown interpolation.");
        }
        std::set<std::pair<std::string, std::string>> driven;
        for (std::size_t ci = 0; ci < channels->items.size(); ++ci) {
            const Value& channel = channels->items[ci];
            if (!is_obj(&channel) || !is_obj(get(channel, "target"))) fail(Code::E_ANIMATION, ref, "Channel needs a target object.");
            index(get(channel, "sampler"), samplers->items.size(), ref);
            const Value& target = item(channel, "target");
            const Value* path = get(target, "path");
            if (!is_str(path))
                fail(Code::E_TYPE, ref + "/channels/" + std::to_string(ci) + "/target/path", "Animation target path is required and must be a string.");
            const std::string& p = path->text;
            if (p != "translation" && p != "rotation" && p != "scale" && p != "weights") {
                const Value* extensions = get(target, "extensions");
                bool inventoried = false;
                if (is_obj(extensions))
                    for (const auto& member : extensions->members)
                        for (std::size_t u = 0; u < size_of(used); ++u) inventoried = inventoried || used->items[u].text == member.first;
                if (extensions && !is_obj(extensions)) inventoried = false;
                if (!extensions || !inventoried) fail(Code::E_ANIMATION, ref, "Noncore animation path requires an inventoried extension.");
                if (const Value* pointer = get(*extensions, "KHR_animation_pointer")) {
                    const Value* text = get(*pointer, "pointer");
                    if (!is_obj(pointer) || !is_str(text) || text->text.compare(0, 1, "/") != 0)
                        fail(Code::E_ANIMATION, ref, "Animation pointer must declare a JSON structural path.");
                }
                continue;
            }
            if (const Value* node_id = get(target, "node")) {
                const Value& node = nodes->items[index(node_id, size_of(nodes), ref)];
                std::pair<std::string, std::string> pair{node_id->text, p};
                if (driven.count(pair)) fail(Code::E_MULTIPLE_WRITERS, ref, "Animation has competing property channels.");
                driven.insert(pair);
                if (has(node, "matrix") && p != "weights") fail(Code::E_ANIMATION, ref, "TRS animation cannot target a matrix-authored node.");
                animation_layout(doc, samplers->items[static_cast<std::size_t>(big(item(channel, "sampler")).to_int64())], target, ref);
            }
        }
    }
    const Value* images = get(doc, "images");
    for (std::size_t i = 0; i < size_of(images); ++i) {
        const Value& image = images->items[i];
        std::string ref = "/images/" + std::to_string(i);
        if (has(image, "uri") == has(image, "bufferView")) fail(Code::E_IMAGE, ref, "Image requires exactly one URI or bufferView.");
        if (const Value* uri = get(image, "uri")) {
            string_check(uri, ref + "/uri");
        } else {
            index(get(image, "bufferView"), size_of(views), ref);
            string_check(get(image, "mimeType"), ref + "/mimeType");
        }
    }
    validate_skin_hierarchy(doc, parents);
    const Value* textures = get(doc, "textures");
    const Value* samplers = get(doc, "samplers");
    for (std::size_t i = 0; i < size_of(textures); ++i)
        for (const auto& [f, list] : {std::pair{"source", images}, std::pair{"sampler", samplers}})
            if (const Value* v = get(textures->items[i], f)) index(v, size_of(list), "/textures/" + std::to_string(i));
}

}  // namespace msf::gltf
