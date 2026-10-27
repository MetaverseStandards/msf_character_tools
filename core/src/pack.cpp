// SPDX-License-Identifier: MIT
#include "msf/pack.hpp"

#include <array>
#include <utility>
#include <vector>

namespace msf::pack {

using json::Value;
using Kind = Value::Kind;

namespace {

const char* const kDispositions[] = {"mapped", "unsupported", "unresolved", "excluded"};
const char* const kQualities[] = {"exact", "approximate"};

const Value& at(const Value& obj, const char* key) { return *json::find(obj, key); }

bool contains(const Value& list, const std::string& text) {
    for (const Value& item : list.items)
        if (item.text == text) return true;
    return false;
}

void field(std::string& out, const std::string& text) {
    if (text.find_first_of(",\"\n\r") == std::string::npos) {
        out += text;
        return;
    }
    out += '"';
    for (char c : text) {
        if (c == '"') out += '"';
        out += c;
    }
    out += '"';
}

Value array() {
    Value v;
    v.kind = Kind::array;
    return v;
}

Value object() {
    Value v;
    v.kind = Kind::object;
    return v;
}

Value integer(std::size_t n) { return Value::make_integer(std::to_string(n)); }

void put(Value& obj, const char* key, Value value) { obj.members.emplace_back(key, std::move(value)); }

// common.thaw: tuples become lists and -0.0 becomes 0.0.
Value thaw(const Value& v) {
    Value out = v;
    if (out.kind == Kind::real && out.number == 0.0) out = Value::make_real(0.0);
    out.is_list = true;
    for (Value& item : out.items) item = thaw(item);
    for (auto& member : out.members) member.second = thaw(member.second);
    return out;
}

Value ids(const std::vector<const Value*>& rows) {
    Value out = array();
    for (const Value* row : rows) out.items.push_back(at(*row, "id"));
    return out;
}

Value partitions(const std::vector<const Value*>& rows) {
    Value out = object();
    for (const char* d : kDispositions) {
        std::vector<const Value*> selected;
        for (const Value* row : rows)
            if (at(*row, "disposition").text == d) selected.push_back(row);
        put(out, d, ids(selected));
    }
    return out;
}

Value rule_quality(const std::vector<const Value*>& rows) {
    Value out = object();
    for (const char* q : kQualities) {
        std::vector<const Value*> selected;
        for (const Value* row : rows) {
            const Value* quality = json::find(*row, "mapping_quality");
            if (quality && quality->text == q) selected.push_back(row);
        }
        put(out, q, ids(selected));
    }
    return out;
}

Value counts(const Value& groups) {
    Value out = object();
    for (const auto& [key, list] : groups.members) out.members.emplace_back(key, integer(list.items.size()));
    return out;
}

bool touches(const Value& rule, const Value& signal_ids) {
    for (const char* side : {"inputs", "outputs"})
        for (const Value& sid : at(rule, side).items)
            if (contains(signal_ids, sid.text)) return true;
    return false;
}

bool mentions(const Value& rule, const std::string& sid) {
    return contains(at(rule, "inputs"), sid) || contains(at(rule, "outputs"), sid);
}

Value metadata(const Value& row) {
    const Value* m = json::find(row, "metadata");
    return m ? thaw(*m) : object();
}

}  // namespace

std::string survey_csv(const Value& document) {
    const Value& profiles = at(document, "profiles");
    std::string out;
    out += "id,label,value_type,units,disposition,evidence_status";
    for (const Value& p : profiles.items) {
        out += ',';
        field(out, at(p, "id").text);
    }
    out += '\n';
    for (const Value& s : at(document, "signals").items) {
        bool first = true;
        for (const char* k : {"id", "label", "value_type", "units", "disposition", "evidence_status"}) {
            if (!first) out += ',';
            first = false;
            field(out, at(s, k).text);
        }
        for (const Value& p : profiles.items) {
            out += ',';
            if (contains(at(p, "signal_ids"), at(s, "id").text)) out += '1';
        }
        out += '\n';
    }
    return out;
}

Value coverage(const Value& document, const std::string& pack_sha256) {
    std::vector<const Value*> signals, rules;
    for (const Value& s : at(document, "signals").items) signals.push_back(&s);
    for (const Value& m : at(document, "mappings").items)
        for (const Value& r : at(m, "rules").items) rules.push_back(&r);
    const Value& all_profiles = at(document, "profiles");

    Value profiles = array();
    for (const Value& p : all_profiles.items) {
        const Value& signal_ids = at(p, "signal_ids");
        std::vector<const Value*> selected, used;
        for (const Value* s : signals)
            if (contains(signal_ids, at(*s, "id").text)) selected.push_back(s);
        for (const Value* r : rules)
            if (touches(*r, signal_ids)) used.push_back(r);
        Value row = object();
        put(row, "id", at(p, "id"));
        put(row, "signal_ids", thaw(signal_ids));
        put(row, "count", integer(selected.size()));
        Value dispositions = partitions(selected);
        Value disposition_counts = counts(dispositions);
        put(row, "dispositions", std::move(dispositions));
        put(row, "disposition_counts", std::move(disposition_counts));
        Value quality = rule_quality(used);
        Value quality_counts = counts(quality);
        put(row, "mapping_quality", std::move(quality));
        put(row, "mapping_quality_counts", std::move(quality_counts));
        put(row, "metadata", metadata(p));
        profiles.items.push_back(std::move(row));
    }

    Value evidence = array();
    for (const Value& e : at(document, "evidence").items) {
        const std::string& eid = at(e, "id").text;
        Value row = thaw(e);
        std::vector<const Value*> by_signal, by_profile, by_rule;
        for (const Value* s : signals)
            if (contains(at(*s, "evidence"), eid)) by_signal.push_back(s);
        for (const Value& p : all_profiles.items) {
            const Value* refs = json::find(p, "evidence");
            if (refs && contains(*refs, eid)) by_profile.push_back(&p);
        }
        for (const Value* r : rules)
            if (contains(at(*r, "evidence"), eid)) by_rule.push_back(r);
        put(row, "signal_ids", ids(by_signal));
        put(row, "profile_ids", ids(by_profile));
        put(row, "rule_ids", ids(by_rule));
        evidence.items.push_back(std::move(row));
    }

    Value out = object();
    put(out, "schema_version", Value::make_string("1.0"));
    put(out, "pack_sha256", Value::make_string(pack_sha256));
    Value totals = object();
    put(totals, "signals", integer(signals.size()));
    put(totals, "profiles", integer(profiles.items.size()));
    put(totals, "rules", integer(rules.size()));
    put(totals, "evidence", integer(evidence.items.size()));
    put(out, "totals", std::move(totals));
    Value dispositions = partitions(signals);
    Value disposition_counts = counts(dispositions);
    put(out, "dispositions", std::move(dispositions));
    put(out, "disposition_counts", std::move(disposition_counts));
    Value quality = rule_quality(rules);
    Value quality_counts = counts(quality);
    put(out, "mapping_quality", std::move(quality));
    put(out, "mapping_quality_counts", std::move(quality_counts));
    put(out, "profiles", std::move(profiles));
    Value thawed_rules = array();
    for (const Value* r : rules) thawed_rules.items.push_back(thaw(*r));
    put(out, "rules", std::move(thawed_rules));
    put(out, "evidence", std::move(evidence));
    Value signal_rows = array();
    for (const Value* s : signals) {
        const std::string& sid = at(*s, "id").text;
        Value row = object();
        put(row, "id", at(*s, "id"));
        put(row, "disposition", at(*s, "disposition"));
        Value meta = metadata(*s);
        const Value* reason = json::find(meta, "reason");
        put(row, "reason", reason ? *reason : Value::null_value());
        std::vector<const Value*> in_profiles, in_rules;
        for (const Value& p : all_profiles.items)
            if (contains(at(p, "signal_ids"), sid)) in_profiles.push_back(&p);
        for (const Value* r : rules)
            if (mentions(*r, sid)) in_rules.push_back(r);
        put(row, "profiles", ids(in_profiles));
        put(row, "rules", ids(in_rules));
        signal_rows.items.push_back(std::move(row));
    }
    put(out, "signals", std::move(signal_rows));
    return out;
}

}  // namespace msf::pack
