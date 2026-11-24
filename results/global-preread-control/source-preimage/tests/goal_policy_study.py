"""Registered target-reaching policy tasks and durable automatic phase execution.

Run from artifact/: python -B -m tests.goal_policy_study --out /new/path
The frozen design is docs/GOAL-POLICY-DESIGN.md. Numerical policy declarations
and +1-minor transitions are exercised, not Kubernetes binaries or kubeadm.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
from copy import deepcopy
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import tempfile
import time

from src.goal_planner import GoalPlanner, GoalPlanningRefusal
from src.network import Network
from src.rollout import RolloutCoordinator

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'data/goal-policy.json'
DESIGN = ROOT / 'docs/GOAL-POLICY-DESIGN.md'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_paths():
    return [FIXTURE, DESIGN, Path(__file__), ROOT / 'tests/check_goal_policy.py',
            *[ROOT / 'src' / name for name in ('__init__.py', 'controller.py', 'envelope.py',
              'checker.py', 'network.py', 'goal_planner.py', 'rollout.py')]]


def source_hashes():
    return {str(path.relative_to(ROOT)): digest(path) for path in source_paths()}


def numeric_safe(vector, ns):
    low, high = min(vector[:ns]), max(vector[:ns])
    return high - low <= 1 and all(high - 3 <= version <= low for version in vector[ns:])


def input_specs(facts):
    specs = [deepcopy(facts['primary_domain'])]
    config = facts['scaling_domains']
    for clients in config['client_owner_counts']:
        specs.append({'name': f'active-{clients + config["server_owners"]}-owner',
                      'server_owners': config['server_owners'], 'client_owners': clients,
                      'server_versions': config['server_versions'], 'client_versions': config['client_versions'],
                      'tasks': config['tasks']})
    return specs


def make_domain(spec):
    server_versions, client_versions = spec['server_versions'], spec['client_versions']
    ns, nc = spec['server_owners'], spec['client_owners']
    windows = []
    for count in (1, 2):
        for values in itertools.combinations(server_versions, count):
            if values[-1] - values[0] <= 1:
                supported = [v for v in client_versions if values[-1] - 3 <= v <= values[0]]
                if supported:
                    windows.append({'servers': list(values), 'clients': supported,
                                    'tag': f'{values[0]}_{values[-1]}'})
    regions = sorted([region for region in windows if not any(
        region != other and set(region['servers']) <= set(other['servers']) and
        set(region['clients']) <= set(other['clients']) for other in windows)],
        key=lambda r: (r['servers'], r['clients']))
    profiles = {}
    for index in range(ns + nc):
        role, key, versions = ('server', 'servers', server_versions) if index < ns else ('client', 'clients', client_versions)
        profiles[str(index)] = {str(version): sorted([f'version.{role}.{version}'] +
             [f'{role}.interval.{region["tag"]}' for region in regions if version in region[key]])
                               for version in versions}
    branches = [{str(index): [f'{"server" if index < ns else "client"}.interval.{region["tag"]}']
                 for index in range(ns + nc)} for region in regions]
    candidates = {node: sorted(values.values()) for node, values in profiles.items()}
    transitions = {node: sorted([{'source': values[str(version)], 'target': values[str(version + 1)]}
                                 for version in map(int, values) if str(version + 1) in values],
                                key=lambda edge: (edge['source'], edge['target']))
                   for node, values in profiles.items()}
    raw = list(itertools.product(*([server_versions] * ns + [client_versions] * nc)))
    compatible = [list(vector) for vector in raw if numeric_safe(vector, ns)]
    for vector in raw:
        support = {str(i): profiles[str(i)][str(v)] for i, v in enumerate(vector)}
        encoded = any(all(set(required) <= set(support[node]) for node, required in branch.items()) for branch in branches)
        require(encoded == numeric_safe(vector, ns), 'Encoding disagrees with numerical policy')
    return {'name': spec['name'], 'specification': deepcopy(spec), 'regions': regions,
            'profiles': profiles, 'branches': branches, 'candidates': candidates,
            'transitions': transitions, 'compatible_placements': compatible, 'catalog_placements': len(raw)}


def vector_support(domain, vector):
    return {str(i): domain['profiles'][str(i)][str(v)] for i, v in enumerate(vector)}


def task_inputs(domain):
    if domain['name'] == 'boundary-three-owner':
        for i, source in enumerate(domain['compatible_placements']):
            for j, target in enumerate(domain['compatible_placements']):
                yield f'{i:03d}-{j:03d}', source, target
    else:
        spec = domain['specification']
        for item in spec['tasks']:
            yield (item['name'], [item['initial_servers']] * spec['server_owners'] +
                   [item['initial_clients']] * spec['client_owners'],
                   [item['target_servers']] * spec['server_owners'] + [item['target_clients']] * spec['client_owners'])


def comparator_results(domain, initial, target):
    """Construct the literal one-write global route and static-product control."""
    start, end = tuple(initial), tuple(target)
    allowed = {tuple(v) for v in domain['compatible_placements']}
    parents, queue = {start: None}, deque([start])
    while queue and end not in parents:
        current = queue.popleft()
        for node in range(len(current)):
            following = list(current)
            following[node] += 1
            following = tuple(following)
            if following in allowed and following not in parents:
                parents[following] = current
                queue.append(following)
    path = []
    if end in parents:
        cursor = end
        while cursor is not None:
            path.append(list(cursor))
            cursor = parents[cursor]
        path.reverse()
    writes = len(path) - 1 if path else None
    static = all(a <= b for a, b in zip(start, end)) and all(
        numeric_safe(vector, domain['specification']['server_owners'])
        for vector in itertools.product(*(range(a, b + 1) for a, b in zip(start, end))))
    return {'coordinate_every_proposal': {'status': 'reachable' if path else 'unreachable',
             'global_checks': writes, 'installations': writes, 'version_path': path},
            'single_static_product': {'status': 'reachable' if static else 'unreachable',
             'guard_admissions': (int(start != end) if static else None),
             'installations': (writes if static else None)}}


def execution_inputs(facts, domains):
    result = [{**deepcopy(design), 'domain': domains[0]['name']} for design in facts['execution_cases']]
    amendment = facts['execution_amendment']
    require(amendment['id'] == 'all-existing-scaling-goals', 'Unknown runtime-coverage amendment')
    for domain in domains[1:]:
        for task, initial, target in task_inputs(domain):
            result.append({'name': domain['name'] + '--' + task, 'domain': domain['name'],
                           'initial': initial, 'target': target, 'fault': 'none',
                           'amendment': amendment['id']})
    return result


def run_planning(facts, domains, output):
    rows, domain_work = [], []
    for domain in domains:
        planner = GoalPlanner(domain['branches'], domain['candidates'], domain['transitions'], **facts['planner_bounds'])
        for name, initial, target in task_inputs(domain):
            row = {'domain': domain['name'], 'task': name, 'initial_versions': list(initial), 'target_versions': list(target),
                   'comparators': comparator_results(domain, initial, target)}
            try:
                plan = planner.plan(vector_support(domain, initial), vector_support(domain, target))
            except GoalPlanningRefusal as exc:
                row.update(status='refused', reason=str(exc))
            else:
                row.update(status=plan['status'], plan=plan)
            rows.append(row)
        domain_work.append({'domain': domain['name'], 'statistics': planner.statistics(),
                            'tasks': sum(r['domain'] == domain['name'] for r in rows)})
        print(json.dumps({'domain': domain['name'], 'tasks_completed': domain_work[-1]['tasks'],
                          'statistics': planner.statistics()}), flush=True)
    with (output / 'plans.jsonl.gz').open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
            for row in rows:
                stream.write((canonical(row) + '\n').encode())
    write(output / 'planner-work.json', domain_work)
    return rows


def budget_controls(facts, domain):
    initial = vector_support(domain, [35, 35, 35])
    target = vector_support(domain, [37, 37, 37])
    results = []
    for case in facts['budget_controls']:
        arguments = {**facts['planner_bounds'], **{k: v for k, v in case.items() if k != 'kind'}}
        try:
            planner = GoalPlanner(domain['branches'], domain['candidates'], domain['transitions'], **arguments)
            planner.plan(initial, target)
        except GoalPlanningRefusal as exc:
            results.append({'kind': case['kind'], 'arguments': arguments, 'status': 'refused', 'reason': str(exc)})
        else:
            raise ValueError('Insufficient registered goal budget did not refuse')
    return results


def checkpoint(net, job, directory, output, name, index, label):
    states = {'owner_states': {str(n): deepcopy(endpoint.state) for n, endpoint in net.nodes.items()},
              'origin_states': {str(n): deepcopy(client.state) for n, client in job.clients.items()},
              'job_state': job.state, 'trace_length': len(net.trace), 'label': label, 'databases': []}
    files = [f'node-{node}.sqlite' for node in sorted(net.nodes)] + ['origin-0.sqlite', 'origin-1.sqlite', 'rollout.sqlite']
    for filename in files:
        source = directory / filename
        target = output / 'databases' / name / f'{index:03d}' / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(target) as dst:
                src.backup(dst)
        states['databases'].append({'path': str(target.relative_to(output)), 'sha256': digest(target)})
    return states


async def execute_case(design, domain, row, directory, output):
    if row['status'] == 'refused':
        return {'name': design['name'], 'design': deepcopy(design), 'status': 'not-run', 'reason': row['reason']}
    require(row['status'] == 'planned', 'Registered runtime goal is unreachable')
    plan = row['plan']
    directory.mkdir(parents=True, exist_ok=True)
    supports = vector_support(domain, design['initial'])
    net = Network(directory, [supports[str(i)] for i in range(len(supports))])
    await net.start()
    observer_events, actions, snapshots, suppressed = [], [], [], []
    job = RolloutCoordinator(net, directory / 'rollout.sqlite', manifest='goal-policy-' + design['name'],
                             plan=plan, observer=observer_events.append)
    original_rpc = net.rpc
    fault_armed = False
    reopened = False

    def snap(label):
        snapshots.append(checkpoint(net, job, directory, output, design['name'], len(snapshots), label))

    async def suppress_one_close(source, target, request, drop=False):
        response = await original_rpc(source, target, request, drop=drop)
        if not suppressed and request.get('op') == 'close' and source == 0 and target == 1:
            require(response is not None and response['status'] == 'closed', 'Close reply was not delivered before suppression')
            suppressed.append({'trace_index': len(net.trace) - 1, 'source': source, 'target': target,
                               'request': deepcopy(request), 'owner_response': deepcopy(response)})
            return None
        return response

    try:
        snap('initial')
        for _ in range(100):
            state = job.state
            if not fault_armed and design['name'] == 'new-phase-unavailable' and state['phase_index'] == 1 and state['stage'] == 'acquire':
                net.blocked.add((1, 2))
                fault_armed = True
            if not fault_armed and design['name'] == 'close-reply-lost' and state['phase_index'] == 1 and state['stage'] == 'release-old':
                net.rpc = suppress_one_close
                fault_armed = True
            result = await job.advance()
            actions.append(deepcopy(result))
            snap(result.get('event', result['status']) + ':' + result.get('reason', ''))
            if result['status'] == 'pending':
                require(fault_armed and not reopened, 'Unexpected or repeated pending runtime')
                expected = 'phase-not-admitted' if design['name'] == 'new-phase-unavailable' else 'old-phase-release-pending'
                require(result['reason'] == expected, 'Fault did not reach the registered protocol boundary')
                net.blocked.clear()
                net.rpc = original_rpc
                job.disconnect()
                job = RolloutCoordinator(net, directory / 'rollout.sqlite', observer=observer_events.append)
                reopened = True
                snap('reopened-after-pending')
            elif result['status'] == 'complete':
                break
            else:
                require(result['status'] == 'progress', 'Runtime deviated from the registered goal path')
        else:
            raise ValueError('Registered runtime exceeded action bound')
        final = job.state
        require(final['stage'] == 'complete', 'Goal execution did not reach complete')
        return {'name': design['name'], 'design': deepcopy(design), 'status': 'complete',
                'plan': deepcopy(plan), 'action_results': actions, 'observer_events': observer_events,
                'logical_rpc_trace': deepcopy(net.trace), 'snapshots': snapshots, 'final_state': final,
                'reopened_after_pending': reopened, 'suppressed_close_replies': suppressed,
                'scope': 'Automatically planned numerical-policy support transitions over actual loopback TCP and SQLite; not Kubernetes binaries.'}
    finally:
        net.rpc = original_rpc
        job.disconnect()
        await net.stop()


def manifest(output, sources):
    files = [{'path': str(path.relative_to(output)), 'sha256': digest(path)}
             for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'manifest.json']
    return {'schema': 'goal-policy-evidence-v1', 'design': 'kubernetes-goal-phases-v1',
            'source_sha256': sources, 'files': files}


async def run(output, planning_only=False):
    require(not output.exists(), 'Use a fresh goal-study output directory')
    output.mkdir(parents=True)
    before = source_hashes()
    facts = json.loads(FIXTURE.read_text())
    domains = [make_domain(spec) for spec in input_specs(facts)]
    write(output / 'fixture.json', facts)
    write(output / 'domains.json', domains)
    started = time.monotonic()
    rows = run_planning(facts, domains, output)
    write(output / 'budget-controls.json', budget_controls(facts, domains[0]))
    executions = []
    if not planning_only:
        with tempfile.TemporaryDirectory(prefix='goal-policy-runtime-') as temporary:
            for design in execution_inputs(facts, domains):
                domain = next(d for d in domains if d['name'] == design['domain'])
                row = next(r for r in rows if r['domain'] == domain['name'] and
                           r['initial_versions'] == design['initial'] and r['target_versions'] == design['target'])
                executions.append(await execute_case(design, domain, row, Path(temporary) / design['name'], output))
                print(json.dumps({'execution': design['name'], 'status': executions[-1]['status']}), flush=True)
    write(output / 'executions.json', executions)
    after = source_hashes()
    require(before == after, 'Study sources changed during execution; keep this run separate and rerun frozen sources')
    for name in before:
        destination = output / 'source-preimage' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    write(output / 'execution.json', {'status': 'completed', 'python': sys.version, 'platform': platform.platform(),
          'elapsed_seconds': time.monotonic() - started, 'planning_only': planning_only,
          'scope': 'Elapsed time describes this whole semantic campaign and is not a policy timing comparison.',
          'source_unchanged': True, 'argv': sys.argv})
    write(output / 'manifest.json', manifest(output, before))
    from tests.check_goal_policy import check
    summary = check(output, source_checks=True, execution_checks=not planning_only, verify_summary=False)
    write(output / 'summary.json', summary)
    write(output / 'manifest.json', manifest(output, before))
    check(output, execution_checks=not planning_only)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'results/goal-policy')
    parser.add_argument('--planning-only', action='store_true', help='Development run without durable execution; never presented as full study.')
    args = parser.parse_args()
    asyncio.run(run(args.out.resolve(), args.planning_only))


if __name__ == '__main__':
    main()
