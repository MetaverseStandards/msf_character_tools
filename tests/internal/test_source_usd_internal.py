# SPDX-License-Identifier: MIT
"""USD inspection through private adapter hooks and source limits."""
from pathlib import Path
import tempfile
import unittest
import unittest.mock
import zipfile

import msf_tools as m
from msf_tools.sources import SourceLimits
from support.values import plain
from test_source_usd import HAVE_USD, REF, ROOT_WITH_SUBLAYER, SUB, good, layer, usdz


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdDependencies(unittest.TestCase):
    files = {'parts/sub.usda': SUB, 'parts/ref.usda': REF}

    def errors(self, result):
        return [(d.code, d.ref) for d in result.report.diagnostics if d.severity == 'error']

    def clip_on_variant(self, host):
        (host / 'clip.usda').write_text('#usda 1.0\nover "A" {\n    double3 xformOp:translate.timeSamples = {\n        0: (5, 0, 0),\n'
                                        '    }\n    uniform token[] xformOpOrder = ["xformOp:translate"]\n}\n')
        # Ivo's probe: clips authored on the variant spec itself, naming a host file outside the resolver root.
        return (f'#usda 1.0\ndef Xform "A" (\n    variants = {{\n        string v = "x"\n    }}\n    prepend variantSets = "v"\n)\n{{\n'
                f'    variantSet "v" = {{\n        "x" (\n            clips = {{\n                dictionary default = {{\n'
                f'                    asset[] assetPaths = [@{host}/clip.usda@]\n                    string primPath = "/A"\n'
                f'                    double2[] active = [(0, 0)]\n                    double2[] times = [(0, 0)]\n                }}\n'
                f'            }}\n        ) {{\n            double3 xformOp:translate\n'
                f'            uniform token[] xformOpOrder = ["xformOp:translate"]\n        }}\n    }}\n}}\n').encode()

    def test_layers_loaded_from_outside_the_materialized_folder_are_refused(self):
        from msf_tools.sources import usd
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(usd, '_refuse_clips', lambda layer: None):
            host = Path(tmp).resolve()
            result = m.inspect_asset(self.clip_on_variant(host), 'usda', resolver=m.LocalResolver(host))
        self.assertEqual(self.errors(result), [('E_SOURCE_REFERENCE', '/')])
        self.assertIn('outside', result.report.diagnostics[0].message)

    def test_dependency_limits_apply_while_fetching(self):
        fetched = []
        def resolver(uri):
            fetched.append(uri)
            return self.files[uri]
        result = m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=resolver, limits=SourceLimits(max_dependencies=1))
        self.assertEqual(self.errors(result), [('E_RESOURCE_LIMIT', '/source/dependencies')])
        self.assertEqual(len(fetched), 2)
        result = m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=self.files.__getitem__,
                                 limits=SourceLimits(max_dependency_bytes=len(SUB) + len(REF) - 1))
        self.assertEqual(self.errors(result), [('E_RESOURCE_LIMIT', '/source/dependencies')])

    def test_unsafe_usdz_archives_are_refused(self):
        root = layer('def Xform "Root" {}\n')
        for package in (usdz([('root.usda', root)], compress=zipfile.ZIP_DEFLATED), usdz([('root.usda', root)], encrypt=True),
                        usdz([('root.usda', root), ('../escape.usda', SUB)]), usdz([('root.usda', root), ('/abs.usda', SUB)]),
                        usdz([('root.usda', root), ('a\\b.usda', SUB)]), usdz([('root.usda', root), ('root.usda', root)]),
                        b'PK\x03\x04not a zip'):
            with self.subTest(package=package[:40]):
                self.assertEqual(self.errors(m.inspect_asset(package, 'usdz')), [('E_USDZ_ARCHIVE', '/')])
        many = usdz([('root.usda', root), ('a.usda', SUB), ('b.usda', SUB)])
        self.assertEqual(self.errors(m.inspect_asset(many, 'usdz', limits=SourceLimits(max_usdz_members=2))), [('E_USDZ_ARCHIVE', '/')])
        self.assertTrue(m.inspect_asset(many, 'usdz', limits=SourceLimits(max_usdz_members=3)).ok)


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdAnimation(unittest.TestCase):
    def codes(self, snapshot):
        return [(d['code'], d['ref']) for d in plain(snapshot.source['losses'])]

    def test_the_animation_value_limit_counts_time_codes_joints_and_blend_channels(self):
        # rig.usda: 3 time codes x (2 joints x 16 matrix values + 1 blend weight) = 99 values.
        data = (Path(__file__).resolve().parents[1] / 'public' / 'fixtures' / 'source' / 'rig.usda').read_bytes()
        good(m.inspect_asset(data, 'usda', limits=SourceLimits(max_animation_values=99)))
        result = m.inspect_asset(data, 'usda', limits=SourceLimits(max_animation_values=98))
        self.assertEqual([(d.code, d.ref) for d in result.report.diagnostics], [('E_RESOURCE_LIMIT', '/')])
        self.assertIn('max_animation_values', result.report.diagnostics[0].remediation)

    def test_the_limit_is_checked_before_any_pose_is_sampled(self):
        from msf_tools.sources import usd
        data = (Path(__file__).resolve().parents[1] / 'public' / 'fixtures' / 'source' / 'rig.usda').read_bytes()
        with unittest.mock.patch.object(usd, '_skeleton_poses', side_effect=AssertionError('sampled before the limit check')):
            result = m.inspect_asset(data, 'usda', isolate=False, limits=SourceLimits(max_animation_values=98))
        self.assertEqual([d.code for d in result.report.diagnostics], ['E_RESOURCE_LIMIT'])


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class UsdIsolated(unittest.TestCase):
    def test_isolated_reader_matches_in_process_with_a_local_resolver(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'parts').mkdir()
            for uri, payload in UsdDependencies.files.items():
                (root / uri).write_bytes(payload)
            local = good(m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=m.LocalResolver(root)))
            isolated = good(m.inspect_asset(ROOT_WITH_SUBLAYER, 'usda', resolver=m.LocalResolver(root), isolate=True))
        self.assertEqual(m.canonical_json(isolated.to_dict()), m.canonical_json(local.to_dict()))
        self.assertEqual(len(isolated.source['dependencies']), 2)


if __name__ == '__main__':
    unittest.main()
