# SPDX-License-Identifier: MIT
"""The format seam: generated snapshots, source identity and sidecar binding."""
import ast
from dataclasses import replace
from pathlib import Path
import unittest

import msf_tools as m
from msf_tools import snapshot as snapshots
from msf_tools.common import digest, freeze, thaw
from msf_tools.records import _admit
from msf_tools.report import Fault
from support import fake_adapter as fake

ROOT = Path(__file__).resolve().parents[1]
COMBINED = (ROOT / 'tests/fixtures/combined.gltf').read_bytes()


def refusal(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
    except Fault as exc:
        return [(exc.diagnostic.code, exc.diagnostic.ref)]
    return [(d.code, d.ref) for d in result.report.diagnostics if d.severity == 'error']


class GltfInspectionLimits(unittest.TestCase):
    def test_byte_and_component_limits_are_parameters(self):
        inspect = snapshots._inspect_gltf
        self.assertEqual(refusal(inspect, COMBINED, 'gltf', None, None, max_asset_bytes=len(COMBINED)), [])
        self.assertEqual(refusal(inspect, COMBINED, 'gltf', None, None, max_asset_bytes=len(COMBINED) - 1),
                         [('E_RESOURCE_LIMIT', '/')])
        self.assertEqual(refusal(inspect, COMBINED, 'gltf', None, None, component_caps=(17, 4_000_000)),
                         [('E_RESOURCE_LIMIT', '/accessors/0')])
        self.assertEqual(refusal(inspect, COMBINED, 'gltf', None, None, component_caps=(1_000_000, 18)),
                         [('E_RESOURCE_LIMIT', '/accessors/1')])


SIGNAL = {'id': 'smile', 'value_type': 'scalar', 'units': '1', 'domain': {'min': 0, 'max': 1}, 'calibration': 'literal'}


def generated(scene=None, **kwargs):
    data = fake.source(scene or fake.scene())
    kwargs.setdefault('resolver', fake.resolver)
    return data, snapshots._inspect_source(fake.FakeAdapter(), data, 'usda', **kwargs)


def good(result):
    assert result.ok, result.report.to_dict()
    return result.value


class GeneratedSnapshots(unittest.TestCase):
    def setUp(self):
        self.data, result = generated()
        self.result = result
        self.snapshot = good(result)
        self.source_sha = digest(self.data)

    def test_admission_records_the_source(self):
        s = self.snapshot
        self.assertEqual(s.format, 'glb')
        self.assertEqual(thaw(s.source), {
            'format': 'usda', 'sha256': self.source_sha, 'byte_length': len(self.data),
            'adapter': 'msf-fake', 'adapter_version': '1', 'reader': 'fake-reader 1',
            'options_sha256': digest(m.canonical_json({})), 'node_order': 'path-sorted-v2',
            'node_paths': ['/Root', '/Root/Face'], 'target_keys': [['smile', 'blink']],
            'dependencies': [{'uri': 'layers/sub.usda', 'sha256': digest(fake.resolver('layers/sub.usda')),
                              'byte_length': len(fake.resolver('layers/sub.usda'))}],
            'losses': [{'code': 'W_SKIPPED', 'severity': 'warning', 'ref': '/Root', 'message': 'Skipped 1 camera.',
                        'remediation': 'Review the declared loss.'}]})
        self.assertEqual([(d.code, d.severity) for d in self.result.report.diagnostics], [('W_SKIPPED', 'warning')])

    def test_every_hash_surface_uses_the_source_hash(self):
        s = self.snapshot
        exported = s.to_dict()
        self.assertEqual(exported['asset_sha256'], self.source_sha)
        self.assertEqual(exported['generated_sha256'], digest(s.original_bytes))
        self.assertEqual(exported['source'], thaw(s.source))
        self.assertEqual(s.resource_hashes, {'layers/sub.usda': digest(fake.resolver('layers/sub.usda'))})
        binding = good(m.morph_binding(s, SIGNAL, 1, 0))
        self.assertEqual(binding['ref']['asset_sha256'], self.source_sha)
        sidecar = good(m.annotate_asset(s, {'bindings': [thaw(binding)]}))
        self.assertEqual(sidecar.to_dict()['asset_sha256'], self.source_sha)
        self.assertEqual(sidecar.to_dict()['resource_hashes'], s.resource_hashes)
        _, bound = generated(sidecar=sidecar)
        bound = good(bound)
        bound._check_integrity()
        golden = good(m.export_geometry_golden(s))
        self.assertEqual(golden['asset_sha256'], self.source_sha)
        self.assertEqual(thaw(golden['source']), {'format': 'usda', 'adapter': 'msf-fake', 'adapter_version': '1',
                                                  'reader': 'fake-reader 1', 'options_sha256': s.source['options_sha256']})
        authoring = {'schema_version': '1.0', 'data_version': '0.1.0', 'operator_version': '1.0', 'id': 'seam', 'license': 'MIT',
                     'signals': [dict(SIGNAL, label='Smile', disposition='mapped', evidence=['e'], evidence_status='verified_current'),
                                 dict(SIGNAL, id='out', label='Out', disposition='mapped', evidence=['e'], evidence_status='verified_current')],
                     'profiles': [{'id': 'target', 'label': 'Target', 'signal_ids': ['out']}],
                     'mappings': [{'id': 'seam', 'rules': [{'id': 'r', 'inputs': ['smile'], 'outputs': ['out'], 'operator': {'id': 'identity'},
                                                            'disposition': 'mapped', 'mapping_quality': 'exact', 'assumptions': [],
                                                            'evidence': ['e'], 'evidence_status': 'verified_current', 'loss_annotations': []}]}],
                     'evidence': [{'id': 'e', 'claim': 'Seam test.', 'status': 'verified_current', 'license': 'MIT', 'authorship': 'MSF Tools contributors'}]}
        pack = good(m.compile_pack(good(m.validate_authoring(authoring))))
        compiled = good(m.compile_mapping(pack, bound, good(m.profile_snapshot(pack, 'target')), 'seam')).to_dict()
        self.assertEqual(compiled['source_sha256'], self.source_sha)
        self.assertEqual(compiled['source_adapter'], thaw(golden['source']))
        self.assertNotIn('target_adapter', compiled)

    def test_tampered_source_record_is_refused(self):
        bad_values = {'format': 'obj', 'sha256': 'x' * 64, 'byte_length': -1, 'adapter': '', 'adapter_version': 2,
                      'reader': None, 'options_sha256': 'ab', 'node_order': 'declared',
                      'node_paths': ['/Root', '/Root'], 'target_keys': [['smile']],
                      'dependencies': [{'uri': 'b', 'sha256': '0' * 64, 'byte_length': 1}, {'uri': 'a', 'sha256': '0' * 64, 'byte_length': 1}],
                      'losses': [{'code': 'W_SKIPPED', 'severity': 'error', 'ref': '/', 'message': 'm', 'remediation': 'r'}]}
        for key, value in bad_values.items():
            with self.subTest(key=key), self.assertRaises(Fault) as caught:
                _admit(replace(self.snapshot, source=freeze(dict(thaw(self.snapshot.source), **{key: value}))))
            self.assertEqual(caught.exception.diagnostic.code, 'E_RECORD_INTEGRITY')
        for changed in ({**thaw(self.snapshot.source), 'extra': 1},
                        {k: v for k, v in thaw(self.snapshot.source).items() if k != 'losses'},
                        dict(thaw(self.snapshot.source), adapter='other')):
            with self.subTest(changed=sorted(changed)), self.assertRaises(Fault):
                _admit(replace(self.snapshot, source=freeze(changed)))
        object.__setattr__(self.snapshot, 'source', freeze(dict(thaw(self.snapshot.source), byte_length=1)))
        with self.assertRaises(Fault):
            self.snapshot._check_integrity()

    def test_gltf_snapshots_have_no_source_fields(self):
        exported = good(m.inspect_asset(COMBINED, 'gltf')).to_dict()
        self.assertEqual(exported['asset_sha256'], digest(COMBINED))
        self.assertNotIn('source', exported)
        self.assertNotIn('generated_sha256', exported)

    def test_adapter_parse_errors_are_truncated_diagnostics(self):
        _, result = generated(fake.scene(fail='x' * 600))
        self.assertIsNone(result.value)
        self.assertEqual([(d.code, d.ref, len(d.message)) for d in result.report.diagnostics], [('E_SOURCE_PARSE', '/', 512)])


class SnapshotHashGuard(unittest.TestCase):
    """Snapshot `.sha256` is the generated GLB digest; persisted hashes must use `_identity`."""
    # to_dict also reports the GLB digest itself, as generated_sha256.
    ALLOWED = {('snapshot.py', '_identity'), ('snapshot.py', 'AssetSnapshot._check_consistency'),
               ('snapshot.py', 'AssetSnapshot.to_dict')}
    SNAPSHOT_NAMES = {'snapshot', 'source_snapshot', 'target_snapshot', 's'}

    def test_snapshot_sha256_is_read_only_in_identity_and_integrity(self):
        offenders = []
        for path in sorted((ROOT / 'msf_tools').rglob('*.py')):
            tree = ast.parse(path.read_text())
            def visit(node, scope, in_snapshot_class):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                        visit(child, f'{scope}.{child.name}'.lstrip('.'),
                              in_snapshot_class or isinstance(child, ast.ClassDef) and child.name == 'AssetSnapshot')
                        continue
                    if isinstance(child, ast.Attribute) and child.attr == 'sha256' and isinstance(child.ctx, ast.Load):
                        base = child.value
                        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, 'id', None)
                        if name in self.SNAPSHOT_NAMES or name == 'self' and in_snapshot_class:
                            if (path.name, scope) not in self.ALLOWED:
                                offenders.append(f'{path.name}:{child.lineno} {scope}')
                    visit(child, scope, in_snapshot_class)
            visit(tree, '', False)
        self.assertEqual(offenders, [])
