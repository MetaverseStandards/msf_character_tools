# SPDX-License-Identifier: MIT
"""Record integrity through private state: the numeric predicate, the factory token and core handles."""
import os
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest import mock

import msf_tools as m
from msf_tools import _native
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


@unittest.skipIf(_native.core is None and os.environ.get('MSF_REQUIRE_CORE') != '1', 'C++ core not built')
class CoreHandleTests(unittest.TestCase):
    setUp = integrity.IntegrityTests.setUp
    good = integrity.IntegrityTests.good
    rejected = integrity.IntegrityTests.rejected
    refuses_export = integrity.IntegrityTests.refuses_export

    def test_views_whose_canonical_bytes_differ_from_the_handle_are_not_admitted(self):
        core = _native.core
        rewrites = {'indent': lambda raw: raw.replace(b'\n  ', b'\n '), 'trailing space': lambda raw: raw + b' ',
                    'string escape': lambda raw: raw.replace(b'"mapped"', b'"m\\u0061pped"')}
        for name, rewrite in rewrites.items():
            with self.subTest(name):
                self.assertNotEqual(rewrite(self.compiled._core.document()), self.compiled._core.document())
                stand_in = SimpleNamespace(compile=lambda spec: core.compile({**spec, 'document': rewrite(spec['document'])}))
                with mock.patch.object(_native, 'core', stand_in):
                    self.rejected(m.compile_mapping(self.pack, self.source, self.target, 'wink'))

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
