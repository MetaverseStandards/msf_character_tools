# SPDX-License-Identifier: MIT
"""The ufbx 0.23.1 test corpus, when a local copy is present (never committed).

Set MSF_UFBX_CORPUS to an extracted ufbx source tree at the pinned commit
(26a482ae…); its data/ folder holds the FBX files. Every file must load
except those whose name marks them as expected failures (`_fail_`), and
every file must go through inspect_asset or be refused with a mapped code.
"""
import os
from pathlib import Path
import unittest

from test_source_fbx_native import HAVE_UFBX, open_scene

ROOT = Path(os.environ['MSF_UFBX_CORPUS']) if os.environ.get('MSF_UFBX_CORPUS') else None
PRESENT = HAVE_UFBX and ROOT is not None and (ROOT / 'data').is_dir()
# Fails in ufbx's own tests only because a referenced cache file is missing; msf never loads external files.
LOADS_WITHOUT_EXTERNAL_FILES = {'synthetic_missing_cache_fail_7500_ascii.fbx'}
# A 10,000-deep node chain; msf refuses hierarchies deeper than 1024 nodes.
DEEPER_THAN_THE_LIMIT = {'synthetic_id_collision_7500_ascii.fbx'}


@unittest.skipUnless(PRESENT, 'set MSF_UFBX_CORPUS to an extracted ufbx 0.23.1 source tree to run this tier')
class UfbxCorpus(unittest.TestCase):
    def test_corpus_loads_except_expected_failures(self):
        from msf_tools_ufbx import lib
        unexpected = []
        files = sorted((ROOT / 'data').glob('*.fbx'))
        for path in files:
            handle, err = open_scene(path.read_bytes())
            if handle is not None:
                lib.msf_fbx_close(handle)
            expected_failure = ('_fail_' in path.name and path.name not in LOADS_WITHOUT_EXTERNAL_FILES
                                or path.name in DEEPER_THAN_THE_LIMIT)
            if (handle is None) != expected_failure:
                unexpected.append((path.name, err))
        self.assertGreater(len(files), 600)
        self.assertEqual(unexpected, [])

    def test_corpus_inspects_or_refuses_with_a_mapped_code(self):
        import msf_tools as m
        outcomes, unexpected = {}, []
        for path in sorted((ROOT / 'data').glob('*.fbx')):
            result = m.inspect_asset(path.read_bytes(), 'fbx')
            code = 'ok' if result.ok else result.report.diagnostics[0].code
            outcomes[code] = outcomes.get(code, 0) + 1
            # Unreadable files, NaN or singular transforms, and animations too long to sample are refused by design.
            if code not in ('ok', 'E_SOURCE_PARSE', 'E_SOURCE_VALUE', 'E_RESOURCE_LIMIT'):
                unexpected.append((path.name, code, result.report.diagnostics[0].message))
        self.assertEqual(unexpected, [])
        self.assertGreater(outcomes['ok'], 650, outcomes)


if __name__ == '__main__':
    unittest.main()
