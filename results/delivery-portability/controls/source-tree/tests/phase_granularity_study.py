"""Paired phase granularity executions with separate owner processes."""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import tempfile

from src.rollout import RolloutCoordinator, validate_execution_plan
from tests.multiprocess import ProcessNetwork
from tests.goal_policy_study import execution_inputs

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    names = ['docs/PHASE-GRANULARITY-DESIGN.md', 'data/goal-policy.json',
             'tests/phase_granularity_study.py', 'tests/check_phase_granularity.py',
             'tests/multiprocess.py', 'tests/process_tcp_endpoint.py',
             'tests/goal_policy_study.py', 'tests/check_goal_policy.py',
             'results/goal-policy/plans.jsonl.gz', 'results/goal-policy/domains.json']
    names += ['src/' + p for p in ('__init__.py', 'controller.py', 'checker.py',
              'envelope.py', 'network.py', 'goal_planner.py', 'rollout.py')]
    return {n: digest(ROOT / n) for n in names}


def one_step_phases(plan):
    result = deepcopy(plan)
    result.pop('search', None)
    result['objective'] = ['one installation per phase; preserve the planned installation sequence']
    result['phases'] = []
    state = deepcopy(plan['initial'])
    for phase in plan['phases']:
        for step in phase['steps']:
            following = deepcopy(state)
            following[step['node']] = list(step['support'])
            local = {node: [list(support)] for node, support in state.items()}
            local[step['node']].append(list(step['support']))
            result['phases'].append({'source': deepcopy(state), 'target': following,
                                     'box': deepcopy(phase['box']),
                                     'steps': [deepcopy(step)], 'local_paths': local})
            state = following
    count = len(result['phases'])
    result['cost'] = {'phases': count, 'installations': count, 'handoffs': max(count - 1, 0)}
    return validate_execution_plan(result)


def read_state(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id,payload FROM state ORDER BY id').fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise ValueError('Unexpected persistent state table')
        return json.loads(rows[0][1])


def snapshot(net, job, directory, output, name, index, label):
    result = {'owner_states': {str(n): read_state(directory / f'process-node-{n}.sqlite')
                               for n in sorted(net.processes)},
              'origin_states': {str(n): deepcopy(c.state) for n, c in job.clients.items()},
              'job_state': job.state,
              'trace_length': sum(e['event'] == 'rpc' for e in net.trace),
              'label': label, 'databases': []}
    if label in {'initial', 'phase-admitted', 'complete'}:
        for source in sorted(directory.glob('*.sqlite')):
            target = output / 'databases' / name / f'{index:03d}' / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
                with sqlite3.connect(target) as dst:
                    src.backup(dst)
            result['databases'].append({'path': str(target.relative_to(output)), 'sha256': digest(target)})
    return result


async def execute(design, domain, plan, directory, output):
    directory.mkdir(parents=True)
    net = ProcessNetwork(directory, [plan['initial'][str(i)] for i in range(len(plan['initial']))])
    job = None
    try:
        net.start()
        workers = {str(n): {'pid': p.pid, 'port': net.ports[n], 'args': p.args}
                   for n, p in net.processes.items()}
        job = RolloutCoordinator(net, directory / 'rollout.sqlite',
                                 manifest='goal-policy-' + design['name'], plan=plan)
        checkpoints = [snapshot(net, job, directory, output, design['name'], 0, 'initial')]
        actions = []
        for _ in range(4 * len(plan['phases']) + plan['cost']['installations'] + 2):
            result = await job.advance()
            actions.append(deepcopy(result))
            label = result.get('event', result['status'])
            checkpoints.append(snapshot(net, job, directory, output, design['name'], len(checkpoints), label))
            if result['status'] == 'complete':
                break
            if result['status'] != 'progress':
                raise ValueError('Unexpected paired execution outcome: ' + str(result))
        else:
            raise ValueError('Paired execution exhausted action bound')
        if any(e['event'] not in {'rpc', 'process-start'} for e in net.trace):
            raise ValueError('Unexpected transport fault in fault-free ablation')
        return {'name': design['name'], 'design': design, 'status': 'complete',
                'plan': deepcopy(plan), 'action_results': actions, 'snapshots': checkpoints,
                'logical_rpc_trace': [deepcopy(e) for e in net.trace if e['event'] == 'rpc'],
                'process_events': [deepcopy(e) for e in net.trace if e['event'] != 'rpc'],
                'worker_processes': workers, 'coordinator_pid': os.getpid(),
                'final_state': job.state, 'reopened_after_pending': False}
    finally:
        if job is not None:
            job.disconnect()
        net.stop()


def manifest(output, identities):
    return {'schema': 'phase-granularity-v1', 'source_sha256': identities,
            'files': [{'path': str(p.relative_to(output)), 'sha256': digest(p)}
                      for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'manifest.json']}


async def run(output):
    if output.exists():
        raise ValueError('Use a fresh output directory')
    output.mkdir(parents=True)
    identities = sources()
    fixture = json.loads((ROOT / 'data/goal-policy.json').read_text())
    domains = json.loads((ROOT / 'results/goal-policy/domains.json').read_text())
    with gzip.open(ROOT / 'results/goal-policy/plans.jsonl.gz', 'rt') as stream:
        rows = [json.loads(line) for line in stream]
    designs = [d for d in execution_inputs(fixture, domains) if d['fault'] == 'none']
    if len(designs) != 19:
        raise ValueError('Paired design inventory changed')
    inputs = []
    for design in designs:
        matches = [row for row in rows if row['domain'] == design['domain'] and
                   row['initial_versions'] == design['initial'] and row['target_versions'] == design['target']]
        if len(matches) != 1 or matches[0]['status'] != 'planned':
            raise ValueError('Missing unique complete input plan')
        inputs.append({'design': design, 'planning_row': matches[0]})
    write(output / 'fixture.json', fixture)
    write(output / 'domains.json', domains)
    write(output / 'inputs.json', inputs)
    records = []
    with tempfile.TemporaryDirectory(prefix='rollout-phase-granularity-') as temporary:
        for item in inputs:
            original = item['planning_row']['plan']
            domain = next(d for d in domains if d['name'] == item['design']['domain'])
            for route, plan in [('frontier', original), ('one-step', one_step_phases(original))]:
                design = {**deepcopy(item['design']), 'name': item['design']['name'] + '--' + route,
                          'paired_case': item['design']['name'], 'route': route}
                record = await execute(design, domain, plan, Path(temporary) / design['name'], output)
                path = 'executions/' + design['name'] + '.json'
                write(output / path, record)
                records.append({'name': design['name'], 'path': path})
                print(json.dumps({'case': design['name'], 'status': record['status']}), flush=True)
    if identities != sources():
        raise ValueError('Study sources changed during execution')
    for name in identities:
        target = output / 'source-preimage' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    write(output / 'executions.json', records)
    write(output / 'environment.json', {'python': sys.version, 'platform': platform.platform(),
          'separate_owner_processes': True, 'coordinator_process': 'study driver',
          'transport': 'loopback TCP', 'measurement': 'RPC counts, not latency comparison',
          'source_unchanged': True})
    write(output / 'manifest.json', manifest(output, identities))
    from tests.check_phase_granularity import check
    write(output / 'summary.json', check(output, verify_summary=False))
    write(output / 'manifest.json', manifest(output, identities))
    print(json.dumps(check(output), sort_keys=True), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    asyncio.run(run(parser.parse_args().out.resolve()))
