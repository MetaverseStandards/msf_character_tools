# SPDX-License-Identifier: MIT
"""Literal analytical oracles for the complete pure numerical CONTRACT_03."""
import base64
import json
from pathlib import Path
import struct
import unittest

import msf_character_tools as m
from test_core_semantic_fixes import AssetBytes, encode, morph_asset
from test_reference import source_doc, compile_map, rule, signal

ROOT = Path(__file__).resolve().parents[2]
assert Path(m.__file__).resolve().parent == ROOT / 'msf_character_tools'
ROWS = ((2,0,0,3),(0,-3,0,4),(0,0,4,5),(0,0,0,1))
COLUMNS = (2,0,0,0, 0,-3,0,0, 0,0,4,0, 3,4,5,1)
PARENT = (0,1,0,0, -1,0,0,0, 0,0,1,0, 10,20,0,1)
CHILD = (0,2,0,0, -3,0,0,0, 0,0,4,0, 4,28,12,1)
LOCAL = (2,0,0,0, 0,3,0,0, 0,0,4,0, 8,6,12,1)


def node_asset(node):
    b = AssetBytes()
    p = b.rows([(1,2,3)], 'VEC3', bounds=True)
    return b.document(nodes=[dict(node, mesh=0)], meshes=[{'primitives': [
        {'mode':0,'attributes':{'POSITION':p}}]}])


class NumericChecks(unittest.TestCase):
    def good(self, result):
        self.assertTrue(result.ok, result.report.to_dict())
        return result.value

    def bad(self, result, code):
        self.assertFalse(result.ok, result)
        self.assertIsNone(result.value)
        self.assertIn(code, [d.code for d in result.report.diagnostics])

    def test_reparent_noncommuting_hand_math_and_original_affine(self):
        self.assertEqual(self.good(m.reparent_local(CHILD,PARENT)),LOCAL)
        p = list(COLUMNS); p[3] = .5
        self.bad(m.reparent_local(p,p),'E_TRANSFORM')

    def test_authored_matrix_decomposition_positive_and_negative(self):
        for mat,code in (((1,0,0,0,.25,1,0,0,0,0,1,0,0,0,0,1),'E_SHEAR'),
                         ((0,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1),'E_SINGULAR'),
                         ((1,0,0,.5,0,1,0,0,0,0,1,0,0,0,0,1),'E_TRANSFORM')):
            self.bad(m.inspect_asset(encode(node_asset({'matrix':mat})),'gltf'),code)
        snapshot=self.good(m.inspect_asset(encode(node_asset({'matrix':COLUMNS})),'gltf'))
        self.assertEqual(self.good(m.evaluate_geometry(snapshot)).to_dict()['instances'][0]['primitives'][0]['positions'],[[1,2,3]])

    def test_override_matrix_and_authored_quaternion(self):
        snap=self.good(m.inspect_asset(encode(node_asset({'matrix':COLUMNS})),'gltf'))
        shear=list(COLUMNS);shear[4]=.25
        self.bad(m.evaluate_geometry(snap,node_transforms={0:{'matrix':shear}}),'E_SHEAR')
        snap=self.good(m.inspect_asset(encode(node_asset({})),'gltf'))
        self.bad(m.evaluate_geometry(snap,node_transforms={0:{'rotation':(0,0,0,2)}}),'E_QUATERNION')
        self.bad(m.inspect_asset(encode(node_asset({'rotation':(1e200,0,0,1e200)})),'gltf'),'E_QUATERNION')

    def test_khronos_simple_skin_keys_are_accepted_and_normalized(self):
        # SimpleSkin (CC0) authors 0.707/0.383 keys whose length is up to 2.3e-4 off one.
        text=(ROOT/'tests'/'public'/'fixtures'/'simple-skin.gltf').read_text()
        snap=self.good(m.inspect_asset(text.encode(),'gltf'))
        quarter=self.good(m.evaluate_geometry(snap,timestamp=1.0,animation_id=0)).to_dict()['instances'][0]['primitives'][0]['positions']
        # The top two vertices follow the second joint, a quarter turn about Z around (0, 1, 0).
        for actual,wanted in zip(quarter[8:],([-1,0.5,0],[-1,1.5,0])):
            for a,w in zip(actual,wanted):self.assertAlmostEqual(a,w,places=6)
        doc=json.loads(text)
        uri=doc['buffers'][3]['uri']
        head,data=uri.split(',',1)
        raw=bytearray(base64.b64decode(data))
        struct.pack_into('<4f',raw,48+16*2,0,0,0.707*1.02,0.707*1.02)
        doc['buffers'][3]['uri']=head+','+base64.b64encode(bytes(raw)).decode()
        self.bad(m.inspect_asset(json.dumps(doc).encode(),'gltf'),'E_QUATERNION')

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
