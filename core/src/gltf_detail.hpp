// SPDX-License-Identifier: MIT
// Python-shaped helpers shared by the glTF sources: lookups that behave like
// dict.get, the snapshot module's index/positive_int/vector checks, and the
// accessor layout.
#pragma once
#include <array>
#include <cmath>
#include <string>
#include <string_view>

#include "msf/bigint.hpp"
#include "msf/diagnostics.hpp"
#include "msf/gltf.hpp"
#include "msf/json.hpp"

namespace msf::gltf::detail {

using Kind = Value::Kind;

// Where Python raised KeyError (a programming slip the checks did not cover).
struct MissingKey {
    std::string key;
};

inline const Value* get(const Value& obj, std::string_view key) {
    return obj.kind == Kind::object ? json::find(obj, key) : nullptr;
}
inline bool has(const Value& obj, std::string_view key) { return get(obj, key) != nullptr; }
inline const Value& item(const Value& obj, std::string_view key) {
    const Value* v = get(obj, key);
    if (!v) throw MissingKey{std::string(key)};
    return *v;
}
inline bool is_int(const Value* v) { return v && v->kind == Kind::integer; }
inline bool is_str(const Value* v) { return v && v->kind == Kind::string; }
inline bool is_obj(const Value* v) { return v && v->kind == Kind::object; }
inline bool is_list(const Value* v) { return v && v->kind == Kind::array; }
inline bool number(const Value* v) {
    return v && (v->kind == Kind::integer || v->kind == Kind::real) && std::isfinite(v->number);
}
inline BigInt big(const Value& v) { return BigInt::from_digits(v.text); }
// A missing key reads as the default.
inline BigInt int_or(const Value& obj, std::string_view key, long long fallback) {
    const Value* v = get(obj, key);
    return v ? big(*v) : BigInt(fallback);
}
inline bool int_is(const Value* v, long long x) { return is_int(v) && big(*v) == BigInt(x); }
inline bool str_is(const Value* v, std::string_view s) { return is_str(v) && v->text == s; }
inline bool is_true(const Value* v) { return v && v->kind == Kind::boolean && v->boolean; }
inline bool is_false(const Value* v) { return v && v->kind == Kind::boolean && !v->boolean; }
// Python truthiness of a JSON value.
inline bool truthy(const Value* v) {
    if (!v) return false;
    switch (v->kind) {
        case Kind::null: return false;
        case Kind::boolean: return v->boolean;
        case Kind::integer: return v->text != "0";
        case Kind::real: return v->number != 0.0;
        case Kind::string: return !v->text.empty();
        case Kind::array: return !v->items.empty();
        case Kind::object: return !v->members.empty();
        default: return true;
    }
}
// Python's == on JSON values (bool counts as 0 or 1).
inline bool numeric_kind(const Value& v) { return v.kind == Kind::integer || v.kind == Kind::real || v.kind == Kind::boolean; }
inline Value as_number(const Value& v) {
    return v.kind == Kind::boolean ? Value::make_integer(v.boolean ? "1" : "0") : v;
}
inline bool py_equal(const Value& a, const Value& b) {
    if (numeric_kind(a) && numeric_kind(b)) return json::compare_numbers(as_number(a), as_number(b)) == 0;
    if (a.kind != b.kind) return false;
    switch (a.kind) {
        case Kind::null: return true;
        case Kind::string: return a.text == b.text;
        case Kind::array:
            if (a.items.size() != b.items.size()) return false;
            for (std::size_t i = 0; i < a.items.size(); ++i)
                if (!py_equal(a.items[i], b.items[i])) return false;
            return true;
        case Kind::object:
            if (a.members.size() != b.members.size()) return false;
            for (const auto& [k, v] : a.members) {
                const Value* other = json::find(b, k);
                if (!other || !py_equal(v, *other)) return false;
            }
            return true;
        default: return false;
    }
}
// A missing value is None, equal only to another missing value.
inline bool py_equal(const Value* a, const Value* b) { return (!a && !b) || (a && b && py_equal(*a, *b)); }
// value == x for a Python int x.
inline bool numeric_equals(const Value* v, long long x) {
    if (!v) return false;
    if (v->kind == Kind::integer) return big(*v) == BigInt(x);
    if (v->kind == Kind::real) return v->number == static_cast<double>(x);
    if (v->kind == Kind::boolean) return (v->boolean ? 1 : 0) == x;
    return false;
}
inline const Value kZero = Value::make_integer("0");

inline std::size_t size_of(const Value* list) { return list && list->kind == Kind::array ? list->items.size() : 0; }

// snapshot.index
inline std::size_t index(const Value* value, std::size_t length, const std::string& ref) {
    if (!is_int(value) || big(*value) < BigInt(0) || big(*value) >= BigInt(static_cast<long long>(length)))
        fail(Code::E_REFERENCE, ref, "Index is not an integer in the referenced array.");
    return static_cast<std::size_t>(big(*value).to_int64());
}
// snapshot.positive_int
inline void positive_int(const Value* value, const std::string& ref, bool zero = false) {
    if (!is_int(value) || big(*value) < BigInt(zero ? 0 : 1))
        fail(Code::E_TYPE, ref, zero ? "Expected a nonnegative integer." : "Expected a positive integer.");
}
// snapshot.vector
inline void vector(const Value* value, std::size_t count, const std::string& ref) {
    bool ok = is_list(value) && value->items.size() == count;
    for (std::size_t i = 0; ok && i < count; ++i) ok = number(&value->items[i]);
    if (!ok) fail(Code::E_TYPE, ref, "Expected " + std::to_string(count) + " finite numeric components.");
}

struct Component {
    char code;  // struct format
    int size;
};
inline bool component(long long type, Component& out) {
    switch (type) {
        case 5120: out = {'b', 1}; return true;
        case 5121: out = {'B', 1}; return true;
        case 5122: out = {'h', 2}; return true;
        case 5123: out = {'H', 2}; return true;
        case 5125: out = {'I', 4}; return true;
        case 5126: out = {'f', 4}; return true;
        default: return false;
    }
}
inline bool shape(std::string_view type, int& columns, int& rows) {
    if (type == "SCALAR") { columns = 1; rows = 1; }
    else if (type == "VEC2") { columns = 1; rows = 2; }
    else if (type == "VEC3") { columns = 1; rows = 3; }
    else if (type == "VEC4") { columns = 1; rows = 4; }
    else if (type == "MAT2") { columns = 2; rows = 2; }
    else if (type == "MAT3") { columns = 3; rows = 3; }
    else if (type == "MAT4") { columns = 4; rows = 4; }
    else return false;
    return true;
}

struct Layout {
    std::vector<long long> offsets;
    long long element_size = 0;
    int size = 0;
    char code = 'f';
    long long component_type = 0;
};
// snapshot._layout, for an accessor whose componentType and type are valid.
inline Layout layout(long long component_type, std::string_view type) {
    Component c{};
    component(component_type, c);
    int columns = 0, rows = 0;
    shape(type, columns, rows);
    long long column_stride = static_cast<long long>(rows) * c.size;
    if (columns > 1) column_stride = (column_stride + 3) / 4 * 4;
    Layout out;
    for (int col = 0; col < columns; ++col)
        for (int r = 0; r < rows; ++r) out.offsets.push_back(col * column_stride + static_cast<long long>(r) * c.size);
    out.element_size = columns * column_stride;
    out.size = c.size;
    out.code = c.code;
    out.component_type = component_type;
    return out;
}
inline Layout layout(const Value& accessor) {
    return layout(big(item(accessor, "componentType")).to_int64(), item(accessor, "type").text);
}

}  // namespace msf::gltf::detail
