# SPDX-License-Identifier: MIT
"""The format seam: generated snapshots, source identity and sidecar binding."""
from pathlib import Path
import unittest

import msf_tools as m
from msf_tools import snapshot as snapshots
from msf_tools.report import Fault

ROOT = Path(__file__).resolve().parents[1]
COMBINED = (ROOT / 'tests/fixtures/combined.gltf').read_bytes()


def refusal(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
    except Fault as exc:
        return [(exc.diagnostic.code, exc.diagnostic.ref)]
    return [(d.code, d.ref) for d in result.report.diagnostics if d.severity == 'error']


class GltfInspectionLimits(unittest.TestCase):
    def test_byte_and_component_limits_are_parameters(self):
        inspect = snapshots._inspect_gltf
        self.assertEqual(refusal(inspect, COMBINED, 'gltf', None, None, max_asset_bytes=len(COMBINED)), [])
        self.assertEqual(refusal(inspect, COMBINED, 'gltf', None, None, max_asset_bytes=len(COMBINED) - 1),
                         [('E_RESOURCE_LIMIT', '/')])
        self.assertEqual(refusal(inspect, COMBINED, 'gltf', None, None, component_caps=(17, 4_000_000)),
                         [('E_RESOURCE_LIMIT', '/accessors/0')])
        self.assertEqual(refusal(inspect, COMBINED, 'gltf', None, None, component_caps=(1_000_000, 18)),
                         [('E_RESOURCE_LIMIT', '/accessors/1')])
