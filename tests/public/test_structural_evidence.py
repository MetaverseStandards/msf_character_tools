# SPDX-License-Identifier: MIT
"""Independent storage/arithmetic admission cases; no physiological oracle."""
import copy
import json
from pathlib import Path
import unittest

import msf_tools as m

ROOT = Path(__file__).resolve().parents[2]
assert Path(m.__file__).resolve().parent.parent == ROOT
C, P, U = 'verified_current', 'proposed', 'unresolved'

# Literal truth table from the corrected RCEF design, not compiler output.
# Offenders appear in declaration order: rule, input, output.
ST = (
    (C, C, C, ()), (C, C, P, ('out',)), (C, C, U, ('out',)),
    (C, P, C, ('in',)), (C, P, P, ('in', 'out')),
    (C, P, U, ('in', 'out')), (C, U, C, ('in',)),
    (C, U, P, ('in', 'out')), (C, U, U, ('in', 'out')),
    (P, C, C, ()), (P, C, P, ()), (P, C, U, ('out',)),
    (P, P, C, ()), (P, P, P, ()), (P, P, U, ('out',)),
    (P, U, C, ('in',)), (P, U, P, ('in',)),
    (P, U, U, ('in', 'out')), (U, C, C, ('copy',)),
    (U, C, P, ('copy',)), (U, C, U, ('copy', 'out')),
    (U, P, C, ('copy',)), (U, P, P, ('copy',)),
    (U, P, U, ('copy', 'out')), (U, U, C, ('copy', 'in')),
    (U, U, P, ('copy', 'in')), (U, U, U, ('copy', 'in', 'out')),
)
# Own status, own refs' statuses, exact diagnostics (record ref added below).
RF = (
    (C, (C,), ()),
    (C, (C, P), ('E_EVIDENCE_COMPATIBILITY',)),
    (C, (C, U), ('E_EVIDENCE_COMPATIBILITY',)),
    (C, (), ('E_EVIDENCE_REQUIRED',)),
    (P, (C,), ()), (P, (C, P), ()),
    (P, (C, U), ('E_EVIDENCE_COMPATIBILITY',)),
    (P, (), ('E_EVIDENCE_REQUIRED',)),
    (U, (C,), ('E_EVIDENCE_STATUS',)),
    (U, (C, P), ('E_EVIDENCE_STATUS',)),
    (U, (C, U), ('E_EVIDENCE_STATUS', 'E_EVIDENCE_COMPATIBILITY')),
    (U, (), ('E_EVIDENCE_STATUS', 'E_EVIDENCE_REQUIRED')),
)


def evidence(eid='good', status=C):
    return {'id': eid, 'claim': 'Original scalar storage definition only.',
            'status': status, 'license': 'MIT', 'authorship': 'MSF Tools contributors'}


def signal(sid):
    return {'id': sid, 'label': sid, 'value_type': 'scalar', 'units': '1',
            'domain': {'min': 0, 'max': 1}, 'calibration': 'original.storage.v1',
            'disposition': 'mapped', 'evidence_status': C, 'evidence': ['good']}


def rule(rid, inputs, output, operator=None):
    return {'id': rid, 'inputs': inputs, 'outputs': [output],
            'operator': operator or {'id': 'identity'}, 'disposition': 'mapped',
            'mapping_quality': 'exact', 'assumptions': [], 'evidence': ['good'],
            'evidence_status': C, 'loss_annotations': []}


def document():
    return {'schema_version': '1.0', 'operator_version': '1.0',
            'data_version': '0.1.0', 'id': 'original.storage', 'license': 'MIT',
            'signals': [signal('in'), signal('out')], 'evidence': [evidence()],
            'profiles': [{'id': 'source', 'label': 'Source', 'signal_ids': ['in']},
                         {'id': 'target', 'label': 'Target', 'signal_ids': ['out']}],
            'mappings': [{'id': 'map', 'rules': [rule('copy', ['in'], 'out')]}]}


def record(doc, location):
    return {'rule': doc['mappings'][0]['rules'][0],
            'source': doc['signals'][0], 'target': doc['signals'][1]}[location]


def chain():
    d = document()
    d['signals'] = [signal(s) for s in ('a', 'b', 'mid', 'out')]
    d['profiles'][0]['signal_ids'] = ['a', 'b']
    d['mappings'][0]['rules'] = [
        rule('last', ['mid', 'b'], 'out', {'id': 'weighted_sum', 'weights': [.5, .5]}),
        rule('first', ['a'], 'mid')]
    return d


def affine():
    d = document()
    d['signals'] = [signal('fixture.affine.signed'), signal('fixture.affine.unit')]
    d['signals'][0].update(domain={'min': -1., 'max': 1.}, calibration='fixture.signed.v1')
    d['signals'][1]['calibration'] = 'fixture.unit.v1'
    for s in d['signals']:
        s.update(side='shared', evidence=['rcef_definitions'])
    d['evidence'] = [evidence('rcef_definitions')]
    d['profiles'][0]['signal_ids'] = ['fixture.affine.signed']
    d['profiles'][1]['signal_ids'] = ['fixture.affine.unit']
    r = rule('fixture.affine.convert', ['fixture.affine.signed'], 'fixture.affine.unit',
             {'id': 'affine', 'scale': .5, 'offset': .5})
    r.update(evidence=['rcef_definitions'], assumptions=[
        'Original fixture states matching low/mid/high at -1/0/1 and 0/0.5/1; explicit basis conversion.'])
    d['mappings'][0]['rules'] = [r]
    return d


BILATERAL_LOSSES = [
    {'category': 'signal', 'effect': 'approximated', 'reason': 'asymmetry irrecoverable',
     'refs': ['fixture.brow.left', 'fixture.brow.right', 'fixture.brow.shared'], 'units': '1'},
    {'category': 'geometry', 'effect': 'unknown', 'reason': 'No geometry evaluated by scalar fixture.',
     'refs': ['fixture.brow.shared']},
]


def bilateral():
    d = document()
    d['signals'] = [signal(s) for s in ('fixture.brow.left', 'fixture.brow.right', 'fixture.brow.shared')]
    for s in d['signals']:
        s.update(side='shared', calibration='fixture.brow.v1', evidence=['rcef_definitions'])
    d['signals'][2]['coupling'] = 'bilateral_shared'
    d['evidence'] = [evidence('rcef_definitions')]
    d['profiles'][0]['signal_ids'] = ['fixture.brow.left', 'fixture.brow.right']
    d['profiles'][1]['signal_ids'] = ['fixture.brow.shared']
    r = rule('fixture.brow.collapse', ['fixture.brow.left', 'fixture.brow.right'],
             'fixture.brow.shared', {'id': 'weighted_sum', 'weights': [.5, .5]})
    r.update(mapping_quality='approximate', coupling='bilateral_shared',
             evidence=['rcef_definitions'], assumptions=[
                 'Original synthetic channels share a declared normalized scale; arithmetic mean chosen for this fixture only.'],
             loss_annotations=copy.deepcopy(BILATERAL_LOSSES))
    d['mappings'][0]['rules'] = [r]
    return d


class Checks(unittest.TestCase):
    def good(self, result):
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def packed(self, doc):
        original = copy.deepcopy(doc)
        validated = self.good(m.validate_authoring(doc))
        self.assertEqual(validated.to_dict(), original)
        pack = self.good(m.compile_pack(validated))
        self.assertEqual(pack.to_dict(), original)
        self.assertEqual(doc, original)
        return pack

    def compile(self, doc, opt=False, source='source', target='target', mapping='map'):
        pack = self.packed(doc)
        # Every mutation gets new pack-bound snapshots, never a stale baseline.
        src = self.good(m.profile_snapshot(pack, source))
        dst = self.good(m.profile_snapshot(pack, target))
        result = m.compile_mapping(pack, src, dst, mapping, allow_approximation=opt)
        self.assertEqual(pack.to_dict(), doc)
        return result

    def refused(self, result, expected):
        self.assertIsNone(result.value)
        self.assertFalse(result.ok)
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], expected)
        self.assertTrue(all(d.severity == 'error' for d in result.report.diagnostics))

    def evaluate(self, compiled, inputs, output, expected):
        frames = [{'timestamp': .125, 'values': x, 'validity': dict.fromkeys(x, True)} for x in inputs]
        evaluation = m.evaluate_mapping(compiled, frames)
        result = self.good(evaluation)
        self.assertEqual(result.to_dict()['samples'], [
            {'timestamp': .125, 'values': {output: y}, 'validity': {output: True}} for y in expected])
        self.assertEqual(result.to_dict()['samples'][0]['timestamp'], .125)
        self.assertEqual(evaluation.report.to_dict()['losses'], compiled.to_dict()['losses'])


class EvidenceAdmission(Checks):
    def test_all_27_status_combinations(self):
        self.assertEqual(len(ST), 27)
        self.assertEqual(sum(not x[3] for x in ST), 5)
        for i, (rs, ss, ts, offenders) in enumerate(ST, 1):
            with self.subTest(case=f'ST-{i:02}', statuses=(rs, ss, ts)):
                d = document()
                record(d, 'rule')['evidence_status'] = rs
                record(d, 'source')['evidence_status'] = ss
                record(d, 'target')['evidence_status'] = ts
                result = self.compile(d)
                if offenders:
                    self.refused(result, [('E_EVIDENCE_STATUS', x) for x in offenders])
                else:
                    c = self.good(result)
                    self.assertEqual(c.to_dict()['instructions'], d['mappings'][0]['rules'])
                    self.assertEqual(c.pack.to_dict()['signals'], d['signals'])
                    self.evaluate(c, [{'in': .25}], 'out', [.25])

    def test_12_reference_rows_at_each_of_three_locations(self):
        for location in ('rule', 'source', 'target'):
            for i, (status, refs, codes) in enumerate(RF, 1):
                with self.subTest(case=f'RF-{i:02}', location=location):
                    d = document()
                    rec = record(d, location)
                    rec['evidence_status'] = status
                    if location != 'rule':
                        record(d, 'rule')['evidence_status'] = C if status == C else P
                    rec['evidence'] = [f'ref{j}' for j in range(len(refs))]
                    d['evidence'] += [evidence(f'ref{j}', s) for j, s in enumerate(refs)]
                    result = self.compile(d, True)
                    if codes:
                        self.refused(result, [(c, rec['id']) for c in codes])
                    else:
                        c = self.good(result)
                        self.assertEqual(c.to_dict()['instructions'], d['mappings'][0]['rules'])
                        self.evaluate(c, [{'in': .25}], 'out', [.25])

    def test_12_mixed_reference_negatives_with_both_positive_controls(self):
        case = 0
        for location in ('rule', 'source', 'target'):
            for bad_status in (P, U):
                for refs in (['design02.test.good', 'design02.test.bad'],
                             ['design02.test.bad', 'design02.test.good']):
                    case += 1
                    for control in ('negative', 'all_current', 'unreferenced_bad'):
                        with self.subTest(case=f'MR-{case:02}', control=control):
                            d = document()
                            rec = record(d, location)
                            d['evidence'] += [evidence('design02.test.good'),
                                             evidence('design02.test.bad', C if control == 'all_current' else bad_status)]
                            rec['evidence'] = list(refs) if control != 'unreferenced_bad' else ['design02.test.good']
                            result = self.compile(d)
                            if control == 'negative':
                                self.refused(result, [('E_EVIDENCE_COMPATIBILITY', rec['id'])])
                                diag = result.report.diagnostics[0]
                                kind = 'Rule' if location == 'rule' else 'Signal'
                                self.assertEqual(diag.message, f'{kind} {rec["id"]} includes evidence design02.test.bad with status {bad_status}, incompatible with its evidence_status verified_current.')
                                self.assertEqual(diag.remediation, 'Correct the referenced input.')
                            else:
                                self.evaluate(self.good(result), [{'in': .25}], 'out', [.25])
        self.assertEqual(case, 12)

    def test_current_endpoints_keep_all_current_requirement_under_proposed_rule(self):
        for location in ('source', 'target'):
            for bad in (P, U):
                with self.subTest(location=location, bad=bad):
                    d = document()
                    record(d, 'rule')['evidence_status'] = P
                    d['evidence'].append(evidence('bad', bad))
                    record(d, location)['evidence'].append('bad')
                    self.refused(self.compile(d, True), [('E_EVIDENCE_COMPATIBILITY', record(d, location)['id'])])

    def test_every_bad_reference_reported_in_authored_order(self):
        for location in ('rule', 'source', 'target'):
            for refs in (['p', 'good', 'u'], ['u', 'good', 'p'], ['p', 'u']):
                with self.subTest(location=location, refs=refs):
                    d = document()
                    d['evidence'] += [evidence('p', P), evidence('u', U)]
                    rec = record(d, location)
                    rec['evidence'] = refs
                    result = self.compile(d)
                    self.refused(result, [('E_EVIDENCE_COMPATIBILITY', rec['id'])] * 2)
                    bad_ids = [x for x in refs if x != 'good']
                    for diag, eid in zip(result.report.diagnostics, bad_ids):
                        self.assertIn(f'includes evidence {eid} ', diag.message)

    def test_unused_status_inventory_and_unselected_mapping_remain_allowed(self):
        d = document()
        for status in (P, U):
            s = signal('unused.' + status)
            s.update(evidence_status=status, evidence=[])
            d['signals'].append(s)
            d['evidence'].append(evidence('unused.ref.' + status, status))
        r = rule('unused.rule', ['in'], 'out')
        r.update(evidence_status=U, evidence=[])
        d['mappings'].append({'id': 'unselected', 'rules': [r]})
        self.evaluate(self.good(self.compile(d)), [{'in': .25}], 'out', [.25])

    def test_structural_unknown_missing_and_invalid_status_diagnostics(self):
        for location, path in (('rule', '/mappings/0/rules/0'), ('source', '/signals/0'),
                               ('target', '/signals/1'), ('evidence', '/evidence/0')):
            for mutation, code in (('missing', 'E_REQUIRED'), ('invalid', 'E_ENUM')):
                with self.subTest(location=location, mutation=mutation):
                    d = document()
                    rec = d['evidence'][0] if location == 'evidence' else record(d, location)
                    key = 'status' if location == 'evidence' else 'evidence_status'
                    if mutation == 'missing': del rec[key]
                    else: rec[key] = 'certified'
                    self.refused(m.validate_authoring(d), [(code, path)])
        for location, path in (('rule', '/rules/copy/evidence'), ('source', '/signals/in'),
                               ('target', '/signals/out')):
            with self.subTest(location=location, mutation='unknown'):
                d = document()
                record(d, location)['evidence'] = ['unknown']
                self.refused(m.validate_authoring(d), [('E_REFERENCE', path)])

    def test_multi_cause_diagnostic_order_and_exact_status_messages(self):
        d = document()
        record(d, 'rule')['evidence'] = []
        record(d, 'source').update(evidence_status=P, evidence=['bad'])
        record(d, 'target').update(evidence_status=U, evidence=[])
        d['evidence'].append(evidence('bad', U))
        result = self.compile(d, True)
        self.refused(result, [('E_EVIDENCE_REQUIRED', 'copy'), ('E_EVIDENCE_STATUS', 'in'),
                              ('E_EVIDENCE_COMPATIBILITY', 'in'), ('E_EVIDENCE_STATUS', 'out'),
                              ('E_EVIDENCE_REQUIRED', 'out')])
        self.assertEqual(result.report.diagnostics[1].message,
                         'Signal in has evidence_status proposed, incompatible with rule copy (verified_current).')
        self.assertEqual(result.report.diagnostics[3].message,
                         'Signal out has evidence_status unresolved, incompatible with rule copy (verified_current).')

    def test_chain_intermediates_and_each_input_checked_in_isolation(self):
        for sid, expected in (('a', ['a']), ('b', ['b']), ('mid', ['mid', 'mid']), ('out', ['out'])):
            for status in (P, U):
                with self.subTest(signal=sid, status=status):
                    d = chain()
                    next(s for s in d['signals'] if s['id'] == sid)['evidence_status'] = status
                    result = self.compile(d)
                    self.refused(result, [('E_EVIDENCE_STATUS', x) for x in expected])
                    if sid == 'mid':
                        self.assertIn('rule last ', result.report.diagnostics[0].message)
                        self.assertIn('rule first ', result.report.diagnostics[1].message)

    def test_chain_own_reference_and_zero_weight_input_isolation(self):
        for sid, refs in (('a', ['a']), ('b', ['b']), ('mid', ['mid', 'mid']), ('out', ['out'])):
            with self.subTest(signal=sid):
                d = chain()
                d['evidence'].append(evidence('bad', U))
                next(s for s in d['signals'] if s['id'] == sid)['evidence'] = ['good', 'bad']
                result = self.compile(d)
                self.refused(result, [('E_EVIDENCE_COMPATIBILITY', x) for x in refs])
                self.assertTrue(all('includes evidence bad ' in x.message for x in result.report.diagnostics))
        d = chain()
        d['mappings'][0]['rules'][0]['operator']['weights'] = [1, 0]
        d['signals'][1]['evidence_status'] = U
        self.refused(self.compile(d), [('E_EVIDENCE_STATUS', 'b')])

    def test_proposed_chain_and_rule_boundary_preserve_waves_and_statuses(self):
        d = chain()
        for s in d['signals']: s['evidence_status'] = P
        for r in d['mappings'][0]['rules']: r['evidence_status'] = P
        c = self.good(self.compile(d))
        self.assertEqual([r['id'] for r in c.instructions], ['first', 'last'])
        self.assertEqual(c.required_inputs, ('b', 'a'))
        self.assertEqual(c.output_ids, ('out',))
        self.evaluate(c, [{'a': .25, 'b': .75}], 'out', [.5])
        d['mappings'][0]['rules'][0]['evidence_status'] = C
        self.refused(self.compile(d), [('E_EVIDENCE_STATUS', 'mid'), ('E_EVIDENCE_STATUS', 'b'),
                                      ('E_EVIDENCE_STATUS', 'out')])


class IdentityAdmission(Checks):
    def test_presence_and_value_for_each_identity_field(self):
        for field, a, b, code in (
            ('neutral', 0, 1, 'E_NEUTRAL_COMPATIBILITY'),
            ('side', 'left', 'right', 'E_SIDE_COMPATIBILITY'),
            ('coupling', 'bilateral_shared', 'opposing_direction_exclusive', 'E_COUPLING_COMPATIBILITY')):
            for mode in ('value', 'missing_source', 'missing_target'):
                with self.subTest(field=field, mode=mode):
                    d = document()
                    if mode != 'missing_source': d['signals'][0][field] = a
                    if mode != 'missing_target': d['signals'][1][field] = b if mode == 'value' else a
                    result = self.compile(d)
                    self.refused(result, [(code, 'copy')])
                    self.assertEqual(result.report.diagnostics[0].message,
                                     f'Identity requires equal presence and value of {field} on in and out.')

    def test_absence_equal_values_and_native_default_are_distinct(self):
        for fields in ({}, {'neutral': 0, 'side': 'left', 'coupling': 'bilateral_shared'},
                       {'coupling': []}, {'coupling': ['bilateral_shared', 'other']}):
            with self.subTest(fields=fields):
                d = document()
                for s in d['signals']: s.update(copy.deepcopy(fields))
                d['signals'][0]['native_default'] = 1
                c = self.good(self.compile(d))
                self.assertNotIn('neutral', c.source_snapshot.channels['in'])
                self.evaluate(c, [{'in': .25}], 'out', [.25])
        d = document()
        d['signals'][1]['coupling'] = []
        self.refused(self.compile(d), [('E_COUPLING_COMPATIBILITY', 'copy')])

    def test_null_never_becomes_absence_or_default(self):
        for field in ('neutral', 'side', 'coupling'):
            for index in (0, 1):
                with self.subTest(field=field, index=index):
                    d = document()
                    d['signals'][index][field] = None
                    self.refused(m.validate_authoring(d), [('E_TYPE', f'/signals/{index}/{field}')])

    def test_existing_identity_checks_and_new_metadata_order(self):
        d = document()
        d['signals'][0].update(neutral=0, side='left', coupling='bilateral_shared')
        d['signals'][1].update(units='mm', calibration='other', domain={'min': 0, 'max': 2},
                               neutral=1, side='right', coupling='opposing_direction_exclusive')
        self.refused(self.compile(d), [(x, 'copy') for x in (
            'E_UNITS', 'E_CALIBRATION', 'E_DOMAIN_COMPATIBILITY',
            'E_NEUTRAL_COMPATIBILITY', 'E_SIDE_COMPATIBILITY', 'E_COUPLING_COMPATIBILITY')])


class DerivationAdmission(Checks):
    def test_signed_exact_affine_retains_conversion_and_no_losses(self):
        d = affine()
        c = self.good(self.compile(d))
        self.assertEqual(c.to_dict()['instructions'], d['mappings'][0]['rules'])
        self.assertEqual(c.to_dict()['losses'], [])
        self.evaluate(c, [{'fixture.affine.signed': x} for x in (-1, 0, 1)],
                      'fixture.affine.unit', [0, .5, 1])

    def test_bilateral_mean_opt_in_preserves_both_exact_authored_losses(self):
        d = bilateral()
        self.refused(self.compile(d), [('E_APPROXIMATION', 'fixture.brow.collapse')] * 3)
        c = self.good(self.compile(d, True))
        self.assertEqual(c.to_dict()['losses'], BILATERAL_LOSSES)
        pairs = [(1, 0), (0, 1), (0, 0), (1, 1), (.25, .75)]
        self.evaluate(c, [{'fixture.brow.left': a, 'fixture.brow.right': b} for a, b in pairs],
                      'fixture.brow.shared', [.5, .5, 0, 1, .5])

    def test_removed_losses_refuse_even_with_opt_in_and_no_generic_loss(self):
        for kind in ('identity', 'bilateral'):
            for opt in (False, True):
                with self.subTest(kind=kind, opt=opt):
                    d = bilateral() if kind == 'bilateral' else document()
                    r = d['mappings'][0]['rules'][0]
                    r.update(mapping_quality='approximate', loss_annotations=[])
                    result = self.compile(d, opt)
                    expected = [] if opt else [('E_APPROXIMATION', r['id'])]
                    self.refused(result, expected + [('E_LOSS_REQUIRED', r['id'])])
                    self.assertEqual(result.report.losses, ())

    def test_missing_required_derivation_refuses_without_changing_inventory(self):
        for name, make in (('affine', affine), ('bilateral', bilateral)):
            with self.subTest(kind=name):
                d = make()
                r = d['mappings'][0]['rules'][0]
                r['assumptions'] = []
                self.refused(self.compile(d, True), [('E_DERIVATION_ASSUMPTIONS', r['id'])])

    def test_quality_only_and_target_basis_only_changes_keep_numerical_scope(self):
        for mutation in ('quality', 'basis'):
            with self.subTest(mutation=mutation):
                d = bilateral()
                r = d['mappings'][0]['rules'][0]
                if mutation == 'quality': r['mapping_quality'] = 'exact'
                else: d['signals'][2]['calibration'] = 'incompatible-target-calibration'
                expected = [('E_APPROXIMATION', 'fixture.brow.collapse')] * (2 if mutation == 'quality' else 3)
                self.refused(self.compile(d), expected)
                c = self.good(self.compile(d, True))
                self.assertEqual(c.to_dict()['losses'], BILATERAL_LOSSES)
                self.assertEqual(c.to_dict()['instructions'], d['mappings'][0]['rules'])
                self.evaluate(c, [{'fixture.brow.left': 1, 'fixture.brow.right': 0}], 'fixture.brow.shared', [.5])
                # Domain reviewer must reject unsupported equivalence; this
                # storage test intentionally has no entailment-checking API.

    def test_exact_same_basis_empty_assumptions_remain_qualified_arithmetic(self):
        for op, expected in (({'id': 'affine', 'scale': 2, 'offset': .25}, .75),
                             ({'id': 'weighted_sum', 'weights': [2]}, .5)):
            with self.subTest(op=op):
                d = document()
                d['mappings'][0]['rules'][0]['operator'] = op
                # Different bounds and semantic metadata are legal nonidentity
                # declarations; equality guards belong to identity only.
                d['signals'][0].update(neutral=0, side='left', coupling='bilateral_shared')
                d['signals'][1].update(domain={'min': -1, 'max': 2}, neutral=1, side='right')
                self.evaluate(self.good(self.compile(d)), [{'in': .25}], 'out', [expected])
        d = chain()
        self.evaluate(self.good(self.compile(d)), [{'a': .25, 'b': .75}], 'out', [.5])

    def test_differing_input_basis_units_and_declared_loss_require_derivation(self):
        for cause in ('input_basis', 'target_basis', 'units', 'approximate', 'loss'):
            with self.subTest(cause=cause):
                d = chain()
                r = d['mappings'][0]['rules'][0]
                if cause == 'input_basis': d['signals'][1]['calibration'] = 'other.input'
                elif cause == 'target_basis': d['signals'][3]['calibration'] = 'other.target'
                elif cause == 'units': d['signals'][3]['units'] = 'mm'
                elif cause == 'approximate': r['mapping_quality'] = 'approximate'
                if cause in ('approximate', 'loss'):
                    r['loss_annotations'] = [{'category': 'signal', 'effect': 'unknown',
                                              'reason': 'Declared uncertainty.', 'refs': ['out']}]
                expected = [('E_UNITS', 'last')] if cause == 'units' else []
                self.refused(self.compile(d, True), expected + [('E_DERIVATION_ASSUMPTIONS', 'last')])
                r['assumptions'] = ['Original explicit numeric derivation only.']
                if cause != 'units': self.good(self.compile(d, True))
        # Unit conversion retains the existing affine-only rule.
        d = document()
        d['signals'][1]['units'] = 'mm'
        r = d['mappings'][0]['rules'][0]
        r['operator'] = {'id': 'affine', 'scale': 1, 'offset': 0}
        self.refused(self.compile(d), [('E_UNITS', 'copy'), ('E_DERIVATION_ASSUMPTIONS', 'copy')])
        r['assumptions'] = ['Synthetic explicit unit conversion.']
        self.evaluate(self.good(self.compile(d)), [{'in': .25}], 'out', [.25])

    def test_proposed_mixed_basis_literal_composite_and_current_rule_promotion(self):
        d = json.loads((ROOT / 'tests/public/fixtures/h6-proposed-composite.json').read_text())
        result = self.compile(d, False, 'synthetic.source', 'synthetic.target', 'synthetic.mix')
        self.refused(result, [('E_APPROXIMATION', 'synthetic.mix.weighted')] * 3)
        c = self.good(self.compile(d, True, 'synthetic.source', 'synthetic.target', 'synthetic.mix'))
        self.assertEqual(c.to_dict()['instructions'], d['mappings'][0]['rules'])
        self.assertEqual(c.to_dict()['losses'], d['mappings'][0]['rules'][0]['loss_annotations'])
        self.assertEqual([s['evidence_status'] for s in c.pack.to_dict()['signals']], [P, P, P])
        self.evaluate(c, [{'synthetic.open': a, 'synthetic.wide': b}
                          for a, b in ((.25, .75), (.75, .25), (0, 1), (1, 0))],
                      'synthetic.lid', [.375, .625, .25, .75])
        d['mappings'][0]['rules'][0]['evidence_status'] = C
        self.refused(self.compile(d, True, 'synthetic.source', 'synthetic.target', 'synthetic.mix'), [
            ('E_EVIDENCE_COMPATIBILITY', 'synthetic.mix.weighted'),
            ('E_EVIDENCE_STATUS', 'synthetic.open'), ('E_EVIDENCE_STATUS', 'synthetic.wide'),
            ('E_EVIDENCE_STATUS', 'synthetic.lid')])


class SchemaInventory(Checks):
    def test_schema_and_runtime_keep_execution_incompatible_inventory(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('Optional jsonschema test tool is not installed.')
        validators = [Draft202012Validator(json.loads((ROOT / f'schemas/{s}.schema.json').read_text()))
                      for s in ('authoring', 'pack')]
        for i, (rs, ss, ts, _) in enumerate(ST, 1):
            for empty in (False, True):
                with self.subTest(case=f'ST-{i:02}', empty=empty):
                    d = document()
                    for loc, status in (('rule', rs), ('source', ss), ('target', ts)):
                        record(d, loc)['evidence_status'] = status
                        if empty: record(d, loc)['evidence'] = []
                    for v in validators: self.assertEqual(list(v.iter_errors(d)), [])
                    self.packed(d)
        for location in ('rule', 'source', 'target'):
            for mutation in ('missing', 'invalid'):
                with self.subTest(location=location, mutation=mutation):
                    d = document()
                    rec = record(d, location)
                    if mutation == 'missing': del rec['evidence_status']
                    else: rec['evidence_status'] = 'certified'
                    for v in validators: self.assertTrue(list(v.iter_errors(d)))
                    self.assertIsNone(m.validate_authoring(d).value)
