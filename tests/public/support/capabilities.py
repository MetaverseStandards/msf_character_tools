# SPDX-License-Identifier: MIT
"""What this build of msf-tools can read, asked through the public API rather than by package name.

A format missing here makes its tests skip. Set MSF_REQUIRE_FORMATS (for example
"fbx,usd", as scripts/ci_local.sh does) to make a missing or broken reader fail
instead, so a stale or broken reader cannot pass the suite by skipping.
"""
import os

import msf_character_tools as m

PROBES = {'fbx': b'Kaydara FBX Binary  \x00\x1a\x00', 'usda': b'#usda 1.0\n'}


def reads(fmt):
    missing = [d for d in m.inspect_asset(PROBES[fmt], fmt).report.diagnostics if d.code == 'E_FORMAT_DEPENDENCY']
    required = {name.strip() for name in os.environ.get('MSF_REQUIRE_FORMATS', '').split(',') if name.strip()}
    if missing and ({fmt, fmt.rstrip('a')} & required):
        raise RuntimeError(f'MSF_REQUIRE_FORMATS needs {fmt} support, which did not load: {missing[0].message}')
    return not missing


FBX = reads('fbx')
USD = reads('usda')
