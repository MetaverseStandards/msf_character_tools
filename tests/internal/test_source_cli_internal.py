# SPDX-License-Identifier: MIT
"""CLI source handling, through fake and misbehaving source adapters."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from msf_tools import snapshot as snapshots
from internal.adapters import fake_adapter as fake
from test_source_cli import FIXTURES, run


@mock.patch.dict(snapshots._ADAPTER_MODULES, {'usda': 'tests.internal.adapters.misbehaving_adapter'})
class SourceCommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in self.tmp.iterdir()] and None or self.tmp.rmdir())
        self.record = self.tmp / 'reader.pid'
        self.asset = self.tmp / 'face.usda'
        scene = fake.source(fake.scene(dependencies=[]))
        self.asset.write_bytes(fake.MAGIC + b'pid:' + str(self.record).encode() + b'\n' + scene[len(fake.MAGIC):])

    def reader_pid(self):
        return int(self.record.read_text())

    def test_source_suffixes_use_an_isolated_reader_unless_in_process(self):
        code, out, report = run('inspect', self.asset)
        self.assertEqual(code, 0, report)
        self.assertEqual(json.loads(out)['source']['format'], 'usda')
        self.assertNotEqual(self.reader_pid(), os.getpid())
        code, out, report = run('inspect', self.asset, '--in-process')
        self.assertEqual(code, 0, report)
        self.assertEqual(self.reader_pid(), os.getpid())

    def test_source_limits_come_from_flags(self):
        code, _, report = run('inspect', self.asset, '--in-process', '--max-source-bytes', '10')
        self.assertEqual((code, [d['code'] for d in report['diagnostics']]), (1, ['E_RESOURCE_LIMIT']))
        code, _, report = run('inspect', self.asset, '--source-timeout', '0')
        self.assertEqual((code, [d['code'] for d in report['diagnostics']]), (1, ['E_CLI_INPUT']))
        self.assertFalse(self.record.exists())

    def test_gltf_assets_ignore_source_flags(self):
        code, _, report = run('inspect', FIXTURES / 'combined.glb', '--source-timeout', '5', '--in-process')
        self.assertEqual(code, 0, report)


if __name__ == '__main__':
    unittest.main()
