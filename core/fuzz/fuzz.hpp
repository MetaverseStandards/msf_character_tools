// SPDX-License-Identifier: MIT
// Shared by the libFuzzer harnesses: the exceptions the core documents as its
// refusals. Anything else escaping a harness is a finding, and so is anything
// the Python boundary reports as E_INTERNAL (InternalError, ZeroDivisionError)
// unless MSF_FUZZ_ALLOW_INTERNAL is set.
#pragma once
#include <cstdio>
#include <cstdlib>
#include <string>
#include "msf/diagnostics.hpp"
#include "msf/gltf.hpp"
#include "msf/pyerror.hpp"

namespace msf::fuzz {
inline void internal(const char* type, const std::string& message) {
    static const bool allow = std::getenv("MSF_FUZZ_ALLOW_INTERNAL") != nullptr;
    if (allow) return;
    std::fprintf(stderr, "E_INTERNAL: %s: %s\n", type, message.c_str());
    std::abort();
}

template <class F>
bool refused(F&& body) {
    try {
        body();
        return false;
    } catch (const Fault&) {
    } catch (const gltf::DecodeError&) {
    } catch (const gltf::TooDeep&) {
    } catch (const gltf::DuplicateKey&) {
    } catch (const gltf::TypeError&) {
    } catch (const PyError& e) {
        if (e.type == PyError::Type::zero_division) internal("ZeroDivisionError", e.message);
    } catch (const gltf::InternalError& e) {
        internal("InternalError", e.what);
    }
    return true;
}
}  // namespace msf::fuzz
