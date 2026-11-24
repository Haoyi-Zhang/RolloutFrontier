"""Actual-codec and exact-planning study for alternative compatible readers.

Three owners independently prepare one parser and activate one emitter. Each
selected producer may route its single-field record to either other owner.
The ordered finite catalog is all seven nonempty producer sets and all eight
local prepare/emission order combinations. The complete compatible endpoint
inventory is retained; forward queries and direction refusals are counted
separately. Every baseline is exact for this single-field event construction.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import csv
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path
import platform
import sys

from google.protobuf import __version__ as protobuf_version
from src.factored_planner import FactoredChainPlanner, validate_factored_plan
from src.heterogeneous_contracts import measure_channel


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = ('src/factored_planner.py', 'src/heterogeneous_contracts.py',
                'src/controller.py', 'src/envelope.py',
                'tests/alternate_reader_study.py', 'tests/alternate_reader_check.py',
                'tests/factored_planning_oracle.py')


def require(value, reason):
    if not value:
        raise ValueError(reason)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n')


def flags(order, rank):
    done = order[:rank]
    return int('e' in done), int('p' in done)


def context(mask, orders, matrix):
    names = tuple(str(i) for i in range(3))
    producers = tuple(i for i in range(3) if mask & (1 << i))
    catalog = {}
    for i, owner in enumerate(names):
        profiles = []
        for rank in range(3):
            e, p = flags(orders[i], rank)
            support = [f'program:e{e}p{p}', 'emit:' + ('new' if e else 'old'),
                       'accept:old']
            if matrix[p][1]:
                support.append('accept:new')
            profiles.append(sorted(support))
        require(len({tuple(v) for v in profiles}) == 3, 'nonobservable local event')
        catalog[owner] = profiles
    transitions = {owner: [{'source': a, 'target': b} for a, b in zip(profiles, profiles[1:])]
                   for owner, profiles in catalog.items()}
    factors = []
    for producer in producers:
        branches = []
        for receiver in range(3):
            if receiver == producer:
                continue
            for cls in ('old', 'new'):
                branch = {n: [] for n in names}
                branch[str(producer)] = ['emit:' + cls]
                branch[str(receiver)] = ['accept:' + cls]
                branches.append(branch)
        factors.append({'id': 'choice-' + str(producer), 'branches': branches})
    states = tuple(product(range(3), repeat=3))

    def accepted(state):
        ep = tuple(flags(order, rank) for order, rank in zip(orders, state))
        return all(any(matrix[ep[v][1]][ep[u][0]] for v in range(3) if v != u)
                   for u in producers)

    allowed = frozenset(s for s in states if accepted(s))
    for state in states:
        supports = {owner: set(catalog[owner][state[i]]) for i, owner in enumerate(names)}
        formula = all(any(all(set(req) <= supports[n] for n, req in branch.items())
                          for branch in factor['branches']) for factor in factors)
        require(formula == (state in allowed), 'factor differs from observed parser alternatives')
    join_pairs = 0
    meet_witness = None
    for first in sorted(allowed):
        for second in sorted(allowed):
            require(tuple(max(a, b) for a, b in zip(first, second)) in allowed,
                    'observed choice relation is not max closed')
            join_pairs += 1
            meet = tuple(min(a, b) for a, b in zip(first, second))
            if meet_witness is None and meet not in allowed:
                meet_witness = {'first': first, 'second': second, 'minimum': meet}
    return {'id': f'{mask}-' + '-'.join(''.join(o) for o in orders),
            'mask': mask, 'producers': producers, 'orders': orders,
            'catalog': catalog, 'transitions': transitions, 'factors': factors,
            'allowed': sorted(allowed), 'checked_ordered_joins': join_pairs,
            'not_min_closed_witness': meet_witness}


def literal_graph(allowed):
    allowed = frozenset(map(tuple, allowed))
    edges = {}
    for source in sorted(allowed):
        targets = []
        for target in sorted(allowed):
            if source == target or any(a > b for a, b in zip(source, target)):
                continue
            if all(cell in allowed for cell in product(*(range(a, b + 1)
                                                         for a, b in zip(source, target)))):
                targets.append(target)
        edges[source] = targets
    return edges


def literal_distances(graph, source):
    distance = {source: 0}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        for following in graph[current]:
            if following not in distance:
                distance[following] = distance[current] + 1
                queue.append(following)
    return distance


def event_problem(ctx, source, target):
    if any(a > b for a, b in zip(source, target)):
        return None
    orders = ctx['orders']
    events = tuple((i, rank) for i in range(3)
                   for rank in range(source[i] + 1, target[i] + 1))
    previous = {(i, rank): ((i, rank - 1) if rank - 1 > source[i] else None)
                for i, rank in events}
    options = {}
    for i, rank in events:
        if orders[i][rank - 1] != 'e' or i not in ctx['producers']:
            continue
        choices = []
        for receiver in range(3):
            if receiver == i:
                continue
            prepared_rank = orders[receiver].index('p') + 1
            if source[receiver] >= prepared_rank:
                choices.append(None)  # Already available at the phase source.
            elif target[receiver] >= prepared_rank:
                choices.append((receiver, prepared_rank))
            else:
                choices.append('absent')
        options[(i, rank)] = tuple(choices)
    return events, previous, options


def or_fixed_point(ctx, source, target):
    problem = event_problem(ctx, source, target)
    if problem is None:
        return None, None
    events, previous, options = problem
    if not events:
        return 0, {}
    infinity = len(events) + 1
    times = {event: 1 for event in events}
    changed = True
    while changed:
        changed = False
        for event in events:
            value = max(1, times.get(previous[event], 0))
            if event in options:
                earliest = min(0 if choice is None else infinity if choice == 'absent'
                               else times[choice] for choice in options[event])
                value = max(value, min(infinity, earliest + 1))
            require(value >= times[event], 'monotone recurrence decreased')
            if value != times[event]:
                changed = True
                times[event] = value
    if infinity in times.values():
        return None, times
    return max(times.values()), times


def chosen_event_graph(ctx, source, target):
    problem = event_problem(ctx, source, target)
    if problem is None:
        return None, 0
    events, previous, options = problem
    if not events:
        return 0, 1
    emitting = tuple(options)
    best = None
    graphs = 0
    for choices in product(*(options[e] for e in emitting)):
        graphs += 1
        if 'absent' in choices:
            continue
        edges = {e: [] for e in events}
        degree = {e: 0 for e in events}
        for event in events:
            if previous[event] is not None:
                edges[previous[event]].append((event, 0))
                degree[event] += 1
        for event, selected in zip(emitting, choices):
            if selected is not None:
                edges[selected].append((event, 1))
                degree[event] += 1
        queue = deque(e for e in events if degree[e] == 0)
        times = {e: 1 for e in events}
        count = 0
        while queue:
            event = queue.popleft()
            count += 1
            for target_event, weight in edges[event]:
                times[target_event] = max(times[target_event], times[event] + weight)
                degree[target_event] -= 1
                if degree[target_event] == 0:
                    queue.append(target_event)
        if count == len(events):
            cost = max(times.values())
            best = cost if best is None else min(best, cost)
    return best, graphs


def verify_phase_labels(ctx, source, target, times, expected):
    if expected is None or expected == 0:
        return
    allowed = set(map(tuple, ctx['allowed']))
    current = tuple(source)
    for phase in range(1, expected + 1):
        following = tuple(max([source[i], *(r for (owner, r), t in times.items()
                                            if owner == i and t <= phase)]) for i in range(3))
        require(current != following, 'event schedule emitted an empty phase')
        require(all(cell in allowed for cell in product(*(range(a, b + 1)
                                                        for a, b in zip(current, following)))),
                'fixed-point phase is unsafe in the literal relation')
        current = following
    require(current == target, 'event schedule did not reach the goal')


def run(output):
    require(not output.exists(), 'Use a fresh output directory')
    output.mkdir(parents=True)
    before = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in DEPENDENCIES}
    probe = measure_channel(0, 1, ('choice',))
    require(probe['matrix'] == [[1, 0], [1, 1]], 'unexpected actual single-field parser relation')
    save(output / 'actual-channel-probe.json', probe)
    contexts = [context(mask, orders, probe['matrix']) for mask in range(1, 8)
                for orders in product((('p', 'e'), ('e', 'p')), repeat=3)]
    totals = Counter()
    summaries = []
    forward_phase_counts = Counter()
    with gzip.open(output / 'plans.jsonl.gz', 'wt', encoding='utf-8') as plans, \
            (output / 'queries.csv').open('w', newline='') as table:
        writer = csv.writer(table)
        writer.writerow(('context', 'source', 'target', 'literal_phases', 'or_fixed_point_phases',
                         'best_chosen_dag_phases', 'production_status', 'production_phases',
                         'production_installations', 'chosen_graphs_checked', 'forward'))
        for ctx in contexts:
            planner = FactoredChainPlanner(ctx['factors'], ctx['catalog'], ctx['transitions'])
            ctx['recognition'] = planner.recognition()
            allowed = tuple(map(tuple, ctx['allowed']))
            graph = literal_graph(allowed)
            counts = Counter()
            full = None
            for source in allowed:
                distances = literal_distances(graph, source)
                for target in allowed:
                    expected = distances.get(target)
                    least, labels = or_fixed_point(ctx, source, target)
                    chosen, graph_count = chosen_event_graph(ctx, source, target)
                    require(least == expected == chosen, 'independent exact methods disagree')
                    verify_phase_labels(ctx, source, target, labels, least)
                    current = {str(i): ctx['catalog'][str(i)][source[i]] for i in range(3)}
                    goal = {str(i): ctx['catalog'][str(i)][target[i]] for i in range(3)}
                    answer = planner.plan(current, goal)
                    require(answer['status'] == ('unreachable' if expected is None else 'planned'),
                            'production reachability differs')
                    if expected is not None:
                        require(answer['cost']['phases'] == expected, 'production phase cost differs')
                        require(answer['cost']['installations'] == sum(b-a for a,b in zip(source,target)),
                                'production installation count differs')
                        validate_factored_plan(answer)
                    counts['queries'] += 1
                    counts['chosen_graphs'] += graph_count
                    counts['unreachable' if expected is None else 'noops' if expected == 0 else 'reachable_changes'] += 1
                    forward = all(a <= b for a, b in zip(source, target))
                    counts['forward_queries' if forward else 'direction_refusals'] += 1
                    if forward:
                        forward_phase_counts['unreachable' if expected is None else str(expected)] += 1
                        if expected is None:
                            counts['forward_obstructions'] += 1
                    if source == (0, 0, 0) and target == (2, 2, 2):
                        full = {'status':answer['status'], 'cost':answer['cost'],
                                'rank_iterates':answer['search']['rank_iterates']}
                    compact = {key:value for key,value in answer.items()
                               if key not in {'factors','catalog','transitions','recognition','budgets'}}
                    labels_record = None if labels is None else [
                        [owner, rank, value] for (owner, rank), value in sorted(labels.items())]
                    plans.write(json.dumps({'context':ctx['id'],'source':source,'target':target,
                                            'answer':compact,
                                            'comparisons':{'literal_phases':expected,
                                                           'or_fixed_point_phases':least,
                                                           'or_event_rounds':labels_record,
                                                           'best_chosen_dag_phases':chosen,
                                                           'chosen_graphs_checked':graph_count}},
                                           separators=(',',':'),sort_keys=True) + '\n')
                    writer.writerow((ctx['id'], ''.join(map(str,source)), ''.join(map(str,target)),
                                     expected, least, chosen, answer['status'],
                                     answer['cost']['phases'] if answer['cost'] else '',
                                     answer['cost']['installations'] if answer['cost'] else '', graph_count,
                                     int(forward)))
            row = {'id':ctx['id'],'compatible_states':len(allowed),
                   'phase_edges':sum(map(len,graph.values())),
                   'not_min_closed_witness':ctx['not_min_closed_witness'],
                   'full_migration':full, **dict(counts)}
            summaries.append(row)
            totals.update(counts)
            print(json.dumps({'context':ctx['id'],**dict(counts)}), flush=True)
    save(output / 'contexts.json', contexts)
    after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in DEPENDENCIES}
    require(before == after, 'a used production source changed during the exploration')
    for name in DEPENDENCIES:
        path = output / 'sources' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    save(output / 'metadata.json',
         {'python':sys.version,'platform':platform.platform(),'protobuf':protobuf_version,
          'sources':before,'sources_unchanged':True,
          'inventory':{'physical_owners':3,'events_per_owner':2,'producer_sets':7,
                       'local_event_orders':8,'all_compatible_ordered_endpoints':True},
          'request_contract':'One single-field record is processed by one of the two other owners; '
                             'both readers retain old-message support after preparation.',
          'codec_reuse':'One measured single-field channel is instantiated in all finite contexts; '
                       'planning query counts are not serialization or parser invocation counts.'})
    report = {'status':'PASS',
              'contexts':len(contexts),'every_context_max_closed':True,
              'contexts_not_min_closed':sum(c['not_min_closed_witness'] is not None for c in contexts),
              'actual_parser_matrix_calls':len(probe['parses']),
              'actual_emitted_wire_records':len(probe['wires']),
              'additional_parser_event_witness_calls':2*len(probe['event_effect_witnesses']),
              'actual_emitter_calls':len(probe['wires']) + 3*len(probe['event_effect_witnesses']),
              'all_compatible_source_target_pairs_covered':True,
              'planning_compared_to_actual_codec_derived_relations':True,
              'production_planner_queries':totals['queries'],
              'or_fixed_point_equals_literal_and_best_selected_dag':True,
              'forward_phase_counts':dict(forward_phase_counts),
              'full_migrations':dict(Counter('unreachable' if s['full_migration']['cost'] is None
                                             else str(s['full_migration']['cost']['phases'])+' phases'
                                             for s in summaries)),
              'counts':dict(totals),'catalogs':summaries}
    save(output / 'summary.json', report)
    print(json.dumps({k:v for k,v in report.items() if k!='catalogs'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    run(parser.parse_args().out.resolve())
