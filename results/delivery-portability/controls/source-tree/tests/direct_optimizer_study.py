"""Registered structural scale and direct-versus-frontier reuse measurements."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import platform
import random
import shutil
import signal
import statistics
import subprocess
import sys
import time
from itertools import combinations
from pathlib import Path

from src.direct_batch import (prepare_problem, choose_direct, prepare_frontier,
                             choose_frontier, DirectSearchLimit)
from src.envelope import frontier_synthesize

ROOT = Path(__file__).resolve().parents[1]
OWNERS = (2, 3, 4, 6)
ALTERNATIVES = (2, 3, 4, 6)
QUERY_SEEDS = tuple(range(91000, 91032))
PREFIXES = (1, 4, 16, 32)
REPETITIONS = 3
PROPOSALS = 96
ROUTE_SECONDS = 30
ROUTE_NS = ROUTE_SECONDS * 1_000_000_000
WORKER_SECONDS = 90
RESOURCE_REFUSALS = {'exact frontier local-library bound',
    'exact frontier search-state bound', 'exact frontier result bound',
    'direct batch search-state bound'}
SOURCES = ('src/direct_batch.py', 'src/envelope.py', 'src/checker.py', 'src/batch.py',
           'src/controller.py', 'tests/direct_optimizer_study.py',
           'tests/check_direct_optimizer.py', 'tests/direct_optimizer_regression.py',
           'docs/DIRECT-OPTIMIZER-DESIGN.md')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def identities():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def context(owners, alternatives):
    nodes = [str(i) for i in range(owners)]
    profiles = {}
    for i, node in enumerate(nodes):
        masks = [(1 << alternatives) - 1] + [1 << j for j in range(alternatives)]
        pairs = [sum(1 << j for j in pair) for pair in combinations(range(alternatives), 2)]
        if pairs:
            offset = i % len(pairs)
            pairs = pairs[offset:] + pairs[:offset]
        for value in pairs:
            if value not in masks and len(set(masks)) < 8:
                masks.append(value)
        profiles[node] = sorted(set(masks))
    support = lambda node, mask: [f'owner{node}.cap{j}' for j in range(alternatives)
                                  if mask & (1 << j)]
    branches = [{n: [f'owner{n}.cap{j}'] for n in nodes} for j in range(alternatives)]
    current = {n: support(n, (1 << alternatives)-1) for n in nodes}
    candidates = {n: [support(n, mask) for mask in profiles[n]] for n in nodes}
    return {'owners': owners, 'alternatives': alternatives, 'branches': branches,
            'current': current, 'candidates': candidates,
            'relevant_atoms': owners*alternatives,
            'candidate_profiles': {n: len(candidates[n]) for n in nodes}}


def queries(inputs):
    nodes = sorted(inputs['current'])
    batches = []
    for seed in QUERY_SEEDS:
        rng = random.Random(seed)
        proposals = []
        for _ in range(PROPOSALS):
            node = rng.choice(nodes)
            support = rng.choice(inputs['candidates'][node])
            proposals.append({'node': node, 'support': list(support)})
        batches.append({'seed': seed, 'proposals': proposals})
    return batches


class RouteWallBudget(Exception):
    pass


def measured(function, *args, remaining_ns=ROUTE_NS):
    """Budget one route independently; never return a timed-out partial result."""
    if remaining_ns <= 0:
        return None, {'status': 'unavailable', 'reason': 'route-wall-budget-exhausted',
                      'budget_available_ns': 0}
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    def expired(signum, frame):
        raise RouteWallBudget()
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining_ns / 1_000_000_000)
    result = None
    record = {'status': 'completed', 'budget_available_ns': remaining_ns}
    try:
        result = function(*args)
    except RouteWallBudget:
        result = None
        record.update(status='wall-budget', reason='cumulative route wall budget exhausted')
    except ValueError as error:
        if str(error) not in RESOURCE_REFUSALS:
            raise
        record.update(status='resource-refused', reason=str(error))
        if isinstance(error, DirectSearchLimit):
            record['search'] = error.search
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    record['timing'] = {'wall_ns': time.perf_counter_ns()-wall,
                        'cpu_ns': time.process_time_ns()-cpu}
    return result, record


def worker(out, owners, alternatives, repetition):
    inputs = context(owners, alternatives)
    record = {'status': 'running', 'owners': owners, 'alternatives': alternatives,
              'repetition': repetition, 'inputs': inputs, 'queries': [],
              'route_budget_ns': ROUTE_NS}
    write(out, record)
    problem, record['language_preparation'] = measured(prepare_problem,
        inputs['branches'], inputs['current'], inputs['candidates'])
    if problem is None:
        record['status'] = 'language-preparation-incomplete'
        write(out, record)
        return
    spent = {method: record['language_preparation']['timing']['wall_ns']
             for method in ('direct', 'frontier')}
    closed = {'direct': False, 'frontier': False}
    record['local_guards'] = {n: len(problem.local[i]) for i, n in enumerate(problem.nodes)}
    write(out, record)
    plan, record['frontier_construction'] = measured(frontier_synthesize,
        inputs['branches'], inputs['current'], inputs['candidates'],
        remaining_ns=max(0, ROUTE_NS-spent['frontier']))
    spent['frontier'] += record['frontier_construction'].get('timing', {}).get('wall_ns', 0)
    compiled = None
    if plan is not None:
        record['frontier_plan'] = plan
        write(out, record)
        compiled, record['frontier_check_and_compile'] = measured(prepare_frontier, problem, plan,
            remaining_ns=max(0, ROUTE_NS-spent['frontier']))
        spent['frontier'] += record['frontier_check_and_compile'].get('timing', {}).get('wall_ns', 0)
    write(out, record)
    for q, item in enumerate(queries(inputs)):
        result = dict(item)
        order = ('direct', 'frontier') if (q+repetition) % 2 == 0 else ('frontier', 'direct')
        result['execution_order'] = list(order)
        for method in order:
            if method == 'frontier' and compiled is None:
                result[method] = {'status': 'unavailable', 'reason': 'frontier-preparation-incomplete'}
                continue
            if closed[method]:
                result[method] = {'status': 'unavailable', 'reason': 'route-wall-budget-exhausted',
                                  'budget_available_ns': 0}
                continue
            answer, timing = (measured(choose_direct, problem, item['proposals'],
                                      remaining_ns=max(0, ROUTE_NS-spent[method]))
                              if method == 'direct' else
                              measured(choose_frontier, problem, compiled, item['proposals'],
                                       remaining_ns=max(0, ROUTE_NS-spent[method])))
            spent[method] += timing.get('timing', {}).get('wall_ns', 0)
            if timing['status'] in ('wall-budget', 'unavailable'):
                closed[method] = True
            result[method] = timing
            if answer is not None:
                result[method]['result'] = answer
        if all(result[m]['status'] == 'completed' for m in ('direct', 'frontier')):
            require(result['direct']['result']['forecast']['installed'] ==
                    result['frontier']['result']['forecast']['installed'], 'Exact optima differ')
        record['queries'].append(result)
        write(out, record)
    record['status'] = 'completed'
    record['route_wall_used_ns'] = spent
    write(out, record)


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


def aggregate(records):
    rows = []
    for owners in OWNERS:
        for alternatives in ALTERNATIVES:
            group = [r for r in records if r['owners'] == owners and r['alternatives'] == alternatives]
            for prefix in PREFIXES:
                row = {'owners': owners, 'alternatives': alternatives,
                       'relevant_atoms': owners*alternatives, 'queries': prefix,
                       'repetitions': len(group)}
                for method in ('direct', 'frontier'):
                    for clock in ('wall_ns', 'cpu_ns'):
                        values = [cumulative(r, prefix, method, clock) for r in group]
                        row[method+'_'+clock+'_median'] = (statistics.median(values)
                            if len(values) == REPETITIONS and all(v is not None for v in values) else None)
                if all(row[m+'_cpu_ns_median'] is not None for m in ('direct', 'frontier')):
                    row['cpu_faster'] = ('frontier' if row['frontier_cpu_ns_median'] <
                                         row['direct_cpu_ns_median'] else 'direct')
                else:
                    row['cpu_faster'] = 'not-comparable'
                rows.append(row)
    return rows


def run(out):
    out = out.resolve()
    require(not out.exists() and not out.is_relative_to(ROOT), 'New output outside artifact required')
    out.mkdir(parents=True)
    before = identities()
    for name in SOURCES:
        path = out/'source-preimage'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, path)
    affinity = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    pinned = affinity[-1] if affinity else None
    if pinned is not None:
        os.sched_setaffinity(0, {pinned})
    environment = {'platform': platform.platform(), 'python': sys.version,
                   'available_logical_cpus': affinity, 'pinned_logical_cpu': pinned,
                   'clock': 'perf_counter_ns and process_time_ns',
                   'scope': 'local descriptive three-repeat planning times; same frozen context across counterfactual queries'}
    environment['budget'] = {'route_seconds': ROUTE_SECONDS, 'worker_safety_seconds': WORKER_SECONDS,
        'accounting': 'independent cumulative timed-call wall budget per route; common language preparation charged to both; file I/O outside timed calls'}
    if Path('/proc/cpuinfo').exists():
        environment['cpu_model'] = next((line.split(':', 1)[1].strip()
            for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), None)
    write(out/'environment.json', environment)
    records = []
    for owners in OWNERS:
        for alternatives in ALTERNATIVES:
            for repetition in range(REPETITIONS):
                stem = f'owners-{owners}-alternatives-{alternatives}-repeat-{repetition}'
                destination = out/(stem+'.json')
                command = [sys.executable, '-B', '-m', 'tests.direct_optimizer_study', '--worker',
                           '--out', str(destination), '--owners', str(owners),
                           '--alternatives', str(alternatives), '--repetition', str(repetition)]
                start = time.monotonic()
                try:
                    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                               timeout=WORKER_SECONDS)
                    (out/(stem+'.stdout.log')).write_text(completed.stdout)
                    (out/(stem+'.stderr.log')).write_text(completed.stderr)
                    require(completed.returncode == 0, 'Worker failed: '+stem+' '+completed.stderr)
                    record = json.loads(destination.read_text())
                except subprocess.TimeoutExpired as error:
                    record = json.loads(destination.read_text())
                    record['status'] = 'wall-time-limit'
                    record['wall_limit_seconds'] = WORKER_SECONDS
                    write(destination, record)
                    (out/(stem+'.stdout.log')).write_text((error.stdout or b'').decode() if isinstance(error.stdout, bytes) else error.stdout or '')
                    (out/(stem+'.stderr.log')).write_text((error.stderr or b'').decode() if isinstance(error.stderr, bytes) else error.stderr or '')
                record['record_file'] = destination.name
                records.append(record)
                print(json.dumps({'context': stem, 'status': record['status'],
                                  'seconds': round(time.monotonic()-start, 3)}), flush=True)
    rows = aggregate(records)
    with (out/'cumulative.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {'status': 'PASS', 'contexts': len(OWNERS)*len(ALTERNATIVES),
        'repetitions_per_context': REPETITIONS, 'queries_per_repetition': len(QUERY_SEEDS),
        'distinct_batches_per_context': len(QUERY_SEEDS), 'proposals_per_batch': PROPOSALS,
        'worker_records': len(records), 'completed_workers': sum(r['status']=='completed' for r in records),
        'route_budget_seconds': ROUTE_SECONDS,
        'wall_time_limited_workers': sum(r['status']=='wall-time-limit' for r in records),
        'frontier_construction_refusals': sum(r.get('frontier_construction',{}).get('status')=='resource-refused' for r in records),
        'frontier_preparation_wall_budgets': sum(any(r.get(f,{}).get('status') in ('wall-budget','unavailable')
            for f in ('frontier_construction','frontier_check_and_compile')) for r in records),
        'direct_completed_queries': sum(q['direct']['status']=='completed' for r in records for q in r['queries']),
        'frontier_completed_queries': sum(q['frontier']['status']=='completed' for r in records for q in r['queries']),
        'direct_query_refusals': sum(q['direct']['status']=='resource-refused' for r in records for q in r['queries']),
        'direct_query_wall_budgets': sum(q['direct']['status']=='wall-budget' for r in records for q in r['queries']),
        'frontier_query_wall_budgets': sum(q['frontier']['status']=='wall-budget' for r in records for q in r['queries']),
        'comparable_optima': sum(all(q[m]['status']=='completed' for m in ('direct','frontier')) for r in records for q in r['queries']),
        'source_sha256': before, 'source_unchanged': before == identities(),
        'cumulative_rows': rows,
        'interpretation': 'Each direct query optimizes only that batch and may reuse its local language. Frontier queries additionally reuse independently checked complete alternatives. Counterfactual queries reset to the same initial placement; installation count is not rollout goal completion.'}
    require(summary['source_unchanged'], 'Study source changed during execution')
    write(out/'summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('source_sha256','cumulative_rows')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--owners', type=int)
    parser.add_argument('--alternatives', type=int)
    parser.add_argument('--repetition', type=int, default=0)
    args = parser.parse_args()
    if args.worker:
        worker(args.out, args.owners, args.alternatives, args.repetition)
    else:
        run(args.out)
