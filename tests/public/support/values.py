# SPDX-License-Identifier: MIT
"""Plain JSON values from records, through the public byte convention."""
import json

import msf_tools as m


def plain(value):
    """`value` as ordinary dicts, lists and numbers, the way `canonical_json` writes it."""
    return json.loads(m.canonical_json(value))
