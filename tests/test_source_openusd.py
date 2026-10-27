# SPDX-License-Identifier: MIT
"""OpenUSD's own UsdSkel test scenes and tutorial assets (TOST-1.0), when a local copy is present.

Set MSF_OPENUSD_ASSETS to a checkout holding pxr/usd/usdSkel/testenv and
extras/usd/tutorials from OpenUSD; the assets are never committed here. Each
asset must inspect or be refused with its expected code, and every mesh must
match usd-core's world-space points within 1e-5 of the bounding-box diagonal:
at the earliest time, and for skinned meshes at the first, middle and last times BakeSkinning writes.
"""
import math
import os
from pathlib import Path
import unittest

import msf_tools as m
from test_source_strict import Oracle, msf_world_points
from test_source_usd import HAVE_USD

ROOT = Path(os.environ['MSF_OPENUSD_ASSETS']) if os.environ.get('MSF_OPENUSD_ASSETS') else None
PRESENT = HAVE_USD and ROOT is not None and (ROOT / 'LICENSE.txt').is_file()
# BakeSkinning output for a rigid cube: the baked transform carries the skinning's shear.
REFUSED = {'pxr/usd/usdSkel/testenv/testUsdSkelBakeSkinning/baseline/lbs.baked.usda': 'E_SHEAR_UNSUPPORTED'}


def assets():
    if not PRESENT:
        return []
    found = list((ROOT / 'pxr/usd/usdSkel/testenv').rglob('*.usd*')) + list((ROOT / 'extras/usd/tutorials').rglob('*.usd*'))
    return sorted(p.relative_to(ROOT).as_posix() for p in found)


@unittest.skipUnless(PRESENT, 'set MSF_OPENUSD_ASSETS to a local OpenUSD asset checkout to run this tier')
class OpenUsdAssets(unittest.TestCase):
    def check(self, relative):
        path = ROOT / relative
        result = m.inspect_asset(path.read_bytes(), path.suffix[1:], resolver=m.LocalResolver(path.parent))
        if relative in REFUSED:
            self.assertEqual([d.code for d in result.report.diagnostics], [REFUSED[relative]])
            return
        self.assertTrue(result.ok, result.report.to_dict())
        snapshot = result.value
        oracle = Oracle(path)
        skinned = any(p.IsA(oracle.UsdSkel.Root) for p in oracle.stage.Traverse())
        earliest = oracle.Usd.TimeCode.EarliestTime()
        meshes = [prim for prim in oracle.meshes if oracle.UsdGeom.Mesh(prim).GetPointsAttr().Get(earliest)]
        checks = [(prim, earliest) for prim in meshes]
        # Point animation is declared as skipped, so such meshes are compared at the earliest time only.
        moving = {prim.GetPath() for prim in meshes if oracle.UsdGeom.Mesh(prim).GetPointsAttr().GetNumTimeSamples() > 1}
        if skinned:
            oracle.bake()
            for prim in meshes:
                codes = oracle.UsdGeom.Mesh(prim).GetPointsAttr().GetTimeSamples()
                if prim.GetPath() not in moving and codes:
                    checks += [(prim, oracle.Usd.TimeCode(c)) for c in sorted({codes[0], codes[len(codes) // 2], codes[-1]})]
        rate = oracle.stage.GetTimeCodesPerSecond()
        animated = bool(snapshot.document.get('animations'))
        first = snapshot.document['animations'][0] if animated else None
        start = m.decode_accessor(snapshot, first['samplers'][0]['input']).value[0][0] * rate if animated else 0.0
        if checks:
            probe = m.evaluate_geometry(snapshot, **({'timestamp': start / rate, 'animation_id': 0} if animated else {}))
            if not probe.ok:
                # Geometry refuses more than four influences until N-influence skinning lands.
                self.assertEqual([d.code for d in probe.report.diagnostics], ['E_INFLUENCE_LIMIT'])
                return
        for prim, code in checks:
            seconds = 0.0 if code == earliest else code.GetValue() / rate
            if code == earliest and animated:
                seconds = start / rate
            actual = msf_world_points(snapshot, str(prim.GetPath()), seconds)
            wanted = oracle.world_points(prim, code)
            diagonal = math.dist([min(c) for c in zip(*wanted)], [max(c) for c in zip(*wanted)]) or 1.0
            for a, w in zip(actual, wanted):
                self.assertLess(math.dist(a, w), 1e-5 * diagonal, (str(prim.GetPath()), code, a, w))


for _relative in assets():
    setattr(OpenUsdAssets, 'test_' + _relative.replace('/', '_').replace('.', '_'),
            lambda self, relative=_relative: self.check(relative))


if __name__ == '__main__':
    unittest.main()
