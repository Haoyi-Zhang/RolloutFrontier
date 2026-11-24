"""Portable finite frontier regression with a literal Cartesian specification.

The oracle enumerates local antichains and full support products; it does not call
producer or checker helpers. Search totals are counted over prefix products,
rather than obtained from the producer's recursive/pruned traversal.
"""
from __future__ import annotations

import builtins
import copy
from itertools import combinations, product
import json
from math import prod
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import checker, envelope


def powerset(values):
    return [tuple(part) for size in range(len(values) + 1)
            for part in combinations(values, size)]


def literal_truth(branches, state):
    return any(all(all(atom in state[node] for atom in required)
                   for node, required in branch.items()) for branch in branches)


def literal_corner_safe(branches, assigned):
    return all(any(all(all(atom in value for atom in branch[node])
                       for (node, _), value in zip(assigned, corner))
                   for branch in branches)
               for corner in product(*(guard for _, guard in assigned)))


def literal_cartesian_plan(branches, current, candidates, weights=None):
    """Complete bounded specification on valid fixtures with <=3 atoms/owner."""
    nodes = sorted(current)
    local, domains = {}, {}
    for node in nodes:
        relevant = sorted({atom for branch in branches for atom in branch[node]})
        if len(relevant) > 3:
            raise ValueError("test oracle domain: at most three atoms per owner")
        project = lambda values: tuple(atom for atom in relevant if atom in values)
        cur = project(current[node])
        raw = [project(profile) for profile in candidates[node]]
        masses = {profile: sum((1 if weights is None else weights[node][i])
                              for i, value in enumerate(raw) if value == profile)
                  for profile in sorted(set(raw))}
        masses.setdefault(cur, 0)
        profiles = sorted(masses)
        domains[node] = [list(profile) for profile in profiles]
        library = sorted({cur, *raw, *(project(branch[node]) for branch in branches)})
        choices = []
        for size in range(1, min(8, len(library)) + 1):
            for guard in combinations(library, size):
                if any(len(a) < len(b) and all(atom in b for atom in a)
                       for a in guard for b in guard):
                    continue
                if not any(all(atom in cur for atom in term) for term in guard):
                    continue
                accepts = lambda support: any(all(atom in support for atom in term)
                                               for term in guard)
                accepted = tuple(profile for profile in profiles if accepts(profile))
                supports = [support for support in powerset(relevant) if accepts(support)]
                choices.append(dict(guard=guard, accepted=accepted, supports=supports,
                                    mass=sum(masses[profile] for profile in accepted)))
        local[node] = choices

    def key(member):
        return tuple((node, tuple(map(tuple, member["box"][node]))) for node in nodes)

    safe = []
    for choices in product(*(local[node] for node in nodes)):
        if prod(len(choice["guard"]) for choice in choices) > 4096:
            continue
        if not all(literal_truth(branches, dict(zip(nodes, state)))
                   for state in product(*(choice["supports"] for choice in choices))):
            continue
        member = dict(
            box={node: [list(term) for term in choice["guard"]]
                 for node, choice in zip(nodes, choices)},
            product_mass=prod(choice["mass"] for choice in choices),
            local_masses={node: choice["mass"] for node, choice in zip(nodes, choices)},
            accepted_unique_profiles={node: len(choice["accepted"])
                                      for node, choice in zip(nodes, choices)},
            accepted_profiles={node: list(map(list, choice["accepted"]))
                               for node, choice in zip(nodes, choices)},
            guard_terms=sum(len(choice["guard"]) for choice in choices))
        safe.append((tuple(choice["accepted"] for choice in choices), member))
    representatives = {}
    for accepted, member in safe:
        previous = representatives.get(accepted)
        if previous is None or (member["guard_terms"], key(member)) < (
                previous["guard_terms"], key(previous)):
            representatives[accepted] = member
    front = [member for accepted, member in representatives.items()
             if not any(other != accepted and
                        all(all(profile in a for profile in b)
                            for a, b in zip(other, accepted))
                        for other in representatives)]
    front.sort(key=lambda member: (-member["product_mass"], member["guard_terms"], key(member)))
    best = min(front, key=lambda member: (-member["product_mass"],
               -sum(member["local_masses"].values()), member["guard_terms"], key(member)))

    # Count reached prefix products independently, without recursive visitation.
    order = sorted(nodes, key=lambda node: (len(local[node]), node))
    totals = dict(states=1, complete=len(safe), safe_complete=len(safe),
                  unsafe_pruned=0, corner_pruned=0)
    for depth in range(1, len(order) + 1):
        for choices in product(*(local[node] for node in order[:depth])):
            assigned = [(node, choice["guard"]) for node, choice in zip(order, choices)]
            parent = assigned[:-1]
            if (prod(len(guard) for _, guard in parent) > 4096 or
                    not literal_corner_safe(branches, parent)):
                continue
            if prod(len(guard) for _, guard in assigned) > 4096:
                totals["corner_pruned"] += 1
            elif not literal_corner_safe(branches, assigned):
                totals["unsafe_pruned"] += 1
            else:
                totals["states"] += 1
    answer = copy.deepcopy(best)
    answer.update(
        frontier=front, frontier_size=len(front), search=totals,
        objective=dict(domain="nondominated frontier members",
                       primary="candidate-profile product mass", secondary="sum of local masses",
                       tertiary="fewer guard terms", final="lexicographic box",
                       weights="uniform per supplied candidate" if weights is None else "supplied integers"),
        candidate_domains=domains,
        certificate=dict(safe=True, corners=prod(len(best["box"][node]) for node in nodes)),
        exact=True, scope="bounded positive guard library; supplied finite candidate profiles")
    return answer


def relation_fixtures():
    for bits in range(1, 511):
        cells = [(i, j) for i in range(3) for j in range(3) if bits & (1 << (3 * i + j))]
        branches = [{"0": [f"a{i}"], "1": [f"b{j}"]} for i, j in cells]
        candidates = {"0": [[f"a{i}"] for i in range(3)],
                      "1": [[f"b{j}"] for j in range(3)]}
        for i, j in cells:
            yield f"relation-{bits}-seed-{i}-{j}", branches, {
                "0": [f"a{i}"], "1": [f"b{j}"]}, candidates, None


def full_relation_fixtures():
    candidates = {"0": [[f"a{i}"] for i in range(3)],
                  "1": [[f"b{j}"] for j in range(3)]}
    for i, j in product(range(3), repeat=2):
        yield f"full-relation-{i}-{j}", [{"0": [], "1": []}], {
            "0": [f"a{i}"], "1": [f"b{j}"]}, candidates, None


def named_fixtures():
    lshape = [{"0": ["a"], "1": ["c"]}, {"0": ["a"], "1": ["d"]},
              {"0": ["b"], "1": ["c"]}]
    yield "weighted-lshape", lshape, {"0": ["a"], "1": ["c"]}, {
        "0": [["a"], ["b"]], "1": [["c"], ["d"]]}, {"0": [1, 9], "1": [8, 1]}
    yield "correlated-pair", [lshape[0], {"0": ["b"], "1": ["d"]}], {
        "0": ["a"], "1": ["c"]}, {"0": [["a"], ["b"]], "1": [["c"], ["d"]]}, None
    yield "zero-weight-nondominance", [{"0": ["a"]}, {"0": ["b"]}], {
        "0": ["a"]}, {"0": [["a"], ["b"]]}, {"0": [1, 0]}
    yield "empty-candidates-anchor", [{"0": ["a"], "1": []}], {
        "0": ["a", "irrelevant"], "1": ["unused"]}, {"0": [], "1": []}, None
    yield "duplicate-projection", [{"0": ["a"]}, {"0": ["b"]}], {"0": ["a"]}, {
        "0": [["a"], ["a", "unused"], ["b"], ["b"], []]}, {"0": [0, 2, 0, 3, 1]}
    yield "three-owner-correlation", [
        {str(node): ["a"] for node in range(3)}, {str(node): ["b"] for node in range(3)}], {
        str(node): ["a", "b"] for node in range(3)}, {
        str(node): [["a"], ["b"], ["a", "b"]] for node in range(3)}, None

    rng = random.Random(314159)
    for case in range(24):
        nodes = [str(i) for i in range(2 + case % 2)]
        profiles = {node: powerset((f"a{node}", f"b{node}")) for node in nodes}
        branches = [{node: list(rng.choice(profiles[node])) for node in nodes}
                    for _ in range(1 + case % 3)]
        current = {node: sorted({atom for branch in branches for atom in branch[node]})
                   for node in nodes}
        candidates = {node: [list(rng.choice(profiles[node])) for _ in range(case % 5)]
                      for node in nodes}
        if case % 3 == 0 and case % 5:
            for node in nodes:
                candidates[node].append(candidates[node][0] + ["irrelevant"])
        weighted = {node: [rng.randrange(4) for _ in candidates[node]] for node in nodes}
        for mode, weights in (
                ("uniform", None), ("zero", {node: [0] * len(candidates[node]) for node in nodes}),
                ("weighted", weighted)):
            yield f"positive-{case}-{mode}", branches, current, candidates, weights


def admission_controls():
    branches = [{"0": ["a"]}, {"0": ["b"]}]
    base = dict(branches=branches, current={"0": ["a"]},
                candidates={"0": [["a"], ["b"]]}, weights={"0": [1, 0]})
    for value in (0, -1, True, 1.0, 250001):
        yield f"state-limit-{value!r}", dict(base, max_states=value), "exact frontier search-state bound"
    for value in (-1, True, 1.0, 10**9 + 1, "1"):
        yield f"weight-{value!r}", dict(base, weights={"0": [value, 0]}), (
            "weights must be bounded nonnegative integers")
    yield "weight-length", dict(base, weights={"0": [1]}), "weight/profile mismatch"
    yield "weight-placement", dict(base, weights={"1": [1, 0]}), "weight placement mismatch"
    yield "nine-candidates", dict(base, candidates={"0": [["a"]] * 9}), "candidate bound"
    yield "nine-branches", dict(base, branches=[{"0": ["a"]}] * 9), "branch bound"
    yield "97-required-atoms", dict(base, branches=[{"0": [f"x{i}" for i in range(97)]}]), (
        "contract bound exceeded")
    yield "12001-support-atoms", dict(base, current={"0": [f"x{i}" for i in range(12001)]}), (
        "contract bound exceeded")
    yield "incompatible-current", dict(base, current={"0": []}), "current placement is incompatible"


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class TermMembershipRegression(unittest.TestCase):
    def check_fixture(self, fixture):
        name, branches, current, candidates, weights = fixture
        inputs = copy.deepcopy((branches, current, candidates, weights))
        expected = literal_cartesian_plan(branches, current, candidates, weights)
        actual = envelope.frontier_synthesize(branches, current, candidates, weights=weights)
        self.assertEqual(canonical(actual), canonical(expected), name)
        self.assertTrue(checker.frontier_certificate(
            branches, current, candidates, actual, weights=weights), name)
        self.assertEqual((branches, current, candidates, weights), inputs)
        return actual

    def test_complete_edge_encoded_three_by_three_frontiers(self):
        count = 0
        for fixture in relation_fixtures():
            with self.subTest(case=fixture[0]):
                self.check_fixture(fixture)
            count += 1
        self.assertEqual(count, 2295)

    def test_full_relation_projection_and_empty_requirements(self):
        for fixture in full_relation_fixtures():
            actual = self.check_fixture(fixture)
            self.assertEqual(actual["product_mass"], 9)
            self.assertEqual(actual["box"], {"0": [[]], "1": [[]]})

    def test_named_and_bounded_positive_weight_variants(self):
        fixtures = list(named_fixtures())
        self.assertEqual(len(fixtures), 78)
        for fixture in fixtures:
            with self.subTest(case=fixture[0]):
                self.check_fixture(fixture)

    def test_negative_weights_and_input_admission_precedence(self):
        for name, kwargs, message in admission_controls():
            with self.subTest(case=name):
                before = copy.deepcopy(kwargs)
                with self.assertRaises(ValueError) as caught:
                    envelope.frontier_synthesize(**kwargs)
                self.assertEqual(str(caught.exception), message)
                self.assertEqual(kwargs, before)
        # Refuse the cap before inspecting an invalid manifest or weights.
        with self.assertRaisesRegex(ValueError, "^exact frontier search-state bound$"):
            envelope.frontier_synthesize([], {}, {}, weights={}, max_states=0)

    def test_visited_state_cap_exact_below_and_above(self):
        fixture = next(named_fixtures())
        _, branches, current, candidates, weights = fixture
        actual = self.check_fixture(fixture)
        required = actual["search"]["states"]
        with self.assertRaisesRegex(ValueError, "^exact frontier search-state bound$"):
            envelope.frontier_synthesize(branches, current, candidates, weights, required - 1)
        for cap in (required, required + 1):
            self.assertEqual(canonical(envelope.frontier_synthesize(
                branches, current, candidates, weights, cap)), canonical(actual))
            self.assertTrue(checker.frontier_certificate(
                branches, current, candidates, actual, weights, combination_bound=cap))
        self.assertFalse(checker.frontier_certificate(
            branches, current, candidates, actual, weights, combination_bound=required - 1))

    def test_guard_library_corner_and_result_caps(self):
        self.assertEqual((envelope.MAX_OPTIONS, envelope.MAX_CORNERS,
                          envelope.MAX_FRONTIER_LIBRARY, envelope.MAX_FRONTIER_STATES,
                          envelope.MAX_FRONTIER_PLANS), (8, 4096, 10, 250000, 4096))
        with self.assertRaisesRegex(ValueError, "^option bound$"):
            envelope.antichain([[f"x{i}"] for i in range(9)])
        branches = [{"0": [f"x{i}"]} for i in range(8)]
        current = {"0": [f"x{i}" for i in range(8)]}
        at_ten = {"0": [["x0", "x1"]]}
        plan = envelope.frontier_synthesize(branches, current, at_ten)
        self.assertTrue(checker.frontier_certificate(branches, current, at_ten, plan))
        with self.assertRaisesRegex(ValueError, "^exact frontier local-library bound$"):
            envelope.frontier_synthesize(branches, current, {"0": at_ten["0"] + [["x2", "x3"]]})
        box = {str(node): [[f"x{i}"] for i in range(8)] for node in range(4)}
        true = [{node: [] for node in box}]
        self.assertEqual(envelope.verify_box(true, box), {"safe": True, "corners": 4096})
        self.assertTrue(checker.safe_envelope(true, box))
        box["4"] = [["x"], ["y"]]
        true[0]["4"] = []
        with self.assertRaisesRegex(ValueError, "^corner bound$"):
            envelope.verify_box(true, box)
        self.assertFalse(checker.safe_envelope(true, box))
        fixture = next(named_fixtures())
        with patch.object(envelope, "MAX_FRONTIER_PLANS", 1):
            with self.assertRaisesRegex(ValueError, "^exact frontier result bound$"):
                envelope.frontier_synthesize(*fixture[1:4], weights=fixture[4])
        self.assertEqual(envelope.MAX_FRONTIER_PLANS, 4096)

    def test_memberships_are_immutable_single_call_and_input_detached(self):
        fixture = next(named_fixtures())
        args = copy.deepcopy(fixture[1:])
        original = envelope._partial_safe
        with patch.object(envelope, "frozenset", side_effect=builtins.frozenset, create=True) as build:
            with patch.object(envelope, "_partial_safe", wraps=original) as safety:
                envelope.frontier_synthesize(*args[:3], weights=args[3])
            maps = [call.args[2] for call in safety.call_args_list]
            self.assertTrue(maps)
            self.assertTrue(all(mapping is maps[0] for mapping in maps))
            self.assertEqual(build.call_count, len(maps[0]))
            self.assertTrue(all(type(value) is builtins.frozenset and value == builtins.frozenset(term)
                                for term, value in maps[0].items()))
        self.assertEqual(args, fixture[1:])
        args[1]["0"] = ["a", "b"]
        altered = ("altered-second-call", *args)
        self.check_fixture(altered)

    def test_checker_rejects_nonselected_omission_and_type_aliases(self):
        actual = self.check_fixture(next(named_fixtures()))
        _, branches, current, candidates, weights = next(named_fixtures())
        selected = {key: actual[key] for key in actual["frontier"][0]}
        index = next(i for i, member in enumerate(actual["frontier"]) if member != selected)
        missing = copy.deepcopy(actual)
        missing["frontier"].pop(index)
        missing["frontier_size"] -= 1
        self.assertFalse(checker.frontier_certificate(branches, current, candidates, missing, weights))
        for field in ("frontier_size", "product_mass", "guard_terms"):
            mutant = copy.deepcopy(actual)
            mutant[field] = float(mutant[field])
            self.assertFalse(checker.frontier_certificate(branches, current, candidates, mutant, weights))
        mutant = copy.deepcopy(actual)
        mutant["search"]["states"] = True
        self.assertFalse(checker.frontier_certificate(branches, current, candidates, mutant, weights))

    def test_literal_corner_scan_empty_late_unsafe_and_large_terms(self):
        assigned = [(str(node), tuple((f"x{i}",) for i in range(8))) for node in range(4)]
        for branches in ([{str(node): [] for node in range(4)}],
                         [{str(node): [f"x{i}"] for node in range(4)} for i in range(8)]):
            sets = [{node: set(required) for node, required in branch.items()} for branch in branches]
            self.assertEqual(envelope._partial_safe(sets, assigned),
                             literal_corner_safe(branches, assigned))
        self.assertTrue(envelope._partial_safe([{}], []))
        late_box = {str(node): [["x0"], ["x1"]] for node in range(4)}
        late_branches = [{str(node): (["x0"] if node == selected else [])
                          for node in range(4)} for selected in range(4)]
        late_assigned = [(node, tuple(map(tuple, guard))) for node, guard in late_box.items()]
        self.assertFalse(literal_corner_safe(late_branches, late_assigned))
        self.assertEqual(envelope.verify_box(late_branches, late_box), {
            "safe": False, "corners": 16,
            "counterexample": {str(node): ["x1"] for node in range(4)}})
        branches = [{"0": ["a"], "1": [f"shared{i}" for i in range(95)] + ["left"]},
                    {"0": ["b"], "1": [f"shared{i}" for i in range(95)] + ["right"]}]
        current = {"0": ["a"], "1": sorted(set(branches[0]["1"] + branches[1]["1"]))}
        candidates = {"0": [["a"], ["b"]], "1": [current["1"]]}
        actual = envelope.frontier_synthesize(branches, current, candidates)
        self.assertEqual(len(actual["box"]["1"][0]), 97)
        self.assertTrue(checker.frontier_certificate(branches, current, candidates, actual))


if __name__ == "__main__":
    unittest.main()
