// SPDX-License-Identifier: MIT
// Source node paths and target keys: parsing either refuses or round-trips
// exactly, escaping round-trips, and the sort order is antisymmetric.
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <optional>
#include <string>
#include <string_view>
#include "msf/paths.hpp"

using namespace msf::paths;

static void check(bool ok) {
    if (!ok) std::abort();
}

static std::optional<NodePath> parsed(std::string_view text) {
    try {
        NodePath path = parse_node_path(text);
        check(node_path(path.components, path.helper) == text);
        return path;
    } catch (const Error&) {
        return std::nullopt;
    }
}

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    std::string_view text(reinterpret_cast<const char*>(data), size);
    check(unescape(escape(text)) == text);
    try {
        check(target_key(parse_target_key(text)) == text);
    } catch (const Error&) {
    }
    std::size_t half = size / 2;
    auto a = parsed(text.substr(0, half)), b = parsed(text.substr(half));
    if (a && b) {
        int ab = compare(*a, *b), ba = compare(*b, *a);
        check((ab < 0) == (ba > 0) && (ab == 0) == (ba == 0));
    }
    return 0;
}
