# SPDX-License-Identifier: MIT
"""Influence rows and their declared losses, shared by the source adapters."""
import math

from ..report import Diagnostic, fail


def count(n, one, many):
    return f"{n} {one if n == 1 else many}"


def warning(code, ref, message):
    return Diagnostic(code, "warning", ref, message, "Review the declared loss.")


def merge(pairs, path):
    """Sum (joint, weight) pairs per joint, dropping zero weights."""
    merged = {}
    for joint, weight in pairs:
        if not math.isfinite(weight) or weight < 0:
            fail("E_SOURCE_VALUE", path, "Joint influences need finite nonnegative weights.")
        if weight > 0:
            merged[joint] = merged.get(joint, 0.0) + weight
    return merged


def influence_rows(merged_rows, root, mode, path, unweighted_to="the skeleton root joint"):
    """Turn per-point {joint: weight} maps into sorted (joint, weight) rows.

    Unweighted points bind to `root`. With mode "top4", points keep their four
    largest weights (ties to the lower joint). The writer renormalizes the rows.
    """
    rows, losses = [], []
    normalized = unweighted = truncated = widest = 0
    dropped = 0.0
    for merged in merged_rows:
        total = math.fsum(merged.values())
        if total == 0:
            unweighted += 1
            merged = {root: 1.0}
        elif abs(total - 1) > 1e-6:
            normalized += 1
        pairs = sorted(merged.items(), key=lambda jw: (-jw[1], jw[0]))
        if len(pairs) > 4 and mode == "top4":
            truncated += 1
            dropped = max(dropped, pairs[4][1] / total)
            pairs = pairs[:4]
        widest = max(widest, len(pairs))
        rows.append(tuple(sorted(pairs)))
    if widest > 4:
        losses.append(Diagnostic("I_INFLUENCES_N", "info", path, f"Vertices have up to {widest} joint influences, stored in "
                                 f"{(widest + 3) // 4} JOINTS/WEIGHTS sets.", "No action needed."))
    if truncated:
        losses.append(warning("W_INFLUENCES_TRUNCATED", path, f"{count(truncated, 'vertex', 'vertices')} kept only their four "
                              f"largest influences; the largest dropped weight is {dropped:.6g}."))
    if normalized:
        losses.append(warning("W_WEIGHTS_NORMALIZED", path, f"Normalized the weights of {count(normalized, 'vertex', 'vertices')} "
                              "that did not sum to 1."))
    if unweighted:
        losses.append(warning("W_UNWEIGHTED_VERTICES", path,
                              f"Bound {count(unweighted, 'unweighted vertex', 'unweighted vertices')} to {unweighted_to}."))
    return tuple(rows), losses


def method_loss(path, method):
    return warning("W_SKINNING_METHOD", path, f"Skinning method {method} is stored as linear blend skinning.")
