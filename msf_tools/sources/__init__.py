# SPDX-License-Identifier: MIT
"""Source-format adapters that convert a scene into an in-memory GLB.

An adapter provides `name`, `version`, `formats`, `reader()` (the parsing
library and its version) and `convert(data, fmt, resolver, limits, options)`,
which returns `Generated`. The unchanged glTF inspector then admits the GLB,
and the snapshot records the real source in its `source` field.
"""
from __future__ import annotations

from dataclasses import dataclass

SOURCE_FORMATS = ("usd", "usda", "usdc", "usdz", "fbx")
# Generated GLBs may exceed the glTF caps: a face rig with dozens of dense targets
# is already over 4,000,000 decoded components.
GENERATED_MAX_BYTES = 512 * 1024 * 1024
GENERATED_MAX_ACCESSOR_COMPONENTS = 4_000_000
GENERATED_MAX_TOTAL_ACCESSOR_COMPONENTS = 16_000_000


class SourceParseError(Exception):
    """Raised by adapters when the reader rejects the source."""


@dataclass(frozen=True)
class Generated:
    glb: bytes
    node_paths: tuple       # node_paths[i] names the source of glTF node i
    target_keys: tuple      # per glTF mesh, one key per morph target in target order
    dependencies: tuple     # (uri, sha256, byte_length), sorted by uri
    losses: tuple           # Diagnostic objects with warning or info severity


MAX_SOURCE_BYTES_CEILING = 4 * 1024 * 1024 * 1024


class ReaderMismatch(ImportError):
    """An optional reader is installed but does not match this msf-tools; `remediation` says how to fix it."""

    def __init__(self, message, remediation):
        super().__init__(message)
        self.remediation = remediation


@dataclass(frozen=True)
class SourceLimits:
    """Limits for one source inspection; every field is a positive integer.

    The component limits may be lowered but not raised: later integrity checks
    re-validate generated snapshots against the generated defaults.
    `max_usdz_members`, `max_reader_memory` and `timeout_s` are enforced by the
    adapters and by isolated conversion. `max_animation_values` bounds the
    values an adapter samples before converting them: samples (FBX) or time
    codes (USD) x (16 x animated nodes + blend channels).
    """
    max_source_bytes: int = 512 * 1024 * 1024
    max_dependency_bytes: int = 1024 * 1024 * 1024
    max_dependencies: int = 1000
    max_usdz_members: int = 10000
    max_generated_bytes: int = GENERATED_MAX_BYTES
    max_accessor_components: int = GENERATED_MAX_ACCESSOR_COMPONENTS
    max_total_accessor_components: int = GENERATED_MAX_TOTAL_ACCESSOR_COMPONENTS
    max_reader_memory: int = 2 * 1024 * 1024 * 1024
    timeout_s: int = 300
    max_animation_values: int = GENERATED_MAX_TOTAL_ACCESSOR_COMPONENTS

    def __post_init__(self):
        ceilings = {"max_source_bytes": MAX_SOURCE_BYTES_CEILING,
                    "max_accessor_components": GENERATED_MAX_ACCESSOR_COMPONENTS,
                    "max_total_accessor_components": GENERATED_MAX_TOTAL_ACCESSOR_COMPONENTS}
        for name, value in vars(self).items():
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
            if value > ceilings.get(name, value):
                raise ValueError(f"{name} cannot exceed {ceilings[name]}.")
