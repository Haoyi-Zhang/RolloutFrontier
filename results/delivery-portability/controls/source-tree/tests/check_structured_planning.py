"""Independent literal relation, interval-graph and execution-witness checker.

This module imports only the Python standard library. It does not import the
planner, its recognizer, the study producer, or the original frontier checker.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from copy import deepcopy
import gzip
from itertools import product
import json
from math import prod, isclose
from pathlib import Path
import statistics


def require(condition, message):
    if not condition:
        raise ValueError(message)


def support(context, coordinates):
    return {str(i): context['coordinate_profiles'][str(i)][value]
            for i, value in enumerate(coordinates)}


def predicate(branches, state):
    return any(all(set(requirements) <= set(state[node]) for node, requirements in branch.items())
               for branch in branches)


def expected_networks():
    values = {}
    for n in (3, 4, 5, 6):
        values[f'precedence-chain-{n}'] = ([2] * n, [[i, i - 1, 0] for i in range(1, n)])
        values[f'equality-cycle-{n}'] = ([2] * n, [[i, (i + 1) % n, 0] for i in range(n)])
    values['fork-star-four'] = ([2] * 4, [[1, 0, 0], [2, 0, 0], [3, 0, 0]])
    values['join-star-four'] = ([2] * 4, [[3, 0, 0], [3, 1, 0], [3, 2, 0]])
    values['diamond-four'] = ([2] * 4, [[1, 0, 0], [2, 0, 0], [3, 1, 0], [3, 2, 0]])
    values['ternary-adjacent-skew'] = ([3] * 3, [[0, 1, 1], [1, 0, 1], [1, 2, 1], [2, 1, 1]])
    values['ternary-complete-skew'] = ([3] * 3, [[i, j, 1] for i in range(3) for j in range(3) if i != j])
    values['ternary-precedence'] = ([3] * 3, [[1, 0, 0], [2, 1, 0]])
    values['ternary-asymmetric'] = ([3] * 3, [[1, 0, 0], [0, 1, 1], [2, 1, 1], [1, 2, 0]])
    return values


def task_inventory(context, allowed, policy):
    if context['family'] != 'policy' or context['name'] == 'boundary-three-owner':
        return [[list(s), list(t)] for s in sorted(allowed) for t in sorted(allowed)]
    spec = context['specification']
    templates = policy['scaling_domains']['tasks']
    require(spec['tasks'] == templates, 'Changed policy task templates')
    result = []
    for task in templates:
        pair = []
        for direction in ('initial', 'target'):
            vector = ([task[direction + '_servers']] * spec['server_owners'] +
                      [task[direction + '_clients']] * spec['client_owners'])
            pair.append([context['coordinate_values'][i].index(value) for i, value in enumerate(vector)])
        result.append(pair)
    return result


def check_context(context, policy):
    shape, family, spec = context['shape'], context['family'], context['specification']
    if family in ('three-by-three', 'binary-three'):
        expected_shape = [3, 3] if family == 'three-by-three' else [2, 2, 2]
        require(shape == expected_shape and type(spec['mask']) is int and
                context['name'] == f"{family}-{spec['mask']:03d}", 'Finite relation identity differs')
    elif family == 'policy':
        if context['name'] == 'boundary-three-owner':
            expected_spec = policy['primary_domain']
        else:
            count = int(context['name'].split('-')[1])
            scale = policy['scaling_domains']
            expected_spec = {'name': context['name'], 'server_owners': scale['server_owners'],
                             'client_owners': count - scale['server_owners'],
                             'server_versions': scale['server_versions'],
                             'client_versions': scale['client_versions'], 'tasks': scale['tasks']}
        require(spec == expected_spec and context['coordinate_values'] ==
                [spec['server_versions']] * spec['server_owners'] +
                [spec['client_versions']] * spec['client_owners'], 'Policy catalog specification differs')
        require(shape == list(map(len, context['coordinate_values'])), 'Policy catalog shape differs')
    nodes = [str(i) for i in range(len(shape))]
    require(set(context['catalog']) == set(nodes), 'Catalog placement')
    all_cells = list(product(*(range(size) for size in shape)))
    allowed = set()
    for node, size in zip(nodes, shape):
        profiles = context['coordinate_profiles'][node]
        require(len(profiles) == size and len({tuple(p) for p in profiles}) == size,
                'Physical profile identity collapsed')
        require({tuple(p) for p in context['catalog'][node]} == {tuple(p) for p in profiles},
                'Coordinate catalog differs')
        edges = {(tuple(e['source']), tuple(e['target'])) for e in context['transitions'][node]}
        require(edges == {(tuple(a), tuple(b)) for a, b in zip(profiles, profiles[1:])},
                'Study chain edges differ')
    for index, cell in enumerate(all_cells):
        actual = predicate(context['branches'], support(context, cell))
        if family in ('three-by-three', 'binary-three'):
            expected = bool(spec['mask'] >> index & 1)
        elif family == 'difference-network':
            expected_shape, expected_bounds = expected_networks()[context['name']]
            require(shape == expected_shape and spec['bounds'] == expected_bounds,
                    'Difference network specification changed')
            expected = all(cell[i] - cell[j] <= bound for i, j, bound in expected_bounds)
        elif family == 'policy':
            version = [context['coordinate_values'][i][value] for i, value in enumerate(cell)]
            servers = version[:spec['server_owners']]
            clients = version[spec['server_owners']:]
            expected = max(servers) - min(servers) <= 1 and all(
                max(servers) - 3 <= value <= min(servers) for value in clients)
        else:
            raise ValueError('Unknown study family')
        require(actual == expected, 'Manifest differs from independently specified relation')
        if actual:
            allowed.add(cell)
    require(allowed, 'Empty study relation')
    require(context['tasks'] == task_inventory(context, allowed, policy), 'Task inventory differs')
    lower = [min(s[i] for s in allowed) for i in range(len(nodes))]
    upper = [max(s[i] for s in allowed) for i in range(len(nodes))]
    bounds = [[max(s[i] - s[j] for s in allowed) for j in range(len(nodes))]
              for i in range(len(nodes))]
    hull = {s for s in all_cells if all(lower[i] <= s[i] <= upper[i] for i in range(len(nodes)))
            and all(s[i] - s[j] <= bounds[i][j] for i in range(len(nodes)) for j in range(len(nodes)))}
    certificate = context['recognition']
    require(type(certificate['recognized']) is bool and certificate['recognized'] == (hull == allowed),
            'Incorrect structure recognition')
    require(certificate['catalog_placements'] == len(all_cells) and
            certificate['checked_placements'] == len(all_cells) and
            certificate['compatible_placements'] == len(allowed), 'Recognition coverage differs')
    if certificate['recognized']:
        require(certificate['nodes'] == nodes and certificate['ordered_profiles'] == context['coordinate_profiles'],
                'Recognition chain ranks differ')
        require(certificate['lower'] == lower and certificate['upper'] == upper and
                certificate['difference_bounds'] == bounds, 'Incorrect difference-bound certificate')
    else:
        require(tuple(certificate['hull_counterexample']) in hull - allowed,
                'Rejected hull lacks a valid additional cell')
    # Every legal phase between chain ranks contains the full interval product.
    # Enumerating these products gives an oracle independent of greedy bounds.
    graph = {source: [] for source in allowed}
    for source in sorted(allowed):
        for target in sorted(allowed):
            if source == target or any(a > b for a, b in zip(source, target)):
                continue
            cells = product(*(range(a, b + 1) for a, b in zip(source, target)))
            if all(cell in allowed for cell in cells):
                graph[source].append(target)
    distances = {}
    for source in sorted(allowed):
        depth, queue = {source: 0}, deque([source])
        while queue:
            current = queue.popleft()
            for target in graph[current]:
                if target not in depth:
                    depth[target] = depth[current] + 1
                    queue.append(target)
        distances[source] = depth
    return allowed, graph, distances


def check_plan(context, query, plan, allowed, distances):
    source, target = map(tuple, context['tasks'][query])
    require(plan['initial'] == support(context, source) and plan['target'] == support(context, target),
            'Plan endpoints differ from declared query')
    require(plan['branches'] == context['branches'] and plan['structure'] == context['recognition'],
            'Plan manifest or structure certificate differs')
    strategy = 'certified-difference-bounds' if context['recognition']['recognized'] else 'complete-frontier'
    require(plan['strategy'] == strategy, 'Incorrect dispatch route')
    nodes = [str(i) for i in range(len(context['shape']))]
    for node in nodes:
        require({tuple(p) for p in plan['catalog'][node]} ==
                {tuple(p) for p in context['catalog'][node]}, 'Plan catalog differs')
        require({(tuple(e['source']), tuple(e['target'])) for e in plan['transitions'][node]} ==
                {(tuple(e['source']), tuple(e['target'])) for e in context['transitions'][node]},
                'Plan transitions differ')
    optimum = distances[source].get(target)
    if optimum is None:
        require(plan['status'] == 'unreachable' and plan['cost'] is None and plan['phases'] == [],
                'False reachability answer')
        return
    expected_cost = {'phases': optimum, 'installations': sum(b - a for a, b in zip(source, target)),
                     'handoffs': max(optimum - 1, 0)}
    require(plan['status'] == 'planned' and plan['cost'] == expected_cost, 'Incorrect optimal plan cost')
    require(all(type(value) is int for value in plan['cost'].values()), 'Plan costs must be integers')
    current, writes = support(context, source), 0
    catalogs = {node: {tuple(p) for p in context['catalog'][node]} for node in nodes}
    edges = {node: {(tuple(e['source']), tuple(e['target'])) for e in context['transitions'][node]}
             for node in nodes}
    libraries = {node: {tuple(sorted(set(profile) & set().union(*(set(b[node]) for b in context['branches']))))
                       for profile in context['catalog'][node]} |
                 {tuple(sorted(b[node])) for b in context['branches']} for node in nodes}
    for phase in plan['phases']:
        require(phase['source'] == current and phase['steps'], 'Phase continuity or progress')
        box = phase['box']
        require(set(box) == set(nodes) and prod(len(box[node]) for node in nodes) <= 4096,
                'Guard placement or corner bound')
        for node in nodes:
            terms = [tuple(term) for term in box[node]]
            require(1 <= len(terms) <= 8 and terms == sorted(set(terms)), 'Guard term bound or order')
            require(all(term in libraries[node] for term in terms), 'Guard term outside admitted library')
            require(not any(set(a) < set(b) for a in terms for b in terms), 'Guard antichain differs')
            require(any(set(term) <= set(current[node]) for term in terms), 'Guard loses source')
        for corner in product(*(box[node] for node in nodes)):
            require(predicate(context['branches'], dict(zip(nodes, corner))), 'Unsafe positive guard corner')
        paths = {node: [current[node]] for node in nodes}
        current = deepcopy(current)
        for step in phase['steps']:
            node, following = step['node'], step['support']
            require((tuple(current[node]), tuple(following)) in edges[node], 'Undeclared physical transition')
            require(tuple(following) in catalogs[node] and
                    any(set(term) <= set(following) for term in box[node]), 'Installation outside guard')
            current[node] = following
            paths[node].append(following)
            writes += 1
        require(current == phase['target'] and paths == phase['local_paths'], 'Phase witness differs')
    require(current == plan['target'] and writes == expected_cost['installations'] and
            len(plan['phases']) == optimum, 'Execution does not attain reported optimum')


def expected_context_names():
    return ({'boundary-three-owner', 'active-4-owner', 'active-5-owner', 'active-6-owner'} |
            {f'three-by-three-{i:03d}' for i in range(1, 512)} |
            {f'binary-three-{i:03d}' for i in range(1, 256)} | set(expected_networks()))


def timing_check(output, contexts, oracles):
    path = output / 'timing-summary.json'
    if not path.exists():
        return {'state': 'not run', 'workers': 0}
    summary = json.loads(path.read_text())
    require(summary['workers'] == 105, 'Timing worker inventory')
    expected_order = []
    domain_order = ['boundary-three-owner', 'active-4-owner', 'active-5-owner', 'active-6-owner']
    routes = ['one-step', 'shortest-path-segmented', 'interval-optimal', 'complete-frontier', 'certified-structure']
    for repetition in range(5):
        for domain in domain_order:
            selected = list(routes)
            if domain == domain_order[0]:
                selected.insert(3, 'literal-products-optimal')
            selected = selected[repetition % len(selected):] + selected[:repetition % len(selected)]
            expected_order.extend(f'{domain}--{route}--{repetition}.json' for route in selected)
    require(summary['execution_order'] == expected_order, 'Timing execution order differs')
    workers = []
    for filename in expected_order:
        row = json.loads((output / 'timing' / filename).read_text())
        require(filename == f"{row['domain']}--{row['route']}--{row['repetition']}.json",
                'Timing worker identity differs')
        require(row['cpu_budget_seconds'] == 30, 'Timing budget differs')
        context = contexts[row['domain']]
        _, _, distances = oracles[row['domain']]
        expected = []
        for index, (raw_source, raw_target) in enumerate(context['tasks']):
            source, target = tuple(raw_source), tuple(raw_target)
            phases = distances[source].get(target)
            writes = sum(b - a for a, b in zip(source, target))
            if phases is None:
                cost = None
            else:
                phases = writes if row['route'] == 'one-step' else phases
                cost = {'phases': phases, 'installations': writes, 'handoffs': max(phases - 1, 0)}
            if context['name'] == 'boundary-three-owner':
                count = len(distances)
                task = f'{index // count:03d}-{index % count:03d}'
            else:
                task = context['specification']['tasks'][index]['name']
            expected.append({'task': task, 'status': 'unreachable' if cost is None else 'planned', 'cost': cost})
        require(row['costs'] == expected, 'Timed task costs differ from independently checked policy optima')
        cohorts = row['cohorts']
        require(1 <= len(cohorts) <= 256 and sum(c['total_cpu_seconds'] for c in cohorts) >= 0.1,
                'Insufficient CPU measurement interval')
        require(sum(c['total_cpu_seconds'] for c in cohorts) < 30, 'Worker exceeded charged CPU budget')
        expected_bytes = len(json.dumps(expected, sort_keys=True, separators=(',', ':')).encode())
        for c in cohorts:
            require(c['serialization_bytes'] == expected_bytes and c['preparation_cpu_seconds'] >= 0 and
                    c['query_cpu_seconds'] >= 0 and c['total_cpu_seconds'] >= 0,
                    'Invalid timing charges')
            require(isclose(c['total_cpu_seconds'], c['preparation_cpu_seconds'] + c['query_cpu_seconds'],
                            rel_tol=1e-10, abs_tol=1e-10), 'CPU decomposition differs')
        for kind in ('total', 'preparation', 'query'):
            require(isclose(row[f'mean_{kind}_cpu_seconds'],
                            statistics.mean(c[f'{kind}_cpu_seconds'] for c in cohorts),
                            rel_tol=1e-10, abs_tol=1e-10), 'Worker mean differs')
        workers.append(row)
    require(len(summary['rows']) == 21, 'Timing summary row count')
    require({(r['domain'], r['route']) for r in summary['rows']} ==
            {(w['domain'], w['route']) for w in workers}, 'Timing summary coverage differs')
    for row in summary['rows']:
        selected = [w for w in workers if w['domain'] == row['domain'] and w['route'] == row['route']]
        require(len(selected) == row['workers'] == 5, 'Timing repetitions differ')
        values = [w['mean_total_cpu_seconds'] for w in selected]
        checks = {'median_total_cpu_seconds': statistics.median(values),
                  'minimum_total_cpu_seconds': min(values), 'maximum_total_cpu_seconds': max(values),
                  'median_preparation_cpu_seconds': statistics.median(w['mean_preparation_cpu_seconds'] for w in selected),
                  'median_query_cpu_seconds': statistics.median(w['mean_query_cpu_seconds'] for w in selected)}
        require(row['queries_per_cohort'] == len(selected[0]['costs']), 'Timed query count')
        require(all(isclose(row[key], value, rel_tol=1e-10, abs_tol=1e-10) for key, value in checks.items()),
                'Timing summary differs')
    return {'state': 'pass', 'workers': len(workers)}


def verify(output, mutation=None):
    with gzip.open(output / 'contexts.json.gz', 'rt', encoding='utf-8') as handle:
        context_rows = json.load(handle)
    if mutation == 'false-structure':
        next(row for row in context_rows if row['recognition']['recognized'])['recognition']['upper'][0] += 1
    contexts = {row['name']: row for row in context_rows}
    require(len(contexts) == len(context_rows) and set(contexts) == expected_context_names(), 'Context inventory differs')
    policy = json.loads((output / 'policy-input.json').read_text())
    oracles = {name: check_context(context, policy) for name, context in contexts.items()}
    groups = {}
    for context in context_rows:
        group = groups.setdefault(context['family'], {'contexts': 0, 'recognized_contexts': 0, 'queries': 0,
            'structured_queries': 0, 'fallback_queries': 0, 'planned_nontrivial': 0, 'noops': 0,
            'unreachable': 0, 'phases': 0, 'installations': 0, 'maximum_phase_count': 0})
        group['contexts'] += 1
        group['recognized_contexts'] += int(context['recognition']['recognized'])
    seen, changed = set(), False
    with gzip.open(output / 'plans.jsonl.gz', 'rt', encoding='utf-8') as handle:
        for line in handle:
            row = json.loads(line)
            key = row['context'], row['query']
            if mutation == 'missing-query' and not changed:
                changed = True
                continue
            context, plan = contexts[row['context']], row['plan']
            if mutation == 'false-cost' and not changed and plan['status'] == 'planned':
                plan['cost']['phases'] += 1
                changed = True
            require(key not in seen and type(row['query']) is int and
                    0 <= row['query'] < len(context['tasks']), 'Duplicate or unknown query')
            seen.add(key)
            allowed, _, distances = oracles[context['name']]
            check_plan(context, row['query'], plan, allowed, distances)
            group = groups[context['family']]
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
    expected_keys = {(c['name'], q) for c in context_rows for q in range(len(c['tasks']))}
    require(seen == expected_keys, 'Saved query coverage differs')
    expected_summary = {'groups': groups, 'contexts': len(context_rows), 'queries': len(seen),
                        'recognized_contexts': sum(g['recognized_contexts'] for g in groups.values())}
    require(json.loads((output / 'summary.json').read_text()) == expected_summary, 'Summary differs')
    timing = timing_check(output, contexts, oracles)
    return {'status': 'pass', **expected_summary, 'timing': timing,
            'checks': ['exact manifest relation', 'directed chain identity', 'tight hull equivalence',
                       'independent interval phase graph', 'positive guard corners', 'directed execution witnesses',
                       'complete query coverage', 'reported totals']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    result = verify(args.results)
    if args.corruption_controls:
        result['corruption_controls'] = []
        for mutation in ('false-structure', 'false-cost', 'missing-query'):
            try:
                verify(args.results, mutation=mutation)
            except (ValueError, KeyError, TypeError) as exc:
                result['corruption_controls'].append({'name': mutation, 'rejected': True, 'reason': str(exc)})
            else:
                raise ValueError('Corrupted evidence was accepted: ' + mutation)
    text = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
