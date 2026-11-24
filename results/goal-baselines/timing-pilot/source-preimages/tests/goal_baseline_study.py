"""Additive same-target baseline study. No existing result path is overwritten."""
from __future__ import annotations

import argparse
from collections import Counter, deque
from copy import deepcopy
import gzip
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time

from tests.goal_path_baselines import PolicyGoalBaselines, ROUTES, shortest_segment_partition
from tests.goal_planner_oracle import (literal_phase_graph, literal_shortest,
                                       relation_inputs, support_state, support_transitions)
from src.goal_planner import GoalPlanner

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'results/goal-policy'
GRAPHS = ({(0, 1), (1, 2)}, {(1, 0), (2, 1)},
          {(0, 1), (1, 2), (1, 0), (2, 1)},
          {(a, b) for a in range(3) for b in range(3) if a != b})
GRAPH_NAMES = ('forward-chain', 'reverse-chain', 'bidirectional-chain', 'complete-directed')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_gzip(path, rows):
    with path.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
            for row in rows:
                stream.write((canonical(row) + '\n').encode())


def tasks(domain):
    if domain['name'] == 'boundary-three-owner':
        return [(f'{i:03d}-{j:03d}', source, target)
                for i, source in enumerate(domain['compatible_placements'])
                for j, target in enumerate(domain['compatible_placements'])]
    spec = domain['specification']
    return [(item['name'], [item['initial_servers']] * spec['server_owners'] +
             [item['initial_clients']] * spec['client_owners'],
             [item['target_servers']] * spec['server_owners'] +
             [item['target_clients']] * spec['client_owners']) for item in spec['tasks']]


def policy_study(output):
    domains = json.loads((OLD / 'domains.json').read_text())
    with gzip.open(OLD / 'plans.jsonl.gz', 'rt') as stream:
        old = {(r['domain'], r['task']): r for r in map(json.loads, stream)}
    rows, work, summaries = [], [], []
    for domain in domains:
        routes = ROUTES if domain['name'] == 'boundary-three-owner' else ROUTES[:-1]
        engines = {route: PolicyGoalBaselines(domain, route) for route in routes}
        counts = {route: Counter() for route in (*routes, 'frontier-goal')}
        distributions = {route: Counter() for route in (*routes, 'frontier-goal')}
        for name, source, target in tasks(domain):
            reference = old[(domain['name'], name)]
            require([reference['initial_versions'], reference['target_versions']] == [source, target],
                    'Task identity differs from frozen study')
            plans = {route: engine.plan(source, target) for route, engine in engines.items()}
            reference_cost = reference['plan']['cost']
            for route, plan in {**plans, 'frontier-goal': reference['plan']}.items():
                counts[route]['tasks'] += 1
                counts[route][plan['status']] += 1
                if plan['status'] == 'planned':
                    k, w = plan['cost']['phases'], plan['cost']['installations']
                    counts[route]['no_op' if w == 0 else 'nontrivial_reachable'] += 1
                    if w:
                        counts[route]['phase_total'] += k
                        counts[route]['installation_total'] += w
                        distributions[route][(k, w)] += 1
                        counts[route]['higher_phase_cost_than_goal'] += int(k > reference_cost['phases'])
                        counts[route]['equal_cost_to_goal'] += int(plan['cost'] == reference_cost)
                require(plan['status'] == reference['status'], 'Reachability mismatch')
                if route in ('interval-optimal', 'literal-products-optimal'):
                    require(plan['cost'] == reference_cost, 'Exact same-goal control differs')
            rows.append({'domain': domain['name'], 'task': name,
                         'initial_versions': source, 'target_versions': target,
                         'frontier_status': reference['status'], 'frontier_cost': reference_cost,
                         'baselines': plans})
        for route, engine in engines.items():
            work.append({'domain': domain['name'], 'route': route, 'work': engine.stats()})
        summaries.append({'domain': domain['name'], 'routes': {
            route: {'counts': dict(counts[route]),
                    'phase_installation_distribution': [
                        {'phases': k, 'installations': w, 'tasks': n}
                        for (k, w), n in sorted(distributions[route].items())]}
            for route in counts}})
    write_gzip(output / 'policy-plans.jsonl.gz', rows)
    write(output / 'policy-work.json', work)
    write(output / 'policy-summary.json', summaries)


def product_closures(output):
    domain = json.loads((OLD / 'domains.json').read_text())[0]
    nodes = sorted(domain['profiles'], key=int)
    values = [sorted(map(int, domain['profiles'][node])) for node in nodes]
    libraries = [[tuple(v for i, v in enumerate(column) if mask >> i & 1)
                  for mask in range(1, 1 << len(column))] for column in values]
    relation = {tuple(v) for v in domain['compatible_placements']}
    relevant = {node: set().union(*(set(b[node]) for b in domain['branches'])) for node in nodes}
    records = []
    for physical in product(*libraries):
        if not all(cell in relation for cell in product(*physical)):
            continue
        guard = {}
        for node, column in zip(nodes, physical):
            terms = {tuple(sorted(set(domain['profiles'][node][str(v)]) & relevant[node])) for v in column}
            guard[node] = sorted([list(t) for t in terms if not any(set(u) < set(t) for u in terms)])
        accepted = {node: [v for v in column if any(set(t) <= set(domain['profiles'][node][str(v)])
                                                    for t in guard[node])]
                    for node, column in zip(nodes, values)}
        records.append({'physical_product': dict(zip(nodes, map(list, physical))),
                        'guard': guard, 'accepted_versions': accepted})
    write(output / 'literal-product-closures.json', records)


def safe_neighbors(relation, graphs, state):
    for owner, edges in enumerate(graphs):
        for source, target in sorted(edges):
            following = state[:owner] + (target,) + state[owner + 1:]
            if source == state[owner] and following in relation:
                yield following


def safe_paths(relation, graphs, source):
    parents, lengths, queue = {source: None}, {source: 0}, deque([source])
    while queue:
        state = queue.popleft()
        for following in safe_neighbors(relation, graphs, state):
            if following not in parents:
                parents[following] = state
                lengths[following] = lengths[state] + 1
                queue.append(following)
    return parents, lengths


def trace(parents, target):
    if target not in parents:
        return []
    path = []
    while target is not None:
        path.append(target)
        target = parents[target]
    return list(reversed(path))


def literal_partition(relation, path):
    return shortest_segment_partition(path, lambda a, b: all(
        point in relation for point in product(*(
            sorted({state[owner] for state in path[a:b + 1]}) for owner in range(len(path[0]))))))[0]


def finite_study(output):
    cells, contexts = list(product(range(3), repeat=2)), []
    totals, families = Counter(), {name: Counter() for name in GRAPH_NAMES}
    for mask in range(1, 512):
        relation = {cell for i, cell in enumerate(cells) if mask >> i & 1}
        for graph_index, edges in enumerate(GRAPHS):
            graphs, queries = (edges, edges), []
            phase_graph, boxes = literal_phase_graph((3, 3), relation, graphs)
            family = families[GRAPH_NAMES[graph_index]]
            totals['contexts'] += 1
            family['contexts'] += 1
            for source in sorted(relation):
                parents, lengths = safe_paths(relation, graphs, source)
                for target in sorted(relation):
                    path = trace(parents, target)
                    cuts = literal_partition(relation, path) if path else []
                    optimum = literal_shortest(phase_graph, source, target)
                    cost = [len(cuts), len(path) - 1] if path else None
                    require(bool(path) == (optimum is not None), 'Finite relation reachability differs')
                    category = 'unreachable' if not path else 'no_op' if source == target else 'nontrivial_reachable'
                    totals['queries'] += 1
                    totals[category] += 1
                    family['queries'] += 1
                    family[category] += 1
                    if path and cost[0] > optimum[0]:
                        totals['fixed_shortest_path_phase_gaps'] += 1
                        family['fixed_shortest_path_phase_gaps'] += 1
                    queries.append({'source': source, 'target': target,
                                    'shortest_path': path, 'segmentation': cuts,
                                    'segmented_cost': cost, 'optimal_cost': optimum})
            contexts.append({'relation_mask': mask, 'graph_family': GRAPH_NAMES[graph_index],
                             'safe_product_count': boxes,
                             'unique_phase_edges': sum(map(len, phase_graph.values())), 'queries': queries})
    write_gzip(output / 'finite-relations.jsonl.gz', contexts)
    write(output / 'finite-summary.json', {'totals': dict(totals),
          'families': {name: dict(counts) for name, counts in families.items()}})


def all_shortest_paths(relation, graphs, source, target):
    _, distances = safe_paths(relation, graphs, source)
    if target not in distances:
        return []
    result = []
    def extend(path):
        if path[-1] == target:
            result.append(list(path))
            return
        if len(path) - 1 >= distances[target]:
            return
        for following in safe_neighbors(relation, graphs, path[-1]):
            if distances[following] == len(path):
                extend(path + [following])
    extend([source])
    return result


def counterexamples(output):
    definitions = [
        ('shortest-path-choice', {(0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2)},
         GRAPHS[0], (0, 0), (2, 2), [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)], [(0, 2), (2, 4)]),
        ('phase-write-tradeoff', {(0, 0), (0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)},
         GRAPHS[3], (1, 2), (2, 1), [(1, 2), (0, 2), (0, 0), (2, 0), (2, 1)], [(0, 2), (2, 4)])]
    examples = []
    for name, relation, edges, source, target, witness, cuts in definitions:
        graph, count = literal_phase_graph((3, 3), relation, (edges, edges))
        branches, catalog = relation_inputs((3, 3), relation)
        planner = GoalPlanner(branches, catalog, support_transitions(catalog, (edges, edges)))
        plan = planner.plan(support_state(catalog, source), support_state(catalog, target))
        paths = all_shortest_paths(relation, (edges, edges), source, target)
        examples.append({'name': name, 'relation': sorted(relation), 'graphs': [sorted(edges)] * 2,
                         'source': source, 'target': target, 'safe_product_count': count,
                         'all_shortest_installation_paths': [
                             {'path': path, 'best_segmentation': literal_partition(relation, path),
                              'cost': [len(literal_partition(relation, path)), len(path) - 1]}
                             for path in paths],
                         'optimal_cost': literal_shortest(graph, source, target),
                         'two_phase_witness': {'path': witness, 'segmentation': cuts},
                         'production_plan': plan})
    write(output / 'counterexamples.json', examples)


def source_paths():
    return [ROOT / 'docs/GOAL-BASELINE-DESIGN.md', ROOT / 'data/goal-policy.json',
            ROOT / 'tests/goal_path_baselines.py', Path(__file__),
            ROOT / 'tests/check_goal_baselines.py', ROOT / 'tests/check_goal_policy.py',
            ROOT / 'tests/goal_planner_oracle.py',
            *sorted((ROOT / 'src').glob('*.py'))]


def manifest(output):
    files = {str(path.relative_to(output)): digest(path) for path in sorted(output.rglob('*'))
             if path.is_file() and path.name not in ('manifest.json', 'verification.json',
                                                     'verification-O.json', 'negative-controls.json')}
    write(output / 'manifest.json', {'schema': 'goal-baseline-study-v1', 'files': files,
          'source_hashes': {str(path.relative_to(ROOT)): digest(path) for path in source_paths()},
          'input_hashes': {str(path.relative_to(ROOT)): digest(path) for path in
                          (OLD / 'domains.json', OLD / 'plans.jsonl.gz')}})


def worker(route, domain_index, cpu_budget):
    def expired(_sig, _frame):
        raise TimeoutError('independent process CPU budget')
    signal.signal(signal.SIGPROF, expired)
    signal.setitimer(signal.ITIMER_PROF, cpu_budget)
    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    started, wall = time.process_time(), time.perf_counter()
    domain = json.loads((OLD / 'domains.json').read_text())[domain_index]
    queries = tasks(domain)
    engine = (GoalPlanner(domain['branches'], domain['candidates'], domain['transitions'])
              if route == 'frontier-goal' else PolicyGoalBaselines(domain, route))
    prepared = time.process_time()
    costs = []
    for name, source, target in queries:
        if route == 'frontier-goal':
            def support(vector):
                return {str(i): domain['profiles'][str(i)][str(v)] for i, v in enumerate(vector)}
            plan = engine.plan(support(source), support(target))
        else:
            plan = engine.plan(source, target)
        costs.append([name, plan['status'], plan['cost']])
    cost_hash = hashlib.sha256(canonical(costs).encode()).hexdigest()
    finished = time.process_time()
    signal.setitimer(signal.ITIMER_PROF, 0)
    return {'domain': domain['name'], 'route': route, 'status': 'completed',
            'preparation_cpu_seconds': prepared - started,
            'queries_cpu_seconds': finished - prepared, 'total_cpu_seconds': finished - started,
            'wall_seconds': time.perf_counter() - wall, 'cpu_budget_seconds': cpu_budget,
            'cpu_affinity': [cpu], 'queries': len(queries), 'costs_sha256': cost_hash,
            'maximum_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'work': engine.stats() if route != 'frontier-goal' else plan['search']['after']}


def timing(output):
    require(not (output / 'timings.json').exists(), 'Refusing to replace a timing record')
    rows = []
    for repetition in range(5):
        for domain_index in range(4):
            routes = [*ROUTES, 'frontier-goal'] if domain_index == 0 else [*ROUTES[:-1], 'frontier-goal']
            routes = routes[repetition % len(routes):] + routes[:repetition % len(routes)]
            for order, route in enumerate(routes):
                command = [sys.executable, '-B', '-m', 'tests.goal_baseline_study', '--worker', route,
                           '--domain-index', str(domain_index), '--cpu-budget', '30']
                completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
                require(completed.returncode == 0, f'Timing subprocess failed: {completed.stderr}')
                row = json.loads(completed.stdout)
                row.update({'repetition': repetition, 'order': order})
                rows.append(row)
                print(canonical({'timed': route, 'domain': row['domain'], 'repetition': repetition,
                                 'cpu_seconds': row['total_cpu_seconds']}), flush=True)
    write(output / 'timings.json', {'python': sys.version, 'platform': platform.platform(),
                                  'logical_cpus': os.cpu_count(), 'records': rows})
    manifest(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path)
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--worker', choices=(*ROUTES, 'frontier-goal'))
    parser.add_argument('--domain-index', type=int, default=0)
    parser.add_argument('--cpu-budget', type=float, default=30)
    args = parser.parse_args()
    if args.worker:
        print(canonical(worker(args.worker, args.domain_index, args.cpu_budget)))
        return
    require(args.out is not None, '--out is required')
    if args.timing:
        timing(args.out)
        return
    require(not args.out.exists(), 'Use a new study output directory')
    args.out.mkdir(parents=True)
    policy_study(args.out)
    product_closures(args.out)
    finite_study(args.out)
    counterexamples(args.out)
    for path in source_paths():
        destination = args.out / 'source-preimages' / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    manifest(args.out)
    print(canonical({'completed': str(args.out)}))


if __name__ == '__main__':
    main()
