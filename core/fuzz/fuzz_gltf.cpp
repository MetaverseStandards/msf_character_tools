// SPDX-License-Identifier: MIT
// glTF and GLB inspection, then every accessor, every animation and one
// geometry evaluation of whatever is admitted. The first byte picks the
// container and whether a resolver serves the input itself as every external buffer.
#include <cstddef>
#include <cstdint>
#include <string>
#include "fuzz.hpp"

using namespace msf;

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    if (size < 1) return 0;
    const std::uint8_t mode = data[0];
    gltf::Bytes raw = gltf::Bytes::own(std::string(reinterpret_cast<const char*>(data + 1), size - 1));
    gltf::Resolve resolve = [&raw](const std::string&, const std::string&, bool image) -> std::optional<gltf::Bytes> {
        if (image) return std::nullopt;
        return raw;
    };
    gltf::Caps caps{20000, 80000};
    gltf::Inspection inspection;
    if (fuzz::refused([&] { inspection = gltf::inspect(raw, mode & 1, (mode & 2) ? &resolve : nullptr, caps, false); })) return 0;
    for (const auto& d : inspection.diagnostics)
        if (d.severity() == Severity::error) return 0;
    const gltf::Asset& asset = *inspection.asset;
    auto count = [&](const char* key) {
        const json::Value* list = json::find(asset.doc, key);
        return list && list->kind == json::Value::Kind::array ? list->items.size() : 0;
    };
    for (std::size_t i = 0; i < count("accessors"); ++i)
        fuzz::refused([&] { gltf::decode_accessor(asset, json::Value::make_integer(std::to_string(i)), "/accessors/" + std::to_string(i)); });
    gltf::Time t{json::Value::make_real(0.25), 0.25};
    for (std::size_t i = 0; i < count("animations"); ++i)
        fuzz::refused([&] { gltf::sample_animation(asset, json::Value::make_integer(std::to_string(i)), t); });
    json::Value first = json::Value::make_integer("0");
    const json::Value* animation = count("animations") ? &first : nullptr;
    fuzz::refused([&] { gltf::evaluate_geometry(asset, t, animation, {}, {}, 100000); });
    return 0;
}
