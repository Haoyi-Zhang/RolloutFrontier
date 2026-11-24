"""Complete finite validation and separate cold-cohort planning measurements."""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import gzip
from itertools import product
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

from src.goal_planner import GoalPlanner
from src.structured_planner import CertifiedGoalPlanner
from tests.goal_path_baselines import PolicyGoalBaselines
from tests.goal_planner_oracle import relation_inputs, support_transitions
from tests.goal_policy_study import input_specs, make_domain, task_inputs, vector_support

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'data/goal-policy.json'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def network_definitions():
    definitions = []
    for size in range(3, 7):
        definitions.append({'name': f'precedence-chain-{size}', 'shape': [2] * size,
                            'bounds': [[i, i - 1, 0] for i in range(1, size)]})
    definitions.extend([
        {'name': 'fork-star-four', 'shape': [2] * 4, 'bounds': [[i, 0, 0] for i in range(1, 4)]},
        {'name': 'join-star-four', 'shape': [2] * 4, 'bounds': [[3, i, 0] for i in range(3)]},
        {'name': 'diamond-four', 'shape': [2] * 4,
         'bounds': [[1, 0, 0], [2, 0, 0], [3, 1, 0], [3, 2, 0]]},
    ])
    for size in range(3, 7):
        definitions.append({'name': f'equality-cycle-{size}', 'shape': [2] * size,
                            'bounds': [[i, (i + 1) % size, 0] for i in range(size)]})
    definitions.extend([
        {'name': 'ternary-adjacent-skew', 'shape': [3] * 3,
         'bounds': [[0, 1, 1], [1, 0, 1], [1, 2, 1], [2, 1, 1]]},
        {'name': 'ternary-complete-skew', 'shape': [3] * 3,
         'bounds': [[i, j, 1] for i in range(3) for j in range(3) if i != j]},
        {'name': 'ternary-precedence', 'shape': [3] * 3,
         'bounds': [[1, 0, 0], [2, 1, 0]]},
        {'name': 'ternary-asymmetric', 'shape': [3] * 3,
         'bounds': [[1, 0, 0], [0, 1, 1], [2, 1, 1], [1, 2, 0]]},
    ])
    return definitions


def relation_context(name, family, shape, relation, specification):
    branches, catalog = relation_inputs(shape, relation)
    graphs = [{(i, i + 1) for i in range(size - 1)} for size in shape]
    transitions = support_transitions(catalog, graphs)
    relation = sorted(relation)
    return {'name': name, 'family': family, 'shape': list(shape),
            'specification': specification, 'branches': branches, 'catalog': catalog,
            'transitions': transitions, 'coordinate_profiles': deepcopy(catalog),
            'tasks': [[list(source), list(target)] for source in relation for target in relation]}


def contexts():
    facts = json.loads(POLICY.read_text())
    for spec in input_specs(facts):
        domain = make_domain(spec)
        nodes = list(domain['profiles'])
        values = [sorted(map(int, domain['profiles'][node])) for node in nodes]
        catalogs = {node: [domain['profiles'][node][str(value)] for value in values[i]]
                    for i, node in enumerate(nodes)}
        tasks = [[[values[i].index(value) for i, value in enumerate(source)],
                  [values[i].index(value) for i, value in enumerate(target)]]
                 for _, source, target in task_inputs(domain)]
        yield {'name': domain['name'], 'family': 'policy', 'shape': list(map(len, values)),
               'specification': spec, 'branches': domain['branches'], 'catalog': domain['candidates'],
               'transitions': domain['transitions'], 'coordinate_profiles': catalogs,
               'coordinate_values': values, 'tasks': tasks}
    for family, shape in [('three-by-three', (3, 3)), ('binary-three', (2, 2, 2))]:
        cells = list(product(*(range(size) for size in shape)))
        for mask in range(1, 1 << len(cells)):
            relation = {state for index, state in enumerate(cells) if mask >> index & 1}
            yield relation_context(f'{family}-{mask:03d}', family, shape, relation, {'mask': mask})
    for spec in network_definitions():
        relation = {state for state in product(*(range(size) for size in spec['shape']))
                    if all(state[i] - state[j] <= bound for i, j, bound in spec['bounds'])}
        yield relation_context(spec['name'], 'difference-network', spec['shape'], relation, spec)


def state(context, coordinates):
    return {str(i): context['coordinate_profiles'][str(i)][rank]
            for i, rank in enumerate(coordinates)}


def summarize(rows, context_rows):
    groups = defaultdict(lambda: {'contexts': 0, 'recognized_contexts': 0, 'queries': 0,
                                  'structured_queries': 0, 'fallback_queries': 0,
                                  'planned_nontrivial': 0, 'noops': 0, 'unreachable': 0,
                                  'phases': 0, 'installations': 0, 'maximum_phase_count': 0})
    family = {row['name']: row['family'] for row in context_rows}
    for row in context_rows:
        group = groups[row['family']]
        group['contexts'] += 1
        group['recognized_contexts'] += int(row['recognition']['recognized'])
    for row in rows:
        group, plan = groups[family[row['context']]], row['plan']
        group['queries'] += 1
        group['structured_queries' if plan['strategy'] == 'certified-difference-bounds' else 'fallback_queries'] += 1
        if plan['status'] == 'unreachable':
            group['unreachable'] += 1
        elif plan['cost']['installations'] == 0:
            group['noops'] += 1
        else:
            group['planned_nontrivial'] += 1
            group['phases'] += plan['cost']['phases']
            group['installations'] += plan['cost']['installations']
            group['maximum_phase_count'] = max(group['maximum_phase_count'], plan['cost']['phases'])
    return {'groups': dict(groups), 'contexts': len(context_rows),
            'queries': sum(group['queries'] for group in groups.values()),
            'recognized_contexts': sum(group['recognized_contexts'] for group in groups.values())}


def produce(output):
    if output.exists():
        raise ValueError('New study output must not already exist')
    output.mkdir(parents=True)
    context_rows, rows = [], []
    with gzip.open(output / 'plans.jsonl.gz', 'wt', encoding='utf-8', compresslevel=6) as handle:
        for context in contexts():
            planner = CertifiedGoalPlanner(context['branches'], context['catalog'], context['transitions'])
            context['recognition'] = planner.recognition()
            context_rows.append(context)
            for query, (source, target) in enumerate(context['tasks']):
                plan = planner.plan(state(context, source), state(context, target))
                row = {'context': context['name'], 'query': query, 'plan': plan}
                handle.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
                rows.append({'context': context['name'], 'plan': {
                    'strategy': plan['strategy'], 'status': plan['status'], 'cost': plan['cost']}})
    with gzip.open(output / 'contexts.json.gz', 'wt', encoding='utf-8', compresslevel=6) as handle:
        json.dump(context_rows, handle, sort_keys=True, separators=(',', ':'))
    summary = summarize(rows, context_rows)
    write(output / 'summary.json', summary)
    write(output / 'policy-input.json', json.loads(POLICY.read_text()))
    write(output / 'environment.json', {'python': platform.python_version(), 'platform': platform.platform(),
                                       'clock': 'time.process_time_ns', 'sources': [
        'src/structured_planner.py', 'tests/structured_planning_study.py',
        'tests/check_structured_planning.py', 'tests/structured_planning_regression.py',
        'docs/STRUCTURED-PLANNING.md']})
    print(json.dumps(summary, sort_keys=True))


def route_names(domain):
    routes = ['one-step', 'shortest-path-segmented', 'interval-optimal',
              'complete-frontier', 'certified-structure']
    if domain == 'boundary-three-owner':
        routes.insert(3, 'literal-products-optimal')
    return routes


def cold_cohort(domain_name, route):
    start = time.process_time_ns()
    facts = json.loads(POLICY.read_text())
    spec = next(spec for spec in input_specs(facts) if spec['name'] == domain_name)
    domain = make_domain(spec)
    tasks = list(task_inputs(domain))
    if route == 'complete-frontier':
        planner = GoalPlanner(domain['branches'], domain['candidates'], domain['transitions'])
    elif route == 'certified-structure':
        planner = CertifiedGoalPlanner(domain['branches'], domain['candidates'], domain['transitions'])
    else:
        planner = PolicyGoalBaselines(domain, route)
    prepared = time.process_time_ns()
    costs = []
    for name, source, target in tasks:
        if route in ('complete-frontier', 'certified-structure'):
            plan = planner.plan(vector_support(domain, source), vector_support(domain, target))
        else:
            plan = planner.plan(source, target)
        costs.append({'task': name, 'status': plan['status'], 'cost': plan['cost']})
    # Cost serialization is charged equally to every route.
    serialization_bytes = len(json.dumps(costs, sort_keys=True, separators=(',', ':')).encode())
    finished = time.process_time_ns()
    return {'preparation_cpu_seconds': (prepared - start) / 1e9,
            'query_cpu_seconds': (finished - prepared) / 1e9,
            'total_cpu_seconds': (finished - start) / 1e9,
            'costs': costs, 'serialization_bytes': serialization_bytes}


def timing_worker(domain, route, repetition, output):
    cpu = min(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    if cpu is not None:
        os.sched_setaffinity(0, {cpu})
    resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
    cohorts, costs, charged = [], None, 0.0
    while charged < 0.1 and len(cohorts) < 256:
        cohort = cold_cohort(domain, route)
        if costs is None:
            costs = cohort.pop('costs')
        elif cohort.pop('costs') != costs:
            raise ValueError('Timed cold cohorts disagree on task costs')
        cohorts.append(cohort)
        charged += cohort['total_cpu_seconds']
    if charged < 0.1:
        raise ValueError('Timing interval remained below declared measurement threshold')
    write(output, {'domain': domain, 'route': route, 'repetition': repetition, 'cpu': cpu,
                   'cpu_budget_seconds': 30, 'cohorts': cohorts, 'costs': costs,
                   'mean_total_cpu_seconds': statistics.mean(row['total_cpu_seconds'] for row in cohorts),
                   'mean_preparation_cpu_seconds': statistics.mean(row['preparation_cpu_seconds'] for row in cohorts),
                   'mean_query_cpu_seconds': statistics.mean(row['query_cpu_seconds'] for row in cohorts)})


def timings(output):
    if not (output / 'summary.json').is_file():
        raise ValueError('Run the non-timing study first')
    timing_dir = output / 'timing'
    if timing_dir.exists():
        raise ValueError('Timing output already exists')
    timing_dir.mkdir()
    domains = [spec['name'] for spec in input_specs(json.loads(POLICY.read_text()))]
    workers = []
    order = []
    for repetition in range(5):
        for domain in domains:
            routes = route_names(domain)
            routes = routes[repetition % len(routes):] + routes[:repetition % len(routes)]
            for route in routes:
                name = f'{domain}--{route}--{repetition}.json'
                path = timing_dir / name
                command = [sys.executable, '-B', '-m', 'tests.structured_planning_study',
                           '--worker', domain, route, str(repetition), '--out', str(path)]
                process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
                if process.returncode:
                    write(timing_dir / 'failure.json', {'command': command, 'returncode': process.returncode,
                                                       'stdout': process.stdout, 'stderr': process.stderr})
                    raise RuntimeError('Timing worker failed; retained diagnostics')
                workers.append(json.loads(path.read_text()))
                order.append(name)
    summaries = []
    for domain in domains:
        for route in route_names(domain):
            selected = [worker for worker in workers if worker['domain'] == domain and worker['route'] == route]
            values = [worker['mean_total_cpu_seconds'] for worker in selected]
            summaries.append({'domain': domain, 'route': route, 'workers': len(selected),
                              'queries_per_cohort': len(selected[0]['costs']),
                              'median_total_cpu_seconds': statistics.median(values),
                              'minimum_total_cpu_seconds': min(values), 'maximum_total_cpu_seconds': max(values),
                              'median_preparation_cpu_seconds': statistics.median(w['mean_preparation_cpu_seconds'] for w in selected),
                              'median_query_cpu_seconds': statistics.median(w['mean_query_cpu_seconds'] for w in selected)})
    write(output / 'timing-summary.json', {'workers': len(workers), 'rows': summaries, 'execution_order': order})
    print(json.dumps({'workers': len(workers), 'rows': summaries}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--worker', nargs=3)
    args = parser.parse_args()
    if args.worker:
        domain, route, repetition = args.worker
        timing_worker(domain, route, int(repetition), args.out)
    elif args.timing:
        timings(args.out)
    else:
        produce(args.out)


if __name__ == '__main__':
    main()
