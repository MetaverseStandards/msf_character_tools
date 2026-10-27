# SPDX-License-Identifier: MIT
"""Steps shared by the examples: inspect an asset, bind a signal to a morph target in a
sidecar, compile and evaluate a one-rule mapping, then pose the mesh and write the results.

Outputs, in the folder given by --out:
  summary.json    what was found and done, in one place
  poses.csv       one row per pose: vertex and triangle counts and the world-space bounds
  authoring.toml  the example pack's authoring (one source signal, one target signal, one rule)
  annotations.json, sidecar.json   the input to annotate_asset and the hash-bound sidecar it wrote
  samples.json, mapping.json, evaluated.json   source frames, the compiled mapping and the mapped frames
  render/         world-space positions per pose (<pose>.f32, little-endian float32 xyz),
                  shared triangle indices (mesh.u32, little-endian uint32) and render.json,
                  a job list for the meshrender tool (run it from inside render/)
"""
import argparse
from collections.abc import Mapping
import csv
import json
import math
from pathlib import Path
import struct
import sys

import msf_tools as m

HERE = Path(__file__).resolve().parent
SOURCE, TARGET, MAPPING = 'example.jaw_open', 'example.target', 'example.drive'
SCALE = 0.8
SAMPLES = (0.0, 0.5, 1.0)


def arguments(name, doc):
    parser = argparse.ArgumentParser(description=doc.strip().splitlines()[0])
    parser.add_argument('--assets', type=Path, default=HERE / 'assets', help='the folder fetch_assets.py downloaded into')
    parser.add_argument('--out', type=Path, default=HERE / 'out' / name, help='where to write the outputs')
    return parser.parse_args()


def need(result, step):
    if not result.ok:
        sys.exit(f'{step} failed:\n' + json.dumps(result.report.to_dict(), indent=2))
    return result.value


def plain(value):
    if hasattr(value, 'to_dict'):
        return plain(value.to_dict())
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def write_json(path, value):
    path.write_text(json.dumps(plain(value), indent=2, sort_keys=True, ensure_ascii=False) + '\n')


def authoring(asset, target_label):
    """A one-rule pack: a jaw-open source signal drives one morph target through y = 0.8 x."""
    evidence = {'id': 'example.asset', 'status': 'verified_current', 'license': asset['license'],
                'authorship': asset['credit'], 'sha256': asset['sha256'],
                'claim': f'{asset["name"]} at a pinned revision; the bound target is its {target_label} morph target.'}
    if asset.get('url'):
        evidence.update(url=asset['url'], revision=asset['revision'], locator='/')

    def signal(sid, label, calibration):
        return {'id': sid, 'label': label, 'value_type': 'scalar', 'units': '1', 'domain': {'min': 0.0, 'max': 1.0},
                'calibration': calibration, 'disposition': 'mapped', 'evidence': ['example.asset'],
                'evidence_status': 'verified_current'}

    return {
        'schema_version': '1.0', 'data_version': '0.1.0', 'operator_version': '1.0',
        'id': 'example.' + asset['name'].lower().replace(' ', '_'), 'license': 'CC-BY-SA-4.0',
        'evidence': [evidence],
        'signals': [signal(SOURCE, 'Jaw open on the source rig', 'Example: 0 is a closed jaw, 1 fully open.'),
                    signal(TARGET, f'{target_label} morph target weight', f'Example: weight of the {target_label} target.')],
        'profiles': [{'id': 'example.source', 'label': 'Source rig', 'signal_ids': [SOURCE]},
                     {'id': 'example.target', 'label': asset['name'], 'signal_ids': [TARGET]}],
        'mappings': [{'id': MAPPING, 'rules': [{
            'id': MAPPING + '.rule', 'inputs': [SOURCE], 'outputs': [TARGET],
            'operator': {'id': 'affine', 'scale': SCALE, 'offset': 0.0},
            'disposition': 'mapped', 'mapping_quality': 'exact', 'evidence': ['example.asset'],
            'evidence_status': 'verified_current', 'loss_annotations': [],
            'assumptions': [f'Weight {SCALE} on the target reads as a fully open jaw; an example choice, not a measurement.'],
        }]}],
    }


def toml(document):
    """TOML for the authoring above: top-level values, then arrays of tables (one level of nesting)."""
    def value(v):
        if isinstance(v, dict):
            return '{' + ', '.join(f'{k} = {value(x)}' for k, x in v.items()) + '}'
        if isinstance(v, list):
            return '[' + ', '.join(value(x) for x in v) + ']'
        return json.dumps(v)

    def table(header, record):
        nested = {k: v for k, v in record.items() if isinstance(v, list) and v and isinstance(v[0], dict)}
        lines = [f'[[{header}]]'] + [f'{k} = {value(v)}' for k, v in record.items() if k not in nested]
        for key, rows in nested.items():
            for row in rows:
                lines += [''] + table(f'{header}.{key}', row)
        return lines

    lines = ['# SPDX-License-Identifier: CC-BY-SA-4.0']
    lines += [f'{k} = {value(v)}' for k, v in document.items() if not isinstance(v, list)]
    for key, rows in document.items():
        if isinstance(rows, list):
            for row in rows:
                lines += [''] + table(key, row)
    return '\n'.join(lines) + '\n'


def local_matrix(node):
    if 'matrix' in node:
        c = node['matrix']
        return [[c[4 * col + row] for col in range(4)] for row in range(4)]
    x, y, z, w = node.get('rotation', (0.0, 0.0, 0.0, 1.0))
    sx, sy, sz = node.get('scale', (1.0, 1.0, 1.0))
    tx, ty, tz = node.get('translation', (0.0, 0.0, 0.0))
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[i][0] * sx, r[i][1] * sy, r[i][2] * sz, t] for i, t in enumerate((tx, ty, tz))] + [[0.0, 0.0, 0.0, 1.0]]


def world_matrices(nodes, overrides):
    parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', ())}
    worlds = {}

    def world(i):
        if i not in worlds:
            local = local_matrix(dict(nodes[i], **dict(overrides.get(i, {}))))
            if i in parent:
                p = world(parent[i])
                local = [[sum(p[r][k] * local[k][c] for k in range(4)) for c in range(4)] for r in range(4)]
            worlds[i] = local
        return worlds[i]

    return [world(i) for i in range(len(nodes))]


def pose(snapshot, **kwargs):
    """World-space points of every mesh instance, concatenated; their triangle indices; and which points can deform.

    evaluate_geometry returns points in each mesh node's space, so each instance is moved by its node's world matrix.
    """
    value = need(m.evaluate_geometry(snapshot, **kwargs), 'evaluate_geometry').to_dict()
    overrides = {}
    if 'animation_id' in kwargs:
        overrides = need(m.sample_animation(snapshot, kwargs['animation_id'], kwargs['timestamp']), 'sample_animation')
    document = snapshot.document
    worlds = world_matrices(document['nodes'], overrides)
    points, indices, deforming = [], [], []
    for instance in value['instances']:
        w = worlds[instance['node']]
        mesh = document['meshes'][instance['mesh']]
        deforms = 'skin' in document['nodes'][instance['node']] or any('targets' in p for p in mesh['primitives'])
        for primitive in instance['primitives']:
            authored = mesh['primitives'][primitive['primitive']]
            if authored.get('mode', 4) != 4:
                continue
            local = primitive['positions']
            order = ([i for (i,) in m.decode_accessor(snapshot, authored['indices']).value]
                     if 'indices' in authored else list(range(len(local))))
            base = len(points)
            points += [[sum(w[r][k] * p[k] for k in range(3)) + w[r][3] for r in range(3)] for p in local]
            indices += [base + i for i in order]
            deforming += [deforms] * len(local)
    return points, indices, deforming


def summarize(snapshot, report):
    document = snapshot.document
    animations = []
    for i, animation in enumerate(document.get('animations', ())):
        end = max(m.decode_accessor(snapshot, s['input']).value[-1][0] for s in animation['samplers'])
        animations.append({'name': animation.get('name', f'animation {i}'), 'seconds': end})
    return {
        'nodes': len(document.get('nodes', ())),
        'meshes': len(document.get('meshes', ())),
        'mesh_instances': sum('mesh' in n for n in document.get('nodes', ())),
        'skins': len(document.get('skins', ())),
        'morph_targets': sum(len(p.get('targets', ())) for mesh in document.get('meshes', ()) for p in mesh['primitives']),
        'animations': animations,
        'declared_losses': plain(snapshot.source['losses']) if snapshot.source else [],
        'diagnostics': plain(report)['diagnostics'],
    }


def run(args, *, name, data, fmt, asset, binding=None, clips=(), resolver=None, options=None):
    """Run every step on one asset.

    binding is (node index or source node path, morph target index, label); clips are (pose name, animation, seconds).
    """
    out, render = args.out, args.out / 'render'
    render.mkdir(parents=True, exist_ok=True)
    extra = {'options': options} if options else {}
    inspected = m.inspect_asset(data, fmt, resolver=resolver, **extra)
    snapshot = need(inspected, 'inspect_asset')
    print(f'[{name}] inspected {asset["file"]}: {len(snapshot.document.get("nodes", ()))} nodes, '
          f'{len(snapshot.source["losses"]) if snapshot.source else 0} declared losses')

    label = binding[2] if binding else 'morph'
    (out / 'authoring.toml').write_text(toml(authoring(asset, label)))
    pack = need(m.compile_pack(need(m.load_authoring(out / 'authoring.toml'), 'load_authoring')), 'compile_pack')
    source_profile = need(m.profile_snapshot(pack, 'example.source'), 'profile_snapshot')

    node, target = binding[:2] if binding else (next(i for i, n in enumerate(snapshot.document['nodes']) if 'mesh' in n), 0)
    if isinstance(node, str):
        node = snapshot.source['node_paths'].index(node)
    bound = m.morph_binding(snapshot, pack.signals[TARGET], node, target)
    metadata = {'example': f'{name}: {SOURCE} drives {label}'}
    annotations = {'bindings': [bound.value] if bound.ok else [], 'metadata': metadata}
    write_json(out / 'annotations.json', annotations)
    sidecar = need(m.annotate_asset(snapshot, annotations), 'annotate_asset')
    if bound.ok:
        sidecar_wire = json.loads(m.canonical_json(sidecar))
        target_snapshot = need(m.inspect_asset(data, fmt, resolver=resolver, sidecar=sidecar_wire, **extra), 'inspect_asset with sidecar')
        path = snapshot.source['node_paths'][node] if snapshot.source else snapshot.document['nodes'][node].get('name')
        binding_summary = {'signal': TARGET, 'node': node, 'target': target, 'label': label, 'node_path': path}
        print(f'[{name}] bound {TARGET} to node {node} ({path}) morph target {target} ({label})')
    else:
        # Without a morph target there is nothing to bind: the mapping still runs against the pack's own target profile.
        refusal = bound.report.diagnostics[0]
        target_snapshot = need(m.profile_snapshot(pack, 'example.target'), 'profile_snapshot')
        binding_summary = {'refused': refusal.code, 'ref': refusal.ref, 'message': refusal.message}
        print(f'[{name}] no morph target to bind: {refusal.code} {refusal.message}')
    (out / 'sidecar.json').write_bytes(m.canonical_json(sidecar))

    compiled = need(m.compile_mapping(pack, source_profile, target_snapshot, MAPPING, False), 'compile_mapping')
    (out / 'mapping.json').write_bytes(m.canonical_json(compiled))
    frames = [{'timestamp': 0.5 * i, 'values': {SOURCE: x}, 'validity': {SOURCE: True}} for i, x in enumerate(SAMPLES)]
    write_json(out / 'samples.json', frames)
    evaluated = need(m.evaluate_mapping(compiled, frames), 'evaluate_mapping')
    (out / 'evaluated.json').write_bytes(m.canonical_json(evaluated))
    mapped = [frame['values'][TARGET] for frame in plain(evaluated)['samples']]
    print(f'[{name}] mapped {SOURCE} {list(SAMPLES)} to {TARGET} {mapped}')

    poses = [('rest', 'rest pose, no animation', {})]
    if bound.ok:
        authored = snapshot.document['nodes'][node]
        defaults = list(authored.get('weights', snapshot.document['meshes'][authored['mesh']].get('weights', ())))
        defaults += [0.0] * (len(snapshot.document['meshes'][authored['mesh']]['primitives'][0]['targets']) - len(defaults))
        for x, y in zip(SAMPLES, mapped):
            weights = list(defaults)
            weights[target] = y
            poses.append((f'jaw_open_{x:g}', f'{SOURCE} = {x:g}, so {label} weight {y:g}', {'morph_weights': {node: weights}}))
    for pose_name, animation, seconds in clips:
        clip = snapshot.document['animations'][animation].get('name', f'animation {animation}')
        poses.append((pose_name, f'{clip} at {seconds:g} s', {'animation_id': animation, 'timestamp': seconds}))

    rows, union, shared = [], [], None
    for pose_name, how, kwargs in poses:
        points, indices, deforming = pose(snapshot, **kwargs)
        if shared is None:
            shared = indices
            (render / 'mesh.u32').write_bytes(struct.pack(f'<{len(indices)}I', *indices))
        assert indices == shared, 'every pose shares one topology'
        (render / f'{pose_name}.f32').write_bytes(struct.pack(f'<{3 * len(points)}f', *(c for p in points for c in p)))
        low, high = [min(c) for c in zip(*points)], [max(c) for c in zip(*points)]
        # Frame the camera on what deforms when the asset has both deforming and static meshes.
        framed = [p for p, d in zip(points, deforming) if d] or points
        union += [[min(c) for c in zip(*framed)], [max(c) for c in zip(*framed)]]
        rows.append({'name': pose_name, 'how': how, 'vertices': len(points), 'triangles': len(indices) // 3,
                     'bbox_min': low, 'bbox_max': high, 'file': f'{pose_name}.f32'})
    print(f'[{name}] posed {len(rows)} times: {rows[0]["vertices"]} vertices, {rows[0]["triangles"]} triangles each')

    low, high = [min(c) for c in zip(*union)], [max(c) for c in zip(*union)]
    centre = [(a + b) / 2 for a, b in zip(low, high)]
    distance = 1.6 * (math.dist(low, high) or 1.0)
    direction = [0.45, 0.3, 1.0]
    length = math.sqrt(sum(c * c for c in direction))
    camera = {'position': [c + distance * d / length for c, d in zip(centre, direction)], 'target': centre,
              'up': [0, 1, 0], 'yfov': 35}
    write_json(render / 'render.json', {'width': 1280, 'height': 720, 'jobs': [
        {'positions': row['file'], 'indices': 'mesh.u32', 'camera': camera, 'out': f'{row["name"]}.png'} for row in rows]})
    with open(out / 'poses.csv', 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['pose', 'how', 'vertices', 'triangles', 'min_x', 'min_y', 'min_z', 'max_x', 'max_y', 'max_z'])
        for row in rows:
            writer.writerow([row['name'], row['how'], row['vertices'], row['triangles'],
                             *(f'{c:.6g}' for c in row['bbox_min']), *(f'{c:.6g}' for c in row['bbox_max'])])
    write_json(out / 'summary.json', {
        'asset': asset, 'inspect': summarize(snapshot, inspected.report), 'binding': binding_summary,
        'mapping': {'id': MAPPING, 'operator': f'{TARGET} = {SCALE} * {SOURCE}'},
        'evaluated': [{'timestamp': f['timestamp'], 'source': x, 'target': y} for f, x, y in zip(frames, SAMPLES, mapped)],
        'poses': rows,
    })
    print(f'[{name}] wrote {out}')
