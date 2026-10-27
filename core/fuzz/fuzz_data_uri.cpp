// SPDX-License-Identifier: MIT
// data: URIs as buffers and images give them. An odd first byte prefixes a
// base64 header so the decoder sees most inputs.
#include <cstddef>
#include <cstdint>
#include <string>
#include "fuzz.hpp"

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    if (size < 1) return 0;
    std::string uri(reinterpret_cast<const char*>(data + 1), size - 1);
    if (data[0] & 1) uri = "data:application/octet-stream;base64," + uri;
    msf::fuzz::refused([&] { msf::gltf::data_uri(uri, "/buffers/0"); });
    return 0;
}
