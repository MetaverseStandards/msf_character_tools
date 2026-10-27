# SPDX-License-Identifier: MIT
"""A source adapter for isolation tests; the source bytes say how to misbehave."""
import os
import signal
import sys
import time

from msf_tools.report import fail
from msf_tools.sources import SourceParseError

from . import fake_adapter


class MisbehavingAdapter:
    name = 'msf-misbehaving'
    version = '1'
    formats = ('usda',)

    def reader(self):
        return 'misbehaving 1'

    def convert(self, data, fmt, resolver, limits, options):
        if data == b'sleep':
            time.sleep(30)
        if data == b'kill':
            # SIGKILL rather than abort(), so the test leaves no crash report behind.
            os.kill(os.getpid(), signal.SIGKILL)
        if data == b'exit':
            sys.stderr.write('reader gave up on the source\n')
            sys.exit(3)
        if data == b'parse':
            raise SourceParseError('line 1: unexpected token')
        if data == b'fault':
            fail('E_SOURCE_REFERENCE', '/Root', 'Layer path @/etc/x.usda@ is not relative.', 'Use relative paths.')
        if data.startswith(b'stdout:'):
            os.write(1, b'stray output from a reader library\n')
            data = data[len(b'stdout:'):]
        return fake_adapter.ADAPTER.convert(data, fmt, resolver, limits, options)


ADAPTER = MisbehavingAdapter()
