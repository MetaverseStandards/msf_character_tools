# SPDX-License-Identifier: MIT
"""Adversarial public API checks and independent analytical numeric fixtures."""
import base64
import contextlib
import copy
import hashlib
import inspect
import io
import json
import math
import os
import socket
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import msf_tools as m
from msf_tools import cli, geometry

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures"


def asset(doc, resolver=None, sidecar=None):
    return m.inspect_asset(m.canonical_json(doc), "gltf", resolver, sidecar)


def source_doc():
    return m.load_authoring(ROOT / "examples/authoring").value.to_dict()


def signal(id):
    d = source_doc()["signals"][0]
    d["id"] = id
    return d


def rule(id, inputs, output, op=None):
    d = source_doc()["mappings"][0]["rules"][0]
    d.update(id=id, inputs=inputs, outputs=[output], operator=op or {"id":"identity"})
    return d


def compile_doc(doc):
    return m.compile_pack(m.validate_authoring(doc).value)


def compile_map(doc):
    p = compile_doc(doc).value
    return m.compile_mapping(p, m.profile_snapshot(p,"source").value,
                             m.profile_snapshot(p,"target").value,"wink")


class Checks(unittest.TestCase):
    def good(self, r):
        self.assertTrue(r.ok, m.canonical_json(r.report).decode())
        return r.value

    def bad(self, r, code):
        self.assertFalse(r.ok)
        self.assertIsNone(r.value)
        self.assertIn(code, [d.code for d in r.report.diagnostics], m.canonical_json(r.report).decode())


class AuthoringTests(Checks):
    def test_unused_evidence_coverage_and_partitions(self):
        d=source_doc();d["evidence"].append({"id":"unused","claim":"Unresolved original inventory","status":"unresolved","license":"CC-BY-SA-4.0","authorship":"MSF Tools contributors"})
        p=self.good(compile_doc(d));c=m.coverage(p)
        self.assertEqual(c["disposition_counts"]["mapped"],2)
        self.assertEqual(c["mapping_quality_counts"]["exact"],1)
        self.assertEqual(c["evidence"][-1]["id"],"unused")
        self.assertEqual(c["evidence"][-1]["signal_ids"],[])
    def test_strict_types_known_keys_references_and_complete_report(self):
        d = source_doc()
        d["signals"][0]["neutral"] = True
        d["signals"][1]["surprise"] = 1
        d["profiles"][0]["signal_ids"] = ["absent"]
        r = m.validate_authoring(d)
        self.bad(r,"E_TYPE")
        self.assertGreaterEqual(len(r.report.diagnostics),3)
        self.assertIn("E_REFERENCE",[x.code for x in r.report.diagnostics])

    def test_duplicates_metadata_nonfinite_version(self):
        d = source_doc()
        d["signals"].append(copy.deepcopy(d["signals"][0]))
        self.bad(m.validate_authoring(d),"E_DUPLICATE_ID")
        d = source_doc()
        d["signals"][0]["metadata"] = {"custom":[1,{"unknown":True}]}
        self.good(m.validate_authoring(d))
        d["signals"][0]["metadata"]["x"] = float("nan")
        self.bad(m.validate_authoring(d),"E_NONFINITE")
        d = source_doc(); d["operator_version"]="2.0"
        self.bad(m.validate_authoring(d),"E_ENUM")

    def test_pack_requires_validated_and_immutable(self):
        self.bad(m.compile_pack(source_doc()),"E_VALIDATED_REQUIRED")
        d = source_doc(); validated=self.good(m.validate_authoring(d)); d["id"]="mutated"
        p = self.good(m.compile_pack(validated)); self.assertEqual(p.document["id"],"msf.synthetic")
        with self.assertRaises(TypeError): p.document["id"]="mutated"

    def test_fragments_sorted_duplicate_metadata_and_generated_exclusion(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); (p/"pack.toml").write_text((ROOT/"examples/authoring/pack.toml").read_text())
            (p/"generated").mkdir(); (p/"generated/invalid.toml").write_text("invalid TOML")
            self.good(m.load_authoring(p))
            (p/"extra.toml").write_text('id="duplicate"\n')
            self.bad(m.load_authoring(p),"E_DUPLICATE_KEY")

    def test_hidden_virtualenv_checkout_and_files_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"pack.toml").write_bytes((ROOT/"examples/authoring/pack.toml").read_bytes())
            for name in [".venv",".git",".ci-tools"]:
                (p/name).mkdir();(p/name/"pack.toml").write_text('schema_version="duplicate"\n')
            (p/".hidden.toml").write_text("broken TOML!")
            self.good(m.load_authoring(p))

    def test_deterministic_bytes_csv_coverage_golden(self):
        p=self.good(compile_doc(source_doc()))
        self.assertEqual(p.to_bytes(),(ROOT/"examples/generated/pack.json").read_bytes())
        self.assertEqual(p.sha256,hashlib.sha256(p.to_bytes()).hexdigest())
        self.assertEqual(m.survey_csv(p),(ROOT/"examples/generated/survey.csv").read_bytes())
        self.assertEqual(m.canonical_json(m.coverage(p)),(ROOT/"examples/generated/coverage.json").read_bytes())
        self.assertEqual(m.canonical_json({"z":-0.0,"a":"é"}),b'{\n  "a": "\xc3\xa9",\n  "z": 0.0\n}\n')


class MappingTests(Checks):
    def test_signed_values_invalid_missing_boolean_timestamp_and_domain(self):
        c=self.good(compile_map(source_doc()))
        r=self.good(m.evaluate_mapping(c,[{"timestamp":.5,"values":{"input.wink":-0.5},"validity":{"input.wink":True}}]))
        self.assertEqual(r.to_dict()["samples"][0]["values"],{"output.wink":-.5})
        self.bad(m.evaluate_mapping(c,[{"timestamp":0,"values":{"input.wink":0},"validity":{"input.wink":False}}]),"E_INVALID_SAMPLE")
        self.bad(m.evaluate_mapping(c,[{"timestamp":0,"values":{},"validity":{}}]),"E_MISSING_SAMPLE")
        self.bad(m.evaluate_mapping(c,[{"timestamp":True,"values":{},"validity":{}}]),"E_TIMESTAMP")
        self.bad(m.evaluate_mapping(c,[{"timestamp":0,"values":{"input.wink":True},"validity":{"input.wink":True}}]),"E_TYPE")
        self.bad(m.evaluate_mapping(c,[{"timestamp":0,"values":{"input.wink":3},"validity":{"input.wink":True}}]),"E_DOMAIN")

    def test_empty_samples_and_unknown_frame_key(self):
        c=self.good(compile_map(source_doc()))
        r=m.evaluate_mapping(c,[])
        self.assertEqual(self.good(r).to_dict(),{"samples":[]});self.assertEqual(r.report.to_dict(),{"schema_version":"1.0","diagnostics":[],"losses":[]})
        calls=[]
        class Frames(list):
            def __iter__(self):
                calls.append("iter");return iter([{"timestamp":0,"values":{},"validity":{},"extra":1}])
        r=m.evaluate_mapping(c,Frames())
        self.assertEqual(calls,["iter"]);self.assertIsNone(r.value)
        self.assertEqual(r.report.to_dict(),{"schema_version":"1.0","diagnostics":[{"code":"E_UNKNOWN_KEY","severity":"error","ref":"/samples/0","message":"Unknown keys: extra","remediation":"Correct the referenced input."}],"losses":[]})

    def test_topological_and_output_domain_weighted_sum(self):
        d=source_doc(); d["signals"] += [signal("mid"),signal("other")]
        d["profiles"][0]["signal_ids"].append("other")
        d["signals"][1]["domain"]={"min":-2,"max":4}
        d["mappings"][0]["rules"]=[rule("last",["mid","other"],"output.wink",{"id":"weighted_sum","weights":[2,-1]}),rule("first",["input.wink"],"mid")]
        c=self.good(compile_map(d)); self.assertEqual([r["id"] for r in c.instructions],["first","last"])
        frame={"timestamp":0,"values":{"input.wink":1.5,"other":.5},"validity":{"input.wink":True,"other":True}}
        result=self.good(m.evaluate_mapping(c,[frame])); self.assertEqual(result.to_dict()["samples"][0]["values"]["output.wink"],2.5)
        frame["values"]["other"]=-1
        frame["values"]["input.wink"]=2
        self.bad(m.evaluate_mapping(c,[frame]),"E_DOMAIN")

    def test_cycles_multiple_writers_units_calibration_unresolved_approximation(self):
        d=source_doc(); d["signals"]+=[signal("a"),signal("b")]
        d["mappings"][0]["rules"]=[rule("a",["b"],"a"),rule("b",["a"],"b")]
        self.bad(compile_map(d),"E_MAPPING_CYCLE")
        d=source_doc();d["mappings"][0]["rules"].append(rule("duplicate",["input.wink"],"output.wink"))
        self.bad(compile_map(d),"E_MULTIPLE_WRITERS")
        d=source_doc();d["signals"][1]["units"]="radians"
        self.bad(compile_map(d),"E_UNITS")
        d["mappings"][0]["rules"][0]["operator"]={"id":"affine","scale":2,"offset":0}
        self.good(compile_map(d))
        d=source_doc();d["signals"][1]["calibration"]="different provider"
        self.bad(compile_map(d),"E_CALIBRATION")
        d=source_doc();r=d["mappings"][0]["rules"][0];r["disposition"]="unresolved";r.pop("mapping_quality")
        self.good(compile_doc(d));self.bad(compile_map(d),"E_UNRESOLVED_RULE")
        d=source_doc();d["mappings"][0]["rules"][0]["mapping_quality"]="approximate"
        self.bad(compile_map(d),"E_APPROXIMATION")
        p=self.good(compile_doc(d))
        self.bad(m.compile_mapping(p,self.good(m.profile_snapshot(p,"source")),self.good(m.profile_snapshot(p,"target")),"wink",True),"E_LOSS_REQUIRED")
        # Approximation needs an authored loss; compilation preserves it.
        loss={"category":"signal","effect":"approximated","reason":"Original declared synthetic approximation.","refs":["input.wink","output.wink"]}
        d["mappings"][0]["rules"][0]["loss_annotations"]=[loss]
        p=self.good(compile_doc(d)); c=self.good(m.compile_mapping(p,self.good(m.profile_snapshot(p,"source")),self.good(m.profile_snapshot(p,"target")),"wink",True))
        self.assertEqual(c.losses[0].to_dict(),loss)


class AssetTests(Checks):
    def test_asset_bytes_parameter_is_positional_only(self):
        raw=(FIX/"combined.gltf").read_bytes()
        self.assertIs(inspect.signature(m.inspect_asset).parameters["bytes"].kind,inspect.Parameter.POSITIONAL_ONLY)
        self.good(m.inspect_asset(raw,"gltf"));self.good(m.inspect_asset(raw,format="gltf"))
        r=m.inspect_asset(bytes=raw,format="gltf");self.bad(r,"E_INPUT");self.assertIn("positional-only",r.report.diagnostics[0].message)

    def test_extension_defined_animation_inventory_and_runtime_refusal(self):
        d=json.loads((FIX/"combined.gltf").read_bytes());d["extensionsUsed"].append("KHR_animation_pointer");d["extensionsRequired"]=["KHR_animation_pointer"]
        d["animations"][0]["channels"][0]["target"]={"path":"pointer","extensions":{"KHR_animation_pointer":{"pointer":"/nodes/0/rotation"}}}
        s=self.good(asset(d));self.assertEqual(s.document["animations"][0]["channels"][0]["target"]["path"],"pointer")
        self.bad(m.evaluate_geometry(s,animation_id=0),"E_REQUIRED_EXTENSION")

    def test_sparse_index_resource_hash_and_corruption(self):
        data=bytes([0,0,0,0])+struct.pack("<fff",.1,.2,.3)
        d={"asset":{"version":"2.0"},"buffers":[{"byteLength":1,"uri":"indices.bin"},{"byteLength":12,"uri":"values.bin"}],
           "bufferViews":[{"buffer":0,"byteLength":1},{"buffer":1,"byteLength":12}],
           "accessors":[{"componentType":5126,"type":"VEC3","count":1,"min":[.1,.2,.3],"max":[.1,.2,.3],"sparse":{"count":1,"indices":{"bufferView":0,"componentType":5121},"values":{"bufferView":1}}}],
           "meshes":[{"primitives":[{"mode":0,"attributes":{"POSITION":0},"targets":[{"POSITION":0}]}]}],"nodes":[{"mesh":0}]}
        resolver=lambda uri:data[:1] if uri=="indices.bin" else data[4:]
        s=self.good(asset(d,resolver));b=self.good(m.morph_binding(s,source_doc()["signals"][1],0,0));b=dict(b);b["ref"]=dict(b["ref"]);b["ref"]["resource_sha256"]=hashlib.sha256(data[:1]).hexdigest()
        self.good(m.annotate_asset(s,{"bindings":[b]}))
        bad=lambda uri:bytes([1]) if uri=="indices.bin" else data[4:]
        self.bad(asset(d,bad),"E_SPARSE_INDEX")
        sc=self.good(m.annotate_asset(s,{"bindings":[b]})).to_dict();sc["resource_hashes"]["/buffers/0"]="0"*64
        self.bad(asset(d,resolver,sc),"E_STALE_SOURCE")
    def test_original_unknown_data_chunks_and_immutability(self):
        raw=(FIX/"combined.glb").read_bytes();s=self.good(m.inspect_asset(raw,"glb"))
        self.assertEqual(s.original_bytes,raw);self.assertEqual(s.chunks[-1].type,0xDEADBEEF);self.assertEqual(s.chunks[-1].data,b"opaque!!")
        self.assertEqual(s.document["extensions"]["MSF_fixture_unknown"]["opaque"],"preserve")
        with self.assertRaises(TypeError): s.document["nodes"][0]["name"]="changed"

    def test_huge_zero_accessor_fails_before_allocation(self):
        d={"asset":{"version":"2.0"},"accessors":[{"componentType":5126,"type":"MAT4","count":10**12}]}
        self.bad(asset(d),"E_RESOURCE_LIMIT")

    def test_glb_malformed_duplicate_keys_nonfinite(self):
        raw=(FIX/"combined.glb").read_bytes()
        self.bad(m.inspect_asset(raw[:-1],"glb"),"E_GLB_HEADER")
        self.bad(m.inspect_asset(b'{"asset":{"version":"2.0","version":"2.0"}}',"gltf"),"E_DUPLICATE_KEY")
        self.bad(m.inspect_asset(b'{"asset":{"version":"2.0"},"extras":{"v":NaN}}',"gltf"),"E_NONFINITE")

    def test_interleaved_normalized_sparse_and_matrix_padding(self):
        data=struct.pack("<fffIfffI",1,2,3,999,4,5,6,999)+bytes([0,127,255,64])+bytes([1,0,0,0])+struct.pack("<fff",7,8,9)+bytes([1,2,3,0,4,5,6,0,7,8,9,0])
        d={"asset":{"version":"2.0"},"buffers":[{"byteLength":len(data),"uri":"data:application/octet-stream;base64,"+base64.b64encode(data).decode()}],
           "bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":32,"byteStride":16},{"buffer":0,"byteOffset":32,"byteLength":4},{"buffer":0,"byteOffset":36,"byteLength":1},{"buffer":0,"byteOffset":40,"byteLength":12},{"buffer":0,"byteOffset":52,"byteLength":12}],
           "accessors":[{"bufferView":0,"componentType":5126,"count":2,"type":"VEC3"},
                        {"bufferView":1,"componentType":5121,"normalized":True,"count":1,"type":"VEC4"},
                        {"componentType":5126,"count":3,"type":"VEC3","sparse":{"count":1,"indices":{"bufferView":2,"componentType":5121},"values":{"bufferView":3}}},
                        {"bufferView":4,"componentType":5121,"count":1,"type":"MAT3"}]}
        s=self.good(asset(d));self.assertEqual(self.good(m.decode_accessor(s,0)),((1,2,3),(4,5,6)))
        self.assertEqual(self.good(m.decode_accessor(s,1))[0],(0,127/255,1,64/255))
        self.assertEqual(self.good(m.decode_accessor(s,2)),((0,0,0),(7,8,9),(0,0,0)))
        self.assertEqual(self.good(m.decode_accessor(s,3))[0],tuple(range(1,10)))
        d["accessors"][2]["sparse"]["count"]=4
        self.bad(asset(d),"E_SPARSE_INDEX")

    def test_bounds_binary_nan_sparse_index_and_hierarchy(self):
        d=json.loads((FIX/"combined.gltf").read_bytes());d["accessors"][0]["byteOffset"]=9999*4
        self.bad(asset(d),"E_ACCESSOR_BOUNDS")
        d=json.loads((FIX/"combined.gltf").read_bytes());data=bytearray(base64.b64decode(d["buffers"][0]["uri"].split(",")[1]));struct.pack_into("<f",data,0,float("nan"));d["buffers"][0]["uri"]="data:application/octet-stream;base64,"+base64.b64encode(data).decode()
        self.bad(asset(d),"E_NONFINITE")
        d=json.loads((FIX/"combined.gltf").read_bytes());d["nodes"][2]["children"]=[0]
        self.bad(asset(d),"E_HIERARCHY_CYCLE")
        d=json.loads((FIX/"combined.gltf").read_bytes());d["nodes"][3]["children"]=[2]
        self.bad(asset(d),"E_HIERARCHY")

    def test_external_default_no_fetch_resolver_traversal_symlink_budget(self):
        d={"asset":{"version":"2.0"},"buffers":[{"byteLength":12,"uri":"https://example.invalid/file.bin"}],"bufferViews":[{"buffer":0,"byteLength":12}],"accessors":[{"bufferView":0,"count":1,"componentType":5126,"type":"VEC3"}]}
        s=self.good(asset(d));self.bad(m.decode_accessor(s,0),"E_RESOURCE_UNAVAILABLE")
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();(root/"data.bin").write_bytes(struct.pack("<fff",1,2,3));(root/"link.bin").symlink_to(root/"data.bin")
            resolver=m.LocalResolver(root);d["buffers"][0]["uri"]="data.bin";s=self.good(asset(d,resolver));self.assertEqual(self.good(m.decode_accessor(s,0))[0],(1,2,3))
            for uri in ["../data.bin","%2e%2e/data.bin","/absolute","https://example.invalid/x","link.bin"]:
                d["buffers"][0]["uri"]=uri;self.assertFalse(asset(d,m.LocalResolver(root)).ok)
            d["buffers"][0]["uri"]="data.bin";self.bad(asset(d,m.LocalResolver(root,max_resource_bytes=8)),"E_RESOURCE_LIMIT")

    def test_resolver_refuses_fifo_without_blocking(self):
        d={"asset":{"version":"2.0"},"buffers":[{"byteLength":12,"uri":"pipe.bin"}]}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();os.mkfifo(root/"pipe.bin");(root/"asset.gltf").write_bytes(m.canonical_json(d))
            # A FIFO with no writer blocks a plain open, so the CLI runs in a killable child process.
            try:
                r=subprocess.run([sys.executable,"-B","-m","msf_tools","inspect",root/"asset.gltf","--resolver-root",root],cwd=ROOT,capture_output=True,timeout=5)
            except subprocess.TimeoutExpired:
                self.fail("Resolver blocked opening a FIFO instead of refusing it.")
        self.assertEqual(r.returncode,1);self.assertEqual(r.stdout,b"")
        self.assertEqual([(x["code"],x["ref"]) for x in json.loads(r.stderr)["diagnostics"]],[("E_RESOURCE_TYPE","/resources")])

    def test_resolver_refuses_unix_socket(self):
        d={"asset":{"version":"2.0"},"buffers":[{"byteLength":12,"uri":"sock.bin"}]}
        with tempfile.TemporaryDirectory() as td, socket.socket(socket.AF_UNIX) as listener:
            root=Path(td).resolve();listener.bind(str(root/"sock.bin"))
            r=asset(d,m.LocalResolver(root))
        self.assertIsNone(r.value)
        self.assertEqual([(x.code,x.ref) for x in r.report.diagnostics],[("E_RESOURCE_TYPE","/resources")])

    def test_sidecar_idempotence_hash_references_mapping(self):
        raw=(FIX/"combined.gltf").read_bytes();s=self.good(m.inspect_asset(raw,"gltf"));d=source_doc();sig=d["signals"][1]
        b=self.good(m.morph_binding(s,sig,5,0));sc=self.good(m.annotate_asset(s,{"bindings":[b],"metadata":{"keep":42}}))
        self.assertEqual(sc.to_bytes(),self.good(m.annotate_asset(s,{"bindings":[b],"metadata":{"keep":42}})).to_bytes())
        bound=self.good(m.inspect_asset(raw,"gltf",sidecar=sc));p=self.good(compile_doc(d));self.good(m.compile_mapping(p,self.good(m.profile_snapshot(p,"source")),bound,"wink"))
        stale=sc.to_dict();stale["asset_sha256"]="0"*64;self.bad(m.inspect_asset(raw,"gltf",sidecar=stale),"E_STALE_SOURCE")
        stale=sc.to_dict();stale["resource_hashes"]["/buffers/0"]="0"*64;self.bad(m.inspect_asset(raw,"gltf",sidecar=stale),"E_STALE_SOURCE")
        stale=sc.to_dict();stale["bindings"][0]["ref"]["target"]=100;self.bad(m.inspect_asset(raw,"gltf",sidecar=stale),"E_BINDING_REFERENCE")
        self.assertEqual(s.original_bytes,raw)


def instanced_points(*meshes):
    """Zero-backed point meshes given as (vertex count, instance count) pairs."""
    accessors,mesh_rows,nodes=[],[],[]
    for count,instances in meshes:
        accessors.append({"componentType":5126,"type":"VEC3","count":count,"min":[0,0,0],"max":[0,0,0]})
        mesh_rows.append({"primitives":[{"mode":0,"attributes":{"POSITION":len(accessors)-1}}]})
        nodes+=[{"mesh":len(mesh_rows)-1}]*instances
    return {"asset":{"version":"2.0"},"accessors":accessors,"meshes":mesh_rows,"nodes":nodes}


class GeometryTests(Checks):
    def assert_instance_budget_refusal(self, r):
        self.assertEqual([(d.code,d.ref) for d in r.report.diagnostics],[("E_RESOURCE_LIMIT","/nodes")])
        self.assertIsNone(r.value)

    def test_instance_vertex_budget_threshold(self):
        with patch.object(geometry,"MAX_INSTANCE_VERTICES",4):
            for instances in (3,4):
                v=self.good(m.evaluate_geometry(self.good(asset(instanced_points((1,instances)))))).to_dict()
                self.assertEqual([i["node"] for i in v["instances"]],list(range(instances)))
            self.assert_instance_budget_refusal(m.evaluate_geometry(self.good(asset(instanced_points((1,5))))))
            self.assert_instance_budget_refusal(m.evaluate_geometry(self.good(asset(instanced_points((2,1),(1,3))))))

    def test_default_instance_vertex_budget_refuses_multiplied_mesh(self):
        s=self.good(asset(instanced_points((1000,1333),(334,1))))
        self.assert_instance_budget_refusal(m.evaluate_geometry(s))
        # Evaluating each POSITION accessor once stays within the inspection component limit.
        self.assertEqual(geometry.MAX_INSTANCE_VERTICES,1_333_333)

    def test_separate_morph_and_skin_analytical(self):
        doc=json.loads((FIX/"combined.gltf").read_bytes())
        doc.pop("animations")
        for node in doc["nodes"]:
            node.pop("skin",None)
        s=self.good(asset(doc));value=self.good(m.evaluate_geometry(s)).to_dict()["instances"][0]["primitives"][0]["positions"]
        self.assertAlmostEqual(value[0][0],-.575,places=7)
        self.assertAlmostEqual(value[0][1],1.125,places=7)
        self.assertAlmostEqual(value[0][2],.025,places=7)
        doc=json.loads((FIX/"combined.gltf").read_bytes());doc.pop("animations")
        s=self.good(asset(doc));value=self.good(m.evaluate_geometry(s,morph_weights={5:[0,0,0],6:[0,0,0]})).to_dict()
        self.assertAlmostEqual(value["instances"][0]["primitives"][0]["positions"][0][0],-.5,places=7)
        self.assertAlmostEqual(value["instances"][1]["primitives"][0]["positions"][0][0],-1,places=7)
    def test_independent_combined_signed_morph_noncommuting_instanced_four_joints(self):
        s=self.good(m.inspect_asset((FIX/"combined.gltf").read_bytes(),"gltf"));gold=json.loads((FIX/"combined.analytical.json").read_bytes())
        maximum=0
        for frame in gold["samples"]:
            value=self.good(m.evaluate_geometry(s,timestamp=frame["timestamp"],animation_id=0)).to_dict()
            for actual, expected in zip(value["instances"],frame["instances"]):
                self.assertEqual(actual["node"],expected["node"])
                for a,e in zip(actual["primitives"][0]["positions"],expected["positions"]):
                    maximum=max(maximum,*(abs(x-y) for x,y in zip(a,e)))
        self.assertLess(maximum,1e-6)
        # Instancing is not collapsed: different mesh world inverses and defaults.
        result=self.good(m.evaluate_geometry(s,timestamp=1,animation_id=0)).to_dict()
        self.assertNotEqual(result["instances"][0]["primitives"],result["instances"][1]["primitives"])
        self.assertEqual(s.document["nodes"][4]["name"],"unrecognized weighted joint")

    def test_rest_not_bind_and_eight_required_extensions_singular(self):
        rest=self.good(m.inspect_asset((FIX/"rest-not-bind.gltf").read_bytes(),"gltf"));base=self.good(m.inspect_asset((FIX/"combined.gltf").read_bytes(),"gltf"))
        a=self.good(m.evaluate_geometry(rest)).to_dict()["instances"][0]["primitives"][0]["positions"]
        b=self.good(m.evaluate_geometry(base)).to_dict()["instances"][0]["primitives"][0]["positions"]
        self.assertAlmostEqual(a[0][1]-b[0][1],.25*(.4+.3),places=7)
        eight=self.good(m.inspect_asset((FIX/"eight-influence.gltf").read_bytes(),"gltf"));self.bad(m.evaluate_geometry(eight),"E_INFLUENCE_LIMIT")
        d=json.loads((FIX/"combined.gltf").read_bytes());d["extensionsRequired"]=["MSF_fixture_unknown"]
        s=self.good(asset(d));self.bad(m.evaluate_geometry(s),"E_REQUIRED_EXTENSION")
        self.bad(m.evaluate_geometry(base,node_transforms={5:{"scale":[0,1,1]}}),"E_SINGULAR")
        self.bad(m.evaluate_geometry(base,attributes=("NORMAL",)),"E_GEOMETRY_CAPABILITY")
        self.bad(m.evaluate_geometry(base,timestamp=.5,animation_id=0,morph_weights={5:[0,0,0]}),"E_MULTIPLE_WRITERS")

    def test_skin_bad_binary_types_signed_skin_and_joint_bounds(self):
        d=json.loads((FIX/"combined.gltf").read_bytes());d["accessors"][1]["componentType"]=5122
        self.bad(asset(d),"E_GEOMETRY_TYPE")
        for change in ("negative","joint"):
            d=json.loads((FIX/"combined.gltf").read_bytes());data=bytearray(base64.b64decode(d["buffers"][0]["uri"].split(",")[1]))
            aid=2 if change=="negative" else 1;offset=d["bufferViews"][d["accessors"][aid]["bufferView"]]["byteOffset"]
            struct.pack_into("<f" if change=="negative" else "<H",data,offset,-.4 if change=="negative" else 100)
            d["buffers"][0]["uri"]="data:application/octet-stream;base64,"+base64.b64encode(data).decode()
            self.bad(asset(d),"E_SKIN_WEIGHTS" if change=="negative" else "E_JOINT_BOUNDS")

    def test_reparent_world_preservation_shear_and_singular(self):
        child=[0,1,0,0,-1,0,0,0,0,0,1,0,2,3,4,1]
        parent=[1,0,0,0,0,1,0,0,0,0,1,0,1,1,0,1]
        local=self.good(m.reparent_local(child,parent));self.assertEqual(local[12:15],(1,2,4))
        shear=list(child);shear[5]=.5;self.bad(m.reparent_local(shear,parent),"E_SHEAR")
        parent[0]=0;self.bad(m.reparent_local(child,parent),"E_SINGULAR")


class AnimationTests(Checks):
    def fixture(self,kind,path,values):
        from make_fixtures import Builder
        b=Builder();ti=b.add([0,2],"SCALAR",extrema=True);out=b.add(values,"VEC4" if path=="rotation" else "VEC3")
        return self.good(asset({"asset":{"version":"2.0"},"buffers":[{"byteLength":len(b.data),"uri":"data:application/octet-stream;base64,"+base64.b64encode(b.data).decode()}],"bufferViews":b.views,"accessors":b.accessors,"nodes":[{}],"animations":[{"samplers":[{"input":ti,"output":out,"interpolation":kind}],"channels":[{"sampler":0,"target":{"node":0,"path":path}}]}]}))

    def test_step_linear_quaternion_shortest_and_endpoint_clamp(self):
        s=self.fixture("STEP","translation",[(0,0,0),(2,4,6)]);self.assertEqual(self.good(m.sample_animation(s,0,1))[0]["translation"],(0,0,0));self.assertEqual(self.good(m.sample_animation(s,0,3))[0]["translation"],(2,4,6))
        s=self.fixture("LINEAR","translation",[(0,0,0),(2,4,6)]);self.assertEqual(self.good(m.sample_animation(s,0,.5))[0]["translation"],(.5,1,1.5))
        s=self.fixture("LINEAR","rotation",[(0,0,0,1),(0,0,-1,0)]);q=self.good(m.sample_animation(s,0,1))[0]["rotation"]
        self.assertAlmostEqual(abs(q[2]),math.sqrt(.5));self.assertAlmostEqual(q[3],math.sqrt(.5))
        s=self.fixture("LINEAR","rotation",[(0,0,0,1),(0,0,0,-1)]);self.assertEqual(self.good(m.sample_animation(s,0,1))[0]["rotation"],(0,0,0,1))

    def test_cubic_dt_hermite_and_no_tangent_normalization(self):
        s=self.fixture("CUBICSPLINE","translation",[(0,0,0),(0,0,0),(3,0,0),(0,0,0),(2,0,0),(0,0,0)])
        # t=.5: h01*2 + h10*dt*3 = 1 + .75 = 1.75.
        self.assertEqual(self.good(m.sample_animation(s,0,1))[0]["translation"],(1.75,0,0))
        s=self.fixture("CUBICSPLINE","rotation",[(0,0,0,0),(0,0,0,1),(0,0,2,0),(0,0,0,0),(0,0,1,0),(0,0,0,0)])
        q=self.good(m.sample_animation(s,0,1))[0]["rotation"]
        # Raw Hermite=(0,0,1,.5), then normalize (tangent magnitude 2 retained).
        self.assertAlmostEqual(q[2],2/math.sqrt(5));self.assertAlmostEqual(q[3],1/math.sqrt(5))


class CLITests(Checks):
    def test_outputs_never_overwrite_assets_authoring_hardlinks_or_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);raw=(FIX/"combined.gltf").read_bytes();(p/"asset.gltf").write_bytes(raw);(p/"annotations.json").write_text('{"bindings":[]}')
            for destination in [p/"asset.gltf",p/"alias.gltf",p/"symlink.json"]:
                if destination.name=="alias.gltf":
                    import os
                    os.link(p/"asset.gltf",destination)
                if destination.name=="symlink.json":destination.symlink_to(p/"asset.gltf")
                r=self.run_cli("annotate",p/"asset.gltf",p/"annotations.json","--output",destination)
                self.assertEqual(r.returncode,1);self.assertIn("E_OUTPUT_PATH",[d["code"] for d in json.loads(r.stderr)["diagnostics"]]);self.assertEqual((p/"asset.gltf").read_bytes(),raw)
                self.assertEqual(r.stdout,b"")
                if destination.name=="symlink.json":self.assertTrue(destination.is_symlink());self.assertEqual(destination.readlink(),p/"asset.gltf")
            (p/"pack.toml").write_bytes((ROOT/"examples/authoring/pack.toml").read_bytes());before=(p/"pack.toml").read_bytes()
            r=self.run_cli("check",p/"pack.toml","--pack",p/"pack.toml","--csv",p/"survey.csv","--write");self.assertEqual(r.returncode,1);self.assertIn(b'E_OUTPUT_PATH',r.stderr);self.assertEqual((p/"pack.toml").read_bytes(),before);self.assertFalse((p/"survey.csv").exists())

    def test_output_creates_parent_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"annotations.json").write_text('{"bindings":[]}');out=p/"nested"/"sidecar.json"
            err=io.TextIOWrapper(io.BytesIO())
            with contextlib.redirect_stderr(err):code=cli.main(["annotate",str(FIX/"combined.gltf"),str(p/"annotations.json"),"--output",str(out)])
            self.assertEqual(code,0,err.buffer.getvalue())
            self.assertEqual(list(out.parent.iterdir()),[out]);self.assertEqual(json.loads(out.read_bytes())["bindings"],[])

    def test_extra_unlisted_output(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);args=["check",ROOT/"examples/authoring","--pack",p/"pack.json","--csv",p/"survey.csv"]
            self.assertEqual(self.run_cli(*args,"--write").returncode,0);(p/"unexpected.csv").write_text("extra")
            self.assertIn(b'E_OUTPUT_EXTRA',self.run_cli(*args).stderr)
    def run_cli(self,*args):
        return subprocess.run([sys.executable,"-B","-m","msf_tools",*map(str,args)],cwd=ROOT,capture_output=True,timeout=30)

    def test_generation_missing_extra_stale_and_failed_write(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);args=["check",ROOT/"examples/authoring","--pack",p/"pack.json","--csv",p/"survey.csv"]
            r=self.run_cli(*args);self.assertEqual(r.returncode,1);self.assertEqual(len(json.loads(r.stderr)["diagnostics"]),4)
            r=self.run_cli(*args,"--write");self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(self.run_cli(*args).returncode,0)
            (p/"survey.csv").write_bytes(b"stale");(p/"SHA256SUMS").write_text("abc  extra.json\n")
            r=self.run_cli(*args);codes=[x["code"] for x in json.loads(r.stderr)["diagnostics"]];self.assertIn("E_OUTPUT_STALE",codes);self.assertIn("E_OUTPUT_EXTRA",codes)
            bad=p/"bad.toml";bad.write_text('schema_version="bad"\n');before=(p/"pack.json").read_bytes();self.assertEqual(self.run_cli("check",bad,"--pack",p/"pack.json","--csv",p/"survey.csv","--write").returncode,1);self.assertEqual((p/"pack.json").read_bytes(),before)

    def test_all_commands_and_invalid_report(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            for args in [("inspect",FIX/"combined.glb"),("geometry",FIX/"combined.gltf","--animation","0","--time",".5"),("map",ROOT/"examples/authoring","wink","--source-profile","source","--target-profile","target"),("evaluate",ROOT/"examples/authoring","wink",ROOT/"examples/samples.json","--source-profile","source","--target-profile","target")]:
                r=self.run_cli(*args);self.assertEqual(r.returncode,0,r.stderr);json.loads(r.stdout)
            (p/"annotations.json").write_text('{"bindings":[],"metadata":{"note":"original"}}')
            r=self.run_cli("annotate",FIX/"combined.gltf",p/"annotations.json","--output",p/"sidecar.json");self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads((p/"sidecar.json").read_bytes())["schema_version"],"1.0")
            r=self.run_cli("invalid-command");self.assertEqual(r.returncode,1);self.assertIn(b'E_CLI_ARGUMENT',r.stderr)


if __name__ == "__main__":
    unittest.main()
