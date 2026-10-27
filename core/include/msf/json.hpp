// SPDX-License-Identifier: MIT
// Strict JSON, as msf-tools reads and writes it in Python:
// parse() accepts what common.parse_json accepts (json.loads with duplicate-key,
// constant and 309-digit hooks, then the json_value limits) and write_canonical()
// produces common.canonical_json's bytes (sort_keys, ensure_ascii=False, indent=2,
// newline, -0.0 written as 0.0).
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace msf::json {

struct Value {
    enum class Kind : std::uint8_t { null, boolean, integer, real, string, array, object };
    Kind kind = Kind::null;
    bool boolean = false;
    // real: the value. integer: the value rounded to binary64, infinite when it
    // exceeds binary64's range.
    double number = 0.0;
    // integer: canonical decimal digits ("-12", never "-0"). real: the lexeme
    // as parsed, empty for values not built by parse(). string: WTF-8, which is
    // UTF-8 plus lone surrogates encoded as three bytes.
    std::string text;
    std::vector<Value> items;
    std::vector<std::pair<std::string, Value>> members;  // in input order

    static Value null_value() { return Value{}; }
    static Value make_boolean(bool b);
    static Value make_real(double d);
    static Value make_integer(std::string digits);
    static Value make_string(std::string wtf8);
};

// Containers nested deeper than this are refused, here and on the Python path
// (common.MAX_NESTING), where the refusal used to depend on the stack. The
// json_value limit (128) is below it.
constexpr int kMaxNesting = 200;
inline const char* const kTooDeep = "JSON nesting exceeds 200 levels.";

struct ParseOutcome {
    enum class Status {
        ok,
        syntax,         // not JSON: the caller reports it as Python's json does
        constant,       // NaN, Infinity or -Infinity; detail is the constant
        duplicate_key,  // detail is the key (WTF-8), found when its object closed
        too_deep,       // a container opened past kMaxNesting
    } status = Status::ok;
    std::string detail;
    Value value;
};

// `text` must be valid WTF-8 without a byte order mark (validate_wtf8). Raises
// msf::Fault for the json_value limits (E_RESOURCE_LIMIT, E_NONFINITE), checked
// after a successful parse in document order.
ParseOutcome parse(std::string_view text);

// True when `text` is UTF-8 in which surrogate code points may also appear,
// which is what Python's 'surrogatepass' decoder accepts.
bool validate_wtf8(std::string_view text);
bool has_surrogate(std::string_view wtf8);

// Throws std::domain_error for non-finite reals and strings with lone surrogates,
// which Python refuses on write.
std::string write_canonical(const Value& value);

// Python's repr(float) for a finite double.
std::string python_repr(double value);
void append_python_repr(std::string& out, double value);

// The value of a JSON number lexeme as an integer, if exact: "1.0" and "1e2"
// give "1" and "100", "1.5" gives false. Decimal's to_integral_value test,
// without binary64 rounding. The lexeme must be a valid JSON number whose
// value parses to a finite binary64.
bool exact_integer(std::string_view lexeme, std::string& digits);

// The binary32 nearest `value`, false when it rounds past FLT_MAX; checked
// before the cast, which would otherwise be undefined.
bool to_float32(double value, float& out);

}  // namespace msf::json
