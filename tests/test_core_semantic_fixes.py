# SPDX-License-Identifier: MIT
"""Independent regression oracles for IVO-SH2-02-01 through 05."""
import base64
import copy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import struct
import unittest

import msf_tools as m

ROOT = Path(__file__).resolve().parents[1]
assert Path(m.__file__).resolve().parent == ROOT / 'msf_tools'
SIGNAL = {'id': 'delta', 'value_type': 'scalar', 'units': '1',
          'domain': {'min': -2, 'max': 2}, 'calibration': 'independent literal'}


class AssetBytes:
    """Author binary rows directly; each document is a detached JSON value."""
    def __init__(self):
        self.data = bytearray()
        self.views = []
        self.accessors = []

    def rows(self, rows, shape, component=5126, normalized=False, bounds=False):
        while len(self.data) % 4:
            self.data.append(0)
        start = len(self.data)
        code = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}[component]
        for row in rows:
            self.data.extend(struct.pack('<' + code * len(row), *row))
        self.views.append({'buffer': 0, 'byteOffset': start, 'byteLength': len(self.data) - start})
        a = {'bufferView': len(self.views) - 1, 'componentType': component,
             'type': shape, 'count': len(rows)}
        if normalized:
            a['normalized'] = True
        if bounds:
            a['min'] = [min(row[k] for row in rows) for k in range(len(rows[0]))]
            a['max'] = [max(row[k] for row in rows) for k in range(len(rows[0]))]
        self.accessors.append(a)
        return len(self.accessors) - 1

    def document(self, **fields):
        result = {'asset': {'version': '2.0'}, 'accessors': self.accessors, **fields}
        if self.data:
            result.update(buffers=[{'byteLength': len(self.data),
                                   'uri': 'data:application/octet-stream;base64,' + base64.b64encode(self.data).decode()}],
                          bufferViews=self.views)
        return copy.deepcopy(result)


def morph_asset(descriptors=False, skin=False):
    b = AssetBytes()
    p = b.rows([(2, 0, 0)], 'VEC3', bounds=True)
    delta = b.rows([(0, 4, 0)], 'VEC3', bounds=True)
    times = b.rows([(0,), (2,)], 'SCALAR', bounds=True)
    output = b.rows([(0,), (1,)], 'SCALAR')
    attrs = {'POSITION': p}
    if skin:
        attrs['JOINTS_0'] = b.rows([(0, 0, 0, 0)], 'VEC4', 5123)
        attrs['WEIGHTS_0'] = b.rows([(1, 0, 0, 0)], 'VEC4')
    d = b.document(meshes=[{'primitives': [{'mode': 0, 'attributes': attrs,
                                           'targets': [{'POSITION': delta}]}]}],
                   nodes=[{'mesh': 0}],
                   animations=[{'samplers': [{'input': times, 'output': output}],
                                'channels': [{'sampler': 0, 'target': {'node': 0, 'path': 'weights'}}]}])
    if skin:
        d['nodes'] = [{'mesh': 0, 'skin': 0}, {}, {'children': [0, 1]}]
        d['skins'] = [{'joints': [1], 'skeleton': 2}]
        d['scenes'] = [{'nodes': [2]}]
    if descriptors:
        for aid in (p, delta):
            d['accessors'][aid].pop('bufferView')
            d['accessors'][aid].update(min=[-4, -3, -2], max=[6, 7, 8])
        d['accessors'].append({'componentType': 5121, 'normalized': True,
                               'type': 'SCALAR', 'count': 1, 'min': [7], 'max': [200]})
        attrs = d['meshes'][0]['primitives'][0]['attributes']
        attrs['_OPAQUE'] = len(d['accessors']) - 1
        d['extensionsUsed'] = ['EXT_unknown']
        d['extensions'] = {'EXT_unknown': {'opaque': [None, True, 1.25, {'count': 1.5}]}}
    return d


def encode(d, tokens=None):
    text = json.dumps(d, allow_nan=False, separators=(',', ':'))
    for marker, value in (tokens or {}).items():
        quoted = json.dumps(marker)
        assert text.count(quoted) == 1
        text = text.replace(quoted, value)
    return text.encode()


class ReviewFixes(unittest.TestCase):
    def good(self, result):
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def inspect(self, d, tokens=None):
        return m.inspect_asset(encode(d, tokens), 'gltf')

    def reject(self, d, code, ref=None, tokens=None):
        result = self.inspect(d, tokens)
        self.assertFalse(result.ok, 'Invalid known structure was admitted')
        self.assertIsNone(result.value)
        self.assertIn(code, [x.code for x in result.report.diagnostics], result.report.to_dict())
        self.assertNotIn('E_INPUT', [x.code for x in result.report.diagnostics])
        if ref is not None:
            self.assertIn((code, ref), [(x.code, x.ref) for x in result.report.diagnostics])

    def paths(self, d, expected, tokens=None):
        raw = encode(d, tokens)
        snapshot = self.good(m.inspect_asset(raw, 'gltf'))
        self.assertEqual(snapshot.original_bytes, raw)
        self.assertEqual(snapshot.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.good(m.sample_animation(snapshot, 0, 1)), {0: {'weights': (.5,)}})
        binding = self.good(m.morph_binding(snapshot, SIGNAL, 0, 0))
        sidecar = self.good(m.annotate_asset(snapshot, {'bindings': [binding]}))
        bound = self.good(m.inspect_asset(raw, 'gltf', sidecar=sidecar))
        self.assertEqual(bound.to_dict()['asset_sha256'], hashlib.sha256(raw).hexdigest())
        positions = self.good(m.evaluate_geometry(bound, animation_id=0, timestamp=1)).to_dict()['instances'][0]['primitives'][0]['positions']
        self.assertEqual(positions, [expected])
        return bound

    def test_descriptor_base_morph_and_opaque_bounds_full_paths(self):
        d = morph_asset(descriptors=True)
        snapshot = self.paths(d, [0, 0, 0])
        self.assertEqual(snapshot.to_dict()['document'], d)
        self.assertEqual(snapshot.to_dict()['document']['extensions'], d['extensions'])
        self.assertEqual(self.good(m.decode_accessor(snapshot, 0)), ((0., 0., 0.),))

    def test_descriptor_normal_and_integer_bounds_are_not_zero_extrema(self):
        for shape, ct, bounds in [('VEC3', 5126, ([-2, -1, 0], [2, 1, 3])),
                                  ('SCALAR', 5120, ([-128], [127])),
                                  ('SCALAR', 5123, ([10], [65535]))]:
            with self.subTest(shape=shape, component=ct):
                d = morph_asset()
                a = {'componentType': ct, 'type': shape, 'count': 1,
                     'min': bounds[0], 'max': bounds[1]}
                d['accessors'].append(a)
                name = 'NORMAL' if shape == 'VEC3' else '_RAW'
                d['meshes'][0]['primitives'][0]['attributes'][name] = len(d['accessors']) - 1
                self.paths(d, [2, 2, 0])

    def test_descriptor_exception_preserves_structural_and_range_rejections(self):
        d = morph_asset()
        a = d['accessors'][0]
        a.pop('bufferView')
        for field, value, code in [('max', [3.5e38, 0, 0], 'E_ACCESSOR_DOMAIN'),
                                    ('min', [3, 0, 0], 'E_ACCESSOR_DOMAIN'),
                                    ('min', [0, 0], 'E_TYPE'),
                                    ('max', [True, 0, 0], 'E_TYPE'),
                                    ('byteOffset', 4, 'E_ACCESSOR_BOUNDS')]:
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(d)
                bad['accessors'][0][field] = value
                self.reject(bad, code)
        d['accessors'].append({'componentType': 5121, 'type': 'SCALAR', 'count': 1,
                               'min': [0], 'max': [256]})
        self.reject(d, 'E_ACCESSOR_DOMAIN')

    def test_available_and_sparse_extrema_remain_exact_with_no_base_view(self):
        b = AssetBytes()
        indices = b.rows([(0,)], 'SCALAR', 5121)
        values = b.rows([(5,)], 'SCALAR', 5123)
        d = b.document()
        d['accessors'].append({'componentType': 5123, 'type': 'SCALAR', 'count': 2,
                               'min': [0], 'max': [5],
                               'sparse': {'count': 1,
                                          'indices': {'bufferView': indices, 'componentType': 5121},
                                          'values': {'bufferView': values}}})
        s = self.good(self.inspect(d))
        self.assertEqual(self.good(m.decode_accessor(s, 2)), ((5,), (0,)))
        d['accessors'][2]['max'] = [6]
        self.reject(d, 'E_ACCESSOR_DOMAIN', '/accessors/2')
        d = morph_asset()
        d['accessors'][0]['max'] = [3, 0, 0]
        self.reject(d, 'E_ACCESSOR_DOMAIN', '/accessors/0')

    def test_lexical_fraction_raw_bounds_reject_all_integer_encodings(self):
        for ct, value in [(5120, -127), (5121, 255), (5122, -32767),
                          (5123, 65535), (5125, 4294967295)]:
            for normalized in ([False] if ct == 5125 else [False, True]):
                for field in ('min', 'max'):
                    with self.subTest(component=ct, normalized=normalized, field=field):
                        b = AssetBytes()
                        b.rows([(value,)], 'SCALAR', ct, normalized, bounds=True)
                        d = b.document()
                        token = str(value) + '.00000000000000000000000001'
                        self.assertEqual(float(token), value)
                        self.assertNotEqual(Decimal(token), value)
                        self.good(self.inspect(d))
                        d['accessors'][0][field] = ['LEXICAL_BOUND']
                        self.reject(d, 'E_ACCESSOR_DOMAIN', tokens={'LEXICAL_BOUND': token})
        b = AssetBytes()
        b.rows([(0,)], 'SCALAR', 5121, bounds=True)
        d = b.document()
        d['accessors'][0]['max'] = ['UNDERFLOW_BOUND']
        self.reject(d, 'E_ACCESSOR_DOMAIN', tokens={'UNDERFLOW_BOUND': '1e-1000'})

    def test_integral_bound_decimal_exponents_raw_identity_and_float_rounding(self):
        for normalized in (False, True):
            d = morph_asset()
            d['accessors'].append({'componentType': 5121, 'type': 'SCALAR', 'count': 1,
                                   'normalized': normalized, 'min': ['MIN_BOUND'], 'max': ['MAX_BOUND']})
            for aid in (0, 1):
                d['accessors'][aid].pop('bufferView')
                d['accessors'][aid].update(min=[-1, -2, -3], max=[4, 5, 6])
            tokens = {'MIN_BOUND': '7.000', 'MAX_BOUND': '2.00e2'}
            snapshot = self.paths(d, [0, 0, 0], tokens)
            view = snapshot.to_dict()['document']
            self.assertEqual(view['accessors'][-1]['min'], [7])
            self.assertEqual(view['accessors'][-1]['max'], [200])
            tampered = copy.deepcopy(view)
            tampered['accessors'][-1]['max'] = [199]
            self.assertFalse(m.evaluate_geometry(replace(snapshot, document=tampered)).ok)
        b = AssetBytes()
        b.rows([(1.2,)], 'SCALAR', bounds=True)
        d = b.document()
        d['accessors'][0].update(min=['FLOAT_MIN'], max=['FLOAT_MAX'])
        s = self.good(self.inspect(d, {'FLOAT_MIN': '1.20000000000000000000001', 'FLOAT_MAX': '1.20e0'}))
        expected = struct.unpack('<f', struct.pack('<f', 1.2))[0]
        self.assertEqual(self.good(m.decode_accessor(s, 0)), ((expected,),))

    def test_top_array_malformed_shapes_keep_precise_refs(self):
        for name in ('scenes', 'meshes', 'animations', 'materials'):
            for value in (None, True, False, 42, 1.25, 'array', {}, [None]):
                with self.subTest(name=name, value=value):
                    d = {'asset': {'version': '2.0'}, name: value}
                    self.reject(d, 'E_TYPE', '/' + name)
        d = morph_asset()
        d.update(materials=[{'normalTexture': {'index': 0}}], textures=[{}], scenes=[{'nodes': [0]}])
        self.paths(d, [2, 2, 0])

    def test_accessor_shape_validation_precedes_hash_membership(self):
        for semantic, code in [('_CUSTOM', 'E_ACCESSOR_TYPE'), ('POSITION', 'E_GEOMETRY_TYPE')]:
            for shape in ([], {}, None, True, 42, ['VEC3']):
                with self.subTest(semantic=semantic, shape=shape):
                    d = morph_asset()
                    if semantic == '_CUSTOM':
                        d['meshes'][0]['primitives'][0]['attributes'][semantic] = 0
                        del d['meshes'][0]['primitives'][0]['attributes']['POSITION']
                        del d['meshes'][0]['primitives'][0]['targets']
                        del d['animations']
                    d['accessors'][0]['type'] = shape
                    self.reject(d, code)

    def test_each_skinned_primitive_requires_influences_even_without_bytes(self):
        for unavailable in (False, True):
            for primitive in (0, 1):
                with self.subTest(unavailable=unavailable, primitive=primitive):
                    d = morph_asset(skin=True)
                    d['meshes'][0]['primitives'].append(copy.deepcopy(d['meshes'][0]['primitives'][0]))
                    if unavailable:
                        d['buffers'][0]['uri'] = 'unavailable.bin'
                    self.good(self.inspect(d))
                    d['meshes'][0]['primitives'][primitive]['attributes'] = {'POSITION': 0}
                    self.reject(d, 'E_SKIN', f'/meshes/0/primitives/{primitive}')

    def test_skin_requirement_confounds_and_full_paired_paths(self):
        self.paths(morph_asset(), [2, 2, 0])
        self.paths(morph_asset(skin=True), [2, 2, 0])
        d = morph_asset(skin=True)
        for missing in ('JOINTS_0', 'WEIGHTS_0'):
            bad = copy.deepcopy(d)
            del bad['meshes'][0]['primitives'][0]['attributes'][missing]
            self.reject(bad, 'E_ATTRIBUTE_SEMANTIC')
        d['meshes'][0]['primitives'][0]['attributes'] = {'POSITION': 0}
        del d['nodes'][0]['skin']
        self.paths(d, [2, 2, 0])

    def test_extension_inventory_cannot_admit_missing_or_nonstring_path(self):
        for extension in (False, True):
            for value in ('MISSING', None, False, 42, 1.25, [], {}):
                with self.subTest(extension=extension, path=value):
                    d = morph_asset()
                    target = {'extensions': {'EXT_unknown': {'opaque': [None, {'x': True}]}}} if extension else {}
                    if extension:
                        d['extensionsUsed'] = ['EXT_unknown']
                    if value != 'MISSING':
                        target['path'] = value
                    d['animations'][0]['channels'][0]['target'] = target
                    self.reject(d, 'E_TYPE', '/animations/0/channels/0/target/path')

    def test_unknown_string_opaque_and_ignored_core_do_not_mask_known_data(self):
        for path in ('vendor_value', ''):
            with self.subTest(path=path):
                d = morph_asset()
                opaque = {'EXT_unknown': {'array': [None, False, 1.5, {'node': 'opaque'}]}}
                d['extensionsUsed'] = ['EXT_unknown']
                d['animations'][0]['channels'] += [
                    {'sampler': 0, 'target': {'path': path, 'extensions': opaque}},
                    {'sampler': 0, 'target': {'path': 'weights'}}]
                snapshot = self.paths(d, [2, 2, 0])
                self.assertEqual(snapshot.to_dict()['document']['animations'][0]['channels'][1]['target']['extensions'], opaque)
                # Change only known output layout; inventory and ignored channels cannot hide it.
                bad = copy.deepcopy(d)
                bad['animations'][0]['samplers'][0]['output'] = 0
                self.reject(bad, 'E_ANIMATION_TYPE')
        d = morph_asset()
        del d['animations'][0]['channels'][0]['target']['node']
        s = self.good(self.inspect(d))
        self.assertEqual(self.good(m.sample_animation(s, 0, 1)), {})
        self.assertEqual(self.good(m.evaluate_geometry(s, animation_id=0, timestamp=1)).to_dict()['instances'][0]['primitives'][0]['positions'], [[2, 0, 0]])


if __name__ == '__main__':
    unittest.main()
