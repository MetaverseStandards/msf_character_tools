// SPDX-License-Identifier: MIT
// The source path grammar path-sorted-v2, as msf_tools.sources.paths defined
// it in 0.3.0. Strings are WTF-8; every special character is ASCII, so byte
// order is code point order.
#pragma once
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace msf::paths {

// A refusal: `kind` names the reference's ValueError message, `text` is what it quoted.
// escape: "Bad or unnecessary escape in {text!r}."   unescaped: "Unescaped special character in {text!r}."
// component: "Malformed path component {text!r}."    start: "Node path must start with '/': {text!r}."
// helper: "Malformed helper suffix in {text!r}."      kind: "Unknown helper kind {text!r}."
struct Error {
    std::string kind, text;
};

struct Component {
    std::string name;
    std::optional<std::string> k;  // the duplicate index's decimal digits
};

struct NodePath {
    std::vector<Component> components;
    std::optional<Component> helper;  // name is the helper kind
};

std::string escape(std::string_view name);
std::string unescape(std::string_view text);
std::string node_path(const std::vector<Component>& components, const std::optional<Component>& helper = std::nullopt);
NodePath parse_node_path(std::string_view path);
std::string target_key(const std::vector<Component>& components);
std::vector<Component> parse_target_key(std::string_view key);
// Python's comparison of the reference's sort_key tuples: negative, zero or positive.
int compare(const NodePath& a, const NodePath& b);

}  // namespace msf::paths
