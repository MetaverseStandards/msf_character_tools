# SPDX-License-Identifier: MIT
"""Write docs/parity.md: how closely the same scene agrees across glTF, USD and FBX.

    python -B scripts/parity_table.py [output.md]

Needs usd-core and msf-tools-ufbx. The Khronos, real-asset, example-asset and
ufbx corpus sections run when MSF_KHRONOS_ASSETS, MSF_REAL_ASSETS,
MSF_EXAMPLE_ASSETS and MSF_UFBX_CORPUS name local copies (see docs/testing.md)
and say "not run" otherwise. Every number is
measured when the script runs; nothing is copied from earlier runs.
"""
import math
import os
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]

import msf_tools as m  # noqa: E402
from msf_tools.sources import fbx as fbx_source  # noqa: E402
import test_source_strict as strict  # noqa: E402
import test_source_twins as twins  # noqa: E402


def diagonal(points):
    return math.dist([min(c) for c in zip(*points)], [max(c) for c in zip(*points)]) or 1.0


def worst(actual, wanted):
    return max(math.dist(a, w) for a, w in zip(actual, wanted)) / diagonal(wanted)


def fbx_twin(snapshot, seconds):
    """Largest difference between the snapshot and its FBX re-authoring, read back through the FBX adapter."""
    data, rows, keys = twins.twin(snapshot)
    options = {'sample_rate': round(1.0 / min(b - a for a, b in zip(keys, keys[1:])), 6)} if len(keys) > 1 else {}
    result = m.inspect_asset(data, 'fbx', options=options)
    if not result.ok:
        return 'refused ' + ', '.join(d.code for d in result.report.diagnostics), ''
    error = max(worst(twins.world_points(result.value, None, None, s, path_of=path), twins.world_points(snapshot, node, primitive, s))
                for s in seconds for node, primitive, path in rows)
    return f'{error:.1e}', ', '.join(d['code'] for d in result.value.source['losses'])


def strict_rows():
    yield '| Scene | USD losses or refusal | USDA, USDC, USDZ agree | vs usd-core (independent) | Round trip through msf\'s FBX writer (consistency only) | Round-trip losses |'
    yield '|---|---|---|---|---|---|'
    for name, (expected, codes) in strict.CASES.items():
        resolver = m.LocalResolver(strict.SOURCE) if name == 'layers' else None
        results = [m.inspect_asset(data, fmt, resolver=resolver) for fmt, data in strict.variants(name)]
        if not results[0].ok:
            refusals = {tuple(d.code for d in r.report.diagnostics) for r in results}
            yield f'| `{name}` | refused: {", ".join(sorted({c for r in refusals for c in r}))} | {"yes" if len(refusals) == 1 else "NO"} | | | |'
            continue
        snapshot = results[0].value
        same = len({m.canonical_json(r.value.document) for r in results}) == 1
        oracle = strict.Oracle(strict.SOURCE / f'{name}.usda')
        if name in strict.SKIN:
            oracle.bake(codes)
        shift, rate = min(0, codes[0]), oracle.stage.GetTimeCodesPerSecond()
        seconds = [(code - shift) / rate for code in codes]
        usd = max(worst(strict.msf_world_points(snapshot, str(prim.GetPath()), s), oracle.world_points(prim, code))
                  for code, s in zip(codes, seconds) for prim in oracle.meshes)
        error, losses = fbx_twin(snapshot, seconds)
        declared = ', '.join(d['code'] for d in snapshot.source['losses']) or 'none'
        yield f'| `{name}` | {declared} | {"yes" if same else "NO"} | {usd:.1e} | {error} | {losses or "none"} |'


def khronos_rows():
    root = os.environ.get('MSF_KHRONOS_ASSETS')
    if not root or not (Path(root) / 'Models').is_dir():
        yield 'Not run: set MSF_KHRONOS_ASSETS to a glTF-Sample-Assets checkout.'
        return
    yield '| Asset | Times compared | Round trip through msf\'s FBX writer (consistency only) |'
    yield '|---|---|---|'
    for name in twins.MODELS:
        folder = Path(root) / 'Models' / name / 'glTF'
        original = m.inspect_asset(next(folder.glob('*.gltf')).read_bytes(), 'gltf', resolver=m.LocalResolver(folder)).value
        keys = twins.twin(original)[2]
        seconds = keys[::max(1, len(keys) // 6)] + keys[-1:] if keys else [0.0]
        yield f'| {name} | {len(seconds)} | {fbx_twin(original, seconds)[0]} |'


def real_rows():
    root = os.environ.get('MSF_REAL_ASSETS')
    if not root or not (Path(root) / 'real-asset-harness-plan09K').is_dir():
        yield 'Not run: set MSF_REAL_ASSETS to a local copy of the 09K harness inputs.'
        return
    import json
    assets, oracles = Path(root) / 'assets-e2e09H' / 'assets', Path(root) / 'assets-oracle-review09I'
    tolerances = json.loads((oracles / 'EXPECTATION_SPEC.json').read_text())['tolerances']
    yield '| Asset | Case | Rows | Largest absolute error (m) | Allowed |'
    yield '|---|---|---|---|---|'
    for name, folder in (('Fox', 'Fox'), ('RobotExpressiveHead', 'RobotExpressiveHead')):
        snapshot = m.inspect_asset((assets / folder / f'{name}.gltf').read_bytes(), 'gltf', resolver=m.LocalResolver(assets / folder)).value
        tolerance = tolerances[name]['POSITION_mesh_local_and_world']
        for case in json.loads((oracles / f'{name}.independent.json').read_text())['cases']:
            kwargs = {}
            if case['case']['animation_id'] is not None:
                kwargs.update(animation_id=case['case']['animation_id'], timestamp=case['case']['timestamp'])
            if case['case']['morph_weights'] is not None:
                # The oracle's weights are for the head's only morphed node, node 0.
                kwargs['morph_weights'] = {0: case['case']['morph_weights']}
            value = m.evaluate_geometry(snapshot, **kwargs).value.to_dict()
            pairs = [(a, w) for got, want in zip(value['instances'][0]['primitives'], case['geometry']['instances'][0]['primitives'])
                     for p, q in zip(got['positions'], want['positions']) for a, w in zip(p, q)]
            label = (f't = {kwargs["timestamp"]:g} s' if 'timestamp' in kwargs else
                     f'weights {kwargs["morph_weights"][0]}' if 'morph_weights' in kwargs else 'rest')
            yield (f'| {name} | {label} | {len(pairs) // 3} | {max(abs(a - w) for a, w in pairs):.1e} | '
                   f'{tolerance["absolute"]:g} absolute + {tolerance["relative"]:g} relative |')


def kenney_rows():
    root = os.environ.get('MSF_EXAMPLE_ASSETS')
    if not root or not (Path(root) / 'character-female-a.glb').is_file():
        yield 'Not run: set MSF_EXAMPLE_ASSETS to the folder examples/fetch_assets.py downloaded into.'
        return
    sys.path.insert(0, str(ROOT / 'examples'))
    from example_pipeline import pose
    fbx = m.inspect_asset((Path(root) / 'character-female-a.fbx').read_bytes(), 'fbx', options={'animation': 'walk'}).value
    glb = m.inspect_asset((Path(root) / 'character-female-a.glb').read_bytes(), 'glb').value
    walk = [a.get('name') for a in glb.document['animations']].index('walk')
    yield '| Pose | FBX vertices | GLB vertices | Largest distance to the other export |'
    yield '|---|---|---|---|'
    for label, seconds in (('rest', None), ('walk 0.1 s', 0.1), ('walk 0.25 s', 0.25), ('walk 0.5 s', 0.5)):
        a = pose(fbx, **({} if seconds is None else {'animation_id': 0, 'timestamp': seconds}))[0]
        b = pose(glb, **({} if seconds is None else {'animation_id': walk, 'timestamp': seconds}))[0]
        error = max(max(min(math.dist(p, q) for q in other) for p in one) for one, other in ((a, b), (b, a)))
        yield f'| {label} | {len(a)} | {len(b)} | {error / diagonal(b):.1e} |'


def dcc_rows():
    if not os.environ.get('MSF_UFBX_CORPUS'):
        yield 'Not run: set MSF_UFBX_CORPUS to the ufbx corpus checkout.'
        return
    import test_source_fbx_dcc as dcc
    counts = {}
    for fbx, obj, stack, seconds, flags in dcc.pairings():
        outcome = dcc.compare(fbx, obj, stack, seconds, flags)[0]
        exporter = re.match('[a-z]+', fbx.name).group()
        counts.setdefault(exporter, {}).setdefault(outcome, 0)
        counts[exporter][outcome] += 1
    outcomes = sorted({o for c in counts.values() for o in c})
    yield '| File prefix | ' + ' | '.join(outcomes) + ' |'
    yield '|---|' + '---|' * len(outcomes)
    for exporter, c in sorted(counts.items()):
        yield f'| `{exporter}` | ' + ' | '.join(str(c.get(o, 0)) for o in outcomes) + ' |'


def main(output):
    from pxr import Usd
    lines = [
        '<!-- Generated by scripts/parity_table.py; edit the script, not this file. -->',
        '# Cross-format parity',
        '',
        f'msf-tools {m.__version__}; usd-core {".".join(map(str, Usd.GetVersion()))}; ufbx '
        f'{fbx_source.UFBX_VERSION}. Errors are the largest point distance divided by the bounding-box diagonal unless '
        'stated otherwise; the tests fail above 1e-5.',
        '',
        '## Strict tier',
        '',
        '### Synthetic USD scenes',
        '',
        'Each scene from `tests/make_source_fixtures.py` is read as USDA, USDC and USDZ and compared with usd-core '
        '(world points at every authored time, `BakeSkinning` for skinned meshes). The FBX twin is the same scene written '
        'by the test FBX writer from msf-tools\' reading of the USD and read back through the FBX adapter. That column is a '
        'consistency check (msf writer to msf reader), not an independent reference: it shows the two readers agree on '
        'what was carried over, and it does not re-test the USD losses.',
        '',
        *strict_rows(),
        '',
        '### Khronos sample assets: round trip through msf\'s FBX writer',
        '',
        'Each asset re-authored as FBX by msf-tools\' test writer with the same nodes, meshes, skins, morph targets and '
        'first animation, then read back (`tests/test_source_twins.py`). This is a consistency check, not an independent '
        'reference.',
        '',
        *khronos_rows(),
        '',
        '### Real glTF assets against the independent Decimal oracles',
        '',
        *real_rows(),
        '',
        '### FBX behaviour with no USD counterpart',
        '',
        'Pivots, offsets, pre- and post-rotation and the three inherit types are checked against an independent '
        'FBX SDK transform formula and the archived affine witness points (`tests/test_source_fbx.py`). glTF and USD '
        'cannot express them, so there is nothing to compare across formats.',
        '',
        '## Exporter tier',
        '',
        'Blender FBX twins of the Khronos assets (decision D4) have not been made yet.',
        '',
        '### Two exports of one model: Kenney\'s character as FBX and as GLB',
        '',
        '`character-female-a` from Kenney\'s Mini Characters pack (CC0), exported by Kenney as FBX (Autodesk FBX SDK) and '
        'as GLB, read through the FBX and glTF paths. Distances are divided by the bounding-box diagonal; the tests allow '
        '1e-3. The exports key the walk clip differently, so they agree closely at shared keys and less between them.',
        '',
        *kenney_rows(),
        '',
        '### DCC reference frames from the ufbx corpus',
        '',
        'The OBJ frames that each DCC exported alongside the ufbx corpus files, compared with msf-tools\' world points '
        '(`tests/test_source_fbx_dcc.py`), with the axes and unit read from each file\'s own header. "explained" rows '
        'differ only on meshes that carry a declared loss that changes points; "refused" rows are singular transforms; '
        '"skipped" rows are OBJ files in skin bind space, frames ufbx evaluates without extrapolation, files with only '
        'skipped surface kinds, and skinned meshes at rest whose rest pose differs from the bind pose.',
        '',
        *dcc_rows(),
        '',
    ]
    Path(output).write_text('\n'.join(lines))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'docs' / 'parity.md')
