# SPDX-License-Identifier: MIT
"""Check that this interpreter's link settings can build the extension, and say what to do when they can't."""
import shlex

GUIDANCE = """msf-tools-ufbx could not be built with this Python.

Its build settings (sysconfig LDSHARED and LDFLAGS) point at a toolchain that
is not on this machine. Meta's system python3 is built this way, for example.
Use a standard CPython 3.11 or 3.12 instead: from python.org, Homebrew or pyenv,
or let uv fetch one:

    uv venv --python 3.12 .venv
    source .venv/bin/activate
    uv pip install ./native/ufbx '.[usd,fbx]'
"""


def missing_link_folders(ldshared, ldflags):
    """Relative -L folders in the link settings that do not exist; a hermetic build's paths, unusable here."""
    import os
    words = shlex.split(ldshared or '') + shlex.split(ldflags or '')
    folders = [w[2:] for w in words if w.startswith('-L') and len(w) > 2]
    return [f for f in dict.fromkeys(folders) if not os.path.isabs(f) and not os.path.isdir(f)]
