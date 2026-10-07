# SPDX-License-Identifier: MIT
"""Machine-readable CLI. Render first; atomically replace each file separately."""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
import tempfile

from . import (load_authoring, compile_pack, inspect_asset, annotate_asset,
               compile_mapping, evaluate_mapping, profile_snapshot,
               evaluate_geometry, LocalResolver, coverage, survey_csv)
from .common import canonical_json, digest, parse_json
from .report import Result, Report, Diagnostic, Fault


def atomic_write(path, data):
    path = Path(path)
    if path.is_symlink():
        raise CommandFailure(Report((_error("E_OUTPUT_PATH", path.name, "Output destination is a symlink."),)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path = path.parent.resolve() / path.name
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _preflight(outputs, inputs):
    """Reject aliases and symlink destinations before the first replacement."""
    outputs, inputs = [Path(p) for p in outputs if p], [Path(p) for p in inputs if p]
    diagnostics = []
    output_ids = set()
    for path in outputs:
        resolved = path.resolve()
        if str(resolved).casefold() in output_ids:
            diagnostics.append(_error("E_OUTPUT_PATH", path.name, "Output files alias one another."))
        output_ids.add(str(resolved).casefold())
        if path.is_symlink():
            diagnostics.append(_error("E_OUTPUT_PATH", path.name, "Output destination cannot be a symlink."))
        if path.exists() and not path.is_file():
            diagnostics.append(_error("E_OUTPUT_PATH", path.name, "Output destination must be a regular file."))
        for input_path in inputs:
            original = input_path.resolve()
            aliases = resolved == original or (input_path.is_dir() and resolved.is_relative_to(original))
            if path.exists() and input_path.is_file():
                aliases = aliases or os.path.samefile(path, input_path)
            if aliases:
                diagnostics.append(_error("E_OUTPUT_PATH", path.name, "Output aliases an input asset or authoring resource."))
                break
    if diagnostics:
        raise CommandFailure(Report(tuple(diagnostics)))


def _input_paths(args):
    fields = ("asset", "authoring", "samples", "sidecar", "annotations", "source_asset", "target_asset", "source_sidecar", "target_sidecar")
    paths = []
    for field in fields:
        value = getattr(args, field, None)
        if not value:
            continue
        path = Path(value)
        if field == "authoring" and path.is_dir():
            from .authoring import authoring_files
            paths.extend(authoring_files(path))
        else:
            paths.append(path)
        if field in ("asset", "source_asset", "target_asset") and getattr(args, "resolver_root", None) and path.is_file():
            inventory = inspect_asset(path.read_bytes(), path.suffix.lstrip("."))
            if inventory.ok:
                from urllib.parse import urlsplit, unquote
                for resource in inventory.value.resources:
                    if resource.uri and not urlsplit(resource.uri).scheme and not urlsplit(resource.uri).netloc:
                        paths.append(Path(args.resolver_root) / unquote(resource.uri))
    return paths


def _error(code, ref, message, remediation="Correct the input and rerun the command."):
    return Diagnostic(code, "error", str(ref), message, remediation)


def _need(result):
    if not result.ok:
        raise CommandFailure(result.report)
    return result.value


class CommandFailure(Exception):
    def __init__(self, report):
        self.report = report


def _pack(path):
    return _need(compile_pack(_need(load_authoring(path))))


def _snapshot(args):
    path = Path(args.asset)
    resolver = LocalResolver(args.resolver_root) if getattr(args, "resolver_root", None) else None
    sidecar = parse_json(Path(args.sidecar).read_bytes()) if getattr(args, "sidecar", None) else None
    return inspect_asset(path.read_bytes(), path.suffix.lstrip("."), resolver=resolver, sidecar=sidecar)


def _mapping(args):
    pack = _pack(args.authoring)
    source = _need(profile_snapshot(pack, args.source_profile)) if args.source_profile else _need(inspect_asset(Path(args.source_asset).read_bytes(), Path(args.source_asset).suffix.lstrip("."), sidecar=parse_json(Path(args.source_sidecar).read_bytes()), resolver=LocalResolver(args.resolver_root) if args.resolver_root else None))
    target = _need(profile_snapshot(pack, args.target_profile)) if args.target_profile else _need(inspect_asset(Path(args.target_asset).read_bytes(), Path(args.target_asset).suffix.lstrip("."), sidecar=parse_json(Path(args.target_sidecar).read_bytes()), resolver=LocalResolver(args.resolver_root) if args.resolver_root else None))
    return compile_mapping(pack, source, target, args.mapping, allow_approximation=args.allow_approximation)


def _check(args):
    pack = _pack(args.authoring)
    pack_path, csv_path = Path(args.pack), Path(args.csv)
    coverage_path = Path(args.coverage) if args.coverage else pack_path.parent / "coverage.json"
    sums_path = Path(args.sha256) if args.sha256 else pack_path.parent / "SHA256SUMS"
    paths = [pack_path, csv_path, coverage_path, sums_path]
    _preflight(paths + ([Path(args.output)] if args.output else []), _input_paths(args))
    if len({str(p.absolute()).casefold() for p in paths}) != 4 or len({p.name.casefold() for p in paths}) != 4:
        raise CommandFailure(Report((_error("E_OUTPUT_PATH", "/outputs", "Output paths and checksum names must be distinct."),)))
    rendered = {pack_path: pack.to_bytes(), csv_path: survey_csv(pack), coverage_path: canonical_json(coverage(pack))}
    sums = "".join(f"{digest(data)}  {p.name}\n" for p, data in rendered.items()).encode("utf-8")
    rendered[sums_path] = sums
    diagnostics = []
    # A common output directory is owned by this generation. Check every file,
    # including unexpected files absent from a stale checksum manifest.
    if len({p.parent.resolve() for p in paths}) == 1 and pack_path.parent.is_dir():
        expected = {p.name for p in paths} | ({Path(args.output).name} if args.output else set())
        for p in sorted(pack_path.parent.iterdir()):
            if p.name not in expected:
                diagnostics.append(_error("E_OUTPUT_EXTRA", p.name, "Unexpected entry in the generated output directory.", "Remove or relocate the extra entry after review."))
    if args.write and not diagnostics:
        for path, data in rendered.items():
            atomic_write(path, data)
    for path, expected in rendered.items():
        if not path.exists():
            diagnostics.append(_error("E_OUTPUT_MISSING", path.name, "Generated output is missing.", "Run check with --write."))
        elif not path.is_file() or path.read_bytes() != expected:
            diagnostics.append(_error("E_OUTPUT_STALE", path.name, "Generated output differs from validated authoring.", "Review authoring changes and run check with --write."))
    if sums_path.is_file():
        try:
            lines = sums_path.read_text(encoding="utf-8").splitlines()
            actual_names = [line.split("  ", 1)[1] for line in lines]
            if set(actual_names) - {p.name for p in rendered if p != sums_path}:
                diagnostics.append(_error("E_OUTPUT_EXTRA", sums_path.name, "Checksum manifest contains extra generated outputs."))
        except (ValueError, IndexError, UnicodeError):
            diagnostics.append(_error("E_OUTPUT_MANIFEST", sums_path.name, "Malformed checksum manifest."))
    report = Report(tuple(diagnostics))
    return Result({"pack_sha256": pack.sha256, "outputs": [p.name for p in rendered]} if report.ok else None, report)


def parser():
    p = argparse.ArgumentParser(prog="msf-tools", description="Validated signal mapping and glTF reference tools")
    sub = p.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("authoring")
    check.add_argument("--pack", required=True)
    check.add_argument("--csv", required=True)
    check.add_argument("--coverage")
    check.add_argument("--sha256")
    check.add_argument("--write", action="store_true")
    check.add_argument("--output")
    for command in ("inspect", "annotate", "geometry"):
        x = sub.add_parser(command)
        x.add_argument("asset")
        x.add_argument("--resolver-root")
        x.add_argument("--sidecar")
        x.add_argument("--output", required=command == "annotate")
        if command == "annotate":
            x.add_argument("annotations")
        if command == "geometry":
            x.add_argument("--time", type=float, default=0.0)
            x.add_argument("--animation", type=int)
    for command in ("map", "evaluate"):
        x = sub.add_parser(command)
        x.add_argument("authoring")
        x.add_argument("mapping")
        if command == "evaluate":
            x.add_argument("samples")
        for side in ("source", "target"):
            group = x.add_mutually_exclusive_group(required=True)
            group.add_argument(f"--{side}-profile")
            group.add_argument(f"--{side}-asset")
            x.add_argument(f"--{side}-sidecar")
        x.add_argument("--resolver-root")
        x.add_argument("--allow-approximation", action="store_true")
        x.add_argument("--output")
    return p


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.command != "check" and args.output:
            _preflight([args.output], _input_paths(args))
        if args.command == "check":
            result = _check(args)
        elif args.command in ("inspect", "annotate", "geometry"):
            result = _snapshot(args)
            if result.ok and args.command == "annotate":
                result = annotate_asset(result.value, parse_json(Path(args.annotations).read_bytes()))
            if result.ok and args.command == "geometry":
                result = evaluate_geometry(result.value, timestamp=args.time, animation_id=args.animation)
        else:
            for side in ("source", "target"):
                if getattr(args, side + "_asset") and not getattr(args, side + "_sidecar"):
                    raise CommandFailure(Report((_error("E_BINDING_REQUIRED", "/" + side, "Asset mappings require an explicit sidecar."),)))
            result = _mapping(args)
            if result.ok and args.command == "evaluate":
                samples = parse_json(Path(args.samples).read_bytes())
                if isinstance(samples, dict) and set(samples) == {"samples"}:
                    samples = samples["samples"]
                result = evaluate_mapping(result.value, samples)
        payload = canonical_json(result.value) if result.ok else canonical_json(result.report)
        if args.output:
            atomic_write(args.output, payload)
        elif result.ok:
            sys.stdout.buffer.write(payload)
        sys.stderr.buffer.write(canonical_json(result.report))
        return 0 if result.ok else 1
    except CommandFailure as exc:
        report = exc.report
    except Fault as exc:
        report = Report((exc.diagnostic,))
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        report = Report((_error("E_CLI_INPUT", "/", str(exc)),))
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        report = Report((_error("E_CLI_ARGUMENT", "/", "Invalid or missing command arguments."),))
    except Exception as exc:
        report = Report((_error("E_INTERNAL", "/", f"{type(exc).__name__}: {exc}"),))
    sys.stderr.buffer.write(canonical_json(report))
    return 1
