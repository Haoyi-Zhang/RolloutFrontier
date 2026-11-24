"""Concurrent traffic through actual ProtoJSON handlers during a durable rollout."""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
import itertools
import gzip
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import tempfile
import time
from google.protobuf import __version__ as protobuf_version
from src.application import (PROGRAMS, PROFILES, PipelineSession, encode, decode,
                             pipeline_branch, profile_name, INPUT_MIN, INPUT_MAX)
from src.controller import canonical
from src.goal_planner import GoalPlanner
from src.network import Client
from src.rollout import RolloutCoordinator
from tests.application_network import ApplicationNetwork

ROOT = Path(__file__).resolve().parents[1]
CONCURRENCIES = (1, 4, 16)
REPETITIONS = 3
REQUESTS = 96
VALUES = (INPUT_MIN, -17, -1, 0, 1, 23, 2147483647, INPUT_MAX)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def plan_inputs():
    branches = [pipeline_branch(pair) for pair in itertools.product(('ACTIVE', 'ENABLED'), repeat=2)]
    candidates = {str(i): list(PROFILES.values()) for i in range(3)}
    transitions = {str(i): [{'source': PROFILES[a], 'target': PROFILES[b]}
                           for a, b in zip(PROGRAMS, list(PROGRAMS)[1:])] for i in range(3)}
    return branches, candidates, transitions


def build_plan():
    branches, candidates, transitions = plan_inputs()
    return GoalPlanner(branches, candidates, transitions).plan(
        {str(i): PROFILES['legacy'] for i in range(3)},
        {str(i): PROFILES['current'] for i in range(3)})


def catalog_goals(output):
    branches, candidates, transitions = plan_inputs()
    planner = GoalPlanner(branches, candidates, transitions)
    names = list(PROGRAMS)
    states = [state for state in itertools.product(range(4), repeat=3)
              if PROGRAMS[names[state[0]]][0] in PROGRAMS[names[state[1]]]
              and PROGRAMS[names[state[1]]][0] in PROGRAMS[names[state[2]]]]
    with gzip.open(output / 'catalog-plans.jsonl.gz', 'wt') as stream:
        for source in states:
            for target in states:
                result = planner.plan({str(i): PROFILES[names[source[i]]] for i in range(3)},
                                      {str(i): PROFILES[names[target[i]]] for i in range(3)})
                stream.write(canonical({'source': source, 'target': target, 'plan': result}) + '\n')


async def session(client, manifest):
    for attempt in range(100):
        profiles = [(await client.net.rpc(client.origin, node, {'op': 'read'}))['observed']
                    for node in range(3)]
        codec = [PROGRAMS[profile_name(profiles[node]['support'])][0] for node in (0, 1)]
        result = await client.acquire(manifest + '-attempt-' + str(attempt), [pipeline_branch(codec)])
        if result['status'] == 'admitted':
            return PipelineSession(client, result['certificate'], codec)
        await asyncio.sleep(0)
    raise RuntimeError('application admission exhausted attempts')


def backup(net, directory):
    directory.mkdir(parents=True, exist_ok=True)
    for path in sorted(net.directory.glob('*.sqlite')):
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(directory / path.name) as destination:
                source.backup(destination)


async def traffic_run(output, name, condition, concurrency, repetition, plan):
    with tempfile.TemporaryDirectory(prefix='application-traffic-') as temporary:
        root = Path(temporary)
        net = ApplicationNetwork(root, [PROFILES['legacy'] for _ in range(3)])
        client = job = None
        try:
            net.start()
            client = Client(net, 2)
            if condition == 'rollout':
                job = RolloutCoordinator(net, root / 'rollout.sqlite', manifest='protojson-alias-rollout', plan=plan)
            gate = asyncio.Event()
            requests, actions = [], []

            async def one(lease, index):
                value = {'key': f'{name}/item-{index}-α', 'amount': VALUES[index % len(VALUES)]}
                start = time.perf_counter_ns()
                result = await lease.request(name + '-request-' + str(index), value)
                end = time.perf_counter_ns()
                expected = {'key': value['key'], 'amount': 3 * value['amount'] + 7}
                if result['record'] != expected:
                    raise ValueError('application output differs from workload oracle')
                requests.append({'request_id': name + '-request-' + str(index), 'index': index,
                    'input': value, 'output': result['record'], 'codec': lease.codec,
                    'owner_replies': result['owner_replies'], 'start_ns': start,
                    'end_ns': end, 'latency_ns': end - start})

            async def traffic():
                for base in range(0, REQUESTS, concurrency):
                    lease = await session(client, name + '-batch-' + str(base // concurrency))
                    tasks = [asyncio.create_task(one(lease, index))
                             for index in range(base, min(base + concurrency, REQUESTS))]
                    gate.set()
                    await asyncio.gather(*tasks)
                    if not await lease.retire():
                        raise RuntimeError('fault-free application release incomplete')

            async def rollout():
                if job is None:
                    return
                await gate.wait()
                for _ in range(2000):
                    start = time.perf_counter_ns()
                    result = await job.advance()
                    actions.append({'result': result, 'start_ns': start, 'end_ns': time.perf_counter_ns()})
                    if result['status'] == 'complete':
                        return
                    if result['status'] not in {'progress', 'pending'}:
                        raise RuntimeError('unexpected rollout execution result: ' + str(result))
                    if result['status'] == 'pending':
                        await asyncio.sleep(.001)
                    else:
                        await asyncio.sleep(0)
                raise RuntimeError('rollout action bound')

            started = time.perf_counter_ns()
            await asyncio.gather(traffic(), rollout())
            ended = time.perf_counter_ns()
            profiles = [(await net.rpc(2, node, {'op': 'read'}))['observed'] for node in range(3)]
            target = 'current' if condition == 'rollout' else 'legacy'
            if any(p['support'] != PROFILES[target] for p in profiles):
                raise ValueError('application final target differs')
            record = {'name': name, 'condition': condition, 'concurrency': concurrency,
                'repetition': repetition, 'initial': [PROFILES['legacy'] for _ in range(3)],
                'request_count': REQUESTS, 'requests': sorted(requests, key=lambda x: x['index']),
                'actions': actions, 'trace': net.trace, 'final_profiles': profiles,
                'start_ns': started, 'end_ns': ended,
                'job_state': None if job is None else job.state}
            backup(net, output / 'databases' / name)
            write(output / 'runs' / (name + '.json'), record)
        finally:
            if job is not None:
                job.disconnect()
            if client is not None:
                client.disconnect()
            net.stop()
    return {'name': name, 'path': 'runs/' + name + '.json'}


async def controls(output):
    records = []
    # Hold retirement waits for the whole application pipeline, not just an
    # encoder response. The old wire name is held at the sink until completion.
    with tempfile.TemporaryDirectory(prefix='application-drain-') as temporary:
        net = ApplicationNetwork(Path(temporary), [PROFILES['accepting'] for _ in range(3)])
        net.start()
        client = Client(net, 2)
        try:
            lease = await session(client, 'drain-control')
            entered, finish = asyncio.Event(), asyncio.Event()
            async def pause():
                entered.set()
                await finish.wait()
            task = asyncio.create_task(lease.request('drained-request', {'key': 'drain', 'amount': 11}, after_encode=pause))
            await entered.wait()
            retiring = asyncio.create_task(lease.retire())
            await asyncio.sleep(0)
            premature = await net.rpc(0, 2, {'op': 'install', 'support': PROFILES['current']})
            closing_rejected = False
            try:
                await lease.request('too-late', {'key': 'late', 'amount': 1})
            except ValueError:
                closing_rejected = True
            if premature.get('status') != 'blocked' or retiring.done() or not closing_rejected:
                raise ValueError('pipeline drain did not retain required authority')
            finish.set()
            result = await task
            released = await retiring
            installed = await net.rpc(0, 2, {'op': 'install', 'support': PROFILES['current']})
            late = await net.rpc(2, 2, {'op': 'application', 'origin': 2,
                'sequence': lease.certificate['sequences']['2'], 'manifest': lease.certificate['manifest'],
                'request_id': 'post-retirement', 'codec': lease.codec,
                'input': '{"key":"late","amount":"10","state":"ACTIVE"}'})
            name = 'drain'
            record = {'name': name, 'initial': [PROFILES['accepting'] for _ in range(3)],
                'trace': net.trace, 'premature_install': premature, 'new_request_rejected': closing_rejected,
                'result': result, 'retired': released, 'after_drain_install': installed, 'late_request': late}
            backup(net, output / 'databases' / name)
            records.append(record)
        finally:
            client.disconnect()
            net.stop()
    # Remove the authority that the application checks; no application effect
    # is allowed even though the current handler can parse the input.
    with tempfile.TemporaryDirectory(prefix='application-guard-') as temporary:
        net = ApplicationNetwork(Path(temporary), [PROFILES['accepting'] for _ in range(3)])
        net.start()
        client = Client(net, 2)
        try:
            lease = await session(client, 'guard-removal')
            removed = await net.rpc(2, 1, {'op': 'close', 'origin': 2,
                'sequence': lease.certificate['sequences']['1']})
            failed = False
            try:
                await lease.request('without-guard', {'key': 'fenced', 'amount': 9})
            except RuntimeError:
                failed = True
            if not failed:
                raise ValueError('request continued after guard removal')
            await lease.retire()
            weak = await client.acquire('weak-guard', [{'0': []}])
            weak_response = await net.rpc(2, 0, {'op': 'application', 'origin': 2,
                'sequence': weak['certificate']['sequences']['0'], 'manifest': 'weak-guard',
                'request_id': 'weak-authority', 'codec': ['ACTIVE', 'ACTIVE'],
                'input': {'key': 'weak', 'amount': 1}})
            await client.retire(weak['certificate'])
            unknown = await net.rpc(0, 0, {'op': 'install', 'support': ['emit:ACTIVE']})
            name = 'guard-controls'
            records.append({'name': name, 'initial': [PROFILES['accepting'] for _ in range(3)],
                'trace': net.trace, 'removed': removed, 'pipeline_rejected': failed,
                'weak_authority': weak_response, 'unknown_program': unknown})
            backup(net, output / 'databases' / name)
        finally:
            client.disconnect()
            net.stop()
    # The sink kills its own actual OS process after committing its application
    # row and before replying. Retry uses that durable result exactly once.
    with tempfile.TemporaryDirectory(prefix='application-crash-') as temporary:
        net = ApplicationNetwork(Path(temporary), [PROFILES['accepting'] for _ in range(3)],
                                 kill_requests={2: 'uncertain-request'})
        net.start()
        client = Client(net, 2)
        try:
            lease = await session(client, 'sink-crash')
            failed = False
            try:
                await lease.request('uncertain-request', {'key': 'recovered', 'amount': -7})
            except RuntimeError:
                failed = True
            process = net.processes[2]
            code = process.wait(timeout=5)
            if not failed or code != -9:
                raise ValueError('sink commit cut did not kill the owner')
            with sqlite3.connect(net.directory / 'process-node-2.sqlite') as db:
                committed = [list(row) for row in db.execute('SELECT * FROM application_results')]
            pending_retirement = await lease.retire()
            if pending_retirement:
                raise ValueError('uncertain application output lost its lease')
            backup(net, output / 'databases' / 'crash-pending')
            saved_certificate, saved_codec = deepcopy(lease.certificate), list(lease.codec)
            client.disconnect()
            client = Client(net, 2)
            lease = PipelineSession(client, saved_certificate, saved_codec)
            net.crash(2)
            result = await lease.request('uncertain-request', {'key': 'recovered', 'amount': -7})
            if not all(reply['duplicate'] for reply in result['owner_replies']):
                raise ValueError('uncertain retry wrote a second application effect')
            await lease.retire()
            # Install a changed serializer and reopen the process; its code
            # selector must use the committed profile, not startup defaults.
            installed = await net.rpc(0, 0, {'op': 'install', 'support': PROFILES['emitting']})
            net.crash(0)
            reopened = await net.rpc(0, 0, {'op': 'read'})
            final_lease = await session(client, 'after-activation-reopen')
            final_result = await final_lease.request('after-reopen', {'key': 'active', 'amount': 3})
            await final_lease.retire()
            name = 'crash-recovery'
            records.append({'name': name, 'initial': [PROFILES['accepting'] for _ in range(3)],
                'trace': net.trace, 'sink_exit_code': code, 'committed_before_retry': committed, 'pending_retirement': pending_retirement,
                'retry': result, 'installed': installed, 'reopened': reopened,
                'after_reopen': final_result})
            backup(net, output / 'databases' / name)
        finally:
            client.disconnect()
            net.stop()
    write(output / 'controls.json', records)


def probes():
    result = []
    for program in PROGRAMS:
        wire = encode(program, {'key': 'probe', 'amount': 23})
        emitted = json.loads(wire)['state']
        for name in ('ACTIVE', 'ENABLED'):
            data = json.loads(wire)
            data['state'] = name
            try:
                output = decode(program, canonical(data), name)
                accepted, error = True, None
            except Exception as failure:
                output, accepted, error = None, False, type(failure).__name__
            result.append({'program': program, 'input_name': name, 'emitted_name': emitted,
                           'accepted': accepted, 'output': output, 'exception': error})
    return result


async def run(output):
    if output.exists() and any(output.iterdir()):
        raise ValueError('use an empty output directory')
    output.mkdir(parents=True, exist_ok=True)
    source_names = ['src/application.py', 'tests/application_network.py',
                    'tests/application_rollout_study.py', 'tests/check_application_rollout.py',
                    'tests/test_application_rollout.py', 'docs/APPLICATION-STUDY.md', 'requirements-application.txt',
                    'src/controller.py','src/network.py','src/rollout.py','src/goal_planner.py','src/envelope.py','src/checker.py']
    captured = {name: (ROOT / name).read_bytes() for name in source_names}
    plan = build_plan()
    write(output / 'plan.json', plan)
    write(output / 'schema-probes.json', probes())
    catalog_goals(output)
    runs = []
    for concurrency in CONCURRENCIES:
        for repetition in range(REPETITIONS):
            # Alternate paired condition order to avoid a single fixed order.
            conditions = ('fixed', 'rollout') if repetition % 2 == 0 else ('rollout', 'fixed')
            for condition in conditions:
                name = f'{condition}-clients-{concurrency}-trial-{repetition + 1}'
                runs.append(await traffic_run(output, name, condition, concurrency, repetition, plan))
                print(canonical({'completed': name}), flush=True)
    await controls(output)
    write(output / 'runs.json', runs)
    write(output / 'environment.json', {'python': sys.version, 'protobuf': protobuf_version,
        'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(),
        'coordinator_pid': os.getpid(), 'logical_cpus': os.cpu_count(), 'affinity': sorted(os.sched_getaffinity(0)), 'owners': 'three separate OS processes',
        'transport': 'loopback TCP', 'sqlite_synchronous': 'FULL',
        'request_audit': 'durable owner audit enabled for all conditions',
        'latency_interval': 'first encode send through final sink reply, excludes batch admission/retirement',
        'condition_order': 'alternated within each concurrency', 'concurrencies': list(CONCURRENCIES),
        'repetitions': REPETITIONS, 'requests_per_trial': REQUESTS})
    for name, data in captured.items():
        if (ROOT / name).read_bytes() != data:
            raise ValueError('application study source changed during execution: ' + name)
        target = output / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    from tests.check_application_rollout import check
    write(output / 'summary.json', check(output, verify_summary=False))
    print(canonical(check(output)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.out.resolve()))
