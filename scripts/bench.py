# SPDX-License-Identifier: MIT
"""Time msf-tools operations through the public API and print a JSON report.

    python -B scripts/bench.py [--root CHECKOUT | --installed] [--frames N] [--runs 5] [--output report.json]

By default msf_tools comes from this checkout. --root imports it from another
checkout; --installed uses the interpreter's installed copy, such as a 0.3.0
wheel in a separate venv. Set MSF_TOOLS_PURE=1 to time the pure-Python path of
a build that has the C++ core. Each workload checks one value analytically before timing.
Timings are medians on one host; they are not a real-time or device guarantee.
"""
import argparse
import importlib
import json
import os
import platform
import random
import statistics
import sys
import time
from pathlib import Path

EVIDENCE = [{'id': 'e', 'claim': 'Synthetic benchmark.', 'status': 'verified_current', 'license': 'MIT',
             'authorship': 'MSF Tools contributors'}]


def signal(sid, low=0, high=1):
    return {'id': sid, 'label': sid, 'value_type': 'scalar', 'units': '1', 'domain': {'min': low, 'max': high},
            'calibration': 'bench.v1', 'disposition': 'mapped', 'evidence_status': 'verified_current', 'evidence': ['e']}


def rule(rid, inputs, output, operator):
    return {'id': rid, 'inputs': inputs, 'outputs': [output], 'operator': operator, 'disposition': 'mapped',
            'mapping_quality': 'exact', 'assumptions': [], 'evidence': ['e'], 'evidence_status': 'verified_current',
            'loss_annotations': []}


def document(signals, sources, targets, rules):
    return {'schema_version': '1.1', 'operator_version': '1.1', 'data_version': '0.1.0', 'id': 'bench', 'license': 'MIT',
            'signals': signals, 'evidence': EVIDENCE,
            'profiles': [{'id': 'source', 'label': 'Source', 'signal_ids': sources},
                         {'id': 'target', 'label': 'Target', 'signal_ids': targets}],
            'mappings': [{'id': 'map', 'rules': rules}]}


def gaze():
    """weighted_sum (in - out) feeding two one-sided piecewise_linear splits."""
    rules = [rule('d', ['in', 'out'], 'gaze', {'id': 'weighted_sum', 'weights': [1, -1]}),
             rule('a', ['gaze'], 'toward_in', {'id': 'piecewise_linear', 'knots': [[-1, 0], [0, 0], [1, 1]]}),
             rule('b', ['gaze'], 'toward_out', {'id': 'piecewise_linear', 'knots': [[-1, 1], [0, 0], [1, 0]]})]
    signals = [signal('in'), signal('out'), signal('gaze', -1, 1), signal('toward_in'), signal('toward_out')]
    return document(signals, ['in', 'out'], ['toward_in', 'toward_out'], rules)


def wide():
    """52 face outputs from 40 inputs: 20 identity, 20 affine, 8 three-input weighted_sum, 4 piecewise_linear."""
    sources = [f's{i:02}' for i in range(40)]
    targets = [f't{i:02}' for i in range(52)]
    rules = []
    for i in range(20):
        rules.append(rule(f'r{i:02}', [sources[i]], targets[i], {'id': 'identity'}))
    for i in range(20, 40):
        rules.append(rule(f'r{i:02}', [sources[i]], targets[i], {'id': 'affine', 'scale': 0.5, 'offset': 0.25}))
    for i in range(40, 48):
        rules.append(rule(f'r{i:02}', [sources[i - 40], sources[i - 30], sources[i - 20]], targets[i],
                          {'id': 'weighted_sum', 'weights': [0.25, 0.25, 0.5]}))
    for i in range(48, 52):
        rules.append(rule(f'r{i:02}', [sources[i - 20]], targets[i],
                          {'id': 'piecewise_linear', 'knots': [[0, 0], [0.3, 0.1], [0.7, 0.8], [1, 1]]}))
    return document([signal(s) for s in sources + targets], sources, targets, rules)


def large(count=2000):
    """A pack-sized document: `count` affine rules over 2 * count signals, for JSON and pack timings."""
    sources = [f'in.{i:05}' for i in range(count)]
    targets = [f'out.{i:05}' for i in range(count)]
    rules = [rule(f'r{i:05}', [sources[i]], targets[i], {'id': 'affine', 'scale': 0.5 + i / count, 'offset': -i / (3 * count)})
             for i in range(count)]
    return document([signal(s, -1, 1) for s in sources] + [signal(s, -2, 2) for s in targets], sources, targets, rules)


def frames(sources, count, seed=20261027):
    rng = random.Random(seed)
    return [{'timestamp': i / 60, 'values': {s: rng.random() for s in sources},
             'validity': dict.fromkeys(sources, True)} for i in range(count)]


def median_seconds(fn, runs):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return {'median': statistics.median(times), 'min': min(times), 'max': max(times)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    source.add_argument('--installed', action='store_true')
    parser.add_argument('--frames', type=int, default=100_000)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.frames <= 10_000_000 or not 3 <= args.runs <= 100:
        parser.error('frames must be 1..10000000; runs 3..100')
    if not args.installed:
        sys.path.insert(0, str(args.root.resolve()))
    m = importlib.import_module('msf_tools')
    native = sys.modules.get('msf_tools._native')
    report = {'msf_tools': m.__version__, 'imported_from': str(Path(m.__file__).parent), 'platform': platform.platform(),
              'machine': platform.machine(), 'processor': platform.processor(), 'python': platform.python_version(),
              'implementation': platform.python_implementation(), 'cpu_count': os.cpu_count(),
              'core': native is not None and native.core is not None, 'frames': args.frames, 'runs': args.runs, 'workloads': {}}
    for name, doc in (('gaze', gaze()), ('wide', wide())):
        pack = m.compile_pack(m.validate_authoring(doc).value).value
        source, target = m.profile_snapshot(pack, 'source').value, m.profile_snapshot(pack, 'target').value
        compiled = m.compile_mapping(pack, source, target, 'map').value
        samples = frames(doc['profiles'][0]['signal_ids'], args.frames)
        result = m.evaluate_mapping(compiled, samples)
        if not result.ok:
            raise SystemExit(f'{name}: evaluation failed: {result.report.to_dict()}')
        first, values = result.value.samples[0]['values'], samples[0]['values']
        if name == 'gaze':
            expected = {'toward_in': max(values['in'] - values['out'], 0.0), 'toward_out': max(values['out'] - values['in'], 0.0)}
        else:
            expected = {'t00': values['s00'], 't20': 0.5 * values['s20'] + 0.25}
        if any(abs(first[k] - v) > 1e-12 for k, v in expected.items()):
            raise SystemExit(f'{name}: analytical check failed: {dict(first)} vs {expected}')
        report['workloads'][name] = {
            'rules': len(doc['mappings'][0]['rules']), 'outputs': len(doc['profiles'][1]['signal_ids']),
            'compile_mapping_seconds': median_seconds(lambda: m.compile_mapping(pack, source, target, 'map'), args.runs),
            'evaluate_mapping_seconds': median_seconds(lambda: m.evaluate_mapping(compiled, samples), args.runs)}
    validated = m.validate_authoring(large()).value
    pack = m.compile_pack(validated).value
    report['workloads']['pack'] = {
        'rules': len(pack.document['mappings'][0]['rules']), 'canonical_json_bytes': len(pack.to_bytes()),
        'canonical_json_seconds': median_seconds(lambda: m.canonical_json(pack.document), args.runs),
        'compile_pack_seconds': median_seconds(lambda: m.compile_pack(validated), args.runs)}
    text = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    sys.stdout.write(text)


if __name__ == '__main__':
    main()
