// SPDX-License-Identifier: MIT
// Exact signed integers for the arithmetic Python does on JSON integers: a
// glTF size or index may carry hundreds of digits, and every comparison must
// come out as it does in Python.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace msf {

class BigInt {
public:
    BigInt() = default;
    BigInt(long long value);  // NOLINT(google-explicit-constructor): ints mix freely, as in Python
    static BigInt from_digits(const std::string& digits);  // "-123"; as json::Value integers carry them

    std::string to_string() const;
    bool fits_int64() const;
    long long to_int64() const;  // requires fits_int64()
    bool negative() const { return negative_; }
    bool zero() const { return limbs_.empty(); }

    friend BigInt operator+(const BigInt& a, const BigInt& b);
    friend BigInt operator-(const BigInt& a, const BigInt& b);
    friend BigInt operator*(const BigInt& a, const BigInt& b);
    // Python's floor modulo by a positive divisor.
    long long mod(long long divisor) const;
    friend int compare(const BigInt& a, const BigInt& b);
    friend bool operator<(const BigInt& a, const BigInt& b) { return compare(a, b) < 0; }
    friend bool operator>(const BigInt& a, const BigInt& b) { return compare(a, b) > 0; }
    friend bool operator<=(const BigInt& a, const BigInt& b) { return compare(a, b) <= 0; }
    friend bool operator>=(const BigInt& a, const BigInt& b) { return compare(a, b) >= 0; }
    friend bool operator==(const BigInt& a, const BigInt& b) { return compare(a, b) == 0; }
    friend bool operator!=(const BigInt& a, const BigInt& b) { return compare(a, b) != 0; }

private:
    bool negative_ = false;
    std::vector<std::uint32_t> limbs_;  // magnitude, base 2**32, least significant first, no trailing zeros
    void trim();
    static int compare_magnitude(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b);
    static std::vector<std::uint32_t> add_magnitude(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b);
    static std::vector<std::uint32_t> sub_magnitude(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b);
};

}  // namespace msf
