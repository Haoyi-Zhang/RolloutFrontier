"""Separate portable literal mask checks; retained five-test smoke count unchanged."""
from itertools import combinations, product
import unittest
from src import envelope


class MaskSafetyTests(unittest.TestCase):
    def test_all_two_atom_two_owner_two_branch_local_antichains(self):
        terms = [(), ("a",), ("b",), ("a", "b")]
        guards = [part for k in range(1, 5) for part in combinations(terms, k)
                  if not any(set(a) < set(b) for a in part for b in part)]
        cases = 0
        for requirements in product(terms, repeat=4):
            branches = [{"0": set(requirements[0]), "1": set(requirements[1])},
                        {"0": set(requirements[2]), "1": set(requirements[3])}]
            for left, right in product(guards, repeat=2):
                assigned = [("0", left), ("1", right)]
                expected = all(any(branch["0"].issubset(a) and branch["1"].issubset(b)
                                   for branch in branches) for a, b in product(left, right))
                memberships = {term: frozenset(term) for _, guard in assigned for term in guard}
                masks = envelope._branch_masks(branches, assigned, memberships)
                self.assertEqual(envelope._partial_safe(branches, assigned, memberships, masks), expected)
                self.assertEqual(envelope._partial_safe(branches, assigned), expected)
                cases += 1
        self.assertEqual(cases, 6400)

    def test_identical_term_different_owners_and_last_unsafe_corner(self):
        branches = [{"0": {"a"}, "1": set()}, {"0": set(), "1": {"b"}}]
        assigned = [("0", (("a",), ("b",))), ("1", (("a",), ("b",)))]
        masks = envelope._branch_masks(branches, assigned, {("a",): frozenset("a"), ("b",): frozenset("b")})
        self.assertNotEqual(masks["0", ("a",)], masks["1", ("a",)])
        self.assertFalse(envelope._partial_safe(branches, assigned))
        self.assertTrue(envelope._partial_safe([{}], []))
        self.assertFalse(envelope._partial_safe([], []))


if __name__ == "__main__":
    unittest.main()
