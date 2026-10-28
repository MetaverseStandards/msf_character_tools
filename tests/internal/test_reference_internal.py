# SPDX-License-Identifier: MIT
"""Geometry budgets, checked by lowering the private component cap."""
from unittest.mock import patch

import msf_character_tools as m
from msf_character_tools import geometry
from test_reference import Checks, FIX, asset, instanced_points


class GeometryTests(Checks):
    def assert_instance_budget_refusal(self, r):
        self.assertEqual([(d.code,d.ref) for d in r.report.diagnostics],[("E_RESOURCE_LIMIT","/nodes")])
        self.assertIsNone(r.value)

    def test_instance_component_budget_threshold(self):
        # Four one-vertex instances, or two with one morph target, need 12 position components.
        for doc in (instanced_points((1,4)),instanced_points((1,2,1)),instanced_points((2,1),(1,2))):
            s=self.good(asset(doc))
            for cap in (13,12):
                with self.subTest(doc=doc,cap=cap),patch.object(geometry,"MAX_EVALUATION_COMPONENTS",cap):
                    self.assertEqual(len(self.good(m.evaluate_geometry(s)).instances),len(doc["nodes"]))
            with self.subTest(doc=doc,cap=11),patch.object(geometry,"MAX_EVALUATION_COMPONENTS",11):
                self.assert_instance_budget_refusal(m.evaluate_geometry(s))

    def test_shared_skin_is_counted_once(self):
        # Two instances x 6 vertices x 3 x (1 + 3 targets) = 144, plus 2 x 6 vertices x 8 joint and weight
        # components = 96, plus 16 x 4 joints for the one shared skin.
        s=self.good(m.inspect_asset((FIX/"combined.gltf").read_bytes(),"gltf"))
        with patch.object(geometry,"MAX_EVALUATION_COMPONENTS",304):
            self.good(m.evaluate_geometry(s,animation_id=0,timestamp=.5))
        with patch.object(geometry,"MAX_EVALUATION_COMPONENTS",303):
            self.assert_instance_budget_refusal(m.evaluate_geometry(s,animation_id=0,timestamp=.5))

    def test_budget_counts_every_influence_set(self):
        # 2 vertices x 3, plus 2 vertices x 2 sets x 8 joint and weight components, plus 16 x 8 joints.
        s=self.good(m.inspect_asset((FIX/"eight-weighted.gltf").read_bytes(),"gltf"))
        with patch.object(geometry,"MAX_EVALUATION_COMPONENTS",166):
            self.good(m.evaluate_geometry(s))
        with patch.object(geometry,"MAX_EVALUATION_COMPONENTS",165):
            self.assert_instance_budget_refusal(m.evaluate_geometry(s))

    def test_default_budget_counts_morph_targets_per_instance(self):
        # 100 vertices x 200 instances is 60,000 components; 100 targets make it 6,060,000.
        self.assert_instance_budget_refusal(m.evaluate_geometry(self.good(asset(instanced_points((100,200,100))))))
        # Evaluating each POSITION and morph-target accessor once stays within the inspection component limit.
        self.assertEqual(geometry.MAX_EVALUATION_COMPONENTS,4_000_000)
