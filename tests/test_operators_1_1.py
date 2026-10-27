# SPDX-License-Identifier: MIT
"""Operators 1.1 (piecewise_linear) and authoring 1.1 (calibrated_software), through the public API."""
import copy
from fractions import Fraction
import itertools
import math
import random
import unittest

import msf_tools as m

C, P, U, K = 'verified_current', 'proposed', 'unresolved', 'calibrated_software'
SPLIT_NEGATIVE = [[-1, 1], [0, 0], [1, 0]]
SPLIT_POSITIVE = [[-1, 0], [0, 0], [1, 1]]


def signal(sid, low=0, high=1):
    return {'id': sid, 'label': sid, 'value_type': 'scalar', 'units': '1', 'domain': {'min': low, 'max': high},
            'calibration': 'fixture.v1', 'disposition': 'mapped', 'evidence_status': C, 'evidence': ['e']}


def rule(rid, inputs, output, operator):
    return {'id': rid, 'inputs': inputs, 'outputs': [output], 'operator': operator, 'disposition': 'mapped',
            'mapping_quality': 'exact', 'assumptions': [], 'evidence': ['e'], 'evidence_status': C,
            'loss_annotations': []}


def piecewise(knots):
    return {'id': 'piecewise_linear', 'knots': knots}


def document(knots=None, low=-1, high=1, out_low=0, out_high=1, schema='1.1', operators='1.1'):
    """One piecewise_linear rule from `in` to `out`."""
    return {'schema_version': schema, 'operator_version': operators, 'data_version': '0.1.0', 'id': 'ops', 'license': 'MIT',
            'signals': [signal('in', low, high), signal('out', out_low, out_high)],
            'evidence': [{'id': 'e', 'claim': 'Original fixture.', 'status': C, 'license': 'MIT', 'authorship': 'MSF Tools contributors'}],
            'profiles': [{'id': 'source', 'label': 'Source', 'signal_ids': ['in']},
                         {'id': 'target', 'label': 'Target', 'signal_ids': ['out']}],
            'mappings': [{'id': 'map', 'rules': [rule('r', ['in'], 'out', piecewise(SPLIT_POSITIVE if knots is None else knots))]}]}


def gaze():
    """weighted_sum (in - out) feeding two one-sided splits."""
    d = document()
    d['signals'] = [signal('look_in'), signal('look_out'), signal('gaze', -1, 1), signal('toward_in'), signal('toward_out')]
    d['profiles'][0]['signal_ids'] = ['look_in', 'look_out']
    d['profiles'][1]['signal_ids'] = ['toward_in', 'toward_out']
    d['mappings'][0]['rules'] = [
        rule('difference', ['look_in', 'look_out'], 'gaze', {'id': 'weighted_sum', 'weights': [1, -1]}),
        rule('toward_out', ['gaze'], 'toward_out', piecewise(SPLIT_NEGATIVE)),
        rule('toward_in', ['gaze'], 'toward_in', piecewise(SPLIT_POSITIVE))]
    return d


def errors(result):
    return [(d.code, d.ref) for d in result.report.diagnostics]


def ulps(value):
    return math.ulp(abs(value)) if value else math.ulp(0.0)


class Checks(unittest.TestCase):
    def good(self, result):
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def compile(self, doc):
        pack = self.good(m.compile_pack(self.good(m.validate_authoring(doc))))
        return m.compile_mapping(pack, self.good(m.profile_snapshot(pack, 'source')),
                                 self.good(m.profile_snapshot(pack, 'target')), 'map')

    def run_frames(self, compiled, frames):
        samples = [{'timestamp': 0, 'values': f, 'validity': dict.fromkeys(f, True)} for f in frames]
        return [s['values'] for s in self.good(m.evaluate_mapping(compiled, samples)).to_dict()['samples']]

    def outputs(self, knots, xs, **kwargs):
        compiled = self.good(self.compile(document(knots, knots[0][0], knots[-1][0], **kwargs)))
        return [v['out'] for v in self.run_frames(compiled, [{'in': x} for x in xs])]


class PiecewiseLinearAuthoring(Checks):
    def test_knots_round_trip_into_the_pack(self):
        doc = document([[-1, 0.25], [0.5, 0.5], [1, 0.75]])
        pack = self.good(m.compile_pack(self.good(m.validate_authoring(copy.deepcopy(doc)))))
        self.assertEqual(pack.to_dict(), doc)

    def test_malformed_knots_are_type_errors(self):
        for knots in ({'x': 1}, 'knots', [], [[-1, 0]], [[-1, 0], [1]], [[-1, 0], [1, 1, 1]], [[-1, 0], [1, '1']],
                      [[-1, 0], [1, True]], [[-1, 0], (1, 1), 3]):
            with self.subTest(knots=knots):
                self.assertEqual(errors(m.validate_authoring(document(knots))), [('E_TYPE', '/mappings/0/rules/0')])

    def test_x_must_increase_strictly_and_y_must_be_monotone(self):
        for knots in ([[-1, 0], [-1, 1], [1, 1]], [[-1, 0], [1, 1], [0, 1]], [[-1, 0], [0, 1], [1, 0]],
                      [[-1, 1], [0, 0], [0.5, 0.5], [1, 0]], [[-1e308, 0], [1e308, 1]], [[-1, -1e308], [1, 1e308]]):
            with self.subTest(knots=knots):
                self.assertEqual(errors(m.validate_authoring(document(knots))), [('E_KNOTS', '/mappings/0/rules/0')])
        for knots in ([[-1, 1], [1, 0]], [[-1, 0.5], [1, 0.5]], SPLIT_NEGATIVE, SPLIT_POSITIVE, [[-1, 0], [1e-300, 0], [1, 1]]):
            with self.subTest(knots=knots):
                self.good(m.validate_authoring(document(knots)))

    def test_coefficients_and_arity(self):
        doc = document()
        doc['mappings'][0]['rules'][0]['operator']['scale'] = 1
        self.assertEqual(errors(m.validate_authoring(doc)), [('E_OPERATOR', '/mappings/0/rules/0')])
        doc['mappings'][0]['rules'][0]['operator'] = {'id': 'piecewise_linear'}
        self.assertEqual(errors(m.validate_authoring(doc)), [('E_OPERATOR', '/mappings/0/rules/0')])
        doc = document()
        doc['mappings'][0]['rules'][0]['inputs'] = ['in', 'out']
        self.assertEqual(errors(m.validate_authoring(doc)), [('E_ARITY', '/mappings/0/rules/0')])

    def test_endpoints_must_equal_the_input_domain_at_compile(self):
        self.good(self.compile(document([[-1.0, 0], [1.0, 1]], low=-1, high=1)))
        for low, high in ((-1, 2), (-2, 1), (-1, None), (None, 1), (None, None)):
            with self.subTest(domain=(low, high)):
                doc = document([[-1, 0], [1, 1]], low, high)
                doc['signals'][0]['domain'] = {k: v for k, v in (('min', low), ('max', high)) if v is not None}
                self.assertEqual(errors(self.compile(doc)), [('E_DOMAIN_COMPATIBILITY', 'r')])


class OperatorVersions(Checks):
    def test_operator_version_1_0_refuses_piecewise_linear(self):
        result = m.validate_authoring(document(operators='1.0'))
        self.assertEqual(errors(result), [('E_OPERATOR_VERSION', '/mappings/0/rules/0')])
        doc = document(operators='1.0')
        doc['mappings'][0]['rules'][0]['operator'] = {'id': 'affine', 'scale': 0.5, 'offset': 0.5}
        self.good(m.validate_authoring(doc))

    def test_unknown_versions_keep_failing_as_before(self):
        for key in ('operator_version', 'schema_version'):
            for value in ('2.0', '1.2', 1.1, None):
                with self.subTest(key=key, value=value):
                    doc = document()
                    doc['mappings'][0]['rules'][0]['operator'] = {'id': 'identity'}
                    doc['signals'][0]['domain'] = doc['signals'][1]['domain']
                    doc[key] = value
                    self.assertEqual(errors(m.validate_authoring(doc)), [('E_ENUM', '/' + key)])

    def test_calibrated_software_needs_authoring_1_1(self):
        for where in ('signal', 'rule', 'evidence'):
            with self.subTest(where=where):
                doc = document(schema='1.0')
                record = {'signal': doc['signals'][0], 'rule': doc['mappings'][0]['rules'][0], 'evidence': doc['evidence'][0]}[where]
                record['status' if where == 'evidence' else 'evidence_status'] = K
                self.assertEqual([d.code for d in m.validate_authoring(doc).report.diagnostics], ['E_ENUM'])
                doc['schema_version'] = '1.1'
                self.good(m.validate_authoring(doc))


class CalibratedSoftware(Checks):
    """calibrated_software is admitted exactly where proposed is, and is never verified_current."""
    def diagnostics(self, rule_status, source_status, target_status, evidence_status):
        doc = document([[-1, 0], [1, 1]])
        doc['mappings'][0]['rules'][0]['evidence_status'] = rule_status
        doc['signals'][0]['evidence_status'] = source_status
        doc['signals'][1]['evidence_status'] = target_status
        doc['evidence'][0]['status'] = evidence_status
        result = self.compile(doc)
        return [(d.code, d.ref, d.message.replace(K, P)) for d in result.report.diagnostics], result.ok

    def matches_proposed(self, combinations):
        for statuses in combinations:
            if K in statuses:
                with self.subTest(statuses=statuses):
                    self.assertEqual(self.diagnostics(*statuses), self.diagnostics(*(P if s == K else s for s in statuses)))

    def test_every_rule_and_signal_status_combination_matches_proposed(self):
        self.matches_proposed(statuses + (C,) for statuses in itertools.product((C, K, U), repeat=3))

    def test_calibrated_evidence_matches_proposed_evidence_under_every_status(self):
        self.matches_proposed(statuses + (K,) for statuses in itertools.product((C, K, U), repeat=3))

    def test_it_mixes_with_proposed_and_never_counts_as_current(self):
        self.assertTrue(self.diagnostics(K, P, K, P)[1])
        self.assertEqual([code for code, _, _ in self.diagnostics(C, K, C, C)[0]], ['E_EVIDENCE_STATUS'])
        self.assertEqual([code for code, _, _ in self.diagnostics(C, C, C, K)[0]], ['E_EVIDENCE_COMPATIBILITY'] * 3)


class PiecewiseLinearValues(Checks):
    def test_knots_evaluate_exactly(self):
        knots = [[-1, 0.1], [-0.3, 0.2], [0.1, 1 / 3], [0.7, 0.9], [1, 1]]
        self.assertEqual(self.outputs(knots, [x for x, _ in knots]), [float(y) for _, y in knots])
        knots = [[-1, 1], [-1 / 3, 0.7], [0.2, 0.1], [1, 0]]
        self.assertEqual(self.outputs(knots, [x for x, _ in knots]), [float(y) for _, y in knots])

    def test_segments_match_an_exact_rational_oracle_and_stay_monotone(self):
        rng = random.Random(20261027)
        for knots in ([[-1, 0.1], [-0.3, 0.2], [0.1, 1 / 3], [0.7, 0.9], [1, 1]],
                      [[-1, 1], [-1 / 3, 0.7], [0.2, 0.1], [1, 0]], SPLIT_NEGATIVE, SPLIT_POSITIVE):
            xs = sorted({rng.uniform(-1, 1) for _ in range(150)} | {math.nextafter(x, 0) for x, _ in knots[1:-1]})
            with self.subTest(knots=knots):
                ys = self.outputs(knots, xs)
                for x, y in zip(xs, ys):
                    i = max(j for j in range(len(knots) - 1) if knots[j][0] <= x)
                    (xa, ya), (xb, yb) = map(lambda k: map(Fraction, k), knots[i:i + 2])
                    exact = ya + (Fraction(x) - xa) / (xb - xa) * (yb - ya)
                    self.assertLessEqual(abs(Fraction(y) - exact), 8 * max(ulps(float(ya)), ulps(float(yb))), x)
                    self.assertTrue(min(ya, yb) <= y <= max(ya, yb), x)
                steps = {(b > a) - (b < a) for a, b in zip(ys, ys[1:])} - {0}
                self.assertLessEqual(len(steps), 1)

    def test_rounding_never_steps_past_the_far_knot(self):
        # Unclamped, this segment formula gives -336553.19921875 here, below the far knot.
        (xa, ya), (xb, yb) = knots = [[-1.2724967734303773e-09, 21036522527349.0], [-1.1275265260032487e-15, -336553.19868886983]]
        x = math.nextafter(xb, xa)
        self.assertLess(ya + (x - xa) / (xb - xa) * (yb - ya), yb)
        self.assertEqual(self.outputs(knots, [x], out_low=-1e6, out_high=1e14), [yb])

    def test_values_outside_the_output_domain_are_refused(self):
        compiled = self.good(self.compile(document([[-1, 0], [0, 1], [1, 2]])))
        self.assertEqual(self.run_frames(compiled, [{'in': 0}]), [{'out': 1.0}])
        result = m.evaluate_mapping(compiled, [{'timestamp': 0, 'values': {'in': 0.5}, 'validity': {'in': True}}])
        self.assertEqual(errors(result), [('E_DOMAIN', '/samples/0/rules/r')])

    def test_segment_arithmetic_is_checked_like_affine(self):
        compiled = self.good(self.compile(document([[0, 0], [1, 0.5]], low=0, high=1)))
        result = m.evaluate_mapping(compiled, [{'timestamp': 0, 'values': {'in': 5e-324}, 'validity': {'in': True}}])
        self.assertEqual(errors(result), [('E_NONFINITE', '/samples/0/rules/r')])


class GazeExclusivity(Checks):
    def test_the_two_sides_are_never_both_nonzero(self):
        compiled = self.good(self.compile(gaze()))
        rng = random.Random(7)
        grid = [i / 20 for i in range(21)] + [0.1, 0.2, 0.3, 1 / 3, 2 / 3, 1e-300, math.nextafter(0.5, 1)]
        pairs = list(itertools.product(grid, repeat=2)) + [(rng.random(), rng.random()) for _ in range(300)]
        pairs += [(x, x) for x in grid]
        values = self.run_frames(compiled, [{'look_in': a, 'look_out': b} for a, b in pairs])
        for (a, b), v in zip(pairs, values):
            with self.subTest(look_in=a, look_out=b):
                self.assertFalse(v['toward_in'] and v['toward_out'], v)
                self.assertTrue(a > b if v['toward_in'] else a < b if v['toward_out'] else True, v)
        self.assertEqual(self.run_frames(compiled, [{'look_in': 1, 'look_out': 0}, {'look_in': 0, 'look_out': 1}]),
                         [{'toward_in': 1.0, 'toward_out': 0.0}, {'toward_in': 0.0, 'toward_out': 1.0}])


if __name__ == '__main__':
    unittest.main()
