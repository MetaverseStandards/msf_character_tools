# SPDX-License-Identifier: MIT
"""The real-asset harness recipes (CASE_MATRIX09K), when a local copy is present (never committed).

Set MSF_REAL_ASSETS to a folder holding exact copies of the plan's inputs, laid out as
`real-asset-harness-plan09K/` (CASE_MATRIX.json and fixtures/), `assets-e2e09H/assets/`
(Fox, RobotExpressiveHead, RobotExpressive) and `assets-oracle-review09I/` (the
independent Decimal oracles and EXPECTATION_SPEC.json). There is one test per case ID
in CASE_MATRIX.json. Cases that need things this checkout cannot provide (installed
artifacts, consumer repositories, DCC hosts, frozen cost literals) are skipped with
the reason, and cases already covered by the fast suite say which tests cover them.
"""
import contextlib
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

import msf_character_tools as m
from msf_character_tools import cli
from support.values import plain

ROOT = Path(os.environ['MSF_REAL_ASSETS']) if os.environ.get('MSF_REAL_ASSETS') else None
PRESENT = ROOT is not None and (ROOT / 'real-asset-harness-plan09K' / 'CASE_MATRIX.json').is_file()
PLAN = ROOT / 'real-asset-harness-plan09K' if PRESENT else None
FIX = PLAN / 'fixtures' if PRESENT else None
ASSETS = ROOT / 'assets-e2e09H' / 'assets' if PRESENT else None
ORACLES = ROOT / 'assets-oracle-review09I' if PRESENT else None
SOURCE = 'vale.review.head.coefficient.source'
TARGET = 'vale.review.head.node0.target0'
MAPPING = 'ren.real09K.head.identity'

SKIPPED = {
    'SYNTHETIC-COMPLEMENT': 'Superseded in part by Ken\'s N-influence decision (its "eight-influence inventory then capability '
                            'refusal" now evaluates); the rest is the retained original suite, which is the fast suite itself.',
    'RECORD-OWNERSHIP': 'Original synthetic contract covered by the fast suite: tests/public/test_record_integrity.py.',
    'REPARENT': 'Original synthetic contract covered by the fast suite: reparent_local tests in tests/public/test_reference.py and '
                'tests/public/test_numerical_boundaries.py.',
    'CLI-FAILURE-PUBLICATION': 'Needs runtime help/exception/emergency bytes frozen independently before observation; the '
                               'alias, hardlink, stale and safe-output branches are covered by tests/public/test_reference.py and '
                               'tests/public/test_source_cli.py and tests/internal/test_source_cli_internal.py.',
    'RESOURCE-DEFAULTS': 'Needs end-to-end-scope09J REQUIREMENTS all45/all49 owner programs and final cost literals frozen '
                         'against accepted sites; the plan marks real default costs as unobserved.',
    'PRODUCER-EXPORT-VALIDATOR': 'Needs the H5L producer exports for 3.11 and 3.12 and a Draft 2020-12 validator install; '
                                 'neither exists in this checkout.',
    'ARTIFACT-TWO-INSTALLS': 'Needs the final committed-source wheel/sdist and verifier (H5L packaging, W9).',
    'RCEF-OWN-CONSUMER': 'Needs RCEF\'s own qualification test adapter and lock; RCEF check.py itself runs in scripts/ci_local.sh.',
    'RCSF-OWN-CONSUMER': 'Needs local RCSF\'s loader, lock and test adapter.',
    'ADMISSION-CAUSE-ROLLBACK': 'Needs H5L artifact admission, locks and rollback; packaging is W9.',
    'HOST-ORIGINAL-REBINDS': 'Needs Blender 4.5.0 and Godot 4.5-stable, which are not installed here.',
    'HOST-REAL-CLAIM-ONLY': 'Conditional: no real-host coverage is claimed, so there is nothing to run.',
    'F-WORLD-PALETTE-WITNESSES': 'Watches private geometry internals, so tests/internal/test_real_assets_internal.py runs it.',
}


def load(path):
    return json.loads(Path(path).read_text())


def close(test, actual, reference, absolute, relative, where=''):
    test.assertEqual(len(actual), len(reference), where)
    for a, r in zip(actual, reference):
        if isinstance(r, (list, tuple)):
            close(test, a, r, absolute, relative, where)
        else:
            test.assertTrue(math.isfinite(a) and abs(a - r) <= absolute + relative * abs(r), (where, a, r))


def cli_run(*args):
    out, err = io.TextIOWrapper(io.BytesIO()), io.TextIOWrapper(io.BytesIO())
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in args])
    out.flush()
    err.flush()
    return code, out.buffer.getvalue(), err.buffer.getvalue()


class Inputs:
    """Everything the cases share, built once with fresh resolvers."""
    _built = None

    @classmethod
    def get(cls):
        if cls._built is None:
            cls._built = cls()
        return cls._built

    def __init__(self):
        self.matrix = load(PLAN / 'CASE_MATRIX.json')
        self.spec = load(PLAN / 'FIXTURE_SPEC.json')
        self.expect = load(ORACLES / 'EXPECTATION_SPEC.json')['tolerances']
        self.head_dir, self.fox_dir = ASSETS / 'RobotExpressiveHead', ASSETS / 'Fox'
        self.head_raw = (self.head_dir / 'RobotExpressiveHead.gltf').read_bytes()
        self.fox_raw = (self.fox_dir / 'Fox.gltf').read_bytes()
        self.authoring = load(FIX / 'head.authoring.json')
        self.pack = m.compile_pack(m.validate_authoring(self.authoring).value).value
        self.head = m.inspect_asset(self.head_raw, 'gltf', resolver=m.LocalResolver(self.head_dir)).value
        self.sidecar_bytes = (FIX / 'head.sidecar.prospective.json').read_bytes()
        self.reinspected = m.inspect_asset(self.head_raw, 'gltf', resolver=m.LocalResolver(self.head_dir),
                                           sidecar=json.loads(self.sidecar_bytes)).value
        self.profile = m.profile_snapshot(self.pack, 'ren.real09K.head.source').value
        self.compiled = m.compile_mapping(self.pack, self.profile, self.reinspected, MAPPING, False).value
        self.samples = load(FIX / 'head.samples.json')
        self.fox = m.inspect_asset(self.fox_raw, 'gltf', resolver=m.LocalResolver(self.fox_dir)).value
        self._oracles = {}

    def oracle(self, name):
        if name not in self._oracles:
            self._oracles[name] = load(ORACLES / f'{name}.independent.json')
        return self._oracles[name]


def negative_report(case_id):
    case = next(c for c in Inputs.get().matrix['cases'] if c['id'] == case_id)
    return case['negative_recipe']


@unittest.skipUnless(PRESENT, 'set MSF_REAL_ASSETS to a local copy of the 09K harness inputs to run this tier')
class RealAssetRecipes(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.x = Inputs.get()

    # Head: authoring, pack, inspection, binding, mapping

    def case_H_AUTHORING(self):
        validated = m.validate_authoring(self.x.authoring)
        loaded = m.load_authoring(FIX / 'head.authoring.toml')
        self.assertTrue(validated.ok and loaded.ok)
        self.assertEqual(plain(validated.value.to_dict()), self.x.authoring)
        self.assertEqual(plain(loaded.value.to_dict()), self.x.authoring)

    def case_H_PACK(self):
        self.assertEqual(self.x.pack.to_bytes(), (FIX / 'expected-generated' / 'pack.json').read_bytes())
        self.assertEqual(self.x.pack.sha256, self.x.spec['proposed_hashes']['pack_canonical_sha256'])
        loaded = m.compile_pack(m.load_authoring(FIX / 'head.authoring.toml').value).value
        self.assertEqual(loaded.to_bytes(), self.x.pack.to_bytes())

    def case_H_PACK_EXPORTS(self):
        generated = FIX / 'expected-generated'
        rendered = {'pack.json': self.x.pack.to_bytes(), 'survey.csv': m.survey_csv(self.x.pack),
                    'coverage.json': m.canonical_json(m.coverage(self.x.pack))}
        rendered['SHA256SUMS'] = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in rendered.items()).encode()
        for name, data in rendered.items():
            self.assertEqual(data, (generated / name).read_bytes(), name)

    def case_H_INSPECT(self):
        recipe = self.x.spec['inspection_public_recipe']
        wire = plain(self.x.head.to_dict())
        self.assertEqual(sorted(wire), sorted(recipe['required_keys']))
        self.assertEqual(wire['document'], json.loads(self.x.head_raw))
        self.assertEqual(wire['resources'], recipe['resources']['HEAD'])
        self.assertEqual((wire['chunks'], wire['channels'], wire['bindings']), ([], {}, []))
        # Superseded by the approved N-influence change: the plan froze "four_influence_LBS" before evaluation covered
        # every influence set, and the capability was renamed to say so.
        expected = copy.deepcopy(recipe['capabilities'])
        self.assertEqual(expected['geometry'], ['POSITION', 'relative_morph', 'four_influence_LBS'])
        expected['geometry'][2] = 'linear_blend_skinning'
        self.assertEqual(wire['capabilities'], expected)
        self.assertEqual(wire['asset_sha256'], self.x.spec['proposed_hashes']['asset_raw_sha256'])

    def case_H_DECODE(self):
        document, buffer = json.loads(self.x.head_raw), (self.x.head_dir / 'RobotExpressiveHead.bin').read_bytes()
        self.assertEqual(len(document['accessors']), 18)
        for index, accessor in enumerate(document['accessors']):
            view = document['bufferViews'][accessor['bufferView']]
            kind = {5126: 'f', 5125: 'I', 5123: 'H', 5121: 'B'}[accessor['componentType']]
            width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
            size = struct.calcsize('<' + kind)
            stride = view.get('byteStride', size * width)
            start = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
            # Read straight from the buffer, independently of msf-tools' accessor decoding.
            wanted = [struct.unpack_from('<' + kind * width, buffer, start + k * stride) for k in range(accessor['count'])]
            decoded = m.decode_accessor(self.x.head, index).value
            self.assertEqual([tuple(row) for row in decoded], wanted, index)
        for primitive in self.x.spec['head_structural_crosscheck']['primitives']:
            mesh = document['meshes'][0]['primitives'][primitive['primitive']]
            self.assertEqual(document['accessors'][primitive['POSITION_accessor']]['count'], primitive['vertices'])
            self.assertEqual(document['accessors'][primitive['index_accessor']]['count'], primitive['indices'])
            self.assertEqual(len(mesh['targets']), primitive['targets'])

    def case_H_BIND_ANNOTATE_REINSPECT(self):
        binding = m.morph_binding(self.x.head, self.x.pack.signals[TARGET], 0, 0).value
        prospective = json.loads(self.x.sidecar_bytes)
        self.assertEqual(plain(binding), prospective['bindings'][0])
        sidecar = m.annotate_asset(self.x.head, load(FIX / 'head.annotations.json')).value
        self.assertEqual(m.canonical_json(sidecar), self.x.sidecar_bytes)
        again = m.annotate_asset(self.x.reinspected, load(FIX / 'head.annotations.json')).value
        self.assertEqual(m.canonical_json(again), self.x.sidecar_bytes)
        self.assertEqual(list(self.x.reinspected.channels), [TARGET])
        self.assertEqual(self.x.reinspected.original_bytes, self.x.head_raw)
        self.assertEqual([r.to_dict() for r in self.x.reinspected.resources], [r.to_dict() for r in self.x.head.resources])

    def case_H_PROFILE(self):
        wire = plain(self.x.profile.to_dict())
        self.assertEqual(wire['asset_sha256'], hashlib.sha256((FIX / 'head.profile.prospective.json').read_bytes()).hexdigest())
        self.assertEqual((wire['resources'], wire['chunks'], wire['bindings']), ([], [], []))
        self.assertEqual(list(wire['channels']), [SOURCE])

    def case_H_MAP(self):
        self.assertEqual(m.canonical_json(self.x.compiled), (FIX / 'head.mapping.prospective.json').read_bytes())
        self.assertEqual(hashlib.sha256(m.canonical_json(self.x.compiled)).hexdigest(),
                         self.x.spec['proposed_hashes']['mapping_canonical_sha256'])

    def case_H_EVALUATE(self):
        evaluated = m.evaluate_mapping(self.x.compiled, self.x.samples).value
        self.assertEqual(m.canonical_json(evaluated), (FIX / 'head.evaluated.prospective.json').read_bytes())

    # Head: the consumer applies evaluated coefficients to geometry

    def head_rows(self, weights):
        kwargs = {} if weights is None else {'morph_weights': {0: weights}}
        return [p['positions'] for p in m.evaluate_geometry(self.x.reinspected, **kwargs).value.to_dict()['instances'][0]['primitives']]

    def check_head(self, rows, case):
        tolerance = self.x.expect['RobotExpressiveHead']['POSITION_mesh_local_and_world']
        oracle = self.x.oracle('RobotExpressiveHead')['cases'][case]
        local = [p['positions'] for p in oracle['geometry']['instances'][0]['primitives']]
        world = oracle['world_reference'][0]
        self.assertEqual(world['world_matrix_column_major'], [float(r == c) for c in range(4) for r in range(4)])
        for actual, wanted, worlds in zip(rows, local, world['primitives']):
            close(self, actual, wanted, tolerance['absolute'], tolerance['relative'], case)
            close(self, actual, worlds['positions'], tolerance['absolute'], tolerance['relative'], case)
        return sum(len(r) for r in rows)

    def case_H_APPLY_GEOMETRY(self):
        evaluated = m.evaluate_mapping(self.x.compiled, self.x.samples).value.to_dict()['samples']
        joins = {j['coefficient']: j['oracle_case_index'] for j in self.x.spec['head_coefficient_join']}
        document = self.x.reinspected.document
        rows = 0
        for frame in evaluated:
            coefficient = frame['values'][TARGET]
            ref = self.x.reinspected.bindings[0]['ref']
            node = document['nodes'][ref['node']]
            weights = list(node.get('weights', document['meshes'][node['mesh']].get('weights', (0.0, 0.0, 0.0))))
            self.assertEqual(len(weights), 3)
            weights[ref['target']] = coefficient
            rows += self.check_head(self.head_rows(weights), joins[coefficient])
        self.assertEqual(rows, 5226)

    def case_H_ZERO_DEFAULT_TWIN(self):
        self.assertEqual(self.check_head(self.head_rows(None), 0), 1742)
        self.assertEqual(self.check_head(self.head_rows([0.0, 0.0, 0.0]), 0), 1742)

    def case_H_EXPORT_GOLDEN(self):
        golden = plain(m.export_geometry_golden(self.x.head).value)
        self.assertEqual(sorted(golden), ['asset_sha256', 'coordinates', 'evaluation', 'precision', 'schema_version', 'units'])
        self.assertEqual((golden['schema_version'], golden['precision'], golden['coordinates'], golden['units']),
                         ('1.0', 'binary64', 'mesh_local', 'metres'))
        self.assertEqual(golden['asset_sha256'], hashlib.sha256(self.x.head_raw).hexdigest())
        self.check_head([p['positions'] for p in golden['evaluation']['instances'][0]['primitives']], 0)
        self.assertEqual(hashlib.sha256((self.x.head_dir / 'RobotExpressiveHead.bin').read_bytes()).hexdigest(),
                         self.x.spec['proposed_hashes']['buffer_raw_sha256'])

    # Fox: skinned, animated, inspected without morph targets

    def case_F_INSPECT_DECODE(self):
        wire = plain(self.x.fox.to_dict())
        self.assertEqual(wire['document'], json.loads(self.x.fox_raw))
        self.assertEqual(wire['resources'], self.x.spec['inspection_public_recipe']['resources']['FOX'])
        self.assertEqual(len(wire['document']['accessors']), 71)
        for index in range(71):
            self.assertTrue(m.decode_accessor(self.x.fox, index).ok, index)
        self.assertEqual(sum(len(a['channels']) for a in wire['document']['animations']), 63)
        sidecar = m.annotate_asset(self.x.fox, {'bindings': []}).value
        again = m.inspect_asset(self.x.fox_raw, 'gltf', resolver=m.LocalResolver(self.x.fox_dir), sidecar=plain(sidecar.to_dict()))
        self.assertTrue(again.ok)
        self.assertEqual((dict(again.value.channels or {}), list(again.value.bindings)), ({}, []))

    def fox_case(self, index):
        case = self.x.oracle('Fox')['cases'][index]
        tolerance = self.x.expect['Fox']['POSITION_mesh_local_and_world']
        kwargs = {'timestamp': case['case']['timestamp'], 'animation_id': case['case']['animation_id']}
        value = m.evaluate_geometry(self.x.fox, **kwargs).value.to_dict()
        self.assertEqual(value['timestamp'], case['case']['timestamp'])
        instance = value['instances'][0]
        self.assertEqual((instance['node'], instance['mesh'], instance['primitives'][0]['primitive']), (1, 0, 0))
        rows = instance['primitives'][0]['positions']
        self.assertEqual(len(rows), 1728)
        close(self, rows, case['geometry']['instances'][0]['primitives'][0]['positions'], tolerance['absolute'], tolerance['relative'])
        world = case['world_reference'][0]['world_matrix_column_major']
        moved = [[math.fsum(world[c * 4 + r] * v for c, v in enumerate((*p, 1.0))) for r in range(3)] for p in rows]
        close(self, moved, case['world_reference'][0]['primitives'][0]['positions'], tolerance['absolute'], tolerance['relative'])

    def case_F_REST(self):
        self.fox_case(0)

    def case_F_SURVEY_0(self):
        self.fox_case(1)

    def case_F_SURVEY_0137(self):
        self.fox_case(2)

    def case_F_SURVEY_END(self):
        self.fox_case(3)

    def case_F_SAMPLE_CHANNELS(self):
        tolerance = self.x.expect['Fox']
        for index in (1, 2, 3):
            case = self.x.oracle('Fox')['cases'][index]
            sampled = m.sample_animation(self.x.fox, 0, case['case']['timestamp']).value
            wanted = case['sampled_channels']
            self.assertEqual({str(node): sorted(props) for node, props in sampled.items()}, {node: sorted(props) for node, props in wanted.items()})
            components = 0
            for node, props in wanted.items():
                for prop, values in props.items():
                    key = 'rotation_channel_XYZW_components_with_expected_hemisphere' if prop == 'rotation' else 'translation_channel'
                    close(self, sampled[int(node)][prop], values, tolerance[key]['absolute'], tolerance[key]['relative'], (node, prop))
                    components += len(values)
            self.assertEqual((sum(len(p) for p in wanted.values()), components), (21, 83))

    def case_F_EXPORT(self):
        rows = 0
        tolerance = self.x.expect['Fox']['POSITION_mesh_local_and_world']
        for case in self.x.oracle('Fox')['cases']:
            golden = plain(m.export_geometry_golden(self.x.fox, timestamp=case['case']['timestamp'], animation_id=case['case']['animation_id']).value)
            positions = golden['evaluation']['instances'][0]['primitives'][0]['positions']
            close(self, positions, case['geometry']['instances'][0]['primitives'][0]['positions'], tolerance['absolute'], tolerance['relative'])
            rows += len(positions)
        self.assertEqual(rows, 6912)

    # Refusals

    def refusal(self, raw, fmt, expected, **kwargs):
        result = m.inspect_asset(raw, fmt, **kwargs)
        self.assertIsNone(result.value)
        self.assertEqual(plain(result.report.to_dict()), expected)

    def robot(self):
        return (ASSETS / 'RobotExpressive' / 'RobotExpressive.glb').read_bytes()

    def case_R_RAW_REFUSAL(self):
        self.refusal(self.robot(), 'glb', negative_report('R-RAW-REFUSAL')['expected_report'])

    def case_R_UNUSED_PRECEDENCE(self):
        self.refusal((FIX / 'twins' / 'RobotExpressive.unused-accessor.glb').read_bytes(), 'glb',
                     negative_report('R-UNUSED-PRECEDENCE')['expected_report'])

    def case_R_SIDECAR_CONTROL(self):
        self.refusal(self.robot(), 'glb', negative_report('R-SIDECAR-CONTROL')['expected_report'],
                     sidecar=load(FIX / 'twins' / 'RobotExpressive.sidecar.prospective.json'))

    def case_R_STALE_PRECEDENCE(self):
        self.refusal(self.robot(), 'glb', negative_report('R-STALE-PRECEDENCE')['expected_report'],
                     sidecar=load(FIX / 'twins' / 'RobotExpressive.stale-sidecar.json'))

    def case_F_BAD_SKIN_IMAGE_CONTROL(self):
        twin = FIX / 'twins' / 'fox-bad-skin'
        self.refusal((twin / 'Fox.gltf').read_bytes(), 'gltf', negative_report('F-BAD-SKIN-IMAGE-CONTROL')['expected_report'],
                     resolver=m.LocalResolver(twin))

    def case_F_MISSING_IMAGE_PRECEDENCE(self):
        recipe = negative_report('F-MISSING-IMAGE-PRECEDENCE')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for name in ('Fox.gltf', 'Fox.bin'):
                shutil.copyfile(FIX / 'twins' / 'fox-bad-skin' / name, root / name)
            result = m.inspect_asset((root / 'Fox.gltf').read_bytes(), 'gltf', resolver=m.LocalResolver(root))
        self.assertIsNone(result.value)
        diagnostics = result.report.diagnostics
        self.assertEqual(len(diagnostics), recipe['expected_report_count'])
        self.assertEqual((diagnostics[0].code, diagnostics[0].ref, diagnostics[0].severity, diagnostics[0].remediation),
                         (recipe['expected_code'], recipe['expected_ref'], recipe['expected_severity'], recipe['expected_remediation']))

    def case_F_UNRESOLVED_REST(self):
        inspected = m.inspect_asset(self.x.fox_raw, 'gltf')
        self.assertIn(('W_RESOURCE_UNCONSUMED', '/buffers/0'), [(d.code, d.ref) for d in inspected.report.diagnostics])
        result = m.evaluate_geometry(inspected.value)
        self.assertIsNone(result.value)
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], [('E_RESOURCE_UNAVAILABLE', '/accessors/0')])

    def case_F_UNRESOLVED_CLIP(self):
        unresolved = m.inspect_asset(self.x.fox_raw, 'gltf').value
        result = m.evaluate_geometry(unresolved, timestamp=0.137, animation_id=0)
        self.assertIsNone(result.value)
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], [('E_RESOURCE_UNAVAILABLE', '/accessors/6')])

    def case_F_CALLBACK_TYPE_BOUNDS(self):
        data = (self.x.fox_dir / 'Fox.bin').read_bytes()
        for answer, expected in ((bytearray(data), ('E_RESOLVER', '/buffers/0')), (data[:-1], ('E_BUFFER_BOUNDS', '/buffers/0'))):
            calls = []

            def resolver(uri, answer=answer):
                calls.append(uri)
                return answer

            result = m.inspect_asset(self.x.fox_raw, 'gltf', resolver=resolver)
            self.assertIsNone(result.value)
            self.assertEqual((result.report.diagnostics[0].code, result.report.diagnostics[0].ref), expected)
            self.assertEqual(calls, ['Fox.bin'])
        exact = m.inspect_asset(self.x.fox_raw, 'gltf', resolver=lambda uri: (self.x.fox_dir / uri).read_bytes()).value
        self.assertEqual(plain(exact.to_dict()), plain(self.x.fox.to_dict()))

    # Sample controls: one otherwise admitted frame, one mutation each

    def sample_control(self, case_id):
        recipe = negative_report(case_id)
        frame = copy.deepcopy(self.x.samples[0])
        mutation = recipe['mutation']
        if mutation == 'false validity':
            frame['validity'][SOURCE] = False
        elif mutation.startswith('values={}'):
            frame['values'], frame['validity'] = {}, {}
        elif mutation.startswith('validity[source]=1'):
            frame['validity'][SOURCE] = 1
        elif mutation.startswith('delete validity'):
            del frame['validity'][SOURCE]
        elif mutation.startswith('values[source]=2.0'):
            frame['values'][SOURCE] = 2.0
        result = m.evaluate_mapping(self.x.compiled, [frame])
        self.assertIsNone(result.value)
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], [(recipe['code'], recipe['ref'])])

    def case_H_INVALID(self):
        self.sample_control('H-INVALID')

    def case_H_MISSING(self):
        self.sample_control('H-MISSING')

    def case_H_NONBOOL(self):
        self.sample_control('H-NONBOOL')

    def case_H_MISSING_VALIDITY(self):
        self.sample_control('H-MISSING-VALIDITY')

    def case_H_OUT_DOMAIN(self):
        self.sample_control('H-OUT-DOMAIN')

    def case_H_STALE_BINDINGS(self):
        base = json.loads(self.x.sidecar_bytes)

        def changed(edit):
            sidecar = copy.deepcopy(base)
            edit(sidecar)
            return sidecar

        def binding(sidecar):
            return sidecar['bindings'][0]

        cases = [
            (lambda s: s.update(asset_sha256='0' * 64), ('E_STALE_SOURCE', '/sidecar')),
            (lambda s: s['resource_hashes'].update({'/buffers/0': '0' * 64}), ('E_STALE_SOURCE', '/sidecar')),
            (lambda s: binding(s)['ref'].update(resource_sha256='0' * 64), ('E_STALE_SOURCE', '/bindings/ref/resource_sha256')),
            (lambda s: binding(s)['ref'].update(target=3, locator='/nodes/0/weights/3'), ('E_BINDING_REFERENCE', '/bindings/ref')),
            (lambda s: binding(s)['ref'].update(locator='/nodes/0/weights/1'), ('E_BINDING_REFERENCE', '/bindings/ref/locator')),
            (lambda s: s['bindings'].append(copy.deepcopy(binding(s))), ('E_DUPLICATE_BINDING', '/sidecar/bindings')),
        ]
        for edit, expected in cases:
            with self.subTest(expected=expected):
                result = m.inspect_asset(self.x.head_raw, 'gltf', resolver=m.LocalResolver(self.x.head_dir), sidecar=changed(edit))
                self.assertIsNone(result.value)
                self.assertEqual((result.report.diagnostics[0].code, result.report.diagnostics[0].ref), expected)

    def case_F_NO_MORPH_BINDING(self):
        result = m.morph_binding(self.x.fox, self.x.pack.signals[TARGET], 1, 0)
        self.assertIsNone(result.value)
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], [('E_BINDING_REFERENCE', '/bindings/ref')])

    def compile_twin(self, edit, target=None):
        authoring = copy.deepcopy(self.x.authoring)
        edit(authoring)
        pack = m.compile_pack(m.validate_authoring(authoring).value).value
        source = m.profile_snapshot(pack, 'ren.real09K.head.source').value
        target = target or m.profile_snapshot(pack, 'ren.real09K.head.target').value
        result = m.compile_mapping(pack, source, target, MAPPING, False)
        self.assertIsNone(result.value)
        return [(d.code, d.ref) for d in result.report.diagnostics]

    def case_H_EVIDENCE_CALIBRATION(self):
        def empty(record):
            def edit(authoring):
                authoring['signals'][record]['evidence'] = []
            return edit

        self.assertEqual(self.compile_twin(empty(1)), [('E_EVIDENCE_REQUIRED', TARGET)])
        self.assertEqual(self.compile_twin(empty(0)), [('E_EVIDENCE_REQUIRED', SOURCE)])

        def no_rule_evidence(authoring):
            authoring['mappings'][0]['rules'][0]['evidence'] = []
        self.assertEqual(self.compile_twin(no_rule_evidence), [('E_EVIDENCE_REQUIRED', 'ren.real09K.head.identity.rule')])

        def basis(authoring):
            authoring['signals'][1]['calibration'] = 'A different technical basis.'
        self.assertEqual(self.compile_twin(basis), [('E_CALIBRATION', 'ren.real09K.head.identity.rule')])

        def both_bases(authoring):
            for signal in authoring['signals']:
                signal['calibration'] = 'A different technical basis.'
        # The sidecar still carries the original calibration, so the bound channel disagrees with the pack.
        self.assertEqual(self.compile_twin(both_bases, target=self.x.reinspected), [('E_CHANNEL_TYPE', TARGET)])

    def case_GEOMETRY_STRICT_TWINS(self):
        head, fox = self.x.reinspected, self.x.fox

        def refused(result, expected):
            self.assertIsNone(result.value)
            self.assertEqual((result.report.diagnostics[0].code, result.report.diagnostics[0].ref), expected)

        refused(m.evaluate_geometry(head, attributes=('POSITION', 'NORMAL')), ('E_GEOMETRY_CAPABILITY', '/attributes'))
        refused(m.evaluate_geometry(head, morph_weights={'0': [0.0, 0.0, 0.0]}), ('E_REFERENCE', '/morph_weights'))
        refused(m.evaluate_geometry(fox, animation_id=True), ('E_ANIMATION_REFERENCE', '/animation_id'))
        refused(m.evaluate_geometry(head, animation_id=0), ('E_REFERENCE', '/animations'))
        document = json.loads(self.x.head_raw)
        document['extensionsRequired'] = ['MSF_fixture_unknown']
        document['extensionsUsed'] = ['MSF_fixture_unknown']
        required = m.inspect_asset(json.dumps(document).encode(), 'gltf', resolver=m.LocalResolver(self.x.head_dir)).value
        refused(m.evaluate_geometry(required), ('E_REQUIRED_EXTENSION', '/extensionsRequired'))
        rotated = next(int(n) for n in self.x.oracle('Fox')['cases'][2]['sampled_channels']
                       if 'rotation' in self.x.oracle('Fox')['cases'][2]['sampled_channels'][n])
        refused(m.evaluate_geometry(fox, animation_id=0, timestamp=0.137, node_transforms={rotated: {'rotation': [0, 0, 0, 1]}}),
                ('E_MULTIPLE_WRITERS', f'/nodes/{rotated}'))
        # Superseded by Ken's N-influence decision: the twin used to expect E_INFLUENCE_LIMIT; it now evaluates.
        eight = m.inspect_asset((Path(__file__).parent / 'fixtures' / 'eight-influence.gltf').read_bytes(), 'gltf').value
        self.assertTrue(m.evaluate_geometry(eight).ok)

    # The six CLI commands, module route, in-process

    def case_CLI_CHECK(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            argv = ['check', FIX / 'head.authoring.toml', '--pack', out / 'pack.json', '--csv', out / 'survey.csv',
                    '--coverage', out / 'coverage.json', '--sha256', out / 'SHA256SUMS', '--write']
            code, stdout, stderr = cli_run(*argv)
            self.assertEqual((code, stdout, stderr), (0, (FIX / 'check.prospective.json').read_bytes(),
                                                      (FIX / 'success.report.prospective.json').read_bytes()))
            for name in ('pack.json', 'survey.csv', 'coverage.json', 'SHA256SUMS'):
                self.assertEqual((out / name).read_bytes(), (FIX / 'expected-generated' / name).read_bytes(), name)
            self.assertEqual(cli_run(*argv[:-1])[0], 0)

    def case_CLI_INSPECT(self):
        code, stdout, stderr = cli_run('inspect', self.x.head_dir / 'RobotExpressiveHead.gltf', '--resolver-root', self.x.head_dir,
                                       '--sidecar', FIX / 'head.sidecar.prospective.json')
        self.assertEqual((code, stderr), (0, (FIX / 'success.report.prospective.json').read_bytes()))
        self.assertEqual(json.loads(stdout), plain(self.x.reinspected.to_dict()))

    def case_CLI_ANNOTATE(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'head.sidecar.json'
            code, stdout, stderr = cli_run('annotate', self.x.head_dir / 'RobotExpressiveHead.gltf', FIX / 'head.annotations.json',
                                           '--resolver-root', self.x.head_dir, '--output', output)
            self.assertEqual((code, stdout, stderr), (0, b'', (FIX / 'success.report.prospective.json').read_bytes()))
            self.assertEqual(output.read_bytes(), self.x.sidecar_bytes)

    def case_CLI_GEOMETRY(self):
        code, stdout, stderr = cli_run('geometry', self.x.fox_dir / 'Fox.gltf', '--resolver-root', self.x.fox_dir, '--time', '0.137',
                                       '--animation', '0')
        self.assertEqual((code, stderr), (0, (FIX / 'success.report.prospective.json').read_bytes()))
        tolerance = self.x.expect['Fox']['POSITION_mesh_local_and_world']
        case = self.x.oracle('Fox')['cases'][2]
        close(self, json.loads(stdout)['instances'][0]['primitives'][0]['positions'],
              case['geometry']['instances'][0]['primitives'][0]['positions'], tolerance['absolute'], tolerance['relative'])

    def case_CLI_MAP(self):
        code, stdout, stderr = cli_run('map', FIX / 'head.authoring.toml', MAPPING, '--source-profile', 'ren.real09K.head.source',
                                       '--target-asset', self.x.head_dir / 'RobotExpressiveHead.gltf',
                                       '--target-sidecar', FIX / 'head.sidecar.prospective.json', '--resolver-root', self.x.head_dir)
        self.assertEqual((code, stdout, stderr), (0, (FIX / 'head.mapping.prospective.json').read_bytes(),
                                                  (FIX / 'success.report.prospective.json').read_bytes()))

    def case_CLI_EVALUATE(self):
        code, stdout, stderr = cli_run('evaluate', FIX / 'head.authoring.toml', MAPPING, FIX / 'head.samples.json',
                                       '--source-profile', 'ren.real09K.head.source',
                                       '--target-asset', self.x.head_dir / 'RobotExpressiveHead.gltf',
                                       '--target-sidecar', FIX / 'head.sidecar.prospective.json', '--resolver-root', self.x.head_dir)
        self.assertEqual((code, stdout, stderr), (0, (FIX / 'head.evaluated.prospective.json').read_bytes(),
                                                  (FIX / 'success.report.prospective.json').read_bytes()))

    def case_CLI_COMPLEMENTARY_VARIANTS(self):
        robot = ASSETS / 'RobotExpressive' / 'RobotExpressive.glb'
        code, stdout, stderr = cli_run('inspect', robot)
        self.assertEqual((code, stdout, json.loads(stderr)), (1, b'', negative_report('R-RAW-REFUSAL')['expected_report']))
        code, _, stderr = cli_run('map', FIX / 'head.authoring.toml', MAPPING, '--source-profile', 'ren.real09K.head.source',
                                  '--target-asset', self.x.head_dir / 'RobotExpressiveHead.gltf', '--resolver-root', self.x.head_dir)
        self.assertEqual((code, [(d['code'], d['ref']) for d in json.loads(stderr)['diagnostics']]), (1, [('E_BINDING_REQUIRED', '/target')]))
        code, _, stderr = cli_run('map', FIX / 'head.authoring.toml', MAPPING, '--source-profile', 'x', '--source-asset', robot,
                                  '--target-profile', 'ren.real09K.head.target')
        report, _ = json.JSONDecoder().raw_decode(stderr.decode())
        self.assertEqual((code, [d['code'] for d in report['diagnostics']]), (1, ['E_CLI_ARGUMENT']))
        self.assertIn(b'usage: msf-tools map', stderr)
        with tempfile.TemporaryDirectory() as tmp:
            impossible = Path(tmp) / 'annotations.json'
            binding = json.loads(self.x.sidecar_bytes)['bindings'][0]
            binding['ref'] = {'asset_sha256': hashlib.sha256(self.x.fox_raw).hexdigest(), 'locator': '/nodes/1/weights/0', 'mesh': 0,
                              'node': 1, 'resource_sha256': hashlib.sha256((self.x.fox_dir / 'Fox.bin').read_bytes()).hexdigest(),
                              'target': 0}
            impossible.write_text(json.dumps({'bindings': [binding], 'metadata': {}}))
            code, _, stderr = cli_run('annotate', self.x.fox_dir / 'Fox.gltf', impossible, '--resolver-root', self.x.fox_dir,
                                      '--output', Path(tmp) / 'out.json')
        self.assertEqual((code, json.loads(stderr)['diagnostics'][0]['code']), (1, 'E_BINDING_REFERENCE'))


def _case_test(case_id):
    method = 'case_' + case_id.replace('-', '_')

    def test(self):
        if case_id in SKIPPED:
            self.skipTest(SKIPPED[case_id])
        getattr(self, method)()
    return test


if PRESENT:
    for _case in load(PLAN / 'CASE_MATRIX.json')['cases']:
        setattr(RealAssetRecipes, 'test_' + _case['id'].replace('-', '_'), _case_test(_case['id']))


@unittest.skipUnless(PRESENT, 'set MSF_REAL_ASSETS to a local copy of the 09K harness inputs to run this tier')
class CaseAccounting(unittest.TestCase):
    def test_every_case_runs_or_says_why_not(self):
        ids = [c['id'] for c in load(PLAN / 'CASE_MATRIX.json')['cases']]
        self.assertEqual(len(ids), 57)
        missing = [i for i in ids if i not in SKIPPED and not hasattr(RealAssetRecipes, 'case_' + i.replace('-', '_'))]
        self.assertEqual(missing, [])
        self.assertEqual([i for i in SKIPPED if i not in ids], [])


if __name__ == '__main__':
    unittest.main()
