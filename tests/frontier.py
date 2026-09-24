"""Independent finite oracle for the exact positive-envelope frontier."""
from __future__ import annotations
from itertools import combinations
import json
import resource
import time
from src.checker import safe_envelope, frontier_certificate
from src.envelope import frontier_synthesize, synthesize


def subsets_containing(values, required):
    others = [x for x in values if x != required]
    return [{required, *choice} for k in range(len(others) + 1)
            for choice in combinations(others, k)]


def relation_oracle():
    profiles = [0, 1, 2]
    cases = safe_boxes = 0
    states = frontier_total = 0
    # All nonempty 3x3 relations representable by the eight-branch manifest bound.
    for bits in range(1, 511):
        pairs = {(i, j) for i in profiles for j in profiles if bits & (1 << (3 * i + j))}
        branches = [{'0': [f'a{i}'], '1': [f'b{j}']} for i, j in sorted(pairs)]
        for seed_left, seed_right in sorted(pairs):
            current = {'0': [f'a{seed_left}'], '1': [f'b{seed_right}']}
            candidates = {'0': [[f'a{i}'] for i in profiles],
                          '1': [[f'b{j}'] for j in profiles]}
            plan = frontier_synthesize(branches, current, candidates)
            assert plan['exact'] and plan['certificate']['safe']
            assert safe_envelope(branches, plan['box'])
            assert frontier_certificate(branches, current, candidates, plan)
            optimum = 0
            maximal = []
            for left in subsets_containing(profiles, seed_left):
                for right in subsets_containing(profiles, seed_right):
                    if all((i, j) in pairs for i in left for j in right):
                        volume = len(left) * len(right)
                        optimum = max(optimum, volume)
                        safe_boxes += 1
                        maximal.append((left, right))
            assert plan['product_mass'] == optimum
            # Returned finite frontier members must be pairwise nondominating.
            masks = []
            for item in plan['frontier']:
                accepted = tuple(frozenset(tuple(x) for x in item['accepted_profiles'][n])
                                 for n in ('0', '1'))
                masks.append(accepted)
            for i, left in enumerate(masks):
                for j, right in enumerate(masks):
                    if i != j:
                        assert not all(a.issuperset(b) for a, b in zip(left, right))
            cases += 1
            states += plan['search']['states']
            frontier_total += plan['frontier_size']
    return dict(relations=510, seeded_relations=cases, independently_enumerated_safe_boxes=safe_boxes,
                planner_search_states=states, returned_frontier_members=frontier_total,
                oracle='enumerate all seeded row/column subsets and direct relation membership')


def greedy_counterexample():
    pairs = [(0, j) for j in range(7)] + [(1, 0)]
    branches = [{'0': [f'a{i}'], '1': [f'b{j}']} for i, j in pairs]
    current = {'0': ['a0'], '1': ['b0']}
    candidates = {'0': [['a0'], ['a1']], '1': [[f'b{j}'] for j in range(7)]}
    greedy = synthesize(branches, current, candidates)
    exact = frontier_synthesize(branches, current, candidates)
    greedy_mass = sum(any(set(o).issubset(p) for o in greedy['box']['0'])
                      for p in map(set, candidates['0']))
    greedy_mass *= sum(any(set(o).issubset(p) for o in greedy['box']['1'])
                       for p in map(set, candidates['1']))
    assert greedy_mass == 2 and exact['product_mass'] == 7
    assert exact['box'] == {'0': [['a0']], '1': [[f'b{j}'] for j in range(7)]}
    return dict(pairs=pairs, greedy_product_mass=greedy_mass,
                exact_product_mass=exact['product_mass'], exact_box=exact['box'],
                exact_frontier_size=exact['frontier_size'], search=exact['search'])


def weighted_case():
    pairs = [(0, 0), (0, 1), (1, 0)]
    branches = [{'0': [f'a{i}'], '1': [f'b{j}']} for i, j in pairs]
    current = {'0': ['a0'], '1': ['b0']}
    candidates = {'0': [['a0'], ['a1']], '1': [['b0'], ['b1']]}
    uniform = frontier_synthesize(branches, current, candidates)
    weighted = frontier_synthesize(branches, current, candidates,
                                    weights={'0': [1, 9], '1': [8, 1]})
    # Uniform objectives tie; lexical ordering chooses the wider left side.
    assert uniform['product_mass'] == 2
    # Weighted mass favors retaining a1 at the left and only b0 at the right.
    assert frontier_certificate(branches, current, candidates, uniform)
    assert frontier_certificate(branches, current, candidates, weighted,
                                weights={'0': [1, 9], '1': [8, 1]})
    assert weighted['product_mass'] == 80
    assert weighted['box'] == {'0': [['a0'], ['a1']], '1': [['b0']]}
    return dict(uniform_box=uniform['box'], uniform_product_mass=uniform['product_mass'],
                weighted_box=weighted['box'], weighted_product_mass=weighted['product_mass'])



def zero_weight_frontier_case():
    """Regression: zero-weight profiles must not make selection leave the frontier."""
    branches = [{'0': ['a']}, {'0': ['b']}]
    current = {'0': ['a']}
    candidates = {'0': [['a'], ['b']]}
    weights = {'0': [1, 0]}
    plan = frontier_synthesize(branches, current, candidates, weights=weights)
    assert frontier_certificate(branches, current, candidates, plan, weights=weights)
    assert plan['frontier_size'] == 1
    assert plan['box'] == {'0': [['a'], ['b']]}
    assert plan['box'] == plan['frontier'][0]['box']
    assert plan['product_mass'] == 1
    return dict(weights=weights['0'], selected_box=plan['box'],
                accepted_profiles=plan['accepted_profiles']['0'],
                product_mass=plan['product_mass'],
                frontier_size=plan['frontier_size'],
                regression='selected plan is a nondominated frontier member')


def run():
    start = time.perf_counter(); cpu = time.process_time()
    relation = relation_oracle()
    counterexample = greedy_counterexample()
    weighted = weighted_case()
    zero_weight = zero_weight_frontier_case()
    return dict(relation_oracle=relation, greedy_counterexample=counterexample,
                weighted_case=weighted, zero_weight_frontier_case=zero_weight,
                cpu_seconds=time.process_time() - cpu,
                wall_seconds=time.perf_counter() - start,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, sort_keys=True))
