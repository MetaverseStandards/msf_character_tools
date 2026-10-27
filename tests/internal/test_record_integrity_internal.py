# SPDX-License-Identifier: MIT
"""Record integrity through private state: the numeric predicate, the factory token and core handles."""
from types import MappingProxyType
import unittest
from unittest import mock

import msf_tools as m
from msf_tools.common import number
import test_record_integrity as integrity


class NumericMetadataTests(unittest.TestCase):
    def test_total_binary64_numeric_predicate(self):
        cases = [(10**400, False), (-(10**400), False), (True, False), (float('nan'), False),
                 (float('inf'), False), (10**300, True), (-1, True), (1.5, True)]
        for value, expected in cases:
            with self.subTest(type=type(value).__name__, expected=expected):
                self.assertIs(number(value), expected)


class FactoryToken(unittest.TestCase):
    def test_a_copy_built_with_the_factory_token_cannot_compile_or_export(self):
        validated = m.validate_authoring(integrity.document()).value
        copy = type(validated)(integrity.document(), validated._token)
        integrity.IntegrityTests.rejected(self, m.compile_pack(copy))
        integrity.IntegrityTests.refuses_export(self, copy.to_dict)


class CoreHandleTests(unittest.TestCase):
    setUp = integrity.IntegrityTests.setUp
    good = integrity.IntegrityTests.good
    rejected = integrity.IntegrityTests.rejected
    refuses_export = integrity.IntegrityTests.refuses_export

    def test_equal_copies_of_handle_views_are_rejected(self):
        # A view is bound to its handle by identity: an equal copy is still a substitution.
        copies = [(self.validated, 'document', lambda r: m.compile_pack(r)),
                  (self.pack, 'document', lambda r: m.profile_snapshot(r, 'source')),
                  (self.compiled, 'instructions', lambda r: m.evaluate_mapping(r, self.frames)),
                  (self.compiled, 'required_inputs', lambda r: m.evaluate_mapping(r, self.frames)),
                  (self.compiled, 'output_ids', lambda r: m.evaluate_mapping(r, self.frames))]
        for record, name, use in copies:
            with self.subTest(record=type(record).__name__, view=name):
                view = getattr(record, name)
                copy = MappingProxyType(dict(view)) if isinstance(view, MappingProxyType) else tuple(list(view))
                self.assertEqual(copy, view)
                object.__setattr__(record, name, copy)
                self.rejected(use(record))
                self.refuses_export(record.to_dict)
                object.__setattr__(record, name, view)
                record.to_dict()

    def test_equal_copies_of_snapshot_and_geometry_views_are_rejected(self):
        glb = self.good(m.inspect_asset((integrity.ROOT / 'tests/public/fixtures/combined.glb').read_bytes(), 'glb'))
        geometry = self.good(m.evaluate_geometry(self.asset))
        mapping = lambda r: m.compile_mapping(self.pack, self.source, r, 'wink')
        copies = [(self.asset, 'document', m.evaluate_geometry), (self.asset, 'resources', m.evaluate_geometry),
                  (self.asset, 'original_bytes', m.evaluate_geometry), (glb, 'chunks', m.evaluate_geometry),
                  (self.bound, 'channels', mapping), (self.bound, 'bindings', mapping),
                  (self.source, 'document', lambda r: m.compile_mapping(self.pack, r, self.target, 'wink')),
                  (self.source, 'channels', lambda r: m.compile_mapping(self.pack, r, self.target, 'wink')),
                  (geometry, 'instances', None)]
        for record, name, use in copies:
            with self.subTest(record=type(record).__name__, view=name):
                view = getattr(record, name)
                copy = (MappingProxyType(dict(view)) if isinstance(view, MappingProxyType)
                        else bytes(bytearray(view)) if isinstance(view, bytes) else tuple(list(view)))
                self.assertEqual(copy, view)
                self.assertIsNot(copy, view)
                object.__setattr__(record, name, copy)
                if use is not None:
                    self.rejected(use(record))
                self.refuses_export(record.to_dict)
                object.__setattr__(record, name, view)
                record.to_dict()

    def test_equal_copies_of_resource_and_chunk_fields_are_rejected(self):
        glb = self.good(m.inspect_asset((integrity.ROOT / 'tests/public/fixtures/combined.glb').read_bytes(), 'glb'))
        for item, name in [(glb.resources[0], 'data'), (glb.resources[0], 'sha256'), (glb.chunks[0], 'data')]:
            with self.subTest(item=type(item).__name__, field=name):
                value = getattr(item, name)
                copy = bytes(bytearray(value)) if isinstance(value, bytes) else ''.join(list(value))
                self.assertEqual(copy, value)
                object.__setattr__(item, name, copy)
                self.rejected(m.decode_accessor(glb, 0))
                object.__setattr__(item, name, value)
                self.good(m.decode_accessor(glb, 0))

    def test_a_compiled_mapping_moved_to_another_pack_is_rejected(self):
        other = self.good(m.compile_pack(self.good(m.validate_authoring(integrity.document()))))
        object.__setattr__(self.compiled, '_core', self.good(m.compile_mapping(other, self.good(m.profile_snapshot(other, 'source')),
                                                                                self.good(m.profile_snapshot(other, 'target')), 'wink'))._core)
        self.rejected(m.evaluate_mapping(self.compiled, self.frames))

    def test_changed_sample_views_are_rejected(self):
        values = self.good(m.evaluate_mapping(self.compiled, self.frames))
        self.assertIsNotNone(values._core)
        frame = values.samples[0]
        def rebuilt(**change):
            parts = {**frame, **change}
            return (MappingProxyType(parts),)
        changes = {'value': rebuilt(values=MappingProxyType({'output.wink': -.25})),
                   'integer value': rebuilt(values=MappingProxyType({'output.wink': -1})),
                   'signed zero timestamp': rebuilt(timestamp=-0.0),
                   'validity': rebuilt(validity=MappingProxyType({'output.wink': 1})),
                   'extra frame': (frame, frame), 'no frames': (), 'list': [frame],
                   'plain dict frame': ({**frame},)}
        for name, samples in changes.items():
            with self.subTest(name):
                object.__setattr__(values, 'samples', samples)
                self.refuses_export(values.to_dict)
        object.__setattr__(values, 'samples', (frame,))
        self.assertEqual(values.to_dict()['samples'][0]['values'], {'output.wink': -.5})


if __name__ == '__main__':
    unittest.main()
