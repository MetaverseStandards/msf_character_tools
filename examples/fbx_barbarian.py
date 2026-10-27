# SPDX-License-Identifier: MIT
"""FBX example: a skinned, animated Blender character from the ufbx test corpus.

    python fbx_barbarian.py [--assets DIR] [--out DIR]

Needs msf-tools-ufbx (pip install ./native/ufbx, then "msf-tools[fbx]"). The
file is fetched by fetch_assets.py and never committed: the ufbx corpus data
files carry no licence of their own. The mapping drives the body's "Mouth"
shape key at the rest pose; the clip, which also animates the shape keys,
gives the animated poses.
"""
from example_pipeline import arguments, run

REVISION = '26a482ae66871d7de36eb722aa060bce95bce274'
BARBARIAN = {
    'name': 'Barbarian', 'file': 'blender_293_barbarian_7400_binary.fbx', 'format': 'fbx', 'revision': REVISION,
    'url': f'https://github.com/ufbx/ufbx/blob/{REVISION}/data/blender_293_barbarian_7400_binary.fbx',
    'sha256': 'bd78a4fc05abe83cb3bb26e4ca649a3c5e7cb1e0c6f523fcd599e48cd0435e04',
    'license': 'NOASSERTION',
    'credit': 'ufbx test corpus (Samuli Raivio); the data file states no author or licence, so use it locally only.',
}

if __name__ == '__main__':
    args = arguments('fbx', __doc__)
    run(args, name='fbx_barbarian', data=(args.assets / BARBARIAN['file']).read_bytes(), fmt='fbx', asset=BARBARIAN,
        binding=('/body', 0, 'Mouth'), clips=[('clip_0.5', 0, 0.5), ('clip_1.25', 0, 1.25), ('clip_2', 0, 2.0)])
