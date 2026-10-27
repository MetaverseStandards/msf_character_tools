# SPDX-License-Identifier: MIT
"""Immutable JSON values and the version-one deterministic byte convention."""
from collections.abc import Mapping
from types import MappingProxyType
import errno
import hashlib
import json
import math

from .report import fail

# Sockets and driverless devices fail at open, before fstat can classify them.
SPECIAL_FILE_ERRNOS = frozenset({errno.ENXIO, errno.ENODEV, errno.EOPNOTSUPP})


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


def canonical_json(value):
    return (json.dumps(thaw(value), sort_keys=True, ensure_ascii=False,
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
    result = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid, parse_int=parse_int)
    json_value(result)
    return result
