"""Reconstruct paired phase-granularity executions without production imports.

The separate numerical-policy checker supplies literal owner transitions and
SQLite decoding. This checker adds the fixed pairing, unchanged installations,
real-process records, every-action checkpoints and exact RPC accounting.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile

from tests.check_goal_policy import (
    IntegerOracle, apply_rpc, canonical, check_job_snapshot, database, digest,
    equal, expected_domain, guard_check, owner_initial, profile, read,
    read_rows, require, safe, specifications, tasks, verify_plan, version_vector,
)

ROOT = Path(__file__).resolve().parents[1]


def expected_designs(fixture, domains):
    result = [{**deepcopy(c), 'domain': domains[0]['name']}
              for c in fixture['execution_cases'] if c['fault'] == 'none']
    for domain in domains[1:]:
        for name, initial, target in tasks(domain):
            result.append({'name': domain['name'] + '--' + name,
                           'domain': domain['name'], 'initial': initial,
                           'target': target, 'fault': 'none',
                           'amendment': fixture['execution_amendment']['id']})
    return result


def check_split(domain, original, split):
    """Check feasibility and one-write granularity against the retained path."""
    fields = ('schema', 'status', 'branches', 'initial', 'target', 'catalog', 'transitions')
    for field in fields:
        equal(split[field], original[field], 'Paired plan changed ' + field)
    reference = [(step, phase['box']) for phase in original['phases'] for step in phase['steps']]
    require(reference, 'Phase-granularity cohort includes an empty plan')
    equal(len(split['phases']), len(reference), 'Split phase inventory differs')
    equal(split['cost'], {'phases': len(reference), 'installations': len(reference),
                         'handoffs': len(reference) - 1}, 'One-write phase cost differs')
    current = deepcopy(original['initial'])
    for phase, (step, box) in zip(split['phases'], reference):
        equal(phase['source'], current, 'Split phase source breaks continuity')
        equal(phase['steps'], [step], 'Split phase changes the ordered installations')
        equal(phase['box'], box, 'Split phase changes its enclosing guard')
        guard_check(domain, box, current)
        before = version_vector(domain, current)
        after = deepcopy(current)
        after[step['node']] = step['support']
        vector = version_vector(domain, after)
        require(all(vector[i] == before[i] + (i == int(step['node']))
                    for i in range(len(vector))), 'Split installation changes the allowed edge')
        require(safe(vector, domain['specification']['server_owners']),
                'Split installation violates the numerical policy')
        require(any(set(term) <= set(step['support']) for term in box[step['node']]),
                'Split installation leaves its guard')
        local = {n: [list(s)] for n, s in current.items()}
        local[step['node']].append(list(step['support']))
        equal(phase['local_paths'], local, 'Split local path differs')
        equal(phase['target'], after, 'Split phase target differs')
        current = after
    equal(current, original['target'], 'Split plan fails to reach the paired target')


def check_processes(run, owners):
    nodes = [str(i) for i in range(owners)]
    equal(sorted(run['worker_processes'], key=int), nodes, 'Worker-process inventory differs')
    pids, ports = [], []
    for node in nodes:
        worker = run['worker_processes'][node]
        require(type(worker['pid']) is int and worker['pid'] > 0,
                'Invalid owner process identity')
        require(type(worker['port']) is int and 0 < worker['port'] < 65536,
                'Invalid owner TCP port')
        require(worker['pid'] != run['coordinator_pid'], 'Owner and coordinator share a process')
        args = worker['args']
        require(isinstance(args, list) and len(args) == 8 and args[1:4] ==
                ['-m', 'tests.process_tcp_endpoint', node], 'Owner process command differs')
        equal(Path(args[4]).name, f'process-node-{node}.sqlite', 'Owner database path differs')
        equal(json.loads(args[5]), run['plan']['initial'][node], 'Worker initial support differs')
        equal(args[6:], ['8', 'predicate'], 'Owner process parameters differ')
        pids.append(worker['pid'])
        ports.append(worker['port'])
    require(len(set(pids)) == owners and len(set(ports)) == owners,
            'Paired execution reused an owner process or TCP endpoint')
    equal(run['process_events'], [{'event': 'process-start', 'node': i} for i in range(owners)],
          'Owner readiness/start inventory differs')


def check_run(directory, domain, run, design, plan):
    equal(run['name'], design['name'], 'Execution name differs')
    equal(run['design'], design, 'Execution design differs')
    equal(run['plan'], plan, 'Execution plan differs from the paired input')
    equal([run['status'], run['reopened_after_pending']], ['complete', False],
          'Fault-free paired execution has a pending or recovery outcome')
    n = len(plan['initial'])
    check_processes(run, n)
    trace = run['logical_rpc_trace']
    require(all(e['event'] == 'rpc' for e in trace), 'Fault-free run contains an unsuccessful transport')
    equal([e['tick'] for e in trace], list(range(1, len(trace) + 1)), 'Owner RPC ordering differs')
    actions, snapshots = run['action_results'], run['snapshots']
    require(actions and snapshots, 'Missing completed action/checkpoint evidence')
    equal(len(snapshots), len(actions) + 1, 'An action lacks its state checkpoint')
    equal([s['label'] for s in snapshots], ['initial'] + [a.get('event', a['status']) for a in actions],
          'Action/checkpoint labels differ')
    require(all(a['status'] == 'progress' for a in actions[:-1]), 'Unexpected fault-free action status')
    equal(snapshots[0]['trace_length'], 0, 'Initial checkpoint includes RPC work')
    states = owner_initial(domain, design['initial'])
    cursor, checked_steps, databases = 0, 0, 0
    previous = None
    for index, snapshot in enumerate(snapshots):
        end = snapshot['trace_length']
        require(type(end) is int and cursor <= end <= len(trace), 'Checkpoint RPC boundary differs')
        if previous is not None:
            state = previous['job_state']
            pi, si = state['phase_index'], state['step_index']
            if state['stage'] == 'install' and si < len(plan['phases'][pi]['steps']):
                step = plan['phases'][pi]['steps'][si]
                segment = trace[cursor:end]
                equal(len(segment), 2, 'Installation lacks exactly one pre-read and conditional write')
                observation, update = segment
                equal([observation['target'], observation['request']],
                      [int(step['node']), {'op': 'read'}], 'Installation reads an unrelated owner')
                equal(observation['response']['status'], 'observed', 'Installation pre-read failed')
                equal([update['target'], update['request']['op'], update['response']['status']],
                      [int(step['node']), 'install_if_current', 'installed'], 'Conditional installation failed')
                observed = observation['response']['observed']
                equal([update['request']['expected_generation'], update['request']['expected_support'],
                       update['request']['support']],
                      [observed['generation'], observed['support'], step['support']],
                      'Installation does not bind its preceding read and planned support')
                origin = state['origins'][pi % 2]
                equal([e['source'] for e in segment], [origin, origin], 'Installation uses another phase origin')
                checked_steps += 1
        for event in trace[cursor:end]:
            apply_rpc(states, event, domain)
        cursor = end
        equal(snapshot['owner_states'], states, 'Checkpoint owner state differs from RPC replay')
        check_job_snapshot(snapshot, run, states, domain)
        expected_db = {}
        if snapshot['label'] in {'initial', 'phase-admitted', 'complete'}:
            expected_db = {f'process-node-{node}.sqlite': state for node, state in states.items()}
            expected_db.update({f'origin-{node}.sqlite': state for node, state in snapshot['origin_states'].items()})
            expected_db['rollout.sqlite'] = snapshot['job_state']
        equal(sorted(Path(item['path']).name for item in snapshot['databases']), sorted(expected_db),
              'Checkpoint SQLite inventory differs')
        for item in snapshot['databases']:
            path = (directory / item['path']).resolve()
            require(path.is_relative_to(directory) and path.is_file(), 'Database path escape or missing file')
            equal(Path(item['path']).parent.as_posix(), f'databases/{run["name"]}/{index:03d}',
                  'Database assigned to a different action checkpoint')
            equal(digest(path), item['sha256'], 'SQLite checkpoint checksum differs')
            equal(database(path), expected_db[path.name], 'SQLite checkpoint differs from semantic replay')
            databases += 1
        previous = snapshot
    equal(cursor, len(trace), 'Final checkpoint omits RPC work')
    equal(version_vector(domain, {node: state['support'] for node, state in states.items()}), design['target'],
          'Execution did not reach its paired target')
    final = run['final_state']
    equal(final, snapshots[-1]['job_state'], 'Final durable state differs')
    equal([final['stage'], final['acknowledged_installs'], final['reconciled_steps']],
          ['complete', plan['cost']['installations'], 0], 'Fault-free installation counters differ')
    result = actions[-1]
    equal([result['status'], result.get('goal_reached')], ['complete', True], 'Final goal observation missing')
    observation = result.get('target_observation')
    require(isinstance(observation, dict) and set(observation) == {'first', 'second'}, 'Missing two target collects')
    equal(observation['first'], observation['second'], 'Target observation accepts changing owner state')
    equal(observation['first'], {node: profile(state) for node, state in states.items()},
          'Target observation differs from replayed owner state')
    tail = trace[-2 * n:]
    equal(len(tail), 2 * n, 'Missing final authoritative reads')
    for i, event in enumerate(tail):
        node = str(i % n)
        equal([event['target'], event['request'], event['response']],
              [int(node), {'op': 'read'}, {'status': 'observed', 'observed': observation['first'][node]}],
              'Completion is not backed by two full identical collects')
    phases, writes = plan['cost']['phases'], plan['cost']['installations']
    admitted = sum(a.get('event') == 'phase-admitted' for a in actions)
    equal([admitted, checked_steps], [phases, writes], 'Phase admissions or installation segments differ')
    operations = Counter(e['request']['op'] for e in trace)
    prediction = {'read': writes + n * (2 * phases + 4), 'prepare': n * phases,
                  'close': n * phases, 'install_if_current': writes}
    equal(dict(operations), prediction, 'Actual RPC decomposition differs from the executor count')
    equal(len(trace), 2 * writes + 4 * n * phases + 4 * n, 'Actual total RPC formula differs')
    return {'name': run['name'], 'paired_case': design['paired_case'], 'route': design['route'],
            'domain': domain['name'], 'owners': n, 'phases': phases, 'installations': writes,
            'rpc_counts': dict(sorted(operations.items())), 'total_rpcs': len(trace),
            'checkpoints': len(snapshots), 'database_snapshots': databases,
            'verified_step_segments': checked_steps}


def check(directory, verify_summary=True):
    directory = Path(directory).resolve()
    manifest = read(directory / 'manifest.json')
    equal(manifest['schema'], 'phase-granularity-v1', 'Unknown phase-granularity evidence schema')
    listed = [item['path'] for item in manifest['files']]
    actual = [str(path.relative_to(directory)) for path in sorted(directory.rglob('*'))
              if path.is_file() and path.name != 'manifest.json']
    equal(listed, actual, 'Phase-granularity manifest coverage differs')
    for item in manifest['files']:
        path = (directory / item['path']).resolve()
        require(path.is_relative_to(directory) and path.is_file(), 'Evidence path escape or missing file')
        equal(digest(path), item['sha256'], 'Evidence checksum differs: ' + item['path'])
    required_sources = {'docs/PHASE-GRANULARITY-DESIGN.md', 'data/goal-policy.json',
                        'tests/phase_granularity_study.py', 'tests/check_phase_granularity.py',
                        'tests/multiprocess.py', 'tests/process_tcp_endpoint.py',
                        'tests/goal_policy_study.py', 'tests/check_goal_policy.py',
                        'results/goal-policy/plans.jsonl.gz', 'results/goal-policy/domains.json'}
    required_sources.update('src/' + name for name in ('__init__.py', 'controller.py', 'checker.py',
                            'envelope.py', 'network.py', 'goal_planner.py', 'rollout.py'))
    equal(sorted(manifest['source_sha256']), sorted(required_sources), 'Bound source inventory differs')
    for name, sha in manifest['source_sha256'].items():
        path = directory / 'source-preimage' / name
        require(path.is_file(), 'Missing executed source preimage: ' + name)
        equal(digest(path), sha, 'Executed source preimage differs: ' + name)
    fixture, domains = read(directory / 'fixture.json'), read(directory / 'domains.json')
    equal(fixture, read(directory / 'source-preimage/data/goal-policy.json'), 'Fixture differs from its preimage')
    equal(domains, [expected_domain(spec) for spec in specifications(fixture)], 'Numerical domains differ')
    equal(domains, read(directory / 'source-preimage/results/goal-policy/domains.json'), 'Domain source differs')
    designs = expected_designs(fixture, domains)
    equal(len(designs), 19, 'Paired fault-free case inventory changed')
    inputs = read(directory / 'inputs.json')
    equal([item['design'] for item in inputs], designs, 'Retained input design inventory differs')
    frozen_rows = read_rows(directory / 'source-preimage/results/goal-policy/plans.jsonl.gz')
    by_name = {d['name']: d for d in domains}
    oracles = {name: IntegerOracle(d) for name, d in by_name.items()}
    for item, design in zip(inputs, designs):
        matching = [r for r in frozen_rows if r['domain'] == design['domain'] and
                    r['initial_versions'] == design['initial'] and r['target_versions'] == design['target']]
        equal(len(matching), 1, 'Paired input is absent or duplicated in the retained plan study')
        equal(item['planning_row'], matching[0], 'Paired input plan changed from its retained source')
        domain = by_name[design['domain']]
        verify_plan(domain, item['planning_row'], oracles[domain['name']])
    index = read(directory / 'executions.json')
    expected_names = [design['name'] + '--' + route for design in designs for route in ('frontier', 'one-step')]
    equal(index, [{'name': name, 'path': 'executions/' + name + '.json'} for name in expected_names],
          'Paired execution inventory differs')
    cases, pairs = [], []
    for item in inputs:
        original, design = item['planning_row']['plan'], item['design']
        domain = by_name[design['domain']]
        routes = []
        for route in ('frontier', 'one-step'):
            paired = {**deepcopy(design), 'name': design['name'] + '--' + route,
                      'paired_case': design['name'], 'route': route}
            run = read(directory / 'executions' / (paired['name'] + '.json'))
            if route == 'frontier':
                plan = original
            else:
                plan = run['plan']
                check_split(domain, original, plan)
            row = check_run(directory, domain, run, paired, plan)
            cases.append(row)
            routes.append(row)
        frontier, one_step = routes
        equal(frontier['installations'], one_step['installations'], 'Paired actual write counts differ')
        saving = one_step['total_rpcs'] - frontier['total_rpcs']
        equal(saving, 4 * frontier['owners'] * (frontier['installations'] - frontier['phases']),
              'Paired RPC difference is not explained by phase granularity')
        pairs.append({'name': design['name'], 'owners': frontier['owners'],
                      'installations_per_execution': frontier['installations'],
                      'frontier_phases': frontier['phases'], 'one_step_phases': one_step['phases'],
                      'frontier_rpcs': frontier['total_rpcs'], 'one_step_rpcs': one_step['total_rpcs'],
                      'rpc_reduction': saving})
    grouped = []
    for n in sorted({row['owners'] for row in pairs}):
        rows = [row for row in pairs if row['owners'] == n]
        grouped.append({'owners': n, 'pairs': len(rows),
            'installations_per_route': sum(row['installations_per_execution'] for row in rows), **{
            field: sum(row[field] for row in rows) for field in
            ('frontier_phases', 'one_step_phases', 'frontier_rpcs', 'one_step_rpcs', 'rpc_reduction')}})
    routes = {}
    for route in ('frontier', 'one-step'):
        rows = [row for row in cases if row['route'] == route]
        routes[route] = {'executions': len(rows), **{field: sum(row[field] for row in rows) for field in
                        ('phases', 'installations', 'total_rpcs', 'checkpoints',
                         'database_snapshots', 'verified_step_segments')},
                        'rpc_counts': {op: sum(row['rpc_counts'][op] for row in rows) for op in
                                       ('read', 'prepare', 'close', 'install_if_current')}}
    env = read(directory / 'environment.json')
    equal([env['separate_owner_processes'], env['transport'], env['source_unchanged']],
          [True, 'loopback TCP', True], 'Execution environment description differs')
    result = {'status': 'PASS', 'pairs': len(pairs), 'executions': len(cases),
              'routes': routes, 'by_owner_count': grouped, 'paired_cases': pairs, 'cases': cases,
              'total_rpc_reduction': sum(row['rpc_reduction'] for row in pairs),
              'scope': 'The same ordered installations under one durable executor, with one OS process per owner. '
                       'These are phase-granularity RPC counts; raw elapsed fields are not used as a latency comparison.'}
    if verify_summary:
        equal(read(directory / 'summary.json'), result, 'Saved phase-granularity summary differs')
    return result


def corruption_controls(directory):
    directory = Path(directory).resolve()
    check(directory)
    results = []
    with tempfile.TemporaryDirectory(prefix='phase-granularity-controls-') as temporary:
        target = Path(temporary) / 'evidence'
        for kind in ('omitted_execution', 'changed_paired_step', 'unbacked_target_observation'):
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(directory, target)
            index = read(target / 'executions.json')
            if kind == 'omitted_execution':
                (target / 'executions.json').write_text(canonical(index[:-1]) + '\n')
            else:
                name = index[1 if kind == 'changed_paired_step' else 0]['path']
                run = read(target / name)
                if kind == 'changed_paired_step':
                    step = run['plan']['phases'][0]['steps'][0]
                    step['support'] = run['plan']['initial'][step['node']]
                else:
                    for collect in run['action_results'][-1]['target_observation'].values():
                        collect['0']['generation'] += 1
                (target / name).write_text(canonical(run) + '\n')
            manifest = read(target / 'manifest.json')
            for item in manifest['files']:
                item['sha256'] = digest(target / item['path'])
            (target / 'manifest.json').write_text(canonical(manifest) + '\n')
            try:
                check(target)
            except ValueError as exc:
                results.append({'case': kind, 'rejected': True, 'reason': str(exc)})
            else:
                raise ValueError('Semantic corruption accepted: ' + kind)
    return {'status': 'PASS', 'controls': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    result = corruption_controls(args.results) if args.corruption_controls else check(args.results)
    print(json.dumps(result, sort_keys=True))
