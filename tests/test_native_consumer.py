# SPDX-License-Identifier: MIT
"""Consumer checks of the native pilot's public Python bindings.

Set MSF_NATIVE_PATH to the directory holding the built `_msf_native` module
(CMake does this for its `msf_python_native_consumer` test). Without it the
tests skip; with it, the module must import from exactly that directory.
"""
import gc
import os
from pathlib import Path
import sys
import unittest

import msf_tools as msf

NATIVE_PATH = os.environ.get('MSF_NATIVE_PATH')
native = None
if NATIVE_PATH:
    NATIVE_PATH = Path(NATIVE_PATH).resolve(strict=True)
    sys.path.insert(0, str(NATIVE_PATH))
    import _msf_native as native
    if Path(native.__file__).resolve().parent != NATIVE_PATH:
        raise AssertionError(f'unexpected native import: {native.__file__}')

IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]


@unittest.skipUnless(native is not None, 'MSF_NATIVE_PATH does not point at a built native module')
class NativeConsumer(unittest.TestCase):
    def refusal(self, code, call, *args):
        with self.assertRaisesRegex(ValueError, '^' + code + ': '):
            call(*args)

    def instruction(self, inputs=(0,), output=1, operation=None, scale=1., offset=0., weights=()):
        i = native.Instruction()
        i.inputs = list(inputs); i.output = output
        i.operation = native.Operator.identity if operation is None else operation
        i.scale = scale; i.offset = offset; i.weights = list(weights)
        return i

    def program(self, instruction=None, count=2, bounded=False):
        p = native.ScalarProgram()
        domains = [native.Domain() for _ in range(count)]
        if bounded:
            for d in domains: d.minimum = 0.; d.maximum = 1.
        p.domains = domains
        p.instructions = [self.instruction() if instruction is None else instruction]
        return p

    def mean(self):
        return self.program(self.instruction((0, 1), 2, native.Operator.weighted_sum, weights=(.5, .5)), 3, True)

    def test_full_vector_and_integer_numeric_inputs(self):
        self.assertEqual(native.evaluate_scalars(self.program(), [.25, 0.], [True, False]), [.25, .25])
        self.assertEqual(native.evaluate_scalars(self.program(), [1, 0], [True, False]), [1., 1.])
        self.assertEqual(native.evaluate_scalars(self.mean(), [1, 0, 0], [True, True, False]), [1., 0., .5])

    def test_strict_types_and_atomic_setters(self):
        p = self.program()
        for value in (True, '0.25'):
            self.refusal('type', native.evaluate_scalars, p, [value, 0], [True, False])
        for validity in ([1, False], [True, 0], [True, 'false']):
            self.refusal('type', native.evaluate_scalars, p, [.25, 0], validity)
        for field, good, bad, code in (
            ('scale', .5, True, 'type'), ('scale', .5, '0.5', 'type'),
            ('offset', .5, True, 'type'), ('offset', .5, '0', 'type'),
            ('weights', [.5], [True], 'type'), ('weights', [.5], ['0.5'], 'type'), ('inputs', [0], [True], 'binding'),
            ('output', 1, True, 'binding'), ('operation', native.Operator.identity, 'identity', 'operator'),
        ):
            with self.subTest(field=field):
                i = self.instruction(); setattr(i, field, good)
                self.refusal(code, setattr, i, field, bad)
                self.assertEqual(getattr(i, field), good)
        d = native.Domain()
        for field in ('minimum', 'maximum'):
            setattr(d, field, .5)
            for value in (True, '1', float('nan'), float('inf'), -float('inf'), 10**400):
                self.refusal('type' if type(value) in (bool, str) else 'nonfinite', setattr, d, field, value)
                self.assertEqual(getattr(d, field), .5)
        for field, bad in (('domains', [native.Domain(), True]), ('instructions', [self.instruction(), True])):
            before = len(getattr(p, field)); self.refusal('type', setattr, p, field, bad)
            self.assertEqual(len(getattr(p, field)), before)
        self.assertEqual(native.evaluate_scalars(p, [.25, 0], [True, False]), [.25, .25])

    def test_shapes_bindings_writers_and_instruction_order(self):
        p = self.program()
        for values, validity in (([.25], [True]), ([.25, 0], [True]), ([.25], [True, False])):
            self.refusal('shape', native.evaluate_scalars, p, values, validity)
        cases = [
            ('shape', self.program(self.instruction((0, 1), 2), 3)),
            ('shape', self.program(self.instruction((0, 1), 2, native.Operator.weighted_sum, weights=(.5,)), 3)),
            ('binding', self.program(self.instruction((3,), 2), 3)),
            ('binding', self.program(self.instruction((0,), 3), 3)),
            ('binding', self.program(self.instruction((2,), 2), 3)),
        ]
        for code, p in cases: self.refusal(code, native.evaluate_scalars, p, [1., 0., 0.], [True, False, False])
        p = self.program(); p.instructions = [self.instruction(), self.instruction()]
        self.refusal('binding', native.evaluate_scalars, p, [1., 0.], [True, False])
        p = self.program(count=3); p.instructions = [self.instruction((2,), 1), self.instruction((0,), 2)]
        self.refusal('cycle', native.evaluate_scalars, p, [1., 0., 0.], [True, False, False])
        p.instructions = [self.instruction((0,), 2), self.instruction((2,), 1)]
        self.assertEqual(native.evaluate_scalars(p, [1., 0., 0.], [True, False, False]), [1., 1., 1.])
        for index in (True, -1, 1.0, '1', 10**400):
            self.refusal('binding', setattr, self.instruction(), 'output', index)
            self.refusal('binding', setattr, self.instruction(), 'inputs', [index])
        d = native.Domain(); d.minimum = 1.; d.maximum = 0.
        p = self.program(); p.domains = [d, native.Domain()]
        self.refusal('domain', native.evaluate_scalars, p, [1., 0.], [True, False])

    def test_large_finite_nonfinite_and_overflow(self):
        self.assertEqual(native.evaluate_scalars(self.program(), [1.5e308, 0], [True, False]), [1.5e308, 1.5e308])
        p = self.program(self.instruction(operation=native.Operator.affine, scale=.5, offset=.5))
        self.assertEqual(native.evaluate_scalars(p, [1.5e308, 0], [True, False]), [1.5e308, 7.5e307])
        p = self.program(self.instruction(operation=native.Operator.affine, scale=2.))
        self.refusal('nonfinite', native.evaluate_scalars, p, [1.5e308, 0], [True, False])
        for weights, values in (((1., 1.), [1e308, 1e308, 0]), ((1e308, 1e308), [2., 2., 0])):
            p = self.program(self.instruction((0, 1), 2, native.Operator.weighted_sum, weights=weights), 3)
            self.refusal('nonfinite', native.evaluate_scalars, p, values, [True, True, False])
        for value in (float('nan'), float('inf'), -float('inf'), 10**400):
            self.refusal('nonfinite', native.evaluate_scalars, self.program(), [value, 0], [True, False])
            for field in ('scale', 'offset', 'weights'):
                i = self.instruction(); before = getattr(i, field)
                self.refusal('nonfinite', setattr, i, field, [value] if field == 'weights' else value)
                self.assertEqual(getattr(i, field), before)

    def test_every_slot_is_checked_and_required_inputs_are_valid(self):
        for value in (float('nan'), float('inf'), -float('inf'), 10**400):
            self.refusal('nonfinite', native.evaluate_scalars, self.program(), [.25, value], [True, False])
        self.refusal('invalid_sample', native.evaluate_scalars, self.program(), [.25, 0], [False, False])
        self.assertEqual(native.evaluate_scalars(self.program(), [.25, 99], [True, False]), [.25, .25])
        p = self.program(count=3)
        self.refusal('nonfinite', native.evaluate_scalars, p, [.25, 0, float('nan')], [True, False, False])
        self.assertEqual(native.evaluate_scalars(p, [.25, 0, -3], [True, False, False]), [.25, .25, -3.])

    def test_caller_outer_nested_and_returned_values_are_copies(self):
        domains = [native.Domain() for _ in range(3)]
        for d in domains: d.minimum = 0.; d.maximum = 1.
        inputs = [0, 1]; weights = [.5, .5]
        i = native.Instruction(); i.inputs = inputs; i.output = 2
        i.operation = native.Operator.weighted_sum; i.weights = weights
        p = native.ScalarProgram(); p.domains = domains; p.instructions = [i]
        inputs[0] = 2; weights[0] = 2.
        self.assertEqual(i.inputs, [0, 1])
        self.assertEqual(i.weights, [.5, .5])
        domains[0].maximum = .1; i.weights = [2., 2.]
        self.assertEqual(native.evaluate_scalars(p, [1., 0., 0.], [True, True, False]), [1., 0., .5])
        outer_d = p.domains; outer_i = p.instructions; outer_d.clear(); outer_i.clear()
        self.assertEqual(native.evaluate_scalars(p, [1., 0., 0.], [True, True, False]), [1., 0., .5])
        nested_d = p.domains[0]; nested_i = p.instructions[0]
        nested_d.maximum = .1; nested_i.inputs = [1, 0]; nested_i.output = 1
        nested_i.scale = 2.; nested_i.offset = 2.; nested_i.weights = [2., 2.]
        values = [1., 0., 0.]; validity = [True, True, False]
        output = native.evaluate_scalars(p, values, validity); output[2] = 99.
        self.assertEqual((values, validity), ([1., 0., 0.], [True, True, False]))
        self.assertEqual(native.evaluate_scalars(p, values, validity), [1., 0., .5])
        del domains, i, inputs, weights; gc.collect()
        self.assertEqual(native.evaluate_scalars(p, values, validity), [1., 0., .5])
        retained_d = p.domains[0]; retained_i = p.instructions[0]; retained_output = native.evaluate_scalars(p, values, validity)
        del p; gc.collect()
        self.assertEqual((retained_d.maximum, retained_i.weights, retained_output), (1., [.5, .5], [1., 0., .5]))
        retained_d.maximum = .2; retained_i.weights = [1., 0.]; retained_output.clear()

    def test_old_getters_survive_vector_replacement_and_clear(self):
        p = self.mean(); old_d = p.domains[0]; old_i = p.instructions[0]
        p.domains = [native.Domain() for _ in range(4)]; p.instructions = [self.instruction((0,), 3)]
        old_d.maximum = .1; old_i.weights = [2., 2.]
        self.assertEqual(native.evaluate_scalars(p, [1., 0., 0., 0.], [True, False, False, False]), [1., 0., 0., 1.])
        p.domains = []; p.instructions = []
        old_d.minimum = -.1; old_i.inputs = [1, 0]
        p.domains = [native.Domain(), native.Domain()]; p.instructions = [self.instruction()]
        self.assertEqual(native.evaluate_scalars(p, [.25, 0.], [True, False]), [.25, .25])
        self.assertEqual((old_d.maximum, old_i.weights), (.1, [2., 2.]))

    def test_matrix_order_storage_and_projective_refusal(self):
        parent = [2., 0., 0., 0., 0., 3., 0., 0., 0., 0., 4., 0., 0., 0., 0., 1.]
        child = [1., 0., 0., 8., 0., 1., 0., 9., 0., 0., 1., 12., 0., 0., 0., 1.]
        expected = [.5, 0., 0., 4., 0., 1/3, 0., 3., 0., 0., .25, 3., 0., 0., 0., 1.]
        result = native.reparent_local(parent, child)
        self.assertEqual(len(result), 16)
        for actual, value in zip(result, expected): self.assertLessEqual(abs(actual - value), 8 * 2**-52 * max(1., abs(value)))
        self.assertEqual(native.transform_point(result, [2., 3., 4.]), [5., 4., 4.])
        child_column = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 8., 9., 12., 1.]
        self.assertEqual(native.from_gltf_column_major(child_column), child)
        self.assertEqual(native.to_gltf_column_major(child), child_column)
        pure = msf.reparent_local(child_column, parent)
        self.assertTrue(pure.ok, pure.report.to_dict())
        for actual, value in zip(native.from_gltf_column_major(pure.value), expected):
            self.assertLessEqual(abs(actual - value), 8 * 2**-52 * max(1., abs(value)))
        projective = IDENTITY.copy(); projective[12] = 1.
        self.refusal('nonaffine', native.transform_point, projective, [0., 0., 0.])
        self.refusal('nonaffine', native.reparent_local, projective, projective)
        self.refusal('nonaffine', native.skin_positions, [[0., 0., 0.]], [[0, 0, 0, 0]], [[1., 0., 0., 0.]],
                     IDENTITY, [projective], [projective])
        self.refusal('nonaffine', native.skin_positions, [[0., 0., 0.]], [[0, 0, 0, 0]], [[1., 0., 0., 0.]],
                     IDENTITY, [IDENTITY, projective], [IDENTITY, IDENTITY])

    def test_huge_axes_nonfinite_and_multiply_overflow(self):
        h = 1.5e308
        huge_axes = [h, h, 0., 0., h, h, 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
        self.refusal('nonfinite', native.reparent_local, IDENTITY, huge_axes)
        for value in (float('nan'), float('inf'), -float('inf')):
            bad = IDENTITY.copy(); bad[0] = value
            self.refusal('nonfinite', native.multiply, bad, IDENTITY)
        left = IDENTITY.copy(); left[0] = h
        right = IDENTITY.copy(); right[0] = 2.
        self.refusal('nonfinite', native.multiply, left, right)


if __name__ == '__main__':
    unittest.main()
