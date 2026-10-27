// SPDX-License-Identifier: MIT
#include "msf/json.hpp"

#include <algorithm>
#include <cfloat>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <unordered_set>

#include "fast_float/fast_float.h"
#include "msf/diagnostics.hpp"
#include "ryu/ryu.h"

namespace msf::json {

Value Value::make_boolean(bool b) {
    Value v;
    v.kind = Kind::boolean;
    v.boolean = b;
    return v;
}

Value Value::make_real(double d) {
    Value v;
    v.kind = Kind::real;
    v.number = d;
    return v;
}

Value Value::make_integer(std::string digits) {
    Value v;
    v.kind = Kind::integer;
    // Correctly rounded like Python's int-to-float; infinite past binary64's range.
    fast_float::from_chars(digits.data(), digits.data() + digits.size(), v.number);
    v.text = std::move(digits);
    return v;
}

Value Value::make_string(std::string wtf8) {
    Value v;
    v.kind = Kind::string;
    v.text = std::move(wtf8);
    return v;
}

// ---------------------------------------------------------------- encoding

namespace {

void append_code_point(std::string& out, std::uint32_t c) {
    if (c < 0x80) {
        out += static_cast<char>(c);
    } else if (c < 0x800) {
        out += static_cast<char>(0xC0 | (c >> 6));
        out += static_cast<char>(0x80 | (c & 0x3F));
    } else if (c < 0x10000) {
        out += static_cast<char>(0xE0 | (c >> 12));
        out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (c & 0x3F));
    } else {
        out += static_cast<char>(0xF0 | (c >> 18));
        out += static_cast<char>(0x80 | ((c >> 12) & 0x3F));
        out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (c & 0x3F));
    }
}

}  // namespace

bool validate_wtf8(std::string_view text) {
    const auto* s = reinterpret_cast<const unsigned char*>(text.data());
    std::size_t n = text.size(), i = 0;
    while (i < n) {
        unsigned char c = s[i];
        if (c < 0x80) {
            ++i;
            continue;
        }
        std::size_t len;
        unsigned char lo = 0x80, hi = 0xBF;
        if (c >= 0xC2 && c <= 0xDF) {
            len = 2;
        } else if (c >= 0xE0 && c <= 0xEF) {
            len = 3;
            if (c == 0xE0) lo = 0xA0;  // no overlong forms; 0xED keeps surrogates (surrogatepass)
        } else if (c >= 0xF0 && c <= 0xF4) {
            len = 4;
            if (c == 0xF0) lo = 0x90;
            if (c == 0xF4) hi = 0x8F;
        } else {
            return false;
        }
        if (i + len > n || s[i + 1] < lo || s[i + 1] > hi) return false;
        for (std::size_t k = 2; k < len; ++k)
            if (s[i + k] < 0x80 || s[i + k] > 0xBF) return false;
        i += len;
    }
    return true;
}

bool has_surrogate(std::string_view wtf8) {
    for (std::size_t i = 0; i + 1 < wtf8.size(); ++i)
        if (static_cast<unsigned char>(wtf8[i]) == 0xED && static_cast<unsigned char>(wtf8[i + 1]) >= 0xA0) return true;
    return false;
}

// ---------------------------------------------------------------- parsing

namespace {

using Status = ParseOutcome::Status;

struct Abort {
    Status status;
    std::string detail;
};

int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool is_digit(char c) { return c >= '0' && c <= '9'; }

class Parser {
public:
    explicit Parser(std::string_view text) : p_(text.data()), end_(text.data() + text.size()) {}

    Value document() {
        skip_space();
        Value v = value(0);
        skip_space();
        if (p_ != end_) syntax();
        return v;
    }

private:
    const char* p_;
    const char* end_;

    [[noreturn]] static void syntax() { throw Abort{Status::syntax, {}}; }

    void skip_space() {
        while (p_ < end_ && (*p_ == ' ' || *p_ == '\t' || *p_ == '\n' || *p_ == '\r')) ++p_;
    }

    bool literal(std::string_view word) {
        if (static_cast<std::size_t>(end_ - p_) >= word.size() && std::memcmp(p_, word.data(), word.size()) == 0) {
            p_ += word.size();
            return true;
        }
        return false;
    }

    Value value(int depth) {
        if (p_ == end_) syntax();
        switch (*p_) {
            case '"':
                ++p_;
                return Value::make_string(string());
            case '{':
                return object(depth + 1);
            case '[':
                return array(depth + 1);
            case 'n':
                if (literal("null")) return Value::null_value();
                syntax();
            case 't':
                if (literal("true")) return Value::make_boolean(true);
                syntax();
            case 'f':
                if (literal("false")) return Value::make_boolean(false);
                syntax();
            case 'N':
                if (literal("NaN")) throw Abort{Status::constant, "NaN"};
                syntax();
            case 'I':
                if (literal("Infinity")) throw Abort{Status::constant, "Infinity"};
                syntax();
            case '-':
                if (literal("-Infinity")) throw Abort{Status::constant, "-Infinity"};
                return number();
            default:
                return number();
        }
    }

    // json's NUMBER_RE, -?(0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?, backtracking
    // over a bare fraction point or exponent marker as its C scanner does.
    Value number() {
        const char* start = p_;
        if (p_ < end_ && *p_ == '-') ++p_;
        if (p_ < end_ && *p_ >= '1' && *p_ <= '9') {
            while (p_ < end_ && is_digit(*p_)) ++p_;
        } else if (p_ < end_ && *p_ == '0') {
            ++p_;
        } else {
            syntax();
        }
        const char* int_end = p_;
        bool real = false;
        if (end_ - p_ >= 2 && *p_ == '.' && is_digit(p_[1])) {
            real = true;
            p_ += 2;
            while (p_ < end_ && is_digit(*p_)) ++p_;
        }
        if (p_ < end_ && (*p_ == 'e' || *p_ == 'E')) {
            const char* e = p_++;
            if (p_ < end_ && (*p_ == '-' || *p_ == '+')) ++p_;
            const char* digits = p_;
            while (p_ < end_ && is_digit(*p_)) ++p_;
            if (p_ == digits)
                p_ = e;
            else
                real = true;
        }
        std::string lexeme(start, p_);
        if (real) {
            Value v = Value::make_real(0.0);
            // Correctly rounded like float(); out of range gives inf or a signed zero.
            fast_float::from_chars(lexeme.data(), lexeme.data() + lexeme.size(), v.number);
            v.text = std::move(lexeme);
            return v;
        }
        std::size_t digits = static_cast<std::size_t>(int_end - start) - (*start == '-' ? 1 : 0);
        if (digits > 309) {
            // common.parse_json's parse_int: more digits than binary64 can hold.
            Value v = Value::make_real(*start == '-' ? -HUGE_VAL : HUGE_VAL);
            v.text = std::move(lexeme);
            return v;
        }
        if (lexeme == "-0") lexeme = "0";
        return Value::make_integer(std::move(lexeme));
    }

    std::string string() {
        std::string out;
        for (;;) {
            const char* run = p_;
            while (p_ < end_ && *p_ != '"' && *p_ != '\\' && static_cast<unsigned char>(*p_) >= 0x20) ++p_;
            out.append(run, p_);
            if (p_ == end_ || static_cast<unsigned char>(*p_) < 0x20) syntax();
            if (*p_ == '"') {
                ++p_;
                return out;
            }
            ++p_;  // backslash
            if (p_ == end_) syntax();
            char c = *p_++;
            switch (c) {
                case '"': out += '"'; break;
                case '\\': out += '\\'; break;
                case '/': out += '/'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'n': out += '\n'; break;
                case 'r': out += '\r'; break;
                case 't': out += '\t'; break;
                case 'u': {
                    std::uint32_t cp = hex4();
                    // A high surrogate joins a following \u low surrogate. Any other
                    // following \uXXXX is decoded on its own, but must still be hex.
                    if (cp >= 0xD800 && cp <= 0xDBFF && end_ - p_ >= 6 && p_[0] == '\\' && p_[1] == 'u') {
                        const char* save = p_;
                        p_ += 2;
                        std::uint32_t low = hex4();
                        if (low >= 0xDC00 && low <= 0xDFFF)
                            cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                        else
                            p_ = save;
                    }
                    append_code_point(out, cp);
                    break;
                }
                default:
                    syntax();
            }
        }
    }

    std::uint32_t hex4() {
        if (end_ - p_ < 4) syntax();
        std::uint32_t cp = 0;
        for (int k = 0; k < 4; ++k) {
            int h = hex_value(p_[k]);
            if (h < 0) syntax();
            cp = (cp << 4) | static_cast<std::uint32_t>(h);
        }
        p_ += 4;
        return cp;
    }

    Value object(int depth) {
        if (depth > kMaxNesting) throw Abort{Status::too_deep, {}};
        ++p_;
        Value v;
        v.kind = Value::Kind::object;
        skip_space();
        if (p_ < end_ && *p_ == '}') {
            ++p_;
            return v;
        }
        for (;;) {
            if (p_ == end_ || *p_ != '"') syntax();
            ++p_;
            std::string key = string();
            skip_space();
            if (p_ == end_ || *p_ != ':') syntax();
            ++p_;
            skip_space();
            v.members.emplace_back(std::move(key), value(depth));
            skip_space();
            if (p_ < end_ && *p_ == '}') {
                ++p_;
                break;
            }
            if (p_ == end_ || *p_ != ',') syntax();
            ++p_;
            skip_space();
        }
        check_duplicates(v);
        return v;
    }

    // As parse_json's object_pairs_hook: when the object closes, the first key
    // seen before.
    static void check_duplicates(const Value& v) {
        std::unordered_set<std::string_view> seen;
        seen.reserve(v.members.size());
        for (const auto& member : v.members)
            if (!seen.insert(member.first).second) throw Abort{Status::duplicate_key, member.first};
    }

    Value array(int depth) {
        if (depth > kMaxNesting) throw Abort{Status::too_deep, {}};
        ++p_;
        Value v;
        v.kind = Value::Kind::array;
        skip_space();
        if (p_ < end_ && *p_ == ']') {
            ++p_;
            return v;
        }
        for (;;) {
            v.items.push_back(value(depth));
            skip_space();
            if (p_ < end_ && *p_ == ']') {
                ++p_;
                break;
            }
            if (p_ == end_ || *p_ != ',') syntax();
            ++p_;
            skip_space();
        }
        return v;
    }
};

std::string child_ref(const std::string& ref, std::string_view key) {
    std::string out = ref == "/" ? std::string() : ref;
    out += '/';
    out += key;
    return out;
}

// common.json_value, in its order: depth before type, depth first.
void check_limits(const Value& v, const std::string& ref, int depth) {
    if (depth > 128) fail(Code::E_RESOURCE_LIMIT, ref, "JSON nesting exceeds 128 levels.");
    switch (v.kind) {
        case Value::Kind::integer:
        case Value::Kind::real:
            if (!std::isfinite(v.number)) fail(Code::E_NONFINITE, ref, "Numbers must be finite binary64 values.");
            break;
        case Value::Kind::object:
            for (const auto& [key, child] : v.members) check_limits(child, child_ref(ref, key), depth + 1);
            break;
        case Value::Kind::array:
            for (std::size_t i = 0; i < v.items.size(); ++i) check_limits(v.items[i], child_ref(ref, std::to_string(i)), depth + 1);
            break;
        default:
            break;
    }
}

}  // namespace

ParseOutcome parse(std::string_view text) {
    ParseOutcome out;
    try {
        out.value = Parser(text).document();
    } catch (Abort& abort) {
        out.status = abort.status;
        out.detail = std::move(abort.detail);
        return out;
    }
    check_limits(out.value, "/", 0);
    return out;
}

// ---------------------------------------------------------------- writing

void append_python_repr(std::string& out, double value) {
    // Ryu prints the shortest round-tripping digits as d[.ddd]E[-]x; Python's
    // repr lays the same digits out as float_repr_style 'short' does.
    char buf[32];
    int n = d2s_buffered_n(value, buf);
    std::string_view s(buf, static_cast<std::size_t>(n));
    std::size_t i = 0;
    if (s[0] == '-') {
        out += '-';
        i = 1;
    }
    std::size_t e = s.find('E');
    std::string digits;
    for (std::size_t k = i; k < e; ++k)
        if (s[k] != '.') digits += s[k];
    int exponent = std::stoi(std::string(s.substr(e + 1)));
    int decpt = exponent + 1;  // value = 0.DIGITS * 10**decpt
    int count = static_cast<int>(digits.size());
    if (decpt <= -4 || decpt > 16) {
        out += digits[0];
        if (count > 1) {
            out += '.';
            out.append(digits, 1, std::string::npos);
        }
        int x = decpt - 1;
        out += 'e';
        out += x < 0 ? '-' : '+';
        if (std::abs(x) < 10) out += '0';
        out += std::to_string(std::abs(x));
    } else if (decpt <= 0) {
        out += "0.";
        out.append(static_cast<std::size_t>(-decpt), '0');
        out += digits;
    } else if (decpt < count) {
        out.append(digits, 0, static_cast<std::size_t>(decpt));
        out += '.';
        out.append(digits, static_cast<std::size_t>(decpt), std::string::npos);
    } else {
        out += digits;
        out.append(static_cast<std::size_t>(decpt - count), '0');
        out += ".0";
    }
}

std::string python_repr(double value) {
    std::string out;
    append_python_repr(out, value);
    return out;
}

namespace {

void append_string(std::string& out, const std::string& s, bool wtf8) {
    if (!wtf8 && has_surrogate(s)) throw std::domain_error("strings with lone surrogates cannot be encoded as UTF-8");
    static const char hex[] = "0123456789abcdef";
    out += '"';
    for (char ch : s) {
        auto c = static_cast<unsigned char>(ch);
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    out += "\\u00";
                    out += hex[c >> 4];
                    out += hex[c & 0xF];
                } else {
                    out += ch;
                }
        }
    }
    out += '"';
}

void write(std::string& out, const Value& v, int level, bool wtf8) {
    switch (v.kind) {
        case Value::Kind::null: out += "null"; return;
        case Value::Kind::boolean: out += v.boolean ? "true" : "false"; return;
        case Value::Kind::integer: out += v.text; return;
        case Value::Kind::real:
            if (!std::isfinite(v.number)) throw std::domain_error("Out of range float values are not JSON compliant");
            // common.thaw writes -0.0 as 0.0.
            if (v.number == 0.0)
                out += "0.0";
            else
                append_python_repr(out, v.number);
            return;
        case Value::Kind::string: append_string(out, v.text, wtf8); return;
        case Value::Kind::array: {
            if (v.items.empty()) {
                out += "[]";
                return;
            }
            out += '[';
            for (std::size_t i = 0; i < v.items.size(); ++i) {
                out += i ? ",\n" : "\n";
                out.append(static_cast<std::size_t>(2 * (level + 1)), ' ');
                write(out, v.items[i], level + 1, wtf8);
            }
            out += '\n';
            out.append(static_cast<std::size_t>(2 * level), ' ');
            out += ']';
            return;
        }
        case Value::Kind::object: {
            if (v.members.empty()) {
                out += "{}";
                return;
            }
            std::vector<const std::pair<std::string, Value>*> sorted;
            sorted.reserve(v.members.size());
            for (const auto& m : v.members) sorted.push_back(&m);
            // Byte order of UTF-8 is code point order, which is how Python sorts str.
            std::sort(sorted.begin(), sorted.end(), [](auto* a, auto* b) { return a->first < b->first; });
            out += '{';
            for (std::size_t i = 0; i < sorted.size(); ++i) {
                out += i ? ",\n" : "\n";
                out.append(static_cast<std::size_t>(2 * (level + 1)), ' ');
                append_string(out, sorted[i]->first, wtf8);
                out += ": ";
                write(out, sorted[i]->second, level + 1, wtf8);
            }
            out += '\n';
            out.append(static_cast<std::size_t>(2 * level), ' ');
            out += '}';
            return;
        }
        case Value::Kind::other:
            throw std::domain_error("value without a JSON type");
    }
}

}  // namespace

namespace {

void write_compact(std::string& out, const Value& v) {
    switch (v.kind) {
        case Value::Kind::null: out += "null"; return;
        case Value::Kind::boolean: out += v.boolean ? "true" : "false"; return;
        case Value::Kind::integer: out += v.text; return;
        case Value::Kind::real:
            if (!std::isfinite(v.number)) throw std::domain_error("Out of range float values are not JSON compliant");
            append_python_repr(out, v.number);
            return;
        case Value::Kind::string:
            out += '"';
            for (char ch : v.text) {
                if (ch == '"' || ch == '\\') out += '\\';
                out += ch;
            }
            out += '"';
            return;
        case Value::Kind::array:
            out += v.is_list ? '[' : '(';
            for (std::size_t i = 0; i < v.items.size(); ++i) {
                if (i) out += ',';
                write_compact(out, v.items[i]);
            }
            out += v.is_list ? ']' : ')';
            return;
        case Value::Kind::object:
            out += '{';
            for (std::size_t i = 0; i < v.members.size(); ++i) {
                if (i) out += ',';
                write_compact(out, Value::make_string(v.members[i].first));
                out += ':';
                write_compact(out, v.members[i].second);
            }
            out += '}';
            return;
        case Value::Kind::other:
            throw std::domain_error("value without a JSON type");
    }
}

}  // namespace

std::string write_exact(const Value& value) {
    std::string out;
    write_compact(out, value);
    return out;
}

std::string write_canonical(const Value& value, bool allow_surrogates) {
    std::string out;
    write(out, value, 0, allow_surrogates);
    out += '\n';
    return out;
}

// ---------------------------------------------------------------- lookups

const Value* find(const Value& object, std::string_view key) {
    for (const auto& member : object.members)
        if (member.first == key) return &member.second;
    return nullptr;
}

namespace {

// Decimal digits of a finite, integer-valued double of magnitude >= 2**53.
std::string integer_digits(double value) {
    int exponent;
    double mantissa = std::frexp(std::fabs(value), &exponent);
    auto bits = static_cast<std::uint64_t>(std::ldexp(mantissa, 53));
    exponent -= 53;
    std::vector<std::uint32_t> limbs;  // base 10**9, least significant first
    for (; bits; bits /= 1000000000U) limbs.push_back(static_cast<std::uint32_t>(bits % 1000000000U));
    for (int i = 0; i < exponent; ++i) {
        std::uint64_t carry = 0;
        for (auto& limb : limbs) {
            std::uint64_t x = static_cast<std::uint64_t>(limb) * 2 + carry;
            limb = static_cast<std::uint32_t>(x % 1000000000U);
            carry = x / 1000000000U;
        }
        if (carry) limbs.push_back(static_cast<std::uint32_t>(carry));
    }
    std::string out = value < 0 ? "-" : "";
    out += std::to_string(limbs.back());
    for (std::size_t i = limbs.size() - 1; i-- > 0;) {
        std::string part = std::to_string(limbs[i]);
        out.append(9 - part.size(), '0');
        out += part;
    }
    return out;
}

int compare_digits(const std::string& a, const std::string& b) {
    bool na = !a.empty() && a[0] == '-', nb = !b.empty() && b[0] == '-';
    if (na != nb) return na ? -1 : 1;
    std::size_t la = a.size() - na, lb = b.size() - nb;
    int magnitude = la != lb ? (la < lb ? -1 : 1) : a.compare(na, std::string::npos, b, nb, std::string::npos);
    magnitude = magnitude < 0 ? -1 : magnitude > 0 ? 1 : 0;
    return na ? -magnitude : magnitude;
}

int compare_int_real(const Value& i, double f) {
    double r = i.number;  // correctly rounded, so on the same side of f unless equal
    if (r < f) return -1;
    if (r > f) return 1;
    if (std::fabs(f) < 9007199254740992.0) return 0;
    return compare_digits(i.text, integer_digits(f));
}

}  // namespace

int compare_numbers(const Value& a, const Value& b) {
    bool ai = a.kind == Value::Kind::integer, bi = b.kind == Value::Kind::integer;
    if (ai && bi) return compare_digits(a.text, b.text);
    if (ai) return compare_int_real(a, b.number);
    if (bi) return -compare_int_real(b, a.number);
    return a.number < b.number ? -1 : a.number > b.number ? 1 : 0;
}

// ---------------------------------------------------------------- numbers

bool exact_integer(std::string_view lexeme, std::string& digits) {
    std::size_t i = 0;
    bool negative = !lexeme.empty() && lexeme[0] == '-';
    if (negative) ++i;
    std::string mantissa;
    long long scale = 0;
    for (; i < lexeme.size() && is_digit(lexeme[i]); ++i) mantissa += lexeme[i];
    if (i < lexeme.size() && lexeme[i] == '.') {
        for (++i; i < lexeme.size() && is_digit(lexeme[i]); ++i) {
            mantissa += lexeme[i];
            --scale;
        }
    }
    if (i < lexeme.size() && (lexeme[i] == 'e' || lexeme[i] == 'E')) {
        ++i;
        bool minus = i < lexeme.size() && lexeme[i] == '-';
        if (i < lexeme.size() && (lexeme[i] == '-' || lexeme[i] == '+')) ++i;
        long long x = 0;
        for (; i < lexeme.size() && is_digit(lexeme[i]); ++i) x = std::min(x * 10 + (lexeme[i] - '0'), 1000000000LL);
        scale += minus ? -x : x;
    }
    std::size_t first = mantissa.find_first_not_of('0');
    if (first == std::string::npos) {
        digits = "0";
        return true;
    }
    mantissa.erase(0, first);
    while (mantissa.back() == '0') {
        mantissa.pop_back();
        ++scale;
    }
    // A finite binary64 has at most 309 integer digits.
    if (scale < 0 || static_cast<long long>(mantissa.size()) + scale > 400) return false;
    digits = negative ? "-" : "";
    digits += mantissa;
    digits.append(static_cast<std::size_t>(scale), '0');
    return true;
}

bool to_float32(double value, float& out) {
    if (std::isnan(value)) {
        out = std::numeric_limits<float>::quiet_NaN();
        return true;
    }
    double magnitude = std::fabs(value);
    // Halfway between FLT_MAX and 2**128 rounds to even, which is infinity.
    constexpr double kOverflow = 340282356779733661637539395458142568448.0;  // 2**128 - 2**103
    if (std::isinf(value)) {
        out = static_cast<float>(value);
    } else if (magnitude >= kOverflow) {
        return false;
    } else if (magnitude > FLT_MAX) {
        out = std::copysign(FLT_MAX, static_cast<float>(value > 0 ? 1 : -1));
    } else {
        out = static_cast<float>(value);
    }
    return true;
}

}  // namespace msf::json
