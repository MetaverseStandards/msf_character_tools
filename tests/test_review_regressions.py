# SPDX-License-Identifier: MIT
"""Independent review regressions: bounded profile work and portable metadata."""
import copy
from dataclasses import replace
import gc
import json
import os
import re
import subprocess
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import tomllib

import msf_tools as m
from msf_tools import mapping
from msf_tools.common import freeze, thaw
from msf_tools.report import Fault

ROOT = Path(__file__).resolve().parents[1]
assert Path(m.__file__).resolve().parent.parent == ROOT


def document():
    return tomllib.loads((ROOT/'examples/authoring/pack.toml').read_text())


def good(result):
    assert result.ok, result.report.to_dict()
    return result.value


def independent_rules(count):
    doc = document()
    signal = doc['signals'][0]
    rule = doc['mappings'][0]['rules'][0]
    doc['signals'] = []
    doc['mappings'][0]['rules'] = []
    for i in range(count):
        for prefix in ('in', 'out'):
            row = copy.deepcopy(signal)
            row['id'] = f'{prefix}{i}'
            doc['signals'].append(row)
        row = copy.deepcopy(rule)
        row.update(id=f'r{i}', inputs=[f'in{i}'], outputs=[f'out{i}'])
        doc['mappings'][0]['rules'].append(row)
    doc['profiles'] = [{'id': 'source', 'label': 'Source', 'signal_ids': [f'in{i}' for i in range(count)]},
                       {'id': 'target', 'label': 'Target', 'signal_ids': [f'out{i}' for i in range(count)]}]
    return doc


class ProfileWork(unittest.TestCase):
    def test_profile_and_pack_checks_are_bounded_per_operation(self):
        import msf_tools.mapping as mapping
        from msf_tools.pack import Pack
        for count in (3, 30, 60):
            pack = good(m.compile_pack(good(m.validate_authoring(independent_rules(count)))))
            source = good(m.profile_snapshot(pack, 'source'))
            target = good(m.profile_snapshot(pack, 'target'))
            compiled = None
            # Count actual full-profile reconstruction and full-pack checking,
            # with fresh operations; no elapsed-time or digest-derived oracle.
            for operation in ('compile', 'export', 'evaluate'):
                if operation != 'compile' and compiled is None:
                    compiled = good(m.compile_mapping(pack, source, target, 'wink'))
                original = Pack._check_integrity
                pack_calls = []
                def check_pack(record):
                    pack_calls.append(record)
                    return original(record)
                with patch.object(mapping, '_check_profile', wraps=mapping._check_profile) as profiles, \
                        patch.object(Pack, '_check_integrity', check_pack):
                    if operation == 'compile':
                        compiled = good(m.compile_mapping(pack, source, target, 'wink'))
                    elif operation == 'export':
                        compiled.to_dict()
                    else:
                        values = {f'in{i}': -0.5 for i in range(count)}
                        frame = {'timestamp': 0, 'values': values, 'validity': dict.fromkeys(values, True)}
                        output = good(m.evaluate_mapping(compiled, [frame])).to_dict()
                        self.assertEqual(output['samples'][0]['values'], {f'out{i}': -0.5 for i in range(count)})
                print(f'rules={count} operation={operation} full_profiles={profiles.call_count} full_pack_checks={len(pack_calls)}')
                with self.subTest(count=count, operation=operation):
                    self.assertLessEqual(profiles.call_count, 4 if operation == 'compile' else 2)
                    self.assertLessEqual(len(pack_calls), 4 if operation == 'compile' else 2)
            self.assertEqual([r['id'] for r in compiled.instructions], [f'r{i}' for i in range(count)])

    def test_later_operations_recheck_mutated_and_copied_dependencies(self):
        for dependency in ('pack', 'source', 'target'):
            for mutation in ('copy', 'replace', 'raw', 'owned_state'):
                with self.subTest(dependency=dependency, mutation=mutation):
                    pack = good(m.compile_pack(good(m.validate_authoring(document()))))
                    source = good(m.profile_snapshot(pack, 'source'))
                    target = good(m.profile_snapshot(pack, 'target'))
                    compiled = good(m.compile_mapping(pack, source, target, 'wink'))
                    compiled.to_dict()  # A previous successful check cannot grant later admission.
                    record = {'pack': pack, 'source': source, 'target': target}[dependency]
                    if mutation in ('copy', 'replace'):
                        bad = copy.copy(record) if mutation == 'copy' else replace(record)
                        if dependency == 'pack': pack = bad
                        elif dependency == 'source': source = bad
                        else: target = bad
                        object.__setattr__(compiled, {'source': 'source_snapshot', 'target': 'target_snapshot'}.get(dependency, dependency), bad)
                    elif mutation == 'raw':
                        field = 'sha256' if dependency == 'pack' else 'original_bytes'
                        object.__setattr__(record, field, '0'*64 if dependency == 'pack' else record.original_bytes+b' ')
                    else:
                        changed = record.to_dict() if dependency == 'pack' else thaw(record.document)
                        if dependency == 'pack': changed['signals'][0]['domain']['min'] = -2
                        else: changed['channels'] = {}
                        object.__setattr__(record, 'document', freeze(changed))
                    for result in (m.compile_mapping(pack, source, target, 'wink'),
                                   m.evaluate_mapping(compiled, [])):
                        self.assertIsNone(result.value)
                        self.assertEqual([d.code for d in result.report.diagnostics], ['E_RECORD_INTEGRITY'])
                    with self.assertRaises(Fault) as caught: compiled.to_dict()
                    self.assertEqual(caught.exception.diagnostic.code, 'E_RECORD_INTEGRITY')
        old_pack = good(m.compile_pack(good(m.validate_authoring(document()))))
        old_source = good(m.profile_snapshot(old_pack, 'source'))
        changed = document(); changed['signals'][0]['label'] = 'New label'
        new_pack = good(m.compile_pack(good(m.validate_authoring(changed))))
        result = m.compile_mapping(new_pack, old_source, good(m.profile_snapshot(new_pack, 'target')), 'wink')
        self.assertIsNone(result.value)
        self.assertIn('E_STALE_SOURCE', [d.code for d in result.report.diagnostics])

    def test_declaration_waves_keep_literal_order(self):
        doc = independent_rules(3)
        doc['signals'].append(dict(copy.deepcopy(doc['signals'][0]), id='mid'))
        rules = doc['mappings'][0]['rules']
        rules[0]['inputs'] = ['mid']
        first = dict(copy.deepcopy(rules[0]), id='first', inputs=['in0'], outputs=['mid'])
        doc['mappings'][0]['rules'] = [rules[0], rules[1], first, rules[2]]
        pack = good(m.compile_pack(good(m.validate_authoring(doc))))
        compiled = good(m.compile_mapping(pack, good(m.profile_snapshot(pack, 'source')),
                                        good(m.profile_snapshot(pack, 'target')), 'wink'))
        self.assertEqual([r['id'] for r in compiled.instructions], ['r1', 'first', 'r2', 'r0'])
        self.assertEqual(compiled.required_inputs, ('in1', 'in0', 'in2'))
        self.assertEqual(compiled.output_ids, ('out0', 'out1', 'out2'))


def scalar_signal(id):
    return {'id': id, 'label': id, 'value_type': 'scalar', 'units': '1', 'domain': {}, 'calibration': 'literal',
            'disposition': 'mapped', 'evidence': ['e'], 'evidence_status': 'verified_current'}


def identity_rule(id, source, target):
    return {'id': id, 'inputs': [source], 'outputs': [target], 'operator': {'id': 'identity'}, 'disposition': 'mapped',
            'mapping_quality': 'exact', 'assumptions': [], 'evidence': ['e'], 'evidence_status': 'verified_current',
            'loss_annotations': []}


def graph(signals, rules, source, target):
    """Minimal authoring for one mapping named 'graph'."""
    return {'schema_version': '1.0', 'data_version': '0.1.0', 'operator_version': '1.0', 'id': 'graph', 'license': 'MIT',
            'signals': [scalar_signal(s) for s in signals],
            'profiles': [{'id': 'source', 'label': 'source', 'signal_ids': source},
                         {'id': 'target', 'label': 'target', 'signal_ids': target}],
            'mappings': [{'id': 'graph', 'rules': rules}],
            'evidence': [{'id': 'e', 'claim': 'Synthetic dependency graph.', 'status': 'verified_current',
                          'license': 'MIT', 'authorship': 'MSF Tools contributors'}]}


def compile_graph(doc):
    pack = good(m.compile_pack(good(m.validate_authoring(doc))))
    return m.compile_mapping(pack, good(m.profile_snapshot(pack, 'source')),
                             good(m.profile_snapshot(pack, 'target')), 'graph')


class GraphOrdering(unittest.TestCase):
    def test_dependent_rule_waits_for_whole_previous_wave(self):
        # [A depends on B, B, C] runs as [B, C, A], not [B, A, C].
        doc = graph(['x', 'b', 'c', 'a'], [identity_rule('A', 'b', 'a'), identity_rule('B', 'x', 'b'),
                                          identity_rule('C', 'x', 'c')], ['x'], ['a', 'c'])
        compiled = good(compile_graph(doc))
        self.assertEqual([r['id'] for r in compiled.instructions], ['B', 'C', 'A'])

    def test_waves_mix_depths_in_declaration_order(self):
        rules = [identity_rule('D', 'a', 'd'), identity_rule('A', 'b', 'a'), identity_rule('E', 'x', 'e'),
                 identity_rule('B', 'x', 'b'), identity_rule('F', 'e', 'f')]
        doc = graph(['x', 'a', 'b', 'd', 'e', 'f'], rules, ['x'], ['d', 'f'])
        compiled = good(compile_graph(doc))
        self.assertEqual([r['id'] for r in compiled.instructions], ['E', 'B', 'A', 'F', 'D'])

    def test_cycle_behind_valid_rules_is_reported_once(self):
        rules = [identity_rule('A', 'x', 'a'), identity_rule('P', 'q', 'p'), identity_rule('Q', 'p', 'q')]
        result = compile_graph(graph(['x', 'a', 'p', 'q'], rules, ['x'], ['a']))
        self.assertIsNone(result.value)
        self.assertEqual([d.code for d in result.report.diagnostics], ['E_MAPPING_CYCLE'])

    def test_scheduler_passes_over_rules_do_not_grow_with_chain_length(self):
        class Rules(list):
            passes = 0

            def __iter__(self):
                Rules.passes += 1
                return super().__iter__()

        count = 2000
        rules = Rules({'id': f'r{i}'} for i in reversed(range(count)))
        dependencies = {f'r{i}': {f'r{i - 1}'} if i else set() for i in range(count)}
        Rules.passes = 0
        ordered = mapping._dependency_waves(rules, dependencies)
        self.assertEqual([r['id'] for r in ordered], [f'r{i}' for i in range(count)])
        # Rescanning every rule once per wave would make one pass per link.
        self.assertLessEqual(Rules.passes, 4)

    def test_scheduler_keeps_declaration_order_and_stops_at_cycles(self):
        rules = [{'id': rid} for rid in ('A', 'B', 'C', 'P', 'Q', 'R')]
        dependencies = {'A': {'B'}, 'B': set(), 'C': set(), 'P': {'Q'}, 'Q': {'P'}, 'R': {'R'}}
        self.assertEqual([r['id'] for r in mapping._dependency_waves(rules, dependencies)], ['B', 'C', 'A'])

    @unittest.skipUnless(os.environ.get('MSF_SLOW_TESTS') == '1', 'Set MSF_SLOW_TESTS=1 to run timed checks.')
    def test_long_chain_compiles_within_cpu_budget(self):
        # On the reference machine, record integrity checks take about two thirds
        # of this budget; rescanning every rule per wave roughly doubled it.
        count = 3000
        rules = [identity_rule(f'r{i}', f's{i}', f's{i + 1}') for i in reversed(range(count))]
        doc = graph([f's{i}' for i in range(count + 1)], rules, ['s0'], [f's{count}'])
        pack = good(m.compile_pack(good(m.validate_authoring(doc))))
        source, target = good(m.profile_snapshot(pack, 'source')), good(m.profile_snapshot(pack, 'target'))
        gc.disable()
        try:
            start = time.process_time()
            compiled = good(m.compile_mapping(pack, source, target, 'graph'))
            elapsed = time.process_time() - start
        finally:
            gc.enable()
        self.assertEqual([r['id'] for r in compiled.instructions], [f'r{i}' for i in range(count)])
        self.assertLess(elapsed, 0.7, 'CPU seconds')



# Explicit independent policy corpus: Python whitespace plus U+FEFF. Controls
# U+001C..1F keep their previous rejection; non-whitespace Unicode stays valid.
BLANK_CODEPOINTS = [*range(0x09, 0x0E), *range(0x1C, 0x21), 0x85, 0xA0, 0x1680,
                    *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF]
TEXT_CASES = [(chr(code), False) for code in BLANK_CODEPOINTS]
TEXT_CASES += [('', False), (' \ufeff\u0085\u001c\t', False),
               ('é', True), ('漢字', True), ('😀', True), ('\u200b', True),
               ('\u180e', True), ('\ufeffé\u0085', True), ('\u001c漢字\ufeff', True)]
JSC = Path('/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc')


def schema_patterns(schemas):
    found = []
    def visit(value):
        if isinstance(value, dict):
            if 'pattern' in value: found.append(value['pattern'])
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    for schema in schemas: visit(schema)
    return list(dict.fromkeys(found))


def ecmascript_results(patterns, texts):
    # A real ECMAScript engine executes the actual schema bytes. Use JSON argv
    # transport, never a shell, and count no unavailable-engine run as a pass.
    code = ('var patterns=' + json.dumps(patterns) + ';var texts=' + json.dumps(texts) + ';'
            'print(JSON.stringify(patterns.map(function(p){var r=new RegExp(p);'
            'return texts.map(function(s){return r.test(s);});})));')
    result = subprocess.run([str(JSC), '-e', code], capture_output=True, text=True, check=True)
    return {(p, t): valid for p, row in zip(patterns, json.loads(result.stdout))
            for t, valid in zip(texts, row)}


def metadata_documents():
    # Every optional description (including both coupling shapes) and opaque
    # metadata are independent inputs. Numeric/bool alternatives are controls.
    for field in ('region', 'side', 'native_id', 'surface', 'time', 'confidence', 'validity', 'coupling'):
        for text, expected in TEXT_CASES:
            doc = document(); doc['signals'][0][field] = text
            yield ('signal', field, repr(text)), doc, expected
    for scope in ('signal', 'rule'):
        for text, expected in TEXT_CASES:
            doc = document()
            row = doc['signals'][0] if scope == 'signal' else doc['mappings'][0]['rules'][0]
            row['coupling'] = [text]
            yield (scope, 'coupling[]', repr(text)), copy.deepcopy(doc), expected
            if scope == 'rule':
                row['coupling'] = text
                yield (scope, 'coupling', repr(text)), doc, expected
    for field, value, expected in [('coupling', [], True), ('coupling', ['é', '漢字'], True),
                                   ('coupling', ['é', 'é'], False), ('coupling', [True], False),
                                   ('confidence', 0, True), ('confidence', 1, True),
                                   ('confidence', False, False), ('confidence', 2, False),
                                   ('validity', True, True), ('validity', False, True),
                                   ('region', None, False), ('time', [], False),
                                   ('metadata', {'description': '\ufeff\u0085\u001c', '漢字': '😀'}, True)]:
        doc = document(); doc['signals'][0][field] = value
        yield ('signal', field, repr(value)), doc, expected


class UnicodeMetadata(unittest.TestCase):
    def test_runtime_full_optional_metadata_policy(self):
        cases = list(metadata_documents())
        for label, doc, expected in cases:
            with self.subTest(input=label):
                result = m.validate_authoring(doc)
                self.assertEqual(result.ok, expected, result.report.to_dict())
                if expected:
                    pack = good(m.compile_pack(result.value))
                    self.assertEqual(pack.to_dict(), doc)
                    self.assertEqual(pack.to_bytes(), (json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                                                 allow_nan=False, indent=2)+'\n').encode())
                else:
                    self.assertIsNone(result.value)
                    self.assertTrue({'E_TYPE', 'E_DUPLICATE'} & {d.code for d in result.report.diagnostics})
        print(f'runtime_full_optional_metadata_cases={len(cases)}')

    def test_real_validators_share_full_optional_metadata_policy(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('Optional jsonschema test tool unavailable')
        if not JSC.is_file(): self.skipTest('ECMAScript JavaScriptCore test tool unavailable')
        schemas = [json.loads((ROOT/'schemas'/name).read_text())
                   for name in ('authoring.schema.json', 'pack.schema.json')]
        cases = list(metadata_documents())
        texts = set()
        def strings_in(value):
            if isinstance(value, str): texts.add(value)
            elif isinstance(value, dict):
                for item in value.values(): strings_in(item)
            elif isinstance(value, list):
                for item in value: strings_in(item)
        for _, doc, _ in cases: strings_in(doc)
        matches = ecmascript_results(schema_patterns(schemas), sorted(texts))
        # Real Draft202012 validation with the pattern keyword evaluated by
        # JavaScriptCore; all other keywords use the stock jsonschema validator.
        # This is not a standalone JavaScript schema-validator claim.
        def ecma_pattern(validator, pattern, instance, schema):
            if isinstance(instance, str) and not matches[pattern, instance]:
                yield jsonschema.ValidationError('String fails the ECMAScript schema pattern')
        ECMAValidator = jsonschema.validators.extend(jsonschema.Draft202012Validator, {'pattern': ecma_pattern})
        validators = []
        for schema in schemas:
            jsonschema.Draft202012Validator.check_schema(schema)
            validators.extend([jsonschema.Draft202012Validator(schema), ECMAValidator(schema)])
        for label, doc, expected in cases:
            for i, validator in enumerate(validators):
                with self.subTest(input=label, engine=('Python', 'ECMAScript')[i % 2], schema=i // 2):
                    self.assertEqual(validator.is_valid(doc), expected)
        print(f'full_optional_metadata_cases={len(cases)} schemas=2 regex_engines=2')

    def test_every_nonblank_schema_pattern_matches_both_regex_engines(self):
        if not JSC.is_file(): self.skipTest('ECMAScript JavaScriptCore test tool unavailable')
        schemas = [json.loads((ROOT/'schemas'/name).read_text())
                   for name in ('authoring.schema.json', 'pack.schema.json')]
        # Select string/description patterns structurally, excluding unrelated
        # URL/hash/version patterns; do not manufacture an expected pattern.
        locations = []
        def visit(value, path):
            if isinstance(value, dict):
                if 'pattern' in value and value.get('minLength') == 1:
                    locations.append((path, value['pattern']))
                for key, item in value.items(): visit(item, path+'/'+key)
            elif isinstance(value, list):
                for i, item in enumerate(value): visit(item, path+'/'+str(i))
        for i, schema in enumerate(schemas): visit(schema, str(i))
        self.assertGreater(len(locations), 50)  # Both full schemas, not one coupling branch.
        matches = ecmascript_results(list(dict.fromkeys(p for _, p in locations)), [t for t, _ in TEXT_CASES])
        for path, pattern in locations:
            for text, expected in TEXT_CASES:
                for engine, valid in [('Python', re.search(pattern, text) is not None),
                                      ('ECMAScript', matches[pattern, text])]:
                    with self.subTest(path=path, text=repr(text), engine=engine):
                        self.assertEqual(valid, expected)
        print(f'nonblank_schema_locations={len(locations)} text_cases={len(TEXT_CASES)} regex_engines=2')


if __name__ == '__main__':
    unittest.main()
