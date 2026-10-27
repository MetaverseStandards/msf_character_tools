# SPDX-License-Identifier: MIT
"""schemas/diagnostics.toml lists every diagnostic code the package can report.

Run this file directly to list registered codes that no test mentions.
"""
import ast
import importlib.util
import os
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import msf_tools as m
from msf_tools import _native
from msf_tools import snapshot as snapshots
from internal.adapters import fake_adapter as fake

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / 'schemas/diagnostics.toml'
SOURCES = sorted((ROOT / 'msf_tools').rglob('*.py'))
CORE_SOURCES = sorted(p for p in (ROOT / 'core').rglob('*.[ch]pp') if 'third_party' not in p.parts)
_spec = importlib.util.spec_from_file_location('gen_diagnostics', ROOT / 'tools/gen_diagnostics.py')
gen_diagnostics = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_diagnostics)
CODE = re.compile(r'[EWI]_[A-Z][A-Z0-9_]*')
SEVERITY = {'E': 'error', 'W': 'warning', 'I': 'info'}
KEYS = {'severity', 'meaning', 'since', 'strict', 'reserved', 'removed'}
RELEASES = ('0.1.0', '0.1.1', '0.2.0.dev0', '0.3.0')
# Codes assembled at run time: template -> (the one file that builds it, its codes).
# 'E_{}' is the strict-losses rename of a warning; entries' `strict` fields cover it.
BUILT = {'E_{}_COMPATIBILITY': ('mapping.py', ('E_NEUTRAL_COMPATIBILITY', 'E_SIDE_COMPATIBILITY', 'E_COUPLING_COMPATIBILITY')),
         'E_{}': ('snapshot.py', ())}


def registry():
    with REGISTRY.open('rb') as f:
        return tomllib.load(f)


def scan(paths):
    """Where each literal code, and each template of a code built at run time, appears."""
    literals, templates = {}, {}
    for path in paths:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant) \
                    and re.match(r'[EWI]_', node.values[0].value):
                templates.setdefault(''.join(v.value if isinstance(v, ast.Constant) else '{}' for v in node.values), set()).add(path)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and isinstance(node.left, ast.Constant) \
                    and type(node.left.value) is str and re.match(r'[EWI]_', node.left.value):
                templates.setdefault(node.left.value + '{}', set()).add(path)
            elif isinstance(node, ast.Constant) and type(node.value) is str and CODE.fullmatch(node.value):
                literals.setdefault(node.value, set()).add(path)
            elif isinstance(node, ast.Constant) and type(node.value) is str and re.match(r'[EWI]_[A-Z0-9_]*[%{]', node.value):
                templates.setdefault(node.value, set()).add(path)
    return literals, templates


def scan_core(paths):
    """Where each code the C++ core names (Code::E_...) appears."""
    literals = {}
    for path in paths:
        for code in re.findall(r'Code::([EWI]_[A-Z][A-Z0-9_]*)', path.read_text(encoding='utf-8')):
            literals.setdefault(code, set()).add(path)
    return literals


def unknown_builders(templates):
    """Run-time code templates that are new, or built somewhere other than their one known file."""
    return sorted(f'{template} in {path.name}' for template, paths in templates.items() for path in paths
                  if template not in BUILT or path.name != BUILT[template][0])


class DiagnosticsRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codes = registry()
        cls.literals, cls.templates = scan(SOURCES)
        for code, paths in scan_core(CORE_SOURCES).items():
            cls.literals.setdefault(code, set()).update(paths)
        cls.strict = {code: entry['strict'] for code, entry in cls.codes.items() if 'strict' in entry}

    def test_entries_are_well_formed(self):
        for code, entry in self.codes.items():
            with self.subTest(code=code):
                self.assertRegex(code, '^' + CODE.pattern + '$')
                self.assertLessEqual(set(entry), KEYS)
                self.assertEqual(entry['severity'], SEVERITY[code[0]])
                self.assertIsInstance(entry['meaning'], str)
                self.assertTrue(entry['meaning'].strip() and '\n' not in entry['meaning'])
                self.assertIn(entry['since'], RELEASES)
                if 'removed' in entry:
                    self.assertGreater(RELEASES.index(entry['removed']), RELEASES.index(entry['since']))
                if 'reserved' in entry:
                    self.assertIs(entry['reserved'], True)
                if 'strict' in entry:
                    self.assertEqual(code[0], 'W')
                    self.assertTrue(entry['strict'] in self.codes, f"{entry['strict']} is not registered")
                    self.assertEqual(self.codes[entry['strict']]['since'], entry['since'])
        targets = list(self.strict.values())
        self.assertEqual(sorted(targets), sorted(set(targets)), 'two warnings share a strict code')

    def test_every_code_in_the_source_is_registered(self):
        for code, paths in sorted(self.literals.items()):
            with self.subTest(code=code):
                where = ', '.join(str(p.relative_to(ROOT)) for p in sorted(paths))
                self.assertTrue(code in self.codes, f'{code} in {where} is not in {REGISTRY.name}')
                self.assertNotIn('removed', self.codes[code], f'{code} is used again; drop its removed field')
                self.assertNotIn('reserved', self.codes[code], f'{code} is now used; drop its reserved field')

    def test_codes_built_at_run_time_are_known_and_registered(self):
        self.assertEqual(unknown_builders(self.templates), [],
                         'A code is built at run time in a new way or place; add the template, file and codes to BUILT.')
        self.assertEqual(set(self.templates), set(BUILT))
        for template, (_, codes) in BUILT.items():
            pattern = '^' + re.escape(template).replace(r'\{\}', '[A-Z][A-Z0-9_]*') + '$'
            for code in codes:
                with self.subTest(code=code):
                    self.assertRegex(code, pattern)
                    self.assertTrue(code in self.codes, f'{code} is not registered')

    def test_new_code_builders_are_caught_wherever_they_appear(self):
        with tempfile.TemporaryDirectory() as tmp:
            for line in ('fail("E_" + kind + "_UNITS", ref, "x")', 'fail("E_SOURCE_" + kind, ref, "x")',
                         'fail("E_%s_UNITS" % kind, ref, "x")', 'fail("E_{}_UNITS".format(kind), ref, "x")',
                         'fail(f"W_{kind}", ref, "x")'):
                with self.subTest(line=line):
                    path = Path(tmp) / 'mapping.py'
                    path.write_text(line + '\n', encoding='utf-8')
                    self.assertNotEqual(unknown_builders(scan([path])[1]), [])
            path = Path(tmp) / 'snapshot.py'
            path.write_text('code = "E_" + d.code.removeprefix("W_")\n', encoding='utf-8')
            self.assertEqual(unknown_builders(scan([path])[1]), [])

    def test_the_generated_cpp_header_matches_the_registry(self):
        expected = gen_diagnostics.render(self.codes)
        self.assertEqual(gen_diagnostics.HEADER.read_text(encoding='utf-8'), expected,
                         'core/include/msf/diagnostics.inc is stale; run python3 -B tools/gen_diagnostics.py')
        self.assertNotIn('E_ANIMATION_TARGET', expected, 'removed codes stay out of the C++ enum')

    @unittest.skipIf(_native.core is None and os.environ.get('MSF_REQUIRE_CORE') != '1', 'C++ core not built')
    def test_the_core_carries_every_current_code_with_its_severity_and_strict_code(self):
        expected = [(code, entry['severity'], entry.get('strict')) for code, entry in sorted(self.codes.items())
                    if 'removed' not in entry]
        self.assertEqual(_native.core._codes(), expected)

    def test_the_registry_has_no_orphans(self):
        reachable = set(self.literals) | set(self.strict.values()) | {c for _, codes in BUILT.values() for c in codes}
        for code, entry in self.codes.items():
            with self.subTest(code=code):
                if 'reserved' not in entry and 'removed' not in entry:
                    self.assertTrue(code in reachable, f'{code} is registered but nothing reports it')

    def test_exactly_the_source_adapter_warnings_have_strict_codes(self):
        losses = {code for code, paths in self.literals.items()
                  if code.startswith('W_') and any(p.parent.name == 'sources' for p in paths)}
        self.assertEqual(set(self.strict), losses)

    def test_strict_losses_refuse_with_the_registered_codes(self):
        warnings = sorted(self.strict)
        data = fake.source(fake.scene(losses=[[code, '/Root', 'A loss.'] for code in warnings]))
        with patch.dict(snapshots._ADAPTER_MODULES, {'usda': 'internal.adapters.fake_adapter'}):
            result = m.inspect_asset(data, 'usda', fake.resolver, options={'losses': 'strict'})
        self.assertEqual([(d.code, d.severity) for d in result.report.diagnostics],
                         [(self.strict[code], 'error') for code in warnings])


def unexercised():
    """Registered codes that no test mentions; the strict codes are all exercised above."""
    codes = registry()
    tests = ' '.join(p.read_text(encoding='utf-8') for p in (ROOT / 'tests').rglob('*.py') if p.name != Path(__file__).name)
    exercised = set(CODE.findall(tests)) | {entry['strict'] for entry in codes.values() if 'strict' in entry}
    return sorted(code for code, entry in codes.items() if code not in exercised and 'removed' not in entry)


if __name__ == '__main__':
    codes = unexercised()
    print(f"{len(codes)} registered codes no test mentions: {', '.join(codes) or 'none'}")
