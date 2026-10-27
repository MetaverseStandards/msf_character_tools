# SPDX-License-Identifier: MIT
"""The ufbx 0.23.1 test corpus, when a local copy is present (never committed).

Set MSF_UFBX_CORPUS to an extracted ufbx source tree at the pinned commit
(26a482ae…); its data/ folder holds the FBX files. Every file must load
except those whose name marks them as expected failures (`_fail_`).
"""
import os
from pathlib import Path
import unittest

from test_source_fbx_native import HAVE_UFBX, open_scene

ROOT = Path(os.environ['MSF_UFBX_CORPUS']) if os.environ.get('MSF_UFBX_CORPUS') else None
PRESENT = HAVE_UFBX and ROOT is not None and (ROOT / 'data').is_dir()
# Fails in ufbx's own tests only because a referenced cache file is missing; msf never loads external files.
LOADS_WITHOUT_EXTERNAL_FILES = {'synthetic_missing_cache_fail_7500_ascii.fbx'}


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
            expected_failure = '_fail_' in path.name and path.name not in LOADS_WITHOUT_EXTERNAL_FILES
            if (handle is None) != expected_failure:
                unexpected.append((path.name, err))
        self.assertGreater(len(files), 600)
        self.assertEqual(unexpected, [])


if __name__ == '__main__':
    unittest.main()
