# SPDX-License-Identifier: MIT
"""Example checks that use the ufbx shim itself as the oracle."""
from pathlib import Path
import tempfile
import unittest

from make_example_fbx import OUTPUT as CUBE_FBX, morph_cube_fbx
from internal.test_source_fbx_native import HAVE_UFBX, open_scene
from test_examples import ASSETS, ExampleChecks, PRESENT, floats, run, same_points


def ufbx_world(data, stack=None, seconds=0.0):
    """ufbx's own evaluation of every mesh, skinning and blend shapes included, in world space, mesh after mesh."""
    from msf_tools_ufbx import ffi, lib
    handle, error = open_scene(data)
    assert handle, error
    try:
        index = -1
        if stack is not None:
            record = ffi.new('msf_fbx_stack *')
            names = []
            while lib.msf_fbx_stack_get(handle, len(names), record):
                names.append(ffi.unpack(record.name, record.name_len).decode())
            index = names.index(stack)
        info = ffi.new('msf_fbx_info *')
        lib.msf_fbx_info_get(handle, info)
        points = []
        for mesh in range(info.meshes):
            sizes = ffi.new('uint32_t[8]')
            lib.msf_fbx_mesh_sizes(handle, mesh, sizes)
            out, text = ffi.new('double[]', 3 * sizes[0] or 1), ffi.new('char[256]')
            assert lib.msf_fbx_skinned_points(handle, index, seconds, mesh, out, sizes[0], text, 256), ffi.string(text)
            points += [tuple(out[3 * v:3 * v + 3]) for v in range(sizes[0])]
        return points
    finally:
        lib.msf_fbx_close(handle)


@unittest.skipUnless(PRESENT and HAVE_UFBX, 'needs MSF_EXAMPLE_ASSETS and msf-tools-ufbx')
class FbxExample(ExampleChecks):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'fbx'
        run('fbx_character.py', cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_kenney_character_walk_matches_ufbx_skinning(self):
        summary, render = self.outputs(self.out / 'character')
        self.assertEqual((summary['asset']['sha256'], summary['asset']['format'], summary['asset']['license']),
                         ('961d8957c4ef36025b9ba1bdee13b3f0c8f860907cd1474dab74b42290e144cc', 'fbx', 'CC0-1.0'))
        self.assertIn('Creative Commons Zero, CC0', (ASSETS / 'Kenney-Mini-Characters-License.txt').read_text())
        self.assertEqual([d['code'] for d in summary['inspect']['declared_losses']], ['I_UNITS_CONVERTED', 'W_ANIMATIONS_SKIPPED', 'W_SKIPPED'])
        self.assertEqual((summary['binding']['refused'], summary['inspect']['skins']), ('E_BINDING_REFERENCE', 2))
        self.mapped(summary)
        data = (ASSETS / 'character-female-a.fbx').read_bytes()
        for name, seconds in (('walk_0.1', 0.1), ('walk_0.25', 0.25), ('walk_0.5', 0.5)):
            same_points(self, floats(render / f'{name}.f32'), ufbx_world(data, 'walk', seconds), 1e-6, name)

    def test_the_writer_made_cube_shape_key_matches_ufbx_at_each_mapped_weight(self):
        glb = (ASSETS / 'AnimatedMorphCube.glb').read_bytes()
        self.assertEqual(CUBE_FBX.read_bytes(), morph_cube_fbx(glb))
        summary, render = self.outputs(self.out / 'morph_cube')
        self.assertIn('not a DCC export', summary['asset']['credit'])
        self.assertEqual((summary['binding']['label'], summary['binding']['node_path']), ('thin', '/AnimatedMorphCube'))
        self.mapped(summary)
        for pose, weight in (('jaw_open_0', 0.0), ('jaw_open_0.5', 0.4), ('jaw_open_1', 0.8)):
            self.close(floats(render / f'{pose}.f32'), ufbx_world(morph_cube_fbx(glb, (100 * weight, 0.0))), pose)


if __name__ == '__main__':
    unittest.main()
