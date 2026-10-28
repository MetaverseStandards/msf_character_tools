# SPDX-License-Identifier: MIT
"""Additional independent core negatives discovered while reading callers."""
import unittest
import msf_character_tools as m
from test_core_semantics import Binary, point, animated, refresh


class SemanticEdges(unittest.TestCase):
    def good(self,r):
        self.assertTrue(r.ok,r.report.to_dict());return r.value
    def bad(self,d,code):
        r=m.inspect_asset(__import__('json').dumps(d).encode(),'gltf')
        self.assertFalse(r.ok);self.assertIn(code,[x.code for x in r.report.diagnostics])

    def test_cubic_cardinality_is_sampler_rule_even_for_ignored_channel(self):
        b,d=animated(cubic=True);del d['animations'][0]['channels'][0]['target']['node'];self.good(m.inspect_asset(__import__('json').dumps(d).encode(),'gltf'))
        b,d=animated(cubic=True,keys=1);del d['animations'][0]['channels'][0]['target']['node'];self.bad(d,'E_ANIMATION_TYPE')

    def test_available_bad_quaternion_is_not_masked_by_unavailable_time(self):
        b,d=animated('rotation');a=d['accessors'][d['animations'][0]['samplers'][0]['input']];v=d['bufferViews'][a['bufferView']]
        d['buffers'].append({'byteLength':v['byteLength'],'uri':'unavailable_times.bin'});v['buffer']=1;v['byteOffset']=0
        self.good(m.inspect_asset(__import__('json').dumps(d).encode(),'gltf'))
        d['animations'][0]['samplers'][0]['output']=b.add([(0,0,0,2),(0,0,0,2)],'VEC4');buffers=d['buffers'];refresh(b,d);d['buffers'].append(buffers[1]);self.bad(d,'E_QUATERNION')

    def test_available_mixed_weights_error_is_not_masked_by_unavailable_joints(self):
        b,d=point();p=d['meshes'][0]['primitives'][0];j=b.add([(0,0,0,0)],'VEC4',5123);w=b.add([(1,0,0,0)],'VEC4');p['attributes'].update(JOINTS_0=j,WEIGHTS_0=w);refresh(b,d)
        a=d['accessors'][j];v=d['bufferViews'][a['bufferView']];d['buffers'].append({'byteLength':v['byteLength'],'uri':'unavailable_joints.bin'});v['buffer']=1;v['byteOffset']=0
        self.good(m.inspect_asset(__import__('json').dumps(d).encode(),'gltf'))
        p['attributes']['WEIGHTS_0']=b.add([(-.5,1.5,0,0)],'VEC4');buffers=d['buffers'];refresh(b,d);d['buffers'].append(buffers[1]);self.bad(d,'E_SKIN_WEIGHTS')

if __name__=='__main__': unittest.main()
