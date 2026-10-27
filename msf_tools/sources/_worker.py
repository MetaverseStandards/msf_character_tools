# SPDX-License-Identifier: MIT
"""Run a source adapter in a separate reader process (protocol msf-source-worker/1).

Both directions carry an 8-byte big-endian header length, a JSON header, then
raw bytes: the source on stdin, the generated GLB on stdout. The parent treats
everything the worker sends as untrusted; the GLB is inspected again after this.
"""
import dataclasses
import importlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time

from ..report import Diagnostic, Fault, fail
from . import Generated, SourceLimits, SourceParseError

PROTOCOL = "msf-source-worker/1"
MAX_HEADER_BYTES = 64 * 1024 * 1024
MAX_STDERR_BYTES = 1024 * 1024
POLL_SECONDS = 0.1
_LENGTH = struct.Struct(">Q")
# `-I` ignores PYTHONPATH and the working directory, so the checkout root is put on the path explicitly.
_BOOT = ("import sys, runpy; sys.path.insert(0, sys.argv[1]); "
         "runpy.run_module('msf_tools.sources._worker', run_name='__main__')")
_DIAGNOSTIC_KEYS = {"code", "severity", "ref", "message", "remediation"}


def frame(header, payload):
    text = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    return _LENGTH.pack(len(text)) + text + payload


def _unframe(raw):
    """Return (header, payload), or None when the bytes are not one well-formed frame."""
    if len(raw) < _LENGTH.size:
        return None
    length = _LENGTH.unpack_from(raw)[0]
    if length > MAX_HEADER_BYTES or _LENGTH.size + length > len(raw):
        return None
    try:
        header = json.loads(raw[_LENGTH.size:_LENGTH.size + length])
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(header, dict) or header.get("protocol") != PROTOCOL:
        return None
    return header, raw[_LENGTH.size + length:]


def _protocol(message):
    fail("E_SOURCE_PROTOCOL", "/", f"The reader process sent a malformed response: {message}",
         "Report the source file; the reader process misbehaved.")


def _strings(value):
    return isinstance(value, list) and all(type(x) is str for x in value)


def _diagnostic(value, severities):
    if not isinstance(value, dict) or set(value) != _DIAGNOSTIC_KEYS or not all(type(v) is str for v in value.values()):
        return None
    if value["severity"] not in severities:
        return None
    return Diagnostic(**value)


def parse_response(raw, limits):
    """Return (Generated, (adapter name, version, reader)) or raise the fault the worker reported."""
    unframed = _unframe(raw)
    if unframed is None:
        _protocol("the frame is not readable.")
    header, payload = unframed
    if header.get("ok") is False:
        if set(header) == {"protocol", "ok", "parse_error"} and type(header["parse_error"]) is str:
            raise SourceParseError(header["parse_error"])
        diagnostic = _diagnostic(header.get("fault"), ("error",)) if set(header) == {"protocol", "ok", "fault"} else None
        if diagnostic is None:
            _protocol("the error report is malformed.")
        fail(diagnostic.code, diagnostic.ref, diagnostic.message, diagnostic.remediation)
    keys = {"protocol", "ok", "adapter", "node_paths", "target_keys", "dependencies", "losses", "glb_length"}
    if header.get("ok") is not True or set(header) != keys:
        _protocol("the header has unexpected fields.")
    if not _strings(header["adapter"]) or len(header["adapter"]) != 3:
        _protocol("the adapter identity is malformed.")
    if (not _strings(header["node_paths"]) or not isinstance(header["target_keys"], list)
            or not all(_strings(k) for k in header["target_keys"])):
        _protocol("node paths or target keys are malformed.")
    dependencies = header["dependencies"]
    if not isinstance(dependencies, list) or not all(
            isinstance(d, list) and len(d) == 3 and type(d[0]) is str and type(d[1]) is str and type(d[2]) is int
            for d in dependencies):
        _protocol("dependencies are malformed.")
    losses = [_diagnostic(d, ("warning", "info")) for d in header["losses"]] if isinstance(header["losses"], list) else [None]
    if None in losses:
        _protocol("losses are malformed.")
    length = header["glb_length"]
    if type(length) is not int or length != len(payload) or length > limits.max_generated_bytes:
        _protocol("the GLB length does not match.")
    generated = Generated(glb=payload, node_paths=tuple(header["node_paths"]),
                          target_keys=tuple(tuple(k) for k in header["target_keys"]),
                          dependencies=tuple(tuple(d) for d in dependencies), losses=tuple(losses))
    return generated, tuple(header["adapter"])


def _resolver_spec(resolver):
    if resolver is None:
        return None
    return {"root": str(resolver.root), "max_resource_bytes": resolver.max_resource_bytes,
            "max_total_bytes": resolver.max_total_bytes}


class _Reader(threading.Thread):
    """Drain a pipe; keep at most `cap` bytes, either the head or the tail."""

    def __init__(self, pipe, cap, tail=False):
        super().__init__(daemon=True)
        self.pipe, self.cap, self.tail = pipe, cap, tail
        self.data = bytearray()
        self.overflow = False

    def run(self):
        while True:
            chunk = self.pipe.read1(1 << 16) if hasattr(self.pipe, "read1") else self.pipe.read(1 << 16)
            if not chunk:
                break
            self.data += chunk
            if len(self.data) > self.cap:
                if self.tail:
                    del self.data[:len(self.data) - self.cap]
                else:
                    self.overflow = True
                    del self.data[self.cap:]
        self.pipe.close()


def _write(pipe, payload):
    try:
        pipe.write(payload)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _kill_group(proc):
    # Only called while proc has not been reaped, so its pid (and process group) cannot have been reused.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run(module, data, fmt, resolver, limits, options, *, timeout=None):
    """Convert `data` with the adapter in `module`, in a new process; return (Generated, adapter identity)."""
    timeout = limits.timeout_s if timeout is None else timeout
    request = frame({"protocol": PROTOCOL, "adapter": module, "format": fmt, "limits": dataclasses.asdict(limits),
                     "options": dict(options), "resolver": _resolver_spec(resolver)}, data)
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR") if k in os.environ}
    env["PXR_WORK_THREAD_LIMIT"] = "1"
    root = str(Path(__file__).resolve().parents[2])
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.Popen([sys.executable, "-I", "-c", _BOOT, root], cwd=tmp, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        stdout = _Reader(proc.stdout, _LENGTH.size + MAX_HEADER_BYTES + limits.max_generated_bytes)
        stderr = _Reader(proc.stderr, MAX_STDERR_BYTES, tail=True)
        writer = threading.Thread(target=_write, args=(proc.stdin, request), daemon=True)
        for thread in (stdout, stderr, writer):
            thread.start()
        failure = None
        deadline = time.monotonic() + timeout
        while failure is None:
            try:
                proc.wait(timeout=POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() > deadline:
                failure = ("E_SOURCE_TIMEOUT", f"The reader process did not finish within {timeout:g} seconds.",
                           "Raise limits.timeout_s, or check the source for unbounded content.")
            elif stdout.overflow:
                failure = ("E_SOURCE_PROTOCOL", "The reader process sent more output than the generated-GLB limit allows.",
                           "Raise limits.max_generated_bytes, or reduce the source.")
            if failure is not None:
                _kill_group(proc)
        proc.wait()
        for thread in (stdout, stderr, writer):
            thread.join()
    if failure is not None:
        code, message, remediation = failure
        fail(code, "/", message, remediation)
    if proc.returncode != 0:
        tail = bytes(stderr.data).decode("utf-8", "replace").strip()[-512:]
        how = (f"was killed by signal {-proc.returncode}" if proc.returncode < 0 else f"exited with status {proc.returncode}")
        fail("E_SOURCE_CRASHED", "/", f"The reader process {how}." + (f" Its last output: {tail}" if tail else ""),
             "Report the source file; the reader crashed on it.")
    return parse_response(bytes(stdout.data), limits)


def _respond(out, header, payload=b""):
    out.write(frame(dict(header, protocol=PROTOCOL), payload))
    out.flush()


def main():
    # Keep a private copy of stdout for the response, and send anything a reader library prints to stderr.
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    unframed = _unframe(sys.stdin.buffer.read())
    if unframed is None:
        sys.exit("msf source worker: malformed request")
    header, data = unframed
    try:
        resolver = None
        if header["resolver"] is not None:
            from ..snapshot import LocalResolver
            resolver = LocalResolver(**header["resolver"])
        try:
            adapter = importlib.import_module(header["adapter"]).ADAPTER
        except ImportError as exc:
            fail("E_FORMAT_DEPENDENCY", "/", f"The reader process could not load its source reader: {exc}",
                 "Install the reader in the Python environment that runs msf-tools.")
        generated = adapter.convert(data, header["format"], resolver, SourceLimits(**header["limits"]), header["options"])
    except Fault as exc:
        _respond(out, {"ok": False, "fault": exc.diagnostic.to_dict()})
    except SourceParseError as exc:
        _respond(out, {"ok": False, "parse_error": str(exc)})
    else:
        _respond(out, {"ok": True, "adapter": [adapter.name, adapter.version, adapter.reader()],
                       "node_paths": list(generated.node_paths), "target_keys": [list(k) for k in generated.target_keys],
                       "dependencies": [list(d) for d in generated.dependencies],
                       "losses": [d.to_dict() for d in generated.losses], "glb_length": len(generated.glb)}, generated.glb)


if __name__ == "__main__":
    main()
