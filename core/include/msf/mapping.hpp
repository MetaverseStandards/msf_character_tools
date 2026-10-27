// SPDX-License-Identifier: MIT
// Mapping compilation and exact sample evaluation over a validated pack, as
// msf_tools.mapping did them in 0.3.0: the same checks, codes, refs, messages
// and order. Values point into the pack document, which must outlive them.
#pragma once
#include <cstddef>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "msf/diagnostics.hpp"
#include "msf/json.hpp"
#include "msf/program.hpp"

namespace msf::mapping {

// Python's == for values from a validated document's frozen view: tuples and
// lists alike, numbers (bool included) exactly.
bool equal(const json::Value& a, const json::Value& b);

// A snapshot's channels, which live on the caller's side.
class Channels {
public:
    virtual ~Channels() = default;
    virtual bool has(const std::string& sid) const = 0;
    // Whether value_type, units, domain or calibration of the channel differs
    // from the signal's, compared in that order as Python's != does.
    virtual bool differs(const std::string& sid, const json::Value& signal) const = 0;
};

struct Loss {
    const json::Value* row;  // the authored loss annotation
};

struct Compiled {
    std::vector<Diagnostic> diagnostics;
    std::vector<Loss> losses;
    std::vector<const json::Value*> instructions;  // the rules, in execution order
    std::vector<std::string> required, outputs;
    bool ok() const { return diagnostics.empty(); }
};

// Raises Fault(E_MAPPING_REFERENCE) for an unknown mapping.
Compiled compile(const json::Value& pack, const std::string& mapping_id, bool allow_approximation, const Channels& source,
                 const Channels& target);

// A sample frame key: a str's text, or str() of any other key.
struct Key {
    bool is_str = true;
    std::string text;
};

class Evaluator {
public:
    // `sources`: the source snapshot's channel IDs.
    Evaluator(const json::Value& pack, const Compiled& compiled, std::vector<std::string> sources);
    // One frame at `index`. `order` is the frame's value and validity keys in
    // the order Python's set union iterated them.
    void frame(const json::Value& frame, const std::vector<Key>& order, std::size_t index);

    std::vector<Diagnostic> diagnostics;
    std::vector<double> timestamps;
    std::vector<double> values;  // one row of len(outputs) per frame, NaN where unwritten

private:
    const json::Value& signal(const std::string& sid) const;
    const Compiled& compiled_;
    std::unordered_map<std::string, const json::Value*> signals_;
    std::unordered_map<std::string, bool> sources_;
};

// The fast program for a compiled mapping: slots are the source channels known
// to the pack, then one per rule output. None when a domain bound has no exact
// binary64 value.
struct Fast {
    Program program;
    std::vector<std::string> sources;
    std::vector<Domain> source_domains;
    std::vector<std::size_t> required, output_slots;
};
std::optional<Fast> fast_program(const json::Value& pack, const Compiled& compiled, const std::vector<std::string>& source_channels);

}  // namespace msf::mapping
