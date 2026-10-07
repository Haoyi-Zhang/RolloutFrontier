"""Finite product-closed rollout envelopes and bounded exact synthesis.

The greedy planner is retained as a transparent baseline.  ``frontier_synthesize``
searches the complete finite guard language induced by the supplied current,
candidate, and branch-local conjunctions.  It is exact only when it terminates
within its explicit library, guard, corner, and search-state bounds.
"""
from __future__ import annotations
from itertools import product
from math import prod
from typing import Iterable
from .controller import atoms, MAX_REQUIREMENTS, MAX_CONTRACTS, MAX_NODES, MAX_BRANCHES

MAX_CORNERS = 4096
MAX_OPTIONS = 8
MAX_FRONTIER_LIBRARY = 10
MAX_FRONTIER_STATES = 250_000
MAX_FRONTIER_PLANS = 4096


def normalize(branches: list[dict[str, list[str]]]) -> list[dict[str, list[str]]]:
    if not isinstance(branches, list) or not 1 <= len(branches) <= MAX_BRANCHES:
        raise ValueError("branch bound")
    nodes = sorted(branches[0])
    if not nodes or len(nodes) > MAX_NODES:
        raise ValueError("placement bound")
    if any(not isinstance(n, str) or n != str(int(n)) or not 0 <= int(n) < MAX_NODES for n in nodes):
        raise ValueError("node identity")
    if any(sorted(branch) != nodes for branch in branches):
        raise ValueError("envelopes require a common fixed placement")
    return [{n: atoms(branch[n], MAX_REQUIREMENTS) for n in nodes} for branch in branches]


def antichain(options: list[list[str]]) -> list[list[str]]:
    if not isinstance(options, list) or not 1 <= len(options) <= MAX_OPTIONS:
        raise ValueError("option bound")
    # A profile-derived term may contain requirements from several alternatives.
    # The per-alternative requirement cap is not a cap on their projected union.
    values = sorted({tuple(atoms(x, MAX_CONTRACTS)) for x in options})
    return [list(x) for x in values if not any(set(y) < set(x) for y in values)]


def _unbounded_antichain(options: Iterable[tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    """Canonicalize a local library subset before applying the public term bound."""
    values = sorted(set(options))
    return tuple(x for x in values if not any(set(y) < set(x) for y in values))


def corners(box: dict[str, list[list[str]]]):
    nodes = sorted(box)
    if not nodes or len(nodes) > MAX_NODES or any(not box[n] for n in nodes):
        raise ValueError("empty or oversized box")
    if prod(len(box[n]) for n in nodes) > MAX_CORNERS:
        raise ValueError("corner bound")
    for values in product(*(box[n] for n in nodes)):
        yield {n: set(s) for n, s in zip(nodes, values)}


def compatible(branches: list[dict[str, list[str]]], state: dict[str, set[str]]) -> bool:
    return any(all(set(required).issubset(state[n]) for n, required in branch.items())
               for branch in branches)


def verify_box(branches: list[dict[str, list[str]]], box: dict[str, list[list[str]]]) -> dict:
    branches = normalize(branches)
    if sorted(box) != sorted(branches[0]):
        raise ValueError("box placement mismatch")
    box = {n: antichain(o) for n, o in box.items()}
    checked = 0
    for state in corners(box):
        checked += 1
        if not compatible(branches, state):
            return dict(safe=False, corners=checked,
                        counterexample={n: sorted(s) for n, s in state.items()})
    return dict(safe=True, corners=checked)


def _projected_inputs(branches: list[dict[str, list[str]]], current: dict[str, list[str]],
                      candidates: dict[str, list[list[str]]]):
    nodes = sorted(branches[0])
    if sorted(current) != nodes or sorted(candidates) != nodes:
        raise ValueError("placement mismatch")
    relevant = {n: set().union(*(set(b[n]) for b in branches)) for n in nodes}
    projected_current = {
        n: tuple(sorted(set(atoms(current[n], 12000)) & relevant[n])) for n in nodes
    }
    projected_candidates: dict[str, list[tuple[str, ...]]] = {}
    for n in nodes:
        if not isinstance(candidates[n], list) or len(candidates[n]) > MAX_OPTIONS:
            raise ValueError("candidate bound")
        projected_candidates[n] = [
            tuple(sorted(set(atoms(c, 12000)) & relevant[n])) for c in candidates[n]
        ]
    return nodes, relevant, projected_current, projected_candidates


def synthesize(branches: list[dict[str, list[str]]], current: dict[str, list[str]],
               candidates: dict[str, list[list[str]]]) -> dict:
    """Greedy inclusion-maximal planning baseline over supplied candidates.

    Current support and candidate profiles are projected onto declared atoms.
    This is neither a maximum-volume rectangle nor a maximum-availability plan.
    Candidate order (node ID, lexical atom tuple) is fixed before evaluation.
    """
    branches = normalize(branches)
    nodes, _, projected_current, projected_candidates = _projected_inputs(
        branches, current, candidates)
    box = {n: [list(projected_current[n])] for n in nodes}
    if not verify_box(branches, box)["safe"]:
        raise ValueError("current placement is incompatible")
    rejected, bounded = [], []
    tests = 1
    for n in nodes:
        options = sorted(set(projected_candidates[n]))
        for option in options:
            trial = {k: [list(x) for x in v] for k, v in box.items()}
            # A redundant stronger predicate changes no accepted domain.
            if any(set(o).issubset(option) for o in trial[n]):
                continue
            try:
                trial[n] = antichain(trial[n] + [list(option)])
                result = verify_box(branches, trial)
                tests += 1
            except ValueError as exc:
                bounded.append(dict(node=n, option=list(option), reason=str(exc)))
                continue
            if result["safe"]:
                box = trial
            else:
                rejected.append(dict(node=n, option=list(option),
                                     counterexample=result["counterexample"]))
    return dict(box=box, tests=tests, rejected=rejected, bounded=bounded,
                certificate=verify_box(branches, box))


def _weights_for(node: str, raw_profiles: list[tuple[str, ...]],
                 weights: dict[str, list[int]] | None) -> dict[tuple[str, ...], int]:
    if weights is None:
        values = [1] * len(raw_profiles)
    else:
        if node not in weights:
            raise ValueError("weight placement mismatch")
        values = weights[node]
        if not isinstance(values, list) or len(values) != len(raw_profiles):
            raise ValueError("weight/profile mismatch")
        if any(type(w) is not int or not 0 <= w <= 10**9 for w in values):
            raise ValueError("weights must be bounded nonnegative integers")
    result: dict[tuple[str, ...], int] = {}
    for profile, weight in zip(raw_profiles, values):
        result[profile] = result.get(profile, 0) + weight
    return result


def candidate_volume(box: dict[str, list[list[str]]], candidates: dict[str, list[list[str]]],
                     weights: dict[str, list[int]] | None = None) -> dict:
    """Measure a guard on the supplied finite candidate-profile domain.

    The product mass is a combinatorial objective, not a probability or fleet
    estimate. Duplicate projected profiles aggregate their supplied weights.
    """
    nodes = sorted(box)
    if sorted(candidates) != nodes:
        raise ValueError("candidate placement mismatch")
    if weights is not None and sorted(weights) != nodes:
        raise ValueError("weight placement mismatch")
    local_masses, accepted, local_profiles = {}, {}, {}
    for n in nodes:
        if not isinstance(candidates[n], list) or len(candidates[n]) > MAX_OPTIONS:
            raise ValueError("candidate bound")
        raw = [tuple(atoms(p, 12000)) for p in candidates[n]]
        by_profile = _weights_for(n, raw, weights)
        options = [set(x) for x in antichain(box[n])]
        accepted_profiles = [p for p in sorted(by_profile) if any(o.issubset(p) for o in options)]
        local_masses[n] = sum(by_profile[p] for p in accepted_profiles)
        accepted[n] = [list(p) for p in accepted_profiles]
        local_profiles[n] = len(accepted_profiles)
    return dict(product_mass=prod(local_masses.values()), local_masses=local_masses,
                accepted_profiles=accepted, accepted_unique_profiles=local_profiles,
                scope="supplied finite candidate profiles; not an execution probability")


def _partial_safe(branch_sets: list[dict[str, set[str]]],
                  assigned: list[tuple[str, tuple[tuple[str, ...], ...]]],
                  term_memberships: dict[tuple[str, ...], frozenset[str]] | None = None) -> bool:
    """Necessary-and-sufficient safety test once all nodes are assigned."""
    if term_memberships is None:
        term_memberships = {term: frozenset(term)
                            for term in {term for _, guard in assigned for term in guard}}
    for local_values in product(*(guard for _, guard in assigned)):
        possible = False
        for branch in branch_sets:
            if all(branch[node].issubset(term_memberships[value])
                   for (node, _), value in zip(assigned, local_values)):
                possible = True
                break
        if not possible:
            return False
    return True


def _local_guards(node: str, branches: list[dict[str, list[str]]],
                  current: tuple[str, ...], raw_candidates: list[tuple[str, ...]],
                  weights: dict[str, list[int]] | None) -> tuple[list[dict], list[tuple[str, ...]]]:
    profile_weights = _weights_for(node, raw_candidates, weights)
    # Retain current as a zero-mass anchor if it was absent from the evaluation set.
    profile_weights.setdefault(current, 0)
    profiles = sorted(profile_weights)
    library = sorted(set([current, *raw_candidates, *(tuple(b[node]) for b in branches)]))
    if len(library) > MAX_FRONTIER_LIBRARY:
        raise ValueError("exact frontier local-library bound")
    choices: dict[tuple[tuple[str, ...], ...], dict] = {}
    for mask in range(1, 1 << len(library)):
        selected = [library[i] for i in range(len(library)) if mask & (1 << i)]
        guard = _unbounded_antichain(selected)
        if not 1 <= len(guard) <= MAX_OPTIONS:
            continue
        if not any(set(option).issubset(current) for option in guard):
            continue
        accepted_mask = 0
        mass = 0
        accepted_profiles = []
        for i, profile in enumerate(profiles):
            if any(set(option).issubset(profile) for option in guard):
                accepted_mask |= 1 << i
                mass += profile_weights[profile]
                accepted_profiles.append(profile)
        entry = dict(guard=guard, accepted_mask=accepted_mask, mass=mass,
                     accepted_count=len(accepted_profiles), accepted_profiles=tuple(accepted_profiles))
        choices[guard] = entry
    ordered = sorted(choices.values(), key=lambda x: (
        -x["mass"], -x["accepted_count"], len(x["guard"]), x["guard"]))
    if not ordered:
        raise ValueError("no current-preserving local guard")
    return ordered, profiles


def _dominates(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    return all((a | b) == a for a, b in zip(left, right))


def frontier_synthesize(branches: list[dict[str, list[str]]], current: dict[str, list[str]],
                        candidates: dict[str, list[list[str]]],
                        weights: dict[str, list[int]] | None = None,
                        max_states: int = MAX_FRONTIER_STATES) -> dict:
    """Exactly enumerate the bounded finite availability frontier.

    Search domain: positive local guards whose minimal conjunctions are drawn
    from the projected current profile, supplied candidate profiles, or a local
    branch requirement. Every guard must admit the current support.  The primary
    objective is the product of accepted candidate-profile weights; ties maximize
    total local mass, then minimize guard terms, then use lexical box order.

    The routine raises instead of returning a purported optimum if any declared
    exact-search bound is exceeded.
    """
    if type(max_states) is not int or not 1 <= max_states <= MAX_FRONTIER_STATES:
        raise ValueError("exact frontier search-state bound")
    branches = normalize(branches)
    nodes, _, projected_current, projected_candidates = _projected_inputs(
        branches, current, candidates)
    if weights is not None and sorted(weights) != nodes:
        raise ValueError("weight placement mismatch")
    seed_box = {n: [list(projected_current[n])] for n in nodes}
    if not verify_box(branches, seed_box)["safe"]:
        raise ValueError("current placement is incompatible")

    local: dict[str, list[dict]] = {}
    profile_domains: dict[str, list[tuple[str, ...]]] = {}
    for n in nodes:
        local[n], profile_domains[n] = _local_guards(
            n, branches, projected_current[n], projected_candidates[n], weights)

    # Only membership is reused: canonical tuples still determine search/output order.
    term_memberships = {term: frozenset(term)
                        for term in {term for choices in local.values()
                                     for choice in choices for term in choice["guard"]}}
    # Fewer local choices first reduces unsafe partial products; node ID breaks ties.
    order = sorted(nodes, key=lambda n: (len(local[n]), n))
    branch_sets = [{n: set(req) for n, req in b.items()} for b in branches]
    frontier: list[dict] = []
    counters = dict(states=0, complete=0, safe_complete=0,
                    unsafe_pruned=0, corner_pruned=0)

    def canonical_box(selected: dict[str, dict]) -> tuple:
        return tuple((n, selected[n]["guard"]) for n in nodes)

    def score(selected: dict[str, dict]) -> tuple:
        masses = [selected[n]["mass"] for n in nodes]
        return (prod(masses), sum(masses), -sum(len(selected[n]["guard"]) for n in nodes))

    def consider(selected: dict[str, dict]) -> None:
        nonlocal frontier
        counters["complete"] += 1
        counters["safe_complete"] += 1
        masks = tuple(selected[n]["accepted_mask"] for n in nodes)
        key = canonical_box(selected)
        record = dict(masks=masks, key=key, selected=dict(selected), score=score(selected))
        # Equal finite acceptance sets keep the lowest-metadata, lexical guard.
        same = next((x for x in frontier if x["masks"] == masks), None)
        if same is not None:
            same_terms = -same["score"][2]
            new_terms = -record["score"][2]
            if (new_terms, key) < (same_terms, same["key"]):
                frontier.remove(same)
            else:
                record = same
        if record not in frontier:
            if any(_dominates(x["masks"], masks) for x in frontier):
                pass
            else:
                frontier = [x for x in frontier if not _dominates(masks, x["masks"])]
                frontier.append(record)
                if len(frontier) > MAX_FRONTIER_PLANS:
                    raise ValueError("exact frontier result bound")

    def visit(depth: int, selected: dict[str, dict],
              assigned: list[tuple[str, tuple[tuple[str, ...], ...]]],
              corner_count: int) -> None:
        counters["states"] += 1
        if counters["states"] > max_states:
            raise ValueError("exact frontier search-state bound")
        if depth == len(order):
            consider(selected)
            return
        n = order[depth]
        for choice in local[n]:
            next_corners = corner_count * len(choice["guard"])
            if next_corners > MAX_CORNERS:
                counters["corner_pruned"] += 1
                continue
            next_assigned = assigned + [(n, choice["guard"])]
            if not _partial_safe(branch_sets, next_assigned, term_memberships):
                counters["unsafe_pruned"] += 1
                continue
            selected[n] = choice
            visit(depth + 1, selected, next_assigned, next_corners)
            del selected[n]

    visit(0, {}, [], 1)
    if not frontier:
        raise AssertionError("current-safe seed did not produce a frontier plan")
    # Selection is deliberately restricted to nondominated accepted-profile
    # vectors. With zero-weight candidates, optimizing over all safe guards can
    # otherwise prefer a smaller dominated guard under the metadata tie-break.
    best_score = max(record["score"] for record in frontier)
    best = min((record for record in frontier if record["score"] == best_score),
               key=lambda record: record["key"])

    def external(record: dict) -> dict:
        selected = record["selected"]
        box = {n: [list(x) for x in selected[n]["guard"]] for n in nodes}
        masses = {n: selected[n]["mass"] for n in nodes}
        counts = {n: selected[n]["accepted_count"] for n in nodes}
        accepted = {n: [list(x) for x in selected[n]["accepted_profiles"]] for n in nodes}
        return dict(box=box, product_mass=record["score"][0], local_masses=masses,
                    accepted_unique_profiles=counts, accepted_profiles=accepted,
                    guard_terms=sum(len(box[n]) for n in nodes))

    front = sorted((external(x) for x in frontier),
                   key=lambda x: (-x["product_mass"], x["guard_terms"],
                                  tuple((n, tuple(tuple(v) for v in x["box"][n])) for n in nodes)))
    answer = external(best)
    answer.update(frontier=front, frontier_size=len(front), search=counters,
                  objective=dict(domain="nondominated frontier members",
                                 primary="candidate-profile product mass",
                                 secondary="sum of local masses",
                                 tertiary="fewer guard terms",
                                 final="lexicographic box",
                                 weights="uniform per supplied candidate" if weights is None else "supplied integers"),
                  candidate_domains={n: [list(x) for x in profile_domains[n]] for n in nodes},
                  certificate=verify_box(branches, answer["box"]), exact=True,
                  scope="bounded positive guard library; supplied finite candidate profiles")
    return answer
