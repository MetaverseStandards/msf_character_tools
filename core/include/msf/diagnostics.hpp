// SPDX-License-Identifier: MIT
// Diagnostic codes from schemas/diagnostics.toml (through the generated
// diagnostics.inc), so an unregistered code does not compile.
#pragma once
#include <exception>
#include <string>
#include <utility>
#include <vector>

namespace msf {

enum class Severity { error, warning, info };

enum class Code {
#define MSF_DIAGNOSTIC(code, severity, strict) code,
#include "msf/diagnostics.inc"
#undef MSF_DIAGNOSTIC
    NONE
};

struct CodeInfo {
    const char* name;
    Severity severity;
    Code strict;  // Code::NONE unless a strict-losses error replaces this warning
};

const CodeInfo& info(Code code);
const char* severity_name(Severity severity);

inline const char* const kDefaultRemediation = "Correct the referenced input.";

struct Diagnostic {
    Code code = Code::NONE;
    std::string ref, message, remediation = kDefaultRemediation;
    Severity severity() const { return info(code).severity; }
};

struct Report {
    std::vector<Diagnostic> diagnostics;
    bool ok() const {
        for (const Diagnostic& d : diagnostics)
            if (d.severity() == Severity::error) return false;
        return true;
    }
};

// An error that ends the current operation, like report.Fault in Python.
// Strings are UTF-8; refs and messages may carry lone surrogates as WTF-8.
class Fault : public std::exception {
public:
    explicit Fault(Diagnostic diagnostic) : diagnostic_(std::move(diagnostic)) {}
    const Diagnostic& diagnostic() const { return diagnostic_; }
    const char* what() const noexcept override { return diagnostic_.message.c_str(); }

private:
    Diagnostic diagnostic_;
};

[[noreturn]] void fail(Code code, std::string ref, std::string message, std::string remediation = kDefaultRemediation);

}  // namespace msf
