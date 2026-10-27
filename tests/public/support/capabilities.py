# SPDX-License-Identifier: MIT
"""What this build of msf-tools can read, asked through the public API rather than by package name."""
import msf_tools as m


def reads(fmt, data):
    return not any(d.code == 'E_FORMAT_DEPENDENCY' for d in m.inspect_asset(data, fmt).report.diagnostics)


FBX = reads('fbx', b'Kaydara FBX Binary  \x00\x1a\x00')
