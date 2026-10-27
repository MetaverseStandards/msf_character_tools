# SPDX-License-Identifier: MIT
"""Packaging metadata: the version is stated once per place and has a CHANGELOG section."""
from pathlib import Path
import tomllib
import unittest

import msf_tools as m

ROOT = Path(__file__).resolve().parents[2]


class PackageMetadata(unittest.TestCase):
    def test_versions_agree_and_licences_are_spdx_expressions(self):
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
        self.assertEqual(project['version'], m.__version__)
        self.assertIn(f'## {m.__version__}', (ROOT / 'CHANGELOG.md').read_text())
        shim = tomllib.loads((ROOT / 'native' / 'ufbx' / 'pyproject.toml').read_text())['project']
        # The wheel's extension links nanobind (BSD-3-Clause) and vendors Ryu (BSL-1.0) and derives hypot and fsum from CPython (PSF-2.0); see NOTICE.md.
        self.assertEqual((project['license'], shim['license']), ('MIT AND BSD-3-Clause AND BSL-1.0 AND PSF-2.0', 'MIT'))
        for path in project['license-files']:
            self.assertTrue((ROOT / path).is_file(), path)


if __name__ == '__main__':
    unittest.main()
