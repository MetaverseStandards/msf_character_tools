# SPDX-License-Identifier: MIT
"""The format seam: generated snapshots, source identity and sidecar binding."""
from pathlib import Path
import unittest

import msf_character_tools as m
from msf_character_tools import snapshot as snapshots
from msf_character_tools.common import digest, freeze, thaw
from msf_character_tools.report import Fault
from msf_character_tools.sources import SourceLimits
from internal.adapters import fake_adapter as fake
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
COMBINED = (ROOT / 'tests/public/fixtures/combined.gltf').read_bytes()


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


def generated(scene=None, adapter=None, **kwargs):
    data = fake.source(scene or fake.scene())
    kwargs.setdefault('resolver', fake.resolver)
    return data, snapshots._inspect_source(adapter or fake.FakeAdapter(), data, 'usda', **kwargs)


def readmit(snapshot, source):
    """Admit the snapshot's asset again with another source record, as inspection would."""
    record = snapshots._record(snapshot._core.fork(), snapshot.document, snapshot.resources, snapshot.chunks,
                               snapshot.channels, snapshot.bindings, freeze(source))
    return snapshots._admit_snapshot(record, snapshot._component_caps())


def good(result):
    assert result.ok, result.report.to_dict()
    return result.value


def seam_authoring():
    """One identity rule from the fake face's 'smile' target to a profile output."""
    return {'schema_version': '1.0', 'data_version': '0.1.0', 'operator_version': '1.0', 'id': 'seam', 'license': 'MIT',
            'signals': [dict(SIGNAL, label='Smile', disposition='mapped', evidence=['e'], evidence_status='verified_current'),
                        dict(SIGNAL, id='out', label='Out', disposition='mapped', evidence=['e'], evidence_status='verified_current')],
            'profiles': [{'id': 'target', 'label': 'Target', 'signal_ids': ['out']}],
            'mappings': [{'id': 'seam', 'rules': [{'id': 'r', 'inputs': ['smile'], 'outputs': ['out'], 'operator': {'id': 'identity'},
                                                   'disposition': 'mapped', 'mapping_quality': 'exact', 'assumptions': [],
                                                   'evidence': ['e'], 'evidence_status': 'verified_current', 'loss_annotations': []}]}],
            'evidence': [{'id': 'e', 'claim': 'Seam test.', 'status': 'verified_current', 'license': 'MIT', 'authorship': 'MSF Tools contributors'}]}


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
            'options_sha256': digest(m.canonical_json({'influences': 'faithful', 'losses': 'declare'})),
            'node_order': 'path-sorted-v2',
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
        self.assertEqual(thaw(binding['ref']), {'asset_sha256': self.source_sha, 'locator': '/nodes/1/weights/0',
                                                'node': 1, 'mesh': 0, 'target': 0, 'source_locator': '/Root/Face#smile'})
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
        pack = good(m.compile_pack(good(m.validate_authoring(seam_authoring()))))
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
                readmit(self.snapshot, dict(thaw(self.snapshot.source), **{key: value}))
            self.assertEqual((caught.exception.diagnostic.code, caught.exception.diagnostic.ref), ('E_RECORD_INTEGRITY', '/source'))
        for changed in ({**thaw(self.snapshot.source), 'extra': 1},
                        {k: v for k, v in thaw(self.snapshot.source).items() if k != 'losses'},
                        dict(thaw(self.snapshot.source), adapter='other')):
            with self.subTest(changed=sorted(changed)), self.assertRaises(Fault) as caught:
                readmit(self.snapshot, changed)
            self.assertEqual(caught.exception.diagnostic.ref, '/source')
        for key, value in (('node_paths', ['/Root/Face', '/Root']), ('node_paths', ['Root', '/Root/Face']),
                           ('target_keys', [['smile', 'bl:ink']])):
            with self.subTest(grammar=value), self.assertRaises(Fault) as caught:
                readmit(self.snapshot, dict(thaw(self.snapshot.source), **{key: value}))
            self.assertEqual((caught.exception.diagnostic.code, caught.exception.diagnostic.ref), ('E_RECORD_INTEGRITY', '/source'))
        readmit(self.snapshot, thaw(self.snapshot.source))
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


class PersistedOutputsIgnoreTheGeneratedGlb(unittest.TestCase):
    """Nothing persisted may depend on the GLB bytes, which change with the reader version."""

    def persisted(self, adapter):
        data, result = generated(adapter=adapter)
        snapshot = good(result)
        binding = thaw(good(m.morph_binding(snapshot, SIGNAL, 1, 0)))
        sidecar = good(m.annotate_asset(snapshot, {'bindings': [binding]}))
        bound = good(generated(adapter=adapter, sidecar=sidecar)[1])
        golden = thaw(good(m.export_geometry_golden(bound)))
        pack = good(m.compile_pack(good(m.validate_authoring(seam_authoring()))))
        compiled = good(m.compile_mapping(pack, bound, good(m.profile_snapshot(pack, 'target')), 'seam'))
        evaluated = good(m.evaluate_mapping(compiled, [{'timestamp': 0, 'values': {'smile': 0.5}, 'validity': {'smile': True}}]))
        exported = bound.to_dict()
        identities = [binding['ref']['asset_sha256'], sidecar.to_dict()['asset_sha256'], golden['asset_sha256'],
                      compiled.to_dict()['source_sha256'], exported['asset_sha256']]
        for field in ('generated_sha256', 'resources', 'chunks', 'source'):
            exported.pop(field)
        golden.pop('source')
        outputs = {'binding': binding, 'sidecar': sidecar.to_dict(), 'golden': golden,
                   'compiled': {k: v for k, v in compiled.to_dict().items() if k != 'source_adapter'},
                   'evaluated': evaluated.to_dict(), 'snapshot': exported}
        return digest(data), bound.sha256, identities, {k: m.canonical_json(v) for k, v in outputs.items()}

    def test_no_output_carries_the_glb_digest_or_changes_with_the_reader(self):
        source_sha, glb_sha, identities, outputs = self.persisted(fake.FakeAdapter())
        self.assertEqual(identities, [source_sha] * 5)
        for name, raw in outputs.items():
            with self.subTest(output=name):
                self.assertNotIn(glb_sha.encode(), raw)
        other_source, other_glb, _, other_outputs = self.persisted(fake.FakeAdapter('2', compact_json=True))
        self.assertEqual(other_source, source_sha)
        self.assertNotEqual(other_glb, glb_sha)
        self.assertEqual(other_outputs, outputs)

def add_arm(scene):
    scene['nodes'].append({'path': '/Root/Arm'})


def swap_targets(scene):
    scene['meshes']['face']['targets'].reverse()


def rename_face(scene):
    scene['nodes'][0]['path'] = '/Root/Head'


class SourceLocatorBinding(unittest.TestCase):
    def setUp(self):
        _, result = generated()
        self.snapshot = good(result)
        self.binding = thaw(good(m.morph_binding(self.snapshot, SIGNAL, 1, 0)))
        self.sidecar = good(m.annotate_asset(self.snapshot, {'bindings': [self.binding]}))

    def bound(self, adapter, sidecar=None):
        return generated(adapter=adapter, sidecar=self.sidecar.to_dict() if sidecar is None else sidecar)[1]

    def test_same_reader_binds_without_warnings(self):
        result = self.bound(fake.FakeAdapter())
        self.assertEqual([d.code for d in result.report.diagnostics], ['W_SKIPPED'])
        self.assertEqual(thaw(good(result).bindings[0]['ref']), self.binding['ref'])

    def test_reindexed_nodes_and_targets_resolve_by_locator(self):
        def both(scene):
            add_arm(scene)
            swap_targets(scene)
        result = self.bound(fake.FakeAdapter('2', both))
        snapshot = good(result)
        self.assertEqual(snapshot.source['node_paths'], ('/Root', '/Root/Arm', '/Root/Face'))
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics],
                         [('W_BINDING_REINDEXED', '/bindings/ref'), ('W_SKIPPED', '/Root')])
        self.assertEqual(thaw(snapshot.bindings[0]['ref']), dict(self.binding['ref'], node=2, target=1, locator='/nodes/2/weights/1'))
        snapshot._check_integrity()
        annotated = m.annotate_asset(snapshot, {'bindings': [self.binding]})
        self.assertEqual([d.code for d in annotated.report.diagnostics], ['W_BINDING_REINDEXED'])
        self.assertEqual(annotated.value.to_dict()['bindings'][0]['ref']['node'], 2)

    def test_missing_source_node_or_target_is_stale(self):
        for edit in (rename_face, lambda scene: scene['meshes']['face']['targets'].pop(0)):
            with self.subTest(edit=edit):
                result = self.bound(fake.FakeAdapter('2', edit))
                self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics if d.severity == 'error'],
                                 [('E_STALE_SOURCE', '/bindings/ref/source_locator')])

    def test_generated_bindings_need_a_locator_and_no_buffer_digest(self):
        for change, code in (({'source_locator': None}, 'E_REQUIRED'), ({'resource_sha256': '0' * 64}, 'E_BINDING_REFERENCE'),
                             ({'source_locator': '/Root/Face'}, 'E_BINDING_REFERENCE'), ({'node': -1}, 'E_BINDING_REFERENCE')):
            ref = {k: v for k, v in dict(self.binding['ref'], **change).items() if v is not None}
            with self.subTest(change=change):
                result = m.annotate_asset(self.snapshot, {'bindings': [dict(self.binding, ref=ref)]})
                self.assertEqual([d.code for d in result.report.diagnostics], [code])

    def test_meshes_on_helper_nodes_bind_by_locator(self):
        scene = fake.scene(nodes=[{'path': '/Body'}, {'path': '/Body#helper:geometry', 'mesh': 'face'}])
        snapshot = good(generated(scene)[1])
        binding = thaw(good(m.morph_binding(snapshot, SIGNAL, 1, 0)))
        self.assertEqual(binding['ref']['source_locator'], '/Body#helper:geometry#smile')
        sidecar = good(m.annotate_asset(snapshot, {'bindings': [binding]}))
        self.assertEqual(thaw(good(generated(scene, sidecar=sidecar)[1]).bindings[0]['ref']), binding['ref'])

    def test_gltf_bindings_refuse_source_locators(self):
        snapshot = good(m.inspect_asset(COMBINED, 'gltf'))
        binding = thaw(good(m.morph_binding(snapshot, SIGNAL, 5, 0)))
        self.assertNotIn('source_locator', binding['ref'])
        binding['ref']['source_locator'] = '/Root/Face#smile'
        result = m.annotate_asset(snapshot, {'bindings': [binding]})
        self.assertEqual([d.code for d in result.report.diagnostics], ['E_UNKNOWN_KEY'])


FAKE_TABLE = {'usd': 'internal.adapters.fake_adapter', 'usda': 'internal.adapters.fake_adapter'}


class PublicSourceDispatch(unittest.TestCase):
    def setUp(self):
        table = patch.dict(snapshots._ADAPTER_MODULES, FAKE_TABLE)
        table.start()
        self.addCleanup(table.stop)
        self.data = fake.source(fake.scene())

    def inspect(self, data=None, fmt='usda', **kwargs):
        kwargs.setdefault('resolver', fake.resolver)
        return m.inspect_asset(self.data if data is None else data, fmt, **kwargs)

    def errors(self, result):
        return [(d.code, d.ref) for d in result.report.diagnostics if d.severity == 'error']

    def test_public_inspect_admits_sources_deterministically(self):
        first, second = good(self.inspect()), good(self.inspect())
        self.assertEqual(first.source['format'], 'usda')
        self.assertEqual(first.original_bytes, second.original_bytes)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(good(self.inspect(fmt='usd')).source['format'], 'usda')
        self.assertEqual(good(self.inspect(fmt='USDA')).source['format'], 'usda')

    def test_magic_bytes_must_match_the_declared_format(self):
        for data, fmt in ((b'PXR-USDC' + self.data, 'usda'), (self.data, 'usdc'), (self.data, 'usdz'), (b'', 'usd'),
                          (b'PK\x03\x04rest', 'usd'), (b'\x00\x01\x02', 'fbx'), (self.data[:0], 'fbx')):
            with self.subTest(data=data[:8], fmt=fmt):
                self.assertEqual(self.errors(self.inspect(data, fmt)), [('E_FORMAT_MISMATCH', '/')])

    def test_missing_support_is_a_dependency_diagnostic(self):
        with patch.dict(snapshots._ADAPTER_MODULES, {'usda': 'internal.adapters.no_such_adapter'}):
            result = self.inspect()
        self.assertEqual(self.errors(result), [('E_FORMAT_DEPENDENCY', '/')])
        self.assertIn('USD support is not installed in this build', result.report.diagnostics[0].message)
        self.assertNotIn('pip install', result.report.diagnostics[0].remediation)
        with patch.dict(snapshots._ADAPTER_MODULES, {'fbx': 'internal.adapters.no_such_adapter'}):
            result = m.inspect_asset(b'Kaydara FBX Binary  \x00\x1a\x00', 'fbx')
        self.assertEqual(self.errors(result), [('E_FORMAT_DEPENDENCY', '/')])
        self.assertIn('FBX support is not installed in this build', result.report.diagnostics[0].message)
        with patch.dict(snapshots._ADAPTER_MODULES, {'usda': 'internal.adapters.adapter_missing_reader'}):
            result = self.inspect()
        self.assertEqual(self.errors(result), [('E_FORMAT_DEPENDENCY', '/')])
        self.assertIn("pip install 'msf-tools[usd]'", result.report.diagnostics[0].remediation)

    def test_unknown_formats_and_gltf_source_arguments_are_refused(self):
        result = m.inspect_asset(self.data, 'obj')
        self.assertEqual(self.errors(result), [('E_ASSET_TYPE', '/')])
        self.assertIn('usd, usda, usdc, usdz, fbx', result.report.diagnostics[0].message)
        for kwargs in ({'options': {}}, {'limits': SourceLimits()}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.errors(m.inspect_asset(COMBINED, 'gltf', **kwargs)), [('E_SOURCE_OPTIONS', '/')])

    def test_options_are_closed_validated_and_digested_with_defaults(self):
        for options in ({'colour': 1}, {'influences': 'top8'}, {'losses': True}, {'animation': -1}, {'animation': True},
                        {'sample_rate': 30.0}, [('losses', 'strict')]):
            with self.subTest(options=options):
                self.assertEqual(self.errors(self.inspect(options=options)), [('E_SOURCE_OPTIONS', '/options')])
        digest_of = lambda options: good(self.inspect(options=options)).source['options_sha256']
        self.assertEqual(digest_of(None), digest_of({'influences': 'faithful', 'losses': 'declare'}))
        self.assertNotEqual(digest_of(None), digest_of({'influences': 'top4'}))
        self.assertNotEqual(digest_of({'animation': 0}), digest_of({'animation': 'Take 001'}))

    def test_strict_losses_refuse_and_infos_stay(self):
        losses = [['W_SKIPPED', '/Root', 'Skipped 1 camera.'], ['W_SHEAR_BAKED', '/Root', 'Baked shear.'], ['I_UNITS_CONVERTED', '/', 'cm to m.']]
        data = fake.source(fake.scene(losses=losses))
        declared = self.inspect(data)
        self.assertEqual([d.severity for d in declared.report.diagnostics], ['warning', 'warning', 'info'])
        strict = self.inspect(data, options={'losses': 'strict'})
        self.assertIsNone(strict.value)
        self.assertEqual([(d.code, d.severity) for d in strict.report.diagnostics],
                         [('E_SKIPPED', 'error'), ('E_SHEAR_UNSUPPORTED', 'error'), ('I_UNITS_CONVERTED', 'info')])

    def test_input_and_output_size_limits(self):
        n = len(self.data)
        self.assertTrue(self.inspect(limits=SourceLimits(max_source_bytes=n)).ok)
        self.assertEqual(self.errors(self.inspect(limits=SourceLimits(max_source_bytes=n - 1))), [('E_RESOURCE_LIMIT', '/')])
        glb_size = len(good(self.inspect()).original_bytes)
        self.assertTrue(self.inspect(limits=SourceLimits(max_generated_bytes=glb_size)).ok)
        self.assertEqual(self.errors(self.inspect(limits=SourceLimits(max_generated_bytes=glb_size - 1))), [('E_RESOURCE_LIMIT', '/')])
        self.assertEqual(self.errors(self.inspect(limits=SourceLimits(max_accessor_components=8))), [('E_RESOURCE_LIMIT', '/accessors/0')])
        self.assertEqual(self.errors(self.inspect(limits=SourceLimits(max_total_accessor_components=9))), [('E_RESOURCE_LIMIT', '/accessors/1')])
        two = fake.source(fake.scene(dependencies=['layers/sub.usda', 'layers/two.usda']))
        resolver = lambda uri: b'0123456789'
        self.assertTrue(self.inspect(two, resolver=resolver, limits=SourceLimits(max_dependencies=2, max_dependency_bytes=20)).ok)
        self.assertEqual(self.errors(self.inspect(two, resolver=resolver, limits=SourceLimits(max_dependencies=1))),
                         [('E_RESOURCE_LIMIT', '/source/dependencies')])
        self.assertEqual(self.errors(self.inspect(two, resolver=resolver, limits=SourceLimits(max_dependency_bytes=19))),
                         [('E_RESOURCE_LIMIT', '/source/dependencies')])
        self.assertEqual(self.errors(self.inspect(limits={'max_source_bytes': 1})), [('E_SOURCE_OPTIONS', '/limits')])

    def test_source_limits_are_positive_integers_within_ceilings(self):
        for field, value in (('max_source_bytes', 0), ('max_source_bytes', 4 * 2**30 + 1), ('timeout_s', -1), ('max_dependencies', True),
                             ('max_usdz_members', 1.0), ('max_accessor_components', 4_000_001), ('max_total_accessor_components', 16_000_001)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                SourceLimits(**{field: value})
