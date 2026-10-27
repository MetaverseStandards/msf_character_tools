# SPDX-License-Identifier: MIT
"""Source formats through the command line."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from msf_tools import cli
from support import capabilities


FIXTURES = Path(__file__).resolve().parent / 'fixtures'
HAVE_USD = capabilities.USD


def run(*args):
    out, err = io.TextIOWrapper(io.BytesIO()), io.TextIOWrapper(io.BytesIO())
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in args])
    out.flush()
    err.flush()
    return code, out.buffer.getvalue(), json.loads(err.buffer.getvalue())


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

    def test_a_failed_source_read_writes_no_output(self):
        # The read fails after fetching layers/sub.usda, so the snapshot that would list it never exists.
        self.sub.write_text('#usda 1.0\n(\n    subLayers = [@/etc/hosts.usda@]\n)\n')
        code, _, report = run('inspect', self.asset, '--in-process', '--resolver-root', self.root, '--output', self.sub)
        self.assertEqual((code, [d['code'] for d in report['diagnostics']]), (1, ['E_SOURCE_REFERENCE']))
        self.assertEqual(self.sub.read_text(), '#usda 1.0\n(\n    subLayers = [@/etc/hosts.usda@]\n)\n')

    def test_output_beside_the_layers_is_written(self):
        code, _, report = run('inspect', self.asset, '--in-process', '--resolver-root', self.root, '--output', self.root / 'out.json')
        self.assertEqual(code, 0, report)
        self.assertEqual(json.loads((self.root / 'out.json').read_bytes())['source']['dependencies'][0]['uri'], 'layers/sub.usda')


if __name__ == '__main__':
    unittest.main()
