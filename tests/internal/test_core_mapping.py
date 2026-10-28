# SPDX-License-Identifier: MIT
"""Mapping compilation and evaluation (the C++ core) against the 0.3.0 oracle.

Each case compiles a document's mapping between its profiles and evaluates
samples, here and in the oracle; records, reports and samples must match
exactly, floats bit for bit. The fast path must also agree with the exact path
(MSF_TOOLS_PURE=1) and take the samples it is meant to take. MSF_GATE=1 runs
2*10**4 random documents with random samples.

0.3.0 checked a frame's channels in set order, which str hashing decides: with
PYTHONHASHSEED unset, diagnostics within one frame are compared as a multiset.
"""
import copy
import math
import os
import random
import re
import struct
import unittest
from types import MappingProxyType
from unittest import mock

import msf_character_tools as m
from msf_character_tools import _native
from internal import oracle
import test_operators_1_1 as ops

GATE = os.environ.get('MSF_GATE') == '1'

# Names reach nested lambdas only as parameters: eval's locals are not closures.
PIPE = ('(lambda doc, samples, mid, allow: (lambda p: (lambda s, t: (s, t, (lambda c: (c, m.evaluate_mapping(c.value, samples)'
        ' if c.ok else None, c.value.instructions if c.ok else None))(m.compile_mapping(p, s.value, t.value, mid, allow))))'
        '(m.profile_snapshot(p, "source"), m.profile_snapshot(p, "target")))'
        '(m.compile_pack(m.validate_authoring(doc).value).value))(doc, samples, mid, allow)')


def build(doc, mid='map', allow=False):
    pack = m.compile_pack(m.validate_authoring(doc).value).value
    source, target = m.profile_snapshot(pack, 'source').value, m.profile_snapshot(pack, 'target').value
    return m.compile_mapping(pack, source, target, mid, allow).value


def affine(scale, offset, low=0, high=2, out_low=-1, out_high=1):
    doc = ops.document(low=low, high=high, out_low=out_low, out_high=out_high)
    doc['mappings'][0]['rules'][0]['operator'] = {'id': 'affine', 'scale': scale, 'offset': offset}
    return doc


def unbounded(doc, *signals):
    """doc with the named signals' domains made unbounded, so only checked arithmetic can refuse."""
    for signal in doc['signals']:
        if signal['id'] in signals:
            signal['domain'] = {}
    return doc


def frame(values, timestamp=0.0):
    return {'timestamp': timestamp, 'values': values, 'validity': dict.fromkeys(values, True)}


def same(a, b):
    """Equal values of identical types, floats compared by their bits."""
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return struct.pack('>d', a) == struct.pack('>d', b)
    if type(a) is MappingProxyType:
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if type(a) is tuple:
        return len(a) == len(b) and all(map(same, a, b))
    return a == b


def frame_of(diagnostic):
    found = re.match(r'/samples/(\d+)', diagnostic[2])
    return int(found.group(1)) if found else -1


def normalize(outcome):
    """Diagnostics of one frame in a fixed order, when set order may differ between the two sides."""
    if oracle.SAME_HASHING:
        return outcome
    if isinstance(outcome, tuple) and len(outcome) == 3 and outcome[0] == 'Report':
        return ('Report', sorted(outcome[1], key=lambda d: (frame_of(d), d)), outcome[2])
    if isinstance(outcome, (tuple, list)):
        return type(outcome)(normalize(x) for x in outcome)
    return outcome


# Documents ------------------------------------------------------------------

NUMBERS = [0, 1, -1, 0.5, -0.0, 0.0, 2, 1e-300, 1.5e308, -1.5e308, 2**-1074, 2**53 + 1, 2.0**53, 1 - 2**-53, 3, 0.25]


def random_document(rng):
    roll = rng.random()
    if roll < 0.3:
        n = rng.randrange(2, 6)
        xs = sorted(set(rng.choice([rng.uniform(-2, 2), rng.choice(NUMBERS[:9])]) for _ in range(n)))
        if len(xs) < 2:
            xs = [-1, 1]
        ys = sorted(rng.uniform(-1, 1) for _ in xs)
        if rng.random() < 0.5:
            ys.reverse()
        doc = ops.document([[x, y] for x, y in zip(xs, ys)], low=xs[0], high=xs[-1], out_low=-1, out_high=1)
    elif roll < 0.55:
        doc = affine(rng.choice(NUMBERS + [rng.uniform(-3, 3)]), rng.choice(NUMBERS + [rng.uniform(-3, 3)]),
                     low=rng.choice([0, -1, -1e308]), high=rng.choice([2, 1, 1e308]),
                     out_low=rng.choice([-1, -2, -1e308]), out_high=rng.choice([1, 2, 1e308]))
        if rng.random() < 0.2:
            doc = unbounded(doc, 'in', 'out')
    elif roll < 0.8:
        doc = ops.gaze()
        rule = doc['mappings'][0]['rules'][0]
        rule['operator']['weights'] = [rng.choice(NUMBERS + [rng.uniform(-2, 2)]) for _ in range(2)]
        if rng.random() < 0.3:
            doc = unbounded(doc, 'gaze')
    else:
        doc = affine(1, 0)
        doc['mappings'][0]['rules'][0]['operator'] = {'id': 'identity'}
    for _ in range(rng.choice((0, 0, 0, 1, 1, 2))):
        tweak(doc, rng)
    return doc


def tweak(doc, rng):
    """One edit aimed at a compile check."""
    rules = doc['mappings'][0]['rules']
    r = rng.choice(rules)
    signals = doc['signals']
    s = rng.choice(signals)
    roll = rng.randrange(12)
    if roll == 0:
        r['disposition'] = rng.choice(['unsupported', 'unresolved', 'excluded'])
        r.pop('mapping_quality', None)
    elif roll == 1:
        r['mapping_quality'] = 'approximate'
        if rng.random() < 0.5:
            r['loss_annotations'] = [{'category': 'signal', 'effect': rng.choice(['approximated', 'preserved', 'dropped']),
                                      'reason': 'r', 'refs': ['in'], 'bound': rng.choice([0, 0.5, -0.0, 2])}]
    elif roll == 2:
        r['evidence_status'] = rng.choice(['proposed', 'unresolved', 'calibrated_software'])
    elif roll == 3:
        s['evidence_status'] = rng.choice(['proposed', 'unresolved', 'calibrated_software'])
    elif roll == 4:
        s['units'] = rng.choice(['m', 'deg'])
    elif roll == 5:
        s['calibration'] = 'other.v1'
    elif roll == 6:
        s[rng.choice(['neutral', 'side', 'coupling'])] = rng.choice([0, 0.0, 'left', ['in'], 'in'])
    elif roll == 7:
        s['disposition'] = rng.choice(['unsupported', 'excluded'])
    elif roll == 8:
        r['assumptions'] = rng.choice([[], ['a']])
    elif roll == 9:
        doc['evidence'].append({'id': 'p', 'claim': 'c', 'status': rng.choice(['proposed', 'unresolved']), 'license': 'MIT',
                                'authorship': 'me'})
        rng.choice([r, s])['evidence'] = rng.choice([['e', 'p'], ['p'], []])
    elif roll == 10:
        rules.append(copy.deepcopy(r))
        rules[-1]['id'] = 'copy'
        if rng.random() < 0.5:
            rules[-1]['inputs'] = list(r['outputs'])
            rules[-1]['outputs'] = list(r['inputs'][:1])
    else:
        doc['profiles'][rng.randrange(2)]['signal_ids'] = [x['id'] for x in rng.sample(signals, rng.randrange(1, len(signals) + 1))]


def sources(doc):
    ids = {x['id']: x for x in doc['signals']}
    return [ids[sid] for sid in doc['profiles'][0]['signal_ids'] if sid in ids]


def value_in(domain, rng):
    low, high = domain.get('min', -1e308), domain.get('max', 1e308)
    roll = rng.random()
    if roll < 0.15:
        return rng.choice([low, high])
    if roll < 0.2:
        return rng.choice([-0.0, 0.0, 0, 2**-1074])
    if roll < 0.25 and isinstance(low, int) and isinstance(high, int) and high - low < 10**6:
        return rng.randint(low, high)
    return low + (high - low) * rng.random() if math.isfinite(high - low) else rng.uniform(-1e300, 1e300)


BAD = [True, False, 'x', None, math.nan, math.inf, -math.inf, 10**400, 2**53 + 1, [], {}, 1e308, -5, 7]


def random_frame(doc, rng, i):
    values = {s['id']: value_in(s['domain'], rng) for s in sources(doc)}
    validity = dict.fromkeys(values, True)
    f = {'timestamp': rng.choice([i, i / 60, 0, 0.0]), 'values': values, 'validity': validity}
    for _ in range(rng.choice((0, 0, 0, 0, 1, 1, 2, 3))):
        roll = rng.randrange(10)
        sid = rng.choice(list(values) + ['other']) if values else 'other'
        if roll == 0:
            values.pop(sid, None)
        elif roll == 1:
            validity.pop(sid, None)
        elif roll == 2:
            values[sid] = rng.choice(BAD)
            validity.setdefault(sid, True)
        elif roll == 3:
            validity[sid] = rng.choice([False, 1, 0, None, 'yes'])
            values.setdefault(sid, 0.5)
        elif roll == 4:
            f['timestamp'] = rng.choice([-1, -0.0, True, math.nan, math.inf, 10**400, 'now', None])
        elif roll == 5:
            f[rng.choice(['note', 'timestamp'])] = 1
        elif roll == 6:
            del f[rng.choice(list(f))]
        elif roll == 7:
            f['values'] = rng.choice([list(values.items()), None, 'x'])
        elif roll == 8:
            values[rng.choice([1, ('t',), 2.5])] = 0.5
        else:
            return rng.choice([None, 3, [f], 'frame'])
    return f


def random_samples(doc, rng):
    n = rng.choice((0, 1, 1, 2, 3, 5))
    samples = [random_frame(doc, rng, i) for i in range(n)]
    return tuple(samples) if rng.random() < 0.2 else samples


@unittest.skipIf(oracle.skip_reason(), oracle.skip_reason() or '')
class AgainstTheOracle(unittest.TestCase):
    def assertSame(self, cases):
        self.assertNotEqual(oracle.outcome(*cases[0])[0], 'error', oracle.outcome(*cases[0]))
        differing = oracle.differ(cases, normalize)
        self.assertEqual(differing[:2], [], f'{len(differing)} of {len(cases)} cases differ')

    def case(self, doc, samples, mid='map', allow=False):
        return PIPE, {'doc': doc, 'samples': samples, 'mid': mid, 'allow': allow}

    def assertFastAndExact(self, doc, samples, fast=True):
        """Both paths agree with the oracle and each other; `fast`: the fast path takes the samples."""
        self.assertSame([self.case(doc, samples)])
        compiled = build(doc)
        taken = compiled._core.evaluate(samples)
        self.assertEqual(taken is not None, fast, 'the fast path took or declined unexpectedly')
        with mock.patch.object(_native, 'core', None):
            exact = m.evaluate_mapping(compiled, samples)
        actual = m.evaluate_mapping(compiled, samples)
        self.assertEqual(actual.report.to_dict(), exact.report.to_dict())
        if exact.ok:
            self.assertTrue(same(actual.value.samples, exact.value.samples))
        return actual

    def test_affine_does_not_fuse_multiply_add(self):
        # Fused, (1 + 2**-30) * (1 - 2**-30) - 1 is -2**-60; rounded first, it is exactly 0.
        result = self.assertFastAndExact(affine(1 + 2**-30, -1), [frame({'in': 1 - 2**-30})])
        self.assertTrue(same(result.value.samples[0]['values']['out'], 0.0))

    def test_signed_zero_coefficients_keep_their_sign(self):
        result = self.assertFastAndExact(affine(1, -0.0, low=-1, high=1), [frame({'in': -0.0})])
        self.assertTrue(same(result.value.samples[0]['values']['out'], -0.0))
        knots = [[0, 1.59], [7.9e299, 1.13], [1e300, -0.0]]
        result = self.assertFastAndExact(ops.document(knots, low=0, high=1e300, out_low=-1, out_high=2), [frame({'in': 1e300})])
        self.assertTrue(same(result.value.samples[0]['values']['out'], -0.0))

    def test_overflow_is_refused_without_a_domain_to_catch_it(self):
        def gaze_weights(weights):
            doc = unbounded(ops.gaze(), 'gaze', 'toward_in', 'toward_out')
            doc['mappings'][0]['rules'] = doc['mappings'][0]['rules'][:1]
            doc['mappings'][0]['rules'][0]['operator']['weights'] = weights
            doc['profiles'][1]['signal_ids'] = ['gaze']
            return doc
        cases = {'product': (unbounded(affine(2, 0), 'in', 'out'), {'in': 1.5e308}),
                 'sum': (unbounded(affine(1e308, 1e308), 'in', 'out'), {'in': 1.5}),
                 'weighted sum': (gaze_weights([1e308, 1e308]), {'look_in': 1, 'look_out': 1}),
                 'underflow': (unbounded(affine(2**-600, 0), 'in', 'out'), {'in': 2**-600})}
        for name, (doc, values) in cases.items():
            with self.subTest(name):
                result = self.assertFastAndExact(doc, [frame(values)], fast=False)
                self.assertEqual([d.code for d in result.report.diagnostics], ['E_NONFINITE'])
        self.assertFastAndExact(unbounded(affine(2, 0), 'in', 'out'), [frame({'in': 8e307})])

    def test_gaze_and_piecewise_segments(self):
        rng = random.Random(7)
        specials = [0, 1, 0.5, -0.0, 0.0, 1.0, 2**-1074, 1 - 2**-53, math.nextafter(0.5, 1)]
        samples = [frame({'look_in': rng.choice(specials) if rng.random() < 0.3 else rng.random(),
                          'look_out': rng.choice(specials) if rng.random() < 0.3 else rng.random()}, rng.choice([i, i / 60]))
                   for i in range(200)]
        self.assertFastAndExact(ops.gaze(), samples)
        knots = [[-1, 0], [-0.3, 0.1], [0.2, 0.1], [0.7, 0.9], [1, 1]]
        xs = [k[0] for k in knots] + [math.nextafter(k[0], 0) for k in knots] + [rng.uniform(-1, 1) for _ in range(100)]
        self.assertFastAndExact(ops.document(knots), [frame({'in': x}) for x in xs])
        self.assertFastAndExact(ops.document([[-1, 1], [1, -1]], out_low=-1), [frame({'in': x}) for x in xs])

    def test_samples_outside_the_fast_path(self):
        doc = ops.document()
        good = frame({'in': 0.25})
        cases = {
            'out of domain': [good, frame({'in': 2})],
            'invalid': [good, {'timestamp': 0, 'values': {'in': 0.5}, 'validity': {'in': False}}],
            'missing': [good, frame({})],
            'unknown channel': [good, frame({'in': 0.5, 'other': 0.5})],
            'boolean value': [good, frame({'in': True})],
            'boolean timestamp': [good, frame({'in': 0.5}, True)],
            'negative timestamp': [good, frame({'in': 0.5}, -1)],
            'huge integer': [good, frame({'in': 2**53 + 1})],
            'nan': [good, frame({'in': math.nan})],
            'validity 1': [good, {'timestamp': 0, 'values': {'in': 0.5}, 'validity': {'in': 1}}],
            'extra key': [good, {**frame({'in': 0.5}), 'note': 1}],
            'tuple samples': (good, frame({'in': 0.5})),
            'integer values': [frame({'in': 0}), frame({'in': -1}, 3)],
            'non-str key': [good, frame({'in': 0.5, 1: 0.5})],
        }
        for name, samples in cases.items():
            with self.subTest(name):
                self.assertSame([self.case(doc, samples)])
        self.assertFastAndExact(doc, [])
        self.assertFastAndExact(doc, [frame({'in': 0}), frame({'in': -1}, 3)])

    def test_inexact_domain_bounds_take_the_exact_path(self):
        doc = affine(1, 0, low=0, high=2**53 + 1, out_low=0, out_high=2**53 + 1)
        compiled = build(doc)
        self.assertIsNone(compiled._core.evaluate([frame({'in': 0.5})]))
        self.assertSame([self.case(doc, [frame({'in': v}) for v in (0.5, 2**53, 2**53 + 1, 2.0**53, 2**53 + 2)])])

    def test_compile_refusals_and_options(self):
        doc = ops.gaze()
        cases = [self.case(doc, [], mid) for mid in ('map', 'nope', '\udc80')] + [self.case(doc, [], 'map', True)]
        self.assertSame(cases)

    def test_rules_run_in_dependency_waves_and_cycles_are_refused(self):
        def chained(order, needs):
            doc = ops.document()
            ids = sorted({*order, *(n for ns in needs.values() for n in ns)})
            doc['signals'] = [ops.signal('in')] + [ops.signal(f'out_{i}') for i in ids]
            doc['profiles'][1]['signal_ids'] = [f'out_{i}' for i in ids]
            doc['mappings'][0]['rules'] = [ops.rule(i, [f'out_{n}' for n in needs.get(i, ())] or ['in'], f'out_{i}',
                                                    {'id': 'weighted_sum', 'weights': [1] * max(1, len(needs.get(i, ())))})
                                           for i in order]
            return doc
        # Rescanning every rule once per wave needs about 1e7 checks here; the
        # snapshots are bypassed, as their Python checks would dominate.
        count = 4000
        long = chained([f'r{i:05}' for i in reversed(range(count))], {f'r{i:05}': [f'r{i - 1:05}'] for i in range(1, count)})
        pack = m.compile_pack(m.validate_authoring(long).value).value
        channels = {s['id']: s for s in pack.document['signals']}
        source = {'in': channels['in']}
        diagnostics, _, handle = _native.built.compile_mapping(pack._core, 'map', False, source, channels)
        self.assertEqual(diagnostics, ())
        self.assertEqual([r['id'] for r in handle.views()[0]], [f'r{i:05}' for i in range(count)])
        waves = chained(['A', 'B', 'C'], {'A': ['B']})
        self.assertEqual([r['id'] for r in build(waves).instructions], ['B', 'C', 'A'])
        cycles = chained(['A', 'B', 'C', 'P', 'Q', 'R'], {'A': ['B'], 'P': ['Q'], 'Q': ['P'], 'R': ['R']})
        self.assertSame([self.case(d, [frame({'in': 0.5})]) for d in (waves, cycles)])

    def test_random_documents_and_samples(self):
        rng = random.Random(23)
        cases = []
        for _ in range(20000 if GATE else 40):
            doc = random_document(rng)
            cases.append(self.case(doc, random_samples(doc, rng), rng.choice(['map'] * 9 + ['other']), rng.random() < 0.3))
        self.assertSame(cases)


if __name__ == '__main__':
    unittest.main()
