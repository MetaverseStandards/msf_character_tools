# SPDX-License-Identifier: MIT
"""Pinned glTF core rules and hand-authored binary/analytic oracles for S-H2."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import msf_character_tools as m

ROOT = Path(__file__).resolve().parents[2]
assert Path(m.__file__).resolve().parent == ROOT / 'msf_character_tools'
IDENTITY = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
SIGNAL = {'id':'morph','value_type':'scalar','units':'1','domain':{'min':-2,'max':2},'calibration':'literal fixture'}


class Binary:
    """Independent tightly packed byte authoring; never imports SDK helpers."""
    def __init__(self):
        self.data=bytearray(); self.views=[]; self.accessors=[]
    def add(self, rows, kind='VEC3', ct=5126, normalized=False, bounds=False):
        rows=[(x,) if isinstance(x,(int,float)) else tuple(x) for x in rows]
        while len(self.data)%4: self.data.append(0)
        start=len(self.data); fmt={5120:'b',5121:'B',5122:'h',5123:'H',5125:'I',5126:'f'}[ct]
        for row in rows: self.data.extend(struct.pack('<'+fmt*len(row),*row))
        self.views=self.views+[{'buffer':0,'byteOffset':start,'byteLength':len(self.data)-start}]
        a={'bufferView':len(self.views)-1,'componentType':ct,'type':kind,'count':len(rows)}
        if normalized: a['normalized']=True
        if bounds:
            a['min']=[min(r[k] for r in rows) for k in range(len(rows[0]))]
            a['max']=[max(r[k] for r in rows) for k in range(len(rows[0]))]
        self.accessors=self.accessors+[a]; return len(self.accessors)-1
    def doc(self, **extra):
        return {'asset':{'version':'2.0'},'buffers':[{'byteLength':len(self.data),'uri':'data:application/octet-stream;base64,'+base64.b64encode(self.data).decode()}], 'bufferViews':self.views,'accessors':self.accessors,**extra}


def point(count=1):
    b=Binary(); p=b.add([(1.2,0,0)]*count,bounds=True)
    return b,b.doc(meshes=[{'primitives':[{'mode':0,'attributes':{'POSITION':p}}]}],nodes=[{'mesh':0}])


def refresh(b,d):
    d['buffers']=b.doc()['buffers']; d['bufferViews']=b.views; d['accessors']=b.accessors
    return d


def animated(path='weights', ct=5126, normalized=False, cubic=False, keys=2):
    b,d=point(); delta=b.add([(0,2,0)],bounds=True)
    d['meshes'][0]['primitives'][0]['targets']=[{'POSITION':delta}]
    ti=b.add([0,2][:keys],'SCALAR',bounds=True)
    one=127 if ct==5120 else 255 if ct==5121 else 32767 if ct==5122 else 65535 if ct==5123 else 1
    if path=='weights': values=[0,one][:keys]; kind='SCALAR'
    elif path=='rotation': values=[(0,0,0,one),(0,0,one,0)][:keys]; kind='VEC4'
    else: values=[(0,0,0),(2,0,0)][:keys]; kind='VEC3'
    if cubic:
        zero=0 if kind=='SCALAR' else (0,)*len(values[0])
        values=[item for v in values for item in (zero,v,zero)]
    out=b.add(values,kind,ct,normalized)
    d['animations']=[{'samplers':[{'input':ti,'output':out,'interpolation':'CUBICSPLINE' if cubic else 'LINEAR'}],'channels':[{'sampler':0,'target':{'node':0,'path':path}}]}]
    return b,refresh(b,d)


def skinned(ct=5126, weights=(1,0,0,0), js=(0,0,0,0), extra_ibm=False):
    b,d=point(); j=b.add([js],'VEC4',5123); w=b.add([weights],'VEC4',ct,ct!=5126)
    ibm=b.add([IDENTITY]*(2 if extra_ibm else 1),'MAT4')
    d['meshes'][0]['primitives'][0]['attributes'].update(JOINTS_0=j,WEIGHTS_0=w)
    d['nodes']=[{'mesh':0,'skin':0},{}, {'children':[0,1]}]
    d['skins']=[{'joints':[1],'inverseBindMatrices':ibm,'skeleton':2}]
    d['scenes']=[{'nodes':[2]}];d['scene']=0
    return b,refresh(b,d)


class CoreSemantics(unittest.TestCase):
    def good(self,r):
        self.assertTrue(r.ok,r.report.to_dict()); return r.value
    def inspect(self,d):
        return m.inspect_asset(json.dumps(d,allow_nan=False,separators=(',',':')).encode(),'gltf')
    def bad(self,d,code):
        r=self.inspect(d);self.assertFalse(r.ok,'Malformed available core was admitted');self.assertIsNone(r.value)
        self.assertIn(code,[x.code for x in r.report.diagnostics],r.report.to_dict())
    def positions(self,s,**kw):
        return self.good(m.evaluate_geometry(s,**kw)).to_dict()['instances'][0]['primitives']

    def test_all_topology_modes_positive_and_negative_cardinality(self):
        # Spec mode numbers are independently listed: points/lines/loop/strip/triangles/strip/fan.
        for mode,valid,invalid in [(0,1,0),(1,2,3),(2,2,1),(3,2,1),(4,3,4),(5,3,2),(6,3,2)]:
            for indexed in (False,True):
                with self.subTest(mode=mode,indexed=indexed):
                    b,d=point(max(valid,invalid,1));p=d['meshes'][0]['primitives'][0];p['mode']=mode
                    if indexed: p['indices']=b.add([0]*valid,'SCALAR',5123);refresh(b,d)
                    else: b,d=point(valid);d['meshes'][0]['primitives'][0]['mode']=mode
                    self.good(self.inspect(d))
                    if invalid==0:
                        d['accessors'][0]['count']=0;self.bad(d,'E_TYPE')
                    else:
                        b,d=point(max(invalid,1));p=d['meshes'][0]['primitives'][0];p['mode']=mode
                        if indexed: p['indices']=b.add([0]*invalid,'SCALAR',5123);refresh(b,d)
                        self.bad(d,'E_PRIMITIVE_COUNT')

    def test_reserved_indices_and_vertex_bounds(self):
        for ct,maximum in [(5121,255),(5123,65535),(5125,4294967295)]:
            with self.subTest(ct=ct):
                b,d=point(256 if ct==5121 else 1);p=d['meshes'][0]['primitives'][0]
                p['indices']=b.add([0],'SCALAR',ct);refresh(b,d);self.good(self.inspect(d))
                p['indices']=b.add([maximum],'SCALAR',ct);refresh(b,d);self.bad(d,'E_INDEX_BOUNDS')
        b,d=point();d['meshes'][0]['primitives'][0]['indices']=b.add([1],'SCALAR',5123);self.bad(refresh(b,d),'E_INDEX_BOUNDS')

    def test_attribute_component_shape_count_normalization(self):
        rows=[('POSITION','VEC3',5126,False,(1,0,0)),('NORMAL','VEC3',5126,False,(0,1,0)),('TANGENT','VEC4',5126,False,(1,0,0,-1)),('TEXCOORD_0','VEC2',5123,True,(0,65535)),('COLOR_0','VEC4',5121,True,(0,255,0,255)),('JOINTS_0','VEC4',5123,False,(0,0,0,0)),('WEIGHTS_0','VEC4',5121,True,(255,0,0,0))]
        for name,shape,ct,norm,row in rows:
            with self.subTest(name=name):
                b,d=point();p=d['meshes'][0]['primitives'][0];aid=b.add([row],shape,ct,norm,name=='POSITION');p['attributes'][name]=aid
                if name.startswith('JOINTS'): p['attributes']['WEIGHTS_0']=b.add([(1,0,0,0)],'VEC4')
                if name.startswith('WEIGHTS'): p['attributes']['JOINTS_0']=b.add([(0,0,0,0)],'VEC4',5123)
                p['attributes']['_COUNT_CONTROL']=0
                refresh(b,d);self.good(self.inspect(d))
                for badrows,badshape,badct,badnorm in [([0],'SCALAR',ct,norm),([row,row],shape,ct,norm),([tuple(0 for _ in row)],shape,5122,False)]:
                    bad=copy.deepcopy(d);bad['meshes'][0]['primitives'][0]['attributes'][name]=b.add(badrows,badshape,badct,badnorm,name=='POSITION');self.bad(refresh(b,bad),'E_GEOMETRY_TYPE')
        b,d=point();d['meshes'][0]['primitives'][0]['attributes']['NORMAL']=b.add([(0,1,0)],'VEC3',5123,True);self.bad(refresh(b,d),'E_GEOMETRY_TYPE')

    def test_tangent_handedness_and_color_range(self):
        for name,good,bad,shape,code in [('TANGENT',(1,0,0,-1),(1,0,0,0),'VEC4','E_TANGENT'),('COLOR_0',(0,.5,1),(0,-.1,1),'VEC3','E_COLOR')]:
            b,d=point();p=d['meshes'][0]['primitives'][0];p['attributes'][name]=b.add([good],shape);self.good(self.inspect(refresh(b,d)))
            p['attributes'][name]=b.add([bad],shape);self.bad(refresh(b,d),code)

    def test_indexed_syntax_contiguity_and_pairing(self):
        for suffix in ('01','-1','1.0','1000000000','x',''):
            b,d=point();d['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_'+suffix]=b.add([(0,0)],'VEC2');self.bad(refresh(b,d),'E_ATTRIBUTE_SEMANTIC')
        b,d=point();p=d['meshes'][0]['primitives'][0];t=b.add([(0,0)],'VEC2');p['attributes'].update(TEXCOORD_0=t,TEXCOORD_1=t);self.good(self.inspect(refresh(b,d)))
        p['attributes']['TEXCOORD_2']=p['attributes'].pop('TEXCOORD_1');self.bad(d,'E_ATTRIBUTE_SEMANTIC')
        b,d=point();d['meshes'][0]['primitives'][0]['attributes']['JOINTS_0']=b.add([(0,0,0,0)],'VEC4',5123);self.bad(refresh(b,d),'E_ATTRIBUTE_SEMANTIC')

    def test_duplicate_positive_influences_and_exact_raw_integer_sums(self):
        b,d=skinned();self.good(self.inspect(d));self.positions(self.good(self.inspect(d)))
        b,d=skinned(weights=(.5,.5,0,0));self.bad(d,'E_SKIN_WEIGHTS')
        for ct,total in [(5121,255),(5123,65535)]:
            b,d=skinned(ct,(total,0,0,0));s=self.good(self.inspect(d));self.positions(s)
            b,d=skinned(ct,(total-1,0,0,0));self.bad(d,'E_SKIN_WEIGHTS')
        b,d=skinned(weights=(-.1,1.1,0,0));self.bad(d,'E_SKIN_WEIGHTS')
        b,d=skinned(js=(1,0,0,0));self.bad(d,'E_JOINT_BOUNDS')

    def test_all_influence_sets_share_duplicate_and_sum_checks(self):
        b,d=skinned();p=d['meshes'][0]['primitives'][0];p['attributes']['JOINTS_1']=b.add([(0,0,0,0)],'VEC4',5123);p['attributes']['WEIGHTS_1']=b.add([(0,0,0,0)],'VEC4');refresh(b,d)
        s=self.good(self.inspect(d));self.assertEqual(self.positions(s),self.positions(self.good(self.inspect(skinned()[1]))))
        p['attributes']['WEIGHTS_1']=b.add([(.5,0,0,0)],'VEC4');self.bad(refresh(b,d),'E_SKIN_WEIGHTS')

    def test_position_bounds_mandatory_exact_rounding_and_enclosure_rejection(self):
        b,d=point();s=self.good(self.inspect(d));actual=self.good(m.decode_accessor(s,0))[0][0]
        self.assertEqual(actual,struct.unpack('<f',struct.pack('<f',1.2))[0])
        for field in ('min','max'):
            bad=copy.deepcopy(d);del bad['accessors'][0][field];self.bad(bad,'E_ACCESSOR_BOUNDS')
        bad=copy.deepcopy(d);bad['accessors'][0]['max'][0]=2;self.bad(bad,'E_ACCESSOR_DOMAIN')
        bad=copy.deepcopy(d);bad['accessors'][0]['max'][0]=1e100;self.bad(bad,'E_ACCESSOR_DOMAIN')

    def test_sparse_extrema_and_raw_normalized_integer_bounds(self):
        b,d=point(2);spix=b.add([1],'SCALAR',5121);spval=b.add([(2,0,0)])
        a=b.accessors[0];a['sparse']={'count':1,'indices':{'bufferView':b.accessors[spix]['bufferView'],'componentType':5121},'values':{'bufferView':b.accessors[spval]['bufferView']}};a['max']=[2,0,0]
        refresh(b,d);self.good(self.inspect(d));a['max']=[1.2,0,0];self.bad(d,'E_ACCESSOR_DOMAIN')
        b,d=point();aid=b.add([(255,0,0,255)],'VEC4',5121,True,True);d['meshes'][0]['primitives'][0]['attributes']['COLOR_0']=aid;self.good(self.inspect(refresh(b,d)))
        b.accessors[aid]['max']=[1,0,0,1];self.bad(d,'E_ACCESSOR_DOMAIN')

    def test_mixed_morphless_primitives_anywhere_bind_sample_evaluate(self):
        for order in ((False,True,False),(True,False,True)):
            b,d=animated();target=d['meshes'][0]['primitives'][0];plain={'mode':0,'attributes':{'POSITION':0}}
            d['meshes'][0]['primitives']=[copy.deepcopy(target if has else plain) for has in order]
            d['meshes'][0]['weights']=[.5];s=self.good(self.inspect(d))
            binding=self.good(m.morph_binding(s,SIGNAL,0,0));self.assertEqual(binding['ref']['locator'],'/nodes/0/weights/0')
            side=self.good(m.annotate_asset(s,{'bindings':[binding]}));bound=self.good(m.inspect_asset(s.original_bytes,'gltf',sidecar=side))
            self.assertEqual(self.good(m.sample_animation(bound,0,1))[0]['weights'],(.5,))
            for primitive,has in zip(self.positions(bound,animation_id=0,timestamp=1),order):
                self.assertEqual(primitive['positions'],[[struct.unpack('<f',struct.pack('<f',1.2))[0],1.0 if has else 0.0,0.0]])

    def test_morph_empty_base_semantic_count_and_common_count(self):
        b,d=animated();self.good(self.inspect(d))
        for change in ('empty','no_base','count','positive_mismatch','zero_array','bounds'):
            bad=copy.deepcopy(d);p=bad['meshes'][0]['primitives'][0];aid=p['targets'][0]['POSITION']
            if change=='empty': p['targets']=[{}]
            if change=='no_base': p['targets']=[{'NORMAL':aid}]
            if change=='count': p['targets'][0]['POSITION']=b.add([(0,2,0),(0,2,0)],bounds=True);refresh(b,bad)
            if change=='positive_mismatch': other=copy.deepcopy(p);other['targets']*=2;bad['meshes'][0]['primitives'].append(other)
            if change=='zero_array': p['targets']=[]
            if change=='bounds': del bad['accessors'][aid]['min']
            self.bad(bad,'E_ACCESSOR_BOUNDS' if change=='bounds' else 'E_MORPH')

    def test_extra_ibms_ordered_palette_and_affine_validation(self):
        b,d=skinned(extra_ibm=True);s=self.good(self.inspect(d));self.assertEqual(self.positions(s)[0]['positions'][0][0],struct.unpack('<f',struct.pack('<f',1.2))[0])
        # Extra row is not used by palette, but MUST still be valid affine data.
        a=d['accessors'][d['skins'][0]['inverseBindMatrices']];v=d['bufferViews'][a['bufferView']];struct.pack_into('<f',b.data,v['byteOffset']+64+12,.25);self.bad(refresh(b,d),'E_SKIN_TYPE')
        b,d=skinned();d['skins'][0]['joints']=[0,1];self.bad(d,'E_SKIN_TYPE')

    def test_skin_common_root_skeleton_and_each_referencing_scene(self):
        b,d=skinned();self.good(self.inspect(d))
        bad=copy.deepcopy(d);bad['nodes'][2]['children']=[0];bad['nodes'].append({});bad['skins'][0]['joints']=[1,3];del bad['skins'][0]['inverseBindMatrices'];self.bad(bad,'E_SKIN')
        bad=copy.deepcopy(d);bad['skins'][0]['skeleton']=0;self.bad(bad,'E_SKIN')
        bad=copy.deepcopy(d);bad['nodes'][2]['children']=[1];bad['scenes']=[{'nodes':[0]},{'nodes':[2]}];self.bad(bad,'E_SKIN')
        bad=copy.deepcopy(d);bad['scenes'].append({'nodes':[2]});self.good(self.inspect(bad))

    def test_matrix_node_weights_positive_trs_negative_and_no_node_ignored(self):
        b,d=animated();d['nodes'][0]['matrix']=IDENTITY;s=self.good(self.inspect(d));self.assertEqual(self.good(m.sample_animation(s,0,1))[0]['weights'],(.5,));self.positions(s,animation_id=0,timestamp=1)
        for path in ('translation','rotation','scale'):
            b,bad=animated(path);bad['nodes'][0]['matrix']=IDENTITY;self.bad(bad,'E_ANIMATION')
        b,d=animated();del d['animations'][0]['channels'][0]['target']['node'];s=self.good(self.inspect(d));self.assertEqual(dict(self.good(m.sample_animation(s,0,1))),{});self.positions(s,animation_id=0)

    def test_unknown_channel_does_not_mask_available_malformed_core(self):
        b,d=animated();d['extensionsUsed']=['EXT_unknown'];anim=d['animations'][0];anim['channels'].append({'sampler':0,'target':{'path':'pointer','extensions':{'EXT_unknown':{'pointer':'opaque'}}}})
        self.good(self.inspect(d));anim['samplers'][0]['output']=b.add([(0,0,0),(1,0,0)]);self.bad(refresh(b,d),'E_ANIMATION_TYPE')
        b,d=animated();d['animations'][0]['samplers'].append(copy.deepcopy(d['animations'][0]['samplers'][0]));d['animations'][0]['channels'].insert(0,{'sampler':1,'target':{'path':'pointer','extensions':{'EXT_unknown':{}}}});d['extensionsUsed']=['EXT_unknown'];d['animations'][0]['samplers'][0]['output']=b.add([(0,0,0),(1,0,0)]);self.bad(refresh(b,d),'E_ANIMATION_TYPE')

    def test_normalized_integer_rotation_and_weights_keys(self):
        for ct in (5120,5121,5122,5123):
            for path in ('rotation','weights'):
                with self.subTest(ct=ct,path=path):
                    b,d=animated(path,ct,True);s=self.good(self.inspect(d));v=self.good(m.sample_animation(s,0,1))[0][path]
                    if path=='weights': self.assertEqual(v,(.5,));self.positions(s,animation_id=0,timestamp=1)
                    else: self.assertAlmostEqual(v[2],2**-.5);self.assertAlmostEqual(v[3],2**-.5)
                    bad=copy.deepcopy(d);bad['accessors'][d['animations'][0]['samplers'][0]['output']]['normalized']=False;self.bad(bad,'E_ANIMATION_TYPE')
        b,d=animated('translation',5123,True);self.bad(d,'E_ANIMATION_TYPE')

    def test_cubic_requires_two_keys_and_preserves_normalized_tangent_roles(self):
        b,d=animated(cubic=True);s=self.good(self.inspect(d));self.assertEqual(self.good(m.sample_animation(s,0,1))[0]['weights'],(.5,))
        b,d=animated(cubic=True,keys=1);self.bad(d,'E_ANIMATION_TYPE')
        b,d=animated('rotation',5122,True,cubic=True);s=self.good(self.inspect(d));q=self.good(m.sample_animation(s,0,1))[0]['rotation'];self.assertAlmostEqual(q[2],2**-.5);self.assertAlmostEqual(q[3],2**-.5)

    def test_integral_json_syntax_normalized_view_preserves_source_and_unknowns(self):
        b,d=animated();d['extras']={'count':1.0,'opaque':1.5};raw=json.dumps(d,separators=(',',':')).encode()
        for old,new in [(b'"count":1',b'"count":1.0'),(b'"componentType":5126',b'"componentType":5.126e3'),(b'"node":0',b'"node":0e0'),(b'"mesh":0',b'"mesh":0.0'),(b'"buffer":0',b'"buffer":0.0'),(b'"sampler":0',b'"sampler":0.0')]: raw=raw.replace(old,new)
        # The extras count replacement deliberately remains a floating JSON value.
        raw=raw.replace(b'1.0.0',b'1.0')
        s=self.good(m.inspect_asset(raw,'gltf'));self.assertEqual(s.original_bytes,raw);self.assertEqual(s.sha256,hashlib.sha256(raw).hexdigest());self.assertIs(type(s.document['accessors'][0]['componentType']),int);self.assertIs(type(s.document['extras']['count']),float)
        self.assertEqual(self.good(m.sample_animation(s,0,1))[0]['weights'],(.5,));self.good(m.morph_binding(s,SIGNAL,0,0));self.positions(s,animation_id=0,timestamp=1);s.to_dict()
        for lexical in (b'1.5',b'true',b'1.00000000000000000000000000001'):
            bad=json.dumps(d,separators=(',',':')).encode().replace(b'"count":1',b'"count":'+lexical,1);r=m.inspect_asset(bad,'gltf');self.assertFalse(r.ok);self.assertIn('E_TYPE',[x.code for x in r.report.diagnostics])

    def test_unavailable_bytes_structural_checks_and_explicit_warning(self):
        b,d=point();d['buffers'][0]['uri']='missing.bin';s=self.good(self.inspect(d));self.assertIn('W_RESOURCE_UNCONSUMED',[x.code for x in self.inspect(d).report.diagnostics]);r=m.evaluate_geometry(s);self.assertFalse(r.ok);self.assertIn('E_RESOURCE_UNAVAILABLE',[x.code for x in r.report.diagnostics])
        del d['accessors'][0]['min'];self.bad(d,'E_ACCESSOR_BOUNDS')

    def test_native_fixture_position_bounds_independently_required(self):
        raw=(ROOT/'tests/public/fixtures/native-agreement.gltf').read_bytes();d=json.loads(raw);aid=d['meshes'][0]['primitives'][0]['attributes']['POSITION'];a=d['accessors'][aid]
        self.assertEqual(a.get('min'),[1,0,0]);self.assertEqual(a.get('max'),[1,0,0]);self.good(m.inspect_asset(raw,'gltf'))


class FixtureGeneration(unittest.TestCase):
    def test_generator_reproduces_checked_in_fixtures(self):
        import make_fixtures
        with tempfile.TemporaryDirectory() as td, patch.object(make_fixtures,'ROOT',Path(td)):
            make_fixtures.combined();make_fixtures.eight_weighted();make_fixtures.native_agreement()
            for path in sorted(Path(td).iterdir()):
                with self.subTest(fixture=path.name):
                    self.assertEqual(path.read_bytes(),(ROOT/'tests/public/fixtures'/path.name).read_bytes())

if __name__=='__main__': unittest.main()
