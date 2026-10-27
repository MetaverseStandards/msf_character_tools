# SPDX-License-Identifier: MIT
"""The end-to-end examples in examples/, run as a user would and checked against independent expectations.

Set MSF_EXAMPLE_ASSETS to the folder examples/fetch_assets.py downloaded into.
Each example runs in a subprocess and writes into a temporary folder. The checks
use facts about the assets that do not come from msf-tools (counts, licences,
hashes, morph deltas applied by hand, usd-core's own skinning, the independent
Fox oracle when MSF_REAL_ASSETS is set), plus the shape of the render files.
"""
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import msf_tools as m
from test_source_fbx_native import HAVE_UFBX
from test_source_usd import HAVE_USD

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / 'examples'
ASSETS = Path(os.environ['MSF_EXAMPLE_ASSETS']) if os.environ.get('MSF_EXAMPLE_ASSETS') else None
PRESENT = ASSETS is not None and (ASSETS / 'Fox.glb').is_file()
REAL = Path(os.environ['MSF_REAL_ASSETS']) if os.environ.get('MSF_REAL_ASSETS') else None
FLOAT32 = 2.0 ** -23
SCALE = 0.8


def run(script, out):
    env = dict(os.environ, PYTHONPATH=str(REPO))
    done = subprocess.run([sys.executable, '-B', str(EXAMPLES / script), '--assets', str(ASSETS), '--out', str(out)],
                          capture_output=True, text=True, env=env, cwd=out.parent, timeout=300)
    if done.returncode != 0:
        raise AssertionError(f'{script} failed:\n{done.stdout}\n{done.stderr}')
    return done.stdout


def floats(path):
    data = path.read_bytes()
    return [struct.unpack_from('<3f', data, 12 * i) for i in range(len(data) // 12)]


def quaternion_matrix(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


class ExampleChecks(unittest.TestCase):
    maxDiff = None

    def outputs(self, folder):
        summary = json.loads((folder / 'summary.json').read_text())
        render = folder / 'render'
        jobs = json.loads((render / 'render.json').read_text())
        indices = struct.unpack(f'<{(render / "mesh.u32").stat().st_size // 4}I', (render / 'mesh.u32').read_bytes())
        self.assertEqual([j['positions'] for j in jobs['jobs']], [p['file'] for p in summary['poses']])
        for pose in summary['poses']:
            self.assertEqual((render / pose['file']).stat().st_size, 12 * pose['vertices'])
            self.assertEqual(len(indices), 3 * pose['triangles'])
        self.assertLess(max(indices), summary['poses'][0]['vertices'])
        self.assertTrue(all(j['indices'] == 'mesh.u32' and j['out'].endswith('.png') for j in jobs['jobs']))
        rows = (folder / 'poses.csv').read_text().splitlines()
        self.assertEqual(len(rows), 1 + len(summary['poses']))
        for name in ('authoring.toml', 'annotations.json', 'sidecar.json', 'samples.json', 'mapping.json', 'evaluated.json'):
            self.assertTrue((folder / name).is_file(), name)
        return summary, render

    def mapped(self, summary):
        self.assertEqual([(e['source'], e['target']) for e in summary['evaluated']], [(x, SCALE * x) for x in (0.0, 0.5, 1.0)])

    def close(self, actual, wanted, where):
        self.assertEqual(len(actual), len(wanted), where)
        for a, w in zip(actual, wanted):
            for x, y in zip(a, w):
                self.assertLessEqual(abs(x - y), FLOAT32 * max(1.0, abs(y)), (where, a, w))


@unittest.skipUnless(PRESENT, 'set MSF_EXAMPLE_ASSETS to the folder examples/fetch_assets.py downloaded into')
class GltfExample(ExampleChecks):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'gltf'
        cls.stdout = run('gltf_fox.py', cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_fox_is_inspected_refuses_a_morph_binding_and_poses_its_clips(self):
        summary, render = self.outputs(self.out / 'fox')
        self.assertEqual((summary['asset']['sha256'], summary['asset']['format'], summary['asset']['license']),
                         ('d97044e701822bac5a62696459b27d7b375aada5de8574ed4362edbba94771f7', 'glb', 'CC0-1.0 AND CC-BY-4.0'))
        self.assertEqual([a['name'] for a in summary['inspect']['animations']], ['Survey', 'Walk', 'Run'])
        self.assertEqual((summary['inspect']['skins'], summary['inspect']['morph_targets'], summary['inspect']['declared_losses']), (1, 0, []))
        self.assertEqual(summary['binding']['refused'], 'E_BINDING_REFERENCE')
        self.mapped(summary)
        self.assertEqual([p['name'] for p in summary['poses']], ['rest', 'survey_0.137', 'survey_end', 'walk_0.35', 'run_0.6'])
        self.assertEqual({(p['vertices'], p['triangles']) for p in summary['poses']}, {(1728, 576)})
        if REAL is not None:
            oracle = json.loads((REAL / 'assets-oracle-review09I' / 'Fox.independent.json').read_text())['cases']
            for name, case in (('rest', 0), ('survey_0.137', 2), ('survey_end', 3)):
                wanted = oracle[case]['world_reference'][0]['primitives'][0]['positions']
                self.close(floats(render / f'{name}.f32'), wanted, name)

    def test_the_morph_cube_binding_drives_its_first_target(self):
        summary, render = self.outputs(self.out / 'morph_cube')
        self.assertEqual(summary['asset']['sha256'], '214ee56160a50dbf22543a1d66dbf860986e87f0efac3d89feac1359d0e6aeab')
        self.assertEqual((summary['binding']['node'], summary['binding']['target']), (0, 0))
        self.mapped(summary)
        snapshot = m.inspect_asset((ASSETS / 'AnimatedMorphCube.glb').read_bytes(), 'glb').value
        rest = m.decode_accessor(snapshot, 2).value
        delta = m.decode_accessor(snapshot, 4).value
        r = quaternion_matrix((0.0, 0.7071067, -0.7071068, 0.0))
        for pose, weight in (('jaw_open_0', 0.0), ('jaw_open_0.5', 0.4), ('jaw_open_1', 0.8)):
            local = [[p[k] + weight * d[k] for k in range(3)] for p, d in zip(rest, delta)]
            wanted = [[100.0 * sum(r[i][k] * p[k] for k in range(3)) for i in range(3)] for p in local]
            self.close(floats(render / f'{pose}.f32'), wanted, pose)


    def test_the_cli_reproduces_the_morph_cube_files(self):
        folder, asset = self.out / 'morph_cube', ASSETS / 'AnimatedMorphCube.glb'
        target = ['--source-profile', 'example.source', '--target-asset', asset, '--target-sidecar', folder / 'sidecar.json']
        with tempfile.TemporaryDirectory() as tmp:
            sidecar = Path(tmp) / 'sidecar.json'
            for argv, wanted in ((['annotate', asset, folder / 'annotations.json', '--output', sidecar], None),
                                 (['map', folder / 'authoring.toml', 'example.drive', *target], 'mapping.json'),
                                 (['evaluate', folder / 'authoring.toml', 'example.drive', folder / 'samples.json', *target], 'evaluated.json')):
                done = subprocess.run([sys.executable, '-B', '-m', 'msf_tools', *map(str, argv)], capture_output=True,
                                      env=dict(os.environ, PYTHONPATH=str(REPO)), timeout=60)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stdout or sidecar.read_bytes(), (folder / (wanted or 'sidecar.json')).read_bytes(), argv[0])


@unittest.skipUnless(PRESENT and HAVE_USD, 'needs MSF_EXAMPLE_ASSETS and usd-core')
class UsdExample(ExampleChecks):
    def test_the_generated_tube_matches_usd_core(self):
        from test_source_strict import Oracle
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'usd'
            run('usd_tube.py', out)
            summary, render = self.outputs(out)
            self.assertEqual((summary['asset']['format'], summary['inspect']['declared_losses']), ('usdz', []))
            self.assertEqual((summary['binding']['label'], summary['binding']['target']), ('bulge', 0))
            self.mapped(summary)
            self.assertEqual({(p['vertices'], p['triangles']) for p in summary['poses']}, {(208, 384)})
            oracle = Oracle(out / 'tube.usda')
            prim = oracle.meshes[0]
            rest = oracle.world_points(prim, oracle.Usd.TimeCode.Default())
            self.close(floats(render / 'rest.f32'), rest, 'rest')
            shape = oracle.UsdSkel.BlendShape(oracle.stage.GetPrimAtPath(f'{prim.GetPath()}/Bulge'))
            offsets = dict(zip(shape.GetPointIndicesAttr().Get(), shape.GetOffsetsAttr().Get()))
            bulged = [[p[k] + 0.8 * offsets[i][k] if i in offsets else p[k] for k in range(3)] for i, p in enumerate(rest)]
            self.close(floats(render / 'jaw_open_1.f32'), bulged, 'jaw_open_1')
            oracle.bake([12, 24, 36])
            for name, code in (('bend_0.5', 12), ('bend_1', 24), ('bend_1.5', 36)):
                wanted = oracle.world_points(prim, code)
                actual = floats(render / f'{name}.f32')
                diagonal = math.dist([min(c) for c in zip(*wanted)], [max(c) for c in zip(*wanted)])
                self.assertLess(max(math.dist(a, w) for a, w in zip(actual, wanted)), 1e-5 * diagonal, name)


@unittest.skipUnless(PRESENT and HAVE_UFBX, 'needs MSF_EXAMPLE_ASSETS and msf-tools-ufbx')
class FbxExample(ExampleChecks):
    def test_the_barbarian_mouth_shape_is_driven_by_the_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'fbx'
            run('fbx_barbarian.py', out)
            summary, render = self.outputs(out)
            self.assertEqual((summary['asset']['sha256'], summary['asset']['format']),
                             ('bd78a4fc05abe83cb3bb26e4ca649a3c5e7cb1e0c6f523fcd599e48cd0435e04', 'fbx'))
            self.assertEqual([d['code'] for d in summary['inspect']['declared_losses']],
                             ['I_INFLUENCES_N', 'W_WEIGHTS_NORMALIZED', 'W_WEIGHTS_NORMALIZED', 'W_UNWEIGHTED_VERTICES', 'W_SKIPPED'])
            self.assertEqual((summary['binding']['label'], summary['binding']['node_path']), ('Mouth', '/body'))
            self.mapped(summary)
            closed, half, open_ = (floats(render / f'jaw_open_{w}.f32') for w in ('0', '0.5', '1'))
            moved = [i for i, (a, b) in enumerate(zip(closed, open_)) if math.dist(a, b) > 1e-6]
            self.assertTrue(0 < len(moved) <= 587, len(moved))
            for i in moved:
                for k in range(3):
                    self.assertAlmostEqual(open_[i][k] - closed[i][k], 2 * (half[i][k] - closed[i][k]), delta=1e-5)
            self.assertEqual([p['name'] for p in summary['poses']][-3:], ['clip_0.5', 'clip_1.25', 'clip_2'])


if __name__ == '__main__':
    unittest.main()
