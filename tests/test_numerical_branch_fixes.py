# SPDX-License-Identifier: MIT
"""Independent literal branch oracles for IVO-N03-01 through IVO-N03-04."""
import math
from pathlib import Path
import unittest

import msf_tools as m
from msf_tools import math3d as h
from msf_tools.report import Fault
from test_core_semantic_fixes import AssetBytes, encode

ROOT = Path(__file__).resolve().parents[1]
assert Path(m.__file__).resolve().parent == ROOT / 'msf_tools'
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
    def call(self, fn, *args, **kwargs):
        # Valid numeric refusals are semantic assertion RED, never setup errors.
        try:
            return fn(*args, **kwargs)
        except Fault as exc:
            self.fail(f'Unexpected Fault: {exc.diagnostic.to_dict()}')

    def good(self, result):
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def bad(self, result, code):
        self.assertFalse(result.ok)
        self.assertIsNone(result.value)
        self.assertIn(code, [d.code for d in result.report.diagnostics], result.report.to_dict())
        self.assertNotIn('E_INPUT', [d.code for d in result.report.diagnostics])

    def fault(self, code, fn, *args, **kwargs):
        with self.assertRaises(Fault) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.diagnostic.code, code)

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
        # An admitted later set of all zeros still exceeds the evaluator contract.
        eight=self.good(m.inspect_asset((ROOT/'tests/fixtures/eight-influence.gltf').read_bytes(),'gltf'))
        self.bad(m.evaluate_geometry(eight),'E_INFLUENCE_LIMIT')

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

    def test_linear_exact_endpoints_do_not_subtract(self):
        for a,b,t,expected in (((1.5e308,),(-1.5e308,),0,(1.5e308,)),
                                ((1.5e308,),(-1.5e308,),1,(-1.5e308,)),
                                ((-1.5e308,),(1.5e308,),0,(-1.5e308,)),
                                ((-1.5e308,),(1.5e308,),1,(1.5e308,))):
            with self.subTest(t=t,a=a):
                self.assertEqual(self.call(h.linear,a,b,t),expected)
        self.assertEqual(self.call(h.linear,(2,4),(6,8),.5),(4,6))

    def test_linear_unselected_admission_and_interior_checked(self):
        for t in (0,1):
            for bad,code in (((True,),'E_TYPE'),(('1',),'E_TYPE'),
                             ((math.nan,),'E_NONFINITE'),((10**400,),'E_NONFINITE'),
                             ((1,2),'E_SHAPE')):
                args=(bad,(0,),t) if t==1 else ((0,),bad,t)
                self.fault(code,h.linear,*args)
        for t,code in ((True,'E_TYPE'),(-1,'E_FRACTION'),(2,'E_FRACTION'),(math.inf,'E_NONFINITE')):
            self.fault(code,h.linear,(0,),(1,),t)
        self.fault('E_NONFINITE',h.linear,(1.5e308,),(-1.5e308,),.5)
        self.fault('E_NONFINITE',h.linear,(0,),(2**-800,),2**-800)

    def test_slerp_tiny_exact_endpoints_and_hemisphere(self):
        tiny=2**-800
        for q in ((tiny,0,0,1),(tiny,0,0,-1)):
            for t in (0,1):
                with self.subTest(q=q,t=t):
                    self.assertEqual(self.call(h.slerp,q,q,t),q)
                    self.assertEqual(self.call(h.slerp,q,tuple(-x for x in q),t),q)
        # At t=1 dot=-.5 selects -b; an exact-zero dot keeps authored b.
        for b, expected in (((0,0,-2,-2),(0,0,math.sqrt(.5),math.sqrt(.5))),
                             ((0,0,-2,0),(0,0,-1,0))):
            actual=self.call(h.slerp,(0,0,0,2),b,1)
            for x,y in zip(actual,expected):self.assertAlmostEqual(x,y,places=15)
        self.assertEqual(self.call(h.slerp,(0,0,0,2),(0,0,0,-2),0),(0,0,0,1))
        # Tiny dot terms round to zero: t=1 tie must retain b's sign.
        a=(tiny,1,0,0); b=(-tiny,0,1,0)
        self.assertEqual(self.call(h.slerp,a,b,0),a)
        self.assertEqual(self.call(h.slerp,a,b,1),b)

    def test_slerp_unselected_normalization_and_controls(self):
        for t in (0,1):
            for bad,code in (((True,0,0,1),'E_TYPE'),((math.nan,0,0,1),'E_NONFINITE'),
                             ((0,0,1),'E_SHAPE'),((0,0,0,0),'E_QUATERNION'),
                             ((1.5e308,1.5e308,0,0),'E_NONFINITE')):
                args=(bad,(0,0,0,1),t) if t==1 else ((0,0,0,1),bad,t)
                self.fault(code,h.slerp,*args)
        for t,code in ((True,'E_TYPE'),(-1,'E_FRACTION'),(2,'E_FRACTION'),(math.inf,'E_NONFINITE')):
            self.fault(code,h.slerp,(0,0,0,1),(0,0,0,1),t)
        tiny=(2**-800,0,0,1)
        self.fault('E_NONFINITE',h.slerp,tiny,tiny,.5)
        self.assertEqual(self.call(h.slerp,(0,0,0,2),(0,0,0,-2),.5),(0,0,0,1))

    def test_hermite_zero_tangent_tiny_and_huge_duration(self):
        for duration in (2**-1074,1.5e308):
            with self.subTest(duration=duration):
                self.assertEqual(self.call(h.hermite,(1,),(0,),(1,),(-0.,),.5,duration),(1,))
        for t,expected in ((0,(2,)),(1,(3,))):
            self.assertEqual(self.call(h.hermite,(2,),(0,),(3,),(0,),t,2**-1074),expected)
        self.assertEqual(self.call(h.hermite,(1,0,0,0),(0,0,0,0),(1,0,0,0),(0,0,0,0),.5,2**-1074,True),(1,0,0,0))

    def test_hermite_raw_signed_tangents_nonzero_checked_and_admission(self):
        self.assertEqual(self.call(h.hermite,(0,),(-2,),(0,),(4,),.5,2),(-1.5,))
        self.assertEqual(self.call(h.hermite,(0,),(2,),(0,),(0,),.5,2),(.5,))
        q=self.call(h.hermite,(0,0,0,1),(0,0,2,0),(0,0,0,1),(0,0,-2,0),.5,2,True)
        for x,y in zip(q,(0,0,math.sqrt(.5),math.sqrt(.5))):self.assertAlmostEqual(x,y,places=15)
        for tangents,duration in (((1,0),2**-1074),((0,1),2**-1074),
                                  ((1.5e308,0),16),((0,1.5e308),16)):
            self.fault('E_NONFINITE',h.hermite,(1,),(tangents[0],),(1,),(tangents[1],),.5,duration)
        for t in (0,1):
            for slot in range(4):
                for bad,code in (((True,),'E_TYPE'),((math.nan,),'E_NONFINITE'),((0,0),'E_SHAPE')):
                    args=[(1,),(0,),(1,),(0,),t,2];args[slot]=bad
                    self.fault(code,h.hermite,*args)
        for kwargs,code in (({'quaternion':1},'E_TYPE'),({'duration':True},'E_TYPE'),
                            ({'duration':0},'E_CURVE'),({'duration':-1},'E_CURVE'),
                            ({'duration':math.inf},'E_NONFINITE'),({'fraction':True},'E_TYPE'),
                            ({'fraction':2},'E_FRACTION')):
            controls=dict(fraction=.5,duration=2);controls.update(kwargs)
            self.fault(code,h.hermite,(1,),(0,),(1,),(0,),**controls)
        self.fault('E_SHAPE',h.hermite,(1,),(0,),(1,),(0,),.5,2,True)


if __name__ == '__main__':
    unittest.main()
