# SPDX-License-Identifier: MIT
"""The source helpers in the core against the 0.3.0 oracle: the path grammar,
matrix decomposition, influence rows and the GLB writer. MSF_GATE=1 runs more cases."""
import os
import random
import unittest

from internal import oracle, source_cases

GATE = os.environ.get('MSF_GATE') == '1'


@unittest.skipIf(oracle.skip_reason(), oracle.skip_reason() or '')
class AgainstTheOracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        oracle.define(source_cases.DEFINITIONS)

    def assertSame(self, cases):
        self.assertEqual(oracle.outcome(*cases[0])[0], 'value', oracle.outcome(*cases[0]))
        differing = oracle.differ(cases)
        self.assertEqual(differing[:2], [], f'{len(differing)} of {len(cases)} cases differ')

    def test_path_grammar(self):
        rng = random.Random(51)
        cases = [('path_battery(name, components, helper, candidate)',
                  dict(zip(('name', 'components', 'helper', 'candidate'), case)))
                 for case in source_cases.path_cases(rng, 20000 if GATE else 300)]
        self.assertSame(cases)

    def test_matrix_decomposition(self):
        rng = random.Random(57)
        batches = [[source_cases.matrix(rng) for _ in range(20)] for _ in range(1000 if GATE else 20)]
        self.assertSame([('transform_battery(matrices)', {'matrices': batch}) for batch in batches])

    def test_influence_rows(self):
        rng = random.Random(59)
        self.assertSame([('skinning_battery(rows, root, mode)', dict(zip(('rows', 'root', 'mode'), case)))
                         for case in source_cases.influence_cases(rng, 20000 if GATE else 300)])

    def test_path_order(self):
        rng = random.Random(53)
        candidates = ['/' + '/'.join(source_cases.text(rng) for _ in range(rng.randint(1, 3))) for _ in range(2000 if GATE else 200)]
        self.assertSame([('path_order(candidates)', {'candidates': candidates})])


if __name__ == '__main__':
    unittest.main()
