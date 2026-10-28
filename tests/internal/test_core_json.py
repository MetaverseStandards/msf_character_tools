# SPDX-License-Identifier: MIT
"""The C++ JSON parser and canonical writer against the Python reference path.

Python's own repr, json and Decimal are the oracles: every case runs through
common.parse_json / common.canonical_json with the core and again with
msf_character_tools._native.core set to None, and the outcomes must be identical:
equal bytes, identical typed values (floats by bit pattern), or the same
diagnostic or exception. MSF_GATE=1 widens the float and fuzz counts.
"""
from array import array
from collections.abc import Mapping
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess
import unittest
from types import MappingProxyType
from unittest import mock

from msf_character_tools import _native
from msf_character_tools.common import canonical_json, parse_json
from msf_character_tools.report import Fault
from internal import workspace

ROOT = Path(__file__).resolve().parents[2]
GATE = os.environ.get('MSF_GATE') == '1'
core = _native.built


def outcome(fn, *args):
    try:
        return ('value', fn(*args))
    except Fault as exc:
        return ('fault', exc.diagnostic)
    except (ValueError, TypeError, RecursionError) as exc:
        return ('error', type(exc).__name__, str(exc))


def outcome_with_message(fn, *args):
    try:
        return ('value', fn(*args))
    except Exception as exc:
        return ('error', type(exc).__name__, str(exc))


def reference(fn, *args):
    with mock.patch.object(_native, 'core', None):
        return outcome(fn, *args)


def parsed_alike(test, data):
    """parse_json agrees with the reference, and the core declines only input Python rejects."""
    actual, expected = outcome(parse_json, data), reference(parse_json, data)
    test.assertEqual(actual[0], expected[0], (data, actual, expected))
    test.assertTrue(same(actual[1:], expected[1:]), (data, actual, expected))
    if type(data) is bytes and json.detect_encoding(data) not in ('utf-8', 'utf-8-sig'):
        return actual
    try:
        declined = core.parse_json(data) is None
    except (Fault, RecursionError):
        declined = False
    if declined and expected[0] == 'value':
        # Allowed: nesting past the core's limit, and str holding lone surrogates.
        test.assertTrue(nesting(data) > 512 or type(data) is str and not data.isascii() and not utf8able(data),
                        (data, 'the core declined input Python accepts'))
    return actual


def utf8able(text):
    try:
        text.encode('utf-8')
        return True
    except UnicodeEncodeError:
        return False


def nesting(data):
    depth = deepest = 0
    for c in data if type(data) is bytes else data.encode('utf-8', 'surrogatepass'):
        depth += (c in b'[{') - (c in b']}')
        deepest = max(deepest, depth)
    return deepest


def same(a, b):
    """Equal values of identical types, floats by bit pattern and dicts in order."""
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return struct.pack('>d', a) == struct.pack('>d', b)
    if type(a) is dict:
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if type(a) in (list, tuple):
        return len(a) == len(b) and all(map(same, a, b))
    return a == b


def finite_floats(count, rng):
    values = array('d', rng.randbytes(8 * count))
    return [x for x in values if math.isfinite(x)]


def hard_floats():
    values = [0.0, -0.0, 5e-324, -5e-324, 2.2250738585072014e-308, 2.2250738585072011e-308, 1.7976931348623157e308,
              0.1, 0.2, 0.3, 1 / 3, 2 / 3, 9007199254740993.0, 2.0**53, 2.0**53 + 2, 123456789012345680.0,
              1e15, 1e16, 1e17, 9.999999999999998e15, 1e-4, 1e-5, 9.9999999999999e-5, 0.00011, 1e22, 1e23,
              5e-310, 4.9406564584124654e-324, 2.4703282292062328e-324, 1.5, 100.0, 1e100, 1e-100]
    for e in range(-1074, 1024):
        p = math.ldexp(1.0, e)
        values += [p, math.nextafter(p, 0), math.nextafter(p, math.inf)]
    for e in range(-325, 309):
        p = float(f'1e{e}')
        values += [p, math.nextafter(p, 0), math.nextafter(p, math.inf), float(f'5e{e}'), float(f'9.5e{e}')]
    return [x for v in values if math.isfinite(v) for x in (v, -v)]


class Floats(unittest.TestCase):
    def check(self, values):
        actual = core._repr_floats(array('d', values).tobytes()).decode().split('\n')
        expected = list(map(repr, values))
        mismatches = [(e, a) for e, a in zip(expected, actual) if e != a]
        self.assertEqual(len(actual), len(expected))
        self.assertEqual(mismatches[:5], [])

    def test_random_float64_like_repr(self):
        self.check(finite_floats(10**5, random.Random(1)))

    def test_hard_float64_cases_like_repr(self):
        self.check(hard_floats())

    @unittest.skipUnless(GATE, 'gate tier: MSF_GATE=1')
    def test_ten_million_random_float64_like_repr(self):
        rng = random.Random(2)
        for _ in range(100):
            self.check(finite_floats(10**5, rng))

    def test_float32_casts_check_the_range_first(self):
        limit = struct.unpack('<f', struct.pack('<I', 0x7F7FFFFF))[0]
        overflow = 2.0**128 - 2.0**103
        cases = [0.0, -0.0, 1e-46, 1.4e-45, limit, -limit, math.nextafter(limit, math.inf), math.nextafter(overflow, 0),
                 overflow, -overflow, 1e39, math.inf, -math.inf, 0.1, 3.4028235677973366e38] + finite_floats(2000, random.Random(3))
        for x in cases:
            with self.subTest(x=x):
                try:
                    expected = struct.unpack('<f', struct.pack('<f', x))[0]
                except OverflowError:
                    expected = None
                actual = core._float32(x)
                self.assertTrue(expected is None and actual is None or same(actual, expected), (x, actual, expected))


class Numbers(unittest.TestCase):
    def test_exact_integers_from_lexemes_like_decimal(self):
        rng = random.Random(4)
        lexemes = ['0', '-0', '0.0', '-0.0', '1.0', '1e2', '1E+2', '1.5', '1.5e1', '15e-1', '1e-2', '0e999999999999',
                   '1.000000000000000000001', '123456789012345678901234567890', '1' + '0' * 300 + '.0e-1',
                   '100e-2', '2.50e1', '-7.000e0', '1e-99999999999']
        for _ in range(3000):
            mantissa = str(rng.randrange(10**rng.randrange(1, 25)))
            point = rng.randrange(len(mantissa) + 1)
            frac = f'{mantissa[:point] or "0"}.{mantissa[point:]}' if point < len(mantissa) else mantissa
            lexemes.append(rng.choice(['', '-']) + frac + rng.choice(['', f'e{rng.randrange(-30, 30)}', f'E+{rng.randrange(0, 5)}']))
        for lexeme in lexemes:
            with self.subTest(lexeme=lexeme):
                value = Decimal(lexeme)
                expected = str(int(value)) if value == value.to_integral_value() else None
                self.assertEqual(core._exact_integer(lexeme), expected)

    def test_number_lexemes_parse_like_the_reference(self):
        big = 2**1024 - 2**970
        cases = ['-0', '0', '1E5', '1e-400', '-1e-400', '1e400', '1' * 309, '1' * 310, '-' + '9' * 310, str(big - 1), str(big),
                 str(2**1024), '0.1e1', '12.5E-3', '1.', '1e', '1e+', '01', '-', '- 1', '+1', '.5', '1.5e', '2e-1074',
                 '4.9406564584124654e-324', '2.4703282292062327e-324', '1' + '0' * 400 + 'e-400', '0e5', '-0.0e-0']
        for text in cases:
            with self.subTest(text=text):
                self.assertSameOutcome(text.encode())

    def assertSameOutcome(self, data):
        parsed_alike(self, data)


def git(root, *args):
    # The sanitizer tier preloads the ASan runtime into Python; git must not inherit it.
    env = {k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'DYLD_INSERT_LIBRARIES')}
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True, env=env).stdout


def goldens(root=ROOT, commit=None):
    """Every JSON file in a repository (the work tree, or a commit read from Git), and each GLB's JSON chunk."""
    if commit is None:
        names = git(root, 'ls-files', '*.json', '*.gltf', '*.glb').decode().split()
    else:
        names = [n for n in git(root, 'ls-tree', '-r', '--name-only', commit).decode().split()
                 if n.endswith(('.json', '.gltf', '.glb'))]
    for name in names:
        data = (root / name).read_bytes() if commit is None else git(root, 'show', f'{commit}:{name}')
        if name.endswith('.glb'):
            length = struct.unpack_from('<I', data, 12)[0]
            data = data[20:20 + length]
        yield name, data


class Documents(unittest.TestCase):
    def assertSameOutcome(self, fn, *args):
        actual, expected = outcome(fn, *args), reference(fn, *args)
        self.assertEqual(actual[0], expected[0], (args, actual, expected))
        self.assertTrue(same(actual[1:], expected[1:]), (args, actual, expected))
        return actual

    def test_every_json_golden_round_trips_byte_for_byte(self):
        self.assertGreater(self.round_trip(goldens()), 3, 'no canonical goldens found')

    @unittest.skipUnless(GATE, 'gate tier: MSF_GATE=1')
    def test_every_rcef_json_golden_round_trips_byte_for_byte(self):
        root = workspace.rcef_root()
        commit = os.environ.get('MSF_RCEF_COMMIT', '0d90172')
        if root is None or not (root / '.git').exists():
            self.skipTest(f'no RCEF checkout at {root}' if root else 'no RCEF checkout (set MSF_RCEF_ROOT)')
        self.assertGreaterEqual(self.round_trip(goldens(root, commit)), 2, 'RCEF generated/ goldens were not canonical')

    def round_trip(self, documents):
        count = 0
        for name, data in documents:
            with self.subTest(name=name):
                self.assertIsNotNone(core.parse_json(data), 'the core declined the document')
                parsed = self.assertSameOutcome(parse_json, data)[1]
                self.assertIsNotNone(core.canonical_json(parsed), 'the core declined the document')
                written = self.assertSameOutcome(canonical_json, parsed)[1]
                with mock.patch.object(_native, 'core', None):
                    if canonical_json(parse_json(data)) == data:
                        self.assertEqual(written, data)
                        count += 1
        return count

    def test_values_records_build_are_written_like_the_reference(self):
        rng = random.Random(5)
        values = [None, True, False, 0, -0.0, 1.5, 2**70, -2**63, 2**63, 'x', [], {}, (), MappingProxyType({'b': 1, 'a': (2,)}),
                  {'k': [1, {'z': 0.1, 'y': [None]}]}, [math.inf], {'n': math.nan}, {1: 'int key'}, {True: 1},
                  {'s': {1, 2}}, [Decimal('1')], 10**5000, [[[]]] * 3]
        for i, value in enumerate(values + [random_value(rng, 0) for _ in range(300)]):
            with self.subTest(i=i):
                self.assertSameOutcome(canonical_json, value)

    def test_mapping_proxies_over_odd_items_are_written_like_the_reference(self):
        rng = random.Random(6)
        for i in range(300):
            value = oddly(random_value(rng, 0), rng)
            with self.subTest(i=i):
                self.assertSameOutcome(canonical_json, value)

    def test_nesting_limits_match_the_reference(self):
        for depth in (127, 128, 129, 130, 199, 200, 201, 600, 2000):
            with self.subTest(depth=depth):
                parsed_alike(self, b'[' * depth + b'1' + b']' * depth)
                parsed_alike(self, b'{"a":' * depth + b'{}' + b'}' * depth)

    def test_containers_nested_past_200_are_refused_the_same_way_on_both_paths(self):
        too_deep = ('error', 'RecursionError', 'JSON nesting exceeds 200 levels.')
        for depth in (199, 200, 201, 600):
            nested_list = []
            for _ in range(depth - 1):
                nested_list = [nested_list]
            nested_map = {}
            for _ in range(depth - 1):
                nested_map = MappingProxyType({'a': nested_map})
            for value in (nested_list, nested_map):
                with self.subTest(depth=depth, kind=type(value).__name__):
                    actual = self.assertSameOutcome(canonical_json, value)
                    self.assertEqual(actual[0] == 'error', depth > 200, actual)
                    if depth > 200:
                        self.assertEqual(outcome_with_message(canonical_json, value), too_deep)
                        with mock.patch.object(_native, 'core', None):
                            self.assertEqual(outcome_with_message(canonical_json, value), too_deep)
            text = b'[' * depth + b']' * depth
            with self.subTest(depth=depth, kind='text'):
                actual = parsed_alike(self, text)
                self.assertEqual(actual[0] == 'error', depth > 200, actual)
                if depth > 200:
                    for data in (text, text.decode(), b'[1, ' + text + b']'):
                        self.assertEqual(outcome_with_message(parse_json, data), too_deep)
                        with mock.patch.object(_native, 'core', None):
                            self.assertEqual(outcome_with_message(parse_json, data), too_deep)
        deep = b'[' * 300 + b']' * 300
        for data in (b'[1 2, ' + deep + b']', b'[NaN, ' + deep + b']', b'{"a": 1, "a": 2, "b": ' + deep + b'}',
                     b'[' + deep + b', NaN]', b'["[[[[", ' + deep + b']', b'["\\"", ' + b'[' * 199 + b']' * 199 + b']'):
            with self.subTest(data=data[:24]):
                parsed_alike(self, data)

    def test_errors_are_reported_in_document_order(self):
        cases = [b'{"a": 1, "a": NaN}', b'{"a": 1, "a": 2, "b": [1,}', b'[1e400, NaN]', b'[NaN, 1e400]',
                 b'{"a": {"b": 1, "b": 2}, "a": 3}', b'[1e400, {"x": 1, "x": 2}]', b'{"\\ud800": 1, "\\ud800": 2}',
                 b'{"x": [1, 2, 1e999], "y": -Infinity}', b'  {"a": 1}  ', b'{"a": 1} x', b'\xef\xbb\xbf{"a": 1}',
                 b'"\xed\xa0\x80"', b'"\xff"', b'"\xc0\x80"', b'\x00\x00\x00[', b'\xff\xfe[\x00]\x00', b'[1, 2]\n\n']
        for data in cases:
            with self.subTest(data=data):
                parsed_alike(self, data)
                parsed_alike(self, data.decode('utf-8', 'surrogateescape'))

    def test_fuzzed_documents_parse_like_the_reference(self):
        rng = random.Random(6)
        for _ in range(3000 if GATE else 300):
            data = mutate(canonical_or_compact(rng), rng)
            with self.subTest(data=data[:80]):
                parsed_alike(self, data)


class Unicode(unittest.TestCase):
    def test_fuzzed_strings_are_written_like_the_reference(self):
        rng = random.Random(7)
        for _ in range(20000 if GATE else 1000):
            key, value = random_text(rng), random_text(rng)
            doc = {key: value, random_text(rng): [random_text(rng)]}
            actual, expected = outcome(canonical_json, doc), reference(canonical_json, doc)
            self.assertEqual(actual, expected, repr(doc))

    def test_fuzzed_escapes_parse_like_the_reference(self):
        rng = random.Random(8)
        pieces = ['\\ud83d', '\\ude00', '\\uD800', '\\udfff', '\\u0000', '\\u00e9', '\\u12G4', '\\u12', '\\x', '\\/',
                  '\\"', '\\\\', '\\b', '\\f', '\\n', '\\r', '\\t', 'a', 'é', '😀', '\t', '\x7f', ' ', '﻿']
        for _ in range(20000 if GATE else 1000):
            body = ''.join(rng.choice(pieces) for _ in range(rng.randrange(6)))
            text = '{"' + body + '": ["' + body + '"]}'
            for data in (text.encode('utf-8', 'surrogatepass'), text):
                actual = parsed_alike(self, data)
                if actual[0] == 'value':
                    self.assertEqual(outcome(canonical_json, actual[1]), reference(canonical_json, actual[1]))


ALPHABET = ['a', 'Z', '0', ' ', '"', '\\', '/', '\n', '\r', '\t', '\b', '\f', '\x00', '\x01', '\x1f', '\x7f', '\x80',
            'é', 'ß', ' ', '﻿', '￿', '中', '😀', '\U0010ffff', '\ud800', '\udfff', '\ud83d', '\ude00']


def random_text(rng):
    return ''.join(rng.choice(ALPHABET) for _ in range(rng.randrange(5)))


def random_value(rng, depth):
    kind = rng.randrange(9 if depth < 4 else 6)
    if kind == 0:
        return rng.choice([None, True, False])
    if kind == 1:
        return rng.choice([0, -1, 2**53 + 1, -2**64, 10**30, rng.randrange(-10**6, 10**6)])
    if kind == 2:
        return rng.choice([rng.random(), -rng.random() * 1e300, rng.choice(hard_floats()[:200]), -0.0, 1e-7])
    if kind in (3, 4, 5):
        return random_text(rng).replace('\ud800', 'x') if rng.random() < 0.9 else random_text(rng)
    if kind in (6, 7):
        return [random_value(rng, depth + 1) for _ in range(rng.randrange(4))]
    return {random_text(rng): random_value(rng, depth + 1) for _ in range(rng.randrange(4))}


class OddItems(Mapping):
    """A Mapping whose items() returns `items` as given, not (key, value) tuples."""
    def __init__(self, items, data):
        self._items, self._data = items, data

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def items(self):
        return self._items


def oddly(value, rng):
    """`value` with some dicts behind a mappingproxy whose items() are lists, short or long tuples, or correct pairs."""
    if isinstance(value, list):
        return [oddly(v, rng) for v in value]
    if not isinstance(value, dict):
        return value
    value = {k: oddly(v, rng) for k, v in value.items()}
    shape = rng.randrange(5)
    if shape == 0:
        return value
    pairs = [[k, v] for k, v in value.items()] if shape == 1 else [(k, v) for k, v in value.items()]
    if shape == 3 and pairs:
        pairs[-1] = pairs[-1][:1]
    if shape == 4:
        pairs.append(('extra', 1, 2))
    return MappingProxyType(OddItems(pairs, value))


def canonical_or_compact(rng):
    import json
    value = random_value(rng, 0)
    try:
        return json.dumps(value, ensure_ascii=rng.random() < 0.3, indent=rng.choice([None, 2])).encode('utf-8', 'surrogatepass')
    except ValueError:
        return b'[1]'


TOKENS = [b'{', b'}', b'[', b']', b',', b':', b'"', b'\\', b'-', b'0', b'1', b'.', b'e', b'E', b'+', b' ', b'\n', b'null',
          b'true', b'NaN', b'Infinity', b'-Infinity', b'\x00', b'\xed\xa0\x80', b'\xc3', b'\xef\xbb\xbf', b'\\u', b'"a":']


def mutate(data, rng):
    data = bytearray(data)
    for _ in range(rng.randrange(4)):
        at = rng.randrange(len(data) + 1)
        choice = rng.randrange(3)
        if choice == 0 and data:
            del data[at:at + rng.randrange(1, 4)]
        elif choice == 1:
            data[at:at] = rng.choice(TOKENS)
        elif data:
            data[at % len(data)] = rng.randrange(256)
    return bytes(data)


if __name__ == '__main__':
    unittest.main()
