# SPDX-License-Identifier: MIT
"""The C++ core. `built` is the extension; `core` is it too unless MSF_TOOLS_PURE=1
selects the reference path for the modules that still have one."""
import os

try:
    from . import _core as built
except ImportError:
    built = None
core = built if os.environ.get("MSF_TOOLS_PURE") != "1" else None

# Fixed at import, so records admitted with a handle stay checkable if `core` is swapped out.
HANDLES = ((built.CompiledRules, built.Frames, built.Document, built.Snapshot, built.Positions)
           if built is not None else ())


def required():
    """The extension, for modules whose only implementation is in the core."""
    if built is None:
        raise ImportError("msf_tools._core is not built; see docs/building.md.")
    return built
