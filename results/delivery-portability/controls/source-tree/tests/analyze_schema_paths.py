#!/usr/bin/env python3
"""Independent topology-orbit and stage-priority analysis of saved schema queries.

Uses only the standard library and retained inputs. No production planner,
producer, codec, or earlier checker is imported. Reconstructs literal phase
graphs, validates the complete query inventory, replays every old path, and
adds six rank-aware paths with exact path segmentation. No time is measured.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from copy import deepcopy
import csv
from functools import lru_cache
import gzip
import hashlib
import io
import itertools
import json
from pathlib import Path


OWNERS = (0, 1, 2)
ORDERS = tuple(itertools.permutations(OWNERS))
EDGE_ORDER = tuple(itertools.permutations(OWNERS, 2))
FAMILIES = ('enum-alias', 'field-key', 'field-addition', 'integer-widening')


def require(value, message):
    if not value:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def edges(mask):
    return tuple(edge for bit, edge in enumerate(EDGE_ORDER) if mask >> bit & 1)


def relabel_mask(mask, order):
    changed = {(order[u], order[v]) for u, v in edges(mask)}
    return sum(1 << bit for bit, edge in enumerate(EDGE_ORDER) if edge in changed)


def relabel_state(state, order):
    out = [0] * 3
    for old, new in enumerate(order):
        out[new] = state[old]
    return tuple(out)


@lru_cache(None)
def canonical_graph(mask):
    return min(relabel_mask(mask, order) for order in ORDERS)


@lru_cache(None)
def canonical_query(mask, source, target):
    return min((relabel_mask(mask, order), relabel_state(source, order),
                relabel_state(target, order)) for order in ORDERS)


def motif_name(mask):
    if mask == 25:
        return 'directed three-cycle'
    if mask == 27:
        return 'directed three-cycle plus one reverse edge'
    return 'other graph with ' + str(len(edges(mask))) + ' edges'


class LiteralGraph:
    def __init__(self, relation, mask):
        self.relation = tuple(tuple(x) for x in relation)
        self.edges = edges(mask)
        self.states = tuple(x for x in itertools.product(range(len(relation)), repeat=3)
                            if self.safe(x))
        self.allowed = set(self.states)
        self.arcs = {x: tuple(y for y in self.states if y != x and self.box(x, y))
                     for x in self.states}
        self.distances = {x: self.distance(x) for x in self.states}
        self.priority = {(x, o): self.owner_paths(x, o) for x in self.states for o in ORDERS}

    def safe(self, state):
        return all(self.relation[state[u]][state[v]] for u, v in self.edges)

    def box(self, source, target):
        return (all(a <= b for a, b in zip(source, target)) and
                all(self.relation[a][b] for u, v in self.edges
                    for a in range(source[u], target[u] + 1)
                    for b in range(source[v], target[v] + 1)))

    def distance(self, source):
        found = {source: 0}
        queue = deque([source])
        while queue:
            x = queue.popleft()
            for y in self.arcs[x]:
                if y not in found:
                    found[y] = found[x] + 1
                    queue.append(y)
        return found

    def owner_paths(self, source, order):
        found = {source: (source,)}
        queue = deque([source])
        while queue:
            x = queue.popleft()
            for i in order:
                y = tuple(v + (j == i) for j, v in enumerate(x))
                if y in self.allowed and y not in found:
                    found[y] = found[x] + (y,)
                    queue.append(y)
        return found

    @lru_cache(None)
    def stage_path(self, source, target, order):
        # Only target-directed one-rank moves may be used. Rank is physical
        # chain position, not an inferred compatibility or semantic label.
        if target not in self.distances[source]:
            return None
        path = [source]
        while path[-1] != target:
            x = path[-1]
            available = []
            for tie, i in enumerate(order):
                if x[i] < target[i]:
                    y = tuple(v + (j == i) for j, v in enumerate(x))
                    if y in self.allowed:
                        available.append((x[i], tie, y))
            if not available:
                return None
            path.append(min(available)[2])
        return tuple(path)

    @lru_cache(None)
    def partition(self, path):
        if path is None:
            return None, None
        n = len(path)
        cost, previous = [0] + [n + 1] * (n - 1), [None] * n
        for end in range(1, n):
            for begin in range(end):
                if self.box(path[begin], path[end]) and cost[begin] + 1 < cost[end]:
                    cost[end] = cost[begin] + 1
                    previous[end] = begin
        cuts = [n - 1]
        while cuts[-1] != 0:
            cuts.append(previous[cuts[-1]])
        return cost[-1], tuple(reversed(cuts))


def counter():
    return Counter({'queries': 0, 'no_ops': 0, 'reachable_changes': 0,
                    'unreachable': 0, 'exact_phases': 0,
                    'owner_six_phases': 0, 'stage_fixed_phases': 0,
                    'stage_six_phases': 0, 'combined_seven_phases': 0,
                    'owner_six_gap_goals': 0, 'stage_fixed_gap_goals': 0,
                    'stage_six_gap_goals': 0, 'combined_seven_gap_goals': 0,
                    'full_goals': 0, 'full_owner_six_gap_goals': 0,
                    'full_stage_fixed_gap_goals': 0, 'full_stage_six_gap_goals': 0})


def accumulate(counts, costs, full):
    exact, owner, fixed, stage, seven = costs
    counts['queries'] += 1
    if exact is None:
        counts['unreachable'] += 1
        return
    if exact == 0:
        counts['no_ops'] += 1
        return
    counts['reachable_changes'] += 1
    for name, value in [('exact', exact), ('owner_six', owner), ('stage_fixed', fixed),
                        ('stage_six', stage), ('combined_seven', seven)]:
        counts[name + '_phases'] += value
        if name != 'exact':
            counts[name + '_gap_goals'] += int(value > exact)
    if full:
        counts['full_goals'] += 1
        for name, value in [('owner_six', owner), ('stage_fixed', fixed), ('stage_six', stage)]:
            counts['full_' + name + '_gap_goals'] += int(value > exact)


def analyze(census):
    contexts = json.loads((census / 'contexts.json').read_text())
    probes = json.loads((census / 'probes.json').read_text())
    require({x['family'] for x in probes} == set(FAMILIES), 'family inventory differs')
    context_map = {x['id']: x for x in contexts}
    require(len(context_map) == len(contexts) == 252, 'context count differs')
    relations = {x['family']: x['relation'] for x in probes}
    require(set(relations) == set(FAMILIES), 'probe family inventory differs')
    expected = {(f, m) for f in FAMILIES for m in range(1, 64)}
    require({(x['family'], x['graph_mask']) for x in contexts} == expected,
            'complete graph inventory differs')
    for x in contexts:
        require(tuple(map(tuple, x['edges'])) == edges(x['graph_mask']), 'context edges differ')
    graphs = {}
    family_rows, motif_rows, gap_orbits, fixed_stage_examples = [], [], {}, []
    for family in FAMILIES:
        relation = relations[family]
        relation_key = tuple(map(tuple, relation))
        total = counter()
        by_motif = {m: counter() for m in sorted({canonical_graph(k) for k in range(1, 64)})}
        query_orbits, reachable_orbits, owner_gap_orbits, fixed_gap_orbits = set(), set(), set(), set()
        seen = {mask: set() for mask in range(1, 64)}
        group_examples = set()
        with gzip.open(census / (family + '.jsonl.gz'), 'rt', encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                ctx = context_map[row['context']]
                require(ctx['family'] == family, 'query family differs')
                mask = ctx['graph_mask']
                key = relation_key, mask
                if key not in graphs:
                    graphs[key] = LiteralGraph(relation, mask)
                graph = graphs[key]
                source, target = tuple(row['source']), tuple(row['target'])
                require(source in graph.allowed and target in graph.allowed, 'query is incompatible')
                require((source, target) not in seen[mask], 'query repeated')
                seen[mask].add((source, target))
                exact = graph.distances[source].get(target)
                answer = row['answer']
                if exact is None:
                    require(answer['status'] == 'unreachable', 'unreachable answer differs')
                else:
                    require(answer['status'] == 'planned' and answer['cost']['phases'] == exact,
                            'literal optimum differs from saved planner')
                    require(answer['cost']['installations'] == sum(b - a for a, b in zip(source, target)),
                            'installation count differs')
                require(tuple(tuple(x['order']) for x in row['routes']) == ORDERS, 'priority order inventory differs')
                owner_costs = []
                for route, order in zip(row['routes'], ORDERS):
                    path = graph.priority[source, order].get(target)
                    saved_path = None if route['path'] is None else tuple(map(tuple, route['path']))
                    require(saved_path == path, 'saved owner-priority path differs')
                    count, cuts = graph.partition(path)
                    require(route['phases'] == count, 'saved path partition cost differs')
                    require((None if route['cuts'] is None else tuple(route['cuts'])) == cuts,
                            'saved optimal cuts differ')
                    owner_costs.append(count)
                stage_paths = [graph.stage_path(source, target, order) for order in ORDERS]
                stage_costs = [graph.partition(path)[0] for path in stage_paths]
                if exact is None:
                    require(all(x is None for x in owner_costs + stage_costs), 'unreachable route returned')
                    costs = (None,) * 5
                else:
                    require(all(x is not None and x >= exact for x in owner_costs + stage_costs),
                            'stage route missing or below optimum')
                    owner, fixed, stage = min(owner_costs), stage_costs[0], min(stage_costs)
                    costs = exact, owner, fixed, stage, min(owner, fixed)
                full = source == (0, 0, 0) and target == (len(relation) - 1,) * 3
                accumulate(total, costs, full)
                motif = canonical_graph(mask)
                accumulate(by_motif[motif], costs, full)
                orbit = canonical_query(mask, source, target)
                query_orbits.add(orbit)
                if exact:
                    reachable_orbits.add(orbit)
                    if costs[1] > exact:
                        owner_gap_orbits.add(orbit)
                        orbit_key = family, orbit
                        if orbit_key not in gap_orbits:
                            canonical_mask, canonical_source, canonical_target = orbit
                            gap_orbits[orbit_key] = {
                                'family': family, 'canonical_graph': canonical_mask,
                                'edges': [list(x) for x in edges(canonical_mask)],
                                'source': canonical_source, 'target': canonical_target,
                                'exact_phases': exact, 'owner_six_phases': costs[1],
                                'stage_six_phases': costs[3], 'labelled_query_members': 0,
                            }
                        gap_orbits[orbit_key]['labelled_query_members'] += 1
                    if costs[2] > exact:
                        fixed_gap_orbits.add(orbit)
                        if motif not in group_examples:
                            group_examples.add(motif)
                            fixed_stage_examples.append({
                                'family': family, 'context': ctx['id'],
                                'source': source, 'target': target, 'exact_phases': exact,
                                'fixed_stage_phases': costs[2], 'stage_six_phases': costs[3],
                                'stage_paths': stage_paths,
                                'stage_path_costs': stage_costs,
                                'stage_path_cuts': [graph.partition(p)[1] for p in stage_paths],
                            })
        for mask in range(1, 64):
            graph = graphs[relation_key, mask]
            require(seen[mask] == set(itertools.product(graph.states, repeat=2)),
                    'complete ordered goal inventory differs')
        family_rows.append({'family': family, 'graphs': 63, 'graph_isomorphism_classes': len(by_motif),
                            'query_orbits': len(query_orbits), 'reachable_change_orbits': len(reachable_orbits),
                            'owner_six_gap_orbits': len(owner_gap_orbits),
                            'query_orbits_with_fixed_stage_gap': len(fixed_gap_orbits), **dict(total)})
        for motif, counts in by_motif.items():
            members = [m for m in range(1, 64) if canonical_graph(m) == motif]
            motif_rows.append({'family': family, 'canonical_graph': motif,
                               'name': motif_name(motif), 'edges': [list(x) for x in edges(motif)],
                               'labelled_graphs': members, 'graphs': len(members), **dict(counts)})
    aggregate = counter()
    for row in family_rows:
        aggregate.update({key: row[key] for key in aggregate})
    summary = {
        'status': 'PASS',
        'scope': 'Exhaustive reconstruction of the registered homogeneous three-owner schema census; no production prevalence or universal heuristic-optimality claim.',
        'comparators': {
            'owner_six': 'Best exact partition of six breadth-first shortest-safe paths with static owner expansion order.',
            'stage_fixed': 'At each target-directed one-rank step choose the enabled owner with least current rank; break ties by 0,1,2; then find the exact minimum-phase partition of that path.',
            'stage_six': 'Best exact partition of the six least-current-rank paths, one per static owner tie order.',
            'combined_seven': 'Best of the existing six owner-priority paths and the fixed 0,1,2 stage-priority path.',
            'exact': 'Independent breadth-first search of every literal safe interval phase between compatible physical states.',
        },
        'graph_isomorphism_classes': len({canonical_graph(m) for m in range(1, 64)}),
        'families': family_rows, 'aggregate': dict(aggregate),
        'motifs': motif_rows,
        'owner_six_gap_query_orbits': list(gap_orbits.values()),
        'fixed_stage_gap_representatives': fixed_stage_examples,
    }
    return summary


def finite_analysis(directory):
    with gzip.open(directory / 'contexts.json.gz', 'rt') as stream:
        contexts = {row['name']: row for row in json.load(stream)}
    graphs = {}
    for name, context in contexts.items():
        owners = tuple(str(i) for i in range(len(context['shape'])))
        catalog = {i: tuple(map(frozenset, context['catalog'][i])) for i in owners}
        closed = True
        for factor in context['factors']:
            placement = sorted({i for branch in factor['branches'] for i in branch}, key=int)
            relation = set()
            for ranks in itertools.product(*(range(len(catalog[i])) for i in placement)):
                support = {i: catalog[i][r] for i, r in zip(placement, ranks)}
                if any(all(set(req) <= support[i] for i, req in branch.items()) for branch in factor['branches']):
                    relation.add(ranks)
            if any(tuple(max(a, b) for a, b in zip(x, y)) not in relation
                   for x in relation for y in relation):
                closed = False
        if closed:
            require(context.get('recognition', {}).get('recognized') is True,
                    'finite recognition differs')
        else:
            require('refusal' in context and 'recognition' not in context,
                    'nonclosed finite factor lacks its recorded refusal')
        if not closed:
            continue
        allowed = set()
        for state in itertools.product(*(range(q) for q in context['shape'])):
            support = {i: catalog[i][r] for i, r in zip(owners, state)}
            if all(any(all(set(req) <= support[i] for i, req in branch.items())
                       for branch in factor['branches']) for factor in context['factors']):
                allowed.add(state)

        def safe_box(source, target, allowed=allowed):
            return (all(a <= b for a, b in zip(source, target)) and
                    all(x in allowed for x in itertools.product(*(range(a, b + 1)
                        for a, b in zip(source, target)))))

        arcs = {x: [y for y in sorted(allowed) if y != x and safe_box(x, y)] for x in allowed}
        distances, fixed_paths = {}, {}
        orders = tuple(itertools.permutations(range(len(owners))))
        for source in allowed:
            found, queue = {source: 0}, deque([source])
            while queue:
                x = queue.popleft()
                for y in arcs[x]:
                    if y not in found:
                        found[y] = found[x] + 1
                        queue.append(y)
            distances[source] = found
            for order in orders:
                paths, queue = {source: (source,)}, deque([source])
                while queue:
                    x = queue.popleft()
                    for i in order:
                        y = tuple(v + (j == i) for j, v in enumerate(x))
                        if y in allowed and y not in paths:
                            paths[y] = paths[x] + (y,)
                            queue.append(y)
                fixed_paths[source, order] = paths
        graphs[name] = (allowed, safe_box, distances, fixed_paths, orders)
    counts = Counter({'queries': 0, 'no_ops': 0, 'reachable_changes': 0, 'unreachable': 0,
                      'owner_portfolio_gap_goals': 0, 'stage_portfolio_gap_goals': 0,
                      'combined_portfolio_gap_goals': 0})
    gaps, seen = [], {name: set() for name in graphs}
    with gzip.open(directory / 'plans.jsonl.gz', 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            name = row['context']
            require(name in graphs, 'query belongs to an unrecognized context')
            allowed, safe_box, distances, fixed_paths, orders = graphs[name]
            source, target = tuple(row['source']), tuple(row['target'])
            require(source in allowed and target in allowed, 'finite query incompatible')
            require((source, target) not in seen[name], 'finite query repeated')
            seen[name].add((source, target))
            counts['queries'] += 1
            exact = distances[source].get(target)
            answer = row['result']
            if exact is None:
                require(answer['status'] == 'unreachable', 'finite unreachability differs')
                counts['unreachable'] += 1
                continue
            require(answer['status'] == 'planned' and answer['cost']['phases'] == exact,
                    'finite optimum differs')
            if exact == 0:
                counts['no_ops'] += 1
                continue
            counts['reachable_changes'] += 1
            stage_costs, owner_costs, stage_witnesses = [], [], []

            def partition(path):
                values = [0] + [len(path) + 1] * (len(path) - 1)
                cuts = [None] * len(path)
                for end in range(1, len(path)):
                    for begin in range(end):
                        if safe_box(path[begin], path[end]) and values[begin] + 1 < values[end]:
                            values[end] = values[begin] + 1
                            cuts[end] = begin
                chosen = [len(path) - 1]
                while chosen[-1] != 0:
                    chosen.append(cuts[chosen[-1]])
                return values[-1], tuple(reversed(chosen))

            for order in orders:
                x, path = source, [source]
                while x != target:
                    available = []
                    for tie, i in enumerate(order):
                        if x[i] < target[i]:
                            y = tuple(v + (j == i) for j, v in enumerate(x))
                            if y in allowed:
                                available.append((x[i], tie, y))
                    require(available, 'finite reachable goal blocked under stage rule')
                    x = min(available)[2]
                    path.append(x)
                cost, cuts = partition(path)
                stage_costs.append(cost)
                stage_witnesses.append({'order': order, 'path': path, 'phases': cost, 'cuts': cuts})
                owner_costs.append(partition(fixed_paths[source, order][target])[0])
            owner, stage = min(owner_costs), min(stage_costs)
            require(owner >= exact and stage >= exact, 'finite path beats exact graph')
            counts['owner_portfolio_gap_goals'] += int(owner > exact)
            counts['stage_portfolio_gap_goals'] += int(stage > exact)
            counts['combined_portfolio_gap_goals'] += int(min(owner, stage) > exact)
            if owner > exact or stage > exact:
                gaps.append({'context': name, 'source': source, 'target': target,
                             'exact_phases': exact, 'owner_portfolio_phases': owner,
                             'stage_portfolio_phases': stage,
                             'relation': sorted(allowed), 'stage_paths': stage_witnesses,
                             'exact_endpoints': answer['search']['rank_iterates']})
    for name, (allowed, *_rest) in graphs.items():
        require(seen[name] == set(itertools.product(allowed, repeat=2)), 'finite inventory incomplete')
    return {'status': 'PASS', 'scope': 'Retained finite compatibility relations; not application deployment observations.',
            'registered_contexts': len(contexts), 'recognized_contexts': len(graphs),
            'counts': dict(counts), 'gaps': gaps}


def validate_summary(saved, expected):
    require(encoded(saved) == encoded(expected), 'derived analysis differs from independent reconstruction')


def corruption_controls(expected):
    cases = []
    def reject(name, mutate):
        altered = json.loads(encoded(expected))
        mutate(altered)
        try:
            validate_summary(altered, expected)
        except ValueError:
            cases.append({'control': name, 'rejected': True})
        else:
            raise ValueError('failed to reject altered analysis: ' + name)

    def hidden_gap(x):
        for row in [x['aggregate'], x['families'][0],
                    next(m for m in x['motifs'] if m['family'] == FAMILIES[0] and m['canonical_graph'] == 25)]:
            row['owner_six_gap_goals'] -= 1
            row['owner_six_phases'] -= 1
    reject('remove_owner_gap_without_changing_query_denominators', hidden_gap)

    def false_stage_gap(x):
        for row in [x['aggregate'], x['families'][0],
                    next(m for m in x['motifs'] if m['family'] == FAMILIES[0] and m['canonical_graph'] == 25)]:
            row['stage_six_gap_goals'] += 1
            row['stage_six_phases'] += 1
    reject('invent_stage_portfolio_gap_with_consistent_aggregate_totals', false_stage_gap)

    def move_motif_gap(x):
        for mask, delta in [(25, 1), (27, -1)]:
            row = next(m for m in x['motifs'] if m['family'] == FAMILIES[0] and m['canonical_graph'] == mask)
            row['owner_six_gap_goals'] += delta
            row['owner_six_phases'] += delta
    reject('move_gap_between_motifs_preserving_family_totals', move_motif_gap)

    def move_orbit_member(x):
        x['owner_six_gap_query_orbits'][0]['labelled_query_members'] += 1
        x['owner_six_gap_query_orbits'][1]['labelled_query_members'] -= 1
    reject('change_orbit_multiplicities_preserving_total_gaps', move_orbit_member)

    def erase_finite(x):
        x['finite_control']['counts']['stage_portfolio_gap_goals'] = 0
        x['finite_control']['gaps'] = []
    reject('erase_the_two_finite_stage_counterexamples', erase_finite)

    def change_path(x):
        x['finite_control']['gaps'][0]['stage_paths'][0]['path'][1][0] += 1
    reject('alter_finite_counterexample_path_with_unchanged_cost', change_path)
    return {'status': 'PASS', 'scope': 'Six readable derived-record mutations checked against full independent reconstruction; raw inputs remain unchanged.',
            'controls': cases}


def motif_csv(result):
    rows = [{key: value for key, value in row.items() if key not in {'edges', 'labelled_graphs'}}
            for row in result['motifs']]
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()


def bindings(census, finite):
    files = ['contexts.json', 'probes.json'] + [name + '.jsonl.gz' for name in FAMILIES]
    return {**{'schema-census/' + name: digest(census / name) for name in files},
            **{'factored-planning/' + name: digest(finite / name)
               for name in ['contexts.json.gz', 'plans.jsonl.gz']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--census', type=Path, required=True)
    parser.add_argument('--finite', type=Path, help='Defaults to factored-planning beside the census directory.')
    parser.add_argument('--corruption-controls', action='store_true')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--out', type=Path)
    group.add_argument('--check', type=Path)
    args = parser.parse_args()
    census = args.census.resolve()
    finite = (args.finite or census.parent / 'factored-planning').resolve()
    before = bindings(census, finite)
    result = analyze(census)
    result['finite_control'] = finite_analysis(finite)
    controls = corruption_controls(result) if args.corruption_controls else None
    require(before == bindings(census, finite), 'source evidence changed during analysis')
    if args.check:
        directory = args.check.resolve()
        validate_summary(json.loads((directory / 'summary.json').read_text()), result)
        meta = json.loads((directory / 'inputs.json').read_text())
        require(meta['inputs'] == before, 'saved input bindings differ')
        require(meta['analyzer'] == digest(Path(__file__)), 'analyzer source differs')
        require((directory / 'sources' / Path(__file__).name).read_bytes() == Path(__file__).read_bytes(),
                'retained analyzer source differs')
        require((directory / 'motifs.csv').read_bytes() == motif_csv(result).encode(), 'saved motif table differs')
        print(encoded({'status': 'PASS', 'queries': result['aggregate']['queries'],
                       'contexts': 252, 'graph_isomorphism_classes': result['graph_isomorphism_classes'],
                       'stage_six_gap_goals': result['aggregate']['stage_six_gap_goals'],
                       'owner_six_gap_goals': result['aggregate']['owner_six_gap_goals'],
                       'finite_control': result['finite_control']['counts'],
                       'corruption_controls': controls}), end='')
    else:
        directory = args.out.resolve()
        require(not directory.exists(), 'use a fresh output directory')
        directory.mkdir(parents=True)
        (directory / 'summary.json').write_text(encoded(result))
        (directory / 'inputs.json').write_text(encoded({'inputs': before, 'analyzer': digest(Path(__file__)),
            'input_location': 'artifact/results', 'producer': Path(__file__).name,
            'measurement': 'none; analysis of retained exact state and path records'}))
        (directory / 'sources').mkdir()
        (directory / 'sources' / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
        (directory / 'motifs.csv').write_bytes(motif_csv(result).encode())
        if controls is not None:
            (directory / 'corruption-controls.json').write_text(encoded(controls))
        print(encoded({'status': 'PASS', 'out': str(directory), 'aggregate': result['aggregate'],
                       'families': result['families']}), end='')


if __name__ == '__main__':
    main()
