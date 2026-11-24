"""Goal-coordinator recovery, directed-write races and actual process cuts.

Run ``python -B -m tests.rollout_recovery --out /new/directory``. Owner processes
remain alive while each coordinator child is SIGKILLed. One owner is then
independently killed/reopened before job recovery. This exercises process and
SQLite recovery on one host, not physical power loss or a multi-host partition.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import tempfile
import unittest

from src.controller import Endpoint, MAX_SEQ, canonical
from src.goal_planner import plan_goal
from src.network import Client, Network
from src.rollout import RolloutCoordinator, RolloutStateError, validate_execution_plan
from tests.multiprocess import ProcessNetwork

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = None
RECORDS = []


def chain_plan():
    # Five compatible cells form a staircase; reaching (2,2) needs four
    # independent safe phases, thereby reusing both origin identities.
    cells = [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2)]
    branches = [{'0': [f'a{x}'], '1': [f'b{y}']} for x, y in cells]
    catalogs = {'0': [[f'a{x}'] for x in range(3)], '1': [[f'b{y}'] for y in range(3)]}
    edges = {n: [{'source': v[i], 'target': v[i + 1]} for i in range(2)] for n, v in catalogs.items()}
    return plan_goal(branches, {'0': ['a0'], '1': ['b0']}, catalogs,
                     {'0': ['a2'], '1': ['b2']}, edges)


def two_phase_plan():
    branches = [{'0': ['a0'], '1': ['b0']},
                {'0': ['a1'], '1': ['b0']},
                {'0': ['a1'], '1': ['b1']}]
    catalogs = {'0': [['a0'], ['a1']], '1': [['b0'], ['b1']]}
    edges = {'0': [{'source': ['a0'], 'target': ['a1']}],
             '1': [{'source': ['b0'], 'target': ['b1']}]}
    return plan_goal(branches, {'0': ['a0'], '1': ['b0']}, catalogs,
                     {'0': ['a1'], '1': ['b1']}, edges)


def race_plan():
    a, b, c = [['a', 'shared'], ['b', 'shared'], ['c', 'shared']]
    return plan_goal([{'0': ['shared']}], {'0': a}, {'0': [a, b, c]},
                     {'0': b}, {'0': [{'source': a, 'target': b}]})


def local_progress_plan():
    branches = [{str(i): [f'cap{i}'] for i in range(3)}]
    catalogs = {str(i): [[f'cap{i}', 'v0'], [f'cap{i}', 'v1']] for i in range(3)}
    initial = {n: values[0] for n, values in catalogs.items()}
    target = {n: values[int(n != '2')] for n, values in catalogs.items()}
    return plan_goal(branches, initial, catalogs, target)


class TCPPartition:
    """Cut a coordinator's actual TCP route while its owner server stays alive.

    The proxy normally relays framed requests to the unchanged owner. Cutting
    it closes established streams and rejects subsequent connections. Direct
    inspection uses the owner's original address to verify its retained hold.
    """
    def __init__(self, network, node):
        self.network, self.node = network, node
        self.owner_port = network.ports[node]
        self.blocked = False
        self.connections = set()
        self.server = None

    async def _serve(self, reader, writer):
        upstream = None
        self.connections.add(writer)
        try:
            if self.blocked:
                return
            other, upstream = await asyncio.open_connection('127.0.0.1', self.owner_port)
            self.connections.add(upstream)
            while line := await reader.readline():
                if self.blocked:
                    return
                upstream.write(line)
                await upstream.drain()
                answer = await other.readline()
                if not answer:
                    return
                writer.write(answer)
                await writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass
        finally:
            for stream in (writer, upstream):
                if stream is not None:
                    self.connections.discard(stream)
                    stream.close()
                    try:
                        await stream.wait_closed()
                    except (ConnectionError, OSError):
                        pass

    async def start(self):
        await self.network._drop_connection(self.node)
        self.server = await asyncio.start_server(self._serve, '127.0.0.1', 0)
        self.network.ports[self.node] = self.server.sockets[0].getsockname()[1]
        return self

    async def cut(self):
        self.blocked = True
        streams = tuple(self.connections)
        for stream in streams:
            stream.close()
        if streams:
            await asyncio.gather(*(stream.wait_closed() for stream in streams),
                                 return_exceptions=True)
        await self.network._drop_connection(self.node)

    def heal(self):
        self.blocked = False

    async def inspect_owner(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.owner_port)
        try:
            writer.write((canonical({'op': 'inspect'}) + '\n').encode())
            await writer.drain()
            return json.loads(await asyncio.wait_for(reader.readline(), 2))['state']
        finally:
            writer.close()
            await writer.wait_closed()

    async def close(self):
        await self.cut()
        self.network.ports[self.node] = self.owner_port
        self.server.close()
        await self.server.wait_closed()


@asynccontextmanager
async def tcp_partition(network, node):
    partition = await TCPPartition(network, node).start()
    try:
        yield partition
    finally:
        await partition.close()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def backup_databases(source, destination):
    result = []
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob('*.sqlite')):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(path)) as src, sqlite3.connect(str(target)) as dst:
            src.backup(dst)
        result.append({'path': str(target.relative_to(OUTPUT)),
                       'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    return result


@asynccontextmanager
async def environment(plan):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        supports = [plan['initial'][str(i)] for i in range(len(plan['initial']))]
        net = Network(root / 'network', supports)
        await net.start()
        state = {'root': root, 'net': net, 'path': root / 'rollout.sqlite',
                 'job': RolloutCoordinator(net, root / 'rollout.sqlite', manifest='recovery-control', plan=plan)}
        try:
            yield state
        finally:
            state['job'].disconnect()
            await net.stop()


def reopen(state, observer=None):
    state['job'].disconnect()
    state['job'] = RolloutCoordinator(state['net'], state['path'], observer=observer)
    return state['job']


async def advance_to(state, stage, phase):
    for _ in range(100):
        position = state['job'].state
        if position['stage'] == stage and position['phase_index'] == phase:
            return
        result = await state['job'].advance()
        if result['status'] != 'progress':
            raise ValueError('Could not reach registered checkpoint: ' + str(result))
    raise ValueError('checkpoint action bound')


class ConditionalInstallTests(unittest.TestCase):
    def test_stale_source_does_not_write_or_override_guard(self):
        with tempfile.TemporaryDirectory() as d:
            owner = Endpoint(0, ['a'], Path(d) / 'owner.sqlite')
            try:
                owner.prepare(0, 1, 'held', ['a'])
                before = deepcopy(owner.state)
                self.assertEqual(owner.install_if_current(1, ['a'], ['b'])['status'], 'stale')
                self.assertEqual(owner.install_if_current(0, ['other'], ['b'])['status'], 'stale')
                self.assertEqual(owner.state, before)
                self.assertEqual(owner.install_if_current(0, ['a'], ['b'])['status'], 'blocked')
                self.assertEqual(owner.state, before)
            finally:
                owner.disconnect()

    def test_canonical_expected_profile_precedes_any_write(self):
        owner = Endpoint(0, ['a'])
        before = deepcopy(owner.state)
        for value in (False, True, 0.0, 1.0, -1, MAX_SEQ + 1, '0'):
            with self.subTest(generation=value), self.assertRaises(ValueError):
                owner.install_if_current(value, ['a'], ['b'])
        for support in (('a',), ['a', 'a'], ['b', 'a'], None):
            with self.subTest(support=support), self.assertRaises(ValueError):
                owner.install_if_current(0, support, ['b'])
        self.assertEqual(owner.state, before)

    def test_commit_and_reopen_preserve_conditional_installation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'owner.sqlite'
            owner = Endpoint(0, ['a'], path)
            result = owner.handle({'op': 'install_if_current', 'expected_generation': 0,
                                   'expected_support': ['a'], 'support': ['b']})
            self.assertEqual(result['status'], 'installed')
            owner.disconnect()
            owner = Endpoint(0, ['a'], path)
            try:
                self.assertEqual(owner.profile(), {'node': 0, 'generation': 1, 'support': ['b']})
                self.assertEqual(owner.install_if_current(0, ['a'], ['b'])['status'], 'stale')
                self.assertEqual(owner.profile()['generation'], 1)
            finally:
                owner.disconnect()


class PlanValidationTests(unittest.TestCase):
    def test_rejects_unsafe_box_transition_target_and_cost(self):
        plan = two_phase_plan()
        controls = []
        changed = deepcopy(plan); changed['phases'][0]['box']['1'] = [['b0'], ['b1']]; controls.append(changed)
        changed = deepcopy(plan); changed['transitions']['0'] = []; controls.append(changed)
        changed = deepcopy(plan); changed['target']['1'] = ['b0']; controls.append(changed)
        changed = deepcopy(plan); changed['cost']['installations'] = True; controls.append(changed)
        changed = deepcopy(plan); changed['phases'][0]['local_paths']['0'] = [['a0']]; controls.append(changed)
        for index, changed in enumerate(controls):
            with self.subTest(control=index), self.assertRaises(ValueError):
                validate_execution_plan(changed)
        RECORDS.append({'case': 'execution-plan negative controls', 'rejected': len(controls)})


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrelated_tcp_partition_allows_current_steps_until_phase_boundary(self):
        plan = local_progress_plan()
        self.assertEqual(plan['cost'], {'phases': 1, 'installations': 2, 'handoffs': 0})
        async with environment(plan) as state, tcp_partition(state['net'], 2) as partition:
            await advance_to(state, 'install', 0)
            await partition.cut()
            owner_before = await partition.inspect_owner()
            self.assertIn('0:1', owner_before['slots'])
            start = len(state['net'].trace)
            first = await state['job'].advance()
            self.assertEqual((first['status'], first.get('event')), ('progress', 'installed'))
            self.assertEqual(first['node'], '0')
            second = await reopen(state).advance()
            self.assertEqual((second['status'], second.get('event')), ('progress', 'installed'))
            self.assertEqual(second['node'], '1')
            steps = deepcopy(state['net'].trace[start:])
            self.assertEqual([(r['target'], r['request']['op']) for r in steps],
                             [(0, 'read'), (0, 'install_if_current'),
                              (1, 'read'), (1, 'install_if_current')])
            boundary = await state['job'].advance()
            self.assertEqual((boundary['status'], boundary['reason']), ('pending', 'owner-unreachable'))
            self.assertEqual(state['job'].state['step_index'], 2)
            self.assertEqual(state['job'].state['stage'], 'install')
            self.assertTrue(any(r['event'] == 'unreachable' and r['target'] == 2
                                for r in state['net'].trace[start:]))
            owner_during = await partition.inspect_owner()
            self.assertEqual(owner_before, owner_during)
            partition.heal()
            result = await reopen(state).run()
            self.assertEqual(result['status'], 'complete')
            self.assertEqual((result['acknowledged_installs'], result['reconciled_steps']), (2, 0))
            RECORDS.append({'case': 'unrelated owner TCP partition inside a committed phase',
                            'partitioned_owner': 2, 'local_step_trace': steps,
                            'boundary_result': boundary, 'owner_probe_before': owner_before,
                            'owner_probe_during': owner_during, 'result': result,
                            'trace': deepcopy(state['net'].trace)})

    async def test_current_target_tcp_partition_remains_pending_without_skipping(self):
        plan = local_progress_plan()
        async with environment(plan) as state, tcp_partition(state['net'], 0) as partition:
            await advance_to(state, 'install', 0)
            await partition.cut()
            start = len(state['net'].trace)
            result = await state['job'].advance()
            self.assertEqual((result['status'], result['reason'], result.get('node')),
                             ('pending', 'owner-unreachable', '0'))
            self.assertEqual(state['job'].state['step_index'], 0)
            attempted = deepcopy(state['net'].trace[start:])
            self.assertTrue(attempted)
            self.assertTrue(all(r['event'] == 'unreachable' and r['target'] == 0
                                and r['request']['op'] == 'read' for r in attempted))
            owner = await partition.inspect_owner()
            self.assertEqual(owner['generation'], 0)
            self.assertIn('0:1', owner['slots'])
            self.assertEqual(state['net'].nodes[1].state['generation'], 0)
            partition.heal()
            final = await reopen(state).run()
            self.assertEqual(final['status'], 'complete')
            RECORDS.append({'case': 'current target TCP partition does not skip the planned step',
                            'attempted_trace': attempted, 'result': result,
                            'owner_probe': owner, 'healed_result': final})

    async def test_other_owner_deviation_is_detected_at_phase_boundary(self):
        plan = local_progress_plan()
        async with environment(plan) as state:
            await advance_to(state, 'install', 0)
            external = await state['net'].rpc(5, 2, {'op': 'install', 'support': ['cap2', 'v1']})
            self.assertEqual(external['status'], 'installed')
            first = await state['job'].advance()
            second = await reopen(state).advance()
            self.assertEqual((first['event'], second['event']), ('installed', 'installed'))
            boundary = await state['job'].advance()
            self.assertEqual((boundary['status'], boundary['reason']),
                             ('deviation', 'phase-endpoint-differs'))
            self.assertEqual(boundary['observed']['2'], ['cap2', 'v1'])
            self.assertEqual((boundary['acknowledged_installs'], boundary['reconciled_steps']), (2, 0))
            self.assertEqual(state['job'].state['stage'], 'install')
            self.assertTrue(all('0:1' in owner.state['slots'] for owner in state['net'].nodes.values()))
            self.assertFalse(any(r.get('request', {}).get('op') == 'close' for r in state['net'].trace))
            restored = await state['net'].rpc(5, 2, {'op': 'install', 'support': ['cap2', 'v0']})
            self.assertEqual(restored['status'], 'installed')
            final = await state['job'].run()
            self.assertEqual(final['status'], 'complete')
            self.assertEqual(state['net'].nodes[2].state['generation'], 2)
            RECORDS.append({'case': 'non-target owner external deviation is detected at the phase boundary',
                            'external_update': external, 'boundary_result': boundary,
                            'guard_retained_until_restored': True, 'result': final,
                            'trace': deepcopy(state['net'].trace)})

    async def test_four_phase_origin_reuse_and_completed_reopen(self):
        plan = chain_plan()
        self.assertEqual(plan['cost'], {'phases': 4, 'installations': 4, 'handoffs': 3})
        async with environment(plan) as state:
            result = await state['job'].run()
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['acknowledged_installs'], 4)
            self.assertEqual(result['reconciled_steps'], 0)
            generations = [owner.state['generation'] for owner in state['net'].nodes.values()]
            self.assertEqual((await reopen(state).run())['status'], 'complete')
            self.assertEqual(generations, [owner.state['generation'] for owner in state['net'].nodes.values()])
            self.assertTrue(all(not client.state['attempts'] for client in state['job'].clients.values()))
            self.assertTrue(all(not owner.state['slots'] for owner in state['net'].nodes.values()))
            RECORDS.append({'case': 'four-phase origin reuse', 'phases': 4, 'goal_reached': True,
                            'completed_reopen_extra_generations': 0})

    async def test_zero_phase_goal_is_checked_without_admission(self):
        plan = plan_goal([{'0': ['a']}], {'0': ['a']}, {'0': [['a']]}, {'0': ['a']})
        async with environment(plan) as state:
            self.assertEqual((await state['job'].run())['status'], 'complete')
            self.assertFalse(any(r.get('request', {}).get('op') == 'prepare' for r in state['net'].trace))
            self.assertEqual(state['net'].nodes[0].state['generation'], 0)

    async def test_target_collect_cannot_invent_a_joint_configuration(self):
        a, other_a = ['a', 'shared'], ['other-a', 'shared']
        b, other_b = ['b', 'shared'], ['other-b', 'shared']
        target = {'0': a, '1': b}
        plan = plan_goal([{'0': ['shared'], '1': ['shared']}], target,
                         {'0': [a, other_a], '1': [b, other_b]}, target)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); net = Network(root / 'network', [a, other_b]); await net.start()
            job = RolloutCoordinator(net, root / 'job.sqlite', manifest='joint-target', plan=plan)
            actual = net.rpc
            changed = False
            actual_vectors = [[a, other_b]]
            async def interleave(source, node, request, **kw):
                nonlocal changed
                response = await actual(source, node, request, **kw)
                if request['op'] == 'read' and node == 0 and not changed:
                    changed = True
                    await actual(5, 0, {'op': 'install', 'support': other_a})
                    actual_vectors.append([other_a, other_b])
                    await actual(5, 1, {'op': 'install', 'support': b})
                    actual_vectors.append([other_a, b])
                return response
            net.rpc = interleave
            try:
                result = await job.run()
                self.assertEqual(result['reason'], 'target-snapshot-changed')
                self.assertNotIn([a, b], actual_vectors)
                self.assertNotIn('goal_reached', result)
                self.assertEqual((await job.run())['status'], 'deviation')
                RECORDS.append({'case': 'single collect would invent a joint target',
                                'actual_vectors': actual_vectors, 'target': [a, b],
                                'result': result, 'joint_target_ever_present': False})
            finally:
                job.disconnect(); await net.stop()

    async def test_target_collect_detects_aba_generation_change(self):
        plan = race_plan()
        plan = plan_goal(plan['branches'], plan['initial'], plan['catalog'], plan['initial'])
        async with environment(plan) as state:
            actual = state['net'].rpc
            changed = False
            async def aba(source, node, request, **kw):
                nonlocal changed
                response = await actual(source, node, request, **kw)
                if request['op'] == 'read' and not changed:
                    changed = True
                    await actual(5, node, {'op': 'install', 'support': ['c', 'shared']})
                    await actual(5, node, {'op': 'install', 'support': ['a', 'shared']})
                return response
            state['net'].rpc = aba
            result = await state['job'].run()
            self.assertEqual(result['reason'], 'target-snapshot-changed')
            observations = result['target_observation']
            self.assertEqual(observations['first']['0']['support'], observations['second']['0']['support'])
            self.assertEqual([observations[which]['0']['generation'] for which in ('first', 'second')], [0, 2])
            self.assertEqual((await state['job'].run())['status'], 'complete')
            RECORDS.append({'case': 'target collect with external ABA', 'generations': [0, 2],
                            'initial_result': 'target-snapshot-changed', 'stable_retry_completed': True})

    async def test_live_state_snapshots_cannot_change_the_persisted_plan(self):
        async with environment(two_phase_plan()) as state:
            snapshot = state['job'].state
            snapshot['plan']['target']['1'] = ['b0']
            snapshot['origins'][0] = 5
            plan = state['job'].plan
            plan['phases'][0]['steps'].clear()
            self.assertEqual((await state['job'].run())['status'], 'complete')
            with self.assertRaises(ValueError):
                RolloutCoordinator(state['net'], state['path'], origins=[False, 1])

    async def test_new_phase_partition_preserves_old_authority_until_healed(self):
        async with environment(two_phase_plan()) as state:
            await advance_to(state, 'acquire', 1)
            state['net'].blocked.add((1, 0))
            # Read profiles originate at 0; this partition would also prevent
            # the preflight read of owner 1. Drop only new-phase prepare/close
            # instead, representing request-specific delivery loss.
            state['net'].blocked.clear()
            actual = state['net'].rpc
            async def drop(source, target, request, **kw):
                if source == 1 and target == 1 and request['op'] in {'prepare', 'close'}:
                    return None
                return await actual(source, target, request, **kw)
            state['net'].rpc = drop
            result = await state['job'].run()
            self.assertEqual(result['reason'], 'phase-not-admitted')
            self.assertEqual(state['job'].state['stage'], 'acquire')
            self.assertTrue(all('0:1' in owner.state['slots'] for owner in state['net'].nodes.values()))
            state['net'].rpc = actual
            self.assertEqual((await reopen(state).run())['status'], 'complete')
            RECORDS.append({'case': 'new-phase admission lost', 'old_guard_preserved': True,
                            'healed_reopen_completed': True})

    async def test_old_close_loss_keeps_new_guard_and_recovers(self):
        async with environment(two_phase_plan()) as state:
            await advance_to(state, 'release-old', 1)
            actual = state['net'].rpc
            async def drop(source, target, request, **kw):
                if source == 0 and target == 1 and request['op'] == 'close':
                    return None
                return await actual(source, target, request, **kw)
            state['net'].rpc = drop
            result = await state['job'].run()
            self.assertEqual(result['reason'], 'old-phase-release-pending')
            self.assertTrue(all('1:1' in owner.state['slots'] for owner in state['net'].nodes.values()))
            self.assertEqual(state['net'].nodes[1].state['slots']['0:1']['status'], 'held')
            state['net'].rpc = actual
            self.assertEqual((await reopen(state).run())['status'], 'complete')
            RECORDS.append({'case': 'old close lost before delivery', 'next_guard_continuously_held': True,
                            'healed_reopen_completed': True})

    async def test_close_commit_with_lost_response_is_idempotently_reconciled(self):
        async with environment(two_phase_plan()) as state:
            await advance_to(state, 'release-old', 1)
            actual = state['net'].rpc
            lost = False
            async def drop(source, target, request, **kw):
                nonlocal lost
                response = await actual(source, target, request, **kw)
                if not lost and source == 0 and target == 1 and request['op'] == 'close':
                    lost = True
                    return None
                return response
            state['net'].rpc = drop
            self.assertEqual((await state['job'].run())['reason'], 'old-phase-release-pending')
            self.assertEqual(state['net'].nodes[1].state['floor'][0], 1)
            self.assertEqual((await reopen(state).run())['status'], 'complete')
            RECORDS.append({'case': 'old close committed but acknowledgement lost',
                            'closed_floor_before_recovery': 1, 'recovered': True})

    async def test_install_commit_with_lost_response_is_not_counted_twice(self):
        async with environment(race_plan()) as state:
            actual = state['net'].rpc
            lost = False
            async def drop(source, target, request, **kw):
                nonlocal lost
                response = await actual(source, target, request, **kw)
                if request['op'] == 'install_if_current' and not lost:
                    lost = True
                    return None
                return response
            state['net'].rpc = drop
            result = await state['job'].run()
            self.assertEqual(result['reason'], 'installation-outcome-unknown')
            self.assertEqual(state['net'].nodes[0].state['generation'], 1)
            result = await reopen(state).run()
            self.assertEqual(result['status'], 'complete')
            self.assertEqual((result['acknowledged_installs'], result['reconciled_steps']), (0, 1))
            self.assertEqual(state['net'].nodes[0].state['generation'], 1)
            RECORDS.append({'case': 'installation committed but acknowledgement lost',
                            'owner_generations': 1, 'acknowledged_installs': 0, 'reconciled_steps': 1})

    async def test_read_write_race_does_not_overwrite_an_external_profile(self):
        async with environment(race_plan()) as state:
            actual = state['net'].rpc
            changed = False
            async def race(source, target, request, **kw):
                nonlocal changed
                if request['op'] == 'install_if_current' and not changed:
                    changed = True
                    external = await actual(5, target, {'op': 'install', 'support': ['c', 'shared']})
                    self.assertEqual(external['status'], 'installed')
                return await actual(source, target, request, **kw)
            state['net'].rpc = race
            result = await state['job'].run()
            self.assertEqual(result['reason'], 'owner-profile-changed')
            self.assertEqual(state['net'].nodes[0].state['support'], ['c', 'shared'])
            result = await state['job'].run()
            self.assertEqual(result['status'], 'deviation')
            self.assertEqual(state['net'].nodes[0].state['generation'], 1)
            self.assertEqual(result['acknowledged_installs'], 0)
            RECORDS.append({'case': 'external write between read and conditional install',
                            'first_result': 'owner-profile-changed', 'second_result': 'deviation',
                            'external_profile_preserved': True, 'controller_installations': 0})

    async def test_external_target_is_reconciled_without_install_credit(self):
        async with environment(race_plan()) as state:
            await state['job'].advance()
            self.assertEqual((await state['net'].rpc(5, 0, {'op': 'install', 'support': ['b', 'shared']}))['status'], 'installed')
            result = await state['job'].run()
            self.assertEqual(result['status'], 'complete')
            self.assertEqual((result['acknowledged_installs'], result['reconciled_steps']), (0, 1))
            self.assertFalse(any(r.get('request', {}).get('op') == 'install_if_current' for r in state['net'].trace))
            RECORDS.append({'case': 'external writer reached next planned support',
                            'controller_installations': 0, 'reconciled_steps': 1})

    async def test_foreign_origin_authority_is_never_retired(self):
        plan = two_phase_plan()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); net = Network(root / 'network', [['a0'], ['b0']]); await net.start()
            core = Client(net, 0)
            try:
                admitted = await core.acquire_box('unrelated-application', plan['branches'], plan['phases'][0]['box'])
                self.assertEqual(admitted['status'], 'admitted')
                token = admitted['certificate']; core.disconnect()
                before = len(net.trace)
                with self.assertRaises(RolloutStateError):
                    RolloutCoordinator(net, root / 'job.sqlite', manifest='new-job', plan=plan)
                self.assertEqual(len(net.trace), before)
                core = Client(net, 0)
                self.assertTrue(all(r['status'] == 'used' for r in await core.use(token)))
                self.assertTrue(await core.retire(token))
                RECORDS.append({'case': 'foreign origin authority', 'job_rejected': True,
                                'foreign_authority_preserved': True, 'cleanup_rpcs_sent': 0})
            finally:
                core.disconnect(); await net.stop()

    async def test_journal_abort_after_admission_requires_reopen(self):
        async with environment(two_phase_plan()) as state:
            def abort(event):
                if event['event'] == 'acquire-returned':
                    state['job'].db.execute("CREATE TRIGGER job_abort BEFORE INSERT ON state BEGIN SELECT RAISE(ABORT,'rollout journal abort'); END")
                    state['job'].db.commit()
            state['job']._observer = abort
            with self.assertRaises(sqlite3.DatabaseError):
                await state['job'].advance()
            with self.assertRaises(sqlite3.DatabaseError):
                await state['job'].advance()
            self.assertEqual(next(iter(state['job'].clients[0].state['attempts'].values()))['status'], 'committed')
            state['job'].disconnect()
            with sqlite3.connect(str(state['path'])) as db:
                db.execute('DROP TRIGGER job_abort')
            self.assertEqual((await reopen(state).run())['status'], 'complete')
            RECORDS.append({'case': 'real job SQLite abort after core commitment',
                            'continued_use_rejected': True, 'reopened_completion': True})

    async def test_uncertain_journal_commit_uses_durable_position(self):
        async with environment(two_phase_plan()) as state:
            job = state['job']; actual = job._write
            def uncertain(value):
                actual(value)
                raise sqlite3.OperationalError('postcommit job uncertainty')
            job._write = uncertain
            with self.assertRaises(sqlite3.DatabaseError):
                await job.advance()
            self.assertEqual(job.state['stage'], 'acquire')
            with self.assertRaises(sqlite3.DatabaseError):
                await job.advance()
            replacement = reopen(state)
            self.assertEqual(replacement.state['stage'], 'install')
            self.assertEqual((await replacement.run())['status'], 'complete')
            RECORDS.append({'case': 'job commit reported an error after commit',
                            'stale_memory_stage': 'acquire', 'reopened_durable_stage': 'install',
                            'completed': True})

    async def test_tampered_durable_role_and_input_are_rejected(self):
        async with environment(two_phase_plan()) as state:
            await state['job'].advance()
            state['job'].disconnect()
            with sqlite3.connect(str(state['path'])) as db:
                stored = json.loads(db.execute('SELECT payload FROM state').fetchone()[0])
                changed = deepcopy(stored); changed['stage'] = 'release-old'
                db.execute('UPDATE state SET payload=?', (canonical(changed),))
            with self.assertRaises(RolloutStateError):
                RolloutCoordinator(state['net'], state['path'])
            with sqlite3.connect(str(state['path'])) as db:
                db.execute('UPDATE state SET payload=?', (canonical(stored),))
            with self.assertRaises(RolloutStateError):
                RolloutCoordinator(state['net'], state['path'], manifest='different-job')
            self.assertEqual((await reopen(state).run())['status'], 'complete')

    async def test_late_prepare_remains_closed_after_completed_owner_reopen(self):
        async with environment(two_phase_plan()) as state:
            tokens = []
            state['job']._observer = lambda event: tokens.append(event['certificate']) if event['event'] == 'acquire-returned' else None
            self.assertEqual((await state['job'].run())['status'], 'complete')
            await state['net'].crash(1)
            for token in tokens:
                for node, sequence in token['sequences'].items():
                    answer = await state['net'].rpc(token['origin'], int(node), {
                        'op': 'prepare', 'origin': token['origin'], 'sequence': sequence,
                        'manifest': token['manifest'], 'requires': [], 'options': token['box'][node]})
                    self.assertEqual(answer['status'], 'closed')
            self.assertEqual((await reopen(state).run())['status'], 'complete')
            RECORDS.append({'case': 'late prepare after completed owner reopen',
                            'phase_tokens': len(tokens), 'rejected_prepares': sum(len(t['sequences']) for t in tokens)})

    async def test_coordinator_sigkills_recover_while_owners_are_independent(self):
        plan = two_phase_plan()
        cuts = [
            {'event': 'acquire-returned', 'phase_index': 0},
            {'event': 'install-returned', 'phase_index': 0},
            {'event': 'acquire-returned', 'phase_index': 1},
            {'event': 'phase-recorded', 'phase_index': 1},
            {'event': 'retire-returned', 'phase_index': 1, 'retired_phase': 0},
            {'event': 'retire-returned', 'phase_index': 1, 'retired_phase': 1},
        ]
        for index, cut in enumerate(cuts):
            with self.subTest(cut=cut), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                net = ProcessNetwork(root / 'network', [['a0'], ['b0']])
                net.start(); job = None
                try:
                    config = {'network_directory': str(net.directory), 'supports': net.supports,
                              'ports': net.ports, 'path': str(root / 'rollout.sqlite'),
                              'plan': plan, 'cut': cut, 'cut_record': str(root / 'cut.json')}
                    write_json(root / 'child.json', config)
                    flags = ['-O', '-B'] if sys.flags.optimize else ['-B']
                    command = [sys.executable, *flags, '-m', 'tests.rollout_recovery', '--child', str(root / 'child.json')]
                    process = await asyncio.create_subprocess_exec(*command, cwd=ROOT,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
                    self.assertEqual(process.returncode, -signal.SIGKILL, stderr.decode())
                    before = json.loads((root / 'cut.json').read_text())
                    owners_before = {}
                    for node in (0, 1):
                        owners_before[str(node)] = (await net.rpc(5, node, {'op': 'inspect'}))['state']
                    if index == 2:
                        self.assertEqual(before['job']['stage'], 'acquire')
                        self.assertEqual(len(before['job']['certificates']), 1)
                        self.assertTrue(all(next(iter(v['attempts'].values()))['status'] == 'committed'
                                            for v in before['origins'].values()))
                    retained = {}
                    if OUTPUT is not None:
                        retained['before'] = backup_databases(root, OUTPUT / 'databases' / f'cut-{index}' / 'before')
                    net.crash(1)
                    owner_kills = net.sigkills
                    job = RolloutCoordinator(net, root / 'rollout.sqlite')
                    result = await job.run()
                    self.assertEqual(result['status'], 'complete')
                    owners_after = {}
                    for node in (0, 1):
                        observed = await net.rpc(5, node, {'op': 'inspect'})
                        owners_after[str(node)] = observed['state']
                        self.assertEqual(observed['state']['support'], plan['target'][str(node)])
                        self.assertEqual(observed['state']['generation'], 1)
                        self.assertFalse(observed['state']['slots'])
                    self.assertEqual(result['acknowledged_installs'] + result['reconciled_steps'], 2)
                    self.assertEqual((await job.run())['status'], 'complete')
                    if OUTPUT is not None:
                        retained['after'] = backup_databases(root, OUTPUT / 'databases' / f'cut-{index}' / 'after')
                    record = {'case': 'independent coordinator process cut', 'cut': cut,
                              'coordinator_returncode': process.returncode, 'coordinator_sigkills': 1,
                              'owner_sigkills': owner_kills, 'owners_remained_alive_at_coordinator_cut': True,
                              'before': before, 'owner_states_before': owners_before,
                              'owner_states_after': owners_after, 'result': result,
                              'database_snapshots': retained, 'stderr': stderr.decode(), 'stdout': stdout.decode()}
                    RECORDS.append(record)
                finally:
                    if job is not None:
                        job.disconnect()
                    net.stop()


class RemoteOwners:
    """Coordinator-only transport to already running owner processes."""
    def __init__(self, config):
        self.directory = Path(config['network_directory'])
        self.supports = config['supports']
        self.ports = {int(n): port for n, port in config['ports'].items()}
        self.window = 8
        self.policy = 'predicate'

    async def rpc(self, source, target, request):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.ports[target])
        try:
            writer.write((canonical(request) + '\n').encode())
            await writer.drain()
            return json.loads(await asyncio.wait_for(reader.readline(), 5))
        finally:
            writer.close()
            await writer.wait_closed()


async def child(config):
    net = RemoteOwners(config)
    job = None
    events = []
    def observe(event):
        events.append(event)
        if all(event.get(k) == v for k, v in config['cut'].items()):
            write_json(Path(config['cut_record']), {'cut': config['cut'], 'events': events,
                       'job': job.state,
                       'origins': {str(n): deepcopy(c.state) for n, c in job.clients.items()}})
            os.kill(os.getpid(), signal.SIGKILL)
    job = RolloutCoordinator(net, Path(config['path']), manifest='process-cut-goal',
                             plan=config['plan'], observer=observe)
    try:
        await job.run()
        raise RuntimeError('registered process cut was not reached')
    finally:
        job.disconnect()


def sources():
    names = ['src/__init__.py', 'src/controller.py', 'src/checker.py', 'src/envelope.py',
             'src/network.py', 'src/goal_planner.py', 'src/rollout.py',
             'tests/rollout_recovery.py', 'tests/multiprocess.py', 'tests/process_tcp_endpoint.py']
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--out', type=Path)
    group.add_argument('--child', type=Path)
    args = parser.parse_args()
    if args.child:
        asyncio.run(child(json.loads(args.child.read_text())))
        return
    OUTPUT = args.out.resolve()
    if OUTPUT.exists() or OUTPUT.is_relative_to(ROOT):
        raise ValueError('Use a new output directory outside artifact')
    OUTPUT.mkdir(parents=True)
    before = sources()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if sources() != before:
        raise RuntimeError('executed sources changed during suite')
    write_json(OUTPUT / 'observations.json', RECORDS)
    summary = {'status': 'PASS' if result.wasSuccessful() else 'FAIL',
               'mode': 'optimized' if sys.flags.optimize else 'normal',
               'tests_run': result.testsRun, 'skipped': len(result.skipped),
               'failures': len(result.failures), 'errors': len(result.errors),
               'observations': len(RECORDS),
               'coordinator_sigkills': sum(r.get('coordinator_sigkills', 0) for r in RECORDS),
               'owner_sigkills': sum(r.get('owner_sigkills', 0) for r in RECORDS),
               'source_sha256': before,
               'scope': 'Single-host independent owner processes, durable coordinator recovery and SQLite state; not physical power loss or WAN failure.'}
    write_json(OUTPUT / 'summary.json', summary)
    print(json.dumps(summary, sort_keys=True))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    main()
