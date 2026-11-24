"""Portable full-powerset oracle for positive conjunctions, not singleton names.

The exact campaign enumerates every one/two-alternative manifest over two atoms
at each of two owners and every compatible current support. A deterministic
three-atom extension covers empty/duplicate candidates and nonnegative weights.
All safety checks in the oracle enumerate support vectors directly. The library
definition is shared as a specification, not via planner/checker helper imports.
Only JSON is printed; no files, sockets, subprocesses, or downloads are used.
"""
from __future__ import annotations
from itertools import combinations, product
from math import prod
import json
import random
import time

from src.checker import frontier_certificate
from src.controller import minimum_obstruction
from src.envelope import frontier_synthesize


def subsets(values):
    return [tuple(choice) for size in range(len(values) + 1)
            for choice in combinations(values, size)]


def truth(branches, state):
    return any(all(all(atom in state[n] for atom in requirement)
                   for n, requirement in branch.items()) for branch in branches)


def direct(branches, current, candidates, universes, weights=None):
    nodes = sorted(current)
    local = {}
    domains = {}
    for node in nodes:
        relevant = {atom for branch in branches for atom in branch[node]}
        cur = tuple(sorted(set(current[node]) & relevant))
        raw = [tuple(sorted(set(profile) & relevant)) for profile in candidates[node]]
        masses = {}
        ws = [1] * len(raw) if weights is None else weights[node]
        for profile, mass in zip(raw, ws):
            masses[profile] = masses.get(profile, 0) + mass
        masses.setdefault(cur, 0)
        profiles = sorted(masses)
        domains[node] = [list(profile) for profile in profiles]
        library = sorted({cur, *raw, *(tuple(sorted(branch[node])) for branch in branches)})
        choices = []
        for size in range(1, len(library) + 1):
            for guard in combinations(library, size):
                if len(guard) > 8 or any(set(a) < set(b) for a in guard for b in guard):
                    continue
                if not any(set(term).issubset(cur) for term in guard):
                    continue
                # Enumerate the complete abstract support domain, not guard corners.
                supports = [support for support in subsets(universes[node])
                            if any(set(term).issubset(support) for term in guard)]
                accepted = [profile for profile in profiles
                            if any(set(term).issubset(profile) for term in guard)]
                choices.append(dict(guard=guard, supports=supports, accepted=accepted,
                                    mass=sum(masses[profile] for profile in accepted)))
        local[node] = choices

    safe = []
    for choices in product(*(local[node] for node in nodes)):
        if prod(len(choice["guard"]) for choice in choices) > 4096:
            continue
        if not all(truth(branches, dict(zip(nodes, support)))
                   for support in product(*(choice["supports"] for choice in choices))):
            continue
        accepted = tuple(frozenset(choice["accepted"]) for choice in choices)
        box = {node: [list(term) for term in choice["guard"]]
               for node, choice in zip(nodes, choices)}
        entry = dict(box=box, product_mass=prod(choice["mass"] for choice in choices),
                     local_masses={node: choice["mass"] for node, choice in zip(nodes, choices)},
                     accepted_unique_profiles={node: len(choice["accepted"]) for node, choice in zip(nodes, choices)},
                     accepted_profiles={node: [list(profile) for profile in choice["accepted"]]
                                        for node, choice in zip(nodes, choices)},
                     guard_terms=sum(len(choice["guard"]) for choice in choices))
        safe.append((accepted, entry))

    def key(entry):
        return tuple((node, tuple(map(tuple, entry["box"][node]))) for node in nodes)
    representatives = {}
    for accepted, entry in safe:
        old = representatives.get(accepted)
        if old is None or (entry["guard_terms"], key(entry)) < (old["guard_terms"], key(old)):
            representatives[accepted] = entry
    frontier = [entry for accepted, entry in representatives.items()
                if not any(other != accepted and all(a.issuperset(b) for a, b in zip(other, accepted))
                           for other in representatives)]
    frontier.sort(key=lambda entry: (-entry["product_mass"], entry["guard_terms"], key(entry)))
    best = min(frontier, key=lambda entry: (-entry["product_mass"],
               -sum(entry["local_masses"].values()), entry["guard_terms"], key(entry)))
    return best, frontier, domains, len(safe)


def one(branches, current, candidates, universes, weights=None):
    expected, front, domains, safe = direct(branches, current, candidates, universes, weights)
    answer = frontier_synthesize(branches, current, candidates, weights=weights)
    assert frontier_certificate(branches, current, candidates, answer, weights=weights)
    assert answer["frontier"] == front
    assert answer["candidate_domains"] == domains
    assert all(answer[field] == value for field, value in expected.items())
    return safe, len(front), answer["search"]["states"]


def positive_campaign():
    universes = {"0": ("a", "b"), "1": ("c", "d")}
    profiles = {node: subsets(atoms) for node, atoms in universes.items()}
    candidates = {node: list(map(list, values)) for node, values in profiles.items()}
    alternatives = [{"0": list(left), "1": list(right)}
                    for left, right in product(profiles["0"], profiles["1"])]
    counts = dict(manifests=0, compatible_current_vectors=0, direct_safe_products=0,
                  frontier_members=0, planner_states=0, mismatches=0)
    for branch_count in (1, 2):
        for branches in combinations(alternatives, branch_count):
            counts["manifests"] += 1
            for current_pair in product(profiles["0"], profiles["1"]):
                current = {node: list(value) for node, value in zip(universes, current_pair)}
                if not truth(branches, current):
                    continue
                safe, front, states = one(list(branches), current, candidates, universes)
                counts["compatible_current_vectors"] += 1
                counts["direct_safe_products"] += safe
                counts["frontier_members"] += front
                counts["planner_states"] += states
    return counts


def weighted_extension():
    rng = random.Random(4242)
    universes = {"0": ("a", "b", "c"), "1": ("d", "e", "f")}
    profiles = {node: subsets(atoms) for node, atoms in universes.items()}
    safe_total = frontier_total = states_total = 0
    zero_weights = empty_candidates = duplicate_candidates = 0
    for case in range(48):
        branches = [{node: list(rng.choice(profiles[node])) for node in universes}
                    for _ in range(1 + case % 3)]
        possible = [pair for pair in product(*profiles.values())
                    if truth(branches, dict(zip(universes, pair)))]
        current = {node: list(value) for node, value in zip(universes, rng.choice(possible))}
        candidates = {node: [list(rng.choice(profiles[node])) for _ in range(case % 6)]
                      for node in universes}
        weights = {node: [rng.randrange(4) for _ in values] for node, values in candidates.items()}
        zero_weights += sum(weight == 0 for values in weights.values() for weight in values)
        empty_candidates += sum(not values for values in candidates.values())
        duplicate_candidates += sum(len(values) != len(set(map(tuple, values))) for values in candidates.values())
        safe, front, states = one(branches, current, candidates, universes, weights)
        safe_total += safe; frontier_total += front; states_total += states
    return dict(cases=48, seed=4242, direct_safe_products=safe_total,
                frontier_members=frontier_total, planner_states=states_total,
                supplied_zero_weights=zero_weights, owners_with_empty_candidates=empty_candidates,
                owners_with_duplicate_candidates=duplicate_candidates, mismatches=0)


def obstruction_campaign():
    universe = [(0, "a"), (0, "b"), (1, "a"), (1, "b")]
    values = [set(choice) for choice in subsets(universe)]
    cases = incompatible = 0
    for branches in product(values, repeat=3):
        for available in values:
            answer = minimum_obstruction(list(branches), available)
            if any(branch.issubset(available) for branch in branches):
                assert answer is None
            else:
                false = sorted(set().union(*branches) - available)
                optimum = next(list(choice) for choice in subsets(false)
                               if all(set(choice) & branch for branch in branches))
                assert answer == optimum
                incompatible += 1
            cases += 1
    return dict(cases=cases, incompatible=incompatible, mismatches=0,
                oracle="all false-atom subsets in cardinality/lexical order")


def full_relation_campaign():
    """The ninth cell does not make the full relation unrepresentable.

    A single true alternative covers it. With no relevant atoms, projection
    combines all three candidates into one zero-atom profile of weight three
    at each owner. The full weighted mass remains nine, not one.
    """
    universes = {"0": ("a0", "a1", "a2"), "1": ("b0", "b1", "b2")}
    branches = [{"0": [], "1": []}]
    candidates = {node: [[atom] for atom in atoms] for node, atoms in universes.items()}
    cases = safe_total = frontier_total = states_total = 0
    for left, right in product(universes["0"], universes["1"]):
        current = {"0": [left], "1": [right]}
        safe, front, states = one(branches, current, candidates, universes)
        plan = frontier_synthesize(branches, current, candidates)
        assert plan["box"] == {"0": [[]], "1": [[]]}
        assert plan["local_masses"] == {"0": 3, "1": 3}
        assert plan["product_mass"] == 9
        assert plan["candidate_domains"] == {"0": [[]], "1": [[]]}
        cases += 1; safe_total += safe; frontier_total += front; states_total += states
    return dict(relations=1, raw_current_cells=cases, direct_safe_products=safe_total,
                frontier_members=frontier_total, planner_states=states_total,
                product_mass=9, mismatches=0,
                encoding="one empty-requirement alternative; three candidate weights aggregate per owner")


def run():
    started, cpu = time.perf_counter(), time.process_time()
    result = dict(positive=positive_campaign(), weighted=weighted_extension(),
                  obstruction=obstruction_campaign(), full_3x3_relation=full_relation_campaign())
    result.update(wall_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu,
                  scope="complete declared two-atom domain plus fixed three-atom samples; no Linux/hardware claim")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
