# SPDX-License-Identifier: MIT
"""Independent literal branch oracles for IVO-N03-01 through IVO-N03-04."""
import math
from pathlib import Path
import unittest

import msf_character_tools as m
from test_core_semantic_fixes import AssetBytes, encode

ROOT = Path(__file__).resolve().parents[2]
assert Path(m.__file__).resolve().parent == ROOT / 'msf_character_tools'
UNIT_COLUMNS = (1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1)


def skin_document(*, ibm_scale=1, weights=(1,0,0,0), joints=(0,1,0,0),
                  ibm_bad=None, extra=False):
    b = AssetBytes()
    p = b.rows([(2,3,4)], 'VEC3', bounds=True)
    js = b.rows([joints], 'VEC4', 5123)
    ws = b.rows([weights], 'VEC4')
    ibms = [list(UNIT_COLUMNS), list(UNIT_COLUMNS)]
    ibms[1][0] = ibm_scale
    if extra:
        ibms.append(list(UNIT_COLUMNS))
    if ibm_bad:
        row, component, value = ibm_bad
        ibms[row][component] = value
    ibm = b.rows(ibms, 'MAT4')
    return b.document(nodes=[{'mesh':0, 'skin':0, 'children':[1,2]},
                             {}, {'scale':[1.5e308,1,1]}],
        skins=[{'joints':[1,2], 'inverseBindMatrices':ibm}],
        meshes=[{'primitives':[{'mode':0, 'attributes':{
            'POSITION':p, 'JOINTS_0':js, 'WEIGHTS_0':ws}}]}])


def curve_document(mode='STEP', times=((0,),(2,)),
                   rows=((0,0,0),(4,0,0)), path='translation'):
    b = AssetBytes()
    p = b.rows([(2,3,4)], 'VEC3', bounds=True)
    ts = b.rows(times, 'SCALAR', bounds=True)
    output = b.rows(rows, 'VEC4' if path == 'rotation' else 'VEC3')
    return b.document(nodes=[{'mesh':0}], meshes=[{'primitives':[
        {'mode':0, 'attributes':{'POSITION':p}}]}], animations=[{
        'samplers':[{'input':ts, 'output':output, 'interpolation':mode}],
        'channels':[{'sampler':0, 'target':{'node':0, 'path':path}}]}])


class BranchFixes(unittest.TestCase):
    def good(self, result):
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def bad(self, result, code):
        self.assertFalse(result.ok)
        self.assertIsNone(result.value)
        self.assertIn(code, [d.code for d in result.report.diagnostics], result.report.to_dict())
        self.assertNotIn('E_INPUT', [d.code for d in result.report.diagnostics])

    def inspect(self, doc):
        return m.inspect_asset(encode(doc), 'gltf')

    def positions(self, doc):
        snapshot = self.good(self.inspect(doc))
        return self.good(m.evaluate_geometry(snapshot)).to_dict()['instances'][0]['primitives'][0]['positions']

    def test_inactive_point_overflow_is_not_a_contribution(self):
        self.assertEqual(self.positions(skin_document()), [[2,3,4]])

    def test_inactive_palette_overflow_is_not_composed(self):
        self.assertEqual(self.positions(skin_document(ibm_scale=2)), [[2,3,4]])

    def test_skin_active_overflow_order_and_mesh_local_controls(self):
        for scale in (1,2):
            snap = self.good(self.inspect(skin_document(ibm_scale=scale, weights=(0,1,0,0))))
            self.bad(m.evaluate_geometry(snap), 'E_NONFINITE')
        # Deliberately non-palette order: huge, negative huge, then 2 -> 2.
        b = AssetBytes()
        p = b.rows([(0,0,0)], 'VEC3', bounds=True)
        js = b.rows([(1,0,2,0)], 'VEC4', 5123)
        ws = b.rows([(.25,.25,.5,0)], 'VEC4')
        d = b.document(nodes=[{'mesh':0,'skin':0,'children':[1,2,3],
                              'translation':[10,0,0]},
                             {'translation':[-1e308,0,0]},
                             {'translation':[1e308,0,0]},
                             {'translation':[4,0,0]}], skins=[{'joints':[1,2,3]}],
            meshes=[{'primitives':[{'mode':0,'attributes':{
                'POSITION':p,'JOINTS_0':js,'WEIGHTS_0':ws}}]}])
        self.assertEqual(self.positions(d), [[2,0,0]])
        # A joint elsewhere in the same tree is inverse(mesh_world)*joint_world.
        d = skin_document();d['nodes'][0]['translation']=[10,20,30]
        d['nodes'][1]['translation']=[5,6,7]
        self.assertEqual(self.positions(d), [[7,9,11]])

    def test_skin_unused_original_and_extra_admission(self):
        for extra, row in ((False,1),(True,2)):
            for component, value, code in ((3,.5,'E_SKIN_TYPE'),(0,math.nan,'E_NONFINITE')):
                with self.subTest(extra=extra, component=component):
                    self.bad(self.inspect(skin_document(extra=extra,ibm_bad=(row,component,value))),code)
        for js, ws, code in (((0,2,0,0),(1,0,0,0),'E_JOINT_BOUNDS'),
                             ((0,1,0,0),(1,-.25,0,0),'E_SKIN_WEIGHTS'),
                             ((0,1,0,0),(.5,0,0,0),'E_SKIN_WEIGHTS'),
                             ((0,0,0,0),(.5,.5,0,0),'E_SKIN_WEIGHTS'),
                             ((0,1,0,0),(1,math.nan,0,0),'E_NONFINITE')):
            self.bad(self.inspect(skin_document(joints=js,weights=ws)),code)
        for component, value, code in ((3,.5,'E_TRANSFORM'),(4,.25,'E_SHEAR'),
                                        (0,0,'E_SINGULAR'),(0,True,'E_TYPE')):
            d = skin_document();d['nodes'][2]={'matrix':list(UNIT_COLUMNS)}
            d['nodes'][2]['matrix'][component]=value
            self.bad(self.inspect(d),code)
        d=skin_document();snap=self.good(self.inspect(d))
        self.bad(m.evaluate_geometry(snap,node_transforms={2:{'scale':[True,1,1]}}),'E_TYPE')
        attrs=d['meshes'][0]['primitives'][0]['attributes']
        attrs.update(JOINTS_1=attrs['JOINTS_0'],WEIGHTS_1=attrs['WEIGHTS_0'])
        self.bad(self.inspect(d),'E_SKIN_WEIGHTS')

    def test_step_subnormal_preceding_exact_final_and_geometry(self):
        snap=self.good(self.inspect(curve_document()))
        for timestamp, expected in ((0,(0,0,0)),(2**-1074,(0,0,0)),
                                    (1,(0,0,0)),(2,(4,0,0)),(3,(4,0,0))):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(self.good(m.sample_animation(snap,0,timestamp)),{0:{'translation':expected}})
        self.good(m.evaluate_geometry(snap,animation_id=0,timestamp=2**-1074))
        snap=self.good(self.inspect(curve_document(times=((0,),(1,),(2,)),
                            rows=((0,0,0),(4,0,0),(8,0,0)))))
        self.assertEqual(self.good(m.sample_animation(snap,0,1)),{0:{'translation':(4,0,0)}})

    def test_step_all_keys_times_layout_and_interpolated_underflow(self):
        for times in (((0,),(0,)),((0,),(-1,)),((0,),(math.nan,))):
            self.bad(self.inspect(curve_document(times=times)),
                     'E_NONFINITE' if math.isnan(times[1][0]) else 'E_ANIMATION_TIME')
        self.bad(self.inspect(curve_document(rows=((0,0,0),(math.nan,0,0)))),'E_NONFINITE')
        self.bad(self.inspect(curve_document(path='rotation',rows=((0,0,0,1),(0,0,0,2)))),'E_QUATERNION')
        self.bad(self.inspect(curve_document(rows=((0,0,0),))),'E_ANIMATION_TYPE')
        for mode in ('LINEAR','CUBICSPLINE'):
            rows=((0,0,0),(4,0,0)) if mode=='LINEAR' else ((0,0,0),)*6
            snap=self.good(self.inspect(curve_document(mode,rows=rows)))
            self.bad(m.sample_animation(snap,0,2**-1074),'E_NONFINITE')
        snap=self.good(self.inspect(curve_document()))
        for timestamp in (True,-1,math.inf):
            self.bad(m.sample_animation(snap,0,timestamp),'E_TIMESTAMP')


if __name__ == '__main__':
    unittest.main()
