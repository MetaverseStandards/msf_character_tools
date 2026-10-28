# SPDX-License-Identifier: MIT
"""Time msf-tools operations through the public API and print a JSON report.

    python -B scripts/bench.py [--root CHECKOUT | --installed] [--frames N] [--runs 5] [--authoring DIR]
                               [--grid 50] [--geometry-frames 300] [--fbx FILE] [--output report.json]

By default msf_character_tools comes from this checkout. --root imports it from another
checkout; --installed uses the interpreter's installed copy, such as a 0.3.0
wheel in a separate venv. Set MSF_TOOLS_PURE=1 to time a build without its
fast paths. --authoring also times a real authoring directory, such as RCEF's.
--fbx also times converting an FBX file, such as the examples' Kenney character,
and evaluating its first animation. Each workload checks one value analytically
before timing. Timings are medians on one host. They are not a real-time or
device guarantee.
"""
import argparse
import importlib
import json
import math
import os
import platform
import random
import statistics
import struct
import sys
import time
from pathlib import Path

EVIDENCE = [{'id': 'e', 'claim': 'Synthetic benchmark.', 'status': 'verified_current', 'license': 'MIT',
             'authorship': 'MSF Tools contributors'}]


def signal(sid, low=0, high=1):
    return {'id': sid, 'label': sid, 'value_type': 'scalar', 'units': '1', 'domain': {'min': low, 'max': high},
            'calibration': 'bench.v1', 'disposition': 'mapped', 'evidence_status': 'verified_current', 'evidence': ['e']}


def rule(rid, inputs, output, operator):
    return {'id': rid, 'inputs': inputs, 'outputs': [output], 'operator': operator, 'disposition': 'mapped',
            'mapping_quality': 'exact', 'assumptions': [], 'evidence': ['e'], 'evidence_status': 'verified_current',
            'loss_annotations': []}


def document(signals, sources, targets, rules):
    return {'schema_version': '1.1', 'operator_version': '1.1', 'data_version': '0.1.0', 'id': 'bench', 'license': 'MIT',
            'signals': signals, 'evidence': EVIDENCE,
            'profiles': [{'id': 'source', 'label': 'Source', 'signal_ids': sources},
                         {'id': 'target', 'label': 'Target', 'signal_ids': targets}],
            'mappings': [{'id': 'map', 'rules': rules}]}


def gaze():
    """weighted_sum (in - out) feeding two one-sided piecewise_linear splits."""
    rules = [rule('d', ['in', 'out'], 'gaze', {'id': 'weighted_sum', 'weights': [1, -1]}),
             rule('a', ['gaze'], 'toward_in', {'id': 'piecewise_linear', 'knots': [[-1, 0], [0, 0], [1, 1]]}),
             rule('b', ['gaze'], 'toward_out', {'id': 'piecewise_linear', 'knots': [[-1, 1], [0, 0], [1, 0]]})]
    signals = [signal('in'), signal('out'), signal('gaze', -1, 1), signal('toward_in'), signal('toward_out')]
    return document(signals, ['in', 'out'], ['toward_in', 'toward_out'], rules)


def wide():
    """52 face outputs from 40 inputs: 20 identity, 20 affine, 8 three-input weighted_sum, 4 piecewise_linear."""
    sources = [f's{i:02}' for i in range(40)]
    targets = [f't{i:02}' for i in range(52)]
    rules = []
    for i in range(20):
        rules.append(rule(f'r{i:02}', [sources[i]], targets[i], {'id': 'identity'}))
    for i in range(20, 40):
        rules.append(rule(f'r{i:02}', [sources[i]], targets[i], {'id': 'affine', 'scale': 0.5, 'offset': 0.25}))
    for i in range(40, 48):
        rules.append(rule(f'r{i:02}', [sources[i - 40], sources[i - 30], sources[i - 20]], targets[i],
                          {'id': 'weighted_sum', 'weights': [0.25, 0.25, 0.5]}))
    for i in range(48, 52):
        rules.append(rule(f'r{i:02}', [sources[i - 20]], targets[i],
                          {'id': 'piecewise_linear', 'knots': [[0, 0], [0.3, 0.1], [0.7, 0.8], [1, 1]]}))
    return document([signal(s) for s in sources + targets], sources, targets, rules)


def large(count=2000):
    """A pack-sized document: `count` affine rules over 2 * count signals, for JSON and pack timings."""
    sources = [f'in.{i:05}' for i in range(count)]
    targets = [f'out.{i:05}' for i in range(count)]
    rules = [rule(f'r{i:05}', [sources[i]], targets[i], {'id': 'affine', 'scale': 0.5 + i / count, 'offset': -i / (3 * count)})
             for i in range(count)]
    return document([signal(s, -1, 1) for s in sources] + [signal(s, -2, 2) for s in targets], sources, targets, rules)


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def skinned_glb(grid):
    """A grid x grid vertex sheet skinned to a four-joint chain, with two morph targets
    and a one-second clip that bends the chain and blends the targets."""
    blob, views, accessors = bytearray(), [], []

    def add(fmt, rows, component_type, kind, bounds=False):
        while len(blob) % 4:
            blob.append(0)
        data = b''.join(struct.pack('<' + fmt * len(row), *row) for row in rows)
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(data)})
        blob.extend(data)
        a = {'bufferView': len(views) - 1, 'componentType': component_type, 'type': kind, 'count': len(rows)}
        if bounds:
            a['min'] = [min(r[k] for r in rows) for k in range(len(rows[0]))]
            a['max'] = [max(r[k] for r in rows) for k in range(len(rows[0]))]
        accessors.append(a)
        return len(accessors) - 1

    points = [(f32(-1 + 2 * c / (grid - 1)), f32(3 * r / (grid - 1)), f32(0.0)) for r in range(grid) for c in range(grid)]
    joints, weights = [], []
    for _, y, _ in points:
        j = min(int(y), 3)
        t = y - j
        joints.append((j, min(j + 1, 3), 0, 0))
        weights.append((f32(1 - t), f32(t) if j < 3 else 0.0, 0.0, 0.0))
    indices = []
    for r in range(grid - 1):
        for c in range(grid - 1):
            a = r * grid + c
            indices += [(a,), (a + 1,), (a + grid,), (a + 1,), (a + grid + 1,), (a + grid,)]
    position = add('f', points, 5126, 'VEC3', True)
    targets = [{'POSITION': add('f', [(f32(0.1 * x), f32(0.0), f32(0.05 * k + 0.05)) for x, _, _ in points], 5126, 'VEC3', True)}
               for k in range(2)]
    attributes = {'POSITION': position, 'JOINTS_0': add('B', joints, 5121, 'VEC4'), 'WEIGHTS_0': add('f', weights, 5126, 'VEC4')}
    index = add('I', indices, 5125, 'SCALAR')
    ibms = add('f', [(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -j, 0, 1) for j in range(4)], 5126, 'MAT4')
    keys = 10
    times = add('f', [(f32(k / (keys - 1)),) for k in range(keys)], 5126, 'SCALAR', True)
    angles = [0.4 * k / (keys - 1) for k in range(keys)]
    rotations = add('f', [(0.0, 0.0, f32(math.sin(a / 2)), f32(math.cos(a / 2))) for a in angles], 5126, 'VEC4')
    morphs = add('f', [(f32(w),) for k in range(keys) for w in (k / (keys - 1), 1 - k / (keys - 1))], 5126, 'SCALAR')
    nodes = [{'mesh': 0, 'skin': 0}, {'children': [2]}, {'translation': [0, 1, 0], 'children': [3]},
             {'translation': [0, 1, 0], 'children': [4]}, {'translation': [0, 1, 0]}]
    document = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0, 1]}], 'nodes': nodes,
                'meshes': [{'primitives': [{'attributes': attributes, 'indices': index, 'targets': targets}], 'weights': [0, 0]}],
                'skins': [{'joints': [1, 2, 3, 4], 'inverseBindMatrices': ibms}],
                'animations': [{'samplers': [{'input': times, 'output': rotations}, {'input': times, 'output': morphs}],
                                'channels': [{'sampler': 0, 'target': {'node': 2, 'path': 'rotation'}},
                                             {'sampler': 1, 'target': {'node': 0, 'path': 'weights'}}]}],
                'buffers': [{'byteLength': len(blob)}], 'bufferViews': views, 'accessors': accessors}
    text = json.dumps(document, separators=(',', ':')).encode()
    text += b' ' * (-len(text) % 4)
    while len(blob) % 4:
        blob.append(0)
    body = struct.pack('<II', len(text), 0x4E4F534A) + text + struct.pack('<II', len(blob), 0x004E4942) + bytes(blob)
    return struct.pack('<III', 0x46546C67, 2, 12 + len(body)) + body


def frames(sources, count, seed=20261027):
    rng = random.Random(seed)
    return [{'timestamp': i / 60, 'values': {s: rng.random() for s in sources},
             'validity': dict.fromkeys(sources, True)} for i in range(count)]


def median_seconds(fn, runs):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return {'median': statistics.median(times), 'min': min(times), 'max': max(times)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    source.add_argument('--installed', action='store_true')
    parser.add_argument('--frames', type=int, default=100_000)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--authoring', type=Path)
    parser.add_argument('--grid', type=int, default=50)
    parser.add_argument('--geometry-frames', type=int, default=300)
    parser.add_argument('--fbx', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.frames <= 10_000_000 or not 3 <= args.runs <= 100 or not 2 <= args.grid <= 500 or not 1 <= args.geometry_frames <= 10_000:
        parser.error('frames must be 1..10000000; runs 3..100; grid 2..500; geometry-frames 1..10000')
    if not args.installed:
        sys.path.insert(0, str(args.root.resolve()))
    m = importlib.import_module('msf_character_tools')
    native = sys.modules.get('msf_character_tools._native')
    report = {'msf_character_tools': m.__version__, 'imported_from': str(Path(m.__file__).parent), 'platform': platform.platform(),
              'machine': platform.machine(), 'processor': platform.processor(), 'python': platform.python_version(),
              'implementation': platform.python_implementation(), 'cpu_count': os.cpu_count(),
              'core': native is not None and native.core is not None, 'frames': args.frames, 'runs': args.runs, 'workloads': {}}
    for name, doc in (('gaze', gaze()), ('wide', wide())):
        pack = m.compile_pack(m.validate_authoring(doc).value).value
        source, target = m.profile_snapshot(pack, 'source').value, m.profile_snapshot(pack, 'target').value
        compiled = m.compile_mapping(pack, source, target, 'map').value
        samples = frames(doc['profiles'][0]['signal_ids'], args.frames)
        result = m.evaluate_mapping(compiled, samples)
        if not result.ok:
            raise SystemExit(f'{name}: evaluation failed: {result.report.to_dict()}')
        first, values = result.value.samples[0]['values'], samples[0]['values']
        if name == 'gaze':
            expected = {'toward_in': max(values['in'] - values['out'], 0.0), 'toward_out': max(values['out'] - values['in'], 0.0)}
        else:
            expected = {'t00': values['s00'], 't20': 0.5 * values['s20'] + 0.25}
        if any(abs(first[k] - v) > 1e-12 for k, v in expected.items()):
            raise SystemExit(f'{name}: analytical check failed: {dict(first)} vs {expected}')
        report['workloads'][name] = {
            'rules': len(doc['mappings'][0]['rules']), 'outputs': len(doc['profiles'][1]['signal_ids']),
            'compile_mapping_seconds': median_seconds(lambda: m.compile_mapping(pack, source, target, 'map'), args.runs),
            'evaluate_mapping_seconds': median_seconds(lambda: m.evaluate_mapping(compiled, samples), args.runs)}
    validated = m.validate_authoring(large()).value
    pack = m.compile_pack(validated).value
    document = large()
    report['workloads']['pack'] = {
        'rules': len(pack.document['mappings'][0]['rules']), 'canonical_json_bytes': len(pack.to_bytes()),
        'validate_authoring_seconds': median_seconds(lambda: m.validate_authoring(document), args.runs),
        'canonical_json_seconds': median_seconds(lambda: m.canonical_json(pack.document), args.runs),
        'compile_pack_seconds': median_seconds(lambda: m.compile_pack(validated), args.runs),
        'survey_csv_seconds': median_seconds(lambda: m.survey_csv(pack), args.runs),
        'coverage_seconds': median_seconds(lambda: m.coverage(pack), args.runs)}
    glb = skinned_glb(args.grid)
    snapshot = m.inspect_asset(glb, 'glb').value
    if snapshot is None:
        raise SystemExit(f'gltf: inspection failed: {m.inspect_asset(glb, "glb").report.to_dict()}')
    rest = m.evaluate_geometry(snapshot).value.to_dict()['instances'][0]['primitives'][0]['positions']
    top = (args.grid - 1) * args.grid  # first vertex of the last row sits on the last joint, at rest
    if rest[0] != [-1.0, 0.0, 0.0] or rest[top] != [-1.0, 3.0, 0.0]:
        raise SystemExit(f'gltf: analytical check failed: {rest[0]}, {rest[top]}')
    stamps = [k / args.geometry_frames for k in range(args.geometry_frames)]
    report['workloads']['gltf'] = {
        'vertices': args.grid ** 2, 'glb_bytes': len(glb), 'geometry_frames': args.geometry_frames,
        'inspect_asset_seconds': median_seconds(lambda: m.inspect_asset(glb, 'glb'), args.runs),
        'decode_accessor_seconds': median_seconds(lambda: m.decode_accessor(snapshot, 0), args.runs),
        'sample_animation_seconds': median_seconds(lambda: m.sample_animation(snapshot, 0, 0.55), args.runs),
        'evaluate_geometry_frames_seconds': median_seconds(
            lambda: [m.evaluate_geometry(snapshot, animation_id=0, timestamp=t) for t in stamps], args.runs),
        'export_geometry_golden_seconds': median_seconds(lambda: m.export_geometry_golden(snapshot, animation_id=0, timestamp=0.5), args.runs)}
    if args.authoring:
        loaded = m.load_authoring(args.authoring)
        if not loaded.ok:
            raise SystemExit(f'{args.authoring}: {loaded.report.to_dict()}')
        real = m.compile_pack(loaded.value).value
        report['workloads']['authoring'] = {
            'path': str(args.authoring), 'pack_sha256': real.sha256, 'canonical_json_bytes': len(real.to_bytes()),
            'load_authoring_seconds': median_seconds(lambda: m.load_authoring(args.authoring), args.runs),
            'compile_pack_seconds': median_seconds(lambda: m.compile_pack(loaded.value), args.runs),
            'to_bytes_seconds': median_seconds(real.to_bytes, args.runs),
            'survey_csv_seconds': median_seconds(lambda: m.survey_csv(real), args.runs),
            'coverage_seconds': median_seconds(lambda: m.coverage(real), args.runs)}
    if args.fbx:
        data = args.fbx.read_bytes()
        converted = m.inspect_asset(data, 'fbx')
        if not converted.ok:
            raise SystemExit(f'{args.fbx}: {converted.report.to_dict()}')
        scene = converted.value
        # The adapter writes one glTF node per source node, every one of them named by a source path.
        if len(scene.source['node_paths']) != len(scene.document['nodes']):
            raise SystemExit(f'{args.fbx}: node paths do not match nodes')
        animated = {'animation_id': 0, 'timestamp': 0.5} if scene.document.get('animations') else {}
        report['workloads']['fbx'] = {
            'path': str(args.fbx), 'bytes': len(data), 'glb_bytes': len(scene.original_bytes),
            'inspect_asset_seconds': median_seconds(lambda: m.inspect_asset(data, 'fbx'), args.runs),
            'evaluate_geometry_seconds': median_seconds(lambda: m.evaluate_geometry(scene, **animated), args.runs)}
    text = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    sys.stdout.write(text)


if __name__ == '__main__':
    main()
