# SPDX-License-Identifier: MIT
"""Literal analytical oracles for the complete pure numerical CONTRACT_03."""
import gc
import math
from pathlib import Path
import unittest

import msf_tools as m
from msf_tools import math3d as h
from msf_tools.report import Fault
from test_core_semantic_fixes import AssetBytes, encode, morph_asset
from test_reference import source_doc, compile_map, rule, signal

ROOT = Path(__file__).resolve().parents[1]
assert Path(m.__file__).resolve().parent == ROOT / 'msf_tools'
ROWS = ((2,0,0,3),(0,-3,0,4),(0,0,4,5),(0,0,0,1))
COLUMNS = (2,0,0,0, 0,-3,0,0, 0,0,4,0, 3,4,5,1)
PARENT = (0,1,0,0, -1,0,0,0, 0,0,1,0, 10,20,0,1)
CHILD = (0,2,0,0, -3,0,0,0, 0,0,4,0, 4,28,12,1)
LOCAL = (2,0,0,0, 0,3,0,0, 0,0,4,0, 8,6,12,1)


def diag(x,y=1,z=1):
    return ((x,0,0,0),(0,y,0,0),(0,0,z,0),(0,0,0,1))


def node_asset(node):
    b = AssetBytes()
    p = b.rows([(1,2,3)], 'VEC3', bounds=True)
    return b.document(nodes=[dict(node, mesh=0)], meshes=[{'primitives': [
        {'mode':0,'attributes':{'POSITION':p}}]}])


class NumericChecks(unittest.TestCase):
    def fault(self, code, fn, *args, **kwargs):
        with self.assertRaises(Fault) as raised:
            fn(*args, **kwargs)
        self.assertEqual(raised.exception.diagnostic.code, code)

    def good(self, result):
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def bad(self, result, code):
        self.assertFalse(result.ok, result)
        self.assertIsNone(result.value)
        self.assertIn(code, [d.code for d in result.report.diagnostics])

    def test_new_helpers_types_shapes_and_tolerances(self):
        for bad,code in ((True,'E_TYPE'),('1','E_TYPE'),(math.inf,'E_NONFINITE')):
            rows=[list(row) for row in h.IDENTITY];rows[0][0]=bad
            for fn,args in ((h.affine,(rows,)),(h.validate_trs,(rows,)),
                            (h.authored_quaternion,((bad,0,0,1),)),
                            (h.linear,((bad,),(0,),.5)),
                            (h.hermite,((0,),(bad,),(0,),(0,),.5,2))):
                with self.subTest(fn=fn.__name__,bad=bad):self.fault(code,fn,*args)
            self.fault(code,h.affine,h.IDENTITY,bad)
            self.fault(code,h.validate_trs,h.IDENTITY,tolerance=bad)
            self.fault(code,h.hermite,(0,),(0,),(0,),(0,),.5,bad)
        for fn,args in ((h.affine,([[1]*4]*3,)),(h.validate_trs,([[1]*4]*3,)),
                        (h.authored_quaternion,((0,0,1),)),(h.linear,((1,),(1,2),.5)),
                        (h.hermite,((0,),(0,0),(0,),(0,),.5,2))):
            self.fault('E_SHAPE',fn,*args)
        self.fault('E_TRANSFORM',h.affine,h.IDENTITY,-1)
        self.fault('E_TRANSFORM',h.validate_trs,h.IDENTITY,tolerance=0)
        self.fault('E_NONFINITE',h.linear,(1e308,),(-1e308,),.5)
        for duration,code in ((True,'E_TYPE'),(-1,'E_CURVE')):
            self.fault(code,h.hermite,(0,),(0,),(0,),(0,),.5,duration)
        self.fault('E_NONFINITE',h.normalize,(1.5e308,1.5e308,0,0))
        self.fault('E_NONFINITE',h.trs,(0,0,0),(2**-800,0,0,1))
        self.fault('E_NONFINITE',h.validate_trs,((1,2**-800,0,0),(2**-800,1,0,0),(0,0,1,0),(0,0,0,1)))

    def test_preserved_role_tolerance_boundaries(self):
        for value,accepted in ((.5e-7,True),(2e-7,False)):
            rows=[list(row) for row in h.IDENTITY];rows[3][0]=value
            if accepted:self.assertEqual(h.transform(rows,(0,0,0)),(0,0,0))
            else:self.fault('E_TRANSFORM',h.transform,rows,(0,0,0))
        for value,accepted in ((.5e-9,True),(2e-9,False)):
            rows=[list(row) for row in h.IDENTITY];rows[0][1]=value
            if accepted:h.validate_trs(rows)
            else:self.fault('E_SHEAR',h.validate_trs,rows)
        for value,accepted in ((.5e-12,True),(2e-12,False)):
            cols=[1,0,0,value,0,1,0,0,0,0,1,0,0,0,0,1]
            result=m.inspect_asset(encode(node_asset({'matrix':cols})),'gltf')
            if accepted:self.good(result)
            else:self.bad(result,'E_TRANSFORM')
        for squared,accepted in ((1+0.5e-5,True),(1+2e-5,False)):
            q=(0,0,0,math.sqrt(squared))
            if accepted:self.assertEqual(h.authored_quaternion(q),q)
            else:self.fault('E_QUATERNION',h.authored_quaternion,q)

    def test_storage_point_inverse_and_owning_outputs(self):
        values = list(COLUMNS)
        rows = h.matrix(values)
        self.assertEqual(rows, ROWS)
        self.assertEqual(h.column_major(rows), list(COLUMNS))
        self.assertEqual(h.transform(rows,(1,2,3)), (5,-2,17))
        self.assertEqual(h.transform(h.inverse(rows),(5,-2,17)), (1,2,3))
        output = h.column_major(rows)
        values[0] = 99; output[0] = 88
        del values; gc.collect()
        self.assertEqual(rows, ROWS)
        self.assertEqual(h.multiply(rows, h.IDENTITY), ROWS)

    def test_every_existing_helper_strict_numeric_arguments(self):
        for bad in (True, '1', float('nan'), float('inf'), 10**400):
            code = 'E_TYPE' if type(bad) not in (int,float) else 'E_NONFINITE'
            cols = list(COLUMNS); cols[0] = bad
            rows = [list(r) for r in ROWS]; rows[0][0] = bad
            for fn,args in ((h.matrix,(cols,)),(h.column_major,(rows,)),
                            (h.multiply,(rows,h.IDENTITY)),(h.multiply,(h.IDENTITY,rows)),
                            (h.inverse,(rows,)),(h.transform,(rows,(0,0,0))),
                            (h.transform,(h.IDENTITY,(bad,0,0))),
                            (h.normalize,((bad,0,0,1),)),
                            (h.trs,((bad,0,0),)),
                            (h.trs,((0,0,0),(0,0,0,1),(bad,1,1))),
                            (h.slerp,((0,0,0,1),(bad,0,0,1),.5))):
                with self.subTest(fn=fn.__name__,bad=repr(bad)):
                    self.fault(code,fn,*args)

    def test_every_existing_helper_shape(self):
        for fn,args in ((h.matrix,([1]*15,)),(h.matrix,([1]*17,)),
                        (h.column_major,([[1]*4]*3,)),(h.inverse,([[1]*3]*4,)),
                        (h.multiply,(h.IDENTITY,[[1]*4]*5)),
                        (h.transform,(h.IDENTITY,(1,2))),
                        (h.normalize,((0,0,1),)),(h.trs,((0,0),)),
                        (h.slerp,((0,0,1),(0,0,0,1),.5))):
            with self.subTest(fn=fn.__name__): self.fault('E_SHAPE',fn,*args)

    def test_full_affine_row_at_origin(self):
        projective = [list(row) for row in h.IDENTITY]; projective[3][0] = .5
        self.fault('E_TRANSFORM',h.transform,projective,(0,0,0))
        self.assertEqual(h.multiply(projective,h.IDENTITY),tuple(map(tuple,projective)))

    def test_reparent_noncommuting_hand_math_and_original_affine(self):
        self.assertEqual(self.good(m.reparent_local(CHILD,PARENT)),LOCAL)
        p = list(COLUMNS); p[3] = .5
        self.bad(m.reparent_local(p,p),'E_TRANSFORM')

    def test_reparent_huge_identical_axes_and_reflection(self):
        for size in (1e200,1.5e308):
            a = (size,size,0,0, size,size,0,0, 0,0,1,0, 0,0,0,1)
            self.bad(m.reparent_local(a,(1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1)),
                     'E_SHEAR' if size==1e200 else 'E_NONFINITE')
        reflection = (-2,0,0,0,0,3,0,0,0,0,4,0,0,0,0,1)
        self.assertEqual(self.good(m.reparent_local(reflection,h.column_major(h.IDENTITY))),reflection)

    def test_huge_and_tiny_orthogonal_axes(self):
        for size in (1e200,1e-200):
            a=diag(size,size,size)
            self.assertEqual(h.inverse(a),diag(1/size,1/size,1/size))
            self.assertEqual(self.good(m.reparent_local(h.column_major(a),h.column_major(h.IDENTITY))),tuple(h.column_major(a)))
        q=h.normalize((1e200,0,0,1e200))
        for actual,expected in zip(q,(math.sqrt(.5),0,0,math.sqrt(.5))): self.assertAlmostEqual(actual,expected,places=15)

    def test_intermediate_overflow_underflow_and_representable_subnormal(self):
        self.assertEqual(h.multiply(diag(1.5e308),h.IDENTITY),diag(1.5e308))
        self.fault('E_NONFINITE',h.multiply,diag(1.5e308),diag(2))
        self.fault('E_NONFINITE',h.multiply,diag(2**-800),diag(2**-800))
        self.assertEqual(h.multiply(diag(2**-1022),diag(.5)),diag(2**-1023))
        self.fault('E_NONFINITE',h.inverse,diag(2**-1074))
        # Elimination overflows even though the exact inverse would be finite.
        a=((1e308,1e308,0,0),(-1e308,1e308,0,0),(0,0,1,0),(0,0,0,1))
        self.fault('E_NONFINITE',h.inverse,a)

    def test_quaternion_default_normalization_and_fractions(self):
        self.assertEqual(h.normalize((0,0,0,2)),(0,0,0,1))
        self.assertEqual(h.slerp((0,0,0,2),(0,0,0,-2),.5),(0,0,0,1))
        self.fault('E_QUATERNION',h.normalize,(0,0,0,0))
        for fraction,code in ((True,'E_TYPE'),(-.1,'E_FRACTION'),(1.1,'E_FRACTION'),(math.inf,'E_NONFINITE')):
            self.fault(code,h.slerp,(0,0,0,1),(0,0,0,1),fraction)

    def test_hermite_literal_oracle_controls_and_intermediates(self):
        self.assertEqual(h.hermite((0,),(2,),(0,),(0,),.5,2),(.5,))
        self.assertEqual(h.hermite((0,0,0,2),(0,0,0,0),(0,0,0,2),(0,0,0,0),.5,2,True),(0,0,0,1))
        for args,code in ((((),(),(),(),.5,2),'E_SHAPE'),
                          (((0,),(2,),(0,),(0,),-.1,2),'E_FRACTION'),
                          (((0,),(2,),(0,),(0,),.5,0),'E_CURVE'),
                          (((0,),(2,),(0,),(0,),.5,2,1),'E_TYPE'),
                          (((0,),(1.5e308,),(0,),(1.5e308,),.5,16),'E_NONFINITE')):
            self.fault(code,h.hermite,*args)

    def test_authored_matrix_decomposition_positive_and_negative(self):
        for mat,code in (((1,0,0,0,.25,1,0,0,0,0,1,0,0,0,0,1),'E_SHEAR'),
                         ((0,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1),'E_SINGULAR'),
                         ((1,0,0,.5,0,1,0,0,0,0,1,0,0,0,0,1),'E_TRANSFORM')):
            self.bad(m.inspect_asset(encode(node_asset({'matrix':mat})),'gltf'),code)
        snapshot=self.good(m.inspect_asset(encode(node_asset({'matrix':COLUMNS})),'gltf'))
        self.assertEqual(self.good(m.evaluate_geometry(snapshot)).to_dict()['instances'][0]['primitives'][0]['positions'],[[1,2,3]])

    def test_explicit_zero_scale_only_inverse_requires_nonsingular(self):
        self.assertEqual(h.trs(s=(0,2,3)),diag(0,2,3))
        snapshot=self.good(m.inspect_asset(encode(node_asset({'scale':[0,2,3]})),'gltf'))
        self.good(m.evaluate_geometry(snapshot))
        self.fault('E_SINGULAR',h.inverse,h.trs(s=(0,2,3)))
        d=morph_asset(skin=True); d['nodes'][0]['scale']=[0,1,1]
        self.bad(m.evaluate_geometry(self.good(m.inspect_asset(encode(d),'gltf'))),'E_SINGULAR')

    def test_override_matrix_and_authored_quaternion(self):
        snap=self.good(m.inspect_asset(encode(node_asset({'matrix':COLUMNS})),'gltf'))
        shear=list(COLUMNS);shear[4]=.25
        self.bad(m.evaluate_geometry(snap,node_transforms={0:{'matrix':shear}}),'E_SHEAR')
        snap=self.good(m.inspect_asset(encode(node_asset({})),'gltf'))
        self.bad(m.evaluate_geometry(snap,node_transforms={0:{'rotation':(0,0,0,2)}}),'E_QUATERNION')
        self.bad(m.inspect_asset(encode(node_asset({'rotation':(1e200,0,0,1e200)})),'gltf'),'E_QUATERNION')

    def test_signed_huge_morph_and_overflow(self):
        snapshot=self.good(m.inspect_asset(encode(morph_asset()),'gltf'))
        def positions(weight):
            return self.good(m.evaluate_geometry(snapshot,morph_weights={0:[weight]})).to_dict()['instances'][0]['primitives'][0]['positions']
        self.assertEqual(positions(-2),[[2,-8,0]])
        self.assertEqual(positions(-1e200),[[2,-4e200,0]])
        self.bad(m.evaluate_geometry(snapshot,morph_weights={0:[1.5e308]}),'E_NONFINITE')

    def test_morph_product_underflow_refuses(self):
        b=AssetBytes(); p=b.rows([(1,0,0)],'VEC3',bounds=True); d=b.rows([(2**-149,0,0)],'VEC3',bounds=True)
        doc=b.document(nodes=[{'mesh':0}],meshes=[{'primitives':[{'mode':0,'attributes':{'POSITION':p},'targets':[{'POSITION':d}]}]}])
        snap=self.good(m.inspect_asset(encode(doc),'gltf'))
        self.bad(m.evaluate_geometry(snap,morph_weights={0:[2**-1000]}),'E_NONFINITE')

    def test_singular_weighted_skin_blend_is_valid_position_map(self):
        b=AssetBytes(); p=b.rows([(2,3,4)],'VEC3',bounds=True); js=b.rows([(0,1,0,0)],'VEC4',5123); ws=b.rows([(.5,.5,0,0)],'VEC4')
        d=b.document(nodes=[{'mesh':0,'skin':0,'children':[1,2]},{},{'scale':[-1,1,1]}],
                     skins=[{'joints':[1,2]}],meshes=[{'primitives':[{'mode':0,'attributes':{'POSITION':p,'JOINTS_0':js,'WEIGHTS_0':ws}}]}])
        snap=self.good(m.inspect_asset(encode(d),'gltf'))
        self.assertEqual(self.good(m.evaluate_geometry(snap)).to_dict()['instances'][0]['primitives'][0]['positions'],[[0,3,4]])

    def test_world_product_overflow_before_output(self):
        d=node_asset({'scale':[1.5e308,1,1],'children':[1]});d['nodes'].append({'scale':[2,1,1]})
        snap=self.good(m.inspect_asset(encode(d),'gltf'))
        self.bad(m.evaluate_geometry(snap),'E_NONFINITE')

    def test_animation_interpolation_controls(self):
        b=AssetBytes(); aid=b.rows([(0,),(0,),(2,),(0,),(0,),(0,)],'SCALAR')
        # Use existing layout author to construct a separate binary asset.
        p=b.rows([(1,0,0)],'VEC3',bounds=True);delta=b.rows([(0,1,0)],'VEC3',bounds=True);times=b.rows([(0,),(2,)],'SCALAR',bounds=True)
        d=b.document(nodes=[{'mesh':0}],meshes=[{'primitives':[{'mode':0,'attributes':{'POSITION':p},'targets':[{'POSITION':delta}]}]}],animations=[{'samplers':[{'input':times,'output':aid,'interpolation':'CUBICSPLINE'}],'channels':[{'sampler':0,'target':{'node':0,'path':'weights'}}]}])
        snap=self.good(m.inspect_asset(encode(d),'gltf'))
        self.assertEqual(self.good(m.sample_animation(snap,0,1))[0]['weights'],(.5,))
        self.bad(m.sample_animation(snap,True,1),'E_REFERENCE')

    def scalar(self, op=None, other=False):
        d=source_doc()
        for s in d['signals']: s['domain']={}
        if op: d['mappings'][0]['rules'][0]['operator']=op
        if other:
            s=signal('other');s['domain']={};d['signals'].append(s)
            d['profiles'][0]['signal_ids'].append('other')
            d['mappings'][0]['rules']=[rule('sum',['input.wink','other'],'output.wink',op)]
        return self.good(compile_map(d))

    def evaluate(self,c,x,y=None):
        values={'input.wink':x}
        if y is not None:values['other']=y
        return m.evaluate_mapping(c,[{'timestamp':0,'values':values,'validity':dict.fromkeys(values,True)}])

    def test_scalar_large_identity_and_ordinary_cancellation(self):
        result=self.good(self.evaluate(self.scalar(),1.5e308))
        self.assertEqual(result.to_dict()['samples'][0]['values']['output.wink'],1.5e308)
        c=self.scalar({'id':'weighted_sum','weights':[1,-1]},True)
        self.assertEqual(self.good(self.evaluate(c,1.5e308,1.5e308)).to_dict()['samples'][0]['values']['output.wink'],0)

    def test_scalar_intermediate_overflow_and_underflow(self):
        c=self.scalar({'id':'affine','scale':2,'offset':-1.5e308})
        self.bad(self.evaluate(c,1.5e308),'E_NONFINITE')
        c=self.scalar({'id':'affine','scale':2**-800,'offset':1})
        self.bad(self.evaluate(c,2**-800),'E_NONFINITE')
        c=self.scalar({'id':'weighted_sum','weights':[2,2]},True)
        self.bad(self.evaluate(c,1e308,-1e308),'E_NONFINITE')


if __name__ == '__main__': unittest.main()
