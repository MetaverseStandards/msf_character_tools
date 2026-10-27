// SPDX-License-Identifier: MIT
#include "msf/diagnostics.hpp"

namespace msf {

namespace {
constexpr Severity error = Severity::error, warning = Severity::warning, info_ = Severity::info;
#define info info_
constexpr CodeInfo kCodes[] = {
#define MSF_DIAGNOSTIC(code, severity, strict) {#code, severity, Code::strict},
#include "msf/diagnostics.inc"
#undef MSF_DIAGNOSTIC
};
#undef info
}  // namespace

const CodeInfo& info(Code code) {
    static constexpr CodeInfo none{"NONE", Severity::error, Code::NONE};
    return code == Code::NONE ? none : kCodes[static_cast<int>(code)];
}

const char* severity_name(Severity severity) {
    switch (severity) {
        case Severity::error: return "error";
        case Severity::warning: return "warning";
        case Severity::info: return "info";
    }
    return "error";
}

void fail(Code code, std::string ref, std::string message, std::string remediation) {
    throw Fault(Diagnostic{code, std::move(ref), std::move(message), std::move(remediation)});
}

}  // namespace msf
