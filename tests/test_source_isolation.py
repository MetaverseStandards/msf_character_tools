# SPDX-License-Identifier: MIT
"""Source conversion in a separate reader process."""
import struct
import unittest

from msf_tools.report import Fault
from msf_tools.sources import SourceLimits, SourceParseError, _worker

from support import fake_adapter as fake

OPTIONS = {'influences': 'faithful', 'losses': 'declare'}
MODULE = 'tests.support.misbehaving_adapter'


def run(data, **kwargs):
    return _worker.run(MODULE, data, 'usda', None, SourceLimits(), OPTIONS, **kwargs)


class IsolatedConversion(unittest.TestCase):
    def fault(self, data, **kwargs):
        with self.assertRaises(Fault) as caught:
            run(data, **kwargs)
        return caught.exception.diagnostic

    def test_isolated_conversion_matches_in_process(self):
        data = fake.source(fake.scene(dependencies=[]))
        generated, identity = run(b'stdout:' + data)
        self.assertEqual(generated, fake.ADAPTER.convert(data, 'usda', None, SourceLimits(), OPTIONS))
        self.assertEqual(identity, ('msf-misbehaving', '1', 'misbehaving 1'))

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


if __name__ == '__main__':
    unittest.main()
