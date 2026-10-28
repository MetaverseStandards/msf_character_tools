# SPDX-License-Identifier: MIT
"""Work bounds and scheduling, measured through private mapping internals."""
import copy
from dataclasses import replace
import unittest
from unittest.mock import patch

import msf_character_tools as m
from msf_character_tools import mapping
from msf_character_tools.common import freeze, thaw
from msf_character_tools.report import Fault
from test_review_regressions import document, good, independent_rules


class ProfileWork(unittest.TestCase):
    def test_profile_and_pack_checks_are_bounded_per_operation(self):
        import msf_character_tools.mapping as mapping
        from msf_character_tools.pack import Pack
        for count in (3, 30, 60):
            pack = good(m.compile_pack(good(m.validate_authoring(independent_rules(count)))))
            source = good(m.profile_snapshot(pack, 'source'))
            target = good(m.profile_snapshot(pack, 'target'))
            compiled = None
            # Count how often fresh operations rebuild a full profile and check the
            # full pack. The counts use no elapsed time and no digests.
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
                    # Evaluation checks the pack once, inside the compiled mapping's own check.
                    self.assertLessEqual(len(pack_calls), {'compile': 4, 'export': 2, 'evaluate': 1}[operation])
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


if __name__ == '__main__':
    unittest.main()
