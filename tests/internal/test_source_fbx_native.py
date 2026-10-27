# SPDX-License-Identifier: MIT
"""The ufbx C shim compiled into the core, through its test hooks (msf_tools._core._fbx_open)."""
import hashlib
import json
from pathlib import Path
import unittest

from msf_tools import _native
from support.fbx_ascii import Scene

_core = _native.required()
HAVE_UFBX = True

MINIMAL = b'''; FBX 7.4.0 project file
FBXHeaderExtension:  {
	FBXHeaderVersion: 1003
	FBXVersion: 7400
}
Objects:  {
	Model: 1, "Model::Root", "Null" {
	}
}
Connections:  {
	C: "OO",1,0
}
'''


def open_scene(data, memory_limit=0, allocation_limit=0):
    """Return (scene or None, error text); the scene closes when it is collected."""
    scene, err = _core._fbx_open(data, memory_limit, allocation_limit)
    return scene, err.decode('utf-8', 'replace')


class UfbxShim(unittest.TestCase):
    def test_the_shim_reports_its_abi_and_the_compiled_ufbx_version(self):
        from msf_tools.sources import fbx
        self.assertEqual(_core._fbx_shim_abi(), 5)
        self.assertEqual(_core._fbx_ufbx_version(), 23001)
        self.assertEqual(fbx.ADAPTER.reader(), 'ufbx 0.23.1')

    def test_open_reports_scene_counts(self):
        scene, err = open_scene(MINIMAL)
        self.assertIsNotNone(scene, err)
        info = scene.info()
        self.assertEqual((info['nodes'], info['meshes'], info['anim_stacks'], info['ascii'], info['version']), (1, 0, 0, 1, 7400))

    def test_unreadable_input_and_memory_limits_are_errors(self):
        scene, err = open_scene(b'this is not an FBX file at all')
        self.assertIsNone(scene)
        self.assertTrue(err)
        scene, err = open_scene(MINIMAL, memory_limit=4096)
        self.assertIsNone(scene)
        self.assertIn('memory', err.lower())

    def scene(self, data):
        scene, err = open_scene(data)
        self.assertIsNotNone(scene, err)
        return scene

    def nodes(self, scene):
        out = []
        for i in range(scene.info()['nodes']):
            node = scene.node(i)
            self.assertIsNotNone(node)
            out.append(dict(node, name=node['name'].decode()))
        self.assertIsNone(scene.node(len(out)))
        return out

    def test_nodes_report_hierarchy_names_and_matrices(self):
        scene = Scene()
        root = scene.model('Root', translation=(1, 2, 3), rotation=(0, 0, 90))
        scene.model('Arm', root, translation=(0, 1, 0), scale=(2, 2, 2))
        scene.model('Arm', root)
        nodes = self.nodes(self.scene(scene.text()))
        self.assertEqual([(n['name'], n['parent']) for n in nodes], [('Root', -1), ('Arm', 0), ('Arm', 0)])
        arm = nodes[1]
        for got, want in zip(arm['to_world'][12:15], (0.0, 2.0, 3.0)):
            self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(arm['to_parent'][0], 2.0, places=9)
        self.assertAlmostEqual(nodes[0]['to_parent'][1], 1.0, places=9)  # X axis turned onto +Y

    def test_mesh_points_and_triangles(self):
        scene = Scene(unit_cm=1.0)
        body = scene.model('Body', kind='Mesh')
        points = [(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0), (200, 0, 0), (300, 100, 0), (250, 200, 0), (150, 150, 0)]
        scene.mesh(body, 'Body', points, [[0, 1, 2, 3], [1, 4, 2], [4, 5, 6, 7, 2]])
        handle = self.scene(scene.text())
        self.assertEqual(self.nodes(handle)[0]['mesh'], 0)
        sizes = handle.mesh_sizes(0)
        count, triangles = sizes[0], sizes[1]
        self.assertEqual((count, triangles, sizes[2], sizes[3], sizes[6]), (8, 6, 0, 0, 0))
        positions, tri = handle.mesh_fill(0, count, triangles)
        self.assertEqual([round(positions[3 * i], 9) for i in range(count)], [0.0, 1.0, 1.0, 0.0, 2.0, 3.0, 2.5, 1.5])
        faces = [{0, 1, 2, 3}] * 2 + [{1, 4, 2}] + [{4, 5, 6, 7, 2}] * 3
        self.assertTrue(all(set(tri[3 * t:3 * t + 3]) <= faces[t] for t in range(triangles)))
        self.assertIsNone(handle.mesh_fill(0, count - 1, triangles))
        self.assertIsNone(handle.mesh_sizes(1))
        scene.cache(1002, 'Body')  # the Body geometry
        self.assertEqual(self.scene(scene.text()).mesh_sizes(0)[6], 1)

    def test_skin_clusters_weights_and_bind_matrices(self):
        identity = [float(r == c) for c in range(4) for r in range(4)]
        raised, lowered = identity[:12] + [0.0, 1.0, 0.0, 1.0], identity[:12] + [0.0, -1.0, 0.0, 1.0]
        for skinning, method in (('Linear', 0), ('DualQuaternion', 2)):
            with self.subTest(skinning=skinning):
                scene = Scene()
                root = scene.model('Root', kind='LimbNode')
                arm = scene.model('Arm', root, kind='LimbNode', translation=(0, 1, 0))
                body = scene.model('Body', kind='Mesh')
                geometry = scene.mesh(body, 'Body', [(0, 0, 0), (1, 1, 0), (0, 2, 0)], [[0, 1, 2]])
                scene.skin(geometry, [(root, [0, 1], [1.0, 0.5], identity, identity), (arm, [1, 2], [0.5, 1.0], lowered, raised)],
                           skinning)
                handle = self.scene(scene.text())
                self.assertEqual(handle.skin_sizes(0, 0), (2, 4))
                offsets, which, weights, nodes, bind, kind = handle.skin_fill(0, 0, 3, 4, 2)
                self.assertEqual(offsets, [0, 1, 3, 4])
                rows = [sorted((which[k], weights[k]) for k in range(offsets[v], offsets[v + 1])) for v in range(3)]
                self.assertEqual(rows, [[(0, 1.0)], [(0, 0.5), (1, 0.5)], [(1, 1.0)]])
                names = [n['name'] for n in self.nodes(handle)]
                self.assertEqual([names[i] for i in nodes], ['Root', 'Arm'])
                self.assertAlmostEqual(bind[16 + 13], -1.0, places=9)
                self.assertEqual(kind, method)
                self.assertIsNone(handle.skin_sizes(0, 1))

    def test_blend_channels_keyframes_and_names(self):
        scene = Scene()
        body = scene.model('Body', kind='Mesh')
        geometry = scene.mesh(body, 'Body', [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]])
        scene.blend(geometry, 'Face', [('smile', 25, [(50, [2], [(0, 0.25, 0)]), (100, [1, 2], [(0, 0, 1), (0, 1, 0)])]),
                                       ('blink', 0, [(100, [0], [(1, 0, 0)])])])
        handle = self.scene(scene.text())
        self.assertEqual(handle.blend_sizes(0, 0), (2, 3))
        fill = handle.blend_fill(0, 0, 2, 3)
        self.assertEqual((fill['deformer'], fill['counts'], fill['indices'], fill['targets']), (0, [1, 2], [2, 1, 2], [0.5, 1.0]))
        self.assertEqual(fill['offsets'][3:6], [0.0, 0.0, 1.0])
        self.assertAlmostEqual(fill['weight'], 0.25)
        self.assertEqual([name.decode() for name in fill['names']], ['Face', 'smile'])
        self.assertEqual(handle.blend_sizes(0, 1), (1, 1))
        self.assertIsNone(handle.blend_sizes(0, 2))

    def test_animation_stacks_evaluate_node_matrices_and_blend_weights(self):
        scene = Scene()
        body = scene.model('Body', kind='Mesh')
        geometry = scene.mesh(body, 'Body', [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]])
        smile, = scene.blend(geometry, 'Face', [('smile', 0, [(100, [2], [(0, 1, 0)])])])
        scene.animation('Take 001', 0.0, 1.0, [(body, 'Lcl Translation', {'X': [(0.0, 0.0), (1.0, 10.0)], 'Y': [(0.0, 0.0), (1.0, 0.0)],
                                                                          'Z': [(0.0, 0.0), (1.0, 0.0)]}),
                                               (smile, 'DeformPercent', {'DeformPercent': [(0.0, 0.0), (1.0, 100.0)]})])
        handle = self.scene(scene.text())
        self.assertEqual(handle.stack(0), (b'Take 001', 0.0, 1.0))
        self.assertIsNone(handle.stack(1))
        channel = handle.blend_channel_id(0, 0)
        self.assertIsNotNone(channel)
        evaluated = handle.evaluate(0, 0.5, 1, 1, True)
        self.assertIsInstance(evaluated, tuple, evaluated)
        to_parent, to_world, weights = evaluated
        self.assertAlmostEqual(to_parent[12], 5.0, places=6)
        self.assertAlmostEqual(weights[channel], 0.5, places=6)
        self.assertIsInstance(handle.evaluate(0, 0.5, 2, 1, True), bytes)


class VendoredUfbx(unittest.TestCase):
    def test_vendored_files_match_the_source_lock(self):
        root = Path(__file__).resolve().parents[2]
        lock = next(e for e in json.loads((root / 'docs/source-lock.json').read_text()) if e['id'] == 'ufbx')
        for name, digest in lock['vendored'].items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest, name)


if __name__ == '__main__':
    unittest.main()
