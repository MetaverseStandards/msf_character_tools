# SPDX-License-Identifier: MIT
"""Random inputs for the source helpers (path grammar, matrix decomposition,
influence rows and the GLB writer), run on both sides of the oracle."""
import math
import random

SPECIAL = '%/#[]:\x00\x01\x1f\x7f'
ALPHABET = SPECIAL + 'abcXYZ09 .-_é漢\U0001F600\ud800'
PIECES = ['%2F', '%25', '%41', '%2f', '%', '%0', '[0]', '[12]', '[01]', '[x]', '[', ']', '#', '/', '#helper:geometry',
          '#helper:scale[2]', '#helper:scale[]', '#helper:other', 'helper:', '']


def text(rng):
    parts = []
    for _ in range(rng.randint(0, 5)):
        parts.append(rng.choice(PIECES) if rng.random() < 0.4 else rng.choice(ALPHABET))
    return ''.join(parts)


def path_cases(rng, count):
    out = []
    for _ in range(count):
        name = text(rng)
        components = [(text(rng), rng.choice([None, 0, 3, 10**30, True])) for _ in range(rng.randint(0, 3))]
        helper = rng.choice([None, ('geometry', None), ('scale', 1), ('other', None), ('scale', 10**20)])
        candidate = rng.choice(['/', '', 'x']) + '/'.join(text(rng) for _ in range(rng.randint(1, 3)))
        out.append((name, components, helper, candidate))
    return out


DEFINITIONS = r"""
from msf_tools.sources import paths as _paths

def exact(fn, *args, **kwargs):
    try:
        return ('value', encode(fn(*args, **kwargs)))
    except Exception as exc:
        diagnostic = getattr(exc, 'diagnostic', None)
        if diagnostic is not None:
            return ('fault', diagnostic.code, diagnostic.ref, diagnostic.message)
        return ('error', type(exc).__name__, str(exc))

def path_battery(name, components, helper, candidate):
    out = [exact(_paths.escape, name), exact(_paths.unescape, name), exact(_paths.unescape, _paths.escape(name))]
    out.append(exact(_paths.node_path, components, helper))
    out.append(exact(_paths.target_key, components))
    for value in (candidate, name, '/' + name):
        out.append(exact(_paths.parse_node_path, value))
        out.append(exact(_paths.parse_target_key, value))
        out.append(exact(_paths.split_locator, value))
        out.append(exact(_paths.sort_key, value))
    made = exact(_paths.node_path, components, helper)
    if made[0] == 'value':
        path = _paths.node_path(components, helper)
        out.append(exact(_paths.parse_node_path, path))
        out.append(exact(_paths.sort_key, path))
        key = _paths.target_key(components)
        out.append(exact(_paths.split_locator, _paths.locator(path, key)))
    return out

def path_order(candidates):
    keyed = []
    for c in candidates:
        try:
            keyed.append((_paths.sort_key(c), c))
        except ValueError:
            pass
    return [c for _, c in sorted(keyed)]
"""
