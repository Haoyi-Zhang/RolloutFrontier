"""Independent saved-data checker for the additive same-target controls.

Only the standard library and the earlier independent integer-policy checker
are imported. Neither the producer, baseline engine nor production code is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path
import shutil
import tempfile

from tests.check_goal_policy import (IntegerOracle, expected_domain, guard_check,
                                      specifications, support_vector, tasks)

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'results/goal-policy'
ROUTES = ('one-step', 'shortest-path-segmented', 'interval-optimal', 'literal-products-optimal')
FAMILIES = ('forward-chain', 'reverse-chain', 'bidirectional-chain', 'complete-directed')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def equal(value, expected, message):
    require(canonical(value) == canonical(expected), message)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream]


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def graph_family(name):
    if name == 'forward-chain':
        return [(0, 1), (1, 2)]
    if name == 'reverse-chain':
        return [(1, 0), (2, 1)]
    if name == 'bidirectional-chain':
        return [(0, 1), (1, 0), (1, 2), (2, 1)]
    require(name == 'complete-directed', 'Unknown graph family')
    return [(a, b) for a in range(3) for b in range(3) if a != b]


def step_graph(relation, local_graphs):
    graph = {}
    for state in sorted(relation):
        following = []
        for owner, edges in enumerate(local_graphs):
            for source, target in sorted(edges):
                if source == state[owner]:
                    candidate = state[:owner] + (target,) + state[owner + 1:]
                    if candidate in relation:
                        following.append(candidate)
        graph[state] = following
    return graph


def deterministic_paths(graph, source):
    queue, parents, offset = [source], {source: None}, 0
    while offset < len(queue):
        state = queue[offset]
        offset += 1
        for following in graph[state]:
            if following not in parents:
                parents[following] = state
                queue.append(following)
    result = {}
    for target in parents:
        path, current = [], target
        while current is not None:
            path.append(current)
            current = parents[current]
        result[target] = list(reversed(path))
    return result


def legal_segment(relation, path, left, right):
    columns = [set(state[i] for state in path[left:right + 1]) for i in range(len(path[0]))]
    return all(tuple(cell) in relation for cell in product(*columns))


def exhaustive_partition_cost(relation, path):
    if not path:
        return None
    steps = len(path) - 1
    if not steps:
        return [0, 0]
    admissible = {(left, right): legal_segment(relation, path, left, right)
                  for right in range(1, steps + 1) for left in range(right)}
    best = steps
    for mask in range(1 << (steps - 1)):
        boundaries = [0] + [i for i in range(1, steps) if mask >> (i - 1) & 1] + [steps]
        if len(boundaries) - 1 < best and all(admissible[a, b] for a, b in zip(boundaries, boundaries[1:])):
            best = len(boundaries) - 1
    return [best, steps]


def partition_check(relation, path, cuts, expected):
    if not path:
        equal(cuts, [], 'Unreachable route has cuts')
        equal(expected, None, 'Unreachable route has a cost')
        return
    offset = 0
    for left, right in cuts:
        require(left == offset and left < right < len(path), 'Partition continuity or bounds')
        require(legal_segment(relation, path, left, right), 'Unsafe product along fixed path')
        offset = right
    require(offset == len(path) - 1, 'Partition does not cover the route')
    equal([len(cuts), len(path) - 1], expected, 'Partition cost differs')


def literal_graph(values, relation, local_graphs):
    """All products, with Floyd-Warshall local distances (not producer BFS)."""
    subsets = [[tuple(v for j, v in enumerate(column) if mask & (1 << j))
                for mask in range(1, 1 << len(column))] for column in values]
    graph = {state: {} for state in relation}
    stats = Counter()
    for box in product(*subsets):
        stats['profile_products'] += 1
        compatible = True
        for cell in product(*box):
            stats['product_corner_tests'] += 1
            if cell not in relation:
                compatible = False
                break
        if not compatible:
            continue
        stats['safe_profile_products'] += 1
        distances = []
        for column, edges in zip(box, local_graphs):
            matrix = {(a, b): 0 if a == b else 1 if (a, b) in edges else 10000
                      for a in column for b in column}
            for via in column:
                for source in column:
                    for target in column:
                        matrix[source, target] = min(matrix[source, target],
                                                      matrix[source, via] + matrix[via, target])
            distances.append(matrix)
        corners = list(product(*box))
        for source in corners:
            for target in corners:
                if source == target:
                    continue
                weights = [distances[i][source[i], target[i]] for i in range(len(values))]
                if max(weights) >= 10000:
                    continue
                stats['phase_edge_candidates'] += 1
                weight = sum(weights)
                graph[source][target] = min(graph[source].get(target, weight), weight)
    stats['unique_phase_edges'] = sum(map(len, graph.values()))
    return graph, stats


def phase_costs(graph, source):
    # Process one phase layer at a time; retain minimum write cost within a
    # layer. A later phase layer can never improve the lexicographic cost.
    result, layer = {source: (0, 0)}, {source: 0}
    for phase in range(1, len(graph)):
        following = {}
        for state, writes in layer.items():
            for target, weight in graph[state].items():
                if target not in result:
                    following[target] = min(following.get(target, writes + weight), writes + weight)
        result.update({state: (phase, writes) for state, writes in following.items()})
        layer = following
        if not layer:
            break
    return result


def validate_witness(domain, plan, source, target, expected_cost, relation):
    equal(plan['schema'], 'rollout-goal-plan-v1', 'Plan schema')
    for field, expected in (('branches', domain['branches']), ('catalog', domain['candidates']),
                            ('transitions', domain['transitions']),
                            ('initial', support_vector(domain, source)),
                            ('target', support_vector(domain, target))):
        equal(plan[field], expected, f'Plan {field} differs')
    equal(plan['cost'], expected_cost, 'Reported plan cost differs')
    if expected_cost is None:
        equal([plan['status'], plan['phases']], ['unreachable', []], 'Unreachable plan has witness')
        return []
    equal(plan['status'], 'planned', 'Feasible task status')
    nodes = sorted(domain['profiles'], key=int)
    inverse = {node: {tuple(profile): int(version) for version, profile in values.items()}
               for node, values in domain['profiles'].items()}
    allowed_edges = {node: {(tuple(edge['source']), tuple(edge['target'])) for edge in edges}
                     for node, edges in domain['transitions'].items()}
    current, actual_path, cuts, written = deepcopy(plan['initial']), [tuple(source)], [], 0
    for phase in plan['phases']:
        equal(phase['source'], current, 'Phase source breaks path')
        guard_check(domain, phase['box'], current)
        accepted = []
        for node in nodes:
            accepted.append([v for v, profile in domain['profiles'][node].items()
                             if any(set(term) <= set(profile) for term in phase['box'][node])])
        require(all(tuple(map(int, cell)) in relation for cell in product(*accepted)),
                'Positive closure admits an incompatible catalog cell')
        local = {node: [deepcopy(profile)] for node, profile in current.items()}
        require(bool(phase['steps']), 'Phase makes no progress')
        start = written
        for step in phase['steps']:
            equal(sorted(step), ['node', 'support'], 'Installation schema')
            node = step['node']
            require(node in current and tuple(step['support']) in inverse[node], 'Unknown full profile')
            require(current[node] != step['support'] and
                    (tuple(current[node]), tuple(step['support'])) in allowed_edges[node],
                    'Undeclared directed installation')
            require(any(set(term) <= set(step['support']) for term in phase['box'][node]),
                    'Installed profile outside guard')
            current[node] = list(step['support'])
            local[node].append(list(step['support']))
            point = tuple(inverse[node][tuple(current[node])] for node in nodes)
            require(point in relation, 'Installed joint state is incompatible')
            actual_path.append(point)
            written += 1
        equal(phase['local_paths'], local, 'Local paths differ from actual order')
        equal(phase['target'], current, 'Phase target differs from actual order')
        cuts.append([start, written])
    equal(current, plan['target'], 'Witness misses target')
    equal(expected_cost, {'phases': len(plan['phases']), 'installations': written,
                         'handoffs': max(len(plan['phases']) - 1, 0)}, 'Witness cost')
    if 'baseline' in plan:
        equal(plan['baseline']['version_path'], actual_path, 'Saved version path differs')
        equal(plan['baseline']['phase_cuts'], cuts, 'Saved phase cuts differ')
    return actual_path


def check_policy(directory):
    fixture = read(ROOT / 'data/goal-policy.json')
    domains = [expected_domain(spec) for spec in specifications(fixture)]
    equal(read(OLD / 'domains.json'), domains, 'Frozen domain does not reconstruct')
    old = {(r['domain'], r['task']): r for r in rows(OLD / 'plans.jsonl.gz')}
    actual = rows(directory / 'policy-plans.jsonl.gz')
    inventory = [(domain['name'], name) for domain in domains for name, _, _ in tasks(domain)]
    equal([(r['domain'], r['task']) for r in actual], inventory, 'Task inventory/order differs')
    by_key = {(r['domain'], r['task']): r for r in actual}
    summaries, expected_work, total_plans = [], [], 0
    timing_hashes = {}
    for domain in domains:
        relation = {tuple(v) for v in domain['compatible_placements']}
        values = [sorted(map(int, domain['profiles'][str(i)])) for i in range(len(domain['profiles']))]
        local_graphs = [{(v, v + 1) for v in column if v + 1 in column} for column in values]
        steps = step_graph(relation, local_graphs)
        oracle = IntegerOracle(domain)
        paths = {source: deterministic_paths(steps, source) for source in relation}
        routes = ROUTES if domain['name'] == 'boundary-three-owner' else ROUTES[:-1]
        literal, literal_stats = (literal_graph(values, relation, local_graphs)
                                  if len(routes) == 4 else (None, None))
        if literal is not None:
            equal({str(s): sorted(literal[s]) for s in relation},
                  {str(s): sorted(oracle.edges[s]) for s in relation}, 'Literal and interval phase edges differ')
        counts = {route: Counter() for route in (*routes, 'frontier-goal')}
        distributions = {route: Counter() for route in counts}
        cost_rows = {route: [] for route in counts}
        for name, source, target in tasks(domain):
            row = by_key[domain['name'], name]
            equal([row['initial_versions'], row['target_versions']], [source, target], 'Task endpoints')
            result = oracle.query(source, target)
            reference = old[domain['name'], name]
            goal_cost = None if not result['reachable'] else {
                'phases': result['minimum_phases'], 'installations': result['minimum_installations'],
                'handoffs': max(result['minimum_phases'] - 1, 0)}
            equal([row['frontier_status'], row['frontier_cost']],
                  [reference['status'], goal_cost], 'Frozen goal reference differs')
            equal(reference['plan']['cost'], goal_cost, 'Frozen production optimum differs')
            equal(sorted(row['baselines']), sorted(routes), 'Baseline coverage')
            shortest = paths[tuple(source)].get(tuple(target), [])
            segmented = exhaustive_partition_cost(relation, shortest)
            for route, plan in {**row['baselines'], 'frontier-goal': reference['plan']}.items():
                if route == 'one-step' and shortest:
                    cost = {'phases': len(shortest) - 1, 'installations': len(shortest) - 1,
                            'handoffs': max(len(shortest) - 2, 0)}
                elif route == 'shortest-path-segmented' and shortest:
                    cost = {'phases': segmented[0], 'installations': segmented[1],
                            'handoffs': max(segmented[0] - 1, 0)}
                else:
                    cost = goal_cost
                actual_path = validate_witness(domain, plan, source, target, cost, relation)
                total_plans += 1
                if route in ('one-step', 'shortest-path-segmented'):
                    equal(actual_path, shortest, 'Deterministic shortest path differs')
                if route != 'frontier-goal':
                    equal(plan['baseline']['route'], route, 'Route label differs')
                    equal(plan['baseline']['globally_phase_optimal'], route in ROUTES[2:], 'Optimality scope differs')
                counts[route]['tasks'] += 1
                counts[route][plan['status']] += 1
                cost_rows[route].append([name, plan['status'], cost])
                if cost is not None:
                    k, w = cost['phases'], cost['installations']
                    counts[route]['no_op' if w == 0 else 'nontrivial_reachable'] += 1
                    if w:
                        counts[route]['phase_total'] += k
                        counts[route]['installation_total'] += w
                        counts[route]['higher_phase_cost_than_goal'] += int(k > goal_cost['phases'])
                        counts[route]['equal_cost_to_goal'] += int(cost == goal_cost)
                        distributions[route][k, w] += 1
            if literal is not None:
                exact = phase_costs(literal, tuple(source)).get(tuple(target))
                equal(exact, None if goal_cost is None else [goal_cost['phases'], goal_cost['installations']],
                      'Literal same-objective optimum differs')
        source_set = {tuple(s) for _, s, _ in tasks(domain)}
        for route in routes:
            graph = steps if route in ROUTES[:2] else oracle.edges
            reachable = {s: deterministic_paths(graph, s) for s in source_set}
            work = {'catalog_cells': domain['catalog_placements'], 'compatible_vertices': len(relation),
                    'safe_edge_candidates': len(relation) * len(values) if route in ROUTES[:2] else 0,
                    'safe_edges': sum(map(len, steps.values())) if route in ROUTES[:2] else 0,
                    'interval_pair_candidates': len(relation) * (len(relation) - 1) if route == 'interval-optimal' else 0,
                    'profile_products': 0, 'safe_profile_products': 0, 'product_corner_tests': 0,
                    'phase_edge_candidates': sum(map(len, oracle.edges.values())) if route == 'interval-optimal' else 0,
                    'unique_phase_edges': sum(map(len, graph.values())), 'queries': len(tasks(domain)),
                    'source_searches': len(source_set),
                    'search_edge_visits': sum(len(graph[v]) for s in source_set for v in reachable[s]),
                    'segment_candidates': sum((len(paths[tuple(s)].get(tuple(t), [])) - 1) *
                                              len(paths[tuple(s)].get(tuple(t), [])) // 2
                                              for _, s, t in tasks(domain))
                                          if route == 'shortest-path-segmented' else 0}
            if route == 'literal-products-optimal':
                work.update(literal_stats)
            expected_work.append({'domain': domain['name'], 'route': route, 'work': work})
        summaries.append({'domain': domain['name'], 'routes': {
            route: {'counts': dict(counts[route]), 'phase_installation_distribution': [
                {'phases': k, 'installations': w, 'tasks': n} for (k, w), n in sorted(distributions[route].items())]}
            for route in counts}})
        for route, value in cost_rows.items():
            timing_hashes[domain['name'], route] = hashlib.sha256(canonical(value).encode()).hexdigest()
    equal(read(directory / 'policy-summary.json'), summaries, 'Policy summary differs')
    equal(read(directory / 'policy-work.json'), expected_work, 'Baseline work accounting differs')
    return {'tasks': len(actual), 'verified_plans_including_reference': total_plans}, timing_hashes


def check_finite(directory):
    contexts = rows(directory / 'finite-relations.jsonl.gz')
    equal([(r['relation_mask'], r['graph_family']) for r in contexts],
          [(mask, family) for mask in range(1, 512) for family in FAMILIES], 'Finite context inventory')
    cells, totals = list(product(range(3), repeat=2)), Counter()
    families = {family: Counter() for family in FAMILIES}
    for context in contexts:
        relation = {cell for i, cell in enumerate(cells) if context['relation_mask'] >> i & 1}
        edges = graph_family(context['graph_family'])
        steps = step_graph(relation, [edges, edges])
        graph, work = literal_graph([range(3), range(3)], relation, [edges, edges])
        equal(context['safe_product_count'], work['safe_profile_products'], 'Safe product count')
        equal(context['unique_phase_edges'], work['unique_phase_edges'], 'Phase edge count')
        equal([(q['source'], q['target']) for q in context['queries']],
              [(s, t) for s in sorted(relation) for t in sorted(relation)], 'Finite query inventory')
        family = families[context['graph_family']]
        totals['contexts'] += 1
        family['contexts'] += 1
        all_paths = {s: deterministic_paths(steps, s) for s in relation}
        optima = {s: phase_costs(graph, s) for s in relation}
        for query in context['queries']:
            source, target = tuple(query['source']), tuple(query['target'])
            path = all_paths[source].get(target, [])
            equal(query['shortest_path'], path, 'Finite shortest path differs')
            equal(query['optimal_cost'], optima[source].get(target), 'Finite exact optimum differs')
            segmented = exhaustive_partition_cost(relation, path)
            equal(query['segmented_cost'], segmented, 'Fixed-path optimum differs')
            partition_check(relation, path, query['segmentation'], segmented)
            category = 'unreachable' if not path else 'no_op' if source == target else 'nontrivial_reachable'
            totals['queries'] += 1
            totals[category] += 1
            family['queries'] += 1
            family[category] += 1
            if segmented is not None and segmented[0] > optima[source][target][0]:
                totals['fixed_shortest_path_phase_gaps'] += 1
                family['fixed_shortest_path_phase_gaps'] += 1
    summary = {'totals': dict(totals), 'families': {name: dict(c) for name, c in families.items()}}
    equal(read(directory / 'finite-summary.json'), summary, 'Finite summary differs')
    return summary['totals']


def check_examples(directory):
    examples = read(directory / 'counterexamples.json')
    equal([e['name'] for e in examples], ['shortest-path-choice', 'phase-write-tradeoff'], 'Example inventory')
    report = []
    for example in examples:
        relation = {tuple(v) for v in example['relation']}
        graphs = [{tuple(e) for e in edges} for edges in example['graphs']]
        source, target = tuple(example['source']), tuple(example['target'])
        steps = step_graph(relation, graphs)
        graph, _ = literal_graph([range(3), range(3)], relation, graphs)
        optimum = phase_costs(graph, source).get(target)
        equal(example['optimal_cost'], optimum, 'Example optimum')
        distance = len(deterministic_paths(steps, source)[target]) - 1
        # Enumerate every length-distance walk, without using producer distance
        # pruning. Minimality guarantees that all successful walks are simple.
        candidates = [[source]]
        for _ in range(distance):
            candidates = [path + [following] for path in candidates for following in steps[path[-1]]]
        all_paths = sorted(path for path in candidates if path[-1] == target)
        saved = example['all_shortest_installation_paths']
        equal(sorted(item['path'] for item in saved), all_paths, 'All-shortest-path enumeration incomplete')
        for item in saved:
            path = [tuple(v) for v in item['path']]
            cost = exhaustive_partition_cost(relation, path)
            equal(item['cost'], cost, 'Shortest-path partition cost')
            partition_check(relation, path, item['best_segmentation'], cost)
        witness = example['two_phase_witness']
        path = [tuple(v) for v in witness['path']]
        require(path[0] == source and path[-1] == target and
                all(b in steps[a] for a, b in zip(path, path[1:])), 'Selected witness has invalid path')
        partition_check(relation, path, witness['segmentation'], optimum)
        row_values = sorted({v[0] for v in relation})
        branches = [{'0': [f'row_{row}'], '1': [f'column_for_{row}']} for row in row_values]
        profiles = {'0': {str(v): sorted([f'identity_0_{v}', f'row_{v}']) for v in range(3)},
                    '1': {str(v): sorted([f'identity_1_{v}'] + [f'column_for_{r}' for r in row_values if (r, v) in relation])
                          for v in range(3)}}
        domain = {'branches': branches, 'profiles': profiles,
                  'candidates': {node: sorted(values.values()) for node, values in profiles.items()},
                  'transitions': {str(i): sorted([{'source': profiles[str(i)][str(a)], 'target': profiles[str(i)][str(b)]}
                                                for a, b in edges], key=lambda e: (e['source'], e['target']))
                                  for i, edges in enumerate(graphs)}}
        cost = {'phases': optimum[0], 'installations': optimum[1], 'handoffs': max(optimum[0] - 1, 0)}
        validate_witness(domain, example['production_plan'], source, target, cost, relation)
        if example['name'] == 'phase-write-tradeoff':
            equal(optimum, [2, 4], 'Tradeoff optimum')
            require(distance == 3 and all(item['cost'] == [3, 3] for item in saved),
                    'Tradeoff does not cover every minimum-write path')
        report.append({'name': example['name'], 'minimum_installations': distance,
                       'number_of_shortest_paths': len(all_paths), 'optimal_cost': optimum,
                       'shortest_path_phase_counts': sorted(set(item['cost'][0] for item in saved))})
    return report


def check_product_closures(directory):
    domain = expected_domain(specifications(read(ROOT / 'data/goal-policy.json'))[0])
    relation = {tuple(v) for v in domain['compatible_placements']}
    nodes = sorted(domain['profiles'], key=int)
    values = [sorted(map(int, domain['profiles'][node])) for node in nodes]
    libraries = [[tuple(v for i, v in enumerate(column) if mask & (1 << i))
                  for mask in range(1, 1 << len(column))] for column in values]
    products = [box for box in product(*libraries) if all(cell in relation for cell in product(*box))]
    saved = read(directory / 'literal-product-closures.json')
    equal([tuple(tuple(row['physical_product'][node]) for node in nodes) for row in saved],
          products, 'Safe product closure inventory')
    widened, maximum_terms, maximum_corners = 0, 0, 0
    for row, box in zip(saved, products):
        source = support_vector(domain, [column[0] for column in box])
        guard_check(domain, row['guard'], source)
        accepted = {node: [v for v in column if any(set(term) <= set(domain['profiles'][node][str(v)])
                                                   for term in row['guard'][node])]
                    for node, column in zip(nodes, values)}
        equal(row['accepted_versions'], accepted, 'Positive product closure differs')
        require(all(set(column) <= set(accepted[node]) for node, column in zip(nodes, box)),
                'Projection loses an original profile or path')
        require(all(tuple(cell) in relation for cell in product(*(accepted[node] for node in nodes))),
                'Positive closure is not safe')
        widened += int(any(set(column) != set(accepted[node]) for node, column in zip(nodes, box)))
        maximum_terms = max(maximum_terms, *(len(row['guard'][node]) for node in nodes))
        corners = 1
        for node in nodes:
            corners *= len(row['guard'][node])
        maximum_corners = max(maximum_corners, corners)
    return {'safe_physical_products': len(saved), 'strictly_widened_products': widened,
            'maximum_normalized_terms_per_owner': maximum_terms,
            'maximum_normalized_term_corners': maximum_corners}


def check(directory, source_checks=True):
    manifest = read(directory / 'manifest.json')
    equal(manifest['schema'], 'goal-baseline-study-v1', 'Manifest schema')
    for relative, expected in manifest['files'].items():
        equal(digest(directory / relative), expected, 'Result/preimage hash mismatch: ' + relative)
    for relative, expected in manifest['input_hashes'].items():
        equal(digest(ROOT / relative), expected, 'Frozen input hash mismatch')
    for relative, expected in manifest['source_hashes'].items():
        equal(digest(directory / 'source-preimages' / relative), expected, 'Source preimage hash mismatch')
        if source_checks:
            equal(digest(ROOT / relative), expected, 'Current source differs from preimage: ' + relative)
    policy, timing_hashes = check_policy(directory)
    closures = check_product_closures(directory)
    finite = check_finite(directory)
    examples = check_examples(directory)
    timing_count = 0
    if (directory / 'timings.json').exists():
        records = read(directory / 'timings.json')['records']
        expected_work = {(r['domain'], r['route']): r['work'] for r in read(directory / 'policy-work.json')}
        for row in rows(OLD / 'plans.jsonl.gz'):
            expected_work[row['domain'], 'frontier-goal'] = row['plan']['search']['after']
        expected = {(domain, route, repetition) for domain, route in timing_hashes for repetition in range(5)}
        equal(sorted((r['domain'], r['route'], r['repetition']) for r in records), sorted(expected), 'Timing inventory')
        for record in records:
            equal(record['status'], 'completed', 'Timing completion')
            equal(record['costs_sha256'], timing_hashes[record['domain'], record['route']], 'Timed costs differ')
            equal(record['work'], expected_work[record['domain'], record['route']], 'Timed work differs')
            equal(record['queries'], 529 if record['domain'] == 'boundary-three-owner' else 6, 'Timed query count')
            route_order = list((*ROUTES, 'frontier-goal') if record['domain'] == 'boundary-three-owner'
                               else (*ROUTES[:-1], 'frontier-goal'))
            rotation = record['repetition'] % len(route_order)
            route_order = route_order[rotation:] + route_order[:rotation]
            equal(record['route'], route_order[record['order']], 'Timed route order')
            require(0 <= record['preparation_cpu_seconds'] <= record['total_cpu_seconds'] < 30 and
                    record['queries_cpu_seconds'] >= 0, 'Timing bounds')
            require(abs(record['preparation_cpu_seconds'] + record['queries_cpu_seconds'] -
                        record['total_cpu_seconds']) < 1e-8, 'Timing preparation omitted')
            batches = record['cold_cohorts']
            require(1 <= len(batches) == record['measurement_batches'] <= 256, 'Cold-cohort batch count')
            require(0.1 <= record['charged_process_cpu_seconds'] < 30, 'Unresolved or over-budget CPU timing')
            require(abs(sum(b['total_cpu_seconds'] for b in batches) -
                        record['charged_process_cpu_seconds']) < 1e-8, 'Cold-cohort CPU charge omitted')
            require(abs(record['total_cpu_seconds'] * len(batches) -
                        record['charged_process_cpu_seconds']) < 1e-8, 'Per-cohort mean differs')
            for batch in batches:
                require(batch['preparation_cpu_seconds'] >= 0 and batch['queries_cpu_seconds'] >= 0 and
                        abs(batch['preparation_cpu_seconds'] + batch['queries_cpu_seconds'] -
                            batch['total_cpu_seconds']) < 1e-8, 'Invalid cold-cohort CPU accounting')
            require(type(record['cpu_budget_seconds']) in (int, float) and
                    record['cpu_budget_seconds'] == 30, 'Unequal route CPU budget')
            require(len(record['cpu_affinity']) == 1, 'Timing was not pinned')
        require(len({tuple(r['cpu_affinity']) for r in records}) == 1, 'Timing CPU differs')
        timing_count = len(records)
    return {'status': 'pass', 'policy': policy, 'finite_relations': finite,
            'counterexamples': examples, 'positive_product_closures': closures,
            'verified_timing_records': timing_count}


def negative_controls(directory):
    outcomes = []
    for mutation in ('cost', 'inventory', 'guard', 'finite-optimum'):
        with tempfile.TemporaryDirectory(prefix='goal-baseline-negative-') as temporary:
            target = Path(temporary) / 'study'
            shutil.copytree(directory, target)
            relative = 'finite-relations.jsonl.gz' if mutation == 'finite-optimum' else 'policy-plans.jsonl.gz'
            saved = rows(target / relative)
            if mutation == 'inventory':
                saved.pop()
            elif mutation in ('cost', 'guard'):
                row = next(r for r in saved if r['baselines']['one-step']['cost'] and
                           r['baselines']['one-step']['cost']['installations'])
                plan = row['baselines']['one-step']
                if mutation == 'cost':
                    plan['cost']['phases'] += 1
                else:
                    plan['phases'][0]['box']['0'] = [[]]
            else:
                query = next(q for context in saved for q in context['queries'] if q['optimal_cost'] == [1, 1])
                query['optimal_cost'] = [2, 1]
            with gzip.open(target / relative, 'wt') as stream:
                for row in saved:
                    stream.write(canonical(row) + '\n')
            manifest = read(target / 'manifest.json')
            manifest['files'][relative] = digest(target / relative)
            write(target / 'manifest.json', manifest)
            try:
                check(target)
            except ValueError as exc:
                outcomes.append({'mutation': mutation, 'status': 'rejected', 'reason': str(exc)})
            else:
                raise ValueError('Semantic mutation escaped: ' + mutation)
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--negative-controls', action='store_true')
    args = parser.parse_args()
    result = negative_controls(args.directory) if args.negative_controls else check(args.directory)
    if args.out:
        write(args.out, result)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
