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
        # The wheel's extension links nanobind (BSD-3-Clause), vendors Ryu (BSL-1.0), fast_float and ufbx (MIT) and derives
        # hypot and fsum from CPython (PSF-2.0); docs/, schemas/ (in the sdist) and the README (the long description,
        # in both) are CC-BY-SA-4.0; see NOTICE.md.
        self.assertEqual(project['license'], 'MIT AND BSD-3-Clause AND BSL-1.0 AND PSF-2.0 AND CC-BY-SA-4.0')
        self.assertIn('LICENSES/ufbx-MIT.txt', project['license-files'])
        self.assertIn('LICENSES/CC-BY-SA-4.0.txt', project['license-files'])
        for path in project['license-files']:
            self.assertTrue((ROOT / path).is_file(), path)


if __name__ == '__main__':
    unittest.main()
