# SPDX-License-Identifier: MIT
"""Strict tier: every synthetic USD fixture, as USDA, USDC and USDZ, against usd-core's own answers.

Topology must match exactly, world positions within 1e-5 of the bounding-box
diagonal at every authored time, and skin weights within 1e-6.
"""
import io
import math
from pathlib import Path
import tempfile
import unittest
import zipfile

import make_source_fixtures
import msf_tools as m
from test_source_usd import HAVE_USD, trs

SOURCE = Path(__file__).resolve().parent / 'fixtures' / 'source'
SKIN = ('rig', 'rig_zup_cm', 'dual_quaternion', 'eight_influences', 'constant_influences')
CASES = {
    'rig': ([], (0, 12, 24)),
    'rig_zup_cm': (['I_UNITS_CONVERTED', 'I_AXES_CONVERTED'], (0, 12, 24)),
    'dual_quaternion': (['W_SKINNING_METHOD'], (0, 12, 24)),
    'eight_influences': (['I_INFLUENCES_N'], (0,)),
    'constant_influences': ([], (0,)),
    'left_handed': (['I_WINDING_FLIPPED'], (0,)),
    'ngon_holes': (['W_SKIPPED'], (0,)),
    'default_subdiv': (['W_SUBDIV_CAGE'], (0,)),
    'inbetween': (['W_INBETWEENS_DROPPED'], (0,)),
    'static_leaf_shear': (['W_SHEAR_BAKED'], (0,)),
    'interior_shear': ('E_SHEAR_UNSUPPORTED', None),
    'animated_shear': ('E_SHEAR_UNSUPPORTED', None),
    'rotated_scaled_interior': ([], (0,)),
    'mirrored': (['I_MIRRORED'], (0,)),
    'negative_time': (['W_TIME_SHIFTED'], (-12, 0, 12)),
    'instancing': ([], (0,)),
    'point_instancer': (['W_SKIPPED'], (0,)),
    'layers': ([], (0,)),
    'escape': ('E_SOURCE_REFERENCE', None),
}


def setUpModule():
    if HAVE_USD:
        # Importing pxr and opening the first stage take about half a second; pay that once, not in the first test.
        from pxr import Usd
        Usd.Stage.CreateInMemory()


def variants(name):
    """The fixture as (format, bytes): USDA from disk, USDC exported by usd-core, and a stored USDZ."""
    from pxr import Sdf
    text = (SOURCE / f'{name}.usda').read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / 'root.usdc'
        Sdf.Layer.FindOrOpen(str(SOURCE / f'{name}.usda')).Export(str(target))
        binary = target.read_bytes()
    members = [('root.usda', text)] + [(f'layers/{p.name}', p.read_bytes())
                                       for p in sorted((SOURCE / 'layers').iterdir())] * (name == 'layers')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for member, payload in members:
            archive.writestr(zipfile.ZipInfo(member), payload)
    return [('usda', text), ('usdc', binary), ('usdz', buffer.getvalue())]


def matrix(node, override):
    return trs(dict(node, **override))


def msf_world_points(snapshot, path, seconds):
    nodes = snapshot.document['nodes']
    animated = bool(snapshot.document.get('animations'))
    overrides = m.sample_animation(snapshot, 0, seconds).value if animated else {}
    parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', ())}
    index = snapshot.source['node_paths'].index(path)
    kwargs = {'timestamp': seconds, 'animation_id': 0} if animated else {}
    instances = m.evaluate_geometry(snapshot, **kwargs).value.to_dict()['instances']
    points = next(i for i in instances if i['node'] == index)['primitives'][0]['positions']
    while index is not None:
        t = matrix(nodes[index], dict(overrides.get(index, {})))
        points = [[sum(t[r][c] * p[c] for c in range(3)) + t[r][3] for r in range(3)] for p in points]
        index = parent.get(index)
    return points


class Oracle:
    """usd-core's view of one fixture, opened from disk, converted to metres and +Y up."""

    def __init__(self, path):
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel
        self.Gf, self.Usd, self.UsdGeom, self.UsdSkel = Gf, Usd, UsdGeom, UsdSkel
        source = Usd.Stage.Open(str(path))
        copy = Sdf.Layer.CreateAnonymous('.usda')
        copy.TransferContent(source.Flatten())
        self.stage = Usd.Stage.Open(copy)
        self.scale = UsdGeom.GetStageMetersPerUnit(self.stage)
        self.z_up = UsdGeom.GetStageUpAxis(self.stage) == UsdGeom.Tokens.z
        self.meshes = [p for p in self.stage.Traverse(Usd.TraverseInstanceProxies()) if p.IsA(UsdGeom.Mesh)]

    def bake(self, codes=None):
        """Bake skinning at the authored time codes between the first and last of `codes` (all of them if None)."""
        for prim in self.stage.Traverse():
            if prim.IsA(self.UsdSkel.Root):
                for mesh in self.meshes:
                    if mesh.IsInstanceProxy():
                        continue
                    method = mesh.GetAttribute('primvars:skel:skinningMethod')
                    if method:
                        method.Set('classicLinear')  # the oracle compares linear blend skinning only
                interval = self.Gf.Interval.GetFullInterval() if codes is None else self.Gf.Interval(min(codes), max(codes))
                self.UsdSkel.BakeSkinning(self.UsdSkel.Root(prim), interval)

    def convert(self, p):
        x, y, z = (self.scale * v for v in p)
        return [x, z, -y] if self.z_up else [x, y, z]

    def world_points(self, prim, code):
        mesh = self.UsdGeom.Mesh(prim)
        world = mesh.ComputeLocalToWorldTransform(code)
        return [self.convert(world.Transform(self.Gf.Vec3d(p))) for p in mesh.GetPointsAttr().Get(code)]

    def triangles(self, prim):
        mesh = self.UsdGeom.Mesh(prim)
        counts, indices = list(mesh.GetFaceVertexCountsAttr().Get()), list(mesh.GetFaceVertexIndicesAttr().Get())
        holes = set(mesh.GetHoleIndicesAttr().Get() or ())
        flip = mesh.GetOrientationAttr().Get() == 'leftHanded'
        out, start = [], 0
        for f, n in enumerate(counts):
            face, start = indices[start:start + n], start + n
            if f not in holes:
                for k in range(1, n - 1):
                    out += [face[0], face[k + 1], face[k]] if flip else [face[0], face[k], face[k + 1]]
        return out

    def weights(self, prim):
        binding = self.UsdSkel.BindingAPI(prim)
        skel = binding.GetInheritedSkeleton()
        order = [str(t) for t in skel.GetJointsAttr().Get()]
        local = binding.GetJointsAttr().Get()
        mapping = [order.index(str(t)) for t in local] if local else list(range(len(order)))
        indices = binding.GetJointIndicesPrimvar()
        weights = binding.GetJointWeightsPrimvar()
        size = indices.GetElementSize()
        flat_i, flat_w = list(indices.Get()), list(weights.Get())
        count = len(self.UsdGeom.Mesh(prim).GetPointsAttr().Get())
        if indices.GetInterpolation() == 'constant':
            flat_i, flat_w = flat_i * count, flat_w * count
        rows = []
        for v in range(count):
            merged = {}
            for j, w in zip(flat_i[v * size:v * size + size], flat_w[v * size:v * size + size]):
                if w:
                    merged[mapping[j]] = merged.get(mapping[j], 0.0) + w
            total = math.fsum(merged.values())
            rows.append({j: w / total for j, w in merged.items()})
        return rows


def msf_weights(snapshot, mesh_index):
    attributes = snapshot.document['meshes'][mesh_index]['primitives'][0]['attributes']
    rows = None
    for s in range(4):
        if f'JOINTS_{s}' not in attributes:
            break
        joints = m.decode_accessor(snapshot, attributes[f'JOINTS_{s}']).value
        weights = m.decode_accessor(snapshot, attributes[f'WEIGHTS_{s}']).value
        rows = rows or [{} for _ in joints]
        for row, js, ws in zip(rows, joints, weights):
            for j, w in zip(js, ws):
                if w:
                    row[j] = row.get(j, 0.0) + w
    return rows


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class StrictTier(unittest.TestCase):
    def test_fixtures_match_their_generator(self):
        for name, text in make_source_fixtures.cases().items():
            self.assertEqual((SOURCE / name).read_text(), text, name)

    def check(self, name):
        expected, codes = CASES[name]
        resolver = m.LocalResolver(SOURCE) if name == 'layers' else None
        documents = set()
        for fmt, data in variants(name):
            result = m.inspect_asset(data, fmt, resolver=resolver)
            if isinstance(expected, str):
                self.assertEqual([d.code for d in result.report.diagnostics], [expected], fmt)
                continue
            self.assertTrue(result.ok, (fmt, result.report.to_dict()))
            snapshot = result.value
            self.assertEqual([d['code'] for d in snapshot.source['losses']], expected, fmt)
            documents.add(m.canonical_json(snapshot.document))
        if isinstance(expected, str):
            return
        self.assertEqual(len(documents), 1, 'USDA, USDC and USDZ give different documents')
        oracle = Oracle(SOURCE / f'{name}.usda')
        paths = snapshot.source['node_paths']
        for prim in oracle.meshes:
            node = snapshot.document['nodes'][paths.index(str(prim.GetPath()))]
            primitive = snapshot.document['meshes'][node['mesh']]['primitives'][0]
            self.assertEqual([i for (i,) in m.decode_accessor(snapshot, primitive['indices']).value], oracle.triangles(prim))
            if name in SKIN:
                for actual, wanted in zip(msf_weights(snapshot, node['mesh']), oracle.weights(prim)):
                    self.assertEqual(set(actual), set(wanted))
                    for j in wanted:
                        self.assertAlmostEqual(actual[j], wanted[j], delta=1e-6)
        if codes is None:
            return
        if name in SKIN:
            oracle.bake(codes)
        shift = min(0, codes[0])
        rate = oracle.stage.GetTimeCodesPerSecond()
        for code in codes:
            for prim in oracle.meshes:
                wanted = oracle.world_points(prim, code)
                actual = msf_world_points(snapshot, str(prim.GetPath()), (code - shift) / rate)
                diagonal = math.dist([min(c) for c in zip(*wanted)], [max(c) for c in zip(*wanted)])
                for a, w in zip(actual, wanted):
                    self.assertLess(math.dist(a, w), 1e-5 * diagonal, (prim.GetPath(), code, actual, wanted))


for _name in CASES:
    setattr(StrictTier, f'test_{_name}', lambda self, name=_name: self.check(name))


if __name__ == '__main__':
    unittest.main()
