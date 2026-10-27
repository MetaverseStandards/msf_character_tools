# SPDX-License-Identifier: MIT
"""glTF inspection, accessors, geometry, animation and bindings against the 0.3.0 oracle.

Random assets (tests/internal/gltf_cases.py), many damaged on purpose, go
through the same battery of public calls here and in the oracle; every Result,
record export, float bit and diagnostic must match. MSF_GATE=1 runs 10**4 assets.
"""
import os
import random
import unittest

from internal import gltf_cases, oracle

GATE = os.environ.get('MSF_GATE') == '1'


@unittest.skipIf(oracle.skip_reason(), oracle.skip_reason() or '')
class AgainstTheOracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        oracle.define(gltf_cases.BATTERY)

    def assertSame(self, cases):
        self.assertEqual(oracle.outcome(*cases[0])[0], 'value', oracle.outcome(*cases[0]))
        differing = oracle.differ(cases)
        self.assertEqual(differing[:2], [], f'{len(differing)} of {len(cases)} cases differ')

    def battery(self, raw, fmt, blobs=None, deep=True):
        return 'gltf_battery(raw, fmt, blobs, signal, deep)', {'raw': raw, 'fmt': fmt, 'blobs': blobs,
                                                               'signal': gltf_cases.SIGNAL, 'deep': deep}

    def test_intact_assets(self):
        rng = random.Random(31)
        self.assertSame([self.battery(*gltf_cases.random_asset(rng, damage=False)) for _ in range(2000 if GATE else 5)])

    def test_damaged_assets(self):
        rng = random.Random(37)
        self.assertSame([self.battery(*gltf_cases.random_asset(rng, damage=True)) for _ in range(8000 if GATE else 8)])


if __name__ == '__main__':
    unittest.main()
