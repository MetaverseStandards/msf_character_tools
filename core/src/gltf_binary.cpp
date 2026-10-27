// SPDX-License-Identifier: MIT
// Accessor decoding, bounds and binary checks, animation sampling and the
// inspection pipeline, as snapshot, gltf_semantics and geometry ran them.
#include <algorithm>
#include <cmath>
#include <cstring>
#include <set>
#include <unordered_set>

#include "gltf_detail.hpp"
#include "msf/math3d.hpp"
#include "msf/sha256.hpp"

namespace msf::gltf {

using namespace detail;
namespace m3 = msf::math3d;

namespace {

bool unavailable(const Fault& fault) { return fault.diagnostic().code == Code::E_RESOURCE_UNAVAILABLE; }

double read_component(const char* at, char code) {
    switch (code) {
        case 'b': { std::int8_t v; std::memcpy(&v, at, 1); return v; }
        case 'B': { std::uint8_t v; std::memcpy(&v, at, 1); return v; }
        case 'h': { std::int16_t v; std::memcpy(&v, at, 2); return v; }
        case 'H': { std::uint16_t v; std::memcpy(&v, at, 2); return v; }
        case 'I': { std::uint32_t v; std::memcpy(&v, at, 4); return v; }
        default: { float v; std::memcpy(&v, at, 4); return v; }
    }
}

// snapshot._read_elements, appending count rows of l.offsets.size() values.
void read_elements(const Asset& asset, const Value* view_id, const BigInt& offset, const BigInt& count, const Layout& l, bool mat,
                   bool normalized, const std::string& ref, bool sparse, std::vector<double>& out) {
    const Value* views = get(asset.doc, "bufferViews");
    const Value& view = views->items[index(view_id, size_of(views), ref)];
    const Resource& resource = asset.resources[static_cast<std::size_t>(big(item(view, "buffer")).to_int64())];
    if (!resource.has_data)
        fail(Code::E_RESOURCE_UNAVAILABLE, ref, "Accessor needs an unresolved external buffer.", "Supply an explicit bounded LocalResolver.");
    BigInt stride = int_or(view, "byteStride", l.element_size);
    if (sparse && has(view, "byteStride")) fail(Code::E_SPARSE_STRIDE, ref, "Sparse views cannot declare byteStride.");
    if (stride < BigInt(l.element_size) || stride.mod(l.size)) fail(Code::E_ACCESSOR_STRIDE, ref, "Stride is smaller than an element or misaligned.");
    BigInt start = int_or(view, "byteOffset", 0) + offset;
    if (offset.mod(l.size) || start.mod(l.size) || (mat && start.mod(4)))
        fail(Code::E_ACCESSOR_ALIGNMENT, ref, "Accessor start violates component/matrix alignment.");
    BigInt end = count.zero() ? offset : offset + (count - BigInt(1)) * stride + BigInt(l.element_size);
    if (end > big(item(view, "byteLength"))) fail(Code::E_ACCESSOR_BOUNDS, ref, "Accessor exceeds its bufferView.");
    // The view lies inside its buffer and consumed data is never shorter than
    // the buffer, so these fit; a shortfall is the reference's struct.error.
    const std::string_view data = resource.data.view;
    if (!start.fits_int64() || !stride.fits_int64() || !count.fits_int64()) throw InternalError{"error: unpack_from out of range"};
    long long base = start.to_int64(), step = stride.to_int64(), n = count.to_int64();
    double divisor = l.component_type == 5120 ? 127 : l.component_type == 5122 ? 32767 : l.component_type == 5121 ? 255 : 65535;
    bool signed_type = l.component_type == 5120 || l.component_type == 5122;
    out.reserve(out.size() + static_cast<std::size_t>(n) * l.offsets.size());
    for (long long i = 0; i < n; ++i)
        for (long long component : l.offsets) {
            long long at = base + i * step + component;
            if (at < 0 || static_cast<unsigned long long>(at) + static_cast<unsigned long long>(l.size) > data.size())
                throw InternalError{"error: unpack_from requires a buffer of at least " + std::to_string(at + l.size) + " bytes"};
            double v = read_component(data.data() + at, l.code);
            if (!std::isfinite(v)) fail(Code::E_NONFINITE, ref, "Binary accessor contains NaN or infinity.");
            if (normalized) v = signed_type ? std::max(v / divisor, -1.0) : v / divisor;
            out.push_back(v);
        }
}

bool is_mat(const Value& accessor) { return item(accessor, "type").text.compare(0, 3, "MAT") == 0; }

}  // namespace

Rows decode_accessor(const Asset& asset, const Value& id, const std::string& ref, bool raw) {
    const Value* accessors = get(asset.doc, "accessors");
    const Value& a = accessors->items[index(&id, size_of(accessors), ref)];
    Layout l = layout(a);
    BigInt count = big(item(a, "count"));
    if (count * BigInt(static_cast<long long>(l.offsets.size())) > BigInt(asset.caps.accessor))
        fail(Code::E_RESOURCE_LIMIT, ref, "Accessor exceeds the decoded component budget.");
    bool normalized = is_true(get(a, "normalized"));
    Rows rows;
    rows.count = static_cast<std::size_t>(count.to_int64());
    rows.width = l.offsets.size();
    rows.integers = l.component_type != 5126 && !normalized;
    if (const Value* view = get(a, "bufferView"))
        read_elements(asset, view, int_or(a, "byteOffset", 0), count, l, is_mat(a), normalized && !raw, ref, false, rows.values);
    else
        rows.values.assign(rows.count * rows.width, 0.0);
    if (const Value* sp = get(a, "sparse")) {
        const Value& ix = item(*sp, "indices");
        BigInt sparse_count = big(item(*sp, "count"));
        Layout index_layout = layout(big(item(ix, "componentType")).to_int64(), "SCALAR");
        std::vector<double> indices, values;
        read_elements(asset, get(ix, "bufferView"), int_or(ix, "byteOffset", 0), sparse_count, index_layout, false, false,
                      ref + "/sparse/indices", true, indices);
        const Value& vals = item(*sp, "values");
        read_elements(asset, get(vals, "bufferView"), int_or(vals, "byteOffset", 0), sparse_count, l, is_mat(a), normalized && !raw,
                      ref + "/sparse/values", true, values);
        double last = -1;
        for (std::size_t k = 0; k < indices.size(); ++k) {
            double i = indices[k];
            if (i <= last || i >= static_cast<double>(rows.count))
                fail(Code::E_SPARSE_INDEX, ref, "Sparse indices must be strictly increasing and in range.");
            std::copy(values.begin() + static_cast<std::ptrdiff_t>(k * rows.width), values.begin() + static_cast<std::ptrdiff_t>((k + 1) * rows.width),
                      rows.values.begin() + static_cast<std::ptrdiff_t>(static_cast<std::size_t>(i) * rows.width));
            last = i;
        }
    }
    return rows;
}

void validate_bounds(const Value& a, const Rows* rows, const std::string& ref) {
    long long ct = big(item(a, "componentType")).to_int64();
    for (const char* name : {"min", "max"}) {
        const Value* bound = get(a, name);
        if (!bound) continue;
        bool is_min = name[1] == 'i';
        std::vector<double> values;
        if (ct == 5126) {
            for (const Value& v : bound->items) {
                float f;
                if (!json::to_float32(v.number, f)) fail(Code::E_ACCESSOR_DOMAIN, ref, "Accessor bounds cannot be represented by component type.");
                values.push_back(f);
            }
        } else {
            long long lo = 0, hi = 0;
            switch (ct) {
                case 5120: lo = -128; hi = 127; break;
                case 5121: hi = 255; break;
                case 5122: lo = -32768; hi = 32767; break;
                case 5123: hi = 65535; break;
                default: hi = 4294967295LL; break;
            }
            for (const Value& v : bound->items) {
                if (v.kind != Kind::integer || big(v) < BigInt(lo) || big(v) > BigInt(hi))
                    fail(Code::E_ACCESSOR_DOMAIN, ref, "Integer bounds must be raw integral component values.");
                values.push_back(static_cast<double>(big(v).to_int64()));
            }
        }
        if (!rows) continue;
        for (std::size_t k = 0; k < values.size(); ++k) {
            double extreme = rows->at(0, k);
            for (std::size_t r = 1; r < rows->count; ++r) extreme = is_min ? std::min(extreme, rows->at(r, k)) : std::max(extreme, rows->at(r, k));
            if (extreme != values[k])
                fail(Code::E_ACCESSOR_DOMAIN, ref, "Declared bounds must exactly match component-rounded extrema after sparse overrides.");
        }
    }
}

std::vector<Diagnostic> validate_binary(const Asset& asset) {
    std::vector<Diagnostic> errors;
    auto attempt = [&](auto&& fn) {
        try {
            fn();
        } catch (const Fault& fault) {
            if (!unavailable(fault)) errors.push_back(fault.diagnostic());
        }
    };
    const Value& doc = asset.doc;
    const Value* accessors = get(doc, "accessors");
    const Value* meshes = get(doc, "meshes");
    const Value* nodes = get(doc, "nodes");
    auto decode = [&](const Value& id, bool raw = false) { return decode_accessor(asset, id, "/accessors/" + id.text, raw); };
    for (std::size_t mi = 0; mi < size_of(meshes); ++mi) {
        const Value& primitives = item(meshes->items[mi], "primitives");
        for (std::size_t pi = 0; pi < primitives.items.size(); ++pi) {
            const Value& p = primitives.items[pi];
            std::string ref = "/meshes/" + std::to_string(mi) + "/primitives/" + std::to_string(pi);
            const Value& attrs = item(p, "attributes");
            auto accessor = [&](const Value& id) -> const Value& { return accessors->items[static_cast<std::size_t>(big(id).to_int64())]; };
            const Value& first_count = item(accessor(attrs.members.front().second), "count");
            attempt([&] {
                const Value* ix = get(p, "indices");
                if (!ix) return;
                long long ct = big(item(accessor(*ix), "componentType")).to_int64();
                double maximum = ct == 5121 ? 255 : ct == 5123 ? 65535 : 4294967295.0;
                double count = static_cast<double>(big(first_count).to_int64());
                Rows rows = decode(*ix);
                for (double i : rows.values)
                    if (i >= count || i == maximum)
                        fail(Code::E_INDEX_BOUNDS, ref, "Index must reference a vertex and must not equal reserved component maximum.");
            });
            for (const auto& [name, aid] : attrs.members)
                attempt([&, &name = name, &aid = aid] {
                    Rows rows = decode(aid);
                    if (name == "TANGENT")
                        for (std::size_t r = 0; r < rows.count; ++r)
                            if (std::fabs(rows.at(r, 3)) != 1) fail(Code::E_TANGENT, ref, "TANGENT W must be exactly -1 or +1.");
                    if (name == "COLOR_0")
                        for (double x : rows.values)
                            if (!(0 <= x && x <= 1)) fail(Code::E_COLOR, ref, "COLOR_0 components must be in [0,1].");
                });
            attempt([&] {
                std::vector<long long> sets;
                for (const auto& member : attrs.members)
                    if (member.first.compare(0, 7, "JOINTS_") == 0) sets.push_back(std::stoll(member.first.substr(7)));
                if (sets.empty()) return;
                std::sort(sets.begin(), sets.end());
                auto available = [&](const std::string& name, bool raw) -> std::optional<Rows> {
                    try {
                        return decode(item(attrs, name), raw);
                    } catch (const Fault& fault) {
                        if (!unavailable(fault)) throw;
                        return std::nullopt;
                    }
                };
                std::vector<std::optional<Rows>> weights, raw_weights, joints;
                std::vector<long long> weight_types;
                for (long long s : sets) weights.push_back(available("WEIGHTS_" + std::to_string(s), false));
                for (long long s : sets)
                    weight_types.push_back(big(item(accessor(item(attrs, "WEIGHTS_" + std::to_string(s))), "componentType")).to_int64());
                for (long long s : sets) raw_weights.push_back(available("WEIGHTS_" + std::to_string(s), true));
                for (const auto& rows : weights)
                    if (rows)
                        for (double w : rows->values)
                            if (w < 0) fail(Code::E_SKIN_WEIGHTS, ref, "Skin weights must be nonnegative.");
                for (long long s : sets) joints.push_back(available("JOINTS_" + std::to_string(s), false));
                std::vector<double> palettes;
                const Value* skins = get(doc, "skins");
                for (std::size_t n = 0; n < size_of(nodes); ++n) {
                    const Value& node = nodes->items[n];
                    if (numeric_equals(get(node, "mesh"), static_cast<long long>(mi)) && has(node, "skin"))
                        palettes.push_back(static_cast<double>(
                            item(skins->items[static_cast<std::size_t>(big(item(node, "skin")).to_int64())], "joints").items.size()));
                }
                std::size_t count = static_cast<std::size_t>(big(first_count).to_int64());
                bool all_weights = std::all_of(weights.begin(), weights.end(), [](const auto& r) { return r.has_value(); });
                bool integer_sum = std::all_of(weight_types.begin(), weight_types.end(), [&](long long t) { return t == weight_types[0]; }) &&
                                   (weight_types[0] == 5121 || weight_types[0] == 5123);
                for (std::size_t vi = 0; vi < count; ++vi) {
                    for (const auto& rows : joints)
                        if (rows)
                            for (double size : palettes)
                                for (std::size_t k = 0; k < rows->width; ++k)
                                    if (rows->at(vi, k) >= size) fail(Code::E_JOINT_BOUNDS, ref, "Joint index exceeds referencing skin palette.");
                    std::vector<double> positive;
                    for (std::size_t s = 0; s < joints.size(); ++s)
                        if (joints[s] && weights[s])
                            for (std::size_t k = 0; k < std::min(joints[s]->width, weights[s]->width); ++k)
                                if (weights[s]->at(vi, k) > 0) positive.push_back(joints[s]->at(vi, k));
                    if (std::set<double>(positive.begin(), positive.end()).size() != positive.size())
                        fail(Code::E_SKIN_WEIGHTS, ref, "A vertex must not have duplicate positive joint weights.");
                    if (!all_weights) continue;
                    bool valid;
                    if (integer_sum) {
                        double total = 0;
                        for (const auto& rows : raw_weights)
                            for (std::size_t k = 0; k < rows->width; ++k) total += rows->at(vi, k);
                        valid = total == (weight_types[0] == 5121 ? 255 : 65535);
                    } else {
                        double total = 0;
                        for (const auto& rows : weights)
                            for (std::size_t k = 0; k < rows->width; ++k) total += rows->at(vi, k);
                        valid = std::fabs(total - 1) <= 1e-6;
                    }
                    if (!valid)
                        fail(Code::E_SKIN_WEIGHTS, ref, "Weight sum violates raw integer or project floating sum policy; no implicit normalization.");
                }
            });
        }
    }
    const Value* skins = get(doc, "skins");
    for (std::size_t si = 0; si < size_of(skins); ++si)
        attempt([&] {
            const Value* ibm = get(skins->items[si], "inverseBindMatrices");
            if (!ibm) return;
            Rows rows = decode(*ibm);
            for (std::size_t r = 0; r < rows.count; ++r)
                if (rows.at(r, 3) != 0 || rows.at(r, 7) != 0 || rows.at(r, 11) != 0 || rows.at(r, 15) != 1)
                    fail(Code::E_SKIN_TYPE, "/skins/" + std::to_string(si),
                         "Every inverse bind matrix including extras must have affine fourth row [0,0,0,1].");
        });
    return errors;
}

std::vector<double> animation_times(const Asset& asset, const Value& accessor_id) {
    Rows rows = decode_accessor(asset, accessor_id, "/accessors/" + accessor_id.text);
    std::vector<double> times(rows.values.begin(), rows.values.end());
    for (double t : times)
        if (t < 0) fail(Code::E_ANIMATION_TIME, "/animations", "Animation times must be nonnegative and strictly increasing.");
    for (std::size_t i = 1; i < times.size(); ++i)
        if (times[i - 1] >= times[i]) fail(Code::E_ANIMATION_TIME, "/animations", "Animation times must be nonnegative and strictly increasing.");
    return times;
}

namespace {

// Python's timestamp < t, exactly for an int timestamp.
int compare_time(const Time& ts, double t) {
    if (ts.value.kind == Kind::real) return ts.seconds < t ? -1 : ts.seconds > t ? 1 : 0;
    return json::compare_numbers(ts.value, Value::make_real(t));
}

void check_values(const m3::Vec& value) {
    for (double x : value)
        if (!std::isfinite(x)) fail(Code::E_NONFINITE, "/animations", "Animation result is not finite.");
}

}  // namespace

Sampled sample_channel(const Asset& asset, std::size_t animation_id, std::size_t channel_id, const Time& ts) {
    const Value& doc = asset.doc;
    const Value& anim = item(doc, "animations").items[animation_id];
    const Value& channel = item(anim, "channels").items[channel_id];
    const Value& target = item(channel, "target");
    const std::string& path = item(target, "path").text;
    Sampled out;
    if (!has(target, "node") || (path != "translation" && path != "rotation" && path != "scale" && path != "weights")) return out;
    std::string ref = "/animations/" + std::to_string(animation_id) + "/channels/" + std::to_string(channel_id);
    const Value& sampler = item(anim, "samplers").items[static_cast<std::size_t>(big(item(channel, "sampler")).to_int64())];
    std::size_t count = animation_layout(doc, sampler, target, ref);
    const Value* interpolation_value = get(sampler, "interpolation");
    std::string interpolation = interpolation_value ? interpolation_value->text : "LINEAR";
    const Value& output = item(sampler, "output");
    Rows decoded = decode_accessor(asset, output, "/accessors/" + output.text);
    std::size_t width = path == "weights" ? count : decoded.width;
    std::size_t row_count = decoded.values.size() / width;
    auto row = [&](std::size_t i) { return m3::Vec(decoded.values.begin() + static_cast<std::ptrdiff_t>(i * width),
                                                   decoded.values.begin() + static_cast<std::ptrdiff_t>((i + 1) * width)); };
    bool cubic = interpolation == "CUBICSPLINE";
    // values = rows[1::3] for cubic samplers, else rows
    std::size_t value_count = cubic ? (row_count + 1) / 3 : row_count;
    auto value_at = [&](std::size_t i) { return row(cubic ? 3 * i + 1 : i); };
    if (path == "rotation")
        for (std::size_t i = 0; i < value_count; ++i) m3::check_authored_quaternion(value_at(i), "/animations");
    std::vector<double> times = animation_times(asset, item(sampler, "input"));
    m3::Vec value;
    if (compare_time(ts, times.front()) <= 0) {
        value = value_at(0);
    } else if (compare_time(ts, times.back()) >= 0) {
        value = value_at(value_count - 1);
    } else {
        std::size_t lo = 0, hi = times.size();
        while (lo < hi) {
            std::size_t mid = (lo + hi) / 2;
            if (compare_time(ts, times[mid]) < 0) hi = mid;
            else lo = mid + 1;
        }
        std::size_t i = lo - 1;
        if (interpolation == "STEP") {
            value = value_at(i);
        } else {
            double dt = m3::sub(times[i + 1], times[i], "/animations");
            double t = m3::divide(m3::sub(ts.seconds, times[i], "/animations"), dt, "/animations");
            if (interpolation == "LINEAR") {
                if (path == "rotation") {
                    m3::Vec a = m3::normalize(value_at(i));
                    m3::Vec b = m3::normalize(value_at(i + 1));
                    value = m3::slerp(a, b, m3::fraction(t));
                } else {
                    value = m3::linear(value_at(i), value_at(i + 1), m3::fraction(t));
                }
            } else {
                value = m3::hermite(row(3 * i + 1), row(3 * i + 2), row(3 * (i + 1) + 1), row(3 * (i + 1)), m3::fraction(t),
                                    m3::finite(dt, "/animations"), false);
            }
        }
    }
    if (path == "rotation") value = m3::normalize(value);
    check_values(value);
    out.present = true;
    out.node = static_cast<std::size_t>(big(item(target, "node")).to_int64());
    out.path = path;
    out.value = std::move(value);
    return out;
}

Pose sample_animation(const Asset& asset, const Value& animation_id, const Time& ts) {
    const Value* animations = get(asset.doc, "animations");
    std::size_t a = index(&animation_id, size_of(animations), "/animations");
    Pose pose;
    std::size_t channels = item(animations->items[a], "channels").items.size();
    for (std::size_t c = 0; c < channels; ++c) {
        Sampled s = sample_channel(asset, a, c, ts);
        if (!s.present) continue;
        auto node = std::find_if(pose.begin(), pose.end(), [&](const auto& entry) { return entry.first == s.node; });
        if (node == pose.end()) {
            pose.push_back({s.node, {}});
            node = pose.end() - 1;
        }
        auto slot = std::find_if(node->second.begin(), node->second.end(), [&](const auto& entry) { return entry.first == s.path; });
        if (slot == node->second.end()) node->second.push_back({s.path, std::move(s.value)});
        else slot->second = std::move(s.value);
    }
    return pose;
}

Inspection inspect(const Bytes& raw, bool glb, const Resolve* resolver, Caps caps, bool generated) {
    Parsed parsed = parse_asset(raw.view, glb);
    validate_document(parsed.doc, caps);
    auto asset = std::make_shared<Asset>();
    asset->format = parsed.kind;
    asset->original = raw;
    asset->sha256 = sha256_hex(raw.view);
    asset->chunks = parsed.chunks;
    asset->generated = generated;
    if (generated) asset->caps = Caps{kGeneratedMaxAccessorComponents, kGeneratedMaxTotalAccessorComponents};
    asset->doc = std::move(parsed.doc);
    const Value& doc = asset->doc;
    std::vector<Diagnostic> errors, warnings;
    long long consumed = 0;
    const Value* buffers = get(doc, "buffers");
    for (std::size_t i = 0; i < size_of(buffers); ++i) {
        const Value& b = buffers->items[i];
        std::string ref = "/buffers/" + std::to_string(i);
        const Value* uri = get(b, "uri");
        const BigInt length = big(item(b, "byteLength"));
        std::optional<Bytes> data;
        if (!uri) {
            if (!glb || i != 0 || !parsed.has_bin) fail(Code::E_RESOURCE, ref, "Buffer without URI needs the first GLB BIN chunk.");
            BigInt bin_size(static_cast<long long>(parsed.bin.size()));
            bool padded = length <= bin_size && bin_size <= length + BigInt(3);
            if (padded) {
                std::size_t used = static_cast<std::size_t>(length.to_int64());
                padded = std::all_of(parsed.bin.begin() + static_cast<std::ptrdiff_t>(used), parsed.bin.end(), [](char c) { return c == 0; });
                if (padded) data = Bytes{parsed.bin.substr(0, used), raw.keep, nullptr};
            }
            if (!padded) fail(Code::E_GLB_PADDING, ref, "BIN length or zero padding violates declared buffer length.");
        } else if (uri->text.compare(0, 5, "data:") == 0) {
            data = data_uri(uri->text, ref);
        } else if (resolver) {
            data = (*resolver)(uri->text, ref, false);
        } else {
            warnings.push_back({Code::W_RESOURCE_UNCONSUMED, ref, "External resource inventoried without fetching.",
                                "Supply a bounded local resolver to evaluate its accessors."});
        }
        Resource r{ref, uri != nullptr, uri ? uri->text : std::string(), item(b, "byteLength"), data.has_value(), {}, {}};
        if (data) {
            long long size = static_cast<long long>(data->view.size());
            consumed += size;
            if (size > kMaxResourceBytes || consumed > kMaxTotalResourceBytes)
                fail(Code::E_RESOURCE_LIMIT, ref, "Consumed resource exceeds byte budget.");
            if (BigInt(size) < length) fail(Code::E_BUFFER_BOUNDS, ref, "Consumed buffer is shorter than byteLength.");
            r.sha256 = sha256_hex(data->view);
            r.data = std::move(*data);
        }
        asset->resources.push_back(std::move(r));
    }
    const Value* accessors = get(doc, "accessors");
    for (std::size_t i = 0; i < size_of(accessors); ++i) {
        const Value& a = accessors->items[i];
        // Spec1509: descriptors without base or sparse data may declare
        // arbitrary representable bounds.
        if (!has(a, "bufferView") && !has(a, "sparse")) continue;
        std::string ref = "/accessors/" + std::to_string(i);
        try {
            Rows rows = decode_accessor(*asset, Value::make_integer(std::to_string(i)), ref, true);
            validate_bounds(a, &rows, ref);
        } catch (const Fault& fault) {
            if (!unavailable(fault)) errors.push_back(fault.diagnostic());
        }
    }
    for (Diagnostic& d : validate_binary(*asset)) errors.push_back(std::move(d));
    const Value* animations = get(doc, "animations");
    const Time zero{Value::make_real(0.0), 0.0};
    for (std::size_t i = 0; i < size_of(animations); ++i) {
        const Value& anim = animations->items[i];
        for (const Value& sampler : item(anim, "samplers").items) {
            try {
                animation_times(*asset, item(sampler, "input"));
            } catch (const Fault& fault) {
                if (!unavailable(fault)) errors.push_back(fault.diagnostic());
            }
        }
        for (std::size_t c = 0; c < item(anim, "channels").items.size(); ++c) {
            try {
                sample_channel(*asset, i, c, zero);
            } catch (const Fault& fault) {
                if (!unavailable(fault)) errors.push_back(fault.diagnostic());
            }
        }
    }
    const Value* images = get(doc, "images");
    for (std::size_t i = 0; i < size_of(images); ++i) {
        const Value* uri = get(images->items[i], "uri");
        if (!uri) continue;
        std::string ref = "/images/" + std::to_string(i);
        std::optional<Bytes> data;
        if (uri->text.compare(0, 5, "data:") == 0) data = data_uri(uri->text, ref);
        else if (resolver) data = (*resolver)(uri->text, ref, true);
        Resource r{ref, true, uri->text, Value::make_integer("0"), data.has_value(), {}, {}};
        if (data) {
            long long size = static_cast<long long>(data->view.size());
            consumed += size;
            if (size > kMaxResourceBytes || consumed > kMaxTotalResourceBytes)
                fail(Code::E_RESOURCE_LIMIT, ref, "Consumed image exceeds byte budget.");
            r.byte_length = Value::make_integer(std::to_string(size));
            r.sha256 = sha256_hex(data->view);
            r.data = std::move(*data);
        }
        asset->resources.push_back(std::move(r));
    }
    for (Diagnostic& d : warnings) errors.push_back(std::move(d));
    return Inspection{asset, std::move(errors)};
}

}  // namespace msf::gltf
