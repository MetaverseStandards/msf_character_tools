# SPDX-License-Identifier: MIT
"""Record this host's measured pilot timing; it is not a real-time guarantee."""
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-dir", type=Path, required=True)
    parser.add_argument("--vertices", type=int, default=10000)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.vertices <= 1000000 or not 3 <= args.repetitions <= 1000:
        parser.error("vertices must be 1..1000000; repetitions 3..1000")
    sys.path.insert(0, str(args.module_dir.resolve(strict=True)))
    import _msf_native as native

    basis = [[1., 0., 0.] for _ in range(args.vertices)]
    deltas = [[[0., .1, 0.] for _ in basis]]
    joints = [[0, 0, 0, 0] for _ in basis]
    weights = [[1., 0., 0., 0.] for _ in basis]
    world = native.identity()
    joint = native.compose_trs([0, 0, 0], [0, 0, .7071067811865476, .7071067811865476], [1, 1, 1])

    def operation():
        morphed = native.morph_positions(basis, deltas, [1.5])
        return native.skin_positions(morphed, joints, weights, world, [joint], [world])

    output = operation()
    if abs(output[0][0] + .15) > 1e-9 or abs(output[0][1] - 1) > 1e-9:
        raise RuntimeError("Analytical position verification failed")
    timings = []
    for _ in range(args.repetitions):
        start = time.perf_counter()
        output = operation()
        timings.append(time.perf_counter() - start)
    report = {
        "schema_version": "1.0", "platform": platform.platform(),
        "architecture": platform.machine(), "python": platform.python_version(),
        "operation": "one relative morph followed by four-influence LBS",
        "includes": "Python/native input and output ownership copies and allocations",
        "vertices": args.vertices, "repetitions": args.repetitions,
        "seconds": {"minimum": min(timings), "median": statistics.median(timings), "maximum": max(timings)},
        "median_vertices_per_second": args.vertices / statistics.median(timings),
        "precision": "binary64", "analytical_position_check": "passed",
        "limits": "Synthetic one-joint workload on one host; no device, frame-budget or memory guarantee.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
