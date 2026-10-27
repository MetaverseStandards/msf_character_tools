# SPDX-License-Identifier: MIT
"""Authoring validation, fragment merging and pack outputs (the C++ core) against
the 0.3.0 oracle.

Documents are seeds mutated at random: every Result, report, record export,
pack byte, CSV and coverage value must match the oracle's exactly (E_INPUT and
E_INTERNAL by code and ref). MSF_GATE=1 runs 2*10**4 documents and, with an
RCEF checkout, loads RCEF's authoring at MSF_RCEF_COMMIT on both sides.
"""
import copy
import csv
import datetime
import hashlib
import io
import math
import os
from pathlib import Path
import random
import subprocess
import tarfile
import tempfile
import tomllib
import unittest

from msf_tools import _native
from internal import oracle, workspace

GATE = os.environ.get('MSF_GATE') == '1'
ROOT = Path(__file__).resolve().parents[2]
core = _native.built
HEX = 'ab' * 32


def rich():
    """A 1.1 document using every optional field and operator."""
    def signal(sid, **extra):
        return {'id': sid, 'label': f'Label {sid}', 'value_type': 'scalar', 'units': '1', 'domain': {'min': -1, 'max': 2.0},
                'calibration': 'basis', 'disposition': 'mapped', 'evidence': ['e1'], 'evidence_status': 'verified_current', **extra}
    def rule(rid, inputs, outputs, operator, **extra):
        out = {'id': rid, 'inputs': inputs, 'outputs': outputs, 'operator': operator, 'disposition': 'mapped',
               'mapping_quality': 'exact', 'assumptions': ['a'], 'evidence': ['e1'], 'evidence_status': 'proposed',
               'loss_annotations': [], **extra}
        if out['disposition'] != 'mapped':
            del out['mapping_quality']
        return out
    return {
        'schema_version': '1.1', 'data_version': '1.2.3-rc.1', 'operator_version': '1.1', 'id': 'msf.rich', 'license': 'MIT',
        'evidence': [
            {'id': 'e1', 'claim': 'c', 'status': 'verified_current', 'license': 'MIT', 'authorship': 'me'},
            {'id': 'e2', 'claim': 'web, "quoted"', 'status': 'calibrated_software', 'url': 'https://example.org/x',
             'sha256': HEX, 'locator': 'p. 3', 'retrieved': '2024-01-01'},
        ],
        'signals': [
            signal('a', neutral=0, native_default=-0.0, region='face', side='left', native_id='A', surface='s', time='t',
                   validity=True, confidence=0.5, coupling='b', metadata={'reason': 'why', 'x': [1, -0.0, {'y': None}]}),
            signal('b', evidence=['e1', 'e2'], validity='when open', confidence='high', coupling=['a', 'c']),
            signal('c', domain={'min': 0}, disposition='unsupported', metadata={'reason': -0.0}),
            signal('d,"q"\nx', domain={}, disposition='excluded', evidence_status='calibrated_software'),
            signal('e', domain={'max': 10**20}, disposition='unresolved'),
        ],
        'profiles': [
            {'id': 'p1', 'label': 'P1', 'signal_ids': ['a', 'b', 'd,"q"\nx'], 'evidence': ['e2'], 'metadata': {'k': 1.5}},
            {'id': 'p,2', 'label': 'P2', 'signal_ids': ['c', 'e']},
        ],
        'mappings': [
            {'id': 'm1', 'rules': [
                rule('r1', ['a'], ['b'], {'id': 'identity'}),
                rule('r2', ['a', 'b'], ['c'], {'id': 'weighted_sum', 'weights': [0.5, -2]}, mapping_quality='approximate',
                     loss_annotations=[{'category': 'signal', 'effect': 'approximated', 'reason': 'r', 'refs': ['a'],
                                        'units': '1', 'bound': 0.25}]),
            ]},
            {'id': 'm2', 'rules': [
                rule('r3', ['c'], ['e'], {'id': 'affine', 'scale': 2, 'offset': -0.0}, coupling='a'),
                rule('r4', ['e'], ['a'], {'id': 'piecewise_linear', 'knots': [[0, 0], [1, 0.5], (2, 2.0)]}, evidence=['e2']),
                rule('r5', ['b'], ['d,"q"\nx'], {'id': 'identity'}, disposition='unsupported'),
            ]},
        ],
    }


def example():
    return tomllib.loads((ROOT / 'examples/authoring/pack.toml').read_text())


def deep(n):
    v = []
    for _ in range(n):
        v = [v]
    return v


def cycle():
    v = []
    v.append(v)
    return v


POOL = [None, True, False, 0, 1, -1, 2, 0.0, -0.0, 0.5, -1.5, 1e308, math.inf, -math.inf, math.nan, 10**400, -10**400,
        2**53 + 1, 2**1024 - 2**970, 2**1024, '', ' ', '\u3000', '\ufeff\u2028', 'x', '\ud800', 'a\udc80b', 'https://x',
        'http://x', '1.0', '1.1', '2.0', '1.0.0', '01.2.3-x.y', '1.0.0-', '1.0.0-é', 'calibrated_software', 'verified_current',
        'piecewise_linear', 'weighted_sum', 'affine', 'identity', 'mapped', 'excluded', 'exact', 'approximate', 'scalar',
        'signal', 'dropped', HEX, HEX.upper(), HEX[:-1], [], (), {}, [1], ['a', 'a'], ['a'], ('a', 'b'), {'min': 0},
        {1: 2}, {'min': 1, 'max': 0}, {'min': 1, 'max': 1.0}, {'min': 2**53 + 1, 'max': 2.0**53}, b'x', frozenset({1}),
        datetime.date(2020, 1, 1), 1 + 2j, [[0, 0], [1, 1]], [[0, 0], [0, 1]], [[0, 0], [1, 1], [2, 0]],
        [[-1e308, 0], [1e308, 0]], [[0, 1e308], [1, -1e308]], [[0, 0]], [[0, 0, 0], [1, 1]], [[True, 0], [1, 1]]]
KEYS = ['id', 'zzz', 'min', 'max', 'neutral', 'native_default', 'coupling', 'metadata', 'evidence', 'url', 'sha256', 'locator',
        'license', 'authorship', 'revision', 'mapping_quality', 'knots', 'weights', 'scale', 'offset', 'bound', 'units',
        'validity', 'confidence', 'signal_ids', 'rules', 'operator', 'schema_version']


def containers(value, path=()):
    yield path, value
    if len(path) > 10:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            yield from containers(v, path + (k,))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from containers(v, path + (i,))


NUMBERS = [0, -1, 2, 0.5, -0.0, 2.0, 3, -1.0000000000000002, 2**53, 2**53 + 1, 2.0**53, 10**20, 1e20, math.inf, True]


def targeted(doc, rng):
    """An edit aimed at one check that random edits rarely reach."""
    def rows(x):
        return x if isinstance(x, (list, tuple)) else ()
    signals = [s for s in rows(doc.get('signals')) if isinstance(s, dict)]
    rules = [r for m in rows(doc.get('mappings')) if isinstance(m, dict) for r in rows(m.get('rules')) if isinstance(r, dict)]
    roll = rng.randrange(6)
    if roll == 0:
        doc['operator_version'] = rng.choice(['1.0', '1.1', '1.2', 1.0])
        doc['schema_version'] = rng.choice(['1.0', '1.1', doc.get('schema_version')])
    elif roll == 1 and signals:
        rng.choice(signals)[rng.choice(['neutral', 'native_default'])] = rng.choice(NUMBERS)
    elif roll == 2 and signals:
        bounds = {k: rng.choice(NUMBERS) for k in rng.sample(['min', 'max'], rng.randrange(3))}
        rng.choice(signals)['domain'] = bounds
    elif roll == 3 and rules:
        rng.choice(rules)['disposition'] = rng.choice(['mapped', 'unsupported', 'unresolved', 'excluded'])
    elif roll == 4 and rules:
        xs = sorted(rng.choice(NUMBERS[:-2]) for _ in range(rng.randrange(1, 5)))
        knots = [[x, rng.choice(NUMBERS[:-2])] for x in xs]
        rng.choice(rules)['operator'] = rng.choice([{'id': 'piecewise_linear', 'knots': knots},
                                                     {'id': 'affine', 'scale': rng.choice(NUMBERS), 'offset': 0},
                                                     {'id': 'weighted_sum', 'weights': [rng.choice(NUMBERS)]}])
    elif roll == 5 and rules:
        rng.choice(rules)['loss_annotations'] = [{'category': 'signal', 'effect': 'dropped', 'reason': 'r', 'refs': [],
                                                  'bound': rng.choice(NUMBERS + [-0.5, 'x'])}]
    return doc


def mutate(doc, rng):
    """Apply one random edit in place and return the (possibly new) root."""
    if isinstance(doc, dict) and rng.random() < 0.3:
        return targeted(doc, rng)
    spots = [(p, v) for p, v in containers(doc) if isinstance(v, (dict, list))]
    path, target = rng.choice(spots)
    ids = [v for _, v in containers(doc) if isinstance(v, str)][:200]
    roll = rng.random()
    if isinstance(target, dict):
        keys = list(target)
        if roll < 0.35 and keys:
            target[rng.choice(keys)] = rng.choice(POOL + ids) if rng.random() < 0.8 else copy.deepcopy(rng.choice(POOL))
        elif roll < 0.55 and keys:
            del target[rng.choice(keys)]
        elif roll < 0.75:
            target[rng.choice(KEYS)] = rng.choice(POOL + ids)
        elif roll < 0.8:
            target[rng.choice([1, True, None, 'x'])] = 1
        elif roll < 0.85:
            target[rng.choice(keys or ['k'])] = rng.choice([deep(128), deep(129), deep(140), cycle()])
        elif keys:
            k = rng.choice(keys)
            if isinstance(target[k], list):
                target[k] = tuple(target[k])
    else:
        if roll < 0.3 and target:
            target[rng.randrange(len(target))] = rng.choice(POOL + ids)
        elif roll < 0.5 and target:
            target.append(copy.deepcopy(rng.choice(target)))
        elif roll < 0.65 and target:
            del target[rng.randrange(len(target))]
        elif roll < 0.75 and len(target) > 1:
            i, j = rng.randrange(len(target)), rng.randrange(len(target))
            target[i], target[j] = target[j], target[i]
        elif roll < 0.85:
            target.append(rng.choice(POOL + ids))
        else:
            target.clear()
    return doc


PACK = ('(lambda r: (lambda p: (p, p.sha256, p.to_bytes(), p.document, p.signals, m.survey_csv(p), m.coverage(p)))'
        '(m.compile_pack(r.value).value) if r.ok else r)(m.validate_authoring(doc))')


def documents(count, seed, seeds):
    rng = random.Random(seed)
    for _ in range(count):
        doc = copy.deepcopy(rng.choice(seeds))
        for _ in range(rng.choice((0, 1, 1, 1, 2, 2, 3, 5))):
            doc = mutate(doc, rng)
        yield doc


def toml_value(v):
    if isinstance(v, dict):
        return '{' + ', '.join(f'{toml_key(k)} = {toml_value(x)}' for k, x in v.items()) + '}'
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(toml_value(x) for x in v) + ']'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        return 'nan' if v != v else 'inf' if v == math.inf else '-inf' if v == -math.inf else repr(v)
    if isinstance(v, str):
        return '"' + ''.join(c if c.isprintable() and c not in '"\\' else f'\\u{ord(c):04x}' for c in v) + '"'
    return str(v)


def toml_key(k):
    return toml_value(str(k))


def toml(table):
    return ''.join(f'{toml_key(k)} = {toml_value(v)}\n' for k, v in table.items())


@unittest.skipIf(oracle.skip_reason(), oracle.skip_reason() or '')
class AgainstTheOracle(unittest.TestCase):
    def assertSame(self, cases):
        differing = oracle.differ(cases)
        self.assertEqual(differing[:3], [], f'{len(differing)} of {len(cases)} cases differ')

    def test_seeds_and_their_packs(self):
        self.assertSame([(PACK, {'doc': d}) for d in (example(), rich())])
        self.assertTrue(core.validate_authoring(rich())[1] is not None)

    def test_mutated_documents(self):
        docs = list(documents(20000 if GATE else 60, 11, [example(), rich()]))
        self.assertSame([(PACK, {'doc': d}) for d in docs])

    def test_odd_inputs(self):
        odd = [None, 1, 'x', [], (), {}, rich()['signals'], {**rich(), 1: 2}, {**rich(), 'zzz': 1}, deep(300), cycle(),
               {**rich(), 'signals': tuple(rich()['signals'])}, {**rich(), 'mappings': [{'id': 'm', 'rules': cycle()}]}]
        self.assertSame([('m.validate_authoring(doc)', {'doc': d}) for d in odd] +
                        [('m.compile_pack(doc)', {'doc': d}) for d in odd[:3]])

    def test_fragment_directories(self):
        rng = random.Random(3)
        cases = []
        with tempfile.TemporaryDirectory() as tmp:
            for n in range(600 if GATE else 6):
                doc = copy.deepcopy(rng.choice([example(), rich()]))
                for _ in range(rng.choice((0, 0, 1, 2))):
                    doc = mutate(doc, rng)
                folder = Path(tmp, str(n))
                (folder / 'parts').mkdir(parents=True)
                try:
                    toml(doc)
                except RecursionError:
                    continue
                meta = {k: v for k, v in doc.items() if not isinstance(v, list)}
                arrays = {k: v for k, v in doc.items() if isinstance(v, list)}
                (folder / 'pack.toml').write_text(toml(meta))
                for i, (k, rows) in enumerate(arrays.items()):
                    cut = rng.randrange(len(rows) + 1)
                    (folder / f'a{i}.toml').write_text(toml({k: rows[:cut]}))
                    (folder / 'parts' / f'b{i}.toml').write_text(toml({k: rows[cut:]}))
                roll = rng.random()
                if roll < 0.1:
                    (folder / 'parts/dup.toml').write_text(toml({'id': 'again'}))
                elif roll < 0.2:
                    (folder / 'parts/bad.toml').write_text('signals = 1\n')
                elif roll < 0.25:
                    (folder / 'parts/table.toml').write_text('[signals]\nx = 1\n')
                cases.append(('(lambda r: (r, m.compile_pack(r.value).value.to_bytes() if r.ok else None))(m.load_authoring(path))',
                              {'path': str(folder)}))
            self.assertSame(cases)

    @unittest.skipUnless(GATE, 'gate tier: MSF_GATE=1')
    def test_rcef_authoring(self):
        root = workspace.rcef_root()
        commit = os.environ.get('MSF_RCEF_COMMIT', '0d90172')
        if root is None or not (root / '.git').exists():
            self.skipTest(f'no RCEF checkout at {root}' if root else 'no RCEF checkout (set MSF_RCEF_ROOT)')
        archive = subprocess.run(['git', '-C', str(root), 'archive', commit], check=True, capture_output=True).stdout
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(tmp, filter='data')
            authoring = next(p.parent for p in sorted(Path(tmp).rglob('pack.toml')) if 'generated' not in p.parts)
            self.assertSame([('(lambda r: (r, (lambda p: (p.to_bytes(), m.survey_csv(p), m.coverage(p)))(m.compile_pack(r.value).value)))'
                              '(m.load_authoring(path))', {'path': str(authoring)})])
            import msf_tools as m
            seed = m.load_authoring(authoring).value.to_dict()
            self.assertSame([(PACK, {'doc': d}) for d in documents(300, 17, [seed])])


class InProcess(unittest.TestCase):
    def test_sha256_matches_hashlib(self):
        rng = random.Random(1)
        for n in list(range(130)) + [1000, 4096, 65537]:
            data = rng.randbytes(n)
            self.assertEqual(core._sha256(data), hashlib.sha256(data).hexdigest(), n)

    def test_csv_quoting_matches_this_interpreters_csv_module(self):
        rng = random.Random(2)
        alphabet = ['a', ',', '"', '\n', '\r', ' ', '\t', '\x00', 'é', '\u2028', ';', "'"]
        for _ in range(200):
            doc = rich()
            labels = [''.join(rng.choice(alphabet) for _ in range(rng.randrange(1, 6))) for _ in doc['signals']]
            for s, label in zip(doc['signals'], labels):
                s['label'] = 'x' + label
            handle = core.validate_authoring(doc)[1]
            stream = io.StringIO(newline='')
            writer = csv.writer(stream, lineterminator='\n', quoting=csv.QUOTE_MINIMAL)
            profiles = doc['profiles']
            writer.writerow(['id', 'label', 'value_type', 'units', 'disposition', 'evidence_status'] + [p['id'] for p in profiles])
            for s in doc['signals']:
                writer.writerow([s[k] for k in ('id', 'label', 'value_type', 'units', 'disposition', 'evidence_status')] +
                                ['1' if s['id'] in p['signal_ids'] else '' for p in profiles])
            self.assertEqual(handle.survey_csv(), stream.getvalue().encode())

    def test_valid_documents_with_surrogates_raise_pythons_own_encode_error(self):
        doc = rich()
        doc['signals'][0]['label'] = 'a\udc80'
        with self.assertRaises(UnicodeEncodeError):
            core.validate_authoring(doc)


if __name__ == '__main__':
    unittest.main()
