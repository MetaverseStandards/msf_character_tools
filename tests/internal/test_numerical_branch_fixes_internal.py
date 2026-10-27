# SPDX-License-Identifier: MIT
"""Branch fixes in the private checked-math helpers in msf_tools.math3d."""
import math
import unittest

import msf_tools as m
from msf_tools import math3d as h
from msf_tools.report import Fault
from test_core_semantic_fixes import encode


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
