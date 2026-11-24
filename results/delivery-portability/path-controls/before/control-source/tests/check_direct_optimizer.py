"""Reconstruct registered inputs and literally check saved optimizer outputs.

Imports no producer, batch optimizer, frontier generator or study driver.
The separate certificate checker re-enumerates the declared bounded frontier.
Timing samples are observations; only their structure and arithmetic are checked.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import random
import statistics
from itertools import combinations
from pathlib import Path

from src.checker import frontier_certificate, safe_envelope

ROOT = Path(__file__).resolve().parents[1]
COUNTS = (2, 3, 4, 6)
PREFIXES = (1, 4, 16, 32)
REFUSALS = {'exact frontier local-library bound', 'exact frontier search-state bound',
            'exact frontier result bound', 'direct batch search-state bound'}
ROUTE_NS = 30_000_000_000


def require(value, message):
    if not value:
        raise ValueError(message)


def independent_context(n, b):
    candidates, current, branches = {}, {}, []
    for owner in range(n):
        node = str(owner)
        names = [f'owner{node}.cap{j}' for j in range(b)]
        current[node] = names
        sets = [tuple(range(b))] + [(j,) for j in range(b)]
        pairs = list(combinations(range(b), 2))
        offset = owner % len(pairs)
        for pair in pairs[offset:] + pairs[:offset]:
            if pair not in sets and len(sets) < 8:
                sets.append(pair)
        sets.sort(key=lambda values: sum(2**j for j in values))
        candidates[node] = [[names[j] for j in values] for values in sets]
    for j in range(b):
        branches.append({str(i): [f'owner{i}.cap{j}'] for i in range(n)})
    return {'owners': n, 'alternatives': b, 'branches': branches, 'current': current,
            'candidates': candidates, 'relevant_atoms': n*b,
            'candidate_profiles': {str(i): len(candidates[str(i)]) for i in range(n)}}


def independent_batch(inputs, seed):
    rng = random.Random(seed)
    nodes = sorted(inputs['current'])
    result = []
    for _ in range(96):
        owner = nodes[rng.randrange(len(nodes))]
        profiles = inputs['candidates'][owner]
        result.append({'node': owner, 'support': profiles[rng.randrange(len(profiles))]})
    return result


def replay(inputs, box, proposals):
    require(safe_envelope(inputs['branches'], box), 'Unsafe output product')
    state = {node: list(value) for node, value in inputs['current'].items()}
    require(all(any(set(term).issubset(state[n]) for term in box[n]) for n in state),
            'Output does not preserve the initial state')
    counts = {'installed': 0, 'blocked': 0, 'unchanged': 0, 'proposals': len(proposals)}
    for item in proposals:
        node, support = item['node'], item['support']
        if support == state[node]:
            counts['unchanged'] += 1
        elif any(all(atom in support for atom in term) for term in box[node]):
            state[node] = list(support)
            counts['installed'] += 1
        else:
            counts['blocked'] += 1
        require(any(all(set(req).issubset(state[node]) for node, req in b.items())
                    for b in inputs['branches']), 'Literal replay became incompatible')
    counts['final'] = state
    return counts


def timing(value):
    require(isinstance(value, dict) and set(value) == {'wall_ns', 'cpu_ns'}, 'Timing schema')
    require(all(type(v) is int and v >= 0 for v in value.values()), 'Timing value')


def cumulative(record, prefix, method, clock):
    if (record.get('language_preparation', {}).get('status') != 'completed'
            or len(record['queries']) < prefix
            or any(q[method]['status'] != 'completed' for q in record['queries'][:prefix])):
        return None
    total = record['language_preparation']['timing'][clock]
    if method == 'frontier':
        for field in ('frontier_construction', 'frontier_check_and_compile'):
            if record.get(field, {}).get('status') != 'completed':
                return None
            total += record[field]['timing'][clock]
    return total + sum(q[method]['timing'][clock] for q in record['queries'][:prefix])


def timed_entry(entry, spent, closed=False):
    require(entry['status'] in ('completed', 'resource-refused', 'wall-budget', 'unavailable'),
            'Timed entry outcome')
    available = 0 if closed else max(0, ROUTE_NS-spent)
    require(type(entry.get('budget_available_ns')) is int and
            entry['budget_available_ns'] == available, 'Route budget accounting differs')
    if entry['status'] == 'unavailable':
        require(available == 0 and entry.get('reason') == 'route-wall-budget-exhausted'
                and 'timing' not in entry and 'result' not in entry,
                'Unjustified exhausted route')
        return spent, True
    require(available > 0, 'Timed work without remaining route budget')
    timing(entry['timing'])
    if entry['status'] == 'resource-refused':
        require(entry.get('reason') in REFUSALS and 'result' not in entry, 'False refusal')
    if entry['status'] == 'wall-budget':
        require(entry.get('reason') == 'cumulative route wall budget exhausted'
                and 'result' not in entry, 'False timeout')
        closed = True
    return spent + entry['timing']['wall_ns'], closed


def check(directory, check_sources=True):
    summary = json.loads((directory/'summary.json').read_text())
    require(summary['status'] == 'PASS' and summary['source_unchanged'] is True, 'Run did not complete')
    if check_sources:
        for name, expected in summary['source_sha256'].items():
            require(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected, 'Current source differs: '+name)
            require(hashlib.sha256((directory/'source-preimage'/name).read_bytes()).hexdigest() == expected,
                    'Saved source differs: '+name)
    records, checked_frontiers = [], set()
    uncertified_frontier_preparations = 0
    comparable = direct_complete = frontier_complete = direct_refused = 0
    for owners in COUNTS:
        for alternatives in COUNTS:
            inputs = independent_context(owners, alternatives)
            for repetition in range(3):
                name = f'owners-{owners}-alternatives-{alternatives}-repeat-{repetition}.json'
                record = json.loads((directory/name).read_text())
                require(record['owners'] == owners and record['alternatives'] == alternatives
                        and record['repetition'] == repetition, 'Worker identity')
                require(record['inputs'] == inputs, 'Registered context differs')
                require(record['status'] in ('completed', 'language-preparation-incomplete', 'wall-time-limit'), 'Worker status')
                require(record.get('route_budget_ns') == ROUTE_NS, 'Route budget differs')
                require(len(record['queries']) == 32 if record['status'] == 'completed'
                        else len(record['queries']) <= 32, 'Query count')
                language = record.get('language_preparation')
                if language is None:
                    require(record['status'] == 'wall-time-limit' and not record['queries'], 'Missing preparation')
                    records.append(record)
                    continue
                language_spent, _ = timed_entry(language, 0)
                if language['status'] != 'completed':
                    require(record['status'] == 'language-preparation-incomplete' and not record['queries'],
                            'Queries after failed language preparation')
                    records.append(record)
                    continue
                spent = {'direct': language_spent, 'frontier': language_spent}
                closed = {'direct': False, 'frontier': False}
                for field in ('frontier_construction', 'frontier_check_and_compile'):
                    if field in record:
                        spent['frontier'], closed['frontier'] = timed_entry(record[field], spent['frontier'], closed['frontier'])
                candidate_plan = record.get('frontier_plan')
                if candidate_plan is not None:
                    require(record.get('frontier_construction', {}).get('status') == 'completed',
                            'Plan from incomplete construction')
                certified = record.get('frontier_check_and_compile',{}).get('status') == 'completed'
                require(not certified or candidate_plan is not None, 'Missing checked frontier')
                plan = candidate_plan if certified else None
                uncertified_frontier_preparations += candidate_plan is not None and not certified
                if plan is not None:
                    key = hashlib.sha256(json.dumps([inputs, plan], sort_keys=True).encode()).hexdigest()
                    if key not in checked_frontiers:
                        require(frontier_certificate(inputs['branches'], inputs['current'],
                            inputs['candidates'], plan), 'Frontier completeness rejected')
                        checked_frontiers.add(key)
                for index, query in enumerate(record['queries']):
                    seed = 91000+index
                    require(query['seed'] == seed, 'Batch seed differs')
                    proposals = independent_batch(inputs, seed)
                    require(query['proposals'] == proposals, 'Registered proposal stream differs')
                    expected_order = ['direct', 'frontier'] if (index+repetition)%2 == 0 else ['frontier', 'direct']
                    require(query['execution_order'] == expected_order, 'Measurement order differs')
                    optimum = max(replay(inputs, m['box'], proposals)['installed']
                                  for m in plan['frontier']) if plan else None
                    for method in ('direct', 'frontier'):
                        entry = query[method]
                        if entry['status'] == 'unavailable' and entry.get('reason') == 'frontier-preparation-incomplete':
                            require(method == 'frontier' and record.get('frontier_check_and_compile',{}).get('status') != 'completed'
                                    and 'timing' not in entry and 'result' not in entry,
                                    'Unjustified unavailable preparation')
                            continue
                        spent[method], closed[method] = timed_entry(entry, spent[method], closed[method])
                        if entry['status'] == 'resource-refused':
                            direct_refused += method == 'direct'
                            continue
                        if entry['status'] in ('wall-budget', 'unavailable'):
                            continue
                        if method == 'frontier':
                            require(record.get('frontier_check_and_compile',{}).get('status') == 'completed',
                                    'Frontier query before complete checking')
                        result = entry['result']
                        require(result['exact'] is True, 'Completed search not exact')
                        observed = replay(inputs, result['box'], proposals)
                        require(result['forecast'] == observed, 'Saved forecast differs from literal replay')
                        if optimum is not None:
                            require(observed['installed'] == optimum, 'Output misses checked static optimum')
                        direct_complete += method == 'direct'
                        frontier_complete += method == 'frontier'
                    comparable += all(query[m]['status'] == 'completed' for m in ('direct', 'frontier'))
                if record['status'] == 'completed':
                    require(record.get('route_wall_used_ns') == spent, 'Final route accounting differs')
                records.append(record)
    rows = []
    for owners in COUNTS:
        for alternatives in COUNTS:
            group = [r for r in records if r['owners'] == owners and r['alternatives'] == alternatives]
            for prefix in PREFIXES:
                row = {'owners': owners, 'alternatives': alternatives,
                       'relevant_atoms': owners*alternatives, 'queries': prefix, 'repetitions': len(group)}
                for method in ('direct', 'frontier'):
                    for clock in ('wall_ns', 'cpu_ns'):
                        values = [cumulative(r, prefix, method, clock) for r in group]
                        row[method+'_'+clock+'_median'] = (statistics.median(values)
                            if len(values) == 3 and all(v is not None for v in values) else None)
                row['cpu_faster'] = ('frontier' if row['frontier_cpu_ns_median'] < row['direct_cpu_ns_median'] else 'direct') if all(row[m+'_cpu_ns_median'] is not None for m in ('direct','frontier')) else 'not-comparable'
                rows.append(row)
    require(summary['cumulative_rows'] == rows, 'Cumulative summary differs')
    with (directory/'cumulative.csv').open(newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    require(len(csv_rows) == len(rows), 'CSV row count')
    for saved, expected in zip(csv_rows, rows):
        require(saved == {k: '' if v is None else str(v) for k,v in expected.items()}, 'CSV aggregate differs')
    counts = {'contexts': 16, 'repetitions_per_context': 3, 'queries_per_repetition': 32,
        'distinct_batches_per_context': 32, 'proposals_per_batch': 96, 'worker_records': len(records),
        'completed_workers': sum(r['status']=='completed' for r in records),
        'route_budget_seconds': 30,
        'wall_time_limited_workers': sum(r['status']=='wall-time-limit' for r in records),
        'frontier_construction_refusals': sum(r.get('frontier_construction',{}).get('status')=='resource-refused' for r in records),
        'frontier_preparation_wall_budgets': sum(any(r.get(f,{}).get('status') in ('wall-budget','unavailable')
            for f in ('frontier_construction','frontier_check_and_compile')) for r in records),
        'direct_completed_queries': direct_complete, 'frontier_completed_queries': frontier_complete,
        'direct_query_refusals': direct_refused, 'comparable_optima': comparable,
        'direct_query_wall_budgets': sum(q['direct']['status']=='wall-budget' for r in records for q in r['queries']),
        'frontier_query_wall_budgets': sum(q['frontier']['status']=='wall-budget' for r in records for q in r['queries'])}
    require(all(summary[k] == v for k,v in counts.items()), 'Aggregate denominator differs')
    return {'status':'PASS', **counts, 'distinct_frontiers_checked': len(checked_frontiers),
            'uncertified_frontier_preparations': uncertified_frontier_preparations,
            'scope':'Independent design reconstruction, completed-frontier completeness checks, literal forecasts and timing aggregation; unfinished frontier preparations are retained without an offline completeness or large-case optimum claim; no timing remeasurement.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT/'results/direct-optimization')
    args = parser.parse_args()
    print(json.dumps(check(args.results), indent=2))
