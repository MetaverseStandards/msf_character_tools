# SPDX-License-Identifier: MIT
"""Partial evaluation, evaluate_mapping(..., partial=True), against whole-map evaluation.

The expected outcome of each output comes from two places that do not use
partial evaluation:
- the output's inputs and rules, found here from the authored rules;
- whole-map evaluation, which the oracle tests hold to 0.3.0: of each frame
  alone, for its diagnostics, and of a map that holds only the output's rules,
  for its value, which must agree bit for bit.
The fast path must agree with the exact path (MSF_TOOLS_PURE=1). MSF_GATE=1
runs 5000 random maps in place of 300.
"""
import copy
import math
import os
import random
import re
import unittest
from types import MappingProxyType
from unittest import mock

import msf_character_tools as m
from msf_character_tools import _native
from internal.test_core_mapping import random_document, random_samples, same, value_in
import test_operators_1_1 as ops
import test_record_integrity as integrity

GATE = os.environ.get('MSF_GATE') == '1'


def signal(sid, domain):
    s = ops.signal(sid)
    s['domain'] = dict(domain)
    return s


def pack_of(doc):
    validated = m.validate_authoring(doc)
    assert validated.ok, validated.report.to_dict()
    pack = m.compile_pack(validated.value)
    assert pack.ok, pack.report.to_dict()
    return pack.value


def compile_map(pack, mid='map'):
    return m.compile_mapping(pack, m.profile_snapshot(pack, 'source').value, m.profile_snapshot(pack, 'target').value, mid)


def frame(values, timestamp=0.0, validity=None):
    return {'timestamp': timestamp, 'values': values, 'validity': dict.fromkeys(values, True) if validity is None else validity}


def both_paths(compiled, samples):
    """Partial evaluation with the fast path, and on the exact path alone; their reports and values must agree."""
    actual = m.evaluate_mapping(compiled, samples, partial=True)
    with mock.patch.object(_native, 'core', None):
        exact = m.evaluate_mapping(compiled, samples, partial=True)
    assert actual.report.to_dict() == exact.report.to_dict(), (actual.report.to_dict(), exact.report.to_dict())
    assert actual.ok == exact.ok
    if exact.ok:
        assert same(actual.value.samples, exact.value.samples), 'fast and exact samples differ'
        assert actual.value.to_dict() == exact.value.to_dict()
    return actual


# The reference model ---------------------------------------------------------

def cones(doc, mid='map'):
    """{target output: (inputs, rule IDs)}, read from the authored rules, in rule declaration order."""
    rules = next(x for x in doc['mappings'] if x['id'] == mid)['rules']
    writer = {r['outputs'][0]: r for r in rules}
    target = set(doc['profiles'][1]['signal_ids'])

    def walk(sid, inputs, rids):
        r = writer.get(sid)
        if r is None:
            inputs.add(sid)
        elif r['id'] not in rids:
            rids.add(r['id'])
            for i in r['inputs']:
                walk(i, inputs, rids)
    out = {}
    for r in rules:
        o = r['outputs'][0]
        if o in target and o not in out:
            inputs, rids = set(), set()
            walk(o, inputs, rids)
            out[o] = (inputs, rids)
    return out


def with_cone_maps(doc, mid='map'):
    """doc plus one map per target output, named sub.<output>, that holds only that output's rules."""
    doc = copy.deepcopy(doc)
    rules = next(x for x in doc['mappings'] if x['id'] == mid)['rules']
    for o, (_, rids) in cones(doc, mid).items():
        sub = [dict(r, id=f"{r['id']}.{o}") for r in rules if r['id'] in rids]
        doc['mappings'].append({'id': f'sub.{o}', 'rules': copy.deepcopy(sub)})
    return doc


def subject(ref, n, required):
    """What a whole-map diagnostic of frame n is about: ('input', sid), ('rule', rid) or ('frame', None)."""
    rest = ref[len(f'/samples/{n}'):]
    if rest.startswith('/rules/'):
        return 'rule', rest[len('/rules/'):]
    if rest.startswith('/') and rest[1:] in required:
        return 'input', rest[1:]
    return 'frame', None


def renumber(diagnostic, n):
    d = diagnostic.to_dict()
    d['ref'] = re.sub(r'^/samples/0(?=/|$)', f'/samples/{n}', d['ref'])
    return d


class Expected:
    """The partial result that whole-map evaluation predicts for `samples`."""

    def __init__(self, doc, compiled, samples, mid='map'):
        self.ok, self.samples, self.refusals, self.unavailable = True, [], [], []
        losses = [x.to_dict() for x in compiled.losses]
        required = set(compiled.required_inputs)
        cone = cones(doc, mid)
        frames = list(samples)
        per_frame = [m.evaluate_mapping(compiled, [f]) for f in frames]
        if any(not d.ref.startswith('/samples/') for r in per_frame for d in r.report.diagnostics):
            self.ok, self.report = False, m.evaluate_mapping(compiled, samples).report.to_dict()
            return
        fatal = [d for n, r in enumerate(per_frame) for d in (renumber(x, n) for x in r.report.diagnostics)
                 if subject(d['ref'], n, required)[0] == 'frame']
        self.report = {'schema_version': '1.0', 'diagnostics': fatal, 'losses': losses}
        if fatal:
            self.ok = False
            return
        self.cone_pack = pack_of(with_cone_maps(doc, mid))
        self.cone_maps = {}
        for n, (f, r) in enumerate(zip(frames, per_frame)):
            diagnostics = [renumber(d, n) for d in r.report.diagnostics]
            subjects = [subject(d['ref'], n, required) for d in diagnostics]
            values = {}
            for o in compiled.output_ids:
                inputs, rids = cone[o]
                mine = [(d, s) for d, s in zip(diagnostics, subjects)
                        if (s[0] == 'input' and s[1] in inputs) or (s[0] == 'rule' and s[1] in rids)]
                if any(d['code'] != 'E_MISSING_SAMPLE' for d, _ in mine):
                    self.refusals.append({'sample': n, 'output': o, 'diagnostics': [d for d, _ in mine]})
                elif mine:
                    missing = {s[1] for _, s in mine}
                    self.unavailable.append({'sample': n, 'output': o, 'inputs': [i for i in compiled.required_inputs if i in missing]})
                else:
                    values[o] = self.cone_value(o, inputs, f)
            self.samples.append({'timestamp': float(f['timestamp']), 'values': values, 'validity': dict.fromkeys(values, True)})

    def cone_value(self, o, inputs, f):
        """The output's value from whole-map evaluation of the map that holds only its rules."""
        if o not in self.cone_maps:
            result = compile_map(self.cone_pack, f'sub.{o}')
            assert result.ok, result.report.to_dict()
            self.cone_maps[o] = result.value
        values = {i: f['values'][i] for i in inputs}
        result = m.evaluate_mapping(self.cone_maps[o], [frame(values, f['timestamp'])])
        assert result.ok, (o, result.report.to_dict())
        return result.value.samples[0]['values'][o]


class Model(unittest.TestCase):
    def assertExpected(self, doc, samples, mid='map'):
        compiled = compile_map(pack_of(doc), mid).value
        expected = Expected(doc, compiled, samples, mid)
        actual = both_paths(compiled, samples)
        self.assertEqual(actual.ok, expected.ok, actual.report.to_dict())
        self.assertEqual(actual.report.to_dict(), expected.report)
        if not expected.ok:
            return actual
        got = actual.value.to_dict()
        self.assertEqual(got['refusals'], expected.refusals)
        self.assertEqual(got['unavailable'], expected.unavailable)
        self.assertEqual(len(actual.value.samples), len(expected.samples))
        for f, e in zip(actual.value.samples, expected.samples):
            self.assertTrue(same(f['timestamp'], e['timestamp']))
            self.assertEqual(list(f['values']), list(e['values']))
            self.assertEqual(dict(f['validity']), e['validity'])
            for o, v in e['values'].items():
                self.assertTrue(same(f['values'][o], v), (o, f['values'][o], v))
        return actual


# A map with intermediate rules ------------------------------------------------

def chains():
    """a, b -> w (virtual) -> o1 (piecewise), o3 (with c), o5 (affine, leaves its domain when w > 1/3); c -> o2; d -> o4."""
    doc = ops.document()
    unit = {'min': 0, 'max': 1}
    doc['signals'] = ([signal(s, unit) for s in ('a', 'b', 'c', 'd', 'w', 'o1', 'o4', 'o5')]
                      + [signal(s, {'min': -1, 'max': 1}) for s in ('o2', 'o3')])
    doc['profiles'][0]['signal_ids'] = ['a', 'b', 'c', 'd']
    doc['profiles'][1]['signal_ids'] = ['o1', 'o2', 'o3', 'o4', 'o5']
    doc['mappings'][0]['rules'] = [
        ops.rule('r1', ['w'], 'o1', ops.piecewise([[0, 0], [0.5, 0.2], [1, 1]])),
        ops.rule('r2', ['c'], 'o2', {'id': 'affine', 'scale': 2, 'offset': -1}),
        ops.rule('r3', ['w', 'c'], 'o3', {'id': 'weighted_sum', 'weights': [1, -1]}),
        ops.rule('r4', ['d'], 'o4', {'id': 'identity'}),
        ops.rule('r5', ['w'], 'o5', {'id': 'affine', 'scale': 3, 'offset': 0}),
        ops.rule('rw', ['a', 'b'], 'w', {'id': 'weighted_sum', 'weights': [0.5, 0.5]})]
    return doc


GOOD = {'a': 0.25, 'b': 0.0, 'c': 0.75, 'd': 0.25}  # w = 0.125, so every output is in its domain
A_INVALID = {'a': False, 'b': True, 'c': True, 'd': True}


class PartialEvaluation(Model):
    def setUp(self):
        self.doc = chains()
        self.compiled = compile_map(pack_of(self.doc)).value

    def run_partial(self, samples, compiled=None):
        result = both_paths(self.compiled if compiled is None else compiled, samples)
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def outcome(self, samples):
        """Per frame: {output: value, ('refused', [(code, ref)]) or ('unavailable', inputs)}."""
        value = self.run_partial(samples)
        out = [dict(f['values']) for f in value.samples]
        for r in value.refusals:
            out[r['sample']][r['output']] = ('refused', [(d.code, d.ref) for d in r['diagnostics']])
        for u in value.unavailable:
            out[u['sample']][u['output']] = ('unavailable', list(u['inputs']))
        return out

    def test_the_inputs_of_each_output(self):
        self.assertEqual(self.compiled.required_inputs, ('c', 'd', 'a', 'b'))
        self.assertIsInstance(self.compiled.output_inputs, MappingProxyType)
        self.assertEqual(dict(self.compiled.output_inputs),
                         {'o1': ('a', 'b'), 'o2': ('c',), 'o3': ('c', 'a', 'b'), 'o4': ('d',), 'o5': ('a', 'b')})
        self.assertEqual(list(self.compiled.output_inputs), list(self.compiled.output_ids))

    def test_good_frames_give_the_whole_map_values(self):
        samples = [frame(GOOD), frame({'a': 0.25, 'b': 0.25, 'c': 0, 'd': 1}, 2), frame({'a': 0.5, 'b': 0.125, 'c': 1, 'd': 0}, 0.5)]
        whole = m.evaluate_mapping(self.compiled, samples)
        self.assertTrue(whole.ok, whole.report.to_dict())
        value = self.run_partial(samples)
        self.assertTrue(same(value.samples, whole.value.samples))
        self.assertEqual((value.refusals, value.unavailable), ((), ()))
        self.assertEqual(value.to_dict(), {**whole.value.to_dict(), 'refusals': [], 'unavailable': []})
        # w = 0.125, so o1 = 0.125 / 0.5 * 0.2, o2 = 2 * 0.75 - 1, o3 = 0.125 - 0.75, o4 = d, o5 = 3 * 0.125.
        self.assertEqual(dict(value.samples[0]['values']), {'o1': 0.125 / 0.5 * 0.2, 'o2': 0.5, 'o3': -0.625, 'o4': 0.25, 'o5': 0.375})

    def test_an_invalid_input_refuses_only_the_outputs_that_read_it(self):
        refused = ('refused', [('E_INVALID_SAMPLE', '/samples/1/a')])
        self.assertEqual(self.outcome([frame(GOOD), frame(GOOD, validity=A_INVALID)])[1],
                         {'o2': 0.5, 'o4': 0.25, 'o1': refused, 'o3': refused, 'o5': refused})

    def test_a_rule_that_leaves_its_domain_refuses_only_its_own_output(self):
        # w = 0.5: o5 = 1.5 is out of [0, 1]; o1 is the knot value 0.2, and o3 = 0.5 - 0.75.
        got = self.outcome([frame({'a': 0.5, 'b': 0.5, 'c': 0.75, 'd': 0.25})])[0]
        self.assertEqual(got, {'o1': 0.2, 'o2': 0.5, 'o3': -0.25, 'o4': 0.25, 'o5': ('refused', [('E_DOMAIN', '/samples/0/rules/r5')])})

    def test_a_refused_intermediate_refuses_every_output_after_it(self):
        doc = chains()
        next(s for s in doc['signals'] if s['id'] == 'w')['domain'] = {'min': 0, 'max': 0.5}
        doc['mappings'][0]['rules'][0]['operator']['knots'] = [[0, 0], [0.25, 0.2], [0.5, 1]]
        compiled = compile_map(pack_of(doc))
        self.assertTrue(compiled.ok, compiled.report.to_dict())
        value = self.run_partial([frame({'a': 1, 'b': 0.5, 'c': 0.75, 'd': 0.25})], compiled.value)
        rule = [('E_DOMAIN', '/samples/0/rules/rw')]
        self.assertEqual({r['output']: [(d.code, d.ref) for d in r['diagnostics']] for r in value.refusals},
                         {'o1': rule, 'o3': rule, 'o5': rule})
        self.assertEqual(dict(value.samples[0]['values']), {'o2': 0.5, 'o4': 0.25})

    def test_several_bad_inputs(self):
        bad = frame(dict(GOOD, c=2, d=True), validity=A_INVALID)
        got = self.outcome([bad])[0]
        self.assertEqual(set(got), {'o1', 'o2', 'o3', 'o4', 'o5'})
        self.assertTrue(all(v[0] == 'refused' for v in got.values()), got)
        self.assertEqual(got['o4'], ('refused', [('E_TYPE', '/samples/0/d')]))
        self.assertEqual(got['o2'], ('refused', [('E_DOMAIN', '/samples/0/c')]))
        whole = [(d.code, d.ref) for d in m.evaluate_mapping(self.compiled, [bad]).report.diagnostics]
        self.assertEqual(got['o3'][1], [x for x in whole if x[1] in ('/samples/0/a', '/samples/0/c')])
        self.assertEqual(len(got['o3'][1]), 2)

    def test_a_missing_input_makes_its_outputs_unavailable(self):
        missing_b = {k: v for k, v in GOOD.items() if k != 'b'}
        got = self.outcome([frame(missing_b), frame({'c': 0.75})])
        self.assertEqual(got[0], {'o2': 0.5, 'o4': 0.25, 'o1': ('unavailable', ['b']), 'o3': ('unavailable', ['b']),
                                  'o5': ('unavailable', ['b'])})
        self.assertEqual(got[1], {'o2': 0.5, 'o1': ('unavailable', ['a', 'b']), 'o3': ('unavailable', ['a', 'b']),
                                  'o4': ('unavailable', ['d']), 'o5': ('unavailable', ['a', 'b'])})
        # Missing inputs alone stay on the fast path.
        self.assertIsNotNone(self.compiled._core.evaluate_partial([frame(missing_b)]))

    def test_a_bad_input_outranks_a_missing_one(self):
        bad = frame({'a': 0.25, 'c': 0.75, 'd': 0.25}, validity={'a': True, 'c': False, 'd': True})
        got = self.outcome([bad])[0]
        self.assertEqual(got['o3'], ('refused', [('E_INVALID_SAMPLE', '/samples/0/c'), ('E_MISSING_SAMPLE', '/samples/0/b')]))
        self.assertEqual(got['o1'], ('unavailable', ['b']))
        self.assertEqual(got['o2'], ('refused', [('E_INVALID_SAMPLE', '/samples/0/c')]))
        self.assertEqual(got['o4'], 0.25)
        self.assertIsNone(self.compiled._core.evaluate_partial([bad]))

    def test_a_value_or_validity_alone_is_refused_not_unavailable(self):
        got = self.outcome([{'timestamp': 0, 'values': dict(GOOD), 'validity': {'a': True, 'b': True, 'c': True}},
                            {'timestamp': 0, 'values': {'a': 0.25, 'b': 0, 'c': 0.75}, 'validity': dict.fromkeys(GOOD, True)}])
        self.assertEqual(got[0]['o4'], ('refused', [('E_VALIDITY', '/samples/0/d')]))
        self.assertEqual(got[1]['o4'], ('refused', [('E_VALIDITY', '/samples/1/d')]))
        self.assertEqual(got[0]['o2'], 0.5)

    def test_faults_no_output_owns_fail_the_whole_evaluation(self):
        doc = chains()
        doc['signals'].append(signal('spare', {'min': 0, 'max': 1}))
        doc['profiles'][0]['signal_ids'].append('spare')
        compiled = compile_map(pack_of(doc)).value
        cases = {'unknown channel': frame(dict(GOOD, other=0.5)),
                 'unread source channel': frame(dict(GOOD, spare=2)),
                 'non-str key': frame({**GOOD, 1: 0.5}),
                 'timestamp': frame(GOOD, -1),
                 'extra key': {**frame(GOOD), 'note': 1},
                 'not an object': 3}
        for name, bad in cases.items():
            with self.subTest(name):
                samples = [frame({'a': 0.25}), bad, frame(GOOD, validity=A_INVALID)]
                result = both_paths(compiled, samples)
                self.assertFalse(result.ok)
                self.assertIsNone(result.value)
                whole = m.evaluate_mapping(compiled, samples)
                self.assertEqual(result.report.diagnostics, tuple(d for d in whole.report.diagnostics if d.ref.startswith('/samples/1')))
        self.assertTrue(both_paths(compiled, [frame(dict(GOOD, spare=0.5))]).ok)

    def test_partial_must_be_a_boolean(self):
        for value in (1, 0, None, 'yes'):
            with self.subTest(value=value):
                result = m.evaluate_mapping(self.compiled, [frame(GOOD)], partial=value)
                self.assertEqual([d.code for d in result.report.diagnostics], ['E_SAMPLE_TYPE'])
        positional = m.evaluate_mapping(self.compiled, [frame(GOOD)], True)
        self.assertEqual([d.code for d in positional.report.diagnostics], ['E_INPUT'])

    def test_whole_map_evaluation_is_unchanged(self):
        value = m.evaluate_mapping(self.compiled, [frame(GOOD)]).value
        self.assertEqual((value.refusals, value.unavailable), (None, None))
        self.assertEqual(list(value.to_dict()), ['samples'])
        self.assertEqual(m.evaluate_mapping(self.compiled, [frame(GOOD)], partial=False).value.to_dict(), value.to_dict())

    def test_records_hold_their_refusals(self):
        value = self.run_partial([frame(GOOD, validity=A_INVALID), frame({'c': 0.5})])
        value.to_dict()
        for name in ('refusals', 'unavailable'):
            with self.subTest(name):
                held = getattr(value, name)
                self.assertTrue(held)
                for changed in (held[:-1], None):
                    object.__setattr__(value, name, changed)
                    integrity.IntegrityTests.refuses_export(self, value.to_dict)
                object.__setattr__(value, name, held)
                value.to_dict()

    def test_piecewise_clamps_and_gaze(self):
        doc = ops.gaze()
        rng = random.Random(11)
        specials = [0, 1, 0.5, -0.0, 1 - 2**-53, math.nextafter(0.5, 1), 2**-1074]
        samples = [frame({'look_in': rng.choice(specials) if rng.random() < 0.3 else rng.random(),
                          'look_out': rng.choice(specials) if rng.random() < 0.3 else rng.random()}, i) for i in range(200)]
        compiled = compile_map(pack_of(doc)).value
        whole = m.evaluate_mapping(compiled, samples)
        self.assertTrue(same(self.run_partial(samples, compiled).samples, whole.value.samples))
        samples[3]['validity']['look_out'] = False
        del samples[5]['values']['look_in'], samples[5]['validity']['look_in']
        result = self.assertExpected(doc, samples)
        self.assertEqual([(r['sample'], r['output']) for r in result.value.refusals], [(3, 'toward_out'), (3, 'toward_in')])


# Random maps -------------------------------------------------------------------

DOMAINS = [{'min': -1, 'max': 1}, {'min': 0, 'max': 1}, {'min': -2, 'max': 2}, {'min': 0, 'max': 0.5}, {}]


def random_map(rng):
    """Sources s0..; rules r0.. writing v0.. from sources or earlier values, declared in a shuffled order."""
    doc = ops.document()
    signals, sources = [], []
    for i in range(rng.randint(1, 5)):
        signals.append(signal(f's{i}', rng.choice(DOMAINS[:4])))
        sources.append(f's{i}')
    domain = {s['id']: s['domain'] for s in signals}
    readable, rules, read = list(sources), [], set()
    for k in range(rng.randint(1, 9)):
        out = f'v{k}'
        kind = rng.choice(['identity', 'affine', 'weighted_sum', 'piecewise_linear'])
        bounded = [s for s in readable if domain[s]]
        if kind == 'piecewise_linear' and not bounded:
            kind = 'affine'
        if kind == 'weighted_sum':
            inputs = rng.sample(readable, rng.randint(1, min(3, len(readable))))
            op = {'id': 'weighted_sum', 'weights': [rng.choice([1, -1, 0.5, 2, 0, rng.uniform(-2, 2)]) for _ in inputs]}
        elif kind == 'piecewise_linear':
            inputs = [rng.choice(bounded)]
            low, high = domain[inputs[0]]['min'], domain[inputs[0]]['max']
            inner = sorted({rng.uniform(low, high) for _ in range(rng.randint(0, 3))} - {low, high})
            ys = sorted(rng.uniform(-1.5, 1.5) for _ in range(len(inner) + 2))
            op = ops.piecewise([[x, y] for x, y in zip([low, *inner, high], ys[::rng.choice([1, -1])])])
        elif kind == 'affine':
            inputs = [rng.choice(readable)]
            op = {'id': 'affine', 'scale': rng.choice([1, -1, 2, 0.5, rng.uniform(-3, 3)]), 'offset': rng.choice([0, 0.5, -1, rng.uniform(-1, 1)])}
        else:
            inputs = [rng.choice(readable)]
            op = {'id': 'identity'}
        domain[out] = domain[inputs[0]] if kind == 'identity' else rng.choice(DOMAINS)
        signals.append(signal(out, domain[out]))
        rules.append(ops.rule(f'r{k}', inputs, out, op))
        read.update(inputs)
        readable.append(out)
    values = [r['outputs'][0] for r in rules]
    spare = rng.random() < 0.2
    if spare:
        signals.append(signal('spare', DOMAINS[1]))
    doc['signals'] = signals
    doc['profiles'][0]['signal_ids'] = sources + (['spare'] if spare else [])
    doc['profiles'][1]['signal_ids'] = [v for v in values if v not in read or rng.random() < 0.3]
    rng.shuffle(rules)
    doc['mappings'][0]['rules'] = rules
    return doc


BAD_VALUES = [True, 'x', None, math.nan, math.inf, 10**400, 5, -3, 2**53 + 1]


def random_frames(doc, rng, faults=True):
    """Frames with inputs left out, and with `faults`, bad inputs and the odd bad frame."""
    signals = {s['id']: s for s in doc['signals']}
    sources = doc['profiles'][0]['signal_ids']
    frames = []
    for i in range(rng.choice((1, 2, 3, 5, 8))):
        values = {sid: value_in(signals[sid]['domain'], rng) for sid in sources}
        validity = dict.fromkeys(values, True)
        f = {'timestamp': rng.choice([i, i / 30, 0.0]), 'values': values, 'validity': validity}
        for _ in range(rng.choice((0, 0, 1, 1, 2, 3))):
            sid = rng.choice(sources)
            roll = rng.random() if faults else 0
            if roll < 0.4:
                values.pop(sid, None)
                validity.pop(sid, None)
            elif roll < 0.55:
                validity[sid] = False
                values.setdefault(sid, 0.5)
            elif roll < 0.72:
                values[sid] = rng.choice(BAD_VALUES)
                validity.setdefault(sid, True)
            elif roll < 0.8:
                validity.pop(sid, None)
                values.setdefault(sid, 0.5)
            elif roll < 0.88:
                values.pop(sid, None)
                validity.setdefault(sid, True)
            elif roll < 0.89:
                f['timestamp'] = rng.choice([-1, math.nan, True])
            elif roll < 0.9:
                values['other'] = 0.5
                validity['other'] = True
        frames.append(f)
    return frames


class RandomMaps(Model):
    def test_random_maps_and_frames(self):
        rng = random.Random(41)
        counts = {'refused': 0, 'unavailable': 0, 'written': 0, 'failed': 0, 'fast': 0}
        for i in range(5000 if GATE else 300):
            doc = random_map(rng)
            compiled = compile_map(pack_of(doc))
            self.assertTrue(compiled.ok, compiled.report.to_dict())
            frames = random_frames(doc, rng, faults=i % 3 > 0)
            counts['fast'] += compiled.value._core.evaluate_partial(frames) is not None
            with self.subTest(case=i):
                result = self.assertExpected(doc, frames)
                if result.ok:
                    counts['refused'] += len(result.value.refusals)
                    counts['unavailable'] += len(result.value.unavailable)
                    counts['written'] += sum(len(f['values']) for f in result.value.samples)
                else:
                    counts['failed'] += 1
        # The cases reach every outcome.
        self.assertTrue(all(counts.values()), counts)

    def test_output_inputs_of_random_maps(self):
        rng = random.Random(43)
        for _ in range(200):
            doc = random_map(rng)
            compiled = compile_map(pack_of(doc)).value
            expected = {o: tuple(i for i in compiled.required_inputs if i in inputs) for o, (inputs, _) in cones(doc).items()}
            self.assertEqual(dict(compiled.output_inputs), expected)
            self.assertEqual(list(compiled.output_inputs), list(compiled.output_ids))

    def test_oracle_documents_and_samples(self):
        """The random documents and samples of test_core_mapping: odd frames and keys, and compile tweaks."""
        rng = random.Random(23)
        ran = 0
        for _ in range(2000 if GATE else 150):
            doc = random_document(rng)
            samples = random_samples(doc, rng)
            mid = rng.choice(['map'] * 9 + ['other'])
            allow = rng.random() < 0.3
            pack = m.compile_pack(m.validate_authoring(doc).value).value
            compiled = m.compile_mapping(pack, m.profile_snapshot(pack, 'source').value,
                                         m.profile_snapshot(pack, 'target').value, mid, allow)
            if not compiled.ok or allow:
                continue
            ran += 1
            with self.subTest(case=ran):
                self.assertExpected(doc, samples, mid)
        self.assertGreater(ran, 20)


if __name__ == '__main__':
    unittest.main()
