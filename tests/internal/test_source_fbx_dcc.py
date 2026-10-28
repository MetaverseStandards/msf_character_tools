# SPDX-License-Identifier: MIT
"""FBX geometry against the DCC-exported OBJ frames in ufbx's corpus (never committed).

ufbx's own tests pair each FBX file with OBJ files that Blender, Maya, 3ds Max and
MotionBuilder exported from the same scene, either at rest or at a named frame.
This tier reads those pairings from ufbx's test sources and compares every
mesh point msf-tools evaluates, in world space, with the OBJ points. The OBJ data
was not produced by ufbx or msf-tools, so it checks the conversion independently.

Points are compared as sets within ufbx's own per-file tolerance (0.001 OBJ
units unless the OBJ says otherwise). OBJ files are in the FBX file's own units
and axes, read from its GlobalSettings by tests/public/support/fbx_header.py, not from
ufbx or msf-tools; msf-tools' declared unit must agree with it.

A pairing that disagrees is explained only mesh by mesh: every mesh with
unmatched points (an OBJ point counts against the mesh of its nearest msf-tools
point) must carry a declared loss that changes points, such as dropped vertex
caches or in-between shapes. Each explained row's match fractions are recorded
in tests/public/fixtures/dcc_differs.json, so a row that gets worse fails; set
MSF_DCC_RECORD=1 to rewrite that file. The only accepted refusal is a singular
transform.
"""
import itertools
import json
import math
import os
from pathlib import Path
import re
import unittest

from support.fbx_header import axes_and_unit
from internal import oracle
from internal.test_source_fbx_native import HAVE_UFBX

ROOT = Path(os.environ['MSF_UFBX_CORPUS']) if os.environ.get('MSF_UFBX_CORPUS') else None
RECORDED = Path(__file__).resolve().parents[1] / 'public' / 'fixtures' / 'dcc_differs.json'
PRESENT = HAVE_UFBX and ROOT is not None and (ROOT / 'test').is_dir()

BLOCK = re.compile(r'^(UFBXT_FILE_TEST[A-Z_]*)\(([^)]*)\)', re.M)
FRAME = re.compile(r'ufbxt_check_frame(?:_imp)?\(scene, err, (?:true|false), "([^"]+)", (NULL|"[^"]*"), ([0-9.+\-*/ ()]+)(?:, ([^)]+))?\)')
# Blocks loaded with ufbx's default options; the _OPTS and _ALT variants load with other settings.
DEFAULT_LOAD = ('UFBXT_FILE_TEST', 'UFBXT_FILE_TEST_FLAGS', 'UFBXT_FILE_TEST_SUFFIX')
# Each code is a loss that changes evaluated points, so a declared one explains a disagreeing frame.
EXPLAINING = {'W_SUBDIV_CAGE', 'W_POINTS_ANIMATION_DROPPED', 'W_INBETWEENS_DROPPED', 'W_INBETWEEN_PARTIAL', 'W_SKINNING_METHOD'}


def pairings():
    """(FBX path, OBJ path, stack name or None, seconds or None for rest, ufbx frame flags)."""
    out = []
    for header in sorted((ROOT / 'test').glob('*.h')):
        text = header.read_text(errors='replace')
        found = list(BLOCK.finditer(text))
        for k, block in enumerate(found):
            macro, args = block.group(1), [a.strip() for a in block.group(2).split(',')]
            if macro not in DEFAULT_LOAD:
                continue
            flags = args[1] if macro == 'UFBXT_FILE_TEST_FLAGS' else ''
            if 'DIFF_EXPECT_FAIL' in flags or 'DIFF_SCALE' in flags:
                continue
            body = text[block.start():found[k + 1].start() if k + 1 < len(found) else len(text)]
            suffix = args[1] if macro == 'UFBXT_FILE_TEST_SUFFIX' else None
            cases = [] if suffix else [(args[0] + '.obj', None, None, '')]
            for obj, stack, seconds, frame_flags in FRAME.findall(body):
                # FRAME only admits digits and arithmetic in the time expression.
                cases.append((obj + '.obj', None if stack == 'NULL' else stack.strip('"'),
                              eval(seconds, {'__builtins__': {}}), frame_flags))
            name = re.compile(re.escape(args[0]) + r'_\d+_(ascii|binary)' + (('_' + re.escape(suffix)) if suffix else '') + r'\.fbx')
            for fbx in sorted(p for p in (ROOT / 'data').iterdir() if name.fullmatch(p.name)):
                out += [(fbx, ROOT / 'data' / obj, stack, seconds, extra) for obj, stack, seconds, extra in cases
                        if (ROOT / 'data' / obj).exists()]
    return out


def obj_file(path):
    points, directives = [], {}
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('v '):
            points.append(tuple(float(x) for x in line.split()[1:4]))
        elif line.startswith('# ufbx:'):
            key, _, value = line[7:].partition('=')
            directives[key.strip()] = value.strip()
    return points, directives


def rotate(r, scale, p):
    return tuple(scale * sum(r[i][j] * p[j] for j in range(3)) for i in range(3))


def misses(points, others, tolerance):
    """Indices of `points` with no point of `others` within `tolerance`."""
    grid = {}
    for q in others:
        grid.setdefault(tuple(math.floor(x / tolerance) for x in q), []).append(q)
    out = []
    for k, p in enumerate(points):
        cell = tuple(math.floor(x / tolerance) for x in p)
        if not any(math.dist(p, q) <= tolerance for step in itertools.product((-1, 0, 1), repeat=3)
                   for q in grid.get(tuple(c + s for c, s in zip(cell, step)), ())):
            out.append(k)
    return out


def world_points(snapshot, seconds):
    """Per mesh instance: (mesh index, skinned?, world points, the same points in mesh space, and unskinned), for every
    point its triangles use; or the geometry refusal code."""
    import msf_character_tools as m
    from test_source_strict import matrix
    nodes = snapshot.document['nodes']
    animated = seconds is not None and bool(snapshot.document.get('animations'))
    overrides = m.sample_animation(snapshot, 0, seconds).value if animated else {}
    kwargs = {'timestamp': seconds, 'animation_id': 0} if animated else {}
    parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', ())}
    out = []
    geometry = m.evaluate_geometry(snapshot, **kwargs)
    if not geometry.ok:
        return geometry.report.diagnostics[0].code
    for instance in geometry.value.to_dict()['instances']:
        primitive = snapshot.document['meshes'][instance['mesh']]['primitives'][0]
        evaluated = instance['primitives'][0]['positions']
        used = sorted({row[0] for row in m.decode_accessor(snapshot, primitive['indices']).value}) if 'indices' in primitive \
            else range(len(evaluated))
        authored = m.decode_accessor(snapshot, primitive['attributes']['POSITION']).value
        local, unskinned = [evaluated[i] for i in used], [authored[i] for i in used]
        points, index = local, instance['node']
        while index is not None:
            t = matrix(nodes[index], dict(overrides.get(index, {})))
            points = [[sum(t[r][c] * p[c] for c in range(3)) + t[r][3] for r in range(3)] for p in points]
            index = parent.get(index)
        out.append((instance['mesh'], 'skin' in nodes[instance['node']], points, local, unskinned))
    return out


def stack_names(data):
    from internal.test_source_fbx_native import open_scene
    scene, _ = open_scene(data)
    return [scene.stack(s)[0].decode('utf-8', 'replace') for s in range(scene.info()['anim_stacks'])]


def explaining_meshes(snapshot):
    """Mesh indices that a declared, point-changing loss names (through any node that instances the mesh)."""
    paths = snapshot.source['node_paths']
    meshes = {path: node['mesh'] for path, node in zip(paths, snapshot.document['nodes']) if 'mesh' in node}
    return {meshes[d['ref']] for d in snapshot.source['losses'] if d['code'] in EXPLAINING and d['ref'] in meshes}


def compare(fbx, obj, stack, seconds, frame_flags):
    """('match' | 'differs' | 'explained' | 'refused' | 'skipped', detail, (OBJ, msf-tools) match fractions)."""
    import msf_character_tools as m
    points, directives = obj_file(obj)
    if 'transform_skin' in directives:
        return 'skipped', 'the OBJ is in the bind pose space of the skin', None
    if 'NO_EXTRAPOLATE' in frame_flags:
        return 'skipped', 'ufbx evaluates this frame with extrapolation off, which msf-tools does not use', None
    data = fbx.read_bytes()
    options = {}
    if stack:
        options['animation'] = next(n for n in stack_names(data) if stack in n)
    result = m.inspect_asset(data, 'fbx', options=options or None)
    if not result.ok:
        first = result.report.diagnostics[0]
        return ('refused' if (first.code, first.message) == ('E_SOURCE_VALUE', 'Transform is singular.') else 'differs'), \
            f'{first.code}: {first.message}', None
    snapshot = result.value
    losses = snapshot.source['losses']
    rotation, unit = axes_and_unit(data)
    declared_unit = next((float(d['message'].split()[1]) for d in losses if d['code'] == 'I_UNITS_CONVERTED'), 1.0)
    if not math.isclose(unit, declared_unit, rel_tol=1e-6):
        return 'differs', f'the file header says {unit:g} metres per unit; msf-tools declared {declared_unit:g}', None
    if (rotation not in (None, ((1, 0, 0), (0, 1, 0), (0, 0, 1)))) != any(d['code'] == 'I_AXES_CONVERTED' for d in losses):
        return 'differs', 'the file header and msf-tools disagree about converting axes', None
    rotation = rotation or ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    shift = next((float(d['message'].split()[4]) for d in losses if d['code'] == 'W_TIME_SHIFTED'), 0.0)
    instances = world_points(snapshot, None if seconds is None else seconds + shift)
    if instances == 'E_GEOMETRY_EMPTY' and any(d['code'] == 'W_SKIPPED' for d in losses):
        return 'skipped', 'every surface in the file is of a kind msf-tools skips and declares', None
    if isinstance(instances, str):
        return 'differs', f'geometry refused with {instances}', None
    scale = unit * (0.01 if 'SCALE_100' in frame_flags else 1.0)
    # ufbx multiplies both sides by position_scale before comparing, which only loosens its tolerance.
    tolerance = float(directives.get('tolerance', 0.001)) / float(directives.get('position_scale', 1.0)) * scale
    theirs = [rotate(rotation, scale, p) for p in points]
    ours = [p for _, _, world, _, _ in instances for p in world]
    owner = [mesh for mesh, _, world, _, _ in instances for _ in world]
    lost_obj, lost_ours = misses(theirs, ours, tolerance), misses(ours, theirs, tolerance)
    fractions = (round(1 - len(lost_obj) / max(1, len(theirs)), 3), round(1 - len(lost_ours) / max(1, len(ours)), 3))
    detail = f'{fractions[0]:.3f} of OBJ points and {fractions[1]:.3f} of msf-tools points match'
    if not lost_obj and not lost_ours:
        return 'match', detail, fractions
    if seconds is None and any(skinned for _, skinned, _, _, _ in instances):
        # At rest the OBJ holds the mesh as authored; msf-tools skins it with the rest pose, which differs when
        # rest is not bind. Only then is a difference expected.
        if any(any(math.dist(a, b) > 1e-6 for a, b in zip(local, unskinned))
               for _, skinned, _, local, unskinned in instances if skinned):
            return 'skipped', 'at rest, and the rest pose differs from the bind pose the OBJ holds', None
    nearest = []
    for k in lost_obj:
        nearest.append(min(range(len(ours)), key=lambda i: math.dist(theirs[k], ours[i])))
    blamed = {owner[i] for i in lost_ours} | {owner[i] for i in nearest}
    if blamed <= explaining_meshes(snapshot):
        return 'explained', detail, fractions
    return 'differs', detail + f'; meshes {sorted(blamed - explaining_meshes(snapshot))} have no loss that explains it', fractions


@unittest.skipUnless(PRESENT, 'set MSF_UFBX_CORPUS to an extracted ufbx 0.23.1 source tree to run this tier')
class DccReferenceFrames(unittest.TestCase):
    def test_msf_geometry_matches_the_dcc_exported_frames(self):
        outcomes, unexplained, rows = {}, [], {}
        for fbx, obj, stack, seconds, flags in pairings():
            outcome, detail, fractions = compare(fbx, obj, stack, seconds, flags)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if outcome == 'differs':
                unexplained.append((fbx.name, obj.name, detail))
            if outcome == 'explained':
                rows[f'{fbx.name} {obj.name} {stack} {seconds}'] = list(fractions)
        if os.environ.get('MSF_DCC_RECORD'):
            RECORDED.write_text(json.dumps(rows, indent=1, sort_keys=True) + '\n')
        recorded = json.loads(RECORDED.read_text())
        worse = [(key, recorded.get(key), now) for key, now in rows.items()
                 if key not in recorded or any(n < r - 0.005 for n, r in zip(now, recorded[key]))]
        self.assertEqual(unexplained, [])
        self.assertEqual(worse, [])
        self.assertGreater(outcomes.get('match', 0), 250, outcomes)



FRAME_OUTCOME = r"""
def dcc_frame(path, animation, seconds):
    from pathlib import Path
    result = m.inspect_asset(Path(path).read_bytes(), 'fbx', options={'animation': animation} if animation else None)
    out = [encode(result)]
    if result.ok:
        s = result.value
        out.append(encode(s.original_bytes))
        shift = next((float(d['message'].split()[4]) for d in s.source['losses'] if d['code'] == 'W_TIME_SHIFTED'), 0.0)
        if seconds is not None and s.document.get('animations'):
            out.append(attempt(lambda: m.sample_animation(s, 0, seconds + shift)))
            out.append(attempt(lambda: m.evaluate_geometry(s, animation_id=0, timestamp=seconds + shift)))
        else:
            out.append(attempt(lambda: m.evaluate_geometry(s)))
    return out
"""


@unittest.skipUnless(PRESENT, 'set MSF_UFBX_CORPUS to an extracted ufbx 0.23.1 source tree to run this tier')
@unittest.skipIf(oracle.skip_reason(), oracle.skip_reason() or '')
class DccFramesAgainstTheOracle(unittest.TestCase):
    def test_every_dcc_frame_evaluates_as_0_3_0_did(self):
        oracle.define(FRAME_OUTCOME)
        frames = set()
        for fbx, _, stack, seconds, _ in pairings():
            animation = next(n for n in stack_names(fbx.read_bytes()) if stack in n) if stack else None
            frames.add((str(fbx), animation, seconds))
        cases = [('dcc_frame(path, animation, seconds)', {'path': f, 'animation': a, 'seconds': t}) for f, a, t in sorted(frames, key=repr)]
        differing = oracle.differ(cases)
        self.assertEqual([tuple(case[1].values()) for case, _, _ in differing[:5]], [], f'{len(differing)} of {len(cases)} frames differ')


if __name__ == '__main__':
    unittest.main()
