# SPDX-License-Identifier: MIT
"""Independent one-vertex fixture: compare the public Python evaluator to C++."""
import base64
import json
import math
import struct
import sys
import unittest

sys.path.insert(0, sys.argv.pop(1))
sys.path.insert(0, sys.argv.pop(1))
import _msf_native as native
from msf_tools import (inspect_asset, evaluate_geometry, validate_authoring, compile_pack,
                       profile_snapshot, compile_mapping, evaluate_mapping, decode_accessor,
                       sample_animation)


def fixture():
    binary = bytearray()
    views, accessors = [], []

    def accessor(values, component, kind, count):
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(struct.pack("<" + {5126: "f", 5123: "H"}[component] * len(values), *values))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(binary) - offset})
        accessors.append({"bufferView": len(views)-1, "componentType": component,
                          "type": kind, "count": count})
        if kind == "SCALAR" and values:
            accessors[-1].update(min=[min(values)], max=[max(values)])
        return len(accessors)-1

    position = accessor([1, 0, 0], 5126, "VEC3", 1)
    accessors[position].update(min=[1,0,0], max=[1,0,0])
    delta = accessor([0, 1, 0], 5126, "VEC3", 1)
    accessors[delta].update(min=[0,1,0], max=[0,1,0])
    joints = accessor([0, 0, 0, 0], 5123, "VEC4", 1)
    weights = accessor([1, 0, 0, 0], 5126, "VEC4", 1)
    ibm = accessor([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1], 5126, "MAT4", 1)
    times = accessor([0, 2], 5126, "SCALAR", 2)
    morph_curve = accessor([0, 0, 2, 0, 0, 0], 5126, "SCALAR", 6)
    quat_linear = accessor([0,0,0,1, 0,0,1,0], 5126, "VEC4", 2)
    quat_cubic = accessor([0,0,0,0, 0,0,0,1, 0,0,2,0,
                           0,0,0,0, 0,0,1,0, 0,0,0,0], 5126, "VEC4", 6)
    document = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0,1,2]}],
        "nodes": [{"name": "mesh", "mesh": 0, "skin": 0, "translation": [1,0,0]},
                  {"name": "joint", "rotation": [0,0,math.sqrt(.5),math.sqrt(.5)]},
                  {"name": "second instance", "mesh": 0, "skin": 0, "translation": [3,0,0]}],
        "meshes": [{"weights": [0], "primitives": [{"mode": 0,
                       "attributes": {"POSITION": position, "JOINTS_0": joints, "WEIGHTS_0": weights},
                       "targets": [{"POSITION": delta}]}]}],
        "skins": [{"joints": [1], "inverseBindMatrices": ibm}],
        "animations": [
            {"samplers": [{"input": times, "output": morph_curve, "interpolation": "CUBICSPLINE"}],
             "channels": [{"sampler": 0, "target": {"node": 0, "path": "weights"}}]},
            {"samplers": [{"input": times, "output": quat_linear, "interpolation": "LINEAR"}],
             "channels": [{"sampler": 0, "target": {"node": 1, "path": "rotation"}}]},
            {"samplers": [{"input": times, "output": quat_cubic, "interpolation": "CUBICSPLINE"}],
             "channels": [{"sampler": 0, "target": {"node": 1, "path": "rotation"}}]},
        ],
        "buffers": [{"byteLength": len(binary), "uri": "data:application/octet-stream;base64," + base64.b64encode(binary).decode()}],
        "bufferViews": views, "accessors": accessors,
    }
    return json.dumps(document).encode()


class Agreement(unittest.TestCase):
    def setUp(self):
        result = inspect_asset(fixture(), "gltf")
        self.assertTrue(result.ok, result.report.to_dict())
        self.snapshot = result.value

    def compare(self, morph, quaternion, *, animation=None, time=0, manual=True):
        kwargs = {"timestamp": time, "animation_id": animation}
        if manual:
            kwargs["morph_weights"] = {0: [morph], 2: [morph]}
        result = evaluate_geometry(self.snapshot, **kwargs)
        self.assertTrue(result.ok, result.report.to_dict())
        instances = result.value.to_dict()["instances"]
        by_node = {item["node"]: item for item in instances}
        for node, translation in ((0,1), (2,3)):
            # The first animation only drives node 0's weights.
            weight = morph if manual or node == 0 else 0
            morphed = native.morph_positions([[1,0,0]], [[[0,1,0]]], [weight])
            world = native.compose_trs([translation,0,0], [0,0,0,1], [1,1,1])
            joint = native.compose_trs([0,0,0], quaternion, [1,1,1])
            expected = native.skin_positions(morphed, [[0,0,0,0]], [[1,0,0,0]],
                                             world, [joint], [native.identity()])[0]
            actual = by_node[node]["primitives"][0]["positions"][0]
            for a, b in zip(actual, expected):
                self.assertLessEqual(abs(a-b), 1e-9 + 1e-8 * abs(b))

    def test_signed_and_large_weights_per_instance(self):
        for weight in (-.5, 0, .25, 2):
            with self.subTest(weight=weight):
                self.compare(weight, [0,0,math.sqrt(.5),math.sqrt(.5)])

    def test_hermite_duration_and_intermediate_samples(self):
        for time in (0, .25, .5, 1, 1.75, 2):
            morph = native.hermite([0], [2], [0], [0], time/2, 2)[0]
            with self.subTest(time=time):
                self.compare(morph, [0,0,math.sqrt(.5),math.sqrt(.5)], animation=0, time=time, manual=False)

    def test_quaternion_linear_and_cubic(self):
        for time in (0, .5, 1, 1.5, 2):
            for animation in (1,2):
                q = (native.slerp([0,0,0,1], [0,0,1,0], time/2) if animation == 1 else
                     native.hermite([0,0,0,1], [0,0,2,0], [0,0,1,0], [0,0,0,0], time/2, 2, True))
                with self.subTest(time=time, animation=animation):
                    self.compare(.5, q, animation=animation, time=time)

    def test_native_ownership_and_invalid_sample(self):
        domain = native.Domain(); domain.minimum=0; domain.maximum=1
        rule = native.Instruction(); rule.inputs=[0,1]; rule.output=2
        rule.operation=native.Operator.weighted_sum; rule.weights=[.5,.5]
        program = native.ScalarProgram(); program.domains=[domain,domain,domain]; program.instructions=[rule]
        values = [1,0,0]
        output = native.evaluate_scalars(program, values, [True,True,False])
        values[0]=0; rule.weights=[2,2]
        self.assertEqual(output, [1,0,.5])
        self.assertEqual(native.evaluate_scalars(program, [1,0,0], [True,True,False]), [1,0,.5])
        with self.assertRaises(ValueError):
            native.evaluate_scalars(program, [1,0,0], [False,True,False])

    def test_public_mapping_matches_native_scalars(self):
        signals = [{"id": name, "label": name, "value_type": "scalar", "units": "1",
                    "domain": {"min": 0, "max": 1}, "calibration": "fixture common normalized scale",
                    "disposition": "mapped", "evidence": ["original"], "evidence_status": "proposed"}
                   for name in ("left", "right", "shared")]
        document = {"schema_version": "1.0", "data_version": "0.1.0", "operator_version": "1.0",
                    "id": "native.agreement", "license": "CC-BY-SA-4.0", "signals": signals,
                    "profiles": [{"id": "source", "label": "Source", "signal_ids": ["left", "right"]},
                                 {"id": "target", "label": "Target", "signal_ids": ["shared"]}],
                    "evidence": [{"id": "original", "claim": "Original bilateral fixture",
                                  "status": "proposed", "license": "CC-BY-SA-4.0", "authorship": "MSF Tools contributors"}],
                    "mappings": [{"id": "mean", "rules": [{"id": "collapse", "inputs": ["left", "right"],
                        "outputs": ["shared"], "operator": {"id": "weighted_sum", "weights": [.5,.5]},
                        "disposition": "mapped", "mapping_quality": "approximate",
                        "assumptions": ["Same authored scale; asymmetric inputs cannot be recovered"],
                        "evidence": ["original"], "evidence_status": "proposed",
                        "loss_annotations": [{"category": "signal", "effect": "approximated", "reason": "bilateral collapse",
                                              "refs": ["left", "right", "shared"], "units": "1"}]}]}]}
        validated = validate_authoring(document)
        self.assertTrue(validated.ok, validated.report.to_dict())
        pack = compile_pack(validated.value).value
        source = profile_snapshot(pack, "source").value
        target = profile_snapshot(pack, "target").value
        compiled = compile_mapping(pack, source, target, "mean", allow_approximation=True)
        self.assertTrue(compiled.ok, compiled.report.to_dict())
        domain = native.Domain(); domain.minimum=0; domain.maximum=1
        rule = native.Instruction(); rule.inputs=[0,1]; rule.output=2
        rule.operation=native.Operator.weighted_sum; rule.weights=[.5,.5]
        program = native.ScalarProgram(); program.domains=[domain]*3; program.instructions=[rule]
        for left, right in ((1,0), (0,1), (.25,.75), (1,1), (0,0)):
            result = evaluate_mapping(compiled.value, [{"timestamp": .5,
                "values": {"left": left, "right": right}, "validity": {"left": True, "right": True}}])
            self.assertTrue(result.ok, result.report.to_dict())
            self.assertAlmostEqual(result.value.to_dict()["samples"][0]["values"]["shared"],
                                   native.evaluate_scalars(program, [left,right,0], [True,True,False])[2])

    def test_singular_and_shear_rejected(self):
        singular = native.identity(); singular[0]=0
        with self.assertRaises(ValueError): native.inverse(singular)
        shear = native.identity(); shear[1]=.25
        with self.assertRaises(ValueError): native.reparent_local(native.identity(), shear)

    def test_combined_fixture_four_nonzero_influences(self):
        path = __import__("pathlib").Path(__file__).resolve().parents[2] / "tests/fixtures/combined.gltf"
        snapshot = inspect_asset(path.read_bytes(), "gltf")
        self.assertTrue(snapshot.ok, snapshot.report.to_dict())
        snapshot = snapshot.value
        doc = snapshot.document
        parents = {child: index for index, node in enumerate(doc["nodes"]) for child in node.get("children", ())}

        def accessor(index):
            result = decode_accessor(snapshot, index)
            self.assertTrue(result.ok, result.report.to_dict())
            return result.value

        for time in (0, .25, .5, 1, 1.5, 1.75, 2, 3):
            animation = sample_animation(snapshot, 0, time)
            self.assertTrue(animation.ok, animation.report.to_dict())
            worlds = {}

            def world(index):
                if index not in worlds:
                    node = dict(doc["nodes"][index]); node.update(animation.value.get(index, {}))
                    local = (native.from_gltf_column_major(node["matrix"]) if "matrix" in node else native.compose_trs(
                        node.get("translation", [0,0,0]), node.get("rotation", [0,0,0,1]), node.get("scale", [1,1,1])))
                    worlds[index] = native.multiply(world(parents[index]), local) if index in parents else local
                return worlds[index]

            evaluated = evaluate_geometry(snapshot, timestamp=time, animation_id=0)
            self.assertTrue(evaluated.ok, evaluated.report.to_dict())
            for instance in evaluated.value.to_dict()["instances"]:
                index = instance["node"]; node = doc["nodes"][index]; mesh = doc["meshes"][node["mesh"]]
                skin = doc["skins"][node["skin"]]
                joint_worlds = [world(joint) for joint in skin["joints"]]
                ibms = [native.from_gltf_column_major(value) for value in accessor(skin["inverseBindMatrices"])]
                weights = animation.value.get(index, {}).get("weights", node.get("weights", mesh["weights"]))
                for actual in instance["primitives"]:
                    primitive = mesh["primitives"][actual["primitive"]]
                    basis = accessor(primitive["attributes"]["POSITION"])
                    deltas = [accessor(target["POSITION"]) for target in primitive["targets"]]
                    morphed = native.morph_positions(basis, deltas, weights)
                    js = accessor(primitive["attributes"]["JOINTS_0"])
                    ws = accessor(primitive["attributes"]["WEIGHTS_0"])
                    self.assertTrue(all(sum(weight > 0 for weight in row) == 4 for row in ws))
                    expected = native.skin_positions(morphed, js, ws, world(index), joint_worlds, ibms)
                    for a, b in zip(actual["positions"], expected):
                        for x, y in zip(a, b):
                            self.assertLessEqual(abs(x-y), 1e-9 + 1e-8 * abs(y))


if __name__ == "__main__":
    unittest.main()
