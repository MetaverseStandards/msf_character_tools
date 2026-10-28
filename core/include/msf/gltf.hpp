// SPDX-License-Identifier: MIT
// glTF 2.0 / GLB inspection as msf_tools.snapshot and gltf_semantics did it in
// 0.3.0: the same checks, codes, refs, messages and order. Documents only ever
// come from JSON here, so values have JSON kinds; integers are exact (BigInt).
#pragma once
#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "msf/bigint.hpp"
#include "msf/diagnostics.hpp"
#include "msf/json.hpp"

namespace msf::gltf {

using json::Value;

// Bytes kept alive by `keep`: a decoded string the core owns, or the caller's
// object (`origin`, opaque to the core) for bytes the caller supplied.
struct Bytes {
    std::string_view view;
    std::shared_ptr<const void> keep;
    const void* origin = nullptr;
    static Bytes own(std::string data);
};

struct DecodeError { std::string text; };   // UnicodeDecodeError or JSONDecodeError on this text: E_INPUT
struct TooDeep {};                          // RecursionError
struct DuplicateKey { std::string key; };   // Fault E_DUPLICATE_KEY, whose message needs Python's repr of the key
struct InternalError { std::string what; }; // an unexpected Python exception, such as struct.error: E_INTERNAL
struct TypeError { std::string what; };     // Python's TypeError: E_INPUT

constexpr long long kMaxAssetBytes = 64LL * 1024 * 1024;
constexpr long long kMaxResourceBytes = 64LL * 1024 * 1024;
constexpr long long kMaxTotalResourceBytes = 256LL * 1024 * 1024;
constexpr long long kMaxAccessorComponents = 1000000;
constexpr long long kMaxTotalAccessorComponents = 4000000;
constexpr long long kMaxStructuralObjects = 100000;
constexpr long long kGeneratedMaxAccessorComponents = 4000000;
constexpr long long kGeneratedMaxTotalAccessorComponents = 16000000;

struct Caps {
    long long accessor = kMaxAccessorComponents, total = kMaxTotalAccessorComponents;
};

struct Chunk {
    std::uint32_t type;
    std::string_view data;  // into the asset's original bytes
};

struct Parsed {
    std::string kind;  // "gltf" or "glb"
    Value doc;
    std::vector<Chunk> chunks;
    bool has_bin = false;
    std::string_view bin;
};

// _parse_asset: the GLB container (when the format is glb, in any case) and
// the JSON document with its core integer slots made exact.
Parsed parse_asset(std::string_view raw, bool glb);
// _data_uri.
Bytes data_uri(const std::string& uri, const std::string& ref);
// _validate_document, gltf_semantics included.
void validate_document(const Value& doc, Caps caps);
// morph_count.
std::size_t morph_count(const Value& mesh);

struct Resource {
    std::string id;  // "/buffers/{i}" or "/images/{i}"
    bool has_uri = false;
    std::string uri;
    Value byte_length;  // an integer: the buffer's declaration, or the image's size
    bool has_data = false;
    Bytes data;
    std::string sha256;  // empty without data
};

struct Asset {
    std::string format;  // "gltf" or "glb"
    Bytes original;
    std::string sha256;
    Value doc;
    std::vector<Chunk> chunks;
    std::vector<Resource> resources;
    bool generated = false;  // converted from a source format
    Caps caps;               // the record's component caps, which decoding uses
};

// Decoded accessor rows. `integers`: the values are Python ints (integer
// components, unnormalized); otherwise floats.
struct Rows {
    std::size_t count = 0, width = 0;
    std::vector<double> values;
    bool integers = false;
    double at(std::size_t row, std::size_t k) const { return values[row * width + k]; }
};

// _decode_accessor; `id` is the caller's index value, `ref` its "/accessors/{id}".
Rows decode_accessor(const Asset& asset, const Value& id, const std::string& ref, bool raw = false);
// validate_bounds with decoded raw rows, or without (nullptr).
void validate_bounds(const Value& accessor, const Rows* rows, const std::string& ref);
// validate_binary: every diagnostic but E_RESOURCE_UNAVAILABLE.
std::vector<Diagnostic> validate_binary(const Asset& asset);
// geometry._animation_times.
std::vector<double> animation_times(const Asset& asset, const Value& accessor_id);
// animation_layout: the component count per key.
std::size_t animation_layout(const Value& doc, const Value& sampler, const Value& target, const std::string& ref);

// A timestamp as Python holds it: an exact int or a float, compared exactly.
struct Time {
    Value value;     // integer or real
    double seconds;  // float(timestamp)
};

struct Sampled {
    bool present = false;  // false for noncore targets
    std::size_t node = 0;
    std::string path;
    std::vector<double> value;
};
// geometry._sample_channel at a valid timestamp.
Sampled sample_channel(const Asset& asset, std::size_t animation, std::size_t channel, const Time& t);

// geometry._sample_animation after its timestamp check: node -> path -> value,
// in insertion order.
using Pose = std::vector<std::pair<std::size_t, std::vector<std::pair<std::string, std::vector<double>>>>>;
Pose sample_animation(const Asset& asset, const Value& animation_id, const Time& t);

// The caller's resolver, called only when the caller supplied one. For a
// buffer URI (image false) it returns the bytes. For an image URI it returns
// the bytes, or std::nullopt when nothing was fetched. For anything else it
// raises a Fault (or the caller's own exception).
using Resolve = std::function<std::optional<Bytes>(const std::string& uri, const std::string& ref, bool image)>;

struct Inspection {
    std::shared_ptr<Asset> asset;
    std::vector<Diagnostic> diagnostics;  // errors, then warnings
};

// _inspect_gltf after its size and resolver checks, up to the sidecar.
Inspection inspect(const Bytes& raw, bool glb, const Resolve* resolver, Caps caps, bool generated);

// One of evaluate_geometry's override mappings: absent (None), not a Mapping,
// or its items in order. A key is an integer Value when it was an exact int.
// The caller's own code can raise while the items are read. Then broken_value
// is the item whose value could not be read (its key is in items), or
// broken_tail says that iteration failed after the last item.
// evaluate_geometry throws OverridesBroken at the point where 0.3.0's loop
// would have met that error.
struct Overrides {
    bool present = false, mapping = false;
    std::vector<std::pair<Value, Value>> items;
    std::optional<std::size_t> broken_value;
    bool broken_tail = false;
};
struct OverridesBroken {
    std::string label;  // "morph_weights" or "node_transforms"
};

struct PrimitivePositions {
    std::size_t primitive = 0;
    std::vector<std::array<double, 3>> positions;
};
struct Instance {
    std::size_t node = 0, mesh = 0;
    std::vector<PrimitivePositions> primitives;
};
struct Geometry {
    std::vector<Instance> instances;
    std::vector<Diagnostic> diagnostics;
    // Witnesses for tests: every node's world matrix (rows), and each skin
    // palette matrix as first built, keyed by joint index.
    std::vector<std::array<std::array<double, 4>, 4>> worlds;
    std::vector<std::pair<long long, std::array<std::array<double, 4>, 4>>> palettes;
};

// evaluate_geometry after its snapshot, timestamp and attributes checks;
// animation_id is nullptr for None, budget caps evaluated components.
Geometry evaluate_geometry(const Asset& asset, const Time& t, const Value* animation_id, const Overrides& morph_weights,
                           const Overrides& node_transforms, long long budget);

}  // namespace msf::gltf
