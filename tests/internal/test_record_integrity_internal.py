# SPDX-License-Identifier: MIT
"""The private finite-number predicate behind record integrity."""
import unittest

from msf_tools.common import number


class NumericMetadataTests(unittest.TestCase):
    def test_total_binary64_numeric_predicate(self):
        cases = [(10**400, False), (-(10**400), False), (True, False), (float('nan'), False),
                 (float('inf'), False), (10**300, True), (-1, True), (1.5, True)]
        for value, expected in cases:
            with self.subTest(type=type(value).__name__, expected=expected):
                self.assertIs(number(value), expected)


if __name__ == '__main__':
    unittest.main()
