# SPDX-License-Identifier: MIT
"""Source conversion in a separate reader process."""
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest import mock

import msf_character_tools as m
from msf_character_tools.report import Fault
from msf_character_tools.sources import SourceLimits, SourceParseError, _worker

from internal.adapters import fake_adapter as fake

OPTIONS = {'influences': 'faithful', 'losses': 'declare'}
MODULE = 'tests.internal.adapters.misbehaving_adapter'


def run(data, limits=SourceLimits(), **kwargs):
    return _worker.run(MODULE, data, 'usda', None, limits, OPTIONS, **kwargs)


class IsolatedConversion(unittest.TestCase):
    def fault(self, data, **kwargs):
        with self.assertRaises(Fault) as caught:
            run(data, **kwargs)
        return caught.exception.diagnostic

    def test_isolated_conversion_matches_in_process(self):
        data = fake.source(fake.scene(dependencies=[]))
        generated, identity = run(b'stdout:' + data)
        self.assertEqual(generated, fake.ADAPTER.convert(data, 'usda', None, SourceLimits(), OPTIONS))
        self.assertEqual(identity, ('msf-fake', '1', 'misbehaving 1'))

    def test_reader_faults_and_parse_errors_cross_the_process_boundary(self):
        diagnostic = self.fault(b'fault')
        self.assertEqual((diagnostic.code, diagnostic.ref, diagnostic.message, diagnostic.remediation),
                         ('E_SOURCE_REFERENCE', '/Root', 'Layer path @/etc/x.usda@ is not relative.', 'Use relative paths.'))
        with self.assertRaises(SourceParseError) as caught:
            run(b'parse')
        self.assertEqual(str(caught.exception), 'line 1: unexpected token')

    def test_hung_and_crashed_readers_are_refused(self):
        self.assertEqual(self.fault(b'sleep', timeout=0.3).code, 'E_SOURCE_TIMEOUT')
        self.assertIn('signal 9', self.fault(b'kill').message)
        crashed = self.fault(b'exit')
        self.assertEqual(crashed.code, 'E_SOURCE_CRASHED')
        self.assertIn('reader gave up on the source', crashed.message)

    def test_reader_memory_is_watched(self):
        diagnostic = self.fault(b'hog', limits=SourceLimits(max_reader_memory=256 << 20), timeout=5)
        self.assertEqual(diagnostic.code, 'E_SOURCE_MEMORY')
        self.assertGreater(_worker.footprint(os.getpid()), 1 << 20)
        self.assertEqual(_worker.linux_footprint('Name:\tpython\nVmRSS:\t  2048 kB\nVmSwap:\t   512 kB\n'), 2560 * 1024)
        self.assertIsNone(_worker.linux_footprint('Name:\tzombie\n'))

    def test_the_whole_process_group_is_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = os.path.join(tmp, 'child.pid')
            self.assertEqual(self.fault(b'spawn:' + record.encode(), timeout=0.5).code, 'E_SOURCE_TIMEOUT')
            with open(record) as handle:
                child = int(handle.read())
        for _ in range(100):  # the orphaned child is reaped by init shortly after it dies
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            self.fail('the reader process left a child running')

    def test_a_parent_exception_still_reaps_the_reader(self):
        seen = []

        def interrupt(pid):
            seen.append(pid)
            raise KeyboardInterrupt

        with mock.patch.object(_worker, 'footprint', interrupt), self.assertRaises(KeyboardInterrupt):
            run(b'sleep')
        with self.assertRaises(ProcessLookupError):
            os.kill(seen[0], 0)

    def test_isolated_reads_count_against_the_resolver_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'layers').mkdir()
            (root / 'layers' / 'sub.usda').write_bytes(b'#usda 1.0\n' + b' ' * 590)
            resolver = m.LocalResolver(root, max_total_bytes=1000)
            data = fake.source(fake.scene())
            _worker.run(MODULE, data, 'usda', resolver, SourceLimits(), OPTIONS)
            with self.assertRaises(Fault) as caught:
                _worker.run(MODULE, data, 'usda', resolver, SourceLimits(), OPTIONS)
        self.assertEqual(caught.exception.diagnostic.code, 'E_RESOURCE_LIMIT')

    def test_malformed_worker_responses_are_protocol_errors(self):
        good = _worker.frame({'protocol': _worker.PROTOCOL, 'ok': True, 'adapter': ['a', '1', 'r 1'], 'node_paths': ['/A'],
                              'target_keys': [], 'dependencies': [], 'losses': [], 'glb_length': 4}, b'glTF')
        self.assertEqual(_worker.parse_response(good, SourceLimits())[0].node_paths, ('/A',))
        header_length = struct.unpack_from('>Q', good)[0]
        for raw in (b'', good[:5], good[:-1], good + b'x', struct.pack('>Q', 2 ** 40) + good[8:],
                    _worker.frame({'protocol': 'other/1'}, b''), struct.pack('>Q', 3) + b'{x}',
                    good.replace(b'"node_paths":["/A"]', b'"node_paths":[7]'),
                    good.replace(b'"losses":[]', b'"losses":[{"code":"W_X"}]'),
                    good.replace(b'"ok":true', b'"ok":false')):
            with self.subTest(raw=raw[:60]), self.assertRaises(Fault) as caught:
                _worker.parse_response(raw, SourceLimits())
            self.assertEqual(caught.exception.diagnostic.code, 'E_SOURCE_PROTOCOL')
        self.assertGreater(header_length, 0)


class IsolateKeyword(unittest.TestCase):
    def codes(self, result):
        return [(d.code, d.ref) for d in result.report.diagnostics]

    def test_isolate_is_checked_and_needs_a_local_resolver(self):
        data = fake.source(fake.scene(dependencies=[]))
        self.assertEqual(self.codes(m.inspect_asset(data, 'usda', resolver=lambda uri: b'', isolate=True)),
                         [('E_ISOLATE_RESOLVER', '/')])
        self.assertEqual(self.codes(m.inspect_asset(data, 'usda', isolate='yes')), [('E_SOURCE_OPTIONS', '/isolate')])
        gltf = m.inspect_asset(b'{"asset":{"version":"2.0"}}', 'gltf', isolate=True)
        self.assertEqual(self.codes(gltf), [('E_SOURCE_OPTIONS', '/')])
        self.assertTrue(m.inspect_asset(b'{"asset":{"version":"2.0"}}', 'gltf', isolate=False).ok)


if __name__ == '__main__':
    unittest.main()
