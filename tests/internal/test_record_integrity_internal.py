# SPDX-License-Identifier: MIT
"""Record integrity through private state: the finite-number predicate and the factory token."""
import unittest

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


if __name__ == '__main__':
    unittest.main()
