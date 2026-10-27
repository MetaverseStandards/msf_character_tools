# SPDX-License-Identifier: MIT
"""The ufbx C shim through cffi; skipped when msf-tools-ufbx is not installed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

from support.fbx_ascii import Scene

HAVE_UFBX = importlib.util.find_spec('msf_tools_ufbx') is not None

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
    """Return (handle, error text); the handle is closed by the caller."""
    from msf_tools_ufbx import ffi, lib
    limits = ffi.new('msf_fbx_limits *', {'memory_limit': memory_limit, 'allocation_limit': allocation_limit})
    out = ffi.new('msf_fbx **')
    err = ffi.new('char[512]')
    ok = lib.msf_fbx_open(ffi.from_buffer(data), len(data), limits, out, err, 512)
    return (out[0] if ok else None), ffi.string(err).decode('utf-8', 'replace')


@unittest.skipUnless(HAVE_UFBX, 'msf-tools-ufbx is not installed')
class UfbxShim(unittest.TestCase):
    def test_open_reports_scene_counts(self):
        from msf_tools_ufbx import ffi, lib
        handle, err = open_scene(MINIMAL)
        self.assertIsNotNone(handle, err)
        try:
            info = ffi.new('msf_fbx_info *')
            self.assertEqual(lib.msf_fbx_info_get(handle, info), 1)
            self.assertEqual((info.nodes, info.meshes, info.anim_stacks, info.ascii, info.version), (1, 0, 0, 1, 7400))
        finally:
            lib.msf_fbx_close(handle)

    def test_unreadable_input_and_memory_limits_are_errors(self):
        handle, err = open_scene(b'this is not an FBX file at all')
        self.assertIsNone(handle)
        self.assertTrue(err)
        handle, err = open_scene(MINIMAL, memory_limit=4096)
        self.assertIsNone(handle)
        self.assertIn('memory', err.lower())

    def scene(self, data):
        from msf_tools_ufbx import lib
        handle, err = open_scene(data)
        self.assertIsNotNone(handle, err)
        self.addCleanup(lib.msf_fbx_close, handle)
        return handle

    def nodes(self, handle):
        from msf_tools_ufbx import ffi, lib
        info = ffi.new('msf_fbx_info *')
        lib.msf_fbx_info_get(handle, info)
        out = []
        for i in range(info.nodes):
            node = ffi.new('msf_fbx_node *')
            self.assertEqual(lib.msf_fbx_node_get(handle, i, node), 1)
            out.append({'name': ffi.unpack(node.name, node.name_len).decode(), 'parent': node.parent, 'mesh': node.mesh,
                        'helper': node.helper, 'to_parent': list(node.to_parent), 'to_world': list(node.to_world)})
        self.assertEqual(lib.msf_fbx_node_get(handle, info.nodes, ffi.new('msf_fbx_node *')), 0)
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
        from msf_tools_ufbx import ffi, lib
        scene = Scene(unit_cm=1.0)
        body = scene.model('Body', kind='Mesh')
        points = [(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0), (200, 0, 0), (300, 100, 0), (250, 200, 0), (150, 150, 0)]
        scene.mesh(body, 'Body', points, [[0, 1, 2, 3], [1, 4, 2], [4, 5, 6, 7, 2]])
        handle = self.scene(scene.text())
        self.assertEqual(self.nodes(handle)[0]['mesh'], 0)
        sizes = ffi.new('uint32_t[6]')
        self.assertEqual(lib.msf_fbx_mesh_sizes(handle, 0, sizes), 1)
        count, triangles = sizes[0], sizes[1]
        self.assertEqual((count, triangles, sizes[2], sizes[3]), (8, 6, 0, 0))
        positions = ffi.new('double[]', 3 * count)
        tri = ffi.new('uint32_t[]', 3 * triangles)
        self.assertEqual(lib.msf_fbx_mesh_fill(handle, 0, positions, count, tri, triangles), 1)
        self.assertEqual([round(positions[3 * i], 9) for i in range(count)], [0.0, 1.0, 1.0, 0.0, 2.0, 3.0, 2.5, 1.5])
        faces = [{0, 1, 2, 3}] * 2 + [{1, 4, 2}] + [{4, 5, 6, 7, 2}] * 3
        self.assertTrue(all(set(tri[3 * t:3 * t + 3]) <= faces[t] for t in range(triangles)))
        self.assertEqual(lib.msf_fbx_mesh_fill(handle, 0, positions, count - 1, tri, triangles), 0)
        self.assertEqual(lib.msf_fbx_mesh_sizes(handle, 1, sizes), 0)


class VendoredUfbx(unittest.TestCase):
    def test_vendored_files_match_the_source_lock(self):
        root = Path(__file__).resolve().parent.parent
        lock = next(e for e in json.loads((root / 'docs/source-lock.json').read_text()) if e['id'] == 'ufbx')
        for name, digest in lock['vendored'].items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest, name)


if __name__ == '__main__':
    unittest.main()
