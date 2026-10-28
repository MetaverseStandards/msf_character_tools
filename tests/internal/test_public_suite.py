# SPDX-License-Identifier: MIT
"""tests/public is the gate a reimplementation must pass unchanged; this test checks that it stays so.

After a deliberate change to tests/public, refresh the manifest with
    python -B tests/internal/test_public_suite.py --write
"""
import ast
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'tests' / 'public'
MANIFEST = ROOT / 'tests' / 'public.sha256'


def public_files():
    return sorted(p for p in PUBLIC.rglob('*') if p.is_file() and '__pycache__' not in p.parts)


def manifest_text():
    return ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}\n' for p in public_files())


def public_names():
    tree = ast.parse((ROOT / 'msf_tools' / '__init__.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__all__' for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise AssertionError('msf_tools/__init__.py has no __all__')


def private_uses(path, public):
    """Every use of msf_tools beyond its public names and the CLI entry point, as (line, what).

    Private attributes (`._name` on anything but self or cls) and strings naming
    msf_tools submodules, as `importlib.import_module` and `mock.patch` take them,
    count too.
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    package, cli, found, attributes = set(), set(), [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            private = node.attr.startswith('_') and not (node.attr.startswith('__') and node.attr.endswith('__'))
            if private and not (isinstance(node.value, ast.Name) and node.value.id in ('self', 'cls')):
                found.append((node.lineno, f'._{node.attr[1:]}'))
            elif isinstance(node.value, ast.Name):
                attributes.append(node)
        elif isinstance(node, ast.Constant) and type(node.value) is str and node.value.startswith(('msf_tools.', 'msf_tools_ufbx')):
            found.append((node.lineno, repr(node.value)))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'msf_tools':
                    package.add(alias.asname or alias.name)
                elif alias.name.split('.')[0] in ('msf_tools', 'msf_tools_ufbx', 'internal'):
                    found.append((node.lineno, 'import ' + alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split('.')[0]
            for alias in node.names:
                if node.module == 'msf_tools' and alias.name == 'cli':
                    cli.add(alias.asname or alias.name)
                elif node.module == 'msf_tools' and alias.name in public:
                    continue
                elif top in ('msf_tools', 'msf_tools_ufbx', 'internal'):
                    found.append((node.lineno, f'from {node.module} import {alias.name}'))
    for node in attributes:
        if node.value.id in package and node.attr not in public and not node.attr.startswith('__'):
            found.append((node.lineno, f'{node.value.id}.{node.attr}'))
        if node.value.id in cli and node.attr != 'main':
            found.append((node.lineno, f'{node.value.id}.{node.attr}'))
    return found


class PublicSuite(unittest.TestCase):
    def test_tests_public_matches_its_manifest(self):
        self.assertEqual(manifest_text(), MANIFEST.read_text(encoding='utf-8'),
                         'tests/public changed. If that is deliberate, run: python -B tests/internal/test_public_suite.py --write')

    def test_tests_public_uses_only_the_public_api_and_the_cli(self):
        public = public_names()
        for path in public_files():
            if path.suffix == '.py':
                with self.subTest(path=path.relative_to(ROOT).as_posix()):
                    self.assertEqual(private_uses(path, public), [])


    def test_private_uses_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test_x.py'
            path.write_text('import msf_tools as m\nfrom msf_tools import cli, Pack, snapshot\nfrom msf_tools.common import thaw\n'
                            'import msf_tools_ufbx\nfrom internal.adapters import fake_adapter\n'
                            'm.compile_pack, m.Pack, m.snapshot, cli.main, cli._error\n', encoding='utf-8')
            self.assertEqual(sorted(what for _, what in private_uses(path, public_names())),
                             sorted(['from msf_tools import snapshot', 'from msf_tools.common import thaw', 'import msf_tools_ufbx',
                                     'from internal.adapters import fake_adapter', 'm.snapshot', '._error']))

    def test_reaching_in_by_name_or_private_attribute_is_found(self):
        cases = {"importlib.import_module('msf_tools.common')\n": ["'msf_tools.common'"],
                 "patch('msf_tools.snapshot._ADAPTER_MODULES', {})\n": ["'msf_tools.snapshot._ADAPTER_MODULES'"],
                 'm.Pack._check_integrity\n': ['._check_integrity'],
                 'record._token\n': ['._token'],
                 'self._helper(); cls._built; record.__class__\n': []}
        with tempfile.TemporaryDirectory() as tmp:
            for source, expected in cases.items():
                with self.subTest(source=source):
                    path = Path(tmp) / 'test_x.py'
                    path.write_text('import msf_tools as m\n' + source, encoding='utf-8')
                    self.assertEqual([what for _, what in private_uses(path, public_names())], expected)

if __name__ == '__main__':
    if sys.argv[1:] == ['--write']:
        MANIFEST.write_text(manifest_text(), encoding='utf-8')
        print(f'Wrote {MANIFEST.relative_to(ROOT)} for {len(public_files())} files.')
    else:
        unittest.main()
