# SPDX-License-Identifier: MIT
"""The 09K recipe that watches private geometry internals (world matrices and skin palettes)."""
import unittest
from unittest import mock

import msf_tools as m
from msf_tools import geometry, math3d
import test_real_assets as recipes


@unittest.skipUnless(recipes.PRESENT, 'set MSF_REAL_ASSETS to a local copy of the 09K harness inputs to run this tier')
class RealAssetInternals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.x = recipes.Inputs.get()

    def test_F_WORLD_PALETTE_WITNESSES(self):
        tolerance = self.x.expect['Fox']
        worlds, palettes = [], {}
        real_worlds, real_skin = geometry._worlds, geometry._skin

        def capture_worlds(*args):
            result = real_worlds(*args)
            worlds.append(result)
            return result

        def capture_skin(positions, joints, weights, mesh_inverse, node_worlds, skin_joints, ibms, ref):
            # The palettes the core builds: one per joint index with a nonzero weight.
            for vertex_joints, vertex_weights in zip(joints, weights):
                for j, w in zip(vertex_joints, vertex_weights):
                    if w and j not in palettes:
                        palettes[j] = math3d.multiply(math3d.multiply(mesh_inverse, node_worlds[skin_joints[j]]), ibms[j])
            return real_skin(positions, joints, weights, mesh_inverse, node_worlds, skin_joints, ibms, ref)

        with mock.patch.object(geometry, '_worlds', capture_worlds), mock.patch.object(geometry, '_skin', capture_skin):
            self.assertTrue(m.evaluate_geometry(self.x.fox).ok)
        case = self.x.oracle('Fox')['cases'][0]
        self.assertEqual(len(worlds), 1)
        self.assertEqual(len(worlds[0]), 26)

        def check_matrix(actual_rows, wanted_columns, where):
            wanted = math3d.matrix(wanted_columns)
            for r in range(4):
                for c in range(4):
                    key = 'matrix_translation' if c == 3 and r < 3 else 'matrix_linear_and_affine_bottom_row'
                    a, w = actual_rows[r][c], wanted[r][c]
                    self.assertLessEqual(abs(a - w), tolerance[key]['absolute'] + tolerance[key]['relative'] * abs(w), where)

        for node, wanted in case['node_world_matrices_column_major'].items():
            check_matrix(worlds[0][int(node)], wanted, ('world', node))
        oracle = case['skin_palettes'][0]
        positive = self.x.matrix['Fox_palette_scope']['positive_weight_palette_indices']
        constructed = [p for p in palettes.values() if len(p) == 4]
        self.assertEqual(len(constructed), len(positive))
        for index in positive:
            wanted = math3d.matrix(oracle['matrices_column_major'][index])
            self.assertTrue(any(all(abs(p[r][c] - wanted[r][c]) <= 2e-10 + 2e-12 * abs(wanted[r][c]) for r in range(4) for c in range(4))
                                for p in constructed), index)
        # Indices 0 and 1 carry no positive weight, so ordinary geometry never builds them; probe them separately.
        document = self.x.fox.document
        ibms = m.decode_accessor(self.x.fox, document['skins'][0]['inverseBindMatrices']).value
        mesh_world = worlds[0][1]
        for index in self.x.matrix['Fox_palette_scope']['unused_palette_indices']:
            joint = document['skins'][0]['joints'][index]
            probe = math3d.multiply(math3d.multiply(math3d.inverse(mesh_world), worlds[0][joint]), math3d.matrix(ibms[index]))
            check_matrix(probe, oracle['matrices_column_major'][index], ('unused palette', index))


if __name__ == '__main__':
    unittest.main()
