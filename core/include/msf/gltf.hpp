// SPDX-License-Identifier: MIT
// glTF 2.0 / GLB inspection as msf_tools.snapshot and gltf_semantics did it in
// 0.3.0: the same checks, codes, refs, messages and order. Documents only ever
// come from JSON here, so values have JSON kinds; integers are exact (BigInt).
#pragma once
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

// Bytes owned elsewhere (a Python bytes object, or a decoded string), kept
// alive by `keep`.
struct Bytes {
    std::string_view view;
    std::shared_ptr<const void> keep;
    static Bytes own(std::string data);
};

// Thrown where Python raised something other than a Fault.
struct DecodeError {};                      // UnicodeDecodeError or JSONDecodeError: E_INPUT
struct TooDeep {};                          // RecursionError
struct DuplicateKey { std::string key; };   // Fault E_DUPLICATE_KEY, whose message needs Python's repr of the key
struct InternalError { std::string what; }; // an unexpected Python exception, such as struct.error: E_INTERNAL

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

// _parse_asset: the GLB container (when format is glb, any case) and the JSON
// document with its core integer slots made exact.
Parsed parse_asset(std::string_view raw, const std::string& format);
// _data_uri.
Bytes data_uri(const std::string& uri, const std::string& ref);
// _validate_document, gltf_semantics included.
void validate_document(const Value& doc, Caps caps);
// morph_count.
std::size_t morph_count(const Value& mesh);

struct Resource {
    std::string id;
    bool has_uri = false;
    std::string uri;
    Value byte_length;  // an integer
    bool has_data = false;
    Bytes data;
    std::string sha256;
};

struct Asset {
    std::string format;  // "gltf", "glb" or "profile"
    Bytes original;
    std::string sha256;
    Value doc;
    std::vector<Chunk> chunks;
    std::vector<Resource> resources;
    Value channels, bindings, source;  // object, array, and null unless generated from a source
    Caps caps;
    bool has_source() const { return source.kind == Value::Kind::object; }
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

struct Sampled {
    bool present = false;  // false for noncore targets
    std::size_t node = 0;
    std::string path;
    std::vector<double> value;
};
// geometry._sample_channel at a finite nonnegative timestamp.
Sampled sample_channel(const Asset& asset, std::size_t animation, std::size_t channel, double timestamp);

// The caller's resolver: returns the bytes for a URI, or raises (with a Fault
// or the caller's own exception). Called only when a resolver was supplied.
using Resolve = std::function<Bytes(const std::string& uri, const std::string& ref)>;

struct Inspection {
    Asset asset;
    std::vector<Diagnostic> diagnostics;  // errors, then warnings
};

// _inspect_gltf up to the sidecar: resources, binary checks, animation checks,
// images. `source` is null or the generated snapshot's source record.
Inspection inspect(const Bytes& raw, const std::string& format, const Resolve* resolver, long long max_asset_bytes, Caps caps,
                   Value source);

}  // namespace msf::gltf
