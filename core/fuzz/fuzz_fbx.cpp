// SPDX-License-Identifier: MIT
// FBX conversion through ufbx and the adapter, then inspection of the GLB it
// generates. The first byte picks the options.
#include <cstddef>
#include <cstdint>
#include <string>
#include "fuzz.hpp"
#include "msf/fbx.hpp"

using namespace msf;

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    if (size < 1) return 0;
    const std::uint8_t mode = data[0];
    fbx::Options options;
    options.top4 = mode & 1;
    if (mode & 2) options.animation_name = "Take 001";
    else options.animation_index = (mode >> 2) & 1;
    if (mode & 8) options.sample_rate = 7.5;
    options.repr = [](const std::string& text) { return "'" + text + "'"; };
    fbx::Limits limits;
    limits.max_reader_memory = 256ull << 20;
    limits.max_animation_values = 200000;
    limits.max_animation_values_text = "200000";
    fbx::Generated generated;
    try {
        if (fuzz::refused([&] {
                generated = fbx::convert(std::string_view(reinterpret_cast<const char*>(data + 1), size - 1), options, limits, "msf-ufbx 1");
            }))
            return 0;
    } catch (const fbx::ParseError&) {
        return 0;
    } catch (const fbx::NoStack&) {
        return 0;
    }
    gltf::Caps caps{gltf::kGeneratedMaxAccessorComponents, gltf::kGeneratedMaxTotalAccessorComponents};
    gltf::Inspection inspection;
    if (fuzz::refused([&] { inspection = gltf::inspect(gltf::Bytes::own(std::move(generated.glb)), true, nullptr, caps, true); })) return 0;
    // The adapter's GLB is admitted unchanged, so it must inspect cleanly.
    for (const auto& d : inspection.diagnostics)
        if (d.severity() == Severity::error) {
            std::fprintf(stderr, "generated GLB refused: %s %s %s\n", info(d.code).name, d.ref.c_str(), d.message.c_str());
            std::abort();
        }
    return 0;
}
