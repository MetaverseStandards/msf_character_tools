# SPDX-License-Identifier: MIT
"""Show FBX files going through msf-tools: an ASCII rig made by the test writer, plus any FBX paths given.

For each file it inspects in a separate reader process, lists declared losses,
binds the first morph target if there is one, and prints the first mesh's
world-space bounding box at three times of its animation.
Run from the repository root:

    python -B scripts/demo_fbx.py [more.fbx ...]
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests' / 'public')]
import msf_character_tools as m  # noqa: E402
from support.fbx_ascii import Scene  # noqa: E402

SIGNAL = {'id': 'demo', 'value_type': 'scalar', 'units': '1', 'domain': {'min': 0, 'max': 1}, 'calibration': 'literal'}
IDENTITY = [float(r == c) for c in range(4) for r in range(4)]


def ascii_rig():
    scene = Scene()
    root = scene.model('Hips', kind='LimbNode')
    arm = scene.model('Arm', root, kind='LimbNode', translation=(0, 1, 0), rotation_pivot=(0, 0.25, 0))
    body = scene.model('Body', kind='Mesh')
    geometry = scene.mesh(body, 'Body', [(0, 0, 0), (1, 0, 0), (1, 2, 0), (0, 2, 0)], [[0, 1, 2, 3]])
    scene.skin(geometry, [(root, [0, 1], [1.0, 1.0], IDENTITY, IDENTITY),
                          (arm, [2, 3], [1.0, 1.0], IDENTITY[:12] + [0.0, -1.0, 0.0, 1.0], IDENTITY[:12] + [0.0, 1.0, 0.0, 1.0])])
    smile, = scene.blend(geometry, 'Face', [('smile', 0, [(100, [2, 3], [(0, 0.5, 0), (0, 0.5, 0)])])])
    scene.animation('Wave', 0.0, 1.0, [(arm, 'Lcl Rotation', {'X': [(0.0, 0.0), (1.0, 0.0)], 'Y': [(0.0, 0.0), (1.0, 0.0)],
                                                              'Z': [(0.0, 0.0), (1.0, 60.0)]}),
                                       (smile, 'DeformPercent', {'DeformPercent': [(0.0, 0.0), (1.0, 100.0)]})])
    return 'writer rig (ASCII FBX 7.4)', scene.text()


def need(result):
    if not result.ok:
        print('  refused:', [(d.code, d.message) for d in result.report.diagnostics])
        return None
    return result.value


def main():
    samples = [ascii_rig()] + [(p, Path(p).read_bytes()) for p in sys.argv[1:]]
    for label, data in samples:
        print(f'{label}: {len(data)} bytes')
        snapshot = need(m.inspect_asset(data, 'fbx', isolate=True))
        if snapshot is None:
            continue
        source = snapshot.source
        print(f'  reader {source["reader"]}, {len(source["node_paths"])} nodes, losses: '
              + (', '.join(d['code'] for d in source['losses']) or 'none'))
        nodes = snapshot.document['nodes']
        mesh_nodes = [i for i, n in enumerate(nodes) if 'mesh' in n]
        if not mesh_nodes:
            continue
        keys = source['target_keys'][nodes[mesh_nodes[0]]['mesh']]
        if keys:
            binding = need(m.morph_binding(snapshot, SIGNAL, mesh_nodes[0], 0))
            if binding is not None:
                need(m.annotate_asset(snapshot, {'bindings': [binding]}))
                print(f'  bound "demo" to {binding["ref"]["source_locator"]}')
        animations = snapshot.document.get('animations', ())
        end = m.decode_accessor(snapshot, animations[0]['samplers'][0]['input']).value[-1][0] if animations else 0.0
        for seconds in sorted({0.0, end / 2, end}):
            kwargs = {'timestamp': seconds, 'animation_id': 0} if animations else {}
            values = need(m.evaluate_geometry(snapshot, **kwargs))
            if values is None:
                break
            points = next(i for i in values.to_dict()['instances'] if i['node'] == mesh_nodes[0])['primitives'][0]['positions']
            low = [min(p[k] for p in points) for k in range(3)]
            high = [max(p[k] for p in points) for k in range(3)]
            print(f'  t={seconds:.2f}s  {source["node_paths"][mesh_nodes[0]]} mesh-local box '
                  f'({", ".join(f"{x:.3f}" for x in low)}) to ({", ".join(f"{x:.3f}" for x in high)})')


if __name__ == '__main__':
    main()
