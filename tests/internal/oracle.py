# SPDX-License-Identifier: MIT
"""The 0.3.0 pure-Python oracle, out of process, for differential tests.

`differ(cases)` evaluates each (expression, names) case here and in the oracle
venv (MSF_ORACLE_PYTHON, default $MSF/_tools/oracle-venv) and returns the
cases whose outcomes differ. Both sides encode outcomes with the code in
ENCODER: values with their exact types (floats by bit pattern), faults by
diagnostic, other exceptions by type, Results by value and report. Messages
of E_INPUT and E_INTERNAL diagnostics are not compared; every other registry
code must match in code, ref, message and remediation.

Expressions see `m` (the package), `h` (its math3d), `math`, `attempt(thunk)`
(a thunk's encoded outcome) and whatever define() added, with the case's names
as globals so nested lambdas see them. The package is msf_character_tools here
and msf_tools, its 0.3.0 name, in the oracle.
"""
import atexit
import os
from pathlib import Path
import pickle
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
# MSF_ORACLE_PYTHON names an interpreter with msf-tools 0.3.0 installed; within a
# local workspace ($MSF) it defaults to $MSF/_tools/oracle-venv.
_default = Path(os.environ['MSF']) / '_tools/oracle-venv/bin/python' if os.environ.get('MSF') else None
PYTHON = Path(os.environ['MSF_ORACLE_PYTHON']) if os.environ.get('MSF_ORACLE_PYTHON') else _default
REQUIRED = os.environ.get('MSF_REQUIRE_ORACLE') == '1'
AVAILABLE = PYTHON is not None and PYTHON.exists()
# Set iteration order follows str hashes; with a fixed PYTHONHASHSEED, which the
# oracle inherits, both sides iterate sets alike.
SAME_HASHING = os.environ.get('PYTHONHASHSEED', 'random') != 'random'

# ENCODER runs after a line that sets PACKAGE.
ENCODER = r'''
import importlib, math, struct
from types import MappingProxyType
m = importlib.import_module(PACKAGE)
h = importlib.import_module(PACKAGE + '.math3d')
_report = importlib.import_module(PACKAGE + '.report')
Fault, Result, Report, Diagnostic, Loss = _report.Fault, _report.Result, _report.Report, _report.Diagnostic, _report.Loss

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

# Names are globals of the expression, so nested lambdas see them; define() adds helpers here.
NAMESPACE = {'m': m, 'h': h, 'math': math}

def attempt(thunk):
    try:
        return ('value', encode(thunk()))
    except Fault as exc:
        return ('fault', diagnostic(exc.diagnostic))
    except Exception as exc:
        return ('error', type(exc).__name__)

NAMESPACE.update(attempt=attempt, encode=encode)

def outcome(expression, names):
    return attempt(lambda: eval(expression, {**NAMESPACE, **names}))
'''

SERVER = "PACKAGE = 'msf_tools'\n" + ENCODER + r'''
import pickle, sys
read, write = sys.stdin.buffer, sys.stdout.buffer
while True:
    header = read.read(8)
    if len(header) < 8:
        break
    message = pickle.loads(read.read(struct.unpack('>Q', header)[0]))
    if isinstance(message, tuple) and message[0] == 'define':
        exec(message[1], NAMESPACE)
        data = pickle.dumps(None, protocol=4)
    else:
        data = pickle.dumps([outcome(e, n) for e, n in message], protocol=4)
    write.write(struct.pack('>Q', len(data)) + data)
    write.flush()
'''

_local = {}
exec(compile("PACKAGE = 'msf_character_tools'\n" + ENCODER, 'oracle.ENCODER', 'exec'), _local)
outcome = _local['outcome']
_process = None


def _start():
    global _process
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'MSF_TOOLS')) or k == 'PYTHONHASHSEED'}
    # Not -I, which would drop PYTHONHASHSEED; the environment is filtered above instead.
    _process = subprocess.Popen([str(PYTHON), '-s', '-P', '-c', SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                cwd='/', env=env)
    atexit.register(_process.kill)


# Started on import, so the oracle boots while other tests run.
if AVAILABLE:
    _start()


def _send(message):
    if _process is None:
        _start()
    data = pickle.dumps(message, protocol=4)
    _process.stdin.write(struct.pack('>Q', len(data)) + data)
    _process.stdin.flush()
    header = _process.stdout.read(8)
    if len(header) < 8:
        raise RuntimeError(f'the oracle at {PYTHON} exited')
    return pickle.loads(_process.stdout.read(struct.unpack('>Q', header)[0]))


def _oracle(cases):
    return _send(list(cases))


_defined = []


def define(source):
    """Run `source` (helper definitions) here and in the oracle; expressions can then call them."""
    if source in _defined:
        return
    exec(source, _local['NAMESPACE'])
    _send(('define', source))
    _defined.append(source)


def differ(cases, normalize=lambda outcome: outcome):
    """[(case, ours, oracle)] for every case whose outcomes differ after `normalize`."""
    cases = list(cases)
    theirs = _oracle(cases)
    ours = [outcome(e, n) for e, n in cases]
    return [(c, a, b) for c, a, b in zip(cases, ours, theirs) if normalize(a) != normalize(b)]


def skip_reason():
    """Why differential tests cannot run, or None."""
    if AVAILABLE:
        return None
    if REQUIRED:
        raise RuntimeError(f'MSF_REQUIRE_ORACLE=1 but there is no oracle Python at {PYTHON}')
    return f'no 0.3.0 oracle at {PYTHON}' if PYTHON else 'no 0.3.0 oracle (set MSF_ORACLE_PYTHON)'
