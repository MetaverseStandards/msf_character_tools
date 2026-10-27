# SPDX-License-Identifier: MIT
"""The optional C++ core. MSF_TOOLS_PURE=1, or a build without it, selects the reference path."""
import os

core = None
if os.environ.get("MSF_TOOLS_PURE") != "1":
    try:
        from . import _core as core
    except ImportError:
        pass

# Fixed at import, so records admitted with a handle stay checkable if `core` is swapped out.
HANDLES = (core.Program, core.Frames) if core is not None else ()
