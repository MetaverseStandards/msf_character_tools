# SPDX-License-Identifier: MIT
"""Independent S-H1 regression oracles; no production serializer creates inputs."""
import base64
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import tomllib
import unittest

import msf_tools as m
from msf_tools.common import number
from msf_tools.report import Fault

ROOT = Path(__file__).resolve().parents[1]
assert Path(m.__file__).resolve().parent == ROOT / "msf_tools", m.__file__


def document():
    return tomllib.loads((ROOT / 'examples/authoring/pack.toml').read_text())


def raw_asset():
    # One point x=2 and one relative target x=3, independently encoded.
    payload = struct.pack('<6f', 2, 0, 0, 3, 0, 0)
    doc = {'asset': {'version': '2.0'},
           'buffers': [{'byteLength': 24, 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(payload).decode()}],
           'bufferViews': [{'buffer': 0, 'byteLength': 12}, {'buffer': 0, 'byteOffset': 12, 'byteLength': 12}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 1, 'min': [2, 0, 0], 'max': [2, 0, 0]},
                         {'bufferView': 1, 'componentType': 5126, 'type': 'VEC3', 'count': 1, 'min': [3, 0, 0], 'max': [3, 0, 0]}],
           'meshes': [{'primitives': [{'mode': 0, 'attributes': {'POSITION': 0}, 'targets': [{'POSITION': 1}]}]}],
           'nodes': [{'mesh': 0, 'weights': [.5]}]}
    return json.dumps(doc, separators=(',', ':')).encode()


class IntegrityTests(unittest.TestCase):
    def good(self, result):
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def rejected(self, result):
        self.assertFalse(result.ok, 'Inconsistent record reached a public boundary')
        self.assertIsNone(result.value)
        self.assertEqual([d.code for d in result.report.diagnostics], ['E_RECORD_INTEGRITY'])

    def refuses_export(self, fn):
        with self.assertRaises(Fault) as caught:
            fn()
        self.assertEqual(caught.exception.diagnostic.code, 'E_RECORD_INTEGRITY')

    def setUp(self):
        self.validated = self.good(m.validate_authoring(document()))
        self.pack = self.good(m.compile_pack(self.validated))
        self.source = self.good(m.profile_snapshot(self.pack, 'source'))
        self.target = self.good(m.profile_snapshot(self.pack, 'target'))
        self.compiled = self.good(m.compile_mapping(self.pack, self.source, self.target, 'wink'))
        self.asset = self.good(m.inspect_asset(raw_asset(), 'gltf'))
        self.signal = document()['signals'][1]
        self.binding = self.good(m.morph_binding(self.asset, self.signal, 0, 0))
        self.sidecar = self.good(m.annotate_asset(self.asset, {'bindings': [self.binding]}))
        self.bound = self.good(m.inspect_asset(raw_asset(), 'gltf', sidecar=self.sidecar))
        self.frames = [{'timestamp': 0, 'values': {'input.wink': -.5}, 'validity': {'input.wink': True}}]

    def test_authoring_replace_and_token_copy_cannot_compile_or_export(self):
        for bad in [replace(self.validated), replace(self.validated, document={'id': 'broken'}),
                    type(self.validated)(document(), self.validated._token)]:
            with self.subTest(record=type(bad).__name__):
                self.rejected(m.compile_pack(bad))
                self.refuses_export(bad.to_dict)

    def test_pack_replace_stale_hash_and_mutable_constructor_all_boundaries(self):
        bad_records = [replace(self.pack), replace(self.pack, sha256='0' * 64), m.Pack(document(), self.pack.sha256)]
        for bad in bad_records:
            with self.subTest(record=bad.sha256):
                self.rejected(m.profile_snapshot(bad, 'source'))
                self.rejected(m.compile_mapping(bad, self.source, self.target, 'wink'))
                for fn in [bad.to_dict, bad.to_bytes, lambda: bad.signals, lambda: m.survey_csv(bad), lambda: m.coverage(bad)]:
                    self.refuses_export(fn)

    def test_pack_factory_owns_input_and_exports_are_detached(self):
        inp = document()
        validated = self.good(m.validate_authoring(inp))
        inp['signals'][0]['domain']['min'] = 999
        pack = self.good(m.compile_pack(validated))
        out = pack.to_dict(); out['signals'][0]['domain']['min'] = 999
        self.assertEqual(pack.document['signals'][0]['domain']['min'], -1.0)
        expected = (ROOT / 'examples/generated/pack.json').read_bytes()
        self.assertEqual(pack.to_bytes(), expected)
        self.assertEqual(pack.sha256, hashlib.sha256(expected).hexdigest())

    def test_snapshot_replace_mutable_constructor_and_stale_digest_boundaries(self):
        raw = raw_asset()
        bad_records = [replace(self.asset), replace(self.asset, sha256='0'*64),
                       m.AssetSnapshot('gltf', raw, hashlib.sha256(raw).hexdigest(), json.loads(raw))]
        for bad in bad_records:
            with self.subTest(record=bad.sha256):
                self.rejected(m.decode_accessor(bad, 0))
                self.rejected(m.evaluate_geometry(bad))
                self.rejected(m.sample_animation(bad, 0, 0))
                self.rejected(m.export_geometry_golden(bad))
                self.rejected(m.morph_binding(bad, self.signal, 0, 0))
                self.rejected(m.annotate_asset(bad, {'bindings': []}))
                self.rejected(m.compile_mapping(self.pack, self.source, bad, 'wink'))
                self.refuses_export(bad.to_dict)
                self.refuses_export(lambda: bad.resource_hashes)

    def test_mutated_document_with_old_raw_identity_is_rejected(self):
        doc = json.loads(raw_asset()); doc['nodes'][0]['weights'] = [1]
        object.__setattr__(self.asset, 'document', doc)
        self.rejected(m.evaluate_geometry(self.asset))
        self.rejected(m.export_geometry_golden(self.asset))

    def test_raw_whitespace_and_parsed_view_are_distinct_consistent_identities(self):
        raw = raw_asset(); pretty = json.dumps(json.loads(raw), indent=4).encode()
        a = self.good(m.inspect_asset(raw, 'gltf')); b = self.good(m.inspect_asset(pretty, 'gltf'))
        self.assertEqual(a.to_dict()['document'], json.loads(raw))
        self.assertEqual(b.to_dict()['document'], json.loads(pretty))
        self.assertEqual(a.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(b.sha256, hashlib.sha256(pretty).hexdigest())
        self.assertNotEqual(a.sha256, b.sha256)
        for snapshot in [a, b]:
            value = self.good(m.evaluate_geometry(snapshot)).to_dict()
            self.assertEqual(value['instances'][0]['primitives'][0]['positions'], [[3.5, 0.0, 0.0]])
        # Updated digest is still insufficient when raw and view disagree.
        changed = json.loads(raw); changed['nodes'][0]['weights'] = [1]
        changed_raw = json.dumps(changed).encode()
        object.__setattr__(a, 'original_bytes', changed_raw)
        object.__setattr__(a, 'sha256', hashlib.sha256(changed_raw).hexdigest())
        self.rejected(m.evaluate_geometry(a))

    def test_binary_resource_mutation_with_stale_or_updated_hash_is_rejected(self):
        for updated in [False, True]:
            with self.subTest(updated=updated):
                snapshot = self.good(m.inspect_asset(raw_asset(), 'gltf'))
                r = snapshot.resources[0]
                new_bytes = struct.pack('<6f', 100, 0, 0, 3, 0, 0)
                object.__setattr__(r, 'data', new_bytes)
                if updated: object.__setattr__(r, 'sha256', hashlib.sha256(new_bytes).hexdigest())
                self.rejected(m.decode_accessor(snapshot, 0))
                self.rejected(m.evaluate_geometry(snapshot))

    def test_chunk_mutation_is_rejected_including_unknown_opaque_chunk(self):
        snapshot = self.good(m.inspect_asset((ROOT/'tests/fixtures/combined.glb').read_bytes(), 'glb'))
        object.__setattr__(snapshot.chunks[-1], 'data', b'changed!')
        self.rejected(m.evaluate_geometry(snapshot))
        self.refuses_export(snapshot.to_dict)

    def test_binding_channel_and_resource_inventory_replacement_is_rejected(self):
        for field, value in [('channels', {}), ('bindings', ()), ('resources', ()), ('chunks', ())]:
            # glTF chunks are already empty; use replace to exercise admission too.
            with self.subTest(field=field):
                bad = replace(self.bound, **{field: value})
                self.rejected(m.compile_mapping(self.pack, self.source, bad, 'wink'))
                self.refuses_export(bad.to_dict)
        object.__setattr__(self.bound, 'channels', {'output.wink': {'calibration': 'forged'}})
        self.rejected(m.compile_mapping(self.pack, self.source, self.bound, 'wink'))

    def test_forged_cyclic_hierarchy_refuses_before_world_traversal(self):
        doc = json.loads(raw_asset()); doc['nodes'][0]['children'] = [0]
        bad = replace(self.asset, document=doc)
        # Binding only indexes nodes, so the old implementation does not hang.
        self.rejected(m.morph_binding(bad, self.signal, 0, 0))
        self.rejected(m.sample_animation(bad, 0, 0))

    def test_profile_channels_raw_document_and_pack_identity_are_checked(self):
        for field, value in [('channels', {}), ('document', {}), ('sha256', '0'*64), ('format', 'gltf')]:
            with self.subTest(field=field):
                bad = replace(self.source, **{field: value})
                self.rejected(m.compile_mapping(self.pack, bad, self.target, 'wink'))
                self.refuses_export(bad.to_dict)
        object.__setattr__(self.source, 'channels', {})
        self.rejected(m.compile_mapping(self.pack, self.source, self.target, 'wink'))

    def test_compiled_instruction_dependency_id_loss_and_source_changes_refuse(self):
        altered = copy.deepcopy(document()['mappings'][0]['rules'][0])
        altered['operator'] = {'id': 'affine', 'scale': 0, 'offset': 1}
        changes = [{}, {'instructions': (altered,)}, {'required_inputs': ()}, {'output_ids': ()},
                   {'mapping_id': 'absent'}, {'losses': (m.Loss('signal', 'unknown', 'forged'),)},
                   {'source_snapshot': replace(self.source)}, {'pack': replace(self.pack)}]
        for change in changes:
            with self.subTest(fields=list(change)):
                bad = replace(self.compiled, **change)
                self.rejected(m.evaluate_mapping(bad, self.frames))
                self.refuses_export(bad.to_dict)
        object.__setattr__(self.compiled, 'instructions', (altered,))
        self.rejected(m.evaluate_mapping(self.compiled, self.frames))

    def test_admitted_dependency_mutation_rejected_through_compiled_mapping(self):
        object.__setattr__(self.pack, 'sha256', '0'*64)
        self.rejected(m.evaluate_mapping(self.compiled, self.frames))
        self.refuses_export(self.compiled.to_dict)

    def test_sidecar_and_result_records_have_owned_exports_and_reject_replace(self):
        self.refuses_export(replace(self.sidecar).to_bytes)
        self.rejected(m.inspect_asset(raw_asset(), 'gltf', sidecar=replace(self.sidecar)))
        values = self.good(m.evaluate_mapping(self.compiled, self.frames))
        self.assertEqual(values.to_dict()['samples'][0]['values'], {'output.wink': -.5})
        geometry = self.good(m.evaluate_geometry(self.asset))
        for record in [values, geometry]:
            self.refuses_export(replace(record).to_dict)
            exported = record.to_dict(); exported.clear()
            self.assertTrue(record.to_dict())
        sampled = self.good(m.sample_animation(self.good(m.inspect_asset((ROOT/'tests/fixtures/combined.gltf').read_bytes(), 'gltf')), 0, .5))
        with self.assertRaises(TypeError): sampled[0] = {}


class NumericMetadataTests(unittest.TestCase):
    def test_json_integer_beyond_python_decimal_digit_limit_has_precise_diagnostic(self):
        raw = b'{"asset":{"version":"2.0"},"extras":{"x":1' + b'0'*5000 + b'}}'
        r = m.inspect_asset(raw, 'gltf')
        self.assertEqual([(d.code,d.ref) for d in r.report.diagnostics], [('E_NONFINITE','/extras/x')])

    def test_nonstring_key_does_not_erase_collected_authoring_numeric_diagnostics(self):
        doc = tomllib.loads((ROOT/'examples/authoring/pack.toml').read_text())
        doc['signals'][0]['neutral'] = 10**400
        doc['signals'][1].update({2:'bad',3:'also bad'})
        r=m.validate_authoring(doc)
        self.assertIn('E_NONFINITE',[d.code for d in r.report.diagnostics])
        self.assertNotIn('E_INPUT',[d.code for d in r.report.diagnostics])

    def test_existing_valid_json_nesting_is_preserved(self):
        doc = document()
        value = 'leaf'
        for _ in range(125):
            value = {'x': value}
        doc['signals'][0]['metadata'] = value
        validated = m.validate_authoring(doc)
        self.assertTrue(validated.ok, validated.report.to_dict())
        pack = m.compile_pack(validated.value)
        self.assertTrue(pack.ok, pack.report.to_dict())
        self.assertEqual(pack.value.to_dict(), doc)

    def test_total_binary64_numeric_predicate(self):
        cases = [(10**400, False), (-(10**400), False), (True, False), (float('nan'), False),
                 (float('inf'), False), (10**300, True), (-1, True), (1.5, True)]
        for value, expected in cases:
            with self.subTest(type=type(value).__name__, expected=expected):
                self.assertIs(number(value), expected)

    def test_giant_integer_preserves_exact_path_and_accumulated_diagnostics(self):
        doc = document(); doc['operator_version'] = '2.0'
        doc['signals'][0]['label'] = ''; doc['signals'][1]['neutral'] = 10**400
        result = m.validate_authoring(doc)
        self.assertFalse(result.ok)
        pairs = [(d.code, d.ref) for d in result.report.diagnostics]
        self.assertIn(('E_ENUM', '/operator_version'), pairs)
        self.assertIn(('E_TYPE', '/signals/0/label'), pairs)
        self.assertIn(('E_NONFINITE', '/signals/1/neutral'), pairs)
        self.assertNotIn('E_INPUT', [d.code for d in result.report.diagnostics])

    def test_giant_numeric_inputs_keep_specific_public_diagnostics(self):
        pack = m.compile_pack(m.validate_authoring(document()).value).value
        c = m.compile_mapping(pack, m.profile_snapshot(pack, 'source').value, m.profile_snapshot(pack, 'target').value, 'wink').value
        r = m.evaluate_mapping(c, [{'timestamp': 0, 'values': {'input.wink': 10**400}, 'validity': {'input.wink': True}}])
        self.assertEqual([(d.code, d.ref) for d in r.report.diagnostics], [('E_TYPE', '/samples/0/input.wink')])
        s = m.inspect_asset(raw_asset(), 'gltf').value
        self.assertEqual([d.code for d in m.evaluate_geometry(s, timestamp=10**400).report.diagnostics], ['E_TIMESTAMP'])
        raw = b'{"asset":{"version":"2.0"},"extras":{"x":' + str(10**400).encode() + b'}}'
        self.assertEqual([(d.code, d.ref) for d in m.inspect_asset(raw, 'gltf').report.diagnostics], [('E_NONFINITE', '/extras/x')])

    def test_schema_runtime_optional_metadata_parity_in_existing_1_0(self):
        # jsonschema is a test tool; the distribution remains dependency-free.
        try:
            import jsonschema
        except ImportError:
            self.skipTest('Optional jsonschema test tool is unavailable for this interpreter')
        validators = [jsonschema.Draft202012Validator(json.loads((ROOT/'schemas'/name).read_bytes()))
                      for name in ['authoring.schema.json', 'pack.schema.json']]
        for category, field, value, expected, code in [
                ('signals', 'coupling', '', False, 'E_TYPE'),
                ('signals', 'coupling', ['x', 'x'], False, 'E_DUPLICATE'),
                ('signals', 'coupling', [''], False, 'E_TYPE'),
                ('signals', 'coupling', ['   '], False, 'E_TYPE'),
                ('signals', 'confidence', '', False, 'E_TYPE'),
                ('signals', 'validity', '', False, 'E_TYPE'),
                ('signals', 'label', '   ', False, 'E_TYPE'),
                ('rules', 'coupling', '', False, 'E_TYPE'),
                ('rules', 'coupling', ['x', 'x'], False, 'E_DUPLICATE'),
                ('rules', 'coupling', ['   '], False, 'E_TYPE'),
                ('signals', 'coupling', [], True, None),
                ('signals', 'coupling', ['x', 'y'], True, None),
                ('signals', 'confidence', 0, True, None),
                ('signals', 'validity', False, True, None),
                ('rules', 'coupling', 'declared', True, None)]:
            with self.subTest(category=category, field=field, value=value):
                doc = document()
                row = doc['signals'][0] if category == 'signals' else doc['mappings'][0]['rules'][0]
                row[field] = value
                result = m.validate_authoring(doc)
                self.assertEqual(result.ok, expected, result.report.to_dict())
                if code: self.assertIn(code, [d.code for d in result.report.diagnostics])
                for validator in validators:
                    self.assertEqual(validator.is_valid(doc), expected)
                self.assertEqual(doc['schema_version'], '1.0')


if __name__ == '__main__':
    unittest.main()
