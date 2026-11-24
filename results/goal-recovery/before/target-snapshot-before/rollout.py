"""Durable execution of a finite, explicitly planned rollout goal.

The coordinator owns two otherwise unused origin identities and one SQLite
journal. It admits the next safe phase before retiring the preceding one.
Recovery resumes the persisted role of each origin, including the interval
where both admissions have committed. Local installations use an atomic
profile comparison, so a read/write race cannot silently change a planned
directed transition. Goal optimality belongs to the planner; this module checks
plan feasibility and preserves its execution intent, not a new optimum under
external changes or permanent partitions.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
from inspect import isawaitable, iscoroutine
from pathlib import Path
import sqlite3

from .checker import certificate, safe_envelope
from .controller import (MAX_CONTRACTS, MAX_NODES, MAX_SEQ, atoms, canonical,
                         initialize_state_table, load_singleton_state)
from .envelope import antichain, compatible, normalize
from .network import Client

MAX_PHASES = 4096
MAX_STEPS = 4096
PLAN_SCHEMA = 'rollout-goal-plan-v1'
STATE_SCHEMA = 'durable-rollout-v1'


class RolloutStateError(ValueError):
    """The job, its durable authority or a planned transition is inconsistent."""


def _support(value):
    if not isinstance(value, list) or atoms(value, MAX_CONTRACTS) != value:
        raise RolloutStateError('noncanonical planned support')
    return list(value)


def _vector(value, nodes):
    if not isinstance(value, dict) or set(value) != set(nodes):
        raise RolloutStateError('planned vector placement differs')
    return {node: _support(value[node]) for node in nodes}


def _accepted(box, node, support):
    return any(set(term) <= set(support) for term in box[node])


def validate_execution_plan(plan):
    """Check the full directed path and every phase independently of the planner.

    This validates feasibility, all local transitions, final target and reported
    path cost. It does not re-run the search or certify minimality. Search
    diagnostics are retained as metadata and never authorize an action.
    """
    if (not isinstance(plan, dict) or plan.get('schema') != PLAN_SCHEMA or
            plan.get('status') != 'planned'):
        raise RolloutStateError('a completed feasible goal plan is required')
    required = {'branches', 'initial', 'target', 'catalog', 'transitions',
                'cost', 'phases'}
    if not required <= set(plan):
        raise RolloutStateError('goal plan is incomplete')
    branches = normalize(plan['branches'])
    if branches != plan['branches']:
        raise RolloutStateError('noncanonical planned branches')
    nodes = sorted(branches[0], key=int)
    initial = _vector(plan['initial'], nodes)
    target = _vector(plan['target'], nodes)
    if not all(compatible(branches, {n: set(s[n]) for n in nodes})
               for s in (initial, target)):
        raise RolloutStateError('incompatible initial or target state')
    if (not isinstance(plan['catalog'], dict) or
            set(plan['catalog']) != set(nodes) or
            not isinstance(plan['transitions'], dict) or
            set(plan['transitions']) != set(nodes)):
        raise RolloutStateError('catalog or transition placement differs')
    catalogs = {}
    edges = {}
    for node in nodes:
        raw = plan['catalog'][node]
        if not isinstance(raw, list) or not raw:
            raise RolloutStateError('empty local catalog')
        values = [_support(value) for value in raw]
        catalog = {tuple(value) for value in values}
        if len(catalog) != len(values):
            raise RolloutStateError('duplicate local catalog entry')
        if tuple(initial[node]) not in catalog or tuple(target[node]) not in catalog:
            raise RolloutStateError('initial or target profile outside catalog')
        catalogs[node] = catalog
        raw_edges = plan['transitions'][node]
        if not isinstance(raw_edges, list):
            raise RolloutStateError('invalid local transition list')
        edges[node] = set()
        for edge in raw_edges:
            if not isinstance(edge, dict) or set(edge) != {'source', 'target'}:
                raise RolloutStateError('invalid directed transition schema')
            source, destination = _support(edge['source']), _support(edge['target'])
            if tuple(source) not in catalog or tuple(destination) not in catalog:
                raise RolloutStateError('directed transition outside catalog')
            pair = (tuple(source), tuple(destination))
            if pair in edges[node]:
                raise RolloutStateError('duplicate directed transition')
            edges[node].add(pair)
    phases = plan['phases']
    if not isinstance(phases, list) or len(phases) > MAX_PHASES:
        raise RolloutStateError('execution phase bound')
    previous = initial
    writes = 0
    for phase in phases:
        if not isinstance(phase, dict) or not {'source', 'target', 'box', 'steps', 'local_paths'} <= set(phase):
            raise RolloutStateError('incomplete execution phase')
        source = _vector(phase['source'], nodes)
        destination = _vector(phase['target'], nodes)
        if source != previous:
            raise RolloutStateError('phase source does not continue previous phase')
        raw_box = phase['box']
        if not isinstance(raw_box, dict) or set(raw_box) != set(nodes):
            raise RolloutStateError('phase box placement differs')
        box = {node: antichain(raw_box[node]) for node in nodes}
        if raw_box != box or not safe_envelope(branches, box):
            raise RolloutStateError('noncanonical or unsafe phase guard')
        if not all(_accepted(box, node, source[node]) for node in nodes):
            raise RolloutStateError('phase guard excludes its source')
        steps = phase['steps']
        if not isinstance(steps, list) or not steps:
            raise RolloutStateError('a phase must make at least one transition')
        current = deepcopy(source)
        local_paths = {node: [list(source[node])] for node in nodes}
        for step in steps:
            if not isinstance(step, dict) or set(step) != {'node', 'support'}:
                raise RolloutStateError('invalid planned installation schema')
            node = step['node']
            if not isinstance(node, str) or node not in nodes:
                raise RolloutStateError('unknown planned owner')
            support = _support(step['support'])
            pair = (tuple(current[node]), tuple(support))
            if pair[0] == pair[1] or pair not in edges[node]:
                raise RolloutStateError('installation is not a declared directed transition')
            if not _accepted(box, node, support):
                raise RolloutStateError('installation lies outside its phase guard')
            current[node] = support
            local_paths[node].append(list(support))
            writes += 1
            if writes > MAX_STEPS:
                raise RolloutStateError('execution installation bound')
        if current != destination or phase['local_paths'] != local_paths:
            raise RolloutStateError('phase path and endpoint differ')
        previous = destination
    if previous != target or (not phases and initial != target):
        raise RolloutStateError('plan does not reach its target')
    cost = plan['cost']
    expected = {'phases': len(phases), 'installations': writes,
                'handoffs': max(len(phases) - 1, 0)}
    if (not isinstance(cost, dict) or set(cost) != set(expected) or
            any(type(cost[k]) is not int or cost[k] != value
                for k, value in expected.items())):
        raise RolloutStateError('reported execution cost differs from path')
    return deepcopy(plan)


class RolloutCoordinator:
    """Single-writer recovery of a fixed goal plan over two private origins.

    Create with ``manifest``, a feasible ``plan`` and optionally two ``origins``.
    Reopen with only ``network`` and ``path``: the complete input and phase
    roles are read from the durable job. The former writer must have stopped.
    These origins own no unrelated admission or application effect lease.
    """
    def __init__(self, network, path: Path, *, manifest=None, plan=None,
                 origins=None, observer=None):
        self.net = network
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._failed = False
        self._closed = False
        self._observer = observer
        self.clients = {}
        if observer is not None and not callable(observer):
            raise ValueError('rollout observer must be callable')
        if network.policy != 'predicate':
            raise RolloutStateError('goal execution requires predicate guards')
        self.db = sqlite3.connect(str(self.path))
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA journal_mode=DELETE')
            initialize_state_table(self.db)
            loaded = load_singleton_state(self.db)
            if loaded is None:
                if not isinstance(manifest, str) or not manifest or len(manifest) > 128:
                    raise RolloutStateError('new rollout needs a bounded manifest identity')
                planned = validate_execution_plan(plan)
                selected = [0, 1] if origins is None else list(origins)
                self._validate_origins(selected)
                self._state = {
                    'schema': STATE_SCHEMA, 'manifest': manifest,
                    'plan': planned, 'plan_sha256': self._digest(planned),
                    'network': self._network_identity(), 'origins': selected,
                    'phase_index': 0, 'step_index': 0,
                    'stage': 'acquire' if planned['phases'] else 'complete',
                    'certificates': {}, 'acknowledged_installs': 0,
                    'reconciled_steps': 0, 'journal_revision': 0,
                }
                self._validate_state(self._state)
                self._write(self._state)
            else:
                self._validate_state(loaded)
                self._state = loaded
                if manifest is not None and manifest != loaded['manifest']:
                    raise RolloutStateError('reopened manifest differs')
                if plan is not None and canonical(plan) != canonical(loaded['plan']):
                    raise RolloutStateError('reopened plan differs')
                if origins is not None:
                    self._validate_origins(list(origins))
                    if list(origins) != loaded['origins']:
                        raise RolloutStateError('reopened origins differ')
            for origin in self._state['origins']:
                self.clients[origin] = Client(network, origin)
            self._check_origin_ownership()
        except BaseException:
            for client in self.clients.values():
                client.disconnect()
            self.db.close()
            self._closed = True
            raise

    @staticmethod
    def _digest(value):
        return hashlib.sha256(canonical(value).encode()).hexdigest()

    def _network_identity(self):
        return {'node_count': len(self.net.supports), 'window': self.net.window,
                'policy': self.net.policy}

    @staticmethod
    def _validate_origins(origins):
        if (not isinstance(origins, list) or len(origins) != 2 or
                any(type(v) is not int or not 0 <= v < MAX_NODES for v in origins) or
                origins[0] == origins[1]):
            raise RolloutStateError('two distinct canonical origin identities required')

    def _validate_state(self, state):
        expected = {'schema', 'manifest', 'plan', 'plan_sha256', 'network', 'origins',
                    'phase_index', 'step_index', 'stage', 'certificates',
                    'acknowledged_installs', 'reconciled_steps', 'journal_revision'}
        if not isinstance(state, dict) or set(state) != expected or state['schema'] != STATE_SCHEMA:
            raise RolloutStateError('invalid durable rollout schema')
        if not isinstance(state['manifest'], str) or not state['manifest'] or len(state['manifest']) > 128:
            raise RolloutStateError('invalid durable manifest')
        validate_execution_plan(state['plan'])
        if state['plan_sha256'] != self._digest(state['plan']):
            raise RolloutStateError('durable plan binding differs')
        identity = state['network']
        if (not isinstance(identity, dict) or identity != self._network_identity() or
                type(identity.get('node_count')) is not int or
                type(identity.get('window')) is not int):
            raise RolloutStateError('durable rollout network differs')
        nodes = state['plan']['initial']
        if any(int(node) >= len(self.net.supports) for node in nodes):
            raise RolloutStateError('planned owner outside network')
        self._validate_origins(state['origins'])
        phases = state['plan']['phases']
        i, k, stage = state['phase_index'], state['step_index'], state['stage']
        if type(i) is not int or type(k) is not int or not 0 <= i <= len(phases):
            raise RolloutStateError('invalid durable rollout position')
        certificates = state['certificates']
        if not isinstance(certificates, dict):
            raise RolloutStateError('invalid durable phase certificates')
        if stage == 'complete':
            if i != len(phases) or k != 0 or certificates:
                raise RolloutStateError('invalid completed rollout state')
            completed = sum(len(p['steps']) for p in phases)
        else:
            if not 0 <= i < len(phases) or not 0 <= k <= len(phases[i]['steps']):
                raise RolloutStateError('invalid active rollout position')
            if stage == 'acquire':
                wanted = set() if i == 0 else {str(i - 1)}
                if k != 0:
                    raise RolloutStateError('acquiring phase already has steps')
            elif stage == 'release-old':
                wanted = {str(i - 1), str(i)}
                if i == 0 or k != 0:
                    raise RolloutStateError('invalid phase overlap state')
            elif stage == 'install':
                wanted = {str(i)}
            elif stage == 'release-final':
                wanted = {str(i)}
                if i != len(phases) - 1 or k != len(phases[i]['steps']):
                    raise RolloutStateError('final retirement before target path')
            else:
                raise RolloutStateError('unknown durable rollout stage')
            if set(certificates) != wanted:
                raise RolloutStateError('phase certificates differ from durable roles')
            completed = sum(len(p['steps']) for p in phases[:i]) + k
        for key, token in certificates.items():
            index = int(key)
            if (key != str(index) or not 0 <= index < len(phases) or
                    not certificate(token, state['plan']['branches']) or
                    token.get('box') != phases[index]['box'] or
                    token.get('manifest') != self._phase_manifest(index, state) or
                    type(token.get('origin')) is not int or
                    token['origin'] != state['origins'][index % 2]):
                raise RolloutStateError('durable phase certificate binding differs')
        for field in ('acknowledged_installs', 'reconciled_steps', 'journal_revision'):
            if type(state[field]) is not int or not 0 <= state[field] <= MAX_SEQ:
                raise RolloutStateError('invalid durable rollout counter')
        if state['acknowledged_installs'] + state['reconciled_steps'] != completed:
            raise RolloutStateError('completed path steps and counters differ')

    @property
    def state(self):
        return deepcopy(self._state)

    @property
    def plan(self):
        return deepcopy(self._state['plan'])

    def _phase_manifest(self, index, state=None):
        state = self._state if state is None else state
        return f"{state['manifest']}:r:{state['plan_sha256']}:p:{index}"

    def _phase_client(self, index):
        return self.clients[self._state['origins'][index % 2]]

    def _healthy(self):
        if self._closed or self._failed:
            raise sqlite3.DatabaseError('rollout journal must be reopened')
        for client in self.clients.values():
            client._require_healthy()

    def _write(self, state):
        try:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (canonical(state),))
        except sqlite3.DatabaseError:
            self._failed = True
            raise

    def _commit(self, **changes):
        state = deepcopy(self._state)
        state.update(changes)
        state['journal_revision'] += 1
        self._validate_state(state)
        try:
            self._write(state)
        except sqlite3.DatabaseError:
            self._failed = True
            raise
        self._state = state

    def _emit(self, event, **details):
        if self._observer is None:
            return
        value = {'event': event, 'phase_index': self._state['phase_index'],
                 'step_index': self._state['step_index'], 'stage': self._state['stage'],
                 **details}
        result = self._observer(deepcopy(value))
        if isawaitable(result):
            if iscoroutine(result):
                result.close()
            raise TypeError('rollout observer must be synchronous')

    def _check_origin_ownership(self):
        self._healthy()
        i = self._state['phase_index']
        indices = [] if self._state['stage'] == 'complete' else [j for j in (i - 1, i) if j >= 0]
        known = {self._phase_manifest(j): j for j in indices}
        for origin, client in self.clients.items():
            for record in client.state['attempts'].values():
                index = known.get(record['manifest'])
                if index is None or self._state['origins'][index % 2] != origin:
                    raise RolloutStateError('origin has authority outside this job phase')
                token = record.get('certificate')
                if token is not None and (
                        token.get('box') != self._state['plan']['phases'][index]['box'] or
                        not certificate(token, self._state['plan']['branches'])):
                    raise RolloutStateError('origin phase authority differs from plan')

    def _require_committed(self, index):
        token = self._state['certificates'].get(str(index))
        if token is None:
            raise RolloutStateError('missing phase authority')
        client = self._phase_client(index)
        key = client._record(token)
        if key is None or client.state['attempts'][key]['status'] != 'committed':
            raise RolloutStateError('active phase is no longer durably committed')
        return token

    def _result(self, status, **details):
        return {'status': status, 'phase_index': self._state['phase_index'],
                'step_index': self._state['step_index'], 'stage': self._state['stage'],
                'planned_cost': deepcopy(self._state['plan']['cost']),
                'acknowledged_installs': self._state['acknowledged_installs'],
                'reconciled_steps': self._state['reconciled_steps'], **details}

    async def _profiles(self):
        profiles = {}
        source = self._state['origins'][0]
        for node in sorted(self._state['plan']['initial'], key=int):
            response = await self.net.rpc(source, int(node), {'op': 'read'})
            if response is None or response.get('status') == 'unavailable':
                return None
            if response.get('status') != 'observed':
                raise RolloutStateError('unexpected authoritative profile response')
            profile = response.get('observed')
            if (not isinstance(profile, dict) or set(profile) != {'node', 'generation', 'support'} or
                    type(profile['node']) is not int or profile['node'] != int(node) or
                    type(profile['generation']) is not int or not 0 <= profile['generation'] <= MAX_SEQ):
                raise RolloutStateError('invalid authoritative profile')
            _support(profile['support'])
            profiles[node] = deepcopy(profile)
        return profiles

    async def _target_check(self):
        profiles = await self._profiles()
        if profiles is None:
            return self._result('pending', reason='owner-unreachable')
        observed = {n: p['support'] for n, p in profiles.items()}
        if observed != self._state['plan']['target']:
            return self._result('deviation', reason='target-state-differs', observed=observed)
        return None

    async def advance(self):
        """Perform one resumable phase action, or report an explicit pending state."""
        async with self._lock:
            self._check_origin_ownership()
            state = self._state
            i, stage = state['phase_index'], state['stage']
            if stage == 'complete':
                return await self._target_check() or self._result('complete', goal_reached=True)
            phase = state['plan']['phases'][i]
            if stage == 'acquire':
                # Check the planned source before starting a new phase. The
                # acquired guard independently checks every owner's then-current
                # support, so this read is not an authority substitute.
                profiles = await self._profiles()
                if profiles is None:
                    return self._result('pending', reason='owner-unreachable')
                observed = {n: p['support'] for n, p in profiles.items()}
                if observed != phase['source']:
                    return self._result('deviation', reason='phase-source-differs', observed=observed)
                if i:
                    self._require_committed(i - 1)
                response = await self._phase_client(i).acquire_box(
                    self._phase_manifest(i), state['plan']['branches'], phase['box'])
                if response.get('status') != 'admitted':
                    return self._result('pending', reason='phase-not-admitted', admission=deepcopy(response))
                token = response['certificate']
                self._emit('acquire-returned', certificate=token)
                certificates = deepcopy(state['certificates'])
                certificates[str(i)] = deepcopy(token)
                self._commit(certificates=certificates, stage='release-old' if i else 'install')
                self._emit('phase-recorded', certificate=token)
                return self._result('progress', event='phase-admitted')
            if stage == 'release-old':
                self._require_committed(i)
                old = state['certificates'][str(i - 1)]
                client = self._phase_client(i - 1)
                key = client._record(old)
                retired = key is None or await client.retire(old)
                self._emit('retire-returned', retired=retired, retired_phase=i - 1)
                if not retired:
                    return self._result('pending', reason='old-phase-release-pending')
                certificates = {str(i): deepcopy(state['certificates'][str(i)])}
                self._commit(certificates=certificates, stage='install')
                self._emit('old-phase-released', retired_phase=i - 1)
                return self._result('progress', event='old-phase-released')
            if stage == 'install':
                self._require_committed(i)
                k = state['step_index']
                expected = deepcopy(phase['source'])
                for step in phase['steps'][:k]:
                    expected[step['node']] = list(step['support'])
                profiles = await self._profiles()
                if profiles is None:
                    return self._result('pending', reason='owner-unreachable')
                observed = {n: p['support'] for n, p in profiles.items()}
                if k == len(phase['steps']):
                    if observed != expected:
                        return self._result('deviation', reason='phase-endpoint-differs', observed=observed)
                    if i + 1 == len(state['plan']['phases']):
                        self._commit(stage='release-final')
                    else:
                        self._commit(phase_index=i + 1, step_index=0, stage='acquire')
                    self._emit('phase-completed', completed_phase=i)
                    return self._result('progress', event='phase-completed')
                step = phase['steps'][k]
                node, support = step['node'], step['support']
                after = deepcopy(expected)
                after[node] = list(support)
                if observed == after:
                    # This is target reconciliation, not an installation credit:
                    # a prior acknowledgement may have been lost, or an external
                    # writer may have made the same planned transition.
                    self._commit(step_index=k + 1, reconciled_steps=state['reconciled_steps'] + 1)
                    self._emit('installation-recorded', outcome='already-target', node=node)
                    return self._result('progress', event='already-target', node=node)
                if observed != expected:
                    return self._result('deviation', reason='planned-source-differs', observed=observed)
                response = await self.net.rpc(state['origins'][i % 2], int(node), {
                    'op': 'install_if_current', 'expected_generation': profiles[node]['generation'],
                    'expected_support': profiles[node]['support'], 'support': support})
                self._emit('install-returned', node=node, response=response)
                if response is None or response.get('status') == 'unavailable':
                    return self._result('pending', reason='installation-outcome-unknown', node=node)
                if response.get('status') == 'stale':
                    return self._result('pending', reason='owner-profile-changed', node=node,
                                        observed=deepcopy(response.get('observed')))
                if response.get('status') in {'blocked', 'generation-exhausted'}:
                    return self._result('pending', reason=response['status'], node=node,
                                        installation=deepcopy(response))
                if (response.get('status') != 'installed' or
                        response.get('observed') != {'node': int(node),
                                                    'generation': profiles[node]['generation'] + 1,
                                                    'support': support}):
                    raise RolloutStateError('unexpected conditional installation response')
                self._commit(step_index=k + 1, acknowledged_installs=state['acknowledged_installs'] + 1)
                self._emit('installation-recorded', outcome='installed', node=node)
                return self._result('progress', event='installed', node=node)
            if stage == 'release-final':
                problem = await self._target_check()
                if problem is not None:
                    return problem
                token = state['certificates'][str(i)]
                client = self._phase_client(i)
                key = client._record(token)
                retired = key is None or await client.retire(token)
                self._emit('retire-returned', retired=retired, retired_phase=i)
                if not retired:
                    return self._result('pending', reason='final-phase-release-pending')
                self._commit(phase_index=len(state['plan']['phases']), step_index=0,
                             stage='complete', certificates={})
                self._emit('rollout-completed')
                return await self._target_check() or self._result('complete', goal_reached=True)
            raise RolloutStateError('unknown execution stage')

    async def run(self, max_actions=None):
        """Resume until the goal completes, or a pending/deviation result is known.

        No busy retry or timeout-based authority reclamation occurs. The caller
        may heal communication or reopen a failed store and invoke this again.
        """
        limit = 4 * MAX_PHASES + MAX_STEPS + 1 if max_actions is None else max_actions
        if type(limit) is not int or not 1 <= limit <= 4 * MAX_PHASES + MAX_STEPS + 1:
            raise ValueError('invalid rollout action bound')
        for _ in range(limit):
            result = await self.advance()
            if result['status'] != 'progress':
                return result
        return self._result('pending', reason='caller-action-bound')

    def disconnect(self):
        if not self._closed:
            self._closed = True
            for client in self.clients.values():
                client.disconnect()
            self.db.close()
