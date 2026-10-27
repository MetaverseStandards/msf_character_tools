# SPDX-License-Identifier: MIT
"""Strict checks for the sidecar, which stays in Python; the core has its own
copies (core/src/authoring.cpp) with the same codes, refs and messages."""
from collections.abc import Mapping

from .common import number
from .report import fail

# Explicit blank set shared by the authoring/pack 1.0 schema character class.
# Includes the existing control whitespace policy and the U+FEFF format mark.
_BLANK_CHARACTERS = ("\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f\u0020"
                     "\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
                     "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")


def keys(obj, required, optional, ref):
    if not isinstance(obj, Mapping):
        fail("E_TYPE", ref, "Expected an object.")
    if any(type(key) is not str for key in obj):
        fail("E_TYPE", ref, "Object keys must be strings.")
    missing = required - obj.keys()
    extra = obj.keys() - required - optional
    if missing:
        fail("E_REQUIRED", ref, "Missing keys: " + ", ".join(sorted(missing)))
    if extra:
        fail("E_UNKNOWN_KEY", ref, "Unknown keys: " + ", ".join(sorted(extra)))


def string(value, ref):
    if type(value) is not str or not value.strip(_BLANK_CHARACTERS):
        fail("E_TYPE", ref, "Expected a nonempty string.")


def domain(obj, ref):
    keys(obj, set(), {"min", "max"}, ref)
    for k, v in obj.items():
        if not number(v):
            fail("E_TYPE", f"{ref}/{k}", "Domain bounds must be finite numbers.")
    if "min" in obj and "max" in obj and obj["min"] > obj["max"]:
        fail("E_DOMAIN", ref, "Domain minimum exceeds maximum.")
