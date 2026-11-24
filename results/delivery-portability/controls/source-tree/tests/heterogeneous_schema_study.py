"""Exhaustive event-order experiments for actual field-addition release semantics.

The catalogue enumeration uses independent event algorithms. Each
feature contributes precisely one parser-preparation event at its receiver and
one emitter-activation event at its sender; every local chain edge changes an
observable field contract. It is a controlled construction space, not a
workload-frequency sample. Actual ProtoJSON channel probes compile the input of the production planner.
The first three domains validate every production plan; the discovery domain
uses a fixed grid of controls plus explicitly selected outcome witnesses.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import csv
import gzip
from copy import deepcopy
from itertools import permutations, product
import json
from pathlib import Path
import time

from src.heterogeneous_contracts import CONFIGS, actual_probes, context_model
from src.factored_planner import FactoredChainPlanner, validate_factored_plan


def require(condition, message):
    if not condition:
        raise ValueError(message)


def event_model(edges, orders):
    ranks = [{event: rank + 1 for rank, event in enumerate(order)} for order in orders]
    thresholds = [(sender, ranks[sender]["e_" + name], receiver,
                   ranks[receiver]["p_" + name]) for name, sender, receiver in edges]
    return thresholds


def safe(point, thresholds):
    return all(point[i] < a or point[j] >= b for i, a, j, b in thresholds)


def box_safe(source, target, thresholds):
    return all(a <= b for a, b in zip(source, target)) and all(
        target[i] < a or source[j] >= b for i, a, j, b in thresholds)


def greatest_plan(target, thresholds):
    current = tuple(0 for _ in target)
    trace = [current]
    while current != target:
        following = list(target)
        for i, a, j, b in thresholds:
            if current[j] < b:
                following[i] = min(following[i], a - 1)
        following = tuple(following)
        require(all(a <= b for a, b in zip(current, following)), "regressing endpoint")
        require(box_safe(current, following, thresholds), "unsafe endpoint rectangle")
        trace.append(following)
        if following == current:
            return None, trace
        current = following
    return len(trace) - 1, trace


def event_dag_plan(edges, orders):
    """Independent lower bound: chain edges cost 0, prepare-to-emit costs 1.

    Every event requires phase >= 1. Local chain order permits a shared phase;
    a field's preparation and emission must lie in distinct phases. Longest
    weighted paths give an achievable phase assignment in an acyclic graph.
    """
    events = [event for order in orders for event in order]
    outgoing = {event: [] for event in events}
    incoming = {event: 0 for event in events}
    for order in orders:
        for before, after in zip(order, order[1:]):
            outgoing[before].append((after, 0))
            incoming[after] += 1
    for name, _, _ in edges:
        before, after = "p_" + name, "e_" + name
        outgoing[before].append((after, 1))
        incoming[after] += 1
    queue = deque(event for event in events if incoming[event] == 0)
    labels = {event: 1 for event in events}
    visited = []
    while queue:
        before = queue.popleft()
        visited.append(before)
        for after, cost in outgoing[before]:
            labels[after] = max(labels[after], labels[before] + cost)
            incoming[after] -= 1
            if incoming[after] == 0:
                queue.append(after)
    if len(visited) != len(events):
        return None, None
    maximum = max(labels.values(), default=0)
    endpoints = [tuple(0 for _ in orders)] + [
        tuple(sum(labels[event] <= phase for event in order) for order in orders)
        for phase in range(1, maximum + 1)]
    return maximum, endpoints


def priority_path(target, thresholds, orders, priority, strategy):
    current = tuple(0 for _ in target)
    trace = [current]
    while current != target:
        ready = []
        for preference, owner in enumerate(priority):
            if current[owner] == target[owner]:
                continue
            following = list(current)
            following[owner] += 1
            following = tuple(following)
            if not safe(following, thresholds):
                continue
            is_emit = orders[owner][current[owner]].startswith("e_")
            if strategy == "owner":
                score = (preference,)
            elif strategy == "stage":
                score = (current[owner], preference)
            elif strategy == "prepare_first":
                score = (is_emit, preference)
            elif strategy == "prepare_first_stage":
                score = (is_emit, current[owner], preference)
            else:
                raise ValueError(strategy)
            ready.append((score, following))
        if not ready:
            return None
        current = min(ready)[1]
        trace.append(current)
    return trace


def path_partition(path, thresholds):
    """Exact dynamic program over every pair of path indices."""
    distance = [0] + [len(path)] * (len(path) - 1)
    predecessor = [None] * len(path)
    for right in range(1, len(path)):
        for left in range(right):
            if (distance[left] + 1 < distance[right]
                    and box_safe(path[left], path[right], thresholds)):
                distance[right] = distance[left] + 1
                predecessor[right] = left
    require(distance[-1] < len(path), "unpartitionable valid path")
    indices, cursor = [], len(path) - 1
    while cursor:
        indices.append(cursor)
        cursor = predecessor[cursor]
    indices.append(0)
    indices.reverse()
    return distance[-1], [path[index] for index in indices]


def literal_check(target, thresholds):
    """Enumerate cells and all safe phase rectangles for retained examples."""
    relation = [point for point in product(*(range(t + 1) for t in target))
                if safe(point, thresholds)]
    membership = set(relation)
    graph = {}
    for source in relation:
        graph[source] = []
        for endpoint in relation:
            if source == endpoint or any(a > b for a, b in zip(source, endpoint)):
                continue
            literal = all(point in membership for point in product(*(
                range(a, b + 1) for a, b in zip(source, endpoint))))
            require(literal == box_safe(source, endpoint, thresholds),
                    "literal rectangle disagrees with field threshold check")
            if literal:
                graph[source].append(endpoint)
    initial = tuple(0 for _ in target)
    distance, queue = {initial: 0}, deque([initial])
    while queue:
        source = queue.popleft()
        for endpoint in graph[source]:
            if endpoint not in distance:
                distance[endpoint] = distance[source] + 1
                queue.append(endpoint)
    return {"compatible_cells": len(relation), "catalog_cells":
            __import__("math").prod(t + 1 for t in target),
            "safe_phase_edges": sum(map(len, graph.values())),
            "optimal_phases": distance.get(target),
            "relation": [list(p) for p in relation],
            "phase_graph": [{"source": list(s), "targets": [list(t) for t in ts]}
                            for s, ts in graph.items()]}


STRATEGIES = ('owner', 'stage', 'prepare_first', 'prepare_first_stage')
CONFIRMATORY_DOMAINS = ('two_owner', 'three_owner', 'three_owner_complete')
DISCOVERY_DOMAIN = 'three_owner_complete_extra'
ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('src/heterogeneous_contracts.py', 'src/factored_planner.py',
           'src/envelope.py', 'src/controller.py',
           'tests/heterogeneous_schema_study.py', 'tests/check_heterogeneous_schema.py')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n')


def inventories_for(edges):
    count = max(max(s, r) for _, s, r in edges) + 1
    inventories = [[] for _ in range(count)]
    for name, sender, receiver in edges:
        inventories[sender].append('e_' + name)
        inventories[receiver].append('p_' + name)
    return inventories


def orders_at(permutations_by_owner, context):
    result = []
    for choices in reversed(permutations_by_owner):
        result.append(choices[context % len(choices)])
        context //= len(choices)
    require(context == 0, 'context beyond inventory')
    return tuple(reversed(result))


def compact_plan(plan, model):
    indices = {owner: {tuple(profile): rank for rank, profile in enumerate(profiles)}
               for owner, profiles in model['catalog'].items()}
    owners = sorted(indices)
    def state(placement):
        return [indices[owner][tuple(placement[owner])] for owner in owners]
    phases = []
    for phase in plan['phases']:
        phases.append({'source': state(phase['source']), 'target': state(phase['target']),
                       'box': deepcopy(phase['box']),
                       'local_paths': {owner: [indices[owner][tuple(p)] for p in phase['local_paths'][owner]]
                                       for owner in owners},
                       'steps': [[step['node'], indices[step['node']][tuple(step['support'])]]
                                 for step in phase['steps']],
                       'factor_checks': deepcopy(phase['factor_checks'])})
    return {'status': plan['status'], 'cost': deepcopy(plan['cost']),
            'rank_iterates': deepcopy(plan['search']['rank_iterates']),
            'reason': plan.get('reason'), 'phases': phases}


def production_plan(config, orders, channels, exact, endpoints):
    model = context_model(config, orders, channels)
    planner = FactoredChainPlanner(model['factors'], model['catalog'], model['transitions'])
    answer = planner.plan(model['initial'], model['target'])
    require(answer['recognition']['recognized'], 'production factor recognition failed')
    require(answer['search']['rank_iterates'] == [list(p) for p in endpoints],
            'production endpoints differ from independent event endpoints')
    if exact is None:
        require(answer['status'] == 'unreachable' and answer['cost'] is None,
                'production did not report independent dependency deadlock')
    else:
        require(answer['status'] == 'planned' and answer['cost']['phases'] == exact
                and answer['cost']['installations'] == sum(map(len, orders)),
                'production phase/install cost differs from event-DAG optimum')
        validate_factored_plan(answer)
    return compact_plan(answer, model)


def dependency_cycle(edges, orders):
    outgoing = {event: [] for order in orders for event in order}
    for order in orders:
        for a, b in zip(order, order[1:]): outgoing[a].append(b)
    for field, _, _ in edges: outgoing['p_' + field].append('e_' + field)
    visited, active, stack = set(), set(), []
    def visit(event):
        if event in active:
            return stack[stack.index(event):] + [event]
        if event in visited: return None
        active.add(event); stack.append(event)
        for following in outgoing[event]:
            found = visit(following)
            if found is not None: return found
        stack.pop(); active.remove(event); visited.add(event)
        return None
    for event in outgoing:
        found = visit(event)
        if found is not None: return found
    return None


def run_domain(config, output, channels):
    import math
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=True)
    edges = CONFIGS[config]
    inventories = inventories_for(edges)
    permutations_by_owner = [list(permutations(sorted(events))) for events in inventories]
    total = math.prod(map(len, permutations_by_owner))
    priority_orders = list(permutations(range(len(inventories))))
    target = tuple(map(len, inventories))
    production_all = config in CONFIRMATORY_DOMAINS
    fixed_controls = sorted({round(i * (total - 1) / 15) for i in range(16)})
    counters, phase_counts, cost_vectors = Counter(), Counter(), Counter()
    production_counts = Counter()
    examples = {}
    fieldnames = ['context', *['order_' + str(i) for i in range(len(inventories))],
                  'status', 'exact', *[s + '_portfolio' for s in STRATEGIES],
                  'owner_stage_portfolio', 'all_portfolio', *[s + '_costs' for s in STRATEGIES]]
    with gzip.open(output / 'contexts.csv.gz', 'wt', newline='', encoding='utf-8') as stream, \
            gzip.open(output / 'production.jsonl.gz', 'wt', encoding='utf-8') as plan_stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for context, orders in enumerate(product(*permutations_by_owner)):
            counters['attempted'] += 1
            thresholds = event_model(edges, orders)
            exact, endpoints = greatest_plan(target, thresholds)
            dag_exact, dag_endpoints = event_dag_plan(edges, orders)
            require(exact == dag_exact, 'endpoint and event-DAG optimum differ')
            require(dag_endpoints is None or dag_endpoints == endpoints, 'earliest DAG layers differ')
            row = {'context': context, 'status': 'unreachable' if exact is None else 'reachable',
                   'exact': exact, **{'order_' + str(i): ' '.join(order) for i, order in enumerate(orders)}}
            labels = []
            record = {'context': context, 'orders': orders, 'thresholds': thresholds,
                      'exact': exact, 'endpoints': endpoints}
            if exact is None:
                counters['unreachable'] += 1
                if 'first_unreachable' not in examples:
                    labels.append('first_unreachable')
                    record['dependency_cycle'] = dependency_cycle(edges, orders)
                    require(record['dependency_cycle'] is not None, 'deadlock has no dependency cycle')
            else:
                counters['reachable'] += 1
                phase_counts[exact] += 1
                portfolios, path_results = {}, []
                for strategy in STRATEGIES:
                    costs = []
                    for priority in priority_orders:
                        path = priority_path(target, thresholds, orders, priority, strategy)
                        require(path is not None, 'greedy deadlock in reachable DAG')
                        cost, cuts = path_partition(path, thresholds)
                        require(cost >= exact, 'path portfolio improves exact event bound')
                        costs.append(cost)
                        path_results.append({'strategy': strategy, 'priority': priority,
                                             'path': path, 'phases': cost, 'endpoints': cuts})
                    best = min(costs)
                    portfolios[strategy] = best
                    row[strategy + '_portfolio'] = best
                    row[strategy + '_costs'] = ' '.join(map(str, costs))
                    counters[strategy + ('_tie' if best == exact else '_gap')] += 1
                owner_stage = min(portfolios['owner'], portfolios['stage'])
                all_portfolio = min(portfolios.values())
                row['owner_stage_portfolio'], row['all_portfolio'] = owner_stage, all_portfolio
                counters['owner_stage' + ('_tie' if owner_stage == exact else '_gap')] += 1
                counters['all' + ('_tie' if all_portfolio == exact else '_gap')] += 1
                cost_vectors[(exact, *portfolios.values())] += 1
                record.update(paths=path_results, portfolios=portfolios)
                if 'first_reachable' not in examples: labels.append('first_reachable')
                for label, cost in [*portfolios.items(), ('owner_stage', owner_stage), ('all', all_portfolio)]:
                    if cost > exact and 'first_' + label + '_gap' not in examples:
                        labels.append('first_' + label + '_gap')
            if production_all or context in fixed_controls or labels:
                produced = production_plan(config, orders, channels, exact, endpoints)
                selection = ('all_contexts' if production_all else
                             'fixed_even_grid' if context in fixed_controls else 'discovery_first_outcome')
                retained = {'context': context, 'selection': selection, **produced}
                plan_stream.write(json.dumps(retained, sort_keys=True, separators=(',', ':')) + '\n')
                production_counts['checked'] += 1
                production_counts[produced['status']] += 1
                production_counts[selection] += 1
                if labels: record['production'] = retained
            for label in labels: examples[label] = record
            writer.writerow(row)
            if (context + 1) % 10000 == 0:
                print(json.dumps({'domain': config, 'contexts': context + 1, 'total': total,
                                  'seconds': round(time.monotonic() - started, 2)}), flush=True)
    for name, record in examples.items():
        literal = literal_check(target, record['thresholds'])
        require(literal['optimal_phases'] == record['exact'], 'literal graph optimum differs')
        record['literal_verification'] = literal
        write(output / (name + '.json'), record)
    summary = {'domain': config,
               'scope': 'declared_finite_domain' if production_all else 'discovery_extension',
               'field_edges': edges, 'events_by_owner': inventories,
               'state_shape': [t + 1 for t in target], 'installations': sum(target),
               'context_count_formula': [len(p) for p in permutations_by_owner],
               'priorities': priority_orders, 'strategies': list(STRATEGIES),
               'counts': dict(sorted(counters.items())),
               'optimal_phase_counts': {str(k): v for k, v in sorted(phase_counts.items())},
               'cost_vectors': [{'exact_owner_stage_prepare_preparestage': list(k), 'contexts': v}
                                for k, v in sorted(cost_vectors.items())],
               'production_scope': 'every_context' if production_all else 'fixed_grid_and_outcome_witnesses',
               'production_fixed_grid': fixed_controls,
               'production_counts': dict(sorted(production_counts.items())),
               'retained_examples': list(examples),
               'all_context_validation': 'weighted-event-DAG versus greatest-contiguous-prefix iteration',
               'retained_example_validation': 'literal catalog cells and safe-phase rectangles plus BFS',
               'elapsed_seconds': time.monotonic() - started}
    write(output / 'summary.json', summary)
    print(json.dumps({'domain': config, 'counts': summary['counts'],
                      'production_counts': summary['production_counts']}), flush=True)
    return summary


def produce(output, domains):
    if output.exists() and any(output.iterdir()):
        raise ValueError('use an empty output directory')
    output.mkdir(parents=True, exist_ok=True)
    channels = actual_probes()
    write(output / 'channel-observations.json', channels)
    probe_summary = {'channel_catalogs': len(channels),
                     'descriptors': sum(len(c['descriptors']) for c in channels),
                     'wires': sum(len(c['wires']) for c in channels),
                     'matrix_parser_invocations': sum(len(c['parses']) for c in channels),
                     'accepted': sum(p['accepted'] for c in channels for p in c['parses']),
                     'rejected': sum(not p['accepted'] for c in channels for p in c['parses']),
                     'event_effect_witnesses': sum(len(c['event_effect_witnesses']) for c in channels),
                     'event_effect_parser_invocations': 2 * sum(len(c['event_effect_witnesses']) for c in channels)}
    write(output / 'probe-summary.json', probe_summary)
    metadata = {'domains': domains, 'declared_finite_domains': list(CONFIRMATORY_DOMAINS),
                'discovery_extension': DISCOVERY_DOMAIN,
                'population': 'all labelled event permutations within each declared channel inventory',
                'not_a_measure': 'deployment prevalence or production workload frequency',
                'queries_per_context': 1, 'query': 'all-legacy to every field prepared and emitting',
                'event_semantics': 'every release performs exactly one reader preparation or emitter activation',
                'baseline_partition': 'exact interval dynamic programming for every generated path',
                'specialized_exact_baseline': 'weighted event DAG, chain weight zero, prepare-to-emit weight one',
                'production_policy': {'declared_domains': 'every context',
                                      'discovery_extension': '16 evenly spaced IDs plus the first outcome witnesses'},
                'sources': list(SOURCES)}
    write(output / 'metadata.json', metadata)
    for name in SOURCES:
        source = ROOT / name
        if source.exists():
            destination = output / 'sources' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
    summaries = [run_domain(domain, output / domain, channels) for domain in domains]
    write(output / 'summary.json', {'status': 'PASS', 'probe_summary': probe_summary,
                                  'domains': summaries,
                                  'attempted': sum(s['counts']['attempted'] for s in summaries),
                                  'reachable': sum(s['counts']['reachable'] for s in summaries),
                                  'unreachable': sum(s['counts']['unreachable'] for s in summaries),
                                  'production_checked': sum(s['production_counts']['checked'] for s in summaries)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--domains', nargs='+', choices=CONFIGS, default=list(CONFIGS))
    args = parser.parse_args()
    require(len(args.domains) == len(set(args.domains)), 'duplicate domain')
    produce(args.output, args.domains)


