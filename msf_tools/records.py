# SPDX-License-Identifier: MIT
"""Factory ownership and consistency for records crossing public boundaries.

This protects API invariants, not a process from code using private internals.
Admission is reset by dataclasses.replace; admission alone is never the check.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
import hashlib
import struct
from types import MappingProxyType

from .report import fail


def _owned(value):
    if isinstance(value, OwnedRecord):
        value._check_integrity()
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({k: _owned(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_owned(v) for v in value)
    if is_dataclass(value):
        if not value.__dataclass_params__.frozen:
            fail("E_RECORD_INTEGRITY", "/", "Nested records must be immutable.")
        return replace(value, **{f.name: _owned(getattr(value, f.name)) for f in fields(value)})
    if type(value) not in (str, bytes, int, float, bool, type(None)):
        fail("E_RECORD_INTEGRITY", "/", "Unsupported record state.")
    return value


def _fingerprint(record):
    """Hash typed stored state without invoking public exports or copying bytes."""
    hasher = hashlib.sha256()

    def emit(tag, data=b""):
        hasher.update(tag)
        hasher.update(struct.pack(">Q", len(data)))
        hasher.update(data)

    def visit(value, depth=0):
        if depth > 128:
            fail("E_RECORD_INTEGRITY", "/", "Record state exceeds supported nesting.")
        if isinstance(value, OwnedRecord):
            if value is not record:
                value._check_integrity()
                emit(b"nested_record", type(value).__name__.encode())
                emit(b"digest", value._integrity.encode())
                return
            emit(b"record", type(value).__name__.encode())
            for f in fields(value):
                if f.name not in {"_integrity", "_record_id", "_token"}:
                    emit(b"field", f.name.encode())
                    # The record wrapper is not an additional JSON nesting level.
                    visit(getattr(value, f.name), depth)
        elif is_dataclass(value) and value.__dataclass_params__.frozen:
            emit(b"data", type(value).__name__.encode())
            for f in fields(value):
                emit(b"field", f.name.encode())
                visit(getattr(value, f.name), depth + 1)
        elif type(value) is MappingProxyType:
            emit(b"map", struct.pack(">Q", len(value)))
            for key, item in value.items():
                visit(key, depth + 1)
                visit(item, depth + 1)
        elif type(value) is tuple:
            emit(b"tuple", struct.pack(">Q", len(value)))
            for item in value:
                visit(item, depth + 1)
        elif value is None:
            emit(b"none")
        elif type(value) is bool:
            emit(b"bool", bytes([value]))
        elif type(value) is int:
            # Binary encoding avoids Python's decimal conversion digit ceiling.
            size = max(1, (value.bit_length() + 8) // 8)
            emit(b"int", value.to_bytes(size, "big", signed=True))
        elif type(value) is float:
            emit(b"float", struct.pack(">d", value))
        elif type(value) is str:
            emit(b"str", value.encode("utf-8"))
        elif type(value) is bytes:
            emit(b"bytes", value)
        else:
            fail("E_RECORD_INTEGRITY", "/", "Record contains mutable or unsupported state.")

    visit(record)
    return hasher.hexdigest()


@dataclass(frozen=True)
class OwnedRecord:
    _integrity: str | None = field(default=None, init=False, repr=False, compare=False)
    _record_id: int | None = field(default=None, init=False, repr=False, compare=False)

    def _check_integrity(self):
        if self._record_id != id(self) or self._integrity is None or self._integrity != _fingerprint(self):
            fail("E_RECORD_INTEGRITY", "/", "Record is unadmitted or its owned state changed.",
                 "Recreate the record using its public validation/compilation factory.")
        self._check_consistency()

    def _check_consistency(self):
        """Specialized records also bind stored identities to their sources."""


def _admit(record):
    """Called only after the factory has validated every semantic input."""
    for f in fields(record):
        if f.name not in {"_integrity", "_record_id", "_token"}:
            object.__setattr__(record, f.name, _owned(getattr(record, f.name)))
    object.__setattr__(record, "_integrity", _fingerprint(record))
    object.__setattr__(record, "_record_id", id(record))
    record._check_integrity()
    return record
