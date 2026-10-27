# SPDX-License-Identifier: MIT
"""The USD adapter with the real usd-core reader; skipped when pxr is not installed."""
import importlib.util
import io
import math
from pathlib import Path
import struct
import tempfile
import unittest
import unittest.mock
import zipfile

import msf_tools as m
from msf_tools.common import digest, thaw
from msf_tools.sources import SourceLimits

HAVE_USD = importlib.util.find_spec('pxr') is not None


def setUpModule():
    # Importing pxr takes about half a second; pay it once here, not inside the first test.
    if HAVE_USD:
        importlib.import_module('msf_tools.sources.usd')


SIGNAL = {'id': 'smile', 'value_type': 'scalar', 'units': '1', 'domain': {'min': 0, 'max': 1}, 'calibration': 'literal'}

FACE = b'''#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Xform "Root"
{
    double3 xformOp:translate = (0, 1, 0)
    uniform token[] xformOpOrder = ["xformOp:translate"]
    def Mesh "Face" (prepend apiSchemas = ["SkelBindingAPI"])
    {
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 3, 2]
        uniform token subdivisionScheme = "none"
        uniform token[] skel:blendShapes = ["smile", "blink"]
        rel skel:blendShapeTargets = [</Root/Face/Smile>, </Root/Face/Blink>]
        def BlendShape "Smile"
        {
            uniform int[] pointIndices = [0]
            uniform vector3f[] offsets = [(0, 0.5, 0)]
        }
        def BlendShape "Blink"
        {
            uniform vector3f[] offsets = [(0, 0, 0), (0, 0, 0.25), (0, 0, 0), (0, 0, 0)]
        }
    }
}
'''


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def good(result):
    assert result.ok, result.report.to_dict()
    return result.value


def positions(snapshot, **kwargs):
    return good(m.evaluate_geometry(snapshot, **kwargs)).to_dict()['instances'][0]['primitives'][0]['positions']


def authoring():
    evidence = {'evidence': ['e'], 'evidence_status': 'verified_current', 'disposition': 'mapped'}
    return {'schema_version': '1.0', 'data_version': '0.1.0', 'operator_version': '1.0', 'id': 'usd', 'license': 'MIT',
            'signals': [dict(SIGNAL, label='Smile', **evidence), dict(SIGNAL, id='out', label='Out', **evidence)],
            'profiles': [{'id': 'target', 'label': 'Target', 'signal_ids': ['out']}],
            'mappings': [{'id': 'usd', 'rules': [{'id': 'r', 'inputs': ['smile'], 'outputs': ['out'], 'operator': {'id': 'identity'},
                                                  'disposition': 'mapped', 'mapping_quality': 'exact', 'assumptions': [],
                                                  'loss_annotations': [], **{k: evidence[k] for k in ('evidence', 'evidence_status')}}]}],
            'evidence': [{'id': 'e', 'claim': 'USD walking skeleton.', 'status': 'verified_current', 'license': 'MIT',
                          'authorship': 'MSF Tools contributors'}]}


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdWalkingSkeleton(unittest.TestCase):
    def test_static_mesh_through_inspect_geometry_annotate_and_map(self):
        snapshot = good(m.inspect_asset(FACE, 'usda'))
        source = thaw(snapshot.source)
        self.assertEqual((source['format'], source['adapter'], source['adapter_version']), ('usda', 'msf-usd', '1'))
        self.assertTrue(source['reader'].startswith('usd-core 0.'))
        self.assertEqual(source['node_paths'], ['/Root', '/Root/Face'])
        self.assertEqual(source['target_keys'], [['smile', 'blink']])
        primitive = snapshot.document['meshes'][0]['primitives'][0]
        self.assertEqual(m.decode_accessor(snapshot, primitive['indices']).value, ((0,), (1,), (3,), (0,), (3,), (2,)))
        self.assertEqual(snapshot.document['nodes'][0]['translation'], (0.0, 1.0, 0.0))
        self.assertEqual(positions(snapshot), [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]])
        self.assertEqual(positions(snapshot, morph_weights={1: [1.0, 1.0]}),
                         [[0.0, 0.5, 0.0], [1.0, 0.0, 0.25], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]])
        binding = thaw(good(m.morph_binding(snapshot, SIGNAL, 1, 0)))
        self.assertEqual(binding['ref']['source_locator'], '/Root/Face#smile')
        sidecar = good(m.annotate_asset(snapshot, {'bindings': [binding]}))
        bound = good(m.inspect_asset(FACE, 'usda', sidecar=sidecar))
        pack = good(m.compile_pack(good(m.validate_authoring(authoring()))))
        compiled = good(m.compile_mapping(pack, bound, good(m.profile_snapshot(pack, 'target')), 'usd'))
        evaluated = good(m.evaluate_mapping(compiled, [{'timestamp': 0, 'values': {'smile': 0.25}, 'validity': {'smile': True}}]))
        self.assertEqual(evaluated.to_dict()['samples'][0]['values'], {'out': 0.25})

    def test_reader_errors_are_parse_diagnostics(self):
        result = m.inspect_asset(b'#usda 1.0\ndef Mesh "x" { garbage', 'usda')
        self.assertEqual([d.code for d in result.report.diagnostics], ['E_SOURCE_PARSE'])


def layer(body, header=''):
    return (f'#usda 1.0\n({header})\n' if header else '#usda 1.0\n').encode() + body.encode()


ROOT_WITH_SUBLAYER = layer('def Xform "Root" (references = @./parts/ref.usda@</Thing>) {}\n',
                           'subLayers = [@./parts/sub.usda@]')
SUB = layer('def Xform "FromSub" {}\n')
REF = layer('def Xform "Thing"\n{\n    def Xform "Inner" {}\n}\n')


def usdz(members, compress=zipfile.ZIP_STORED, encrypt=False):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = compress
            archive.writestr(info, payload)
    data = bytearray(buffer.getvalue())
    if encrypt:
        # zipfile clears flag bits on write, so set the encryption bit in both headers by hand.
        for magic, offset in ((b'PK\x03\x04', 6), (b'PK\x01\x02', 8)):
            at = data.find(magic)
            data[at + offset] |= 0x1
    return bytes(data)


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdDependencies(unittest.TestCase):
    files = {'parts/sub.usda': SUB, 'parts/ref.usda': REF}

    def errors(self, result):
        return [(d.code, d.ref) for d in result.report.diagnostics if d.severity == 'error']

    def test_relative_layers_are_fetched_through_the_resolver(self):
        snapshot = good(m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=self.files.__getitem__))
        self.assertEqual(snapshot.source['node_paths'], ('/FromSub', '/Root', '/Root/Inner'))
        self.assertEqual(thaw(snapshot.source['dependencies']),
                         [{'uri': uri, 'sha256': digest(self.files[uri]), 'byte_length': len(self.files[uri])}
                          for uri in ('parts/ref.usda', 'parts/sub.usda')])

    def test_unsafe_or_unresolvable_references_are_refused(self):
        self.assertEqual(self.errors(m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda')), [('E_SOURCE_REFERENCE', '/')])
        for asset in ('/etc/layer.usda', 'https://example.invalid/a.usda', '../outside.usda', 'parts/../../outside.usda',
                      './parts/../../outside.usda', 'C:/layer.usda', 'C:layer.usda', 'parts\\sub.usda'):
            with self.subTest(asset=asset):
                data = layer('def Xform "Root" {}\n', f'subLayers = [@{asset}@]')
                self.assertEqual(self.errors(m.inspect_asset(data, 'usda', resolver=lambda uri: SUB)), [('E_SOURCE_REFERENCE', '/')])
        clipped = layer('def Xform "Root" (\n    clips = {\n        dictionary default = {\n'
                        '            asset[] assetPaths = [@/etc/clip.usda@]\n            string primPath = "/Root"\n'
                        '        }\n    }\n)\n{\n}\n')
        self.assertEqual(self.errors(m.inspect_asset(clipped, 'usda', resolver=lambda uri: SUB)), [('E_SOURCE_REFERENCE', '/')])
        broken = dict(self.files, **{'parts/sub.usda': b'#usda 1.0\ndef Xform "x" { garbage'})
        self.assertEqual(self.errors(m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=broken.__getitem__)),
                         [('E_SOURCE_PARSE', '/')])

    def clip_on_variant(self, host):
        (host / 'clip.usda').write_text('#usda 1.0\nover "A" {\n    double3 xformOp:translate.timeSamples = {\n        0: (5, 0, 0),\n'
                                        '    }\n    uniform token[] xformOpOrder = ["xformOp:translate"]\n}\n')
        # Ivo's probe: clips authored on the variant spec itself, naming a host file outside the resolver root.
        return (f'#usda 1.0\ndef Xform "A" (\n    variants = {{\n        string v = "x"\n    }}\n    prepend variantSets = "v"\n)\n{{\n'
                f'    variantSet "v" = {{\n        "x" (\n            clips = {{\n                dictionary default = {{\n'
                f'                    asset[] assetPaths = [@{host}/clip.usda@]\n                    string primPath = "/A"\n'
                f'                    double2[] active = [(0, 0)]\n                    double2[] times = [(0, 0)]\n                }}\n'
                f'            }}\n        ) {{\n            double3 xformOp:translate\n'
                f'            uniform token[] xformOpOrder = ["xformOp:translate"]\n        }}\n    }}\n}}\n').encode()

    def test_clips_on_variant_specs_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = Path(tmp).resolve()
            result = m.inspect_asset(self.clip_on_variant(host), 'usda', resolver=m.LocalResolver(host))
        self.assertEqual(self.errors(result), [('E_SOURCE_REFERENCE', '/')])

    def test_layers_loaded_from_outside_the_materialized_folder_are_refused(self):
        from msf_tools.sources import usd
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(usd, '_refuse_clips', lambda layer: None):
            host = Path(tmp).resolve()
            result = m.inspect_asset(self.clip_on_variant(host), 'usda', resolver=m.LocalResolver(host))
        self.assertEqual(self.errors(result), [('E_SOURCE_REFERENCE', '/')])
        self.assertIn('outside', result.report.diagnostics[0].message)

    def test_bare_relative_layer_paths_are_anchored_to_their_layer(self):
        # USD tries a bare path next to the referring layer before any search path; only that first step is allowed.
        fetched = []
        data = layer('def Xform "Root" {}\n', 'subLayers = [@parts/sub.usda@]')
        snapshot = good(m.inspect_asset(data, 'usda', resolver=lambda uri: fetched.append(uri) or SUB))
        self.assertEqual((fetched, snapshot.source['node_paths']), (['parts/sub.usda'], ('/FromSub', '/Root')))

    def test_dependency_limits_apply_while_fetching(self):
        fetched = []
        def resolver(uri):
            fetched.append(uri)
            return self.files[uri]
        result = m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=resolver, limits=SourceLimits(max_dependencies=1))
        self.assertEqual(self.errors(result), [('E_RESOURCE_LIMIT', '/source/dependencies')])
        self.assertEqual(len(fetched), 2)
        result = m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=self.files.__getitem__,
                                 limits=SourceLimits(max_dependency_bytes=len(SUB) + len(REF) - 1))
        self.assertEqual(self.errors(result), [('E_RESOURCE_LIMIT', '/source/dependencies')])

    def test_usdz_packages_keep_dependencies_inside(self):
        package = usdz([('root.usda', ROOT_WITH_SUBLAYER), ('parts/sub.usda', SUB), ('parts/ref.usda', REF)])
        snapshot = good(m.inspect_asset(package, 'usdz'))
        self.assertEqual(snapshot.source['node_paths'], ('/FromSub', '/Root', '/Root/Inner'))
        self.assertEqual(snapshot.source['dependencies'], ())
        missing = usdz([('root.usda', ROOT_WITH_SUBLAYER), ('parts/sub.usda', SUB)])
        self.assertEqual(self.errors(m.inspect_asset(missing, 'usdz', resolver=self.files.__getitem__)), [('E_SOURCE_REFERENCE', '/')])

    def test_unsafe_usdz_archives_are_refused(self):
        root = layer('def Xform "Root" {}\n')
        for package in (usdz([('root.usda', root)], compress=zipfile.ZIP_DEFLATED), usdz([('root.usda', root)], encrypt=True),
                        usdz([('root.usda', root), ('../escape.usda', SUB)]), usdz([('root.usda', root), ('/abs.usda', SUB)]),
                        usdz([('root.usda', root), ('a\\b.usda', SUB)]), usdz([('root.usda', root), ('root.usda', root)]),
                        b'PK\x03\x04not a zip'):
            with self.subTest(package=package[:40]):
                self.assertEqual(self.errors(m.inspect_asset(package, 'usdz')), [('E_USDZ_ARCHIVE', '/')])
        many = usdz([('root.usda', root), ('a.usda', SUB), ('b.usda', SUB)])
        self.assertEqual(self.errors(m.inspect_asset(many, 'usdz', limits=SourceLimits(max_usdz_members=2))), [('E_USDZ_ARCHIVE', '/')])
        self.assertTrue(m.inspect_asset(many, 'usdz', limits=SourceLimits(max_usdz_members=3)).ok)

    def test_usdc_bytes_inspect_like_usda(self):
        from pxr import Sdf
        import tempfile, os
        source = Sdf.Layer.CreateAnonymous('face.usda')
        source.ImportFromString(FACE.decode())
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'face.usdc')
            source.Export(path)
            data = open(path, 'rb').read()
        crate = good(m.inspect_asset(data, 'usdc'))
        text = good(m.inspect_asset(FACE, 'usda'))
        self.assertEqual(crate.source['format'], 'usdc')
        self.assertEqual(good(m.inspect_asset(data, 'usd')).source['format'], 'usdc')
        self.assertEqual(crate.document, text.document)


if __name__ == '__main__':
    unittest.main()


def trs(node):
    x, y, z, w = node.get('rotation', (0.0, 0.0, 0.0, 1.0))
    sx, sy, sz = node.get('scale', (1.0, 1.0, 1.0))
    t = node.get('translation', (0.0, 0.0, 0.0))
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[i][0] * sx, r[i][1] * sy, r[i][2] * sz, t[i]] for i in range(3)]


def world_points(snapshot, path, **kwargs):
    """Mesh points of the node at `path`, carried to world space through the static glTF node TRS chain."""
    index = snapshot.source['node_paths'].index(path)
    nodes = snapshot.document['nodes']
    parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', ())}
    instances = good(m.evaluate_geometry(snapshot, **kwargs)).to_dict()['instances']
    points = next(i for i in instances if i['node'] == index)['primitives'][0]['positions']
    while index is not None:
        matrix = trs(nodes[index])
        points = [[sum(matrix[r][c] * p[c] for c in range(3)) + matrix[r][3] for r in range(3)] for p in points]
        index = parent.get(index)
    return points


def mesh(name, points, counts, indices, extra='', scheme='none'):
    scheme_line = f'    uniform token subdivisionScheme = "{scheme}"\n' if scheme else ''
    return (f'def Mesh "{name}"\n{{\n    point3f[] points = {points}\n    int[] faceVertexCounts = {counts}\n'
            f'    int[] faceVertexIndices = {indices}\n{scheme_line}{extra}}}\n')


def xform(name, ops, body):
    lines = ''.join(f'    {op}\n' for op in ops)
    order = ', '.join('"' + op.split()[1].split('=')[0].split('.')[0] + '"' for op in ops if 'xformOp:' in op.split()[1])
    order_line = f'    uniform token[] xformOpOrder = [{order}]\n' if order else ''
    return f'def Xform "{name}"\n{{\n{lines}{order_line}' + ''.join('    ' + line + '\n' for line in body.splitlines()) + '}\n'


TRI = mesh('Tri', '[(100, 0, 0), (0, 100, 0), (0, 0, 100)]', '[3]', '[0, 1, 2]')
SHEAR = 'matrix4d xformOp:transform = ((1, 0, 0, 0), (0.5, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))'


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdMeshesAndTransforms(unittest.TestCase):
    def codes(self, snapshot):
        return [(d['code'], d['ref']) for d in thaw(snapshot.source['losses'])]

    def assertPoints(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            for x, y in zip(a, e):
                self.assertAlmostEqual(x, y, places=5)

    def test_units_and_up_axis_are_applied_to_the_data(self):
        shape = ('    uniform token[] skel:blendShapes = ["up"]\n    rel skel:blendShapeTargets = </Root/Tri/Up>\n'
                 '    def BlendShape "Up"\n    {\n        uniform int[] pointIndices = [0]\n'
                 '        uniform vector3f[] offsets = [(0, 0, 100)]\n    }\n')
        tri = mesh('Tri', '[(100, 0, 0), (0, 100, 0), (0, 0, 100)]', '[3]', '[0, 1, 2]', shape).replace(
            'def Mesh "Tri"', 'def Mesh "Tri" (prepend apiSchemas = ["SkelBindingAPI"])')
        data = layer(xform('Root', ['double3 xformOp:translate = (0, 0, 100)', 'float xformOp:rotateZ = 90'], tri),
                     'upAxis = "Z"\n    metersPerUnit = 0.01')
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(snapshot), [('I_UNITS_CONVERTED', '/'), ('I_AXES_CONVERTED', '/')])
        self.assertPoints(positions(snapshot), [[1, 0, 0], [0, 0, -1], [0, 1, 0]])
        self.assertPoints(positions(snapshot, morph_weights={1: [1.0]}), [[1, 1, 0], [0, 0, -1], [0, 1, 0]])
        # USD world points rotate about Z, then rise 100 cm along Z; C carries Z-up centimetres to Y-up metres.
        self.assertPoints(world_points(snapshot, '/Root/Tri'), [[0, 1, -1], [-1, 1, 0], [0, 2, 0]])

    def test_mirrored_nodes_keep_their_world_points(self):
        data = layer(xform('M', ['double3 xformOp:scale = (1, 1, -1)'], TRI), 'metersPerUnit = 1')
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(snapshot), [('I_MIRRORED', '/M')])
        self.assertLess(snapshot.document['nodes'][0]['scale'][0], 0)
        self.assertPoints(world_points(snapshot, '/M/Tri'), [[100, 0, 0], [0, 100, 0], [0, 0, -100]])

    def test_static_shear_on_an_unskinned_leaf_mesh_is_baked(self):
        data = layer(xform('Root', [], xform('Tri', [SHEAR], '').replace('def Xform "Tri"\n{\n', 'def Mesh "Tri"\n{\n'
                     '    point3f[] points = [(0, 1, 0), (1, 0, 0), (0, 0, 1)]\n    int[] faceVertexCounts = [3]\n'
                     '    int[] faceVertexIndices = [0, 1, 2]\n    uniform token subdivisionScheme = "none"\n')),
                     'metersPerUnit = 1')
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(snapshot), [('W_SHEAR_BAKED', '/Root/Tri')])
        self.assertEqual({k for k in ('translation', 'rotation', 'scale') if k in snapshot.document['nodes'][1]}, set())
        self.assertPoints(positions(snapshot), [[0.5, 1, 0], [1, 0, 0], [0, 0, 1]])
        strict = m.inspect_asset(data, 'usda', options={'losses': 'strict'})
        self.assertEqual([d.code for d in strict.report.diagnostics], ['E_SHEAR_UNSUPPORTED'])

    def test_shear_on_interior_or_animated_nodes_is_refused(self):
        interior = layer(xform('Root', [SHEAR], TRI), 'metersPerUnit = 1')
        animated = layer(mesh('Tri', '[(0, 1, 0), (1, 0, 0), (0, 0, 1)]', '[3]', '[0, 1, 2]',
                              '    matrix4d xformOp:transform.timeSamples = {0: ((1, 0, 0, 0), (0.5, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),'
                              ' 1: ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))}\n'
                              '    uniform token[] xformOpOrder = ["xformOp:transform"]\n'), 'metersPerUnit = 1')
        for data, ref in ((interior, '/Root'), (animated, '/Tri')):
            with self.subTest(ref=ref):
                result = m.inspect_asset(data, 'usda')
                self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], [('E_SHEAR_UNSUPPORTED', ref)])

    def test_point_animation_is_skipped_and_declared(self):
        data = layer(mesh('Tri', '[(0, 0, 0), (1, 0, 0), (0, 1, 0)]', '[3]', '[0, 1, 2]').replace(
            'point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]',
            'point3f[] points.timeSamples = {0: [(0, 0, 0), (1, 0, 0), (0, 1, 0)], 1: [(0, 0, 0), (2, 0, 0), (0, 1, 0)]}'),
            'metersPerUnit = 1')
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(snapshot), [('W_SKIPPED', '/')])
        self.assertEqual(thaw(snapshot.source['losses'])[0]['message'], 'Skipped 1 point animation.')
        self.assertEqual(positions(snapshot), [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    def test_holes_cages_winding_and_skipped_prims_are_declared(self):
        quads = mesh('Quads', '[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0), (2, 1, 0)]', '[4, 4]',
                     '[0, 1, 2, 3, 1, 4, 5, 2]', '    int[] holeIndices = [1]\n    uniform token orientation = "leftHanded"\n',
                     scheme=None)
        others = ('def Camera "Cam" {}\ndef BasisCurves "Hair"\n{\n    int[] curveVertexCounts = [2]\n'
                  '    point3f[] points = [(0, 0, 0), (0, 1, 0)]\n}\ndef Material "Skin" {}\n')
        snapshot = good(m.inspect_asset(layer(quads + others, 'metersPerUnit = 1'), 'usda'))
        self.assertEqual(self.codes(snapshot), [('W_SUBDIV_CAGE', '/Quads'), ('I_WINDING_FLIPPED', '/Quads'), ('W_SKIPPED', '/')])
        self.assertEqual(thaw(snapshot.source['losses'])[-1]['message'],
                         'Skipped 1 BasisCurves, 1 Camera, 1 Material and 1 hole face.')
        self.assertEqual(snapshot.source['node_paths'], ('/Cam', '/Hair', '/Quads'))
        primitive = snapshot.document['meshes'][0]['primitives'][0]
        self.assertEqual(m.decode_accessor(snapshot, primitive['indices']).value, ((0,), (2,), (1,), (0,), (3,), (2,)))


def matrices(rows):
    return '[' + ', '.join('((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (%s, %s, %s, 1))' % row for row in rows) + ']'


def rig(joints, indices, weights, size, *, header='metersPerUnit = 1', interpolation='vertex', binds=None, rests=None,
        mesh_extra='', points='[(0, 0, 0), (1, 1, 0), (0, 2, 0)]', anim=''):
    binds = binds or [(0, 0, 0)] * len(joints)
    rests = rests or [(0, 0, 0)] * len(joints)
    tokens = ', '.join(f'"{j}"' for j in joints)
    return layer(f"""def SkelRoot "Rig"
{{
    def Skeleton "Skel" (prepend apiSchemas = ["SkelBindingAPI"])
    {{
        uniform token[] joints = [{tokens}]
        uniform matrix4d[] bindTransforms = {matrices(binds)}
        uniform matrix4d[] restTransforms = {matrices(rests)}
{anim}    }}
    def Mesh "Body" (prepend apiSchemas = ["SkelBindingAPI"])
    {{
        point3f[] points = {points}
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        uniform token subdivisionScheme = "none"
        double3 xformOp:translate = (5, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
        int[] primvars:skel:jointIndices = {indices} (
            elementSize = {size}
            interpolation = "{interpolation}"
        )
        float[] primvars:skel:jointWeights = {weights} (
            elementSize = {size}
            interpolation = "{interpolation}"
        )
        rel skel:skeleton = </Rig/Skel>
{mesh_extra}    }}
}}
""", header)


ARM_ANIM = """        rel skel:animationSource = </Rig/Skel/Anim>
        def SkelAnimation "Anim"
        {
            uniform token[] joints = ["root/arm"]
            float3[] translations = [(0, 100, 0)]
            quatf[] rotations = [(0.7071068, 0, 0, 0.7071068)]
            half3[] scales = [(1, 1, 1)]
        }
"""


def baked_world_points(data, mesh_path, time=0.0):
    """usd-core's own skinning of the mesh, in world space, converted to metres and +Y up."""
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel
    copy = Sdf.Layer.CreateAnonymous('.usda')
    copy.ImportFromString(data.decode())
    stage = Usd.Stage.Open(copy)
    for prim in stage.Traverse():
        if prim.IsA(UsdSkel.Root):
            UsdSkel.BakeSkinning(UsdSkel.Root(prim), Gf.Interval(time, time))
    mesh = UsdGeom.Mesh(stage.GetPrimAtPath(mesh_path))
    world = mesh.ComputeLocalToWorldTransform(time)
    k = UsdGeom.GetStageMetersPerUnit(stage)
    z_up = UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z
    out = []
    for p in mesh.GetPointsAttr().Get(time):
        x, y, z = world.Transform(Gf.Vec3d(p))
        out.append([k * x, k * z, -k * y] if z_up else [k * x, k * y, k * z])
    return out


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdSkinning(unittest.TestCase):
    codes = UsdMeshesAndTransforms.codes

    def influences(self, snapshot, s=0):
        primitive = snapshot.document['meshes'][0]['primitives'][0]['attributes']
        if f'JOINTS_{s}' not in primitive:
            return None
        joints = m.decode_accessor(snapshot, primitive[f'JOINTS_{s}']).value
        weights = m.decode_accessor(snapshot, primitive[f'WEIGHTS_{s}']).value
        return [list(zip(j, w)) for j, w in zip(joints, weights)]

    def test_skinned_points_match_usd_bake_skinning(self):
        for header in ('metersPerUnit = 1', 'upAxis = "Z"\n    metersPerUnit = 0.01'):
            with self.subTest(header=header):
                data = rig(['root', 'root/arm'], '[0, 0, 0, 1, 1, 0]', '[1, 0, 0.5, 0.5, 1, 0]', 2, header=header,
                           binds=[(0, 0, 0), (0, 100, 0)], rests=[(0, 0, 0), (0, 100, 0)], anim=ARM_ANIM,
                           points='[(0, 0, 0), (100, 100, 0), (0, 200, 0)]')
                snapshot = good(m.inspect_asset(data, 'usda'))
                self.assertEqual(snapshot.source['node_paths'],
                                 ('/Rig', '/Rig/Body', '/Rig/Skel', '/Rig/Skel.joints/root', '/Rig/Skel.joints/root/arm'))
                self.assertEqual([skin['joints'] for skin in thaw(snapshot.document['skins'])], [[3, 4]])
                expected = baked_world_points(data, '/Rig/Body')
                actual = world_points(snapshot, '/Rig/Body')
                diagonal = math.dist([min(c) for c in zip(*expected)], [max(c) for c in zip(*expected)])
                for a, e in zip(actual, expected):
                    self.assertLess(math.dist(a, e), 1e-5 * diagonal, (actual, expected))

    def test_more_than_four_influences_are_kept_or_truncated(self):
        joints = ['r', 'r/a', 'r/b', 'r/c', 'r/d']
        data = rig(joints, '[0, 1, 2, 3, 4, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0]',
                   '[0.3, 0.25, 0.2, 0.15, 0.1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0]', 5)
        faithful = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(faithful), [('I_INFLUENCES_N', '/Rig/Body')])
        self.assertEqual(self.influences(faithful, 1)[0], [(4, f32(0.1)), (0, 0.0), (0, 0.0), (0, 0.0)])
        top4 = good(m.inspect_asset(data, 'usda', options={'influences': 'top4'}))
        self.assertEqual(self.codes(top4), [('W_INFLUENCES_TRUNCATED', '/Rig/Body')])
        self.assertIn('1 vertex', thaw(top4.source['losses'])[0]['message'])
        self.assertIsNone(self.influences(top4, 1))
        self.assertEqual([j for j, _ in self.influences(top4)[0]], [0, 1, 2, 3])
        self.assertAlmostEqual(self.influences(top4)[0][0][1], 0.3 / 0.9, places=6)
        strict = m.inspect_asset(data, 'usda', options={'influences': 'top4', 'losses': 'strict'})
        self.assertEqual([d.code for d in strict.report.diagnostics], ['E_INFLUENCES_TRUNCATED'])

    def test_weight_sums_unweighted_vertices_and_skinning_method_are_declared(self):
        data = rig(['root', 'root/a'], '[0, 1, 1, 0, 0, 0]', '[0.5, 0.25, 1, 0, 0, 0]', 2,
                   mesh_extra='        uniform token primvars:skel:skinningMethod = "dualQuaternion"\n')
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(snapshot), [('W_WEIGHTS_NORMALIZED', '/Rig/Body'), ('W_UNWEIGHTED_VERTICES', '/Rig/Body'),
                                                ('W_SKINNING_METHOD', '/Rig/Body')])
        influences = self.influences(snapshot)
        self.assertEqual([j for j, _ in influences[0][:2]], [0, 1])
        self.assertAlmostEqual(influences[0][0][1], 2 / 3, places=6)
        self.assertEqual(influences[2][0], (0, 1.0))
        strict = m.inspect_asset(data, 'usda', options={'losses': 'strict'})
        self.assertEqual([d.code for d in strict.report.diagnostics],
                         ['E_WEIGHTS_NORMALIZED', 'E_UNWEIGHTED_VERTICES', 'E_SKINNING_METHOD'])

    def test_constant_influences_and_joint_subsets_map_to_skeleton_joints(self):
        constant = rig(['root', 'root/a', 'root/b'], '[2]', '[1]', 1, interpolation='constant')
        self.assertEqual([row[0] for row in self.influences(good(m.inspect_asset(constant, 'usda')))], [(2, 1.0)] * 3)
        subset = rig(['root', 'root/a', 'root/b'], '[0, 0, 0]', '[1, 1, 1]', 1,
                     mesh_extra='        uniform token[] skel:joints = ["root/b"]\n')
        self.assertEqual([row[0] for row in self.influences(good(m.inspect_asset(subset, 'usda')))], [(2, 1.0)] * 3)

    def test_skinned_meshes_refuse_shear(self):
        data = rig(['root'], '[0, 0, 0]', '[1, 1, 1]', 1).replace(
            b'double3 xformOp:translate = (5, 0, 0)', SHEAR.encode()).replace(b'"xformOp:translate"', b'"xformOp:transform"')
        result = m.inspect_asset(data, 'usda')
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], [('E_SHEAR_UNSUPPORTED', '/Rig/Body')])


ANIMATED_ARM = """        rel skel:animationSource = </Rig/Skel/Anim>
        def SkelAnimation "Anim"
        {
            uniform token[] joints = ["root/arm"]
            float3[] translations.timeSamples = {0: [(0, 100, 0)], 12: [(0, 150, 0)], 24: [(50, 100, 0)]}
            quatf[] rotations.timeSamples = {0: [(1, 0, 0, 0)], 24: [(0.7071068, 0, 0, 0.7071068)]}
            half3[] scales = [(1, 1, 1)]
            uniform token[] blendShapes = ["lift"]
            float[] blendShapeWeights.timeSamples = {0: [0], 24: [1]}
        }
"""

LIFT = """        uniform token[] skel:blendShapes = ["lift"]
        rel skel:blendShapeTargets = </Rig/Body/Lift>
        def BlendShape "Lift"
        {
            uniform int[] pointIndices = [1]
            uniform vector3f[] offsets = [(0, 50, 0)]
        }
"""


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdAnimation(unittest.TestCase):
    codes = UsdMeshesAndTransforms.codes

    def test_animated_skeleton_and_blend_weights_match_usd_bake_skinning(self):
        header = 'upAxis = "Z"\n    metersPerUnit = 0.01\n    timeCodesPerSecond = 24'
        data = rig(['root', 'root/arm'], '[0, 0, 0, 1, 1, 0]', '[1, 0, 0.5, 0.5, 1, 0]', 2, header=header,
                   binds=[(0, 0, 0), (0, 100, 0)], rests=[(0, 0, 0), (0, 100, 0)], anim=ANIMATED_ARM, mesh_extra=LIFT,
                   points='[(0, 0, 0), (100, 100, 0), (0, 200, 0)]')
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(snapshot), [('I_UNITS_CONVERTED', '/'), ('I_AXES_CONVERTED', '/')])
        self.assertEqual(len(snapshot.document['animations']), 1)
        # BakeSkinning writes points only at authored time codes, so compare there.
        for code in (0, 12, 24):
            with self.subTest(code=code):
                expected = baked_world_points(data, '/Rig/Body', code)
                actual = world_points(snapshot, '/Rig/Body', timestamp=code / 24, animation_id=0)
                diagonal = math.dist([min(c) for c in zip(*expected)], [max(c) for c in zip(*expected)])
                for a, e in zip(actual, expected):
                    self.assertLess(math.dist(a, e), 1e-5 * diagonal, (code, actual, expected))

    def test_animated_transforms_are_clipped_shifted_and_converted(self):
        header = ('upAxis = "Z"\n    metersPerUnit = 0.01\n    timeCodesPerSecond = 24\n'
                  '    startTimeCode = -24\n    endTimeCode = 24')
        data = layer('def Xform "Mover"\n{\n    double3 xformOp:translate.timeSamples = {-24: (0, 0, 0), 24: (0, 0, 100),'
                     ' 48: (0, 0, 900)}\n    uniform token[] xformOpOrder = ["xformOp:translate"]\n}\n', header)
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(snapshot), [('I_UNITS_CONVERTED', '/'), ('I_AXES_CONVERTED', '/'), ('W_TIME_SHIFTED', '/')])
        sampler = snapshot.document['animations'][0]['samplers'][0]
        self.assertEqual(m.decode_accessor(snapshot, sampler['input']).value, ((0.0,), (2.0,)))
        sample = m.sample_animation(snapshot, 0, 1.0).value
        self.assertAlmostEqual(sample[0]['translation'][1], 0.5, places=6)

    def test_shear_in_any_sample_is_refused(self):
        data = layer('def Xform "Root"\n{\n    matrix4d xformOp:transform.timeSamples = {0: ((1, 0, 0, 0), (0, 1, 0, 0),'
                     ' (0, 0, 1, 0), (0, 0, 0, 1)), 1: ((1, 0, 0, 0), (0.5, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))}\n'
                     '    uniform token[] xformOpOrder = ["xformOp:transform"]\n}\n', 'metersPerUnit = 1')
        result = m.inspect_asset(data, 'usda')
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], [('E_SHEAR_UNSUPPORTED', '/Root')])

    def test_inbetweens_are_dropped_and_declared(self):
        shape = ('    uniform token[] skel:blendShapes = ["smile"]\n    rel skel:blendShapeTargets = </Face/Smile>\n'
                 '    def BlendShape "Smile"\n    {\n        uniform vector3f[] offsets = [(0, 1, 0), (0, 1, 0), (0, 1, 0)]\n'
                 '        uniform vector3f[] inbetweens:half = [(0, 0.25, 0), (0, 0.25, 0), (0, 0.25, 0)] (\n'
                 '            weight = 0.5\n        )\n    }\n')
        face = mesh('Face', '[(0, 0, 0), (1, 0, 0), (0, 1, 0)]', '[3]', '[0, 1, 2]', shape).replace(
            'def Mesh "Face"', 'def Mesh "Face" (prepend apiSchemas = ["SkelBindingAPI"])')
        data = layer(face, 'metersPerUnit = 1')
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertEqual(self.codes(snapshot), [('W_INBETWEENS_DROPPED', '/Face')])
        self.assertEqual(positions(snapshot, morph_weights={0: [1.0]}), [[0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 2.0, 0.0]])
        strict = m.inspect_asset(data, 'usda', options={'losses': 'strict'})
        self.assertEqual([d.code for d in strict.report.diagnostics], ['E_INBETWEEN_UNSUPPORTED'])


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdIsolated(unittest.TestCase):
    def test_isolated_reader_matches_in_process_with_a_local_resolver(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'parts').mkdir()
            for uri, payload in UsdDependencies.files.items():
                (root / uri).write_bytes(payload)
            local = good(m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=m.LocalResolver(root)))
            isolated = good(m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=m.LocalResolver(root), isolate=True))
        self.assertEqual(m.canonical_json(isolated.to_dict()), m.canonical_json(local.to_dict()))
        self.assertEqual(len(isolated.source['dependencies']), 2)


BLEND_ONLY_RIG = """def SkelRoot "Rig"
{
    def Skeleton "Skel" (prepend apiSchemas = ["SkelBindingAPI"])
    {
        rel skel:animationSource = </Rig/Skel/Anim>
        def SkelAnimation "Anim"
        {
            uniform token[] blendShapes = ["lift", "flat"]
            float[] blendShapeWeights.timeSamples = {0: [0, 1], 24: [1, 1]}
        }
    }
    def Mesh "Face" (prepend apiSchemas = ["SkelBindingAPI"])
    {
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        uniform token subdivisionScheme = "none"
        double3 xformOp:translate = (0, 0, 2)
        uniform token[] xformOpOrder = ["xformOp:translate"]
        rel skel:skeleton = </Rig/Skel>
        uniform token[] skel:blendShapes = ["lift", "flat"]
        rel skel:blendShapeTargets = [</Rig/Face/Lift>, </Rig/Face/Flat>]
        def BlendShape "Lift"
        {
            uniform int[] pointIndices = [2]
            uniform vector3f[] offsets = [(0, 1, 0)]
        }
        def BlendShape "Flat"
        {
            uniform int[] pointIndices = [0, 1]
            uniform vector3f[] normalOffsets = [(0, 0, 1), (0, 0, 1)]
        }
    }
}
"""


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdBlendShapeBindings(unittest.TestCase):
    def test_blend_weights_animate_meshes_bound_without_joints(self):
        data = layer(BLEND_ONLY_RIG, 'metersPerUnit = 1\n    timeCodesPerSecond = 24')
        snapshot = good(m.inspect_asset(data, 'usda'))
        self.assertNotIn('skins', snapshot.document)
        self.assertEqual(snapshot.source['target_keys'], (('lift', 'flat'),))
        self.assertAlmostEqual(positions(snapshot, timestamp=0.5, animation_id=0)[2][1], 1.5, places=6)
        for code in (0, 24):  # BakeSkinning writes points only at authored time codes
            with self.subTest(code=code):
                expected = baked_world_points(data, '/Rig/Face', code)
                actual = world_points(snapshot, '/Rig/Face', timestamp=code / 24, animation_id=0)
                for a, e in zip(actual, expected):
                    self.assertLess(math.dist(a, e), 1e-6, (code, actual, expected))
