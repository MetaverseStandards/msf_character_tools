# SPDX-License-Identifier: MIT
"""The shared source GLB writer, checked through the public glTF inspector."""
import json
import math
import struct
import unittest

import msf_tools as m
from msf_tools.sources import glb

TRIANGLE = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.1, 0.0))


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def document(raw):
    assert raw[:4] == b'glTF', raw[:16]
    length, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 0x4E4F534A
    return json.loads(raw[20:20 + length])


def inspect(raw):
    result = m.inspect_asset(raw, 'glb')
    assert result.ok, result.report.to_dict()
    return result.value


def positions(snapshot, **kwargs):
    result = m.evaluate_geometry(snapshot, **kwargs)
    assert result.ok, result.report.to_dict()
    return [instance['primitives'][0]['positions'] for instance in result.value.to_dict()['instances']]


class GlbWriter(unittest.TestCase):
    def test_static_mesh_keeps_one_vertex_per_point(self):
        mesh = glb.Mesh(points=TRIANGLE + ((5.0, 5.0, 5.0),), triangles=(0, 1, 2, 2, 1, 0))
        nodes = (glb.Node(name='root', children=(1,), translation=(1.0, 0.0, 0.0)), glb.Node(name='leaf', mesh=0))
        raw = glb.write_glb(nodes, (mesh,), generator='fake 1')
        doc = document(raw)
        self.assertEqual(doc['asset'], {'version': '2.0', 'generator': 'fake 1'})
        self.assertEqual(doc['scenes'], [{'nodes': [0]}])
        primitive = doc['meshes'][0]['primitives'][0]
        self.assertEqual(doc['accessors'][primitive['attributes']['POSITION']]['count'], 4)
        self.assertEqual(doc['accessors'][primitive['indices']]['count'], 6)
        self.assertEqual(positions(inspect(raw)), [[[f32(c) for c in p] for p in mesh.points]])

    def test_points_without_triangles_use_point_mode(self):
        raw = glb.write_glb((glb.Node(mesh=0),), (glb.Mesh(points=TRIANGLE),), generator='fake 1')
        primitive = document(raw)['meshes'][0]['primitives'][0]
        self.assertEqual(primitive['mode'], 0)
        self.assertNotIn('indices', primitive)
        inspect(raw)

    def test_sparse_targets_at_two_thirds_and_dense_above(self):
        zero, up = (0.0, 0.0, 0.0), (0.0, 0.5, 0.0)
        three = glb.Mesh(points=TRIANGLE, targets=((up, up, zero), (up, zero, zero), (zero, zero, zero)))
        four = glb.Mesh(points=TRIANGLE + ((2.0, 0.0, 0.0),), targets=((up, up, up, zero),))
        raw = glb.write_glb((glb.Node(mesh=0), glb.Node(mesh=1)), (three, four), generator='fake 1')
        doc = document(raw)
        accessor = lambda mi, ti: doc['accessors'][doc['meshes'][mi]['primitives'][0]['targets'][ti]['POSITION']]
        self.assertEqual(accessor(0, 0)['sparse']['count'], 2)
        self.assertNotIn('bufferView', accessor(0, 0))
        self.assertEqual(accessor(0, 1)['sparse']['count'], 1)
        self.assertNotIn('sparse', accessor(0, 2))
        self.assertNotIn('bufferView', accessor(0, 2))
        self.assertIn('bufferView', accessor(1, 0))
        self.assertNotIn('sparse', accessor(1, 0))
        snapshot = inspect(raw)
        morphed = positions(snapshot, morph_weights={0: [1.0, 2.0, 3.0], 1: [1.0]})
        self.assertEqual(morphed[0], [[0.0, 1.5, 0.0], [1.0, 0.5, 0.0], [0.0, f32(1.1), 0.0]])
        self.assertEqual(morphed[1][3], [2.0, 0.0, 0.0])

    def test_default_morph_weights_are_written(self):
        mesh = glb.Mesh(points=TRIANGLE, targets=(((0.0, 1.0, 0.0),) * 3,), weights=(0.25,))
        doc = document(glb.write_glb((glb.Node(mesh=0, weights=(0.5,)),), (mesh,), generator='fake 1'))
        self.assertEqual(doc['meshes'][0]['weights'], [0.25])
        self.assertEqual(doc['nodes'][0]['weights'], [0.5])

    def test_weights_are_merged_normalized_and_split_into_sets_of_four(self):
        influences = (((0, 0.2), (1, 0.2), (2, 0.2)),
                      ((0, 0.5), (0, 0.5)),
                      tuple((j, 1.0) for j in range(6)))
        mesh = glb.Mesh(points=TRIANGLE, triangles=(0, 1, 2), influences=influences)
        nodes = (glb.Node(children=tuple(range(1, 7))),) + tuple(glb.Node() for _ in range(6)) + (glb.Node(mesh=0, skin=0),)
        identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        skin = glb.Skin(joints=tuple(range(1, 7)), inverse_bind_matrices=(identity,) * 6, skeleton=0)
        raw = glb.write_glb(nodes, (mesh,), (skin,), generator='fake 1')
        doc = document(raw)
        attributes = doc['meshes'][0]['primitives'][0]['attributes']
        self.assertEqual(sorted(attributes), ['JOINTS_0', 'JOINTS_1', 'POSITION', 'WEIGHTS_0', 'WEIGHTS_1'])
        snapshot = inspect(raw)
        for vertex in range(3):
            weights = [w for name in ('WEIGHTS_0', 'WEIGHTS_1')
                       for w in m.decode_accessor(snapshot, attributes[name]).value[vertex]]
            self.assertLessEqual(abs(math.fsum(weights) - 1), 1e-6)
        joints = m.decode_accessor(snapshot, attributes['JOINTS_0']).value
        self.assertEqual(joints[1], (0, 0, 0, 0))
        self.assertEqual(m.decode_accessor(snapshot, attributes['WEIGHTS_0']).value[1], (1.0, 0.0, 0.0, 0.0))

    def test_output_is_deterministic(self):
        build = lambda: glb.write_glb((glb.Node(mesh=0),), (glb.Mesh(points=TRIANGLE, triangles=(0, 1, 2)),), generator='fake 1')
        self.assertEqual(build(), build())

    def test_invalid_scene_data_is_refused(self):
        for mesh in (glb.Mesh(points=TRIANGLE, triangles=(0, 1, 3)),
                     glb.Mesh(points=TRIANGLE, triangles=(0, 1)),
                     glb.Mesh(points=TRIANGLE, influences=(((0, 1.0),), ((0, -1.0), (1, 2.0)), ((0, 1.0),))),
                     glb.Mesh(points=TRIANGLE, influences=(((0, 1.0),), ((0, 0.0),), ((0, 1.0),))),
                     glb.Mesh(points=((0.0, math.nan, 0.0),)),
                     glb.Mesh(points=TRIANGLE, targets=(((0.0, 0.0, 0.0),),))):
            with self.subTest(mesh=mesh), self.assertRaises(ValueError):
                glb.write_glb((glb.Node(mesh=0),), (mesh,), generator='fake 1')


if __name__ == '__main__':
    unittest.main()
