# SPDX-License-Identifier: MIT
"""glTF example: the Khronos Fox (skinning, three clips) and AnimatedMorphCube (morph targets).

    python gltf_fox.py [--assets DIR] [--out DIR]

The Fox has no morph targets, so binding a signal to it is refused and the
mapping runs against the example pack's own target profile; its poses come from
its clips. The morph cube shows the whole chain: the mapped value drives its
first morph target.
"""
from example_pipeline import arguments, run

REVISION = '8f492390ddc7a2ae221a1369ef560589cf8c70fb'
KHRONOS = f'https://github.com/KhronosGroup/glTF-Sample-Assets/tree/{REVISION}/Models'
FOX = {
    'name': 'Fox', 'file': 'Fox.glb', 'format': 'glb', 'url': f'{KHRONOS}/Fox', 'revision': REVISION,
    'sha256': 'd97044e701822bac5a62696459b27d7b375aada5de8574ed4362edbba94771f7',
    'license': 'CC0-1.0 AND CC-BY-4.0',
    'credit': 'Model: PixelMannen (CC0). Rigging and animation: tomkranis (CC-BY 4.0). '
              'glTF conversion: @AsoboStudio and @scurest (CC-BY 4.0).',
}
CUBE = {
    'name': 'AnimatedMorphCube', 'file': 'AnimatedMorphCube.glb', 'format': 'glb', 'url': f'{KHRONOS}/AnimatedMorphCube',
    'revision': REVISION,
    'sha256': '214ee56160a50dbf22543a1d66dbf860986e87f0efac3d89feac1359d0e6aeab',
    'license': 'CC0-1.0', 'credit': 'Microsoft, 2017',
}

if __name__ == '__main__':
    args = arguments('gltf', __doc__)
    root = args.out
    args.out = root / 'fox'
    run(args, name='fox', data=(args.assets / FOX['file']).read_bytes(), fmt='glb', asset=FOX,
        clips=[('survey_0.137', 0, 0.137), ('survey_end', 0, 3.4166667461395264), ('walk_0.35', 1, 0.35), ('run_0.6', 2, 0.6)])
    args.out = root / 'morph_cube'
    run(args, name='morph_cube', data=(args.assets / CUBE['file']).read_bytes(), fmt='glb', asset=CUBE, binding=(0, 0, 'thin'))
