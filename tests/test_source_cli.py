# SPDX-License-Identifier: MIT
"""Source formats through the command line."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from msf_tools import cli
from msf_tools import snapshot as snapshots

from support import fake_adapter as fake

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
HAVE_USD = importlib.util.find_spec('pxr') is not None


def run(*args):
    out, err = io.TextIOWrapper(io.BytesIO()), io.TextIOWrapper(io.BytesIO())
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in args])
    out.flush()
    err.flush()
    return code, out.buffer.getvalue(), json.loads(err.buffer.getvalue())


@mock.patch.dict(snapshots._ADAPTER_MODULES, {'usda': 'tests.support.misbehaving_adapter'})
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


@unittest.skipUnless(HAVE_USD, 'usd-core is not installed')
class SourceOutputAliases(unittest.TestCase):
    """Ivo's repro: inspect root.usda --resolver-root . --output layers/sub.usda overwrote the fetched layer."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / 'layers').mkdir()
        self.sub = self.root / 'layers' / 'sub.usda'
        self.sub.write_text('#usda 1.0\ndef Xform "Sub" {}\n')
        self.asset = self.root / 'root.usda'
        self.asset.write_text('#usda 1.0\n(\n    subLayers = [@layers/sub.usda@]\n)\n')

    def refused(self, output):
        code, _, report = run('inspect', self.asset, '--in-process', '--resolver-root', self.root, '--output', output)
        self.assertEqual((code, [d['code'] for d in report['diagnostics']]), (1, ['E_OUTPUT_PATH']))
        self.assertEqual(self.sub.read_text(), '#usda 1.0\ndef Xform "Sub" {}\n')

    def test_output_cannot_overwrite_a_fetched_layer(self):
        self.refused(self.sub)

    def test_output_cannot_be_a_hard_link_to_a_fetched_layer(self):
        link = self.root / 'link.json'
        os.link(self.sub, link)
        self.refused(link)

    def test_output_beside_the_layers_is_written(self):
        code, _, report = run('inspect', self.asset, '--in-process', '--resolver-root', self.root, '--output', self.root / 'out.json')
        self.assertEqual(code, 0, report)
        self.assertEqual(json.loads((self.root / 'out.json').read_bytes())['source']['dependencies'][0]['uri'], 'layers/sub.usda')


if __name__ == '__main__':
    unittest.main()
