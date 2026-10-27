// SPDX-License-Identifier: MIT
#include "msf/paths.hpp"

namespace msf::paths {

namespace {

bool special(unsigned char c) { return c == '%' || c == '/' || c == '#' || c == '[' || c == ']' || c == ':' || c < 0x20 || c == 0x7f; }
bool upper_hex(char c) { return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F'); }
int hex_value(char c) { return c <= '9' ? c - '0' : c - 'A' + 10; }

// (?:0|[1-9][0-9]*)
bool index_digits(std::string_view s) {
    if (s.empty() || (s[0] == '0' && s.size() > 1)) return false;
    for (char c : s)
        if (c < '0' || c > '9') return false;
    return true;
}

// (?P<text>[^\[\]]*)(?:\[(?P<k>0|[1-9][0-9]*)\])?
Component parse_component(std::string_view text) {
    std::size_t bracket = text.find_first_of("[]");
    Component out;
    if (bracket != std::string_view::npos) {
        std::string_view rest = text.substr(bracket);
        if (rest.size() < 3 || rest.front() != '[' || rest.back() != ']' || !index_digits(rest.substr(1, rest.size() - 2)))
            throw Error{"component", std::string(text)};
        out.k = std::string(rest.substr(1, rest.size() - 2));
    }
    out.name = unescape(text.substr(0, bracket));
    return out;
}

std::string component(const Component& c) { return escape(c.name) + (c.k ? "[" + *c.k + "]" : std::string()); }

std::vector<Component> parse_components(std::string_view joined) {
    std::vector<Component> out;
    std::size_t start = 0;
    while (true) {
        std::size_t slash = joined.find('/', start);
        out.push_back(parse_component(joined.substr(start, slash == std::string_view::npos ? std::string_view::npos : slash - start)));
        if (slash == std::string_view::npos) return out;
        start = slash + 1;
    }
}

// Python's int comparison of two optional indices, None counting as -1.
int compare_index(const std::optional<std::string>& a, const std::optional<std::string>& b) {
    if (!a || !b) return (a ? 1 : 0) - (b ? 1 : 0);
    if (a->size() != b->size()) return a->size() < b->size() ? -1 : 1;
    int c = a->compare(*b);
    return c < 0 ? -1 : c > 0 ? 1 : 0;
}

int compare_component(const Component& a, const Component& b) {
    int c = a.name.compare(b.name);
    if (c) return c < 0 ? -1 : 1;
    return compare_index(a.k, b.k);
}

}  // namespace

std::string escape(std::string_view name) {
    static const char* hex = "0123456789ABCDEF";
    std::string out;
    for (char ch : name) {
        unsigned char c = static_cast<unsigned char>(ch);
        if (special(c)) {
            out += '%';
            out += hex[c >> 4];
            out += hex[c & 15];
        } else {
            out += ch;
        }
    }
    return out;
}

std::string unescape(std::string_view text) {
    std::string out;
    for (std::size_t i = 0; i < text.size();) {
        unsigned char c = static_cast<unsigned char>(text[i]);
        if (c == '%') {
            if (i + 3 > text.size() || !upper_hex(text[i + 1]) || !upper_hex(text[i + 2])) throw Error{"escape", std::string(text)};
            unsigned char decoded = static_cast<unsigned char>(hex_value(text[i + 1]) * 16 + hex_value(text[i + 2]));
            if (!special(decoded)) throw Error{"escape", std::string(text)};
            out += static_cast<char>(decoded);
            i += 3;
        } else if (special(c)) {
            throw Error{"unescaped", std::string(text)};
        } else {
            out += text[i];
            i += 1;
        }
    }
    return out;
}

std::string node_path(const std::vector<Component>& components, const std::optional<Component>& helper) {
    std::string path = "/";
    for (std::size_t i = 0; i < components.size(); ++i) {
        if (i) path += '/';
        path += component(components[i]);
    }
    if (helper) {
        if (helper->name != "geometry" && helper->name != "scale") throw Error{"kind", helper->name};
        path += "#helper:" + helper->name + (helper->k ? "[" + *helper->k + "]" : std::string());
    }
    return path;
}

NodePath parse_node_path(std::string_view path) {
    if (path.empty() || path[0] != '/') throw Error{"start", std::string(path)};
    std::size_t hash = path.find('#');
    NodePath out;
    if (hash != std::string_view::npos) {
        // helper:(?P<kind>geometry|scale)(?:\[(?P<k>0|[1-9][0-9]*)\])?
        std::string_view suffix = path.substr(hash + 1);
        Component helper;
        bool ok = suffix.compare(0, 7, "helper:") == 0;
        if (ok) {
            std::string_view rest = suffix.substr(7);
            for (const char* kind : {"geometry", "scale"})
                if (rest.compare(0, std::char_traits<char>::length(kind), kind) == 0) helper.name = kind;
            rest.remove_prefix(helper.name.size());
            ok = !helper.name.empty();
            if (ok && !rest.empty()) {
                ok = rest.size() >= 3 && rest.front() == '[' && rest.back() == ']' && index_digits(rest.substr(1, rest.size() - 2));
                if (ok) helper.k = std::string(rest.substr(1, rest.size() - 2));
            }
        }
        if (!ok) throw Error{"helper", std::string(path)};
        out.helper = helper;
    }
    out.components = parse_components(path.substr(1, hash == std::string_view::npos ? std::string_view::npos : hash - 1));
    return out;
}

std::string target_key(const std::vector<Component>& components) {
    std::string out;
    for (std::size_t i = 0; i < components.size(); ++i) {
        if (i) out += '/';
        out += component(components[i]);
    }
    return out;
}

std::vector<Component> parse_target_key(std::string_view key) { return parse_components(key); }

int compare(const NodePath& a, const NodePath& b) {
    for (std::size_t i = 0; i < a.components.size() && i < b.components.size(); ++i)
        if (int c = compare_component(a.components[i], b.components[i])) return c;
    if (a.components.size() != b.components.size()) return a.components.size() < b.components.size() ? -1 : 1;
    if (!a.helper || !b.helper) return (a.helper ? 1 : 0) - (b.helper ? 1 : 0);
    return compare_component(*a.helper, *b.helper);
}

}  // namespace msf::paths
