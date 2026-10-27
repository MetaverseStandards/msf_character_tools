# SPDX-License-Identifier: MIT
"""FBX geometry against the DCC-exported OBJ frames in ufbx's corpus (never committed).

ufbx's own tests pair each FBX file with OBJ files that Blender, Maya, 3ds Max and
MotionBuilder exported from the same scene, either at rest or at a named frame.
This tier reads those pairings from ufbx's test sources and compares every
mesh point msf-tools evaluates, in world space, with the OBJ points. The OBJ data
was not produced by ufbx or msf-tools, so it checks the conversion independently.

Points are compared as sets within ufbx's own per-file tolerance (0.001 OBJ
units unless the OBJ says otherwise). OBJ files are in the FBX file's own units
and axes: the unit comes from msf-tools' I_UNITS_CONVERTED, and the axis change
is chosen among the 24 axis-aligned rotations that best match.

A pairing that disagrees must be explained by a loss msf-tools declared for
that file, such as dropped vertex caches or in-between shapes.
"""
import itertools
import math
import os
from pathlib import Path
import re
import unittest

from test_source_fbx_native import HAVE_UFBX

ROOT = Path(os.environ['MSF_UFBX_CORPUS']) if os.environ.get('MSF_UFBX_CORPUS') else None
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


ROTATIONS = [tuple(tuple(s if c == p else 0 for c in range(3)) for p, s in zip(perm, signs))
             for perm in itertools.permutations(range(3)) for signs in itertools.product((1, -1), repeat=3)]
ROTATIONS = [r for r in ROTATIONS if round(
    r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1]) - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
    + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])) == 1]


def rotate(r, scale, p):
    return tuple(scale * sum(r[i][j] * p[j] for j in range(3)) for i in range(3))


def coverage(points, others, tolerance):
    """Fraction of `points` with a point of `others` within `tolerance`."""
    grid = {}
    for q in others:
        grid.setdefault(tuple(math.floor(x / tolerance) for x in q), []).append(q)
    near = 0
    for p in points:
        cell = tuple(math.floor(x / tolerance) for x in p)
        near += any(math.dist(p, q) <= tolerance for step in itertools.product((-1, 0, 1), repeat=3)
                    for q in grid.get(tuple(c + s for c, s in zip(cell, step)), ()))
    return near / max(1, len(points))


def world_points(snapshot, seconds):
    """Every point a triangle uses, of every mesh instance, in world space."""
    import msf_tools as m
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
        points = instance['primitives'][0]['positions']
        if 'indices' in primitive:
            points = [points[i] for i in sorted({row[0] for row in m.decode_accessor(snapshot, primitive['indices']).value})]
        index = instance['node']
        while index is not None:
            t = matrix(nodes[index], dict(overrides.get(index, {})))
            points = [[sum(t[r][c] * p[c] for c in range(3)) + t[r][3] for r in range(3)] for p in points]
            index = parent.get(index)
        out += points
    return out


def stack_names(data):
    from msf_tools_ufbx import ffi, lib
    from test_source_fbx_native import open_scene
    handle, _ = open_scene(data)
    try:
        info = ffi.new('msf_fbx_info *')
        lib.msf_fbx_info_get(handle, info)
        names = []
        for s in range(info.anim_stacks):
            stack = ffi.new('msf_fbx_stack *')
            lib.msf_fbx_stack_get(handle, s, stack)
            names.append(ffi.unpack(stack.name, stack.name_len).decode('utf-8', 'replace'))
        return names
    finally:
        lib.msf_fbx_close(handle)


def compare(fbx, obj, stack, seconds, frame_flags):
    """('match' | 'differs' | 'refused' | 'skipped', detail, declared loss codes)."""
    import msf_tools as m
    points, directives = obj_file(obj)
    if 'transform_skin' in directives:
        return 'skipped', 'the OBJ is in the bind pose space of the skin', set()
    if 'NO_EXTRAPOLATE' in frame_flags:
        return 'skipped', 'ufbx evaluates this frame with extrapolation off, which msf-tools does not use', set()
    data = fbx.read_bytes()
    options = {}
    if stack:
        options['animation'] = next(n for n in stack_names(data) if stack in n)
    result = m.inspect_asset(data, 'fbx', options=options or None)
    if not result.ok:
        return 'refused', result.report.diagnostics[0].code, {d.code for d in result.report.diagnostics}
    snapshot = result.value
    declared = {d['code'] for d in snapshot.source['losses']}
    if seconds is None and snapshot.document.get('skins'):
        return 'skipped', 'at rest the OBJ holds the unskinned mesh, which msf-tools evaluates skinned', declared
    unit = next((float(d['message'].split()[1]) for d in snapshot.source['losses'] if d['code'] == 'I_UNITS_CONVERTED'), 1.0)
    shift = next((float(d['message'].split()[4]) for d in snapshot.source['losses'] if d['code'] == 'W_TIME_SHIFTED'), 0.0)
    ours = world_points(snapshot, None if seconds is None else seconds + shift)
    if ours == 'E_GEOMETRY_EMPTY' and 'W_SKIPPED' in declared:
        return 'skipped', 'every surface in the file is of a kind msf-tools skips and declares', declared
    if isinstance(ours, str):
        return 'differs', f'geometry refused with {ours}', declared
    scale = unit * (0.01 if 'SCALE_100' in frame_flags else 1.0)
    # ufbx multiplies both sides by position_scale before comparing, which only loosens its tolerance.
    tolerance = float(directives.get('tolerance', 0.001)) / float(directives.get('position_scale', 1.0)) * scale
    sample = points[::max(1, len(points) // 200)]
    best = max(ROTATIONS, key=lambda r: coverage([rotate(r, scale, p) for p in sample], ours, tolerance))
    theirs = [rotate(best, scale, p) for p in points]
    forward, backward = coverage(theirs, ours, tolerance), coverage(ours, theirs, tolerance)
    detail = f'{forward:.3f} of OBJ points and {backward:.3f} of msf-tools points match'
    return ('match' if forward == backward == 1.0 else 'differs'), detail, declared


@unittest.skipUnless(PRESENT, 'set MSF_UFBX_CORPUS to an extracted ufbx 0.23.1 source tree to run this tier')
class DccReferenceFrames(unittest.TestCase):
    def test_msf_geometry_matches_the_dcc_exported_frames(self):
        outcomes, unexplained = {}, []
        for fbx, obj, stack, seconds, flags in pairings():
            outcome, detail, declared = compare(fbx, obj, stack, seconds, flags)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            # Singular transforms are refused by design; any other refusal or unexplained difference is a defect.
            if outcome == 'differs' and not declared & EXPLAINING or outcome == 'refused' and detail != 'E_SOURCE_VALUE':
                unexplained.append((fbx.name, obj.name, detail, sorted(declared)))
        self.assertEqual(unexplained, [])
        self.assertGreater(outcomes.get('match', 0), 250, outcomes)


if __name__ == '__main__':
    unittest.main()
