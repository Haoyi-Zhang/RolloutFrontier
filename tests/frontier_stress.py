"""Deterministic larger-domain stress checks against a direct box oracle."""
from __future__ import annotations
from itertools import combinations, product
import copy
import json
from math import prod
import random
import resource
import time
from src.checker import frontier_certificate
from src.envelope import frontier_synthesize

SEED = 20260912


def containing(size: int, required: int):
    rest = [x for x in range(size) if x != required]
    for count in range(len(rest) + 1):
        for choice in combinations(rest, count):
            yield frozenset((required, *choice))


def direct_frontier(size: int, pairs: set[tuple[int, int]], seed: tuple[int, int]):
    safe = []
    for left in containing(size, seed[0]):
        for right in containing(size, seed[1]):
            if all((i, j) in pairs for i in left for j in right):
                safe.append((left, right))
    frontier = set()
    for item in safe:
        if not any(item != other and other[0].issuperset(item[0]) and
                   other[1].issuperset(item[1]) for other in safe):
            frontier.add(item)
    return safe, frontier


def direct_frontier_3d(size: int, triples: set[tuple[int, int, int]],
                       seed: tuple[int, int, int]):
    safe = []
    domains = [list(containing(size, seed[i])) for i in range(3)]
    for left, middle, right in product(*domains):
        if all((i, j, k) in triples for i in left for j in middle for k in right):
            safe.append((left, middle, right))
    frontier = set()
    for item in safe:
        if not any(item != other and all(a.issuperset(b) for a, b in zip(other, item))
                   for other in safe):
            frontier.add(item)
    return safe, frontier


def decode(item: dict):
    left = frozenset(int(p[0][1:]) for p in item['accepted_profiles']['0'])
    right = frozenset(int(p[0][1:]) for p in item['accepted_profiles']['1'])
    return left, right


def one(size: int, pairs: set[tuple[int, int]], seed: tuple[int, int]):
    branches = [{'0': [f'a{i}'], '1': [f'b{j}']} for i, j in sorted(pairs)]
    current = {'0': [f'a{seed[0]}'], '1': [f'b{seed[1]}']}
    candidates = {'0': [[f'a{i}'] for i in range(size)],
                  '1': [[f'b{j}'] for j in range(size)]}
    plan = frontier_synthesize(branches, current, candidates)
    assert frontier_certificate(branches, current, candidates, plan)
    safe, expected = direct_frontier(size, pairs, seed)
    returned = {decode(item) for item in plan['frontier']}
    assert returned == expected
    optimum = max(len(left) * len(right) for left, right in expected)
    assert plan['product_mass'] == optimum
    assert decode(plan) in expected
    return len(safe), len(expected), plan['search']['states']


def one_3d(size: int, triples: set[tuple[int, int, int]], seed: tuple[int, int, int]):
    prefixes = ('a', 'b', 'c')
    branches = [{str(n): [f'{prefixes[n]}{cell[n]}'] for n in range(3)}
                for cell in sorted(triples)]
    current = {str(n): [f'{prefixes[n]}{seed[n]}'] for n in range(3)}
    candidates = {str(n): [[f'{prefixes[n]}{i}'] for i in range(size)]
                  for n in range(3)}
    plan = frontier_synthesize(branches, current, candidates)
    assert frontier_certificate(branches, current, candidates, plan)
    safe, expected = direct_frontier_3d(size, triples, seed)
    returned = {
        tuple(frozenset(int(profile[0][1:]) for profile in item['accepted_profiles'][str(n)])
              for n in range(3))
        for item in plan['frontier']
    }
    assert returned == expected
    optimum = max(prod(len(x) for x in item) for item in expected)
    selected = tuple(frozenset(int(profile[0][1:])
                               for profile in plan['accepted_profiles'][str(n)])
                     for n in range(3))
    assert selected in expected and plan['product_mass'] == optimum
    return len(safe), len(expected), plan['search']['states']


def relation_samples(size: int, count: int, rng: random.Random):
    cells = [(i, j) for i in range(size) for j in range(size)]
    seen = set()
    while len(seen) < count:
        edge_count = rng.randint(2, 8)
        relation = tuple(sorted(rng.sample(cells, edge_count)))
        if relation not in seen:
            seen.add(relation)
            yield set(relation)


def relation_samples_3d(size: int, count: int, rng: random.Random):
    cells = list(product(range(size), repeat=3))
    seen = set()
    while len(seen) < count:
        edge_count = rng.randint(2, 8)
        relation = tuple(sorted(rng.sample(cells, edge_count)))
        if relation not in seen:
            seen.add(relation)
            yield set(relation)


def _direct_local_guard_count(node, branches, current, candidates):
    relevant = set().union(*(set(branch[node]) for branch in branches))
    cur = tuple(sorted(set(current[node]) & relevant))
    raw = [tuple(sorted(set(profile) & relevant)) for profile in candidates[node]]
    library = sorted(set([cur, *raw, *(tuple(sorted(set(b[node]))) for b in branches)]))
    guards = set()
    for count in range(1, len(library) + 1):
        for selected in combinations(library, count):
            guard = tuple(x for x in sorted(set(selected))
                          if not any(set(y) < set(x) for y in selected))
            if 1 <= len(guard) <= 8 and any(set(x).issubset(cur) for x in guard):
                guards.add(guard)
    return len(guards)


def high_pruning_checker_case():
    """Regression for a checker that once bounded the raw local-choice product."""
    nodes = [str(i) for i in range(5)]
    profiles = {n: [[], [f'{n}a'], [f'{n}b'], [f'{n}c'],
                    [f'{n}a', f'{n}b'], [f'{n}b', f'{n}c'],
                    [f'{n}a', f'{n}b', f'{n}c']] for n in nodes}
    branches = [
        {'0': ['0a', '0b', '0c'], '1': ['1a', '1b'], '2': ['2b', '2c'],
         '3': ['3a', '3b', '3c'], '4': []},
        {'0': ['0b', '0c'], '1': ['1b', '1c'], '2': ['2a', '2b'],
         '3': ['3c'], '4': ['4a', '4b', '4c']},
    ]
    current = {'0': ['0a', '0b', '0c'], '1': ['1a', '1b'], '2': ['2b', '2c'],
               '3': ['3a', '3b', '3c'], '4': ['4a', '4b']}
    counts = [_direct_local_guard_count(n, branches, current, profiles) for n in nodes]
    raw_product = prod(counts)
    assert counts == [14, 11, 11, 14, 11] and raw_product == 260876
    plan = frontier_synthesize(branches, current, profiles)
    assert plan['search']['states'] == 37
    assert frontier_certificate(branches, current, profiles, plan)

    mutations = []
    def rejected(name, mutate):
        candidate = copy.deepcopy(plan)
        mutate(candidate)
        assert not frontier_certificate(branches, current, profiles, candidate)
        mutations.append(name)
    rejected('duplicate-frontier-member', lambda p: p['frontier'].append(copy.deepcopy(p['frontier'][0])))
    rejected('frontier-product-mass', lambda p: p['frontier'][0].__setitem__('product_mass', 10**9))
    rejected('selected-accepted-profiles', lambda p: p.__setitem__('accepted_profiles', {}))
    rejected('candidate-domains', lambda p: p.__setitem__('candidate_domains', {}))
    rejected('search-state-count', lambda p: p['search'].__setitem__('states', p['search']['states'] + 1))
    rejected('corner-certificate', lambda p: p['certificate'].__setitem__('corners', 999))
    rejected('guard-term-count', lambda p: p.__setitem__('guard_terms', p['guard_terms'] + 1))
    rejected('objective-description', lambda p: p['objective'].__setitem__('weights', 'corrupted'))
    return dict(local_guard_counts=counts, raw_choice_product=raw_product,
                visited_prefix_states=plan['search']['states'],
                checker_accepts=True, rejected_mutations=mutations)


def run() -> dict:
    started, cpu = time.perf_counter(), time.process_time()
    rng = random.Random(SEED)
    cases = safe_boxes = frontier_members = planner_states = 0
    by_size = {}
    for size, relations in ((4, 192), (5, 48)):
        local_cases = local_safe = local_front = local_states = 0
        for pairs in relation_samples(size, relations, rng):
            seeds = rng.sample(sorted(pairs), min(2, len(pairs)))
            for seed in seeds:
                safe, front, states = one(size, pairs, seed)
                cases += 1; safe_boxes += safe; frontier_members += front; planner_states += states
                local_cases += 1; local_safe += safe; local_front += front; local_states += states
        by_size[str(size)] = dict(relations=relations, seeded_cases=local_cases,
                                  direct_safe_boxes=local_safe,
                                  direct_frontier_members=local_front,
                                  planner_search_states=local_states)

    three_d_cases = three_d_safe = three_d_front = three_d_states = 0
    for triples in relation_samples_3d(3, 96, rng):
        for seed in rng.sample(sorted(triples), min(2, len(triples))):
            safe, front, states = one_3d(3, triples, seed)
            three_d_cases += 1; three_d_safe += safe
            three_d_front += front; three_d_states += states
    three_d = dict(relations=96, seeded_cases=three_d_cases,
                   direct_safe_boxes=three_d_safe,
                   direct_frontier_members=three_d_front,
                   planner_search_states=three_d_states,
                   dimensions=3, profiles_per_dimension=3)
    pruning = high_pruning_checker_case()

    # Exact routines must fail closed rather than silently truncate.
    nine = [{'0': [f'a{i}'], '1': [f'b{i}']} for i in range(9)]
    branch_bound = None
    try:
        frontier_synthesize(nine, {'0': ['a0'], '1': ['b0']},
                            {'0': [[f'a{i}'] for i in range(8)],
                             '1': [[f'b{i}'] for i in range(8)]})
    except ValueError as error:
        branch_bound = str(error)
    assert branch_bound == 'branch bound'

    simple = [{'0': ['a'], '1': ['b']}]
    state_bound = None
    try:
        frontier_synthesize(simple, {'0': ['a'], '1': ['b']},
                            {'0': [['a']], '1': [['b']]}, max_states=1)
    except ValueError as error:
        state_bound = str(error)
    assert state_bound == 'exact frontier search-state bound'

    return dict(seed=SEED, seeded_cases=cases, direct_safe_boxes=safe_boxes,
                direct_frontier_members=frontier_members,
                planner_search_states=planner_states, by_profile_count=by_size,
                three_dimensional=three_d, high_pruning_checker=pruning,
                fail_closed_checks={'nine-branch-manifest': branch_bound,
                                    'one-state-search-limit': state_bound},
                oracle=('all row/column subsets containing the seed, followed by direct '
                        'relation-membership and nondominance checks'),
                scope=('deterministic sparse 2D 4x4/5x5 and 3D 3x3x3 samples with at most '
                       'eight allowed tuples; stress evidence, not exhaustive at these dimensions'),
                cpu_seconds=time.process_time() - cpu,
                wall_seconds=time.perf_counter() - started,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, sort_keys=True))
