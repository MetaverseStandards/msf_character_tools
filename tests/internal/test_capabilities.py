# SPDX-License-Identifier: MIT
"""A required format whose reader fails to load fails the public suite instead of skipping it."""
import os
import unittest
from unittest.mock import patch

from msf_character_tools import snapshot as snapshots
from support import capabilities

BROKEN = 'internal.adapters.adapter_missing_reader'


class RequiredFormats(unittest.TestCase):
    def setUp(self):
        broken = patch.dict(snapshots._ADAPTER_MODULES, {'fbx': BROKEN, 'usda': BROKEN})
        broken.start()
        self.addCleanup(broken.stop)

    def test_a_broken_reader_skips_only_when_not_required(self):
        with patch.dict(os.environ, {'MSF_REQUIRE_FORMATS': ''}):
            self.assertFalse(capabilities.reads('fbx'))
            self.assertFalse(capabilities.reads('usda'))
        with patch.dict(os.environ, {'MSF_REQUIRE_FORMATS': 'usd'}):
            self.assertFalse(capabilities.reads('fbx'))

    def test_a_broken_reader_fails_when_required(self):
        for required, fmt in (('fbx', 'fbx'), ('fbx,usd', 'fbx'), (' usd , fbx ', 'usda'), ('usd', 'usda')):
            with self.subTest(required=required, fmt=fmt), patch.dict(os.environ, {'MSF_REQUIRE_FORMATS': required}):
                with self.assertRaises(RuntimeError) as caught:
                    capabilities.reads(fmt)
                self.assertIn('MSF_REQUIRE_FORMATS', str(caught.exception))


class WorkingReaders(unittest.TestCase):
    def test_working_readers_pass_when_required(self):
        # USD is optional; a run that requires it already failed at import if usd-core is missing.
        with patch.dict(os.environ, {'MSF_REQUIRE_FORMATS': 'fbx,usd' if capabilities.USD else 'fbx'}):
            self.assertEqual((capabilities.reads('fbx'), capabilities.reads('usda')), (capabilities.FBX, capabilities.USD))


if __name__ == '__main__':
    unittest.main()
