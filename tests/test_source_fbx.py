# SPDX-License-Identifier: MIT
"""The FBX adapter on ufbx, with ASCII FBX files written by the test writer."""
import math
import struct
import unittest
import unittest.mock

import msf_tools as m
from msf_tools.common import thaw
from support.fbx_ascii import Scene
from test_source_fbx_native import HAVE_UFBX, open_scene
from test_source_strict import msf_world_points
from test_source_usd import SIGNAL, authoring, good, positions

IDENTITY = [float(r == c) for c in range(4) for r in range(4)]


def translated(x, y, z):
    return IDENTITY[:12] + [float(x), float(y), float(z), 1.0]


def codes(snapshot):
    return [(d['code'], d['ref']) for d in thaw(snapshot.source['losses'])]


def errors(result):
    return [(d.code, d.ref) for d in result.report.diagnostics if d.severity == 'error']


def face(unit_cm=100.0, **settings):
    scene = Scene(unit_cm=unit_cm, **settings)
    root = scene.model('Root', translation=(0, 1, 0))
    body = scene.model('Face', root, kind='Mesh')
    geometry = scene.mesh(body, 'Face', [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [[0, 1, 2, 3]])
    scene.blend(geometry, 'Blend', [('smile', 0, [(100, [3], [(0, 0.5, 0)])]), ('blink', 0, [(100, [1], [(0, 0, 0.25)])])])
    return scene


def mesh_node(snapshot, path):
    """The path of the node that holds the mesh for `path`: the node itself or one of its helpers."""
    nodes = snapshot.document['nodes']
    return next(p for i, p in enumerate(snapshot.source['node_paths'])
                if (p == path or p.startswith(path + '#helper:')) and 'mesh' in nodes[i])


def close(test, actual, expected, tolerance=1e-6):
    test.assertEqual(len(actual), len(expected))
    for a, e in zip(actual, expected):
        test.assertLess(math.dist(a, e), tolerance, (actual, expected))


@unittest.skipUnless(HAVE_UFBX, 'msf-tools-ufbx is not installed')
class FbxStatic(unittest.TestCase):
    def test_static_mesh_through_inspect_geometry_annotate_and_map(self):
        data = face().text()
        snapshot = good(m.inspect_asset(data, 'fbx'))
        source = thaw(snapshot.source)
        self.assertEqual((source['format'], source['adapter'], source['reader']), ('fbx', 'msf-ufbx', 'ufbx 0.23.1'))
        self.assertEqual(source['node_paths'], ['/Root', '/Root/Face'])
        self.assertEqual(source['target_keys'], [['Blend/smile', 'Blend/blink']])
        self.assertEqual(source['losses'], [])
        close(self, positions(snapshot), [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
        close(self, positions(snapshot, morph_weights={1: [1.0, 1.0]}), [(0, 0, 0), (1, 0, 0.25), (1, 1, 0), (0, 1.5, 0)])
        binding = thaw(good(m.morph_binding(snapshot, SIGNAL, 1, 0)))
        self.assertEqual(binding['ref']['source_locator'], '/Root/Face#Blend/smile')
        sidecar = good(m.annotate_asset(snapshot, {'bindings': [binding]}))
        bound = good(m.inspect_asset(data, 'fbx', sidecar=sidecar))
        pack = good(m.compile_pack(good(m.validate_authoring(authoring()))))
        compiled = good(m.compile_mapping(pack, bound, good(m.profile_snapshot(pack, 'target')), 'usd'))
        evaluated = good(m.evaluate_mapping(compiled, [{'timestamp': 0, 'values': {'smile': 0.25}, 'validity': {'smile': True}}]))
        self.assertEqual(evaluated.to_dict()['samples'][0]['values'], {'out': 0.25})

    def test_units_and_axes_are_converted_and_declared(self):
        snapshot = good(m.inspect_asset(face(unit_cm=1.0, up=2, front=1, front_sign=-1).text(), 'fbx'))
        self.assertEqual(codes(snapshot), [('I_UNITS_CONVERTED', '/'), ('I_AXES_CONVERTED', '/')])
        root = snapshot.document['nodes'][0]
        # File +Z is up and +Y points back, so the file's +Y becomes -Z; 2 cm along it is 0.02 m.
        close(self, [msf_world_points(snapshot, '/Root/Face', 0.0)[3]], [(0, 0, -0.02)])
        self.assertTrue(root)

    def test_a_file_without_axis_settings_is_not_declared_as_converted(self):
        # Old exports (FBX 5000 and earlier) have no GlobalSettings; ufbx then leaves the axes as they are.
        text = face(unit_cm=100.0, up=2, front=1, front_sign=-1).text()
        text = text if isinstance(text, bytes) else text.encode()
        start = text.index(b'GlobalSettings:')
        stripped = text[:start] + text[text.index(b'\n}\n', start) + 3:]
        snapshot = good(m.inspect_asset(stripped, 'fbx'))
        self.assertNotIn(('I_AXES_CONVERTED', '/'), codes(snapshot))
        # Unconverted, the file's +Y stays +Y.
        close(self, [msf_world_points(snapshot, '/Root/Face', 0.0)[3]], [(0, 0.02 * 0.01 * 100.0, 0)])

    def test_the_unit_reported_is_the_one_ufbx_converted_from(self):
        # 3ds Max writes OriginalUnitScaleFactor for the unit the scene was made in; ufbx converts by UnitScaleFactor.
        metres = good(m.inspect_asset(face(unit_cm=100.0, original_unit_cm=1.0).text(), 'fbx'))
        self.assertEqual(codes(metres), [])
        close(self, [msf_world_points(metres, '/Root/Face', 0.0)[2]], [(1, 2, 0)])
        centimetres = good(m.inspect_asset(face(unit_cm=1.0, original_unit_cm=100.0).text(), 'fbx'))
        self.assertEqual(codes(centimetres), [('I_UNITS_CONVERTED', '/')])
        self.assertIn('0.01 metres per unit', thaw(centimetres.source['losses'])[0]['message'])
        close(self, [msf_world_points(centimetres, '/Root/Face', 0.0)[2]], [(0.01, 0.02, 0)])

    def test_duplicate_names_and_geometry_helpers_get_distinct_paths(self):
        scene = Scene()
        root = scene.model('Root')
        for x in (0, 2):
            node = scene.model('Copy', root, kind='Mesh', translation=(x, 0, 0), geometric_translation=(0, 0, x + 1))
            if x == 0:
                geometry = scene.mesh(node, 'Shared', [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]])
            else:
                scene.connect(geometry, node)
        snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
        paths = snapshot.source['node_paths']
        self.assertEqual(paths[:3], ('/Root', '/Root/Copy[0]', '/Root/Copy[0]#helper:geometry'))
        self.assertIn('/Root/Copy[1]#helper:geometry', paths)
        self.assertIn(('W_HELPER_NODES', '/'), codes(snapshot))
        close(self, msf_world_points(snapshot, '/Root/Copy[1]#helper:geometry', 0.0), [(2, 0, 3), (3, 0, 3), (2, 1, 3)])

    def test_empty_meshes_tiny_rotations_and_deep_hierarchies(self):
        scene = Scene()
        root = scene.model('Root', rotation=(1e-170, 0, 0))
        empty = scene.model('Empty', root, kind='Mesh')
        scene.mesh(empty, 'Empty', [], [])
        snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
        self.assertEqual(codes(snapshot), [('W_SKIPPED', '/')])
        self.assertEqual(thaw(snapshot.source['losses'])[0]['message'], 'Skipped 1 empty mesh.')
        self.assertNotIn('meshes', {k for k, v in snapshot.document.items() if v})
        deep = Scene()
        parent = 0
        for k in range(1100):
            parent = deep.model(f'n{k}', parent)
        self.assertEqual(errors(m.inspect_asset(deep.text(), 'fbx')), [('E_SOURCE_PARSE', '/')])

    def test_cameras_lights_and_materials_are_counted_as_skipped(self):
        scene = face()
        scene.attribute(scene.model('Cam'), 'Camera')
        scene.attribute(scene.model('Sun'), 'Light')
        scene.material(1002, 'Skin')
        snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
        self.assertEqual(codes(snapshot), [('W_SKIPPED', '/')])
        self.assertEqual(thaw(snapshot.source['losses'])[0]['message'], 'Skipped 1 camera, 1 light and 1 material.')
        self.assertIn('/Cam', snapshot.source['node_paths'])

    def test_smooth_subdivision_surfaces_are_declared_as_cages(self):
        # Smoothness 2 and 3 display the smoothed surface, 1 the cage; zero preview levels leave it unsmoothed.
        cases = {(3, 2): [('W_SUBDIV_CAGE', '/Body')], (2, 1): [('W_SUBDIV_CAGE', '/Body')], (1, 2): [], (3, 0): []}
        for subdivision, expected in cases.items():
            with self.subTest(subdivision=subdivision):
                scene = Scene()
                body = scene.model('Body', kind='Mesh')
                scene.mesh(body, 'Body', [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [[0, 1, 2, 3]], subdivision=subdivision)
                data = scene.text()
                self.assertEqual(codes(good(m.inspect_asset(data, 'fbx'))), expected)
                if expected:
                    strict = m.inspect_asset(data, 'fbx', options={'losses': 'strict'})
                    self.assertEqual(errors(strict), [('E_SUBDIV_CAGE', '/Body')])

    def test_vertex_caches_are_declared_as_dropped_point_animation(self):
        scene = face()
        scene.cache(1003, 'Face')  # the Face geometry
        snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
        self.assertEqual(codes(snapshot), [('W_POINTS_ANIMATION_DROPPED', '/Root/Face')])
        self.assertEqual(positions(snapshot), [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
        strict = m.inspect_asset(scene.text(), 'fbx', options={'losses': 'strict'})
        self.assertEqual(errors(strict), [('E_POINTS_ANIMATION_DROPPED', '/Root/Face')])

    def test_unreadable_files_and_reader_memory(self):
        self.assertEqual(errors(m.inspect_asset(b'; FBX 7.4.0 project file\nObjects: { garbage', 'fbx')), [('E_SOURCE_PARSE', '/')])
        result = m.inspect_asset(face().text(), 'fbx', limits=m.sources.SourceLimits(max_reader_memory=4096))
        self.assertEqual(errors(result), [('E_SOURCE_MEMORY', '/')])


def euler(order, degrees):
    """Rotation matrix (rows) for FBX Euler angles; order names the axis applied first, e.g. XYZ = Rz*Ry*Rx."""
    def axis(k, a):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        i, j = [(1, 2), (2, 0), (0, 1)][k]
        out = [[float(r == q) for q in range(3)] for r in range(3)]
        out[i][i], out[i][j], out[j][i], out[j][j] = c, -s, s, c
        return out
    result = [[float(r == q) for q in range(3)] for r in range(3)]
    for k in ['XYZ', 'XZY', 'YZX', 'YXZ', 'ZXY', 'ZYX'][order]:
        idx = 'XYZ'.index(k)
        result = matmul(axis(idx, degrees[idx]), result)
    return result


def matmul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(len(b))) for c in range(len(b[0]))] for r in range(len(a))]


def affine(linear=None, t=(0, 0, 0)):
    linear = linear or [[float(r == c) for c in range(3)] for r in range(3)]
    return [list(linear[r]) + [float(t[r])] for r in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def inverse_rigid(mat):
    rt = [[mat[c][r] for c in range(3)] for r in range(3)]
    t = [-sum(rt[r][k] * mat[k][3] for k in range(3)) for r in range(3)]
    return affine(rt, t)


def fbx_local(p):
    """FBX SDK local matrix: T * Roff * Rp * Rpre * R * Rpost^-1 * Rp^-1 * Soff * Sp * S * Sp^-1."""
    g = lambda key, default=(0, 0, 0): p.get(key, default)
    order = p.get('rotation_order', 0)
    neg = lambda v: tuple(-x for x in v)
    scale = g('scale', (1, 1, 1))
    parts = [affine(t=g('translation')), affine(t=g('rotation_offset')), affine(t=g('rotation_pivot')),
             affine(euler(0, g('pre_rotation'))), affine(euler(order, g('rotation'))), inverse_rigid(affine(euler(0, g('post_rotation')))),
             affine(t=neg(g('rotation_pivot'))), affine(t=g('scaling_offset')), affine(t=g('scaling_pivot')),
             affine([[scale[0], 0, 0], [0, scale[1], 0], [0, 0, scale[2]]]), affine(t=neg(g('scaling_pivot')))]
    out = affine()
    for part in parts:
        out = matmul(out, part)
    return out


def oracle_worlds(nodes):
    """World matrices of (name, parent name, properties) rows, with FBX inherit types as in the FBX SDK:
    1 (RSrs) composes matrices, 0 (RrSs) applies the parent's scale after the child's rotation, 2 (Rrs) drops it.
    In every mode the parent's full matrix still carries the child's translation."""
    worlds = {}
    for name, parent, p in nodes:
        local = fbx_local(p)
        linear = [row[:3] for row in local[:3]]
        if parent is None:
            worlds[name] = local
            continue
        mode = p.get('inherit_type', 0)
        pw = worlds[parent]
        scale = [math.dist([0, 0, 0], [pw[r][c] for r in range(3)]) for c in range(3)]
        prot = affine([[pw[r][c] / scale[c] for c in range(3)] for r in range(3)], [pw[r][3] for r in range(3)])
        if mode == 1:
            world = matmul(pw, local)
        else:
            s = [1.0, 1.0, 1.0] if mode == 2 else scale
            # Parent rotation and translation, then the child's rotation, then the parent's scale in the child's frame.
            translated_ = [sum(pw[r][k] * local[k][3] for k in range(3)) + pw[r][3] for r in range(3)]
            child = matmul([[prot[r][c] for c in range(3)] for r in range(3)], linear)
            rotation = [[child[r][c] for c in range(3)] for r in range(3)]
            world = affine([[rotation[r][c] * s[c] for c in range(3)] for r in range(3)], translated_)
        worlds[name] = world
    return worlds


@unittest.skipUnless(HAVE_UFBX, 'msf-tools-ufbx is not installed')
class FbxPivots(unittest.TestCase):
    def test_pivots_offsets_and_pre_post_rotation_match_the_fbx_formula(self):
        rows = [('Root', None, dict(translation=(1, 2, 3), rotation=(10, 20, 30), rotation_order=4, rotation_pivot=(0.5, 0, 0),
                                    scaling_pivot=(0, 0.25, 0), rotation_offset=(0, 0, 1), scaling_offset=(0.1, 0, 0),
                                    pre_rotation=(0, 0, 45), post_rotation=(15, 0, 0), scale=(2, 2, 2), inherit_type=1)),
                ('Arm', 'Root', dict(translation=(0, 1, 0), rotation=(0, 90, 0), rotation_pivot=(0, 0.5, 0), scale=(1, 1, 1),
                                     inherit_type=1))]
        scene = Scene()
        ids = {}
        for name, parent, p in rows:
            ids[name] = scene.model(name, ids.get(parent, 0), kind='Mesh', **p)
        geometry = scene.mesh(ids['Arm'], 'Arm', [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]])
        self.assertTrue(geometry)
        snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
        self.assertIn(('I_PIVOTS_BAKED', '/'), codes(snapshot))
        world = oracle_worlds(rows)['Arm']
        wanted = [[sum(world[r][k] * p[k] for k in range(3)) + world[r][3] for r in range(3)] for p in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]]
        close(self, msf_world_points(snapshot, mesh_node(snapshot, '/Root/Arm'), 0.0), wanted)

    def test_inherit_types_match_the_fbx_sdk_rules(self):
        for mode in (0, 1, 2):
            with self.subTest(inherit_type=mode):
                rows = [('Root', None, dict(rotation=(0, 0, 90), scale=(2, 3, 4), inherit_type=1)),
                        ('Arm', 'Root', dict(rotation=(90, 0, 0), translation=(1, 0, 0), inherit_type=mode))]
                scene = Scene()
                root = scene.model('Root', **rows[0][2])
                arm = scene.model('Arm', root, kind='Mesh', **rows[1][2])
                scene.mesh(arm, 'Arm', [(1, 2, 3), (0, 0, 0), (0, 1, 0)], [[0, 1, 2]])
                snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
                world = oracle_worlds(rows)['Arm']
                wanted = [[sum(world[r][k] * p[k] for k in range(3)) + world[r][3] for r in range(3)] for p in [(1, 2, 3), (0, 0, 0), (0, 1, 0)]]
                close(self, msf_world_points(snapshot, mesh_node(snapshot, '/Root/Arm'), 0.0), wanted)

    def test_inherit_types_reproduce_the_codex_affine_witness_points(self):
        # Literal points from the archived Codex FBX carry tests: parent Rz(90) with scale (2, 3, 4), child Rx(90),
        # point (1, 2, 3).
        for mode, expected in ((0, (12, 2, 6)), (1, (9, 2, 8)), (2, (3, 1, 2))):
            with self.subTest(inherit_type=mode):
                scene = Scene()
                root = scene.model('Root', rotation=(0, 0, 90), scale=(2, 3, 4), inherit_type=1)
                arm = scene.model('Arm', root, kind='Mesh', rotation=(90, 0, 0), inherit_type=mode)
                scene.mesh(arm, 'Arm', [(1, 2, 3), (0, 0, 0), (0, 1, 0)], [[0, 1, 2]])
                snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
                close(self, msf_world_points(snapshot, mesh_node(snapshot, '/Root/Arm'), 0.0)[:1], [expected])


def skinned_scene(skinning='Linear', weights=None):
    scene = Scene()
    root = scene.model('Root', kind='LimbNode')
    arm = scene.model('Arm', root, kind='LimbNode', translation=(0, 1, 0), rotation=(0, 0, 30))
    body = scene.model('Body', kind='Mesh', translation=(5, 0, 0))
    geometry = scene.mesh(body, 'Body', [(0, 0, 0), (1, 1, 0), (0, 2, 0), (1, 2, 0)], [[0, 1, 3, 2]])
    weights = weights or ([0, 1, 2], [1.0, 0.5, 0.25], [1, 2, 3], [0.5, 0.75, 1.0])
    scene.skin(geometry, [(root, weights[0], weights[1], translated(-5, 0, 0), IDENTITY),
                          (arm, weights[2], weights[3], translated(-5, -1, 0), translated(0, 1, 0))], skinning)
    return scene, geometry


def ufbx_skinned_world(data, mesh=0, stack=-1, time=0.0):
    from msf_tools_ufbx import ffi, lib
    handle, err = open_scene(data)
    try:
        sizes = ffi.new('uint32_t[8]')
        lib.msf_fbx_mesh_sizes(handle, mesh, sizes)
        out, text = ffi.new('double[]', 3 * sizes[0]), ffi.new('char[256]')
        assert lib.msf_fbx_skinned_points(handle, stack, time, mesh, out, sizes[0], text, 256), ffi.string(text)
        return [tuple(out[3 * v:3 * v + 3]) for v in range(sizes[0])]
    finally:
        lib.msf_fbx_close(handle)


@unittest.skipUnless(HAVE_UFBX, 'msf-tools-ufbx is not installed')
class FbxSkin(unittest.TestCase):
    def test_skinned_points_match_ufbx_skinning(self):
        scene, _ = skinned_scene()
        data = scene.text()
        snapshot = good(m.inspect_asset(data, 'fbx'))
        self.assertEqual(codes(snapshot), [])
        self.assertEqual(snapshot.source['node_paths'], ('/Body', '/Root', '/Root/Arm'))
        self.assertEqual([s['joints'] for s in thaw(snapshot.document['skins'])], [[1, 2]])
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

    def test_skin_losses_are_declared(self):
        scene, _ = skinned_scene('DualQuaternion', ([0, 1], [1.0, 1.0], [1], [1.0]))
        snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
        self.assertEqual(codes(snapshot), [('W_WEIGHTS_NORMALIZED', '/Body'), ('W_UNWEIGHTED_VERTICES', '/Body'),
                                           ('W_SKINNING_METHOD', '/Body')])


@unittest.skipUnless(HAVE_UFBX, 'msf-tools-ufbx is not installed')
class FbxBlend(unittest.TestCase):
    def test_inbetweens_and_partial_channels(self):
        scene = Scene()
        body = scene.model('Body', kind='Mesh')
        geometry = scene.mesh(body, 'Body', [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]])
        scene.blend(geometry, 'Face', [('smile', 0, [(50, [2], [(0, 0.25, 0)]), (100, [2], [(0, 1, 0)])]),
                                       ('half', 0, [(50, [1], [(0, 0, 0.5)])]), ('half', 0, [(100, [0], [(1, 0, 0)])])])
        data = scene.text()
        snapshot = good(m.inspect_asset(data, 'fbx'))
        self.assertEqual(snapshot.source['target_keys'], (('Face/smile', 'Face/half[0]', 'Face/half[1]'),))
        self.assertEqual(codes(snapshot), [('W_INBETWEENS_DROPPED', '/Body'), ('W_INBETWEEN_PARTIAL', '/Body')])
        close(self, positions(snapshot, morph_weights={0: [1.0, 1.0, 0.0]}), [(0, 0, 0), (1, 0, 1.0), (0, 2, 0)])
        strict = m.inspect_asset(data, 'fbx', options={'losses': 'strict'})
        self.assertEqual([d.code for d in strict.report.diagnostics], ['E_INBETWEEN_UNSUPPORTED', 'E_INBETWEEN_PARTIAL'])


def animated(start=0.0, stacks=1):
    scene = face()
    body = 1002 + 0  # 'Face' model id
    smile = None
    for obj in scene.objects:
        if '"SubDeformer::smile"' in obj:
            smile = int(obj.split(':')[1].split(',')[0])
    for k in range(stacks):
        scene.animation(f'Take {k}', start, start + 1.0, [
            (body, 'Lcl Translation', {'X': [(start, 0.0), (start + 1.0, 10.0 * (k + 1))], 'Y': [(start, 0.0), (start + 1.0, 0.0)],
                                       'Z': [(start, 0.0), (start + 1.0, 0.0)]}),
            (smile, 'DeformPercent', {'DeformPercent': [(start, 0.0), (start + 1.0, 100.0)]})])
    return scene


@unittest.skipUnless(HAVE_UFBX, 'msf-tools-ufbx is not installed')
class FbxAnimation(unittest.TestCase):
    def test_stack_samples_translations_and_blend_weights(self):
        snapshot = good(m.inspect_asset(animated().text(), 'fbx'))
        sample = m.sample_animation(snapshot, 0, 0.5).value
        self.assertAlmostEqual(sample[1]['translation'][0], 5.0, places=5)
        self.assertAlmostEqual(sample[1]['weights'][0], 0.5, places=5)
        times = m.decode_accessor(snapshot, snapshot.document['animations'][0]['samplers'][0]['input']).value
        self.assertEqual(len(times), 25)

    def test_stack_choice_sample_rate_and_time_shift(self):
        data = animated(stacks=2).text()
        snapshot = good(m.inspect_asset(data, 'fbx', options={'animation': 'Take 1', 'sample_rate': 4}))
        self.assertEqual(codes(snapshot), [('W_ANIMATIONS_SKIPPED', '/')])
        self.assertAlmostEqual(m.sample_animation(snapshot, 0, 1.0).value[1]['translation'][0], 20.0, places=5)
        self.assertEqual(len(m.decode_accessor(snapshot, snapshot.document['animations'][0]['samplers'][0]['input']).value), 5)
        self.assertEqual(errors(m.inspect_asset(data, 'fbx', options={'animation': 'Missing'})), [('E_SOURCE_OPTIONS', '/options/animation')])
        shifted = good(m.inspect_asset(animated(start=-0.5).text(), 'fbx'))
        self.assertIn(('W_TIME_SHIFTED', '/'), codes(shifted))
        self.assertAlmostEqual(m.sample_animation(shifted, 0, 1.0).value[1]['translation'][0], 10.0, places=5)

    def test_a_stop_time_equal_to_the_last_frame_in_binary32_adds_no_sample(self):
        # Kenney's Mini Characters store 40 frames at 60 fps as a stop time of float32(2/3), 1.4e-8 s past frame 40.
        stop = struct.unpack('<f', struct.pack('<f', 2 / 3))[0]
        scene = face()
        scene.settings['fps'] = 60.0
        scene.animation('walk', 0.0, stop, [(1002, 'Lcl Translation', {'X': [(0.0, 0.0), (stop, 1.0)], 'Y': [(0.0, 0.0)], 'Z': [(0.0, 0.0)]})])
        snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
        times = m.decode_accessor(snapshot, snapshot.document['animations'][0]['samplers'][0]['input']).value
        self.assertEqual(len(times), 41)
        self.assertAlmostEqual(m.sample_animation(snapshot, 0, times[-1][0]).value[1]['translation'][0], 1.0, places=5)

    def test_constant_animated_values_that_differ_from_the_static_pose_are_kept(self):
        # Found by comparing with the DCC-exported OBJ frames in ufbx's corpus (blender_279_sausage "Base").
        scene = face()
        smile = next(int(o.split(':')[1].split(',')[0]) for o in scene.objects if '"SubDeformer::smile"' in o)
        scene.animation('Hold', 0.0, 1.0, [
            (1002, 'Lcl Translation', {'X': [(0.0, 5.0), (1.0, 5.0)], 'Y': [(0.0, 0.0), (1.0, 0.0)], 'Z': [(0.0, 0.0), (1.0, 0.0)]}),
            (smile, 'DeformPercent', {'DeformPercent': [(0.0, 100.0), (1.0, 100.0)]})])
        snapshot = good(m.inspect_asset(scene.text(), 'fbx'))
        sample = m.sample_animation(snapshot, 0, 0.5).value
        self.assertEqual(sample[1]['translation'], (5.0, 0.0, 0.0))
        self.assertEqual(sample[1]['weights'], (1.0, 0.0))

    def test_long_clips_on_large_rigs_are_refused_before_sampling(self):
        from msf_tools.sources import fbx
        real = fbx.lib

        class NoEvaluation:
            def __getattr__(self, name):
                if name == 'msf_fbx_evaluate':
                    raise AssertionError('the animation was sampled before the limit was checked')
                return getattr(real, name)

        scene = Scene()
        parent = 0
        for k in range(200):
            parent = scene.model(f'n{k}', parent)
        scene.animation('Long', 0.0, 3000.0, [(parent, 'Lcl Translation', {
            'X': [(0.0, 0.0), (3000.0, 1.0)], 'Y': [(0.0, 0.0), (3000.0, 0.0)], 'Z': [(0.0, 0.0), (3000.0, 0.0)]})])
        with unittest.mock.patch.object(fbx, 'lib', NoEvaluation()):
            result = m.inspect_asset(scene.text(), 'fbx')
        self.assertEqual(errors(result), [('E_RESOURCE_LIMIT', '/')])
        self.assertIn('max_animation_values', result.report.diagnostics[0].remediation)

    def test_the_animation_value_limit_counts_samples_nodes_and_channels(self):
        # 25 samples x (2 nodes x 16 matrix values + 2 blend weights) = 850 values.
        data = animated().text()
        good(m.inspect_asset(data, 'fbx', limits=m.sources.SourceLimits(max_animation_values=850)))
        result = m.inspect_asset(data, 'fbx', limits=m.sources.SourceLimits(max_animation_values=849))
        self.assertEqual(errors(result), [('E_RESOURCE_LIMIT', '/')])

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

    def test_isolated_reader_matches_in_process(self):
        data = animated().text()
        local = good(m.inspect_asset(data, 'fbx'))
        isolated = good(m.inspect_asset(data, 'fbx', isolate=True))
        self.assertEqual(m.canonical_json(isolated.to_dict()), m.canonical_json(local.to_dict()))


if __name__ == '__main__':
    unittest.main()
