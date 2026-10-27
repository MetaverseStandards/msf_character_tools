# SPDX-License-Identifier: MIT
"""Immutable JSON values and the version-one deterministic byte convention."""
from collections.abc import Mapping
from types import MappingProxyType
import errno
import hashlib
import json
import math

from . import _native
from .report import fail

# Sockets and driverless devices fail at open, before fstat can classify them.
SPECIAL_FILE_ERRNOS = frozenset({errno.ENXIO, errno.ENODEV, errno.EOPNOTSUPP})
_UTF8 = {"utf-8", "utf-8-sig"}
# canonical_json and parse_json refuse containers nested deeper than this, on
# both the core and the Python path, with RecursionError(TOO_DEEP).
MAX_NESTING = 200
TOO_DEEP = f"JSON nesting exceeds {MAX_NESTING} levels."


def freeze(x):
    if isinstance(x, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in x.items()})
    if isinstance(x, (tuple, list)):
        return tuple(freeze(v) for v in x)
    return x


def thaw(x):
    if hasattr(x, "to_dict"):
        return thaw(x.to_dict())
    if isinstance(x, Mapping):
        return {k: thaw(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return [thaw(v) for v in x]
    if isinstance(x, float) and x == 0.0:
        return 0.0
    return x


def _thaw_limited(x, depth=0):
    """thaw, refusing containers nested deeper than MAX_NESTING."""
    if hasattr(x, "to_dict"):
        return _thaw_limited(x.to_dict(), depth)
    if isinstance(x, Mapping):
        if depth >= MAX_NESTING:
            raise RecursionError(TOO_DEEP)
        return {k: _thaw_limited(v, depth + 1) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        if depth >= MAX_NESTING:
            raise RecursionError(TOO_DEEP)
        return [_thaw_limited(v, depth + 1) for v in x]
    if isinstance(x, float) and x == 0.0:
        return 0.0
    return x


def _too_deep_at(text):
    """Index of the first bracket opening a container past MAX_NESTING, outside strings, or None."""
    if text.count("[") + text.count("{") <= MAX_NESTING:
        return None
    depth, in_string, escaped = 0, False, False
    for i, c in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c in "[{":
            depth += 1
            if depth > MAX_NESTING:
                return i
        elif c in "]}":
            depth -= 1
    return None


def canonical_json(value):
    if _native.core is not None:
        # None: a value only the reference path below can write or refuse exactly.
        raw = _native.core.canonical_json(value)
        if raw is not None:
            return raw
    return (json.dumps(_thaw_limited(value), sort_keys=True, ensure_ascii=False,
                       allow_nan=False, indent=2) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def integer(value):
    return type(value) is int


def json_value(value, ref="/", depth=0):
    if depth > 128:
        fail("E_RESOURCE_LIMIT", ref, "JSON nesting exceeds 128 levels.")
    if value is None or type(value) in (str, bool):
        return
    if type(value) in (float, int):
        if not number(value):
            fail("E_NONFINITE", ref, "Numbers must be finite binary64 values.")
        return
    if isinstance(value, Mapping):
        for key, v in value.items():
            if type(key) is not str:
                fail("E_TYPE", ref, "Object keys must be strings.")
            json_value(v, f"{'' if ref == '/' else ref}/{key}", depth + 1)
        return
    if isinstance(value, (tuple, list)):
        for i, v in enumerate(value):
            json_value(v, f"{'' if ref == '/' else ref}/{i}", depth + 1)
        return
    fail("E_TYPE", ref, "Expected a JSON-compatible value.")


def parse_json(data):
    if _native.core is not None and (type(data) is str or type(data) is bytes and json.detect_encoding(data) in _UTF8):
        # None: input only the reference path below reports exactly, such as invalid JSON.
        parsed = _native.core.parse_json(data)
        if parsed is not None:
            return parsed[0]
    def parse_int(text):
        # More than 309 significant decimal digits cannot fit binary64. Avoid
        # Python's decimal integer digit ceiling and let json_value report its path.
        if len(text.lstrip("-")) > 309:
            return -math.inf if text.startswith("-") else math.inf
        return int(text)
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                fail("E_DUPLICATE_KEY", "/", f"Duplicate JSON key {k!r}.")
            out[k] = v
        return out
    def invalid(value):
        fail("E_NONFINITE", "/", f"Invalid JSON constant {value}.")
    text = data.decode(json.detect_encoding(data), "surrogatepass") if isinstance(data, (bytes, bytearray)) else data
    cut = _too_deep_at(text) if type(text) is str else None
    if cut is not None:
        # Errors before the over-deep container still come first, as in json.loads.
        try:
            json.loads(text[:cut], object_pairs_hook=pairs, parse_constant=invalid, parse_int=parse_int)
        except json.JSONDecodeError as exc:
            if exc.pos < cut:
                raise
        raise RecursionError(TOO_DEEP)
    result = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid, parse_int=parse_int)
    json_value(result)
    return result
