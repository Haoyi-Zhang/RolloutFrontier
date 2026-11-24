"""Source-bound before/after evidence for owner-local installation reads.

Reuses the exact previous runtime bytes and one already-retained goal plan.
It measures logical RPC counts over real loopback TCP, not runtime latency.
The partition control cuts TCP streams through a proxy while its owner stays
alive. Completed raw traces and both runtime source images are retained.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

from src.network import Network
from src.rollout import RolloutCoordinator
from tests.rollout_recovery import ROOT, local_progress_plan, sources, tcp_partition


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def load_runtime(path):
    name = 'src._retained_global_preread_rollout'
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, 'Cannot load retained runtime')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.RolloutCoordinator


async def execute_goal(coordinator, plan):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        net = Network(root / 'network', [plan['initial'][str(i)] for i in range(len(plan['initial']))])
        await net.start()
        job = coordinator(net, root / 'job.sqlite', manifest='same-goal-locality', plan=plan)
        try:
            result = await job.run()
            require(result['status'] == 'complete', 'Retained goal did not complete')
            trace = deepcopy(net.trace)
            counts = Counter(row['request']['op'] for row in trace if row['event'] == 'rpc')
            require(all(row['event'] == 'rpc' for row in trace), 'Unexpected no-fault delivery failure')
            return {'result': result, 'final_job': job.state,
                    'owner_profiles': {str(n): owner.profile() for n, owner in net.nodes.items()},
                    'rpc_counts': dict(sorted(counts.items())), 'trace': trace}
        finally:
            job.disconnect()
            await net.stop()


async def execute_partition(coordinator, plan):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        net = Network(root / 'network', [plan['initial'][str(i)] for i in range(len(plan['initial']))])
        await net.start()
        job = coordinator(net, root / 'job.sqlite', manifest='same-partition-locality', plan=plan)
        try:
            async with tcp_partition(net, 2) as partition:
                admitted = await job.advance()
                require(admitted['status'] == 'progress' and job.state['stage'] == 'install',
                        'Did not reach a committed phase')
                await partition.cut()
                owner_before = await partition.inspect_owner()
                start = len(net.trace)
                attempts = []
                for _ in range(len(plan['phases'][0]['steps']) + 1):
                    result = await job.advance()
                    attempts.append(deepcopy(result))
                    if result['status'] != 'progress':
                        break
                during = {'attempts': attempts, 'job': job.state,
                          'trace': deepcopy(net.trace[start:]),
                          'owner_probe_before': owner_before,
                          'owner_probe_during': await partition.inspect_owner(),
                          'owner_profiles': {str(n): owner.profile() for n, owner in net.nodes.items()}}
                partition.heal()
                healed = await job.run()
                require(healed['status'] == 'complete', 'Healed job did not complete')
                return {'during_partition': during, 'healed_result': healed,
                        'complete_trace': deepcopy(net.trace)}
        finally:
            job.disconnect()
            await net.stop()


async def run(before_runtime, goal_plan, partition_plan):
    old = load_runtime(before_runtime)
    return {'before': {'goal': await execute_goal(old, goal_plan),
                       'partition': await execute_partition(old, partition_plan)},
            'after': {'goal': await execute_goal(RolloutCoordinator, goal_plan),
                      'partition': await execute_partition(RolloutCoordinator, partition_plan)}}


def check(data, plan):
    n = len(plan['initial'])
    p, w = plan['cost']['phases'], plan['cost']['installations']
    require(p > 0, 'Comparison needs a nonempty goal plan')
    before = data['before']['goal']['rpc_counts']
    after = data['after']['goal']['rpc_counts']
    expected_before, expected_after = n * (w + 2 * p + 4), w + n * (2 * p + 4)
    require(before.get('read') == expected_before and after.get('read') == expected_after,
            'Measured read counts differ from the registered no-fault lifecycle')
    require({k: v for k, v in before.items() if k != 'read'} ==
            {k: v for k, v in after.items() if k != 'read'}, 'Non-read RPC counts changed')
    require(before.get('install_if_current') == w, 'Physical write count differs from the plan')
    old = data['before']['partition']['during_partition']
    new = data['after']['partition']['during_partition']
    require(old['attempts'][0]['status'] == 'pending' and old['job']['step_index'] == 0,
            'The retained global collect did not expose its communication dependency')
    require(new['job']['step_index'] == 2 and
            [r.get('event') for r in new['attempts'][:2]] == ['installed', 'installed'] and
            new['attempts'][-1].get('reason') == 'owner-unreachable',
            'Local steps or the retained phase boundary differ')
    for result in (old, new):
        require(result['owner_probe_before'] == result['owner_probe_during'] and
                '0:1' in result['owner_probe_during']['slots'], 'Partitioned owner lost its hold')
        require(any(r['event'] == 'unreachable' and r['target'] == 2 for r in result['trace']),
                'No real TCP failure was observed')
    return {'owners': n, 'phases': p, 'installations': w,
            'measured_read_rpcs_before': before['read'], 'measured_read_rpcs_after': after['read'],
            'measured_read_rpcs_saved': before['read'] - after['read'],
            'predicted_read_rpcs_before': expected_before, 'predicted_read_rpcs_after': expected_after,
            'unrelated_partition_completed_steps_before': old['job']['step_index'],
            'unrelated_partition_completed_steps_after': new['job']['step_index'],
            'non_read_rpc_counts_equal': True, 'both_healed_runs_completed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--before-runtime', type=Path, default=ROOT /
        'results/development/goal-recovery-global-preread/review-preimage/src/rollout.py')
    parser.add_argument('--goal-records', type=Path, default=ROOT /
        'results/goal-policy-development/global-preread/executions.json')
    args = parser.parse_args()
    output = args.out.resolve()
    require(not output.exists() and not output.is_relative_to(ROOT), 'Use a new output directory outside artifact')
    before_runtime = args.before_runtime.resolve()
    require(before_runtime.is_relative_to(ROOT), 'Retained runtime must be inside artifact')
    goal_records = args.goal_records.resolve()
    require(goal_records.is_relative_to(ROOT), 'Retained goal records must be inside artifact')
    old_name = str(before_runtime.relative_to(ROOT))
    bindings = sources()
    bindings['tests/rollout_locality_study.py'] = digest(Path(__file__))
    bindings[old_name] = digest(before_runtime)
    records_digest = digest(goal_records)
    records = json.loads(goal_records.read_text())
    selected = [r for r in records if r['name'] == 'normal-two-minor']
    require(len(selected) == 1, 'Expected one retained normal-two-minor goal')
    goal_plan = selected[0]['plan']
    partition_plan = local_progress_plan()
    output.mkdir(parents=True)
    inputs = {'goal': goal_plan, 'partition': partition_plan,
              'goal_origin': {'path': str(goal_records.relative_to(ROOT)),
                              'sha256': records_digest, 'record': selected[0]['name']}}
    write_json(output / 'inputs.json', inputs)
    data = asyncio.run(run(before_runtime, goal_plan, partition_plan))
    write_json(output / 'observations.json', data)
    summary = check(data, goal_plan)
    for name, value in bindings.items():
        path = ROOT / name
        require(digest(path) == value, 'Source changed during comparison: ' + name)
        retained = output / 'source-preimage' / name
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_bytes(path.read_bytes())
    require(digest(goal_records) == records_digest, 'Retained goal records changed during comparison')
    result = {'schema': 'rollout-locality-comparison-v1', 'status': 'PASS',
              'source_sha256': bindings, 'inputs_sha256': digest(output / 'inputs.json'),
              'observations_sha256': digest(output / 'observations.json'), **summary,
              'scope': 'One identical retained goal and one controlled TCP partition; logical RPC counts, not latency or fleet measurements.'}
    write_json(output / 'summary.json', result)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
