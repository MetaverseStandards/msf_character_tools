# SPDX-License-Identifier: MIT
"""The end-to-end examples in examples/, run as a user would and checked against independent expectations.

Set MSF_EXAMPLE_ASSETS to the folder examples/fetch_assets.py downloaded into.
Each example runs in a subprocess and writes into a temporary folder. The checks
use facts about the assets that do not come from msf-tools: counts, licences and
hashes; GLB data read with struct and morph deltas applied by hand; usd-core's
and ufbx's own evaluation; the independent Fox oracle when MSF_REAL_ASSETS is
set. The command-line check compares msf-tools with itself and is only a
reproducibility check.
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

from support import capabilities
from support.glb_struct import accessor, read_glb
from test_source_usd import HAVE_USD

HAVE_FBX = capabilities.FBX

REPO = Path(__file__).resolve().parents[2]
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


def same_points(test, actual, wanted, tolerance, where, counts=True):
    """Every point of each list lies within tolerance of a point of the other (mesh order may differ).

    counts=False allows exports that split vertices at seams differently.
    """
    if counts:
        test.assertEqual(len(actual), len(wanted), where)
    for one, other in ((actual, wanted), (wanted, actual)):
        cells = {}
        for p in other:
            cells.setdefault(tuple(math.floor(c / (4 * tolerance)) for c in p), []).append(p)
        for p in one:
            key = [math.floor(c / (4 * tolerance)) for c in p]
            near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                    for q in cells.get((key[0] + dx, key[1] + dy, key[2] + dz), ())]
            test.assertTrue(any(math.dist(p, q) <= tolerance for q in near), (where, p))


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
        self.assertTrue(all(j['caption'] == jobs['credit'] for j in jobs['jobs']))
        self.assertIn(summary['asset']['license'], jobs['credit'])
        self.assertEqual((render / 'CREDITS.txt').read_text(), jobs['credit'] + '\n')
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
        credit = json.loads((render / 'render.json').read_text())['credit']
        self.assertTrue(all(name in credit for name in ('PixelMannen', 'tomkranis', '@AsoboStudio', '@scurest', 'CC-BY-4.0')))
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
        document, binary = read_glb((ASSETS / 'AnimatedMorphCube.glb').read_bytes())
        primitive = document['meshes'][0]['primitives'][0]
        rest = accessor(document, binary, primitive['attributes']['POSITION'])
        delta = accessor(document, binary, primitive['targets'][0]['POSITION'])
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


@unittest.skipUnless(PRESENT and HAVE_FBX, 'needs MSF_EXAMPLE_ASSETS and FBX support')
class FbxExample(ExampleChecks):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'fbx'
        run('fbx_character.py', cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_kenneys_glb_export_of_the_character_agrees_with_the_fbx_export(self):
        # Exporter tier: two exports of one model; the clips are keyed differently, so between keys they differ slightly.
        from msf_tools import inspect_asset
        render = self.out / 'character' / 'render'
        glb = inspect_asset((ASSETS / 'character-female-a.glb').read_bytes(), 'glb').value
        walk = [a.get('name') for a in glb.document['animations']].index('walk')
        sys.path.insert(0, str(EXAMPLES))
        from example_pipeline import pose
        for name, kwargs in (('rest', {}), ('walk_0.1', {'animation_id': walk, 'timestamp': 0.1}),
                             ('walk_0.25', {'animation_id': walk, 'timestamp': 0.25}), ('walk_0.5', {'animation_id': walk, 'timestamp': 0.5})):
            wanted = pose(glb, **kwargs)[0]
            diagonal = math.dist([min(c) for c in zip(*wanted)], [max(c) for c in zip(*wanted)])
            same_points(self, floats(render / f'{name}.f32'), wanted, 1e-3 * diagonal, name, counts=False)


if __name__ == '__main__':
    unittest.main()
