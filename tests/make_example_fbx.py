# SPDX-License-Identifier: MIT
"""Write examples/data/AnimatedMorphCube.writer.fbx: the Khronos AnimatedMorphCube (CC0) as ASCII FBX.

    python -B tests/make_example_fbx.py path/to/AnimatedMorphCube.glb

It is written by the test FBX writer, not exported by a DCC tool, so it shows
the shape-key binding path but is no evidence about real exporters. The mesh,
its two morph targets and its node transform are read from the GLB with struct.
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]
from support.fbx_ascii import Scene  # noqa: E402
from support.glb_struct import accessor, read_glb  # noqa: E402
from test_source_twins import euler_xyz  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / 'examples' / 'data' / 'AnimatedMorphCube.writer.fbx'
NOTE = ('; AnimatedMorphCube (CC0-1.0, Microsoft 2017, Khronos glTF-Sample-Assets) written by msf-tools\' test FBX writer\n'
        '; (tests/make_example_fbx.py). It is not a DCC export.\n')


def morph_cube_fbx(glb, percents=(0.0, 0.0)):
    """The cube as FBX text, with its two blend channels at the given DeformPercent values."""
    document, binary = read_glb(glb)
    node = document['nodes'][0]
    primitive = document['meshes'][node['mesh']]['primitives'][0]
    points = accessor(document, binary, primitive['attributes']['POSITION'])
    order = [i for (i,) in accessor(document, binary, primitive['indices'])]
    scene = Scene()
    model = scene.model('AnimatedMorphCube', kind='Mesh', rotation=euler_xyz(node['rotation']), scale=node['scale'])
    geometry = scene.mesh(model, 'Cube', points, [order[k:k + 3] for k in range(0, len(order), 3)])
    channels = []
    for name, target, percent in zip(('thin', 'angle'), primitive['targets'], percents):
        offsets = accessor(document, binary, target['POSITION'])
        channels.append((name, percent, [(100.0, list(range(len(offsets))), offsets)]))
    scene.blend(geometry, 'Cube', channels)
    text = scene.text()
    text = text.decode() if isinstance(text, bytes) else text
    first, rest = text.split('\n', 1)
    return (first + '\n' + NOTE + rest).encode()


if __name__ == '__main__':
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_bytes(morph_cube_fbx(Path(sys.argv[1]).read_bytes()))
    print(OUTPUT)
