// SPDX-License-Identifier: MIT
#include "msf/bigint.hpp"

#include <algorithm>

namespace msf {

BigInt::BigInt(long long value) {
    negative_ = value < 0;
    unsigned long long magnitude = negative_ ? 0ULL - static_cast<unsigned long long>(value) : static_cast<unsigned long long>(value);
    while (magnitude) {
        limbs_.push_back(static_cast<std::uint32_t>(magnitude));
        magnitude >>= 32;
    }
}

BigInt BigInt::from_digits(const std::string& digits) {
    BigInt out;
    std::size_t i = 0;
    bool negative = !digits.empty() && digits[0] == '-';
    if (negative || (!digits.empty() && digits[0] == '+')) i = 1;
    for (; i < digits.size(); ++i) {
        std::uint64_t carry = static_cast<std::uint64_t>(digits[i] - '0');
        for (auto& limb : out.limbs_) {
            std::uint64_t x = static_cast<std::uint64_t>(limb) * 10 + carry;
            limb = static_cast<std::uint32_t>(x);
            carry = x >> 32;
        }
        if (carry) out.limbs_.push_back(static_cast<std::uint32_t>(carry));
    }
    out.trim();
    out.negative_ = negative && !out.limbs_.empty();
    return out;
}

void BigInt::trim() {
    while (!limbs_.empty() && limbs_.back() == 0) limbs_.pop_back();
    if (limbs_.empty()) negative_ = false;
}

std::string BigInt::to_string() const {
    if (limbs_.empty()) return "0";
    std::vector<std::uint32_t> work = limbs_;
    std::string out;
    while (!work.empty()) {
        std::uint64_t remainder = 0;
        for (std::size_t i = work.size(); i-- > 0;) {
            std::uint64_t x = (remainder << 32) | work[i];
            work[i] = static_cast<std::uint32_t>(x / 1000000000U);
            remainder = x % 1000000000U;
        }
        while (!work.empty() && work.back() == 0) work.pop_back();
        for (int k = 0; k < 9; ++k) {
            out.push_back(static_cast<char>('0' + remainder % 10));
            remainder /= 10;
            if (work.empty() && remainder == 0) break;
        }
    }
    while (out.size() > 1 && out.back() == '0') out.pop_back();
    if (negative_) out.push_back('-');
    std::reverse(out.begin(), out.end());
    return out;
}

bool BigInt::fits_int64() const {
    if (limbs_.size() > 2) return false;
    unsigned long long magnitude = 0;
    for (std::size_t i = limbs_.size(); i-- > 0;) magnitude = (magnitude << 32) | limbs_[i];
    return negative_ ? magnitude <= (1ULL << 63) : magnitude < (1ULL << 63);
}

long long BigInt::to_int64() const {
    unsigned long long magnitude = 0;
    for (std::size_t i = limbs_.size(); i-- > 0;) magnitude = (magnitude << 32) | limbs_[i];
    return negative_ ? static_cast<long long>(0ULL - magnitude) : static_cast<long long>(magnitude);
}

int BigInt::compare_magnitude(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b) {
    if (a.size() != b.size()) return a.size() < b.size() ? -1 : 1;
    for (std::size_t i = a.size(); i-- > 0;)
        if (a[i] != b[i]) return a[i] < b[i] ? -1 : 1;
    return 0;
}

std::vector<std::uint32_t> BigInt::add_magnitude(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b) {
    std::vector<std::uint32_t> out(std::max(a.size(), b.size()) + 1);
    std::uint64_t carry = 0;
    for (std::size_t i = 0; i + 1 < out.size(); ++i) {
        std::uint64_t x = carry + (i < a.size() ? a[i] : 0) + (i < b.size() ? b[i] : 0);
        out[i] = static_cast<std::uint32_t>(x);
        carry = x >> 32;
    }
    out.back() = static_cast<std::uint32_t>(carry);
    return out;
}

// |a| - |b| for |a| >= |b|.
std::vector<std::uint32_t> BigInt::sub_magnitude(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b) {
    std::vector<std::uint32_t> out(a.size());
    std::int64_t borrow = 0;
    for (std::size_t i = 0; i < a.size(); ++i) {
        std::int64_t x = static_cast<std::int64_t>(a[i]) - borrow - (i < b.size() ? b[i] : 0);
        borrow = x < 0;
        out[i] = static_cast<std::uint32_t>(x + (borrow ? (1LL << 32) : 0));
    }
    return out;
}

BigInt operator+(const BigInt& a, const BigInt& b) {
    BigInt out;
    if (a.negative_ == b.negative_) {
        out.limbs_ = BigInt::add_magnitude(a.limbs_, b.limbs_);
        out.negative_ = a.negative_;
    } else if (BigInt::compare_magnitude(a.limbs_, b.limbs_) >= 0) {
        out.limbs_ = BigInt::sub_magnitude(a.limbs_, b.limbs_);
        out.negative_ = a.negative_;
    } else {
        out.limbs_ = BigInt::sub_magnitude(b.limbs_, a.limbs_);
        out.negative_ = b.negative_;
    }
    out.trim();
    return out;
}

BigInt operator-(const BigInt& a, const BigInt& b) {
    BigInt negated = b;
    if (!negated.limbs_.empty()) negated.negative_ = !negated.negative_;
    return a + negated;
}

BigInt operator*(const BigInt& a, const BigInt& b) {
    BigInt out;
    if (a.limbs_.empty() || b.limbs_.empty()) return out;
    out.limbs_.assign(a.limbs_.size() + b.limbs_.size(), 0);
    for (std::size_t i = 0; i < a.limbs_.size(); ++i) {
        std::uint64_t carry = 0;
        for (std::size_t j = 0; j < b.limbs_.size(); ++j) {
            std::uint64_t x = static_cast<std::uint64_t>(a.limbs_[i]) * b.limbs_[j] + out.limbs_[i + j] + carry;
            out.limbs_[i + j] = static_cast<std::uint32_t>(x);
            carry = x >> 32;
        }
        for (std::size_t k = i + b.limbs_.size(); carry; ++k) {
            std::uint64_t x = static_cast<std::uint64_t>(out.limbs_[k]) + carry;
            out.limbs_[k] = static_cast<std::uint32_t>(x);
            carry = x >> 32;
        }
    }
    out.negative_ = a.negative_ != b.negative_;
    out.trim();
    return out;
}

long long BigInt::mod(long long divisor) const {
    std::uint64_t remainder = 0;
    for (std::size_t i = limbs_.size(); i-- > 0;)
        remainder = ((remainder << 32) | limbs_[i]) % static_cast<std::uint64_t>(divisor);
    long long r = static_cast<long long>(remainder);
    return negative_ && r ? divisor - r : r;
}

int compare(const BigInt& a, const BigInt& b) {
    if (a.negative_ != b.negative_) return a.negative_ ? -1 : 1;
    int magnitude = BigInt::compare_magnitude(a.limbs_, b.limbs_);
    return a.negative_ ? -magnitude : magnitude;
}

}  // namespace msf
