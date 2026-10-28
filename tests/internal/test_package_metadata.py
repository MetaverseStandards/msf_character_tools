# SPDX-License-Identifier: MIT
"""Packaging metadata: the version is stated once per place and has a CHANGELOG section; vendored code is pinned."""
import hashlib
import json
import re
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

    def test_every_vendored_file_matches_its_source_lock_pin(self):
        pins = {}
        for entry in json.loads((ROOT / 'docs/source-lock.json').read_text()):
            pins.update(entry.get('vendored', {}))
        vendored = {str(p.relative_to(ROOT)) for p in (ROOT / 'core/third_party').rglob('*') if p.is_file()}
        self.assertEqual(sorted(vendored - set(pins)), [])
        for name, digest in pins.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)

    def test_release_build_requirements_pin_the_build_system_with_hashes(self):
        requires = tomllib.loads((ROOT / 'pyproject.toml').read_text())['build-system']['requires']
        text = (ROOT / 'scripts/build-requirements.txt').read_text()
        lines = [line for line in text.splitlines() if line and not line.startswith('#')]
        pins = [line.removesuffix(' \\') for line in lines if not line.startswith(' ')]
        self.assertTrue(set(requires) <= set(pins), pins)
        for pin in pins:
            self.assertRegex(text, rf'(?m)^{re.escape(pin)} \\\n    --hash=sha256:[0-9a-f]{{64}}')
            self.assertRegex(pin, r'^[a-z0-9-]+==[0-9.]+$')


if __name__ == '__main__':
    unittest.main()
