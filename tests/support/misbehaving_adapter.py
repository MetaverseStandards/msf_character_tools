# SPDX-License-Identifier: MIT
"""A source adapter for isolation tests; the source bytes say how to misbehave."""
import os
import signal
import subprocess
import sys
import time

from msf_tools.report import fail
from msf_tools.sources import SourceParseError

from . import fake_adapter


class MisbehavingAdapter:
    name = 'msf-fake'  # the GLB comes from the fake adapter, whose generator names it
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
        if data == b'hog':
            chunks = []
            for _ in range(32):  # stops at 1 GiB if nothing kills the process first
                chunks.append(b'\x01' * (32 << 20))
                time.sleep(0.01)
            time.sleep(30)
        if data.startswith(b'spawn:'):
            child = subprocess.Popen(['sleep', '30'])
            with open(data[len(b'spawn:'):], 'w') as handle:
                handle.write(str(child.pid))
            time.sleep(30)
        if data == b'parse':
            raise SourceParseError('line 1: unexpected token')
        if data == b'fault':
            fail('E_SOURCE_REFERENCE', '/Root', 'Layer path @/etc/x.usda@ is not relative.', 'Use relative paths.')
        directive = fake_adapter.MAGIC + b'pid:'
        if data.startswith(directive):
            record, _, rest = data[len(directive):].partition(b'\n')
            data = fake_adapter.MAGIC + rest
            with open(record, 'w') as handle:
                handle.write(str(os.getpid()))
        if data.startswith(b'stdout:'):
            os.write(1, b'stray output from a reader library\n')
            data = data[len(b'stdout:'):]
        return fake_adapter.ADAPTER.convert(data, fmt, resolver, limits, options)


ADAPTER = MisbehavingAdapter()
