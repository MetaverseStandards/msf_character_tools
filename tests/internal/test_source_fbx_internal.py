# SPDX-License-Identifier: MIT
"""FBX inspection checked against the ufbx shim and private adapter limits."""
import contextlib
import unittest

import msf_character_tools as m
from msf_character_tools import _native
from support.values import plain
from support.fbx_ascii import Scene
from internal.test_source_fbx_native import open_scene
from test_source_strict import msf_world_points
from test_source_usd import good
from test_source_fbx import IDENTITY, animated, close, codes, errors, face, skinned_scene

_core = _native.built


def ufbx_skinned_world(data, mesh=0, stack=-1, time=0.0):
    scene, err = open_scene(data)
    points = scene.mesh_sizes(mesh)[0]
    out = scene.skinned_points(stack, time, mesh, points)
    assert isinstance(out, tuple), out
    return [tuple(out[3 * v:3 * v + 3]) for v in range(points)]


@contextlib.contextmanager
def failing(name):
    """Make one ufbx shim call report failure while converting."""
    _core._fbx_fail_call(name)
    try:
        yield
    finally:
        _core._fbx_fail_call('')


class FbxStatic(unittest.TestCase):
    def test_unreadable_files_and_reader_memory(self):
        self.assertEqual(errors(m.inspect_asset(b'; FBX 7.4.0 project file\nObjects: { garbage', 'fbx')), [('E_SOURCE_PARSE', '/')])
        result = m.inspect_asset(face().text(), 'fbx', limits=m.sources.SourceLimits(max_reader_memory=4096))
        self.assertEqual(errors(result), [('E_SOURCE_MEMORY', '/')])


class FbxNumbers(unittest.TestCase):
    def test_numbers_at_and_past_the_int64_range_convert_without_overflow(self):
        # ufbx stores every number as int64 too; 2^63 used to overflow that conversion (UBSan in the sanitizer tier).
        for value in ('9.223372036854775808e18', '-9.223372036854775808e18', '1e300', '9223372036854775807'):
            text = ('; FBX 7.4.0 project file\nFBXHeaderExtension:  {\n\tFBXHeaderVersion: 1003\n\tFBXVersion: 7400\n}\n'
                    'Objects:  {\n\tModel: 1, "Model::a", "Null" {\n\t\tProperties70:  {\n'
                    f'\t\t\tP: "Visibility", "Visibility", "", "A",{value}\n\t\t}}\n\t}}\n}}\n')
            with self.subTest(value=value):
                result = m.inspect_asset(text.encode(), 'fbx')
                self.assertIsInstance(result, m.Result)


class FbxSkin(unittest.TestCase):
    def test_skinned_points_match_ufbx_skinning(self):
        scene, _ = skinned_scene()
        data = scene.text()
        snapshot = good(m.inspect_asset(data, 'fbx'))
        self.assertEqual(codes(snapshot), [])
        self.assertEqual(snapshot.source['node_paths'], ('/Body', '/Root', '/Root/Arm'))
        self.assertEqual([s['joints'] for s in plain(snapshot.document['skins'])], [[1, 2]])
        close(self, msf_world_points(snapshot, '/Body', 0.0), ufbx_skinned_world(data))

    def test_more_than_four_influences_match_ufbx_skinning(self):
        scene = Scene()
        bones, parent = [], 0
        for k in range(6):
            parent = scene.model(f'B{k}', parent, kind='LimbNode', translation=(0, 1 if k else 0, 0), rotation=(0, 0, 10 * k))
            bones.append(parent)
        body = scene.model('Body', kind='Mesh')
        geometry = scene.mesh(body, 'Body', [(1, 0, 0), (0, 3, 0), (2, 5, 1)], [[0, 1, 2]])
        weights = [0.3, 0.2, 0.15, 0.15, 0.1, 0.1]
        # The bones' bind matrices are identity here, so each cluster's Transform and TransformLink are too.
        scene.skin(geometry, [(bone, [0, 1, 2], [w] * 3, IDENTITY, IDENTITY) for bone, w in zip(bones, weights)])
        data = scene.text()
        snapshot = good(m.inspect_asset(data, 'fbx'))
        self.assertEqual(codes(snapshot), [('I_INFLUENCES_N', '/Body')])
        close(self, msf_world_points(snapshot, '/Body', 0.0), ufbx_skinned_world(data))


class FbxAnimation(unittest.TestCase):
    def test_long_clips_on_large_rigs_are_refused_before_sampling(self):
        # Sampling first would fail with E_SOURCE_VALUE, since evaluation reports failure here.
        scene = Scene()
        parent = 0
        for k in range(200):
            parent = scene.model(f'n{k}', parent)
        scene.animation('Long', 0.0, 3000.0, [(parent, 'Lcl Translation', {
            'X': [(0.0, 0.0), (3000.0, 1.0)], 'Y': [(0.0, 0.0), (3000.0, 0.0)], 'Z': [(0.0, 0.0), (3000.0, 0.0)]})])
        with failing('msf_fbx_evaluate'):
            result = m.inspect_asset(scene.text(), 'fbx')
        self.assertEqual(errors(result), [('E_RESOURCE_LIMIT', '/')])
        self.assertIn('max_animation_values', result.report.diagnostics[0].remediation)

    def test_the_animation_value_limit_counts_samples_nodes_and_channels(self):
        # 25 samples x (2 nodes x 16 matrix values + 2 blend weights) = 850 values.
        data = animated().text()
        good(m.inspect_asset(data, 'fbx', limits=m.sources.SourceLimits(max_animation_values=850)))
        result = m.inspect_asset(data, 'fbx', limits=m.sources.SourceLimits(max_animation_values=849))
        self.assertEqual(errors(result), [('E_RESOURCE_LIMIT', '/')])

    def test_reader_calls_that_report_failure_are_refused(self):
        skinned, _ = skinned_scene()
        for name, data in (('msf_fbx_skin_sizes', skinned.text()), ('msf_fbx_blend_sizes', animated().text()),
                           ('msf_fbx_stack_get', animated().text()), ('msf_fbx_blend_channel_id', animated().text())):
            with self.subTest(name=name), failing(name):
                result = m.inspect_asset(data, 'fbx', isolate=False)
                self.assertEqual([d.code for d in result.report.diagnostics], ['E_SOURCE_VALUE'])

    def test_animated_skin_matches_ufbx_skinning(self):
        scene, _ = skinned_scene()
        arm = next(int(o.split(':')[1].split(',')[0]) for o in scene.objects if '"Model::Arm"' in o)
        scene.animation('Take', 0.0, 1.0, [(arm, 'Lcl Rotation', {'X': [(0.0, 0.0), (1.0, 0.0)], 'Y': [(0.0, 0.0), (1.0, 0.0)],
                                                                 'Z': [(0.0, 30.0), (1.0, 120.0)]})])
        data = scene.text()
        snapshot = good(m.inspect_asset(data, 'fbx'))
        for t in (0.25, 0.5, 1.0):
            with self.subTest(t=t):
                close(self, msf_world_points(snapshot, '/Body', t), ufbx_skinned_world(data, stack=0, time=t), 1e-5)


if __name__ == '__main__':
    unittest.main()
