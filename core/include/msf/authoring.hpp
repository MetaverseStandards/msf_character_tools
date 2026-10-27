// SPDX-License-Identifier: MIT
// Authoring validation and fragment merging, as msf_tools.authoring did them
// in 0.3.0: the same checks, codes, refs, messages and order.
#pragma once
#include <set>
#include <string>
#include <vector>

#include "msf/diagnostics.hpp"
#include "msf/json.hpp"

namespace msf::authoring {

// Every diagnostic validate_authoring reports for `document`, in order; the
// document is valid when the report is ok.
Report validate(const json::Value& document);

// load_authoring's merge of a directory's fragments, one parsed TOML table at
// a time; add() raises msf::Fault as the Python loop did.
class Merger {
public:
    Merger();
    void add(const std::string& relative, const json::Value& fragment);
    const json::Value& document() const { return merged_; }

private:
    json::Value merged_;
    std::set<std::string> seen_meta_;
};

// The strict checks other modules share (authoring.keys, string, domain,
// in_domain); each raises msf::Fault.
void keys(const json::Value& obj, const std::set<std::string>& required, const std::set<std::string>& optional,
          const std::string& ref);
void string(const json::Value& value, const std::string& ref);
void domain(const json::Value& obj, const std::string& ref);
void in_domain(const json::Value& value, const json::Value& bounds, const std::string& ref);
bool number(const json::Value& value);

}  // namespace msf::authoring
