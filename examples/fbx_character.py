# SPDX-License-Identifier: MIT
"""FBX example: a skinned Kenney character (CC0) and a shape-key cube written by msf-tools' FBX test writer.

    python fbx_character.py [--assets DIR] [--out DIR]

Needs msf-tools-ufbx (see the README). The character is `character-female-a.fbx`
from Kenney's Mini Characters pack, exported with the Autodesk FBX SDK, fetched
by fetch_assets.py. It has 32 animation stacks and no shape keys, so the binding
is refused and the poses come from its `walk` stack. The cube is the Khronos
AnimatedMorphCube (CC0) written to FBX by the test writer
(tests/public/make_example_fbx.py, committed as data/AnimatedMorphCube.writer.fbx): it
shows the shape-key binding, but it is not a DCC export.
"""
import hashlib

from example_pipeline import HERE, arguments, run

CHARACTER = {
    'name': 'Kenney Mini Characters, character-female-a', 'file': 'character-female-a.fbx', 'format': 'fbx',
    'url': 'https://kenney.nl/assets/mini-characters', 'revision': 'kenney_mini-characters.zip 1.0, sha256 9e1d48e6d7b8479e',
    'sha256': '961d8957c4ef36025b9ba1bdee13b3f0c8f860907cd1474dab74b42290e144cc',
    'license': 'CC0-1.0', 'credit': 'Kenney (www.kenney.nl); exported with the Autodesk FBX SDK 2020.3.2.',
}

if __name__ == '__main__':
    args = arguments('fbx', __doc__)
    root = args.out
    args.out = root / 'character'
    run(args, name='fbx_character', data=(args.assets / CHARACTER['file']).read_bytes(), fmt='fbx', asset=CHARACTER,
        options={'animation': 'walk'}, clips=[('walk_0.1', 0, 0.1), ('walk_0.25', 0, 0.25), ('walk_0.5', 0, 0.5)])
    cube = (HERE / 'data' / 'AnimatedMorphCube.writer.fbx').read_bytes()
    args.out = root / 'morph_cube'
    run(args, name='fbx_morph_cube', data=cube, fmt='fbx', binding=('/AnimatedMorphCube', 0, 'thin'), asset={
        'name': 'AnimatedMorphCube as FBX', 'file': 'data/AnimatedMorphCube.writer.fbx', 'format': 'fbx',
        'sha256': hashlib.sha256(cube).hexdigest(), 'license': 'CC0-1.0',
        'credit': "Microsoft, 2017 (Khronos glTF-Sample-Assets); written to FBX by msf-tools' test FBX writer, not a DCC export.",
    })
