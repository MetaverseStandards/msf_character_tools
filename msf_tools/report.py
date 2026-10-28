# SPDX-License-Identifier: MIT
"""The stable public types for diagnostics and results. A result with an error has no value."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    ref: str
    message: str
    remediation: str

    def to_dict(self):
        return {k: getattr(self, k) for k in
                ("code", "severity", "ref", "message", "remediation")}


@dataclass(frozen=True)
class Loss:
    category: str
    effect: str
    reason: str
    refs: tuple[str, ...] = ()
    units: str | None = None
    bound: float | None = None

    def to_dict(self):
        d = {"category": self.category, "effect": self.effect,
             "reason": self.reason, "refs": list(self.refs)}
        if self.units is not None:
            d["units"] = self.units
        if self.bound is not None:
            d["bound"] = self.bound
        return d


@dataclass(frozen=True)
class Report:
    diagnostics: tuple[Diagnostic, ...] = ()
    losses: tuple[Loss, ...] = ()
    schema_version: str = "1.0"

    @property
    def ok(self):
        return not any(d.severity == "error" for d in self.diagnostics)

    def to_dict(self):
        return {"schema_version": self.schema_version,
                "diagnostics": [d.to_dict() for d in self.diagnostics],
                "losses": [x.to_dict() for x in self.losses]}


@dataclass(frozen=True)
class Result(Generic[T]):
    value: T | None
    report: Report = field(default_factory=Report)

    def __post_init__(self):
        if not self.report.ok and self.value is not None:
            object.__setattr__(self, "value", None)

    @property
    def ok(self):
        return self.value is not None and self.report.ok


class Fault(Exception):
    def __init__(self, code, ref, message, remediation="Correct the referenced input."):
        self.diagnostic = Diagnostic(code, "error", str(ref), message, remediation)
        super().__init__(message)


def fail(code, ref, message, remediation="Correct the referenced input."):
    raise Fault(code, ref, message, remediation)


def public(fn):
    """Translate exceptions for decorated Result APIs; plain helpers raise Fault."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            value = fn(*args, **kwargs)
            return value if isinstance(value, Result) else Result(value)
        except Fault as exc:
            return Result(None, Report((exc.diagnostic,)))
        except RecursionError:
            return Result(None, Report((Diagnostic(
                "E_RESOURCE_LIMIT", "error", fn.__name__, "Input exceeds supported nesting depth.",
                "Reduce structural nesting."),)))
        except (ValueError, TypeError, KeyError, IndexError, OSError, OverflowError) as exc:
            return Result(None, Report((Diagnostic(
                "E_INPUT", "error", fn.__name__, str(exc), "Check input types, structure and resource bounds."),)))
        except Exception as exc:
            return Result(None, Report((Diagnostic(
                "E_INTERNAL", "error", fn.__name__, f"{type(exc).__name__}: {exc}",
                "Report this diagnostic with a minimal reproducible input."),)))
    return wrapped
