# SPDX-License-Identifier: MIT
"""Literal numerical and original-value oracles for the compiled pilot."""
import gc
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import unittest

module_dir = Path(sys.argv.pop(1)).resolve(strict=True)
source_root = Path(sys.argv.pop(1)).resolve(strict=True)
baseline = '--baseline' in sys.argv
if baseline:
    sys.argv.remove('--baseline')
sys.path.insert(0, str(module_dir))
sys.path.insert(0, str(source_root))
import _msf_native as n
import msf_tools
assert Path(n.__file__).resolve().parent == module_dir, n.__file__
assert Path(msf_tools.__file__).resolve().parent == source_root / 'msf_tools'
print(json.dumps({'executable':sys.executable,'version':sys.version,
                  'platform':platform.platform(),'machine':platform.machine(),
                  'native_origin':n.__file__,'native_sha256':hashlib.sha256(Path(n.__file__).read_bytes()).hexdigest(),
                  'pure_origin':msf_tools.__file__},sort_keys=True),flush=True)

I = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
ROWS = [2,0,0,3, 0,-3,0,4, 0,0,4,5, 0,0,0,1]
COLUMN = [2,0,0,0, 0,-3,0,0, 0,0,4,0, 3,4,5,1]
PARENT = [0,-1,0,10, 1,0,0,20, 0,0,1,0, 0,0,0,1]
CHILD = [0,-3,0,4, 2,0,0,28, 0,0,4,12, 0,0,0,1]
LOCAL = [2,0,0,8, 0,3,0,6, 0,0,4,12, 0,0,0,1]
TINY = 2.0**-800
SUB = 2.0**-1074


def diag(x,y=None,z=None):
    return [x,0,0,0, 0,x if y is None else y,0,0,
            0,0,x if z is None else z,0, 0,0,0,1]


def program(operation=None, inputs=(0,), weights=(), scale=1, offset=0, slots=2, output=None):
    d = n.Domain()
    rule = n.Instruction()
    rule.inputs = list(inputs); rule.output = slots-1 if output is None else output
    rule.operation = n.Operator.identity if operation is None else operation
    rule.scale = scale; rule.offset = offset; rule.weights = list(weights)
    p = n.ScalarProgram(); p.domains = [d]*slots; p.instructions = [rule]
    return p


def skin(point=(2,3,4), worlds=None, ibms=None, weights=(1,0,0,0), joints=(0,0,0,0), mesh=I):
    return n.skin_positions([list(point)], [list(joints)], [list(weights)], mesh,
                            [I] if worlds is None else worlds, [I] if ibms is None else ibms)


class Strict(unittest.TestCase):
    def refuses(self, code, call):
        try:
            call()
        except ValueError as exc:
            self.assertTrue(str(exc).startswith(code+': '), str(exc))
        except Exception as exc:
            self.fail(f'Expected ValueError {code}, got {type(exc).__name__}: {exc}')
        else:
            self.fail(f'Expected ValueError {code}')

    def succeeds(self, call):
        try:
            return call()
        except ValueError as exc:
            self.fail(f'Unexpected kernel refusal: {exc}')

    def near(self, actual, expected):
        self.assertEqual(len(actual),len(expected))
        for x,y in zip(actual,expected):
            self.assertLessEqual(abs(x-y),8*2**-52*max(1,abs(y)))

    def test_numeric_bool_arrays_and_coefficients(self):
        calls = [lambda:n.multiply([True]+I[1:],I),lambda:n.inverse([True]+I[1:]),
                 lambda:n.transform_point(I,[False,0,0]),
                 lambda:n.compose_trs([False,0,0],[0,0,0,1],[1,1,1]),
                 lambda:n.compose_trs([0,0,0],[0,0,False,1],[1,1,1]),
                 lambda:n.compose_trs([0,0,0],[0,0,0,1],[True,1,1]),
                 lambda:n.reparent_local([True]+I[1:],I),
                 lambda:n.slerp([0,0,0,1],[0,0,0,1],True),
                 lambda:n.hermite([True],[0],[0],[0],.5,1),
                 lambda:n.hermite([0],[True],[0],[0],.5,1),
                 lambda:n.hermite([0],[0],[True],[0],.5,1),
                 lambda:n.hermite([0],[0],[0],[True],.5,1),
                 lambda:n.hermite([0],[0],[0],[0],True,1),
                 lambda:n.hermite([0],[0],[0],[0],.5,True),
                 lambda:n.morph_positions([[True,0,0]],[],[]),
                 lambda:n.morph_positions([[0,0,0]],[[[True,0,0]]],[0]),
                 lambda:n.morph_positions([[0,0,0]],[[[0,0,0]]],[True]),
                 lambda:skin(point=(True,0,0)),lambda:skin(weights=(True,0,0,0)),
                 lambda:n.evaluate_scalars(program(),[True,0],[True,False])]
        for k,call in enumerate(calls):
            with self.subTest(case=k): self.refuses('type',call)

    def test_numeric_types_and_nonfinite_admission(self):
        class Floatable:
            def __float__(self):return 1.
        class FloatSubclass(float):pass
        class IntSubclass(int):pass
        for v in ('1',None,Floatable(),FloatSubclass(1),IntSubclass(1)):
            with self.subTest(value=repr(v)):
                self.refuses('type',lambda:n.multiply([v]+I[1:],I))
        for v in (10**400, math.nan, math.inf, -math.inf):
            calls=[lambda:n.multiply([v]+I[1:],I),lambda:n.slerp([0,0,0,1],[0,0,v,1],0),
                   lambda:n.hermite([0],[0],[0],[0],.5,v),
                   lambda:n.morph_positions([[0,0,0]],[[[0,0,0]]],[v]),
                   lambda:skin(worlds=[I,[v]+I[1:]],ibms=[I,I]),
                   lambda:n.evaluate_scalars(program(),[.25,v],[True,False])]
            for k,call in enumerate(calls):
                with self.subTest(value=repr(v),case=k):self.refuses('nonfinite',call)

    def test_strict_mutable_setters_and_atomic_failure(self):
        for cls,field,good in ((n.Domain,'minimum',0),(n.Domain,'maximum',1),
                              (n.Instruction,'scale',.5),(n.Instruction,'offset',.25)):
            obj=cls();setattr(obj,field,good)
            for bad,code in ((True,'type'),('1','type'),(10**400,'nonfinite'),(math.nan,'nonfinite'),(math.inf,'nonfinite')):
                with self.subTest(cls=cls.__name__,field=field,bad=repr(bad)):
                    self.refuses(code,lambda:setattr(obj,field,bad));self.assertEqual(getattr(obj,field),good)
        r=n.Instruction();r.weights=[.5,.5]
        for bad,code in (([True,.5],'type'),([math.inf,.5],'nonfinite'),([10**400],'nonfinite'),({0:.5},'shape')):
            with self.subTest(weights=repr(bad)):
                self.refuses(code,lambda:setattr(r,'weights',bad));self.assertEqual(r.weights,[.5,.5])
        for field,good in (('inputs',[0]),('output',1)):
            setattr(r,field,good)
            for bad in (True,1.,-1,10**400,'0'):
                v=[bad] if field=='inputs' else bad
                with self.subTest(field=field,bad=repr(bad)):
                    self.refuses('binding',lambda:setattr(r,field,v));self.assertEqual(getattr(r,field),good)
        self.refuses('operator',lambda:setattr(r,'operation',1))
        self.assertEqual(r.operation,n.Operator.identity)
        p=program()
        self.refuses('type',lambda:setattr(p,'domains',[n.Domain(),True]))
        self.refuses('type',lambda:setattr(p,'instructions',[r,True]))
        self.refuses('shape',lambda:setattr(p,'domains',iter([n.Domain()])))
        self.assertEqual(n.evaluate_scalars(p,[.25,0],[True,False]),[.25,.25])

    def test_exact_validity_and_quaternion_mode(self):
        for bad in (0,1,None,'true',[],1.):
            for slot in (0,1):
                validity=[True,False];validity[slot]=bad
                with self.subTest(validity=repr(bad),slot=slot):
                    self.refuses('type',lambda:n.evaluate_scalars(program(),[.25,0],validity))
            with self.subTest(mode=repr(bad)):
                self.refuses('type',lambda:n.hermite([0],[0],[0],[0],.5,1,bad))

    def test_shapes_and_index_types(self):
        for m in (I[:-1],I+[0],[I]*4,iter(I),{i:v for i,v in enumerate(I)}):
            with self.subTest(matrix=repr(m)):self.refuses('shape',lambda:n.inverse(m))
        calls=[lambda:n.transform_point(I,[0,0]),lambda:n.compose_trs([0,0,0],[0,0,1],[1,1,1]),
               lambda:n.hermite([],[],[],[],.5,1),lambda:n.hermite([0],[0,1],[0],[0],.5,1),
               lambda:n.hermite([0],[0],[0],[0],.5,1,True),
               lambda:n.morph_positions([[0,0]],[],[]),lambda:n.morph_positions([[0,0,0]],[[]],[1]),
               lambda:n.morph_positions([[0,0,0]],[],[1]),
               lambda:n.skin_positions([[0,0,0]],[],[],I,[I],[I]),
               lambda:n.skin_positions([[0,0,0]],[[0]*3],[[1,0,0,0]],I,[I],[I]),
               lambda:n.skin_positions([[0,0,0]],[[0]*4],[[1,0,0]],I,[I],[I]),
               lambda:skin(worlds=[I,I],ibms=[I]),lambda:n.evaluate_scalars(program(),[0],[True])]
        for k,call in enumerate(calls):
            with self.subTest(case=k):self.refuses('shape',call)
        for bad in (True,0.,-1,10**400,'0'):
            with self.subTest(index=repr(bad)):self.refuses('binding',lambda:skin(joints=(0,bad,0,0)))
        self.refuses('influence',lambda:skin(joints=(0,1,0,0)))

    def test_full_affine_origin_and_original_cancellation(self):
        for slot,value in ((12,.5),(13,.5),(14,.5),(15,2)):
            bad=I.copy();bad[slot]=value
            with self.subTest(bottom_slot=slot):
                self.refuses('nonaffine',lambda:n.transform_point(bad,[0,0,0]))
                self.refuses('nonaffine',lambda:n.reparent_local(bad,bad))
                self.refuses('nonaffine',lambda:skin(mesh=bad,worlds=[bad],ibms=[I]))
        p=I.copy();p[12]=.5;c=I.copy();c[12]=-.5
        self.refuses('nonaffine',lambda:skin(worlds=[p],ibms=[c]))
        self.assertEqual(n.multiply(p,c),I)  # Generic arithmetic is not affine admission.

    def test_unused_skin_matrices_and_influences_are_validated(self):
        for kind in ('world','bind'):
            for v,code in ((.5,'nonaffine'),(math.inf,'nonfinite')):
                bad=I.copy();bad[12]=v
                with self.subTest(kind=kind,value=v):
                    self.refuses(code,lambda:skin(worlds=[I,bad if kind=='world' else I],ibms=[I,bad if kind=='bind' else I]))
        self.refuses('influence',lambda:skin(weights=(1,-.1,0,.1)))
        self.refuses('weights',lambda:skin(weights=(.9,0,0,0)))
        self.refuses('nonfinite',lambda:skin(weights=(1,math.nan,0,0)))

    def test_infinite_and_identical_axis_norms(self):
        for size,code in ((1.5e308,'nonfinite'),(1e200,'shear')):
            bad=[size,size,0,0, size,size,0,0, 0,0,1,0, 0,0,0,1]
            with self.subTest(size=size):self.refuses(code,lambda:n.reparent_local(I,bad))
        self.refuses('nonfinite',lambda:n.slerp([1.5e308,1.5e308,0,0],[0,0,0,1],0))

    def test_reflection_anisotropic_norms_and_inverse(self):
        for d in (diag(-2,3,4),diag(1e200),diag(1e-200),diag(1e-200,1e200,1)):
            with self.subTest(matrix=d):self.near(n.reparent_local(I,d),d)
        self.near(n.inverse(diag(1e-200,1e200,1)),diag(1e200,1e-200,1))
        self.assertEqual(n.inverse(diag(2.0**-600,2.0**600,1)),diag(2.0**600,2.0**-600,1))
        zero=diag(0,2,3)
        self.assertEqual(n.compose_trs([0,0,0],[0,0,0,2],[0,2,3]),zero)
        self.refuses('singular',lambda:n.inverse(zero))
        self.refuses('singular',lambda:n.reparent_local(I,zero))
        shear=I.copy();shear[1]=.25
        self.refuses('shear',lambda:n.reparent_local(I,shear))

    def test_role_tolerances(self):
        good=I.copy();good[12]=.5e-10
        bad=I.copy();bad[12]=2e-10
        self.assertEqual(n.transform_point(good,[0,0,0]),[0,0,0])
        self.refuses('nonaffine',lambda:n.transform_point(bad,[0,0,0]))
        shear=I.copy();shear[1]=2e-10
        self.refuses('shear',lambda:n.reparent_local(I,shear))
        self.near(skin(weights=(1+5e-7,0,0,0))[0],[2*(1+5e-7),3*(1+5e-7),4*(1+5e-7)])
        self.refuses('weights',lambda:skin(weights=(1+2e-6,0,0,0)))

    def test_literal_storage_reparent_and_product_order(self):
        self.assertEqual(n.transform_point(ROWS,[1,2,3]),[5,-2,17])
        self.near(n.transform_point(n.inverse(ROWS),[5,-2,17]),[1,2,3])
        self.assertEqual(n.reparent_local(PARENT,CHILD),LOCAL)
        self.assertEqual(n.multiply(PARENT,LOCAL),CHILD)
        self.assertNotEqual(n.multiply(LOCAL,PARENT),CHILD)
        expected=[.5,0,0,4,0,1/3,0,3,0,0,.25,3,0,0,0,1]
        self.near(n.reparent_local(diag(2,3,4),[1,0,0,8,0,1,0,9,0,0,1,12,0,0,0,1]),expected)
        self.near(n.transform_point(expected,[2,3,4]),[5,4,4])

    def test_named_storage_bridge(self):
        self.assertEqual(n.from_gltf_column_major(COLUMN),ROWS)
        self.assertEqual(n.to_gltf_column_major(ROWS),COLUMN)
        for fn in (n.from_gltf_column_major,n.to_gltf_column_major):
            self.refuses('type',lambda:fn([True]+I[1:]))
            self.refuses('shape',lambda:fn(I[:-1]))
            self.refuses('nonfinite',lambda:fn([math.inf]+I[1:]))
        c=COLUMN.copy();out=n.from_gltf_column_major(c);c[0]=99
        self.assertEqual(out,ROWS)

    def test_matrix_and_point_intermediate_representability(self):
        self.assertEqual(n.multiply(diag(1.5e308),I),diag(1.5e308))
        self.assertEqual(n.transform_point(diag(1.5e308),[1,0,0]),[1.5e308,0,0])
        self.assertEqual(n.multiply(diag(2**-1022),diag(.5)),diag(2**-1023))
        self.refuses('nonfinite',lambda:n.multiply(diag(1.5e308),diag(2)))
        self.refuses('nonfinite',lambda:n.multiply(diag(TINY),diag(TINY)))
        cancel=I.copy();cancel[:4]=[1.5e308,-1.5e308,0,0]
        self.refuses('nonfinite',lambda:n.transform_point(cancel,[2,2,0]))
        self.refuses('nonfinite',lambda:n.transform_point(diag(TINY),[TINY,0,0]))
        self.refuses('nonfinite',lambda:n.inverse(diag(SUB)))
        self.refuses('nonfinite',lambda:n.compose_trs([0,0,0],[TINY,0,0,1],[1,1,1]))

    def test_literal_quaternion_normalization_and_endpoints(self):
        self.assertEqual(n.slerp([0,0,0,2],[0,0,0,-3],.5),[0,0,0,1])
        self.near(n.slerp([1e200,0,0,1e200],[0,0,0,1],0),[math.sqrt(.5),0,0,math.sqrt(.5)])
        self.near(n.slerp([0,0,0,1],[0,0,1,0],.5),[0,0,math.sqrt(.5),math.sqrt(.5)])
        a=[TINY,0,0,1];b=[0,TINY,0,1]
        self.assertEqual(n.slerp(a,b,0),a)
        self.assertEqual(n.slerp(a,[-x for x in b],1),b)
        tie=[TINY,0,0,1];other=[TINY,1,0,0]
        self.assertEqual(n.slerp(tie,other,1),other)
        self.refuses('nonfinite',lambda:n.slerp(tie,other,.5))
        self.refuses('quaternion',lambda:n.slerp([0,0,0,1],[0,0,0,0],0))
        for t in (-.01,1.01):self.refuses('fraction',lambda:n.slerp(a,b,t))

    def test_hermite_literals_and_inactive_zero_tangents(self):
        self.assertEqual(n.hermite([0],[2],[0],[0],.5,2),[.5])
        self.assertEqual(n.hermite([1],[0],[1],[0],.5,SUB),[1])
        self.assertEqual(n.hermite([1.5e308],[0],[-1.5e308],[0],0,1),[1.5e308])
        self.assertEqual(n.hermite([1.5e308],[0],[-1.5e308],[0],1,1),[-1.5e308])
        self.near(n.hermite([0,0,0,1],[0,0,2,0],[0,0,1,0],[0,0,0,0],.5,2,True),[0,0,2/math.sqrt(5),1/math.sqrt(5)])
        self.refuses('curve',lambda:n.hermite([0],[0],[0],[0],.5,0))
        self.refuses('fraction',lambda:n.hermite([0],[0],[0],[0],1.1,1))
        self.refuses('nonfinite',lambda:n.hermite([1],[math.inf],[1],[0],0,1))

    def test_hermite_intermediate_overflow_and_underflow(self):
        self.refuses('nonfinite',lambda:n.hermite([0],[2**1023],[0],[2**1023],.5,16))
        self.refuses('nonfinite',lambda:n.hermite([0],[TINY],[0],[0],.5,TINY))
        self.refuses('nonfinite',lambda:n.hermite([0],[0],[0],[0],TINY,1))

    def test_literal_signed_morph_and_representability(self):
        self.assertEqual(n.morph_positions([[2,0,0]],[[[0,4,0]]],[-2]),[[2,-8,0]])
        self.assertEqual(n.morph_positions([[0,0,0]],[[[1,0,0]]],[1.5e308]),[[1.5e308,0,0]])
        self.assertEqual(n.morph_positions([[2,3,4]],[[[1.5e308,0,0]]],[0]),[[2,3,4]])
        self.refuses('nonfinite',lambda:n.morph_positions([[0,0,0]],[[[2,0,0]]],[1.5e308]))
        self.refuses('nonfinite',lambda:n.morph_positions([[0,0,0]],[[[TINY,0,0]]],[TINY]))
        self.refuses('nonfinite',lambda:n.morph_positions([[2,3,4]],[[[math.nan,0,0]]],[0]))
        self.refuses('nonfinite',lambda:n.morph_positions([[0,0,0]],[[[2,0,0]],[[-2,0,0]]],[1.5e308,1.5e308]))

    def test_literal_skin_and_singular_weighted_blend(self):
        mesh=[1,0,0,1,0,1,0,0,0,0,1,0,0,0,0,1]
        rz=[0,-1,0,0,1,0,0,0,0,0,1,0,0,0,0,1]
        jt=[1,0,0,5,0,1,0,0,0,0,1,0,0,0,0,1]
        self.assertEqual(skin(point=(2,4,0),worlds=[rz,jt],ibms=[I,I],weights=(.25,.75,0,0),joints=(0,1,0,0),mesh=mesh),[[3.25,3.5,0]])
        self.assertEqual(skin(worlds=[I,diag(-1,1,1)],ibms=[I,I],weights=(.5,.5,0,0),joints=(0,1,0,0)),[[0,3,4]])
        shear=I.copy();shear[1]=.25
        self.assertEqual(skin(worlds=[shear]),[[2.75,3,4]])

    def test_inactive_skin_arithmetic_and_active_overflow(self):
        for bind in (diag(2),I):
            with self.subTest(inactive_bind=bind):
                self.assertEqual(self.succeeds(lambda:skin(worlds=[I,diag(1.5e308)],ibms=[I,bind],joints=(0,1,0,0))),[[2,3,4]])
        self.refuses('nonfinite',lambda:skin(worlds=[diag(1.5e308)],ibms=[diag(2)]))
        self.refuses('nonfinite',lambda:skin(worlds=[diag(TINY)],point=(TINY,0,0)))
        self.refuses('nonfinite',lambda:skin(point=(SUB,0,0),weights=(.5,.5,0,0)))
        worlds=[diag(1.5e308),diag(-1.5e308)]
        self.refuses('nonfinite',lambda:skin(point=(2,0,0),worlds=worlds,ibms=[I,I],joints=(0,1,0,0),weights=(.5,.5,0,0)))

    def test_literal_scalar_outputs_and_checked_arithmetic(self):
        self.assertEqual(n.evaluate_scalars(program(),[1.5e308,0],[True,False]),[1.5e308,1.5e308])
        p=program(n.Operator.affine,scale=.5,offset=.5)
        self.assertEqual(n.evaluate_scalars(p,[0,0],[True,False]),[0,.5])
        self.assertEqual(n.evaluate_scalars(p,[1.5e308,0],[True,False]),[1.5e308,7.5e307])
        w=program(n.Operator.weighted_sum,(0,1),(.75,.25),slots=3)
        self.assertEqual(n.evaluate_scalars(w,[.5,1,0],[True,True,False]),[.5,1,.625])
        w=program(n.Operator.weighted_sum,(0,1),(1,-1),slots=3)
        self.assertEqual(n.evaluate_scalars(w,[1.5e308,1.5e308,0],[True,True,False]),[1.5e308,1.5e308,0])
        self.refuses('nonfinite',lambda:n.evaluate_scalars(program(n.Operator.affine,scale=2),[1.5e308,0],[True,False]))
        self.refuses('nonfinite',lambda:n.evaluate_scalars(program(n.Operator.affine,scale=TINY),[TINY,0],[True,False]))
        for values,weights in (([1.5e308,1.5e308,0],[1,1]),([1.5e308,1.5e308,0],[2,-2])):
            with self.subTest(weights=weights):
                self.refuses('nonfinite',lambda:n.evaluate_scalars(program(n.Operator.weighted_sum,(0,1),weights,slots=3),values,[True,True,False]))

    def test_all_scalar_slots_and_unused_fields_are_validated(self):
        for slot in (0,1,2):
            for v in (math.nan,math.inf):
                values=[.25,0,0];values[slot]=v
                with self.subTest(slot=slot,value=v):
                    self.refuses('nonfinite',lambda:n.evaluate_scalars(program(slots=3),values,[True,False,False]))
        self.refuses('invalid_sample',lambda:n.evaluate_scalars(program(),[.25,0],[False,False]))
        self.assertEqual(n.evaluate_scalars(program(),[.25,100],[True,False]),[.25,.25])
        for field in ('scale','offset','weights'):
            r=n.Instruction();r.inputs=[0];r.output=1
            with self.subTest(unused=field):self.refuses('nonfinite',lambda:setattr(r,field,[math.inf] if field=='weights' else math.inf))

    def test_scalar_structure_domain_and_topology_codes(self):
        p=program();d=n.Domain();d.minimum=1;d.maximum=0;p.domains=[d,d]
        self.refuses('domain',lambda:n.evaluate_scalars(p,[.25,0],[True,False]))
        d.minimum=0;d.maximum=1;p.domains=[d,d]
        self.refuses('domain',lambda:n.evaluate_scalars(p,[2,0],[True,False]))
        p.instructions=[];self.assertEqual(n.evaluate_scalars(p,[2,0],[False,False]),[2,0])
        for inputs,output,op,weights,code in (([0,1],2,n.Operator.identity,[],'shape'),([0],2,n.Operator.weighted_sum,[],'shape'),([3],2,n.Operator.identity,[],'binding'),([2],2,n.Operator.identity,[],'binding'),([],2,n.Operator.identity,[],'binding')):
            with self.subTest(inputs=inputs,op=op):
                self.refuses(code,lambda:n.evaluate_scalars(program(op,inputs,weights,slots=3,output=output),[0,0,0],[True]*3))
        p=program(slots=3);a=p.instructions[0];a.inputs=[1];a.output=2
        b=n.Instruction();b.inputs=[0];b.output=1;p.instructions=[a,b]
        self.refuses('cycle',lambda:n.evaluate_scalars(p,[0,0,0],[True]*3))
        p.instructions=[b,b];self.refuses('binding',lambda:n.evaluate_scalars(p,[0,0,0],[True]*3))

    def test_detached_nested_getters_and_setter_arguments(self):
        d=n.Domain();d.minimum=0;d.maximum=1
        r=n.Instruction();r.inputs=[0,1];r.output=2;r.operation=n.Operator.weighted_sum;r.weights=[.5,.5]
        ds=[d]*3;rs=[r];p=n.ScalarProgram();p.domains=ds;p.instructions=rs
        d.maximum=.1;r.weights=[2,2];ds.clear();rs.clear()
        out=n.evaluate_scalars(p,[1,0,0],[True,True,False]);self.assertEqual(out,[1,0,.5])
        ds=p.domains;rs=p.instructions
        ds[0].maximum=.1;rs[0].weights=[2,2];rs[0].scale=2;rs[0].offset=1;rs[0].inputs=[1,0];rs[0].output=0
        self.assertEqual(self.succeeds(lambda:n.evaluate_scalars(p,[1,0,0],[True,True,False])),[1,0,.5])
        ds.clear();rs.clear();out[2]=9
        del d,r,ds,rs;gc.collect()
        self.assertEqual(self.succeeds(lambda:n.evaluate_scalars(p,[1,0,0],[True,True,False])),[1,0,.5])

    def test_getters_survive_vector_replacement_and_parent_deletion(self):
        # This test only runs after detached getters pass; never dereference stale legacy aliases.
        p=program(n.Operator.affine,scale=.25);old_d=p.domains;old_i=p.instructions
        old_i[0].scale=.5
        self.assertEqual(n.evaluate_scalars(p,[1,0],[True,False]),[1,.25])
        for slots,values,expected in ((4,[1,0,0,0],[1,0,0,1]),(2,[.25,0],[.25,.25])):
            replacement=program(slots=slots)
            p.domains=replacement.domains;p.instructions=replacement.instructions
            old_d[0].maximum=.1;old_i[0].scale=8
            self.assertEqual(n.evaluate_scalars(p,values,[True]+[False]*(slots-1)),expected)
        p.domains=[];p.instructions=[];del p;gc.collect()
        old_d[0].minimum=-1;old_i[0].inputs=[9];old_i[0].weights=[2]
        self.assertEqual(old_d[0].minimum,-1);self.assertEqual(old_i[0].weights,[2])

    def test_numeric_returns_survive_mutation_and_deletion(self):
        a=ROWS.copy();p=[1,2,3];out=n.transform_point(a,p)
        a[0]=99;p[0]=99;del a,p;gc.collect();self.assertEqual(out,[5,-2,17])
        b=[[2,0,0]];d=[[[0,4,0]]];w=[-2];out=n.morph_positions(b,d,w)
        b[0][0]=99;d[0][0][1]=99;w[0]=99;del b,d,w;gc.collect();self.assertEqual(out,[[2,-8,0]])
        result=skin();del result[:];self.assertEqual(skin(),[[2,3,4]])
        p=program();v=[.25,0];valid=[True,False];out=n.evaluate_scalars(p,v,valid)
        v[0]=9;valid[0]=False;del p,v,valid;gc.collect();self.assertEqual(out,[.25,.25])


if __name__ == '__main__':
    names=unittest.defaultTestLoader.getTestCaseNames(Strict)
    # New named adapters do not exist in baseline; absence is setup, not semantic RED.
    if baseline:names.remove('test_named_storage_bridge')
    suite=unittest.TestSuite(Strict(name) for name in names)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'methods':names,'tests_run':result.testsRun,'failures':[str(t) for t,detail in result.failures],
            'errors':[str(t) for t,detail in result.errors],'skips':result.skipped,
            'baseline_exclusions':['test_named_storage_bridge: new helper setup'] if baseline else []}
    print('STRICT_RESULT='+json.dumps(report,sort_keys=True),flush=True)
    sys.exit(not result.wasSuccessful())
