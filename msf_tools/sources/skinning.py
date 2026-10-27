# SPDX-License-Identifier: MIT
"""Influence rows and their declared losses, shared by the source adapters.

Implemented in the C++ core (core/src/source_helpers.cpp).
"""
from .. import _native
from ..report import Diagnostic

_core = _native.built


def count(n, one, many):
    return f"{n} {one if n == 1 else many}"


def warning(code, ref, message):
    return Diagnostic(code, "warning", ref, message, "Review the declared loss.")


def merge(pairs, path):
    """Sum (joint, weight) pairs per joint, dropping zero weights."""
    return dict(_core._merge(list(pairs), path))


def influence_rows(merged_rows, root, mode, path, unweighted_to="the skeleton root joint"):
    """Turn per-point {joint: weight} maps into sorted (joint, weight) rows.

    Unweighted points bind to `root`. With mode "top4", points keep their four
    largest weights (ties to the lower joint). The writer renormalizes the rows.
    """
    rows, losses = _core._influence_rows([list(merged.items()) for merged in merged_rows], root, mode == "top4", path, unweighted_to)
    return rows, [Diagnostic(*d) for d in losses]


def method_loss(path, method):
    return warning("W_SKINNING_METHOD", path, f"Skinning method {method} is stored as linear blend skinning.")
