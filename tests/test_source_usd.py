# SPDX-License-Identifier: MIT
"""The USD adapter with the real usd-core reader; skipped when pxr is not installed."""
import importlib.util
import struct
import unittest

import msf_tools as m
from msf_tools.common import thaw

HAVE_USD = importlib.util.find_spec('pxr') is not None
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


if __name__ == '__main__':
    unittest.main()
