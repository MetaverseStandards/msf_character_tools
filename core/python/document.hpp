// SPDX-License-Identifier: MIT
// The handle a validated authoring document and its compiled pack share.
#pragma once
#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>

#include <optional>
#include <string>
#include <utility>

#include "bridge.hpp"
#include "msf/json.hpp"
#include "msf/pack.hpp"
#include "msf/sha256.hpp"

struct Document {
    msf::json::Value value;
    mutable nanobind::object view_;
    mutable std::optional<std::string> sha256_;

    explicit Document(msf::json::Value v) : value(std::move(v)) {}

    nanobind::object view() const {
        if (!view_.is_valid()) view_ = bridge::frozen(value);
        return view_;
    }

    // The view is deeply immutable (proxies, tuples, scalars). So if the
    // candidate is the same object this handle built, it holds the handle's value.
    bool check_view(nanobind::handle candidate) const { return view_.is_valid() && candidate.ptr() == view_.ptr(); }

    nanobind::bytes state() const {
        std::string out = msf::json::write_exact(value);
        return nanobind::bytes(out.data(), out.size());
    }

    nanobind::bytes canonical() const { return bridge::utf8_bytes(msf::json::write_canonical(value, true)); }

    std::string sha256() const {
        if (!sha256_) {
            nanobind::bytes raw = canonical();
            sha256_ = msf::sha256_hex(std::string_view(raw.c_str(), raw.size()));
        }
        return *sha256_;
    }

    nanobind::bytes survey_csv() const { return bridge::utf8_bytes(msf::pack::survey_csv(value)); }

    nanobind::object coverage() const { return bridge::to_python(msf::pack::coverage(value, sha256())); }
};

