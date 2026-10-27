// SPDX-License-Identifier: MIT
#include "msf/authoring.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace msf::authoring {

using json::Value;
using Kind = Value::Kind;
using Names = std::set<std::string>;

namespace {

const char* const kArrays[] = {"signals", "profiles", "mappings", "evidence"};
const Names kTop = {"schema_version", "data_version", "operator_version", "id", "license",
                    "signals", "profiles", "mappings", "evidence"};
const Names kSignalRequired = {"id", "label", "value_type", "units", "domain", "calibration",
                               "disposition", "evidence", "evidence_status"};
const Names kSignalOptional = {"region", "side", "neutral", "native_default", "coupling", "native_id",
                               "surface", "validity", "confidence", "time", "metadata"};
const Names kRuleRequired = {"id", "inputs", "outputs", "operator", "disposition", "assumptions",
                             "evidence", "evidence_status", "loss_annotations"};
const Names kDispositions = {"mapped", "unsupported", "unresolved", "excluded"};
const Names kStatuses = {"verified_current", "proposed", "unresolved"};
const Names kStatuses11 = {"verified_current", "proposed", "unresolved", "calibrated_software"};
const Names kSchemaVersions = {"1.0", "1.1"};
const Names kOperators10 = {"identity", "affine", "weighted_sum"};
const Names kOperators11 = {"identity", "affine", "weighted_sum", "piecewise_linear"};

// The blank set shared by the authoring and pack 1.0 schemas' character class.
const std::uint32_t kBlank[] = {0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680,
                                0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009,
                                0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000, 0xfeff};

bool is_blank(const std::string& wtf8) {
    const auto* s = reinterpret_cast<const unsigned char*>(wtf8.data());
    std::size_t i = 0, n = wtf8.size();
    while (i < n) {
        std::uint32_t c = s[i];
        std::size_t len = c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4;
        if (len > 1) {
            c &= 0xFF >> (len + 1);
            for (std::size_t k = 1; k < len; ++k) c = (c << 6) | (s[i + k] & 0x3F);
        }
        if (std::find(std::begin(kBlank), std::end(kBlank), c) == std::end(kBlank)) return false;
        i += len;
    }
    return true;
}

std::string joined(const Names& names) {
    std::string out;
    for (const std::string& name : names) {
        if (!out.empty()) out += ", ";
        out += name;
    }
    return out;
}

std::string child(const std::string& ref, const std::string& key) { return ref + "/" + key; }

bool is_mapping(const Value& v) { return v.kind == Kind::object; }
bool is_sequence(const Value& v) { return v.kind == Kind::array; }
bool is_str(const Value& v) { return v.kind == Kind::string; }

const Value& at(const Value& obj, const char* key) { return *json::find(obj, key); }
bool has(const Value& obj, const char* key) { return json::find(obj, key) != nullptr; }

void strings(const Value& value, const std::string& ref, bool unique = true, bool nonempty = false) {
    if (!is_sequence(value)) fail(Code::E_TYPE, ref, "Expected an array of strings.");
    for (std::size_t i = 0; i < value.items.size(); ++i) string(value.items[i], child(ref, std::to_string(i)));
    if (unique) {
        std::unordered_set<std::string> seen;
        for (const Value& x : value.items) seen.insert(x.text);
        if (seen.size() != value.items.size()) fail(Code::E_DUPLICATE, ref, "Duplicate array entries.");
    }
    if (nonempty && value.items.empty()) fail(Code::E_REQUIRED, ref, "At least one entry is required.");
}

void coupling(const Value& value, const std::string& ref) {
    if (is_str(value))
        string(value, ref);
    else
        strings(value, ref);
}

void enumerated(const Value& value, const Names& choices, const std::string& ref) {
    if (!is_str(value) || !choices.count(value.text)) fail(Code::E_ENUM, ref, "Expected one of " + joined(choices));
}

void loss_annotation(const Value& obj, const std::string& ref) {
    keys(obj, {"category", "effect", "reason", "refs"}, {"units", "bound"}, ref);
    enumerated(at(obj, "category"), {"signal", "geometry", "binding", "animation", "material", "metadata"}, ref);
    enumerated(at(obj, "effect"), {"preserved", "approximated", "dropped", "unknown"}, ref);
    string(at(obj, "reason"), ref);
    strings(at(obj, "refs"), ref);
    if (has(obj, "units")) string(at(obj, "units"), ref);
    if (has(obj, "bound") && (!number(at(obj, "bound")) || at(obj, "bound").number < 0))
        fail(Code::E_TYPE, ref, "Loss bound must be finite and nonnegative.");
}

void validate_signal(const Value& s, const std::string& ref, const Names& statuses) {
    keys(s, kSignalRequired, kSignalOptional, ref);
    for (const char* k : {"id", "label", "units", "calibration"}) string(at(s, k), child(ref, k));
    enumerated(at(s, "value_type"), {"scalar"}, child(ref, "value_type"));
    enumerated(at(s, "disposition"), kDispositions, ref);
    enumerated(at(s, "evidence_status"), statuses, ref);
    strings(at(s, "evidence"), child(ref, "evidence"));
    domain(at(s, "domain"), child(ref, "domain"));
    for (const char* k : {"neutral", "native_default"})
        if (has(s, k)) in_domain(at(s, k), at(s, "domain"), child(ref, k));
    for (const char* k : {"region", "side", "native_id", "surface", "time"})
        if (has(s, k)) string(at(s, k), child(ref, k));
    if (has(s, "validity") && !is_str(at(s, "validity")) && at(s, "validity").kind != Kind::boolean)
        fail(Code::E_TYPE, child(ref, "validity"), "Expected a boolean or explicit validity description.");
    if (has(s, "validity") && is_str(at(s, "validity"))) string(at(s, "validity"), child(ref, "validity"));
    if (has(s, "confidence")) {
        const Value& c = at(s, "confidence");
        if (!(is_str(c) || (number(c) && 0 <= c.number && c.number <= 1)))
            fail(Code::E_TYPE, ref, "Confidence must be a description or number in [0,1].");
        if (is_str(c)) string(c, child(ref, "confidence"));
    }
    if (has(s, "coupling")) coupling(at(s, "coupling"), child(ref, "coupling"));
    if (has(s, "metadata") && !is_mapping(at(s, "metadata"))) fail(Code::E_TYPE, ref, "metadata must be an object.");
}

void knots(const Value& value, const std::string& ref) {
    bool shaped = is_sequence(value) && value.items.size() >= 2;
    for (std::size_t i = 0; shaped && i < value.items.size(); ++i) {
        const Value& k = value.items[i];
        shaped = is_sequence(k) && k.items.size() == 2 && number(k.items[0]) && number(k.items[1]);
    }
    if (!shaped) fail(Code::E_TYPE, ref, "Knots must be an array of at least two [x, y] pairs of finite numbers.");
    std::vector<std::pair<double, double>> steps;
    for (std::size_t i = 1; i < value.items.size(); ++i) {
        const Value &a = value.items[i - 1], &b = value.items[i];
        steps.emplace_back(b.items[0].number - a.items[0].number, b.items[1].number - a.items[1].number);
    }
    for (const auto& [dx, dy] : steps)
        if (!std::isfinite(dx) || !std::isfinite(dy)) fail(Code::E_KNOTS, ref, "Knot spans must be finite binary64 values.");
    for (const auto& step : steps)
        if (!(step.first > 0)) fail(Code::E_KNOTS, ref, "Knot x values must be strictly increasing.");
    bool rising = std::all_of(steps.begin(), steps.end(), [](auto& s) { return s.second >= 0; });
    bool falling = std::all_of(steps.begin(), steps.end(), [](auto& s) { return s.second <= 0; });
    if (!rising && !falling)
        fail(Code::E_KNOTS, ref, "Knot y values must be monotone, all nondecreasing or all nonincreasing.");
}

void validate_rule(const Value& r, const std::string& ref, const Names& statuses, const Names& operators) {
    keys(r, kRuleRequired, {"mapping_quality", "coupling"}, ref);
    string(at(r, "id"), ref);
    strings(at(r, "inputs"), child(ref, "inputs"), true, true);
    strings(at(r, "outputs"), child(ref, "outputs"), true, true);
    strings(at(r, "assumptions"), child(ref, "assumptions"));
    strings(at(r, "evidence"), child(ref, "evidence"));
    enumerated(at(r, "disposition"), kDispositions, ref);
    enumerated(at(r, "evidence_status"), statuses, ref);
    if (at(r, "disposition").text == "mapped") {
        if (!has(r, "mapping_quality")) fail(Code::E_REQUIRED, ref, "Mapped rules require mapping_quality.");
        enumerated(at(r, "mapping_quality"), {"exact", "approximate"}, ref);
    } else if (has(r, "mapping_quality")) {
        fail(Code::E_DISPOSITION, ref, "mapping_quality is only valid on mapped rules.");
    }
    if (has(r, "coupling")) coupling(at(r, "coupling"), child(ref, "coupling"));
    const Value& op = at(r, "operator");
    Names optional = {"scale", "offset", "weights"};
    if (operators.count("piecewise_linear")) optional.insert("knots");
    keys(op, {"id"}, optional, child(ref, "operator"));
    enumerated(at(op, "id"), operators, ref);
    const std::string& id = at(op, "id").text;
    if (at(r, "outputs").items.size() != 1 || (id != "weighted_sum" && at(r, "inputs").items.size() != 1))
        fail(Code::E_ARITY, ref, "Unary operators need 1 input/output; weighted_sum needs N inputs and 1 output.");
    Names allowed = id == "identity" ? Names{"id"} : id == "affine" ? Names{"id", "scale", "offset"}
                    : id == "weighted_sum" ? Names{"id", "weights"} : Names{"id", "knots"};
    Names present;
    for (const auto& member : op.members) present.insert(member.first);
    if (present != allowed) fail(Code::E_OPERATOR, ref, "Operator coefficients must be explicit and match its type.");
    if (id == "affine" && (!number(at(op, "scale")) || !number(at(op, "offset"))))
        fail(Code::E_TYPE, ref, "Affine coefficients must be finite scalars.");
    if (id == "weighted_sum") {
        const Value& w = at(op, "weights");
        bool good = is_sequence(w) && w.items.size() == at(r, "inputs").items.size() &&
                    std::all_of(w.items.begin(), w.items.end(), [](const Value& x) { return number(x); });
        if (!good) fail(Code::E_TYPE, ref, "Weights must be finite, ordered and match inputs.");
    }
    if (id == "piecewise_linear") knots(at(op, "knots"), ref);
    const Value& losses = at(r, "loss_annotations");
    if (!is_sequence(losses)) fail(Code::E_TYPE, ref, "loss_annotations must be an array.");
    for (std::size_t i = 0; i < losses.items.size(); ++i)
        loss_annotation(losses.items[i], child(ref, "loss_annotations/" + std::to_string(i)));
}

bool data_version(const Value& v) {
    if (!is_str(v)) return false;
    const std::string& s = v.text;
    std::size_t i = 0;
    auto digits = [&] {
        std::size_t start = i;
        while (i < s.size() && s[i] >= '0' && s[i] <= '9') ++i;
        return i > start;
    };
    if (!digits() || i >= s.size() || s[i++] != '.' || !digits() || i >= s.size() || s[i++] != '.' || !digits()) return false;
    if (i == s.size()) return true;
    if (s[i++] != '-' || i == s.size()) return false;
    for (; i < s.size(); ++i) {
        char c = s[i];
        bool ascii_alnum = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
        if (!ascii_alnum && c != '.' && c != '-') return false;
    }
    return true;
}

bool sha256_digest(const Value& v) {
    return is_str(v) && v.text.size() == 64 &&
           std::all_of(v.text.begin(), v.text.end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
}

// common.json_value: depth before type, in document order.
void json_value(const Value& v, const std::string& ref, int depth) {
    if (depth > 128) fail(Code::E_RESOURCE_LIMIT, ref, "JSON nesting exceeds 128 levels.");
    auto down = [&](const std::string& key) { return (ref == "/" ? std::string() : ref) + "/" + key; };
    switch (v.kind) {
        case Kind::null:
        case Kind::string:
        case Kind::boolean:
            return;
        case Kind::integer:
        case Kind::real:
            if (!number(v)) fail(Code::E_NONFINITE, ref, "Numbers must be finite binary64 values.");
            return;
        case Kind::object:
            for (const auto& [key, item] : v.members) {
                if (json::is_nonstring_key(key)) fail(Code::E_TYPE, ref, "Object keys must be strings.");
                json_value(item, down(key), depth + 1);
            }
            return;
        case Kind::array:
            for (std::size_t i = 0; i < v.items.size(); ++i) json_value(v.items[i], down(std::to_string(i)), depth + 1);
            return;
        case Kind::other:
            fail(Code::E_TYPE, ref, "Expected a JSON-compatible value.");
    }
}

// An inventory: IDs in first-seen order, each with its first row.
struct Inventory {
    std::vector<std::pair<std::string, const Value*>> rows;
    std::unordered_set<std::string> ids;
    bool contains(const std::string& id) const { return ids.count(id) > 0; }
};

}  // namespace

bool number(const Value& v) { return (v.kind == Kind::integer || v.kind == Kind::real) && std::isfinite(v.number); }

void keys(const Value& obj, const Names& required, const Names& optional, const std::string& ref) {
    if (!is_mapping(obj)) fail(Code::E_TYPE, ref, "Expected an object.");
    for (const auto& member : obj.members)
        if (json::is_nonstring_key(member.first)) fail(Code::E_TYPE, ref, "Object keys must be strings.");
    Names present;
    for (const auto& member : obj.members) present.insert(member.first);
    Names missing, extra;
    for (const std::string& k : required)
        if (!present.count(k)) missing.insert(k);
    for (const std::string& k : present)
        if (!required.count(k) && !optional.count(k)) extra.insert(k);
    if (!missing.empty()) fail(Code::E_REQUIRED, ref, "Missing keys: " + joined(missing));
    if (!extra.empty()) fail(Code::E_UNKNOWN_KEY, ref, "Unknown keys: " + joined(extra));
}

void string(const Value& value, const std::string& ref) {
    if (!is_str(value) || is_blank(value.text)) fail(Code::E_TYPE, ref, "Expected a nonempty string.");
}

void domain(const Value& obj, const std::string& ref) {
    keys(obj, {}, {"min", "max"}, ref);
    for (const auto& [k, v] : obj.members)
        if (!number(v)) fail(Code::E_TYPE, child(ref, k), "Domain bounds must be finite numbers.");
    if (has(obj, "min") && has(obj, "max") && json::compare_numbers(at(obj, "min"), at(obj, "max")) > 0)
        fail(Code::E_DOMAIN, ref, "Domain minimum exceeds maximum.");
}

void in_domain(const Value& value, const Value& bounds, const std::string& ref) {
    if (!number(value)) fail(Code::E_TYPE, ref, "Expected a finite scalar, excluding boolean.");
    const Value* low = json::find(bounds, "min");
    const Value* high = json::find(bounds, "max");
    if ((low && json::compare_numbers(value, *low) < 0) || (high && json::compare_numbers(value, *high) > 0))
        fail(Code::E_DOMAIN, ref, "Value is outside its declared domain.",
             "Supply a valid sample; no clamping or neutral substitution is performed.");
}

Report validate(const Value& document) {
    Report report;
    auto check = [&](const std::function<void()>& fn) {
        try {
            fn();
            return true;
        } catch (const Fault& fault) {
            report.diagnostics.push_back(fault.diagnostic());
            return false;
        }
    };
    auto add = [&](Code code, std::string ref, std::string message) {
        report.diagnostics.push_back({code, std::move(ref), std::move(message)});
    };
    if (!check([&] { keys(document, kTop, {}, "/"); })) return report;
    check([&] { json_value(document, "/", 0); });
    for (const char* k : {"id", "license"}) check([&] { string(at(document, k), std::string("/") + k); });
    const Value& schema = at(document, "schema_version");
    const Value& op_version = at(document, "operator_version");
    check([&] { enumerated(schema, kSchemaVersions, "/schema_version"); });
    check([&] { enumerated(op_version, kSchemaVersions, "/operator_version"); });
    // An unknown schema or operator version already failed; check the rest as 1.0.
    const Names& statuses = is_str(schema) && schema.text == "1.1" ? kStatuses11 : kStatuses;
    bool known_operators = is_str(op_version) && kSchemaVersions.count(op_version.text);
    const Names& operators = is_str(op_version) && op_version.text == "1.1" ? kOperators11 : kOperators10;
    if (!data_version(at(document, "data_version")))
        report.diagnostics.push_back(
            {Code::E_VERSION, "/data_version", "Expected a semantic data version.", "Use an independently versioned data release."});
    std::unordered_map<std::string, Inventory> inventories;
    std::vector<std::string> rule_order;
    std::unordered_map<std::string, const Value*> rules;
    for (const char* category : kArrays) {
        const Value& rows = at(document, category);
        Inventory& ids = inventories[category];
        std::string top = std::string("/") + category;
        if (!is_sequence(rows)) {
            add(Code::E_TYPE, top, "Expected an array.");
            continue;
        }
        for (std::size_t i = 0; i < rows.items.size(); ++i) {
            const Value& row = rows.items[i];
            std::string ref = top + "/" + std::to_string(i);
            if (!is_mapping(row)) {
                add(Code::E_TYPE, ref, "Expected an object.");
                continue;
            }
            const Value* id = json::find(row, "id");
            if (id && is_str(*id)) {
                if (ids.contains(id->text))
                    add(Code::E_DUPLICATE_ID, ref, std::string("Duplicate ") + category + " ID " + id->text + ".");
                else
                    ids.ids.insert(id->text), ids.rows.emplace_back(id->text, &row);
            }
            std::string name = category;
            if (name == "signals") {
                check([&] { validate_signal(row, ref, statuses); });
            } else if (name == "profiles") {
                if (check([&] { keys(row, {"id", "label", "signal_ids"}, {"evidence", "metadata"}, ref); })) {
                    check([&] { string(at(row, "id"), ref); });
                    check([&] { string(at(row, "label"), ref); });
                    check([&] { strings(at(row, "signal_ids"), ref); });
                    if (has(row, "evidence")) check([&] { strings(at(row, "evidence"), ref); });
                    if (has(row, "metadata") && !is_mapping(at(row, "metadata")))
                        add(Code::E_TYPE, ref, "metadata must be an object.");
                }
            } else if (name == "evidence") {
                if (check([&] { keys(row, {"id", "claim", "status"},
                                      {"url", "revision", "retrieved", "sha256", "locator", "license", "authorship"}, ref); })) {
                    for (const auto& member : row.members) check([&] { string(member.second, child(ref, member.first)); });
                    check([&] { enumerated(at(row, "status"), statuses, ref); });
                    if (has(row, "url")) {
                        const Value& url = at(row, "url");
                        if (!is_str(url) || url.text.compare(0, 8, "https://") != 0)
                            add(Code::E_EVIDENCE, ref, "Public evidence URL must use HTTPS.");
                        if (!(has(row, "revision") || has(row, "retrieved") || has(row, "sha256")) || !has(row, "locator"))
                            add(Code::E_EVIDENCE, ref, "Public evidence needs revision/retrieved/digest and locator.");
                    } else if (!(has(row, "license") && has(row, "authorship"))) {
                        add(Code::E_EVIDENCE, ref, "Original evidence needs license and authorship.");
                    }
                    if (has(row, "sha256") && !sha256_digest(at(row, "sha256")))
                        add(Code::E_EVIDENCE, ref, "Invalid SHA256 digest.");
                }
            } else {
                if (check([&] { keys(row, {"id", "rules"}, {}, ref); })) {
                    check([&] { string(at(row, "id"), ref); });
                    const Value& list = at(row, "rules");
                    if (!is_sequence(list)) {
                        add(Code::E_TYPE, ref, "rules must be an array.");
                        continue;
                    }
                    for (std::size_t j = 0; j < list.items.size(); ++j) {
                        const Value& r = list.items[j];
                        std::string rr = ref + "/rules/" + std::to_string(j);
                        const Value* op = is_mapping(r) ? json::find(r, "operator") : nullptr;
                        const Value* op_id = op && is_mapping(*op) ? json::find(*op, "id") : nullptr;
                        if (known_operators && op_id && is_str(*op_id) && kOperators11.count(op_id->text) && !operators.count(op_id->text))
                            add(Code::E_OPERATOR_VERSION, rr, "Operator " + op_id->text + " needs a newer operator_version than " + op_version.text + ".");
                        else
                            check([&] { validate_rule(r, rr, statuses, operators); });
                        const Value* rid = is_mapping(r) ? json::find(r, "id") : nullptr;
                        if (rid && is_str(*rid)) {
                            if (rules.count(rid->text))
                                add(Code::E_DUPLICATE_ID, rr, "Rule IDs must be unique across mappings.");
                            else
                                rule_order.push_back(rid->text);
                            rules[rid->text] = &r;  // a later duplicate replaces the row, keeping the first position
                        }
                    }
                }
            }
        }
    }
    for (const char* category : kArrays) {
        for (const auto& [sid, row] : inventories[category].rows) {
            std::string ref = std::string("/") + category + "/" + sid;
            const Value* refs = json::find(*row, "evidence");
            if (refs && is_sequence(*refs))
                for (const Value& eid : refs->items)
                    if (is_str(eid) && !inventories["evidence"].contains(eid.text))
                        add(Code::E_REFERENCE, ref, "Unknown evidence " + eid.text + ".");
            const Value* signal_ids = json::find(*row, "signal_ids");
            if (std::string(category) == "profiles" && signal_ids && is_sequence(*signal_ids))
                for (const Value& signal : signal_ids->items)
                    if (is_str(signal) && !inventories["signals"].contains(signal.text))
                        add(Code::E_REFERENCE, ref, "Unknown signal " + signal.text + ".");
        }
    }
    for (const std::string& rid : rule_order) {
        const Value& r = *rules[rid];
        for (const auto& [field, inventory] : {std::pair{"inputs", "signals"}, std::pair{"outputs", "signals"}, std::pair{"evidence", "evidence"}}) {
            const Value* list = json::find(r, field);
            if (list && is_sequence(*list))
                for (const Value& item : list->items)
                    if (is_str(item) && !inventories[inventory].contains(item.text))
                        add(Code::E_REFERENCE, "/rules/" + rid + "/" + field, "Unknown reference " + item.text + ".");
        }
    }
    return report;
}

Merger::Merger() {
    merged_.kind = Kind::object;
    for (const char* k : kArrays) {
        Value empty;
        empty.kind = Kind::array;
        merged_.members.emplace_back(k, std::move(empty));
    }
}

void Merger::add(const std::string& relative, const Value& fragment) {
    for (const auto& member : fragment.members) {
        const std::string& k = member.first;
        const Value& v = member.second;
        auto target = std::find_if(merged_.members.begin(), merged_.members.begin() + std::size(kArrays),
                                   [&](const auto& m) { return m.first == k; });
        if (target != merged_.members.begin() + std::size(kArrays)) {
            if (v.kind != Kind::array || !v.is_list) fail(Code::E_TYPE, relative, k + " must be an array.");
            target->second.items.insert(target->second.items.end(), v.items.begin(), v.items.end());
        } else {
            if (seen_meta_.count(k)) fail(Code::E_DUPLICATE_KEY, relative, "Duplicate metadata key " + k + ".");
            seen_meta_.insert(k);
            merged_.members.emplace_back(k, v);
        }
    }
}

}  // namespace msf::authoring
