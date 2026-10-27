# SPDX-License-Identifier: MIT
"""The 0.3.0 pure-Python oracle, out of process, for differential tests.

`differ(cases)` evaluates each (expression, names) case here and in the oracle
venv (MSF_ORACLE_PYTHON, default $MSF/_tools/oracle-venv) and returns the
cases whose outcomes differ. Both sides encode outcomes with the code in
ENCODER: values with their exact types (floats by bit pattern), faults by
diagnostic, other exceptions by type, Results by value and report. Messages
of E_INPUT and E_INTERNAL diagnostics are not compared; every other registry
code must match in code, ref, message and remediation.

Expressions see `m` (msf_tools), `h` (msf_tools.math3d) and `math`.
"""
import atexit
import os
from pathlib import Path
import pickle
import struct
import subprocess
import sys

MSF = Path(os.environ.get('MSF', Path.home() / '.local/share/msf'))
PYTHON = Path(os.environ.get('MSF_ORACLE_PYTHON', MSF / '_tools/oracle-venv/bin/python'))
REQUIRED = os.environ.get('MSF_REQUIRE_ORACLE') == '1'
AVAILABLE = PYTHON.exists()

ENCODER = r'''
import math, struct
from types import MappingProxyType
import msf_tools as m
from msf_tools import math3d as h
from msf_tools.report import Fault, Result, Report, Diagnostic, Loss

LOOSE = {'E_INPUT', 'E_INTERNAL'}

def diagnostic(d):
    if d.code in LOOSE:
        return (d.code, d.severity, d.ref)
    return (d.code, d.severity, d.ref, d.message, d.remediation)

def encode(value):
    t = type(value)
    if t is float:
        return ('float', struct.pack('>d', value))
    if value is None or t in (bool, int, str, bytes):
        return (t.__name__, value)
    if t in (tuple, list):
        return (t.__name__, [encode(v) for v in value])
    if t in (dict, MappingProxyType):
        return (t.__name__, [(encode(k), encode(v)) for k, v in value.items()])
    if t is Result:
        return ('Result', encode(value.value), encode(value.report))
    if t is Report:
        return ('Report', [diagnostic(d) for d in value.diagnostics], [encode(x.to_dict()) for x in value.losses])
    if t is Diagnostic:
        return ('Diagnostic', diagnostic(value))
    if hasattr(value, 'to_dict'):
        return ('record', t.__name__, encode(value.to_dict()))
    return ('object', t.__name__)

def outcome(expression, names):
    try:
        return ('value', encode(eval(expression, {'m': m, 'h': h, 'math': math}, dict(names))))
    except Fault as exc:
        return ('fault', diagnostic(exc.diagnostic))
    except Exception as exc:
        return ('error', type(exc).__name__)
'''

SERVER = ENCODER + r'''
import pickle, sys
read, write = sys.stdin.buffer, sys.stdout.buffer
while True:
    header = read.read(8)
    if len(header) < 8:
        break
    cases = pickle.loads(read.read(struct.unpack('>Q', header)[0]))
    data = pickle.dumps([outcome(e, n) for e, n in cases], protocol=4)
    write.write(struct.pack('>Q', len(data)) + data)
    write.flush()
'''

_local = {}
exec(compile(ENCODER, 'oracle.ENCODER', 'exec'), _local)
outcome = _local['outcome']
_process = None


def _start():
    global _process
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'MSF_TOOLS'))}
    _process = subprocess.Popen([str(PYTHON), '-I', '-c', SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                cwd='/', env=env)
    atexit.register(_process.kill)


# Started on import, so the oracle boots while other tests run.
if AVAILABLE:
    _start()


def _oracle(cases):
    if _process is None:
        _start()
    data = pickle.dumps(list(cases), protocol=4)
    _process.stdin.write(struct.pack('>Q', len(data)) + data)
    _process.stdin.flush()
    header = _process.stdout.read(8)
    if len(header) < 8:
        raise RuntimeError(f'the oracle at {PYTHON} exited')
    return pickle.loads(_process.stdout.read(struct.unpack('>Q', header)[0]))


def differ(cases):
    """[(case, ours, oracle)] for every case whose outcomes differ."""
    cases = list(cases)
    theirs = _oracle(cases)
    ours = [outcome(e, n) for e, n in cases]
    return [(c, a, b) for c, a, b in zip(cases, ours, theirs) if a != b]


def skip_reason():
    """Why differential tests cannot run, or None."""
    if AVAILABLE:
        return None
    if REQUIRED:
        raise RuntimeError(f'MSF_REQUIRE_ORACLE=1 but there is no oracle Python at {PYTHON}')
    return f'no 0.3.0 oracle at {PYTHON}'
