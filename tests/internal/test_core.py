# SPDX-License-Identifier: MIT
"""The C++ core against the pure-Python reference, through the public API.

Each case evaluates with the core and with msf_tools._native.core set to None,
and requires the same diagnostics and bit-identical, same-typed samples.
"""
import math
import os
import random
import struct
import unittest
from types import MappingProxyType, SimpleNamespace
from unittest import mock

import msf_tools as m
from msf_tools import _native
from msf_tools.report import Fault
import test_operators_1_1 as ops

REQUIRED = os.environ.get('MSF_REQUIRE_CORE') == '1'


def build(doc):
    pack = m.compile_pack(m.validate_authoring(doc).value).value
    source, target = m.profile_snapshot(pack, 'source').value, m.profile_snapshot(pack, 'target').value
    return m.compile_mapping(pack, source, target, 'map').value


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


@unittest.skipIf(_native.core is None and not REQUIRED, 'C++ core not built')
class CoreTests(unittest.TestCase):
    def assertSameAsReference(self, doc, samples):
        compiled = build(doc)
        with mock.patch.object(_native, 'core', None):
            reference = build(doc)
            expected = m.evaluate_mapping(reference, samples)
        self.assertEqual(compiled.to_dict(), reference.to_dict())
        self.assertTrue(same(compiled.instructions, reference.instructions), (compiled.instructions, reference.instructions))
        actual = m.evaluate_mapping(compiled, samples)
        self.assertEqual(actual.report.to_dict(), expected.report.to_dict())
        if expected.ok:
            self.assertTrue(same(actual.value.samples, expected.value.samples), (actual.value.samples, expected.value.samples))
            self.assertEqual(actual.value.to_dict(), expected.value.to_dict())
        return actual

    def test_affine_does_not_fuse_multiply_add(self):
        # Fused, (1 + 2**-30) * (1 - 2**-30) - 1 is -2**-60; rounded first, it is exactly 0.
        result = self.assertSameAsReference(affine(1 + 2**-30, -1), [frame({'in': 1 - 2**-30})])
        self.assertIsNotNone(result.value._core, 'evaluation did not take the core path')
        self.assertTrue(same(result.value.samples[0]['values']['out'], 0.0))

    def test_signed_zero_coefficients_keep_their_sign(self):
        result = self.assertSameAsReference(affine(1, -0.0, low=-1, high=1), [frame({'in': -0.0})])
        self.assertIsNotNone(result.value._core)
        self.assertTrue(same(result.value.samples[0]['values']['out'], -0.0))
        knots = [[0, 1.59], [7.9e299, 1.13], [1e300, -0.0]]
        result = self.assertSameAsReference(ops.document(knots, low=0, high=1e300, out_low=-1, out_high=2), [frame({'in': 1e300})])
        self.assertIsNotNone(result.value._core)
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
                result = self.assertSameAsReference(doc, [frame(values)])
                self.assertEqual([d.code for d in result.report.diagnostics], ['E_NONFINITE'])
        result = self.assertSameAsReference(unbounded(affine(2, 0), 'in', 'out'), [frame({'in': 8e307})])
        self.assertIsNotNone(result.value._core, 'a large finite result should stay on the core path')

    def test_gaze_matches_reference_bit_for_bit(self):
        rng = random.Random(7)
        specials = [0, 1, 0.5, -0.0, 0.0, 1.0, 2**-1074, 1 - 2**-53, math.nextafter(0.5, 1)]
        samples = []
        for i in range(400):
            look_in, look_out = (rng.choice(specials) if rng.random() < 0.3 else rng.random() for _ in range(2))
            samples.append(frame({'look_in': look_in, 'look_out': look_out}, rng.choice([i, i / 60])))
        result = self.assertSameAsReference(ops.gaze(), samples)
        self.assertIsNotNone(result.value._core)

    def test_piecewise_segments_and_knots_match_reference(self):
        knots = [[-1, 0], [-0.3, 0.1], [0.2, 0.1], [0.7, 0.9], [1, 1]]
        rng = random.Random(11)
        xs = [k[0] for k in knots] + [math.nextafter(k[0], 0) for k in knots] + [rng.uniform(-1, 1) for _ in range(300)]
        self.assertSameAsReference(ops.document(knots), [frame({'in': x}) for x in xs])
        self.assertSameAsReference(ops.document([[-1, 1], [1, -1]], out_low=-1), [frame({'in': x}) for x in xs])

    def test_samples_outside_the_fast_path_keep_reference_diagnostics(self):
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
            'proxy frame': [good, MappingProxyType(frame({'in': 0.5}))],
            'tuple samples': (good, frame({'in': 0.5})),
            'integer values': [frame({'in': 0}), frame({'in': -1}, 3)],
            'empty': [],
        }
        for name, samples in cases.items():
            with self.subTest(name):
                self.assertSameAsReference(doc, samples)

    def test_checked_arithmetic_refusals_fall_back_to_reference(self):
        big = 1.5e308
        self.assertSameAsReference(affine(2, 0, high=big, out_low=-big, out_high=big),
                                   [frame({'in': big})])
        self.assertSameAsReference(affine(2**-600, 0, high=1, out_low=0), [frame({'in': 2**-600})])
        self.assertSameAsReference(affine(1, 0.5), [frame({'in': 0.25}), frame({'in': 1})])


def captured_spec(doc):
    """The spec compile_mapping hands to _core.compile for doc."""
    specs = []
    core = _native.core
    stand_in = SimpleNamespace(**{**vars(core), 'compile': lambda spec: specs.append(spec) or core.compile(spec)})
    with mock.patch.object(_native, 'core', stand_in):
        build(doc)
    return specs[0]


JUNK = [None, True, -1, 2**70, 1.5, math.nan, 'x', b'x', (), [], {}, (1,), [0], ('affine',), 10**6]


def malformed(spec, rng):
    """spec with one value replaced, dropped, shortened or lengthened somewhere inside it."""
    spec = {k: list(v) if isinstance(v, list) else v for k, v in spec.items()}
    key = rng.choice(list(spec) + ['extra'])
    choice = rng.randrange(4)
    if key == 'extra' or choice == 0:
        spec.pop(key, None) if key != 'extra' else spec.update(extra=1)
    elif isinstance(spec[key], list) and spec[key] and choice < 3:
        items = spec[key]
        i = rng.randrange(len(items))
        if isinstance(items[i], tuple):
            parts = list(items[i])
            j = rng.randrange(len(parts) + 1)
            if choice == 1:
                parts = parts[:j]
            else:
                parts[j % len(parts)] = rng.choice(JUNK + [(True, 0.0), (False, 0.0, False, 0.0, 1)])
            items[i] = tuple(parts)
        else:
            items[i] = rng.choice(JUNK)
    else:
        spec[key] = rng.choice(JUNK)
    return spec


@unittest.skipIf(_native.core is None and not REQUIRED, 'C++ core not built')
class CompileBoundary(unittest.TestCase):
    def test_malformed_program_specs_raise_internal_faults(self):
        rng = random.Random(9)
        specs = [captured_spec(ops.gaze()), captured_spec(affine(2, 1)), captured_spec(ops.document([[-1, 0], [0.5, 0.2], [1, 1]]))]
        refused = 0
        for _ in range(1500):
            spec = malformed(rng.choice(specs), rng)
            try:
                program = _native.core.compile(spec)
            except Fault as exc:
                self.assertEqual(exc.diagnostic.code, 'E_INTERNAL', exc.diagnostic)
                refused += 1
                continue
            # Whatever compiles must evaluate safely.
            program.evaluate([frame({'look_in': 0.5, 'look_out': 0.25})])
            program.evaluate([frame({'in': 0.5})])
        self.assertGreater(refused, 1000)
        for bad in (None, [], 'spec', {'document': b''}):
            with self.subTest(spec=bad), self.assertRaises(Fault):
                _native.core.compile(bad)


if __name__ == '__main__':
    unittest.main()
