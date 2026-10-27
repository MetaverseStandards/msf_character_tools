// SPDX-License-Identifier: MIT
// The FBX source adapter on ufbx 0.23.1, as msf_tools.sources.fbx converted
// files in 0.3.0: the same scene walk, node paths, losses and GLB.
#pragma once
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "msf/diagnostics.hpp"

namespace msf::fbx {

struct Options {
    bool top4 = false;                       // influences: "top4" rather than "faithful"
    std::optional<std::string> animation_name;  // options["animation"] when it is a stack name
    long long animation_index = 0;           // otherwise the stack index (0 by default)
    std::optional<double> sample_rate;
    // Python's repr of a str, for messages that quote stack names.
    std::function<std::string(const std::string&)> repr;
};

struct Limits {
    unsigned long long max_reader_memory = 0;
    long long max_animation_values = 0;
    std::string max_animation_values_text;  // as Python prints the limit
};

struct Generated {
    std::string glb;
    std::vector<std::string> node_paths;
    std::vector<std::vector<std::string>> target_keys;
    std::vector<Diagnostic> losses;
};

// The reader rejected the file: SourceParseError with this message.
struct ParseError {
    std::string message;
};
// options["animation"] named no stack; the binding words the refusal with repr(name).
struct NoStack {};

Generated convert(std::string_view data, const Options& options, const Limits& limits, const std::string& generator);
std::string ufbx_version();  // "0.23.1"

// Python's bytes.decode("utf-8", "replace").
std::string decode_replace(std::string_view bytes);

// For tests: the name of one shim call that then reports failure ("" for none).
std::string& failing_call();

}  // namespace msf::fbx
