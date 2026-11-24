"""Durable global phase execution over independently named physical owners.

A named physical owner hosts the existing Endpoint under local node identity 0.
One-owner Client views preserve its original admission and retirement protocol.
The global journal binds all views to an immutable deployment registry and a
checked factored plan. No global Cartesian catalog is enumerated by this runtime.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3

from .controller import canonical, initialize_state_table, load_singleton_state, MAX_SEQ, atoms, MAX_CONTRACTS
from .factored_planner import validate_factored_plan
from .network import Client
from .checker import envelope_certificate


class FactoredExecutionError(ValueError):
    pass


class OwnerView:
    """One physical owner in the unchanged protocol's one-node namespace."""
    def __init__(self, network, owner, directory):
        if owner not in network.registry['owners']:
            raise FactoredExecutionError('unknown physical owner')
        self.network, self.owner = network, owner
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.supports = [deepcopy(network.registry['owners'][owner]['initial'])]
        self.window, self.policy = network.window, network.policy

    async def rpc(self, source, target, request, drop=False):
        if target != 0 or type(target) is not int or source != request.get('origin', source):
            raise FactoredExecutionError('one-owner namespace mismatch')
        return await self.network.rpc(self.owner, request, source=source, drop=drop)


def _profile(owner, response):
    if response is None or response.get('status') == 'unavailable':
        return None
    profile = response.get('observed')
    if (not isinstance(profile, dict) or set(profile) != {'node', 'generation', 'support'} or
            type(profile['node']) is not int or profile['node'] != 0 or
            type(profile['generation']) is not int or not 0 <= profile['generation'] <= MAX_SEQ or
            not isinstance(profile['support'], list) or
            atoms(profile['support'], MAX_CONTRACTS) != profile['support']):
        raise FactoredExecutionError('invalid physical owner observation')
    return {'node': owner, 'generation': profile['generation'], 'support': deepcopy(profile['support'])}


class FactoredCoordinator:
    """Single-writer global journal with independently durable owner admissions.

    Create with a planned factored witness and manifest. Reopen with network and
    path after the former writer has stopped. The two rollout origins are private
    to this job at each physical owner. Other application origins remain separate.
    Transport addresses may change after restart; deployment and owner identities
    and their registered catalogs may not.
    """
    def __init__(self, network, path, *, plan=None, manifest=None, observer=None):
        self.net, self.path = network, Path(path)
        self._lock = asyncio.Lock()
        self._failed = self._closed = False
        self._observer = observer
        self.clients = {}
        if observer is not None and not callable(observer):
            raise FactoredExecutionError('observer must be callable')
        if network.policy != 'predicate' or not 1 <= len(network.registry['owners']) <= 1024:
            raise FactoredExecutionError('invalid physical owner registry')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA journal_mode=DELETE')
            initialize_state_table(self.db)
            loaded = load_singleton_state(self.db)
            if loaded is None:
                if not isinstance(manifest, str) or not 1 <= len(manifest) <= 128:
                    raise FactoredExecutionError('new job needs a bounded manifest identity')
                validate_factored_plan(plan)
                if plan.get('status') != 'planned':
                    raise FactoredExecutionError('only a feasible plan can execute')
                self._state = {'schema': 'factored-rollout', 'manifest': manifest,
                    'plan': deepcopy(plan), 'plan_digest': self._digest(plan),
                    'registry': deepcopy(network.registry), 'window': network.window,
                    'phase_index': 0, 'step_index': 0, 'stage': 'acquire' if plan['phases'] else 'complete',
                    'certificates': {}, 'acknowledged_installs': 0, 'reconciled_steps': 0,
                    'journal_sequence': 0}
                self._validate_state(self._state, full=True)
                self._write(self._state)
            else:
                self._validate_state(loaded, full=True)
                self._state = loaded
                if plan is not None and canonical(plan) != canonical(loaded['plan']):
                    raise FactoredExecutionError('reopened plan differs')
                if manifest is not None and manifest != loaded['manifest']:
                    raise FactoredExecutionError('reopened manifest differs')
            self.owners = sorted(self._state['plan']['initial'])
            for index, owner in enumerate(self.owners):
                # Sequence floors belong to this physical deployment and origin,
                # so a later fully retired job must reuse the same allocator.
                directory = Path(network.directory) / 'rollout-origins' / f'owner-{index:04d}'
                view = OwnerView(network, owner, directory)
                for origin in (0, 1):
                    self.clients[owner, origin] = Client(view, origin)
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

    def _phase_manifest(self, index, state=None):
        state = self._state if state is None else state
        return state['manifest'] + ':plan:' + state['plan_digest'] + ':phase:' + str(index)

    def _validate_state(self, state, *, full=False):
        expected = {'schema', 'manifest', 'plan', 'plan_digest', 'registry', 'window',
                    'phase_index', 'step_index', 'stage', 'certificates',
                    'acknowledged_installs', 'reconciled_steps', 'journal_sequence'}
        if not isinstance(state, dict) or set(state) != expected or state['schema'] != 'factored-rollout':
            raise FactoredExecutionError('invalid global journal schema')
        if not isinstance(state['manifest'], str) or not 1 <= len(state['manifest']) <= 128:
            raise FactoredExecutionError('invalid durable manifest')
        if canonical(state['registry']) != canonical(self.net.registry) or state['window'] != self.net.window:
            raise FactoredExecutionError('physical owner registry changed')
        plan = state['plan']
        if full:
            validate_factored_plan(plan)
        if plan.get('status') != 'planned' or self._digest(plan) != state['plan_digest']:
            raise FactoredExecutionError('durable plan changed')
        owners = sorted(plan['initial'])
        if owners != sorted(self.net.registry['owners']):
            raise FactoredExecutionError('plan and physical owner placement differ')
        for owner in owners:
            registered = self.net.registry['owners'][owner]
            if (plan['initial'][owner] not in registered['catalog'] or
                    registered['initial'] not in registered['catalog'] or
                    canonical(registered['catalog']) != canonical(plan['catalog'][owner])):
                raise FactoredExecutionError('registered physical catalog differs')
        i, step, stage = state['phase_index'], state['step_index'], state['stage']
        phases = plan['phases']
        if (type(i) is not int or type(step) is not int or not 0 <= i <= len(phases) or step < 0 or
                stage not in {'acquire', 'release-old', 'install', 'release-final', 'complete'}):
            raise FactoredExecutionError('invalid global journal position')
        if stage == 'complete':
            if i != len(phases) or step or state['certificates']:
                raise FactoredExecutionError('invalid completed global journal')
            expected_writes = plan['cost']['installations']
            expected_certificates = set()
        else:
            if i >= len(phases) or step > len(phases[i]['steps']):
                raise FactoredExecutionError('global journal position outside plan')
            if stage in {'acquire', 'release-old'} and step:
                raise FactoredExecutionError('phase handoff has installation credits')
            if stage == 'release-old' and i == 0:
                raise FactoredExecutionError('first phase has no predecessor')
            if stage == 'release-final' and (i != len(phases)-1 or step != len(phases[i]['steps'])):
                raise FactoredExecutionError('invalid final retirement position')
            expected_writes = sum(len(p['steps']) for p in phases[:i]) + step
            if stage == 'acquire': expected_certificates = {str(i-1)} if i else set()
            elif stage == 'release-old': expected_certificates = {str(i-1), str(i)}
            else: expected_certificates = {str(i)}
        certs = state['certificates']
        if not isinstance(certs, dict) or set(certs) != expected_certificates:
            raise FactoredExecutionError('global phase roles differ')
        for text, owner_certs in certs.items():
            phase_index = int(text)
            if not isinstance(owner_certs, dict) or sorted(owner_certs) != owners:
                raise FactoredExecutionError('incomplete global phase authority')
            for owner, cert in owner_certs.items():
                if (not isinstance(cert, dict) or cert.get('manifest') != self._phase_manifest(phase_index, state) or
                        cert.get('origin') != phase_index % 2 or
                        cert.get('box') != {'0': phases[phase_index]['box'][owner]} or
                        not envelope_certificate(cert, [{'0': term} for term in phases[phase_index]['box'][owner]])):
                    raise FactoredExecutionError('local certificate differs from global role')
        for field in ('acknowledged_installs', 'reconciled_steps', 'journal_sequence'):
            if type(state[field]) is not int or not 0 <= state[field] <= MAX_SEQ:
                raise FactoredExecutionError('invalid global journal counter')
        if state['acknowledged_installs'] + state['reconciled_steps'] != expected_writes:
            raise FactoredExecutionError('installation accounting differs from journal position')

    @property
    def state(self):
        return deepcopy(self._state)

    @property
    def plan(self):
        return deepcopy(self._state['plan'])

    def _healthy(self):
        if self._closed or self._failed:
            raise sqlite3.DatabaseError('global journal must be reopened')

    def _write(self, state):
        self._healthy()
        try:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO state VALUES(1,?)', (canonical(state),))
        except sqlite3.DatabaseError:
            self._failed = True
            raise

    def _commit(self, **changes):
        self._healthy()
        next_state = deepcopy(self._state)
        next_state.update(deepcopy(changes))
        if next_state['journal_sequence'] == MAX_SEQ:
            raise FactoredExecutionError('journal sequence exhausted')
        next_state['journal_sequence'] += 1
        self._validate_state(next_state)
        self._write(next_state)
        self._state = next_state

    def _emit(self, event, **details):
        if self._observer is not None:
            self._observer({'event': event, 'phase_index': self._state['phase_index'],
                            'step_index': self._state['step_index'], **deepcopy(details)})

    def _check_origin_ownership(self):
        i, stage = self._state['phase_index'], self._state['stage']
        allowed = set(self._state['certificates'])
        if stage == 'acquire': allowed.add(str(i))
        manifests = {self._phase_manifest(int(index)): int(index) for index in allowed}
        for (owner, origin), client in self.clients.items():
            for record in client.state['attempts'].values():
                phase = manifests.get(record['manifest'])
                if phase is None or phase % 2 != origin:
                    raise FactoredExecutionError('rollout origin contains foreign authority')
                if 'certificate' in record:
                    cert = record['certificate']
                    expected_box = {'0': self._state['plan']['phases'][phase]['box'][owner]}
                    if canonical(cert.get('box')) != canonical(expected_box):
                        raise FactoredExecutionError('local guard differs from plan')
                    published = self._state['certificates'].get(str(phase), {}).get(owner)
                    if published is not None and canonical(cert) != canonical(published):
                        raise FactoredExecutionError('global and local certificate pointers differ')
                    if published is None and not (stage == 'acquire' and phase == i):
                        raise FactoredExecutionError('unpublished local authority outside acquisition')

    def _require_committed(self, i):
        certs = self._state['certificates'].get(str(i), {})
        if sorted(certs) != self.owners:
            raise FactoredExecutionError('phase not globally admitted')
        for owner, cert in certs.items():
            client = self.clients[owner, i % 2]
            key = client._record(cert)
            if key is None or client.state['attempts'][key]['status'] != 'committed':
                raise FactoredExecutionError('local phase authority is not committed')

    async def _profiles(self):
        result = {}
        for owner in self.owners:
            response = await self.net.rpc(owner, {'op': 'read'}, source=0)
            value = _profile(owner, response)
            if value is None:
                return None
            result[owner] = value
        return result

    async def _target_check(self):
        first = await self._profiles()
        if first is None:
            return {'status': 'pending', 'reason': 'owner-unreachable'}
        second = await self._profiles()
        if second is None:
            return {'status': 'pending', 'reason': 'owner-unreachable'}
        if first != second:
            return {'status': 'pending', 'reason': 'target-observation-changed'}
        if {n:p['support'] for n,p in first.items()} != self._state['plan']['target']:
            return {'status': 'deviation', 'reason': 'observed-target-differs', 'observed': second}
        return {'status': 'target-observed', 'observation': {'first': first, 'second': second}}

    def _result(self, status, **details):
        return {'status': status, 'phase_index': self._state['phase_index'],
                'step_index': self._state['step_index'],
                'acknowledged_installs': self._state['acknowledged_installs'],
                'reconciled_steps': self._state['reconciled_steps'], **deepcopy(details)}

    async def advance(self):
        async with self._lock:
            self._healthy()
            self._check_origin_ownership()
            state = self._state
            i, k, stage = state['phase_index'], state['step_index'], state['stage']
            if stage == 'complete':
                observed = await self._target_check()
                if observed['status'] != 'target-observed': return observed
                return self._result('complete', goal_reached=True, target_observation=observed['observation'])
            phase = state['plan']['phases'][i]
            if stage == 'acquire':
                profiles = await self._profiles()
                if profiles is None: return self._result('pending', reason='owner-unreachable')
                if {n:p['support'] for n,p in profiles.items()} != phase['source']:
                    return self._result('deviation', reason='phase-source-differs', observed=profiles)
                acquired = {}
                for owner in self.owners:
                    guard = phase['box'][owner]
                    answer = await self.clients[owner, i % 2].acquire_box(
                        self._phase_manifest(i), [{'0': term} for term in guard], {'0': guard})
                    self._emit('acquire-returned', owner=owner, response=answer)
                    if answer['status'] != 'admitted':
                        return self._result('pending', reason='phase-admission-pending', owner=owner)
                    acquired[owner] = answer['certificate']
                certs = deepcopy(state['certificates'])
                certs[str(i)] = acquired
                self._commit(certificates=certs, stage='release-old' if i else 'install')
                self._emit('phase-recorded')
                return self._result('progress', event='phase-admitted')
            if stage == 'release-old':
                self._require_committed(i)
                for owner, cert in state['certificates'][str(i-1)].items():
                    client = self.clients[owner, (i-1) % 2]
                    retired = client._record(cert) is None or await client.retire(cert)
                    self._emit('retire-returned', owner=owner, retired=retired, retired_phase=i-1)
                    if not retired:
                        return self._result('pending', reason='old-phase-release-pending', owner=owner)
                self._commit(certificates={str(i): state['certificates'][str(i)]}, stage='install')
                self._emit('old-phase-released')
                return self._result('progress', event='old-phase-released')
            if stage == 'install':
                self._require_committed(i)
                if k == len(phase['steps']):
                    profiles = await self._profiles()
                    if profiles is None: return self._result('pending', reason='owner-unreachable')
                    if {n:p['support'] for n,p in profiles.items()} != phase['target']:
                        return self._result('deviation', reason='phase-endpoint-differs', observed=profiles)
                    if i+1 == len(state['plan']['phases']): self._commit(stage='release-final')
                    else: self._commit(phase_index=i+1, step_index=0, stage='acquire')
                    self._emit('phase-completed', completed_phase=i)
                    return self._result('progress', event='phase-completed')
                step = phase['steps'][k]
                owner, support = step['node'], step['support']
                expected = phase['source'][owner]
                for earlier in phase['steps'][:k]:
                    if earlier['node'] == owner: expected = earlier['support']
                response = await self.net.rpc(owner, {'op': 'read'}, source=i % 2)
                profile = _profile(owner, response)
                if profile is None: return self._result('pending', reason='owner-unreachable', owner=owner)
                if profile['support'] == support:
                    self._commit(step_index=k+1, reconciled_steps=state['reconciled_steps']+1)
                    self._emit('installation-recorded', owner=owner, outcome='already-target')
                    return self._result('progress', event='already-target', owner=owner)
                if profile['support'] != expected:
                    return self._result('deviation', reason='planned-source-differs', owner=owner, observed=profile)
                response = await self.net.rpc(owner, {'op': 'install_if_current',
                    'expected_generation': profile['generation'], 'expected_support': profile['support'],
                    'support': support}, source=i % 2)
                self._emit('install-returned', owner=owner, response=response)
                if response is None or response.get('status') == 'unavailable':
                    return self._result('pending', reason='installation-outcome-unknown', owner=owner)
                if response.get('status') in {'stale', 'blocked', 'generation-exhausted'}:
                    return self._result('pending', reason=response['status'], owner=owner, installation=response)
                after = _profile(owner, response)
                if response.get('status') != 'installed' or after != {
                        'node': owner, 'generation': profile['generation']+1, 'support': support}:
                    raise FactoredExecutionError('unexpected conditional installation response')
                self._commit(step_index=k+1, acknowledged_installs=state['acknowledged_installs']+1)
                self._emit('installation-recorded', owner=owner, outcome='installed')
                return self._result('progress', event='installed', owner=owner)
            if stage == 'release-final':
                observed = await self._target_check()
                if observed['status'] != 'target-observed': return observed
                for owner, cert in state['certificates'][str(i)].items():
                    client = self.clients[owner, i % 2]
                    retired = client._record(cert) is None or await client.retire(cert)
                    self._emit('retire-returned', owner=owner, retired=retired, retired_phase=i)
                    if not retired:
                        return self._result('pending', reason='final-phase-release-pending', owner=owner)
                self._commit(phase_index=len(state['plan']['phases']), step_index=0,
                             stage='complete', certificates={})
                self._emit('rollout-completed')
                observed = await self._target_check()
                if observed['status'] != 'target-observed': return observed
                return self._result('complete', goal_reached=True, target_observation=observed['observation'])
            raise FactoredExecutionError('unknown global stage')

    async def run(self, max_actions=100000):
        if type(max_actions) is not int or not 1 <= max_actions <= 1000000:
            raise ValueError('invalid action bound')
        for _ in range(max_actions):
            result = await self.advance()
            if result['status'] != 'progress': return result
        return self._result('pending', reason='caller-action-bound')

    def disconnect(self):
        if not self._closed:
            self._closed = True
            for client in self.clients.values(): client.disconnect()
            self.db.close()
