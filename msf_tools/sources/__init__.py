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
