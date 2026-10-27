# SPDX-License-Identifier: MIT
"""The C++ core, msf_tools._core, which msf-tools needs.

`core` is the core too, unless MSF_TOOLS_PURE=1. Then every input takes the
paths that the core's fast paths otherwise leave to inputs they decline:
Python's json module in parse_json and canonical_json, and the core's exact
mapping evaluation. The suites run that way to keep those paths tested."""
import os

try:
    from . import _core as built
except ImportError as exc:
    raise ImportError("msf_tools._core is not built; see docs/building.md.") from exc
core = None if os.environ.get("MSF_TOOLS_PURE") == "1" else built

# Fixed at import, so records admitted with a handle stay checkable if `core` is swapped out.
HANDLES = (built.CompiledRules, built.Frames, built.Document, built.Snapshot, built.Positions)
