// SPDX-License-Identifier: MIT
#include "msf/mapping.hpp"

#include <algorithm>
#include <cmath>
#include <set>
#include <stdexcept>
#include <unordered_set>
#include <utility>

#include "msf/authoring.hpp"
#include "msf/math3d.hpp"

namespace msf::mapping {

using json::Value;
using Kind = Value::Kind;

namespace {

const Value& at(const Value& obj, const char* key) { return *json::find(obj, key); }
const std::string& text(const Value& obj, const char* key) { return at(obj, key).text; }

bool numeric(const Value& v) { return v.kind == Kind::integer || v.kind == Kind::real || v.kind == Kind::boolean; }

Value as_number(const Value& v) { return v.kind == Kind::boolean ? Value::make_integer(v.boolean ? "1" : "0") : v; }

bool is_loss_effect(const std::string& effect) { return effect == "approximated" || effect == "dropped" || effect == "unknown"; }

const Value* optional(const Value& obj, const char* key) { return json::find(obj, key); }

}  // namespace

bool equal(const Value& a, const Value& b) {
    if (numeric(a) && numeric(b)) {
        if ((a.kind == Kind::real && std::isnan(a.number)) || (b.kind == Kind::real && std::isnan(b.number))) return false;
        return json::compare_numbers(as_number(a), as_number(b)) == 0;
    }
    if (a.kind != b.kind) return false;
    switch (a.kind) {
        case Kind::null: return true;
        case Kind::string: return a.text == b.text;
        case Kind::array:
            if (a.items.size() != b.items.size()) return false;
            for (std::size_t i = 0; i < a.items.size(); ++i)
                if (!equal(a.items[i], b.items[i])) return false;
            return true;
        case Kind::object:
            if (a.members.size() != b.members.size()) return false;
            for (const auto& [key, value] : a.members) {
                const Value* other = json::find(b, key);
                if (!other || !equal(value, *other)) return false;
            }
            return true;
        default: return false;
    }
}

Compiled compile(const Value& pack, const std::string& mapping_id, bool allow_approximation, const Channels& source,
                 const Channels& target) {
    const Value* mapping = nullptr;
    for (const Value& m : at(pack, "mappings").items)
        if (text(m, "id") == mapping_id) {
            mapping = &m;
            break;
        }
    if (!mapping) fail(Code::E_MAPPING_REFERENCE, "/mappings", "Unknown mapping " + mapping_id + ".");
    Compiled out;
    auto add = [&](Code code, std::string ref, std::string message, std::string remediation = kDefaultRemediation) {
        out.diagnostics.push_back({code, std::move(ref), std::move(message), std::move(remediation)});
    };
    std::unordered_map<std::string, const Value*> signals, evidence;
    for (const Value& s : at(pack, "signals").items) signals.emplace(text(s, "id"), &s);
    for (const Value& e : at(pack, "evidence").items) evidence.emplace(text(e, "id"), &e);

    auto execution_evidence = [&](const Value& record, const std::string& kind, const Value& rule) {
        const std::string& sid = text(record, "id");
        const std::string& status = text(record, "evidence_status");
        if (kind == "Rule") {
            if (status == "unresolved")
                add(Code::E_EVIDENCE_STATUS, sid, "Rule " + sid + " has unresolved evidence_status and cannot execute.");
        } else if (status == "unresolved" || (text(rule, "evidence_status") == "verified_current" && status != "verified_current")) {
            add(Code::E_EVIDENCE_STATUS, sid, "Signal " + sid + " has evidence_status " + status + ", incompatible with rule " +
                                                  text(rule, "id") + " (" + text(rule, "evidence_status") + ").");
        }
        const Value& refs = at(record, "evidence");
        if (refs.items.empty()) add(Code::E_EVIDENCE_REQUIRED, sid, kind + " " + sid + " requires nonempty evidence for execution.");
        for (const Value& eid : refs.items) {
            const std::string& ref_status = text(*evidence.at(eid.text), "status");
            if (ref_status == "unresolved" || (status == "verified_current" && ref_status != "verified_current"))
                add(Code::E_EVIDENCE_COMPATIBILITY, sid, kind + " " + sid + " includes evidence " + eid.text + " with status " +
                                                             ref_status + ", incompatible with its evidence_status " + status + ".");
        }
    };
    auto channel = [&](const std::string& sid, const Channels& snapshot) {
        if (!snapshot.has(sid)) {
            add(Code::E_CHANNEL_REFERENCE, sid, "Required channel is absent from snapshot.",
                "Use profile_snapshot or hash-bound structural sidecar bindings.");
            return;
        }
        if (snapshot.differs(sid, *signals.at(sid)))
            add(Code::E_CHANNEL_TYPE, sid, "Snapshot channel type/domain/calibration disagrees with pack.");
    };

    // output -> rule; a later writer replaces the rule but keeps the position, like a dict.
    std::vector<std::string> written;
    std::unordered_map<std::string, std::string> writers;
    auto writer = [&](const std::string& sid) -> const std::string* {
        auto found = writers.find(sid);
        return found == writers.end() ? nullptr : &found->second;
    };
    const Value& rules = at(*mapping, "rules");
    for (const Value& r : rules.items) {
        const std::string& rid = text(r, "id");
        const Value* quality = optional(r, "mapping_quality");
        bool approximate = quality && quality->text == "approximate";
        const Value& losses = at(r, "loss_annotations");
        if (text(r, "disposition") != "mapped")
            add(Code::E_UNRESOLVED_RULE, rid, "Requested mapping contains an unsupported, unresolved or excluded rule.");
        execution_evidence(r, "Rule", r);
        if (approximate && !allow_approximation) add(Code::E_APPROXIMATION, rid, "Approximate rule requires explicit opt-in.");
        if (approximate && losses.items.empty())
            add(Code::E_LOSS_REQUIRED, rid, "Approximate rule " + rid + " requires explicit loss_annotations.");
        for (const Value& loss : losses.items) {
            if (is_loss_effect(text(loss, "effect")) && !allow_approximation)
                add(Code::E_APPROXIMATION, rid, "Declared loss requires explicit approximation opt-in.");
            out.losses.push_back({&loss});
        }
        for (const char* side : {"inputs", "outputs"})
            for (const Value& sid : at(r, side).items) {
                const Value& signal = *signals.at(sid.text);
                if (text(signal, "disposition") != "mapped") add(Code::E_SIGNAL_DISPOSITION, rid, "Signal " + sid.text + " is not mapped.");
                execution_evidence(signal, "Signal", r);
            }
        const std::string& output = at(r, "outputs").items[0].text;
        if (writer(output)) {
            add(Code::E_MULTIPLE_WRITERS, output, "Two rules write the same signal.");
            writers[output] = rid;
        } else {
            written.push_back(output);
            writers.emplace(output, rid);
        }
        std::vector<const Value*> inputs;
        for (const Value& sid : at(r, "inputs").items) inputs.push_back(signals.at(sid.text));
        const Value& out_signal = *signals.at(output);
        const std::string& op = text(at(r, "operator"), "id");
        bool assumptions = !at(r, "assumptions").items.empty();
        if (std::any_of(inputs.begin(), inputs.end(), [&](const Value* s) { return text(*s, "value_type") != text(out_signal, "value_type"); }))
            add(Code::E_SHAPE, rid, "Operator shapes disagree.");
        if (std::any_of(inputs.begin(), inputs.end(), [&](const Value* s) { return text(*s, "units") != text(out_signal, "units"); }) &&
            !(op == "affine" && assumptions))
            add(Code::E_UNITS, rid, "Unit conversion needs explicit affine coefficients and assumptions.");
        if (op == "identity" && text(*inputs[0], "calibration") != text(out_signal, "calibration"))
            add(Code::E_CALIBRATION, rid, "Identity requires the same explicit calibration basis.");
        if (op == "identity" && !equal(at(*inputs[0], "domain"), at(out_signal, "domain")))
            add(Code::E_DOMAIN_COMPATIBILITY, rid, "Identity requires equal declared domains.");
        if (op == "piecewise_linear") {
            const Value& knots = at(at(r, "operator"), "knots");
            const Value& bounds = at(*inputs[0], "domain");
            const Value* low = optional(bounds, "min");
            const Value* high = optional(bounds, "max");
            if (!low || !equal(*low, knots.items.front().items[0]) || !high || !equal(*high, knots.items.back().items[0]))
                add(Code::E_DOMAIN_COMPATIBILITY, rid, "Piecewise-linear knots must start and end at the input domain bounds.");
        }
        if (op == "identity") {
            const std::pair<const char*, Code> fields[] = {
                {"neutral", Code::E_NEUTRAL_COMPATIBILITY}, {"side", Code::E_SIDE_COMPATIBILITY}, {"coupling", Code::E_COUPLING_COMPATIBILITY}};
            for (const auto& [field, code] : fields) {
                const Value* a = optional(*inputs[0], field);
                const Value* b = optional(out_signal, field);
                if (!a != !b || (a && !equal(*a, *b)))
                    add(code, rid, std::string("Identity requires equal presence and value of ") + field + " on " + text(*inputs[0], "id") +
                                       " and " + output + ".");
            }
        } else {
            bool mixed_basis = std::any_of(inputs.begin(), inputs.end(), [&](const Value* s) {
                return text(*s, "calibration") != text(out_signal, "calibration") || text(*s, "units") != text(out_signal, "units");
            });
            bool declared_loss = std::any_of(losses.items.begin(), losses.items.end(), [](const Value& l) { return is_loss_effect(text(l, "effect")); });
            if (!assumptions && (mixed_basis || approximate || declared_loss))
                add(Code::E_DERIVATION_ASSUMPTIONS, rid, "Nonidentity rule " + rid +
                                                             " requires explicit derivation assumptions for differing calibration/units or declared approximation/loss.");
        }
    }

    // _dependency_waves: a rule joins the wave after the one holding its last
    // dependency; each wave runs in declaration order.
    std::size_t n = rules.items.size();
    std::unordered_map<std::string, std::size_t> position;
    for (std::size_t i = 0; i < n; ++i) position.emplace(text(rules.items[i], "id"), i);
    std::vector<std::vector<std::size_t>> dependents(n);
    std::vector<std::size_t> pending(n);
    for (std::size_t i = 0; i < n; ++i) {
        std::set<std::size_t> needs;
        for (const Value& sid : at(rules.items[i], "inputs").items)
            if (const std::string* w = writer(sid.text)) needs.insert(position.at(*w));
        pending[i] = needs.size();
        for (std::size_t need : needs) dependents[need].push_back(i);
    }
    std::vector<std::size_t> wave;
    for (std::size_t i = 0; i < n; ++i)
        if (!pending[i]) wave.push_back(i);
    while (!wave.empty()) {
        std::vector<std::size_t> ready;
        for (std::size_t i : wave) {
            out.instructions.push_back(&rules.items[i]);
            for (std::size_t d : dependents[i])
                if (!--pending[d]) ready.push_back(d);
        }
        std::sort(ready.begin(), ready.end());
        wave = std::move(ready);
    }
    if (out.instructions.size() < n) add(Code::E_MAPPING_CYCLE, mapping_id, "Mapping dependency graph contains a cycle.");

    std::unordered_set<std::string> consumed, seen_required, seen_output;
    for (const Value& r : rules.items)
        for (const Value& sid : at(r, "inputs").items) {
            consumed.insert(sid.text);
            if (!writer(sid.text) && seen_required.insert(sid.text).second) out.required.push_back(sid.text);
        }
    for (const Value& r : rules.items) {
        const std::string& output = at(r, "outputs").items[0].text;
        if (target.has(output) && seen_output.insert(output).second) out.outputs.push_back(output);
    }
    for (const std::string& sid : out.required) channel(sid, source);
    for (const std::string& sid : written) {
        if (source.has(sid)) add(Code::E_MULTIPLE_WRITERS, sid, "Rule output is also a source channel driver.");
        if (target.has(sid) || !consumed.count(sid)) channel(sid, target);
    }
    if (out.outputs.empty()) add(Code::E_MAPPING_OUTPUT, mapping_id, "Mapping has no target-bound outputs.");
    return out;
}

// ---------------------------------------------------------------- evaluation

Evaluator::Evaluator(const Value& pack, const Compiled& compiled, std::vector<std::string> sources) : compiled_(compiled) {
    for (const Value& s : at(pack, "signals").items) signals_.emplace(text(s, "id"), &s);
    for (std::string& sid : sources) sources_.emplace(std::move(sid), true);
}

// signals[sid] in Python: a source channel the pack does not declare raises KeyError there.
const Value& Evaluator::signal(const std::string& sid) const {
    auto found = signals_.find(sid);
    if (found == signals_.end()) throw std::out_of_range(sid);
    return *found->second;
}

namespace {

double piecewise(const Value& knots, double x, const std::string& ref) {
    std::vector<double> xs;
    for (const Value& k : knots.items) xs.push_back(k.items[0].number);
    std::size_t i = static_cast<std::size_t>(std::upper_bound(xs.begin(), xs.end(), x) - xs.begin()) - 1;
    if (xs[i] == x) return knots.items[i].items[1].number;
    double xa = xs[i], xb = xs[i + 1];
    double ya = knots.items[i].items[1].number, yb = knots.items[i + 1].items[1].number;
    double t = math3d::divide(math3d::sub(x, xa, ref), math3d::sub(xb, xa, ref), ref);
    double dy = math3d::sub(yb, ya, ref);
    double value = math3d::add(ya, math3d::product(t, dy, ref), ref);
    return piecewise_clamp(value, ya, yb);
}

}  // namespace

void Evaluator::frame(const Value& frame, const std::vector<Key>& order, std::size_t index) {
    std::string ref = "/samples/" + std::to_string(index);
    std::unordered_map<std::string, double> values;
    std::unordered_set<std::string> invalid;
    auto record = [&](const Fault& fault) { diagnostics.push_back(fault.diagnostic()); };
    try {
        authoring::keys(frame, {"timestamp", "values", "validity"}, {}, ref);
        const Value& ts = at(frame, "timestamp");
        if (!authoring::number(ts) || json::compare_numbers(ts, Value::make_integer("0")) < 0)
            fail(Code::E_TIMESTAMP, ref + "/timestamp", "Timestamp must be nonnegative finite seconds.");
        const Value& supplied = at(frame, "values");
        const Value& validity = at(frame, "validity");
        if (supplied.kind != Kind::object || validity.kind != Kind::object)
            fail(Code::E_SAMPLE_TYPE, ref, "values and validity must be objects by signal ID.");
        for (const Key& key : order) {
            const std::string& sid = key.text;
            try {
                if (!key.is_str || !sources_.count(sid))
                    fail(Code::E_SAMPLE_REFERENCE, ref, "Sample contains unknown/non-source channel " + sid + ".");
                const Value* value = json::find(supplied, sid);
                const Value* valid = json::find(validity, sid);
                if (!value || !valid || valid->kind != Kind::boolean)
                    fail(Code::E_VALIDITY, ref + "/" + sid, "Every supplied value needs explicit boolean validity.");
                authoring::in_domain(*value, at(signal(sid), "domain"), ref + "/" + sid);
                if (!valid->boolean) fail(Code::E_INVALID_SAMPLE, ref + "/" + sid, "Input is explicitly invalid; neutral is not substituted.");
                values[sid] = value->number;
            } catch (const Fault& fault) {
                record(fault);
                invalid.insert(sid);
            }
        }
        for (const std::string& sid : compiled_.required)
            if (!values.count(sid) && !invalid.count(sid))
                diagnostics.push_back({Code::E_MISSING_SAMPLE, ref + "/" + sid, "Required input or validity is missing."});
        for (const Value* rule : compiled_.instructions) {
            const std::string& output = at(*rule, "outputs").items[0].text;
            const Value& inputs = at(*rule, "inputs");
            if (std::any_of(inputs.items.begin(), inputs.items.end(), [&](const Value& s) { return !values.count(s.text); })) continue;
            try {
                const Value& op = at(*rule, "operator");
                const std::string& id = text(op, "id");
                std::string math_ref = ref + "/rules/" + text(*rule, "id");
                double value;
                if (id == "identity") {
                    value = values.at(inputs.items[0].text);
                } else if (id == "affine") {
                    value = math3d::add(math3d::product(at(op, "scale").number, values.at(inputs.items[0].text), math_ref),
                                        at(op, "offset").number, math_ref);
                } else if (id == "weighted_sum") {
                    value = 0.0;
                    const Value& weights = at(op, "weights");
                    for (std::size_t k = 0; k < weights.items.size() && k < inputs.items.size(); ++k)
                        value = math3d::add(value, math3d::product(weights.items[k].number, values.at(inputs.items[k].text), math_ref), math_ref);
                } else {
                    value = piecewise(at(op, "knots"), values.at(inputs.items[0].text), math_ref);
                }
                authoring::in_domain(Value::make_real(value), at(signal(output), "domain"), ref + "/rules/" + text(*rule, "id"));
                values[output] = value;
            } catch (const Fault& fault) {
                record(fault);
            }
        }
        timestamps.push_back(ts.number);
        for (const std::string& sid : compiled_.outputs) {
            auto found = values.find(sid);
            this->values.push_back(found == values.end() ? std::nan("") : found->second);
        }
    } catch (const Fault& fault) {
        record(fault);
    }
}

// ---------------------------------------------------------------- fast program

namespace {

// common.py's _domain: None when a bound has no exact binary64 value.
std::optional<Domain> exact_domain(const Value& bounds) {
    Domain d;
    for (const char* key : {"min", "max"}) {
        const Value* bound = json::find(bounds, key);
        if (!bound) continue;
        if (json::compare_numbers(*bound, Value::make_real(bound->number)) != 0) return std::nullopt;
        (key[1] == 'i' ? d.has_min : d.has_max) = true;
        (key[1] == 'i' ? d.min : d.max) = bound->number;
    }
    return d;
}

}  // namespace

std::optional<Fast> fast_program(const Value& pack, const Compiled& compiled, const std::vector<std::string>& source_channels) {
    std::unordered_map<std::string, const Value*> signals;
    for (const Value& s : at(pack, "signals").items) signals.emplace(text(s, "id"), &s);
    Fast fast;
    std::unordered_map<std::string, std::size_t> slots;
    for (const std::string& sid : source_channels) {
        auto signal = signals.find(sid);
        if (signal == signals.end()) continue;
        auto domain = exact_domain(at(*signal->second, "domain"));
        if (!domain) return std::nullopt;
        slots.emplace(sid, fast.sources.size());
        fast.sources.push_back(sid);
        fast.source_domains.push_back(*domain);
    }
    for (const Value* rule : compiled.instructions) {
        const Value& op = at(*rule, "operator");
        const std::string& id = text(op, "id");
        const std::string& output = at(*rule, "outputs").items[0].text;
        Instruction ins;
        ins.op = id == "identity" ? Op::identity : id == "affine" ? Op::affine : id == "weighted_sum" ? Op::weighted_sum : Op::piecewise_linear;
        for (const Value& sid : at(*rule, "inputs").items) ins.inputs.push_back(slots.at(sid.text));
        ins.output = slots.emplace(output, slots.size()).first->second;
        auto domain = exact_domain(at(*signals.at(output), "domain"));
        if (!domain) return std::nullopt;
        ins.output_domain = *domain;
        if (const Value* scale = json::find(op, "scale")) ins.scale = scale->number;
        if (const Value* offset = json::find(op, "offset")) ins.offset = offset->number;
        if (const Value* weights = json::find(op, "weights"))
            for (const Value& w : weights->items) ins.weights.push_back(w.number);
        if (const Value* knots = json::find(op, "knots"))
            for (const Value& k : knots->items) {
                ins.xs.push_back(k.items[0].number);
                ins.ys.push_back(k.items[1].number);
            }
        fast.program.instructions.push_back(std::move(ins));
    }
    fast.program.slots = slots.size();
    for (const std::string& sid : compiled.required) fast.required.push_back(slots.at(sid));
    for (const std::string& sid : compiled.outputs) fast.output_slots.push_back(slots.at(sid));
    return fast;
}

}  // namespace msf::mapping
