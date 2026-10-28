# SPDX-License-Identifier: MIT
"""Source path grammar `path-sorted-v2`: escaping, parsing, locators and order."""
import random
import unittest

from msf_character_tools.sources import paths

SPECIAL = '%/#[]:\x00\x01\x1f\x7f'
ALPHABET = SPECIAL + 'abcXYZ09 .-_é漢\U0001F600'


def names(count, seed=7):
    rng = random.Random(seed)
    return [''.join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 6))) for _ in range(count)]


class PathGrammar(unittest.TestCase):
    def test_escaping_round_trips_and_hides_every_special_character(self):
        for name in names(500):
            escaped = paths.escape(name)
            self.assertEqual(paths.unescape(escaped), name)
            self.assertFalse(set(escaped) & set(SPECIAL.replace('%', '')), escaped)
        self.assertEqual(paths.escape('a/b#c[0]:%'), 'a%2Fb%23c%5B0%5D%3A%25')
        self.assertEqual(paths.escape('\x00é'), '%00é')

    def test_node_paths_round_trip_with_duplicate_indices_and_helpers(self):
        rng = random.Random(3)
        for _ in range(200):
            components = [(name, rng.choice([None, 0, 1, 12])) for name in names(rng.randint(1, 4), rng.randint(0, 10**6))]
            helper = rng.choice([None, ('geometry', None), ('scale', None), ('scale', 2)])
            path = paths.node_path(components, helper)
            self.assertEqual(paths.parse_node_path(path), (components, helper))

    def test_names_with_separators_stay_single_components(self):
        self.assertEqual(paths.node_path([('a/b', None), ('c', None)]), '/a%2Fb/c')
        self.assertNotEqual(paths.node_path([('Skeleton.joints', None), ('j0', None)]),
                            paths.node_path([('Skeleton', None), ('joints', None), ('j0', None)]))
        self.assertNotEqual(paths.node_path([('n', None)], ('geometry', None)), paths.node_path([('n', None)], ('scale', None)))
        self.assertNotEqual(paths.node_path([('n', 0)]), paths.node_path([('n[0]', None)]))

    def test_locators_on_helper_nodes_round_trip(self):
        # A reader can put an instanced mesh on a geometry helper node.
        node = paths.node_path([('Body', None)], ('geometry', None))
        key = paths.target_key([('Blend', None), ('smile', None)])
        self.assertEqual(paths.split_locator(paths.locator(node, key)), (node, key))

    def test_locators_split_at_the_unescaped_hash_before_the_key(self):
        node = paths.node_path([('Face#1', None)])
        key = paths.target_key([('Blend#A', None), ('smile:L', 1)])
        locator = paths.locator(node, key)
        self.assertEqual(paths.split_locator(locator), (node, key))
        self.assertEqual(paths.parse_target_key(key), [('Blend#A', None), ('smile:L', 1)])

    def test_malformed_paths_and_keys_are_refused(self):
        # Source names may be empty (FBX allows it), so '/' and '' are well formed.
        self.assertEqual(paths.parse_node_path('/'), ([('', None)], None))
        self.assertEqual(paths.parse_target_key(''), [('', None)])
        for bad in ('', 'relative', '/a%2fb', '/a%41', '/a%2', '/a[01]', '/a[x]', '/a]', '/a:b', '/a\x01',
                    '/a#helper:other', '/a#helper:scale[]', '/a#other', '/a#helper:geometry#helper:scale'):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                paths.parse_node_path(bad)
        for bad in ('a#b', 'a[1', 'a%zz', 'a:b', '%41'):
            with self.subTest(key=bad), self.assertRaises(ValueError):
                paths.parse_target_key(bad)
        for bad in ('/a', 'a#k', '#k', '/a#helper:other#k', '/a#helper:scale', '/a#b#k'):
            with self.subTest(locator=bad), self.assertRaises(ValueError):
                paths.split_locator(bad)

    def test_order_is_by_unescaped_components_parents_first(self):
        unordered = [paths.node_path(c) for c in (
            [('b', None)], [('a', None), ('z', None)], [('a', None)], [('a', 1)], [('a', 0)], [('A', None)],
            [('a/b', None)], [('a', None), ('%', None)], [('é', None)])]
        ordered = sorted(unordered, key=paths.sort_key)
        self.assertEqual([paths.parse_node_path(p)[0] for p in ordered], [
            [('A', None)], [('a', None)], [('a', None), ('%', None)], [('a', None), ('z', None)],
            [('a', 0)], [('a', 1)], [('a/b', None)], [('b', None)], [('é', None)]])
        helper = paths.node_path([('a', None)], ('geometry', None))
        self.assertLess(paths.sort_key('/a'), paths.sort_key(helper))
        self.assertLess(paths.sort_key(helper), paths.sort_key('/a/b'))


if __name__ == '__main__':
    unittest.main()
