"""Executable controls for session birth identity and cancellation recovery.

Every owner transition uses the production Endpoint, SQLite and ProtoJSON code.
The adapter can withhold a response or suspend a task after an actual committed
operation; it does not claim a socket or operating-system process failure.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import sys

from google.protobuf import __version__ as protobuf_version

from src.controller import canonical
from src.factored_runtime import FactoredExecutionError
from src.factored_session import FactoredSession, SchemaRequestPending
from src.schema_contracts import actual_probes
from src.schema_runtime import SchemaEndpoint, identity_for

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    'src/controller.py', 'src/network.py', 'src/checker.py', 'src/envelope.py',
    'src/factored_planner.py', 'src/factored_runtime.py', 'src/factored_session.py',
    'src/schema_runtime.py', 'src/schema_contracts.py',
    'tests/session_identity_regression.py',
)
FLOW = [
    {'id': 'source', 'owner': 'a', 'parents': []},
    {'id': 'sink', 'owner': 'b', 'parents': ['source']},
]
CYCLE = [
    {'id': 'source', 'owner': 'a', 'parents': []},
    {'id': 'middle', 'owner': 'b', 'parents': ['source']},
    {'id': 'sink', 'owner': 'a', 'parents': ['middle']},
]
REVERSED_CYCLE = [
    {'id': 'source', 'owner': 'b', 'parents': []},
    {'id': 'middle', 'owner': 'a', 'parents': ['source']},
    {'id': 'sink', 'owner': 'b', 'parents': ['middle']},
]
VALUE = {'key': 'retained-κ', 'value': 17, 'status': 1}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class DirectOwners:
    """Transport adapter; production owner handlers perform every state change."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.window, self.policy = 8, 'predicate'
        probe = next(p for p in actual_probes() if p['family'] == 'enum-alias')
        self.registry = {'deployment': 'session-identity-control', 'owners': {
            owner: {'family': 'enum-alias', 'initial': deepcopy(probe['profiles'][0]),
                    'catalog': deepcopy(probe['profiles'])}
            for owner in ('a', 'b')}}
        self.endpoints = {owner: SchemaEndpoint(identity_for(self.registry, owner),
                         self.directory / (owner + '.sqlite')) for owner in ('a', 'b')}
        self.drop_effect_reply = False
        self.pause_operation = None
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.trace = []

    async def rpc(self, owner, request, source=0, drop=False):
        require(not drop, 'unexpected transport drop argument')
        reply = self.endpoints[owner].handle(deepcopy(request))
        event = {'owner': owner, 'source': source, 'request': deepcopy(request),
                 'response': deepcopy(reply), 'owner_order': self.endpoints[owner].last_audit,
                 'response_disposition': 'returned'}
        self.trace.append(event)
        if self.drop_effect_reply and request.get('op') == 'schema' and reply.get('status') == 'applied':
            self.drop_effect_reply = False
            event['response_disposition'] = 'withheld-after-commit'
            return None
        if request.get('op') == self.pause_operation:
            self.pause_operation = None
            event['response_disposition'] = 'paused-after-commit'
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                event['response_disposition'] = 'cancelled-after-commit'
                raise
            event['response_disposition'] = 'returned-after-pause'
        return reply

    def effects(self):
        return sum(ep.db.execute('SELECT count(*) FROM schema_results').fetchone()[0]
                   for ep in self.endpoints.values())

    def holds(self):
        return sum(slot['status'] == 'held' for ep in self.endpoints.values()
                   for slot in ep.state['slots'].values())

    def snapshot(self):
        return {'owners': {name: deepcopy(ep.state) for name, ep in self.endpoints.items()},
                'effects': self.effects()}

    def close(self):
        (self.directory / 'operations.json').write_text(json.dumps(self.trace, indent=2) + '\n')
        for endpoint in self.endpoints.values():
            endpoint.disconnect()


def new_idle(owners, path, label, workflow=FLOW):
    return FactoredSession(owners, path, workflow=workflow, manifest=label,
                           codecs={'a': 'old-name', 'b': 'old-name'})


async def leave_pending(session, owners):
    owners.drop_effect_reply = True
    try:
        await session.request('retained-request', VALUE)
    except SchemaRequestPending:
        pass
    else:
        raise ValueError('withheld effect response did not leave a pending request')
    require(owners.effects() == 1 and owners.holds() == 2, 'pending owner state differs')
    require(not await session.close(), 'pending session was retired')
    require(session.db.execute("SELECT count(*) FROM requests WHERE status='pending'").fetchone()[0] == 1,
            'pending input binding is absent')
    return deepcopy(session.state)


async def rejected_begin(owners, path, label, workflow=FLOW):
    before = owners.snapshot()
    try:
        unexpected = await FactoredSession.begin(owners, path, workflow, label)
    except FactoredExecutionError as error:
        require('foreign authority' in str(error), 'unexpected rejection reason: ' + str(error))
    else:
        unexpected.disconnect()
        raise ValueError('unrelated journal adopted active session authority')
    require(owners.snapshot() == before, 'rejected journal changed owner state or effects')


async def recover_pending(owners, path, previous, workflow=FLOW):
    session = FactoredSession(owners, path)
    try:
        require(session.state['birth_token'] == previous['birth_token'], 'reopen changed session birth')
        require(session.state['certificates'] == previous['certificates'], 'reopen changed retained admission')
        output = await session.request('retained-request', VALUE)
        require(output['records']['sink'] == VALUE, 'recovery changed semantic output')
        require(output['steps']['source']['duplicate'] is True, 'recovery repeated the committed source effect')
        require(owners.effects() == len(workflow), 'unexpected recovered effect count')
        require(await session.close() and owners.holds() == 0, 'recovered session did not drain')
        require(session.db.execute("SELECT count(*) FROM requests WHERE status='pending'").fetchone()[0] == 0,
                'recovered request remains pending')
    finally:
        session.disconnect()


async def fresh_and_repeated_journal(directory):
    owners = DirectOwners(directory)
    label = 'm' * 128
    old = await FactoredSession.begin(owners, directory / 'active.sqlite', FLOW, label)
    previous = await leave_pending(old, owners)
    admission = FactoredSession._admission_manifest(previous)
    require(len(admission) == 201 and admission.startswith(label + ':session:'), 'admission label bound')
    old.disconnect()
    try:
        rejected = directory / 'unrelated.sqlite'
        await rejected_begin(owners, rejected, label)
        await rejected_begin(owners, rejected, label)
        with sqlite3.connect(rejected) as db:
            unrelated = json.loads(db.execute('SELECT payload FROM state').fetchone()[0])
        require(unrelated['birth_token'] != previous['birth_token'], 'fresh journals share a birth token')
        await recover_pending(owners, directory / 'active.sqlite', previous)
        later = await FactoredSession.begin(owners, rejected, FLOW, label)
        try:
            require(later.state['birth_token'] == unrelated['birth_token'], 'rejected journal lost its own birth')
            require(all(later.state['certificates'][o]['sequences']['0'] > previous['certificates'][o]['sequences']['0']
                        for o in ('a', 'b')), 'later admission reused a retired sequence')
            changed = {'key': 'later', 'value': 29, 'status': 1}
            output = await later.request('retained-request', changed)
            require(output['records']['sink'] == changed, 'later session aliased earlier effects')
            require(owners.effects() == 4 and await later.close() and owners.holds() == 0,
                    'later session did not complete independently')
        finally:
            later.disconnect()
        return {'foreign_journal_rejections': 2, 'pending_holds_preserved': 2,
                'old_exact_retry_recovered': True, 'fresh_births_distinct': True,
                'later_same_label_and_request_id': 'independent-completion',
                'admission_manifest_characters_at_label_limit': len(admission),
                'final_effects': 4, 'final_holds': 0}
    finally:
        owners.close()


async def precreated_journal(directory):
    owners = DirectOwners(directory)
    idle = new_idle(owners, directory / 'precreated.sqlite', 'same-label')
    birth = idle.state['birth_token']
    require(owners.holds() == 0, 'idle session unexpectedly acquired owner authority')
    idle.disconnect()
    active = await FactoredSession.begin(owners, directory / 'active.sqlite', FLOW, 'same-label')
    previous = await leave_pending(active, owners)
    active.disconnect()
    try:
        require(birth != previous['birth_token'], 'precreated and active births coincide')
        await rejected_begin(owners, directory / 'precreated.sqlite', 'same-label')
        await recover_pending(owners, directory / 'active.sqlite', previous)
        idle = await FactoredSession.begin(owners, directory / 'precreated.sqlite', FLOW, 'same-label')
        try:
            require(idle.state['birth_token'] == birth, 'precreated birth changed on legitimate admission')
            require(await idle.close() and owners.holds() == 0, 'precreated session failed after prior drain')
        finally:
            idle.disconnect()
        return {'created_before_other_session': True, 'foreign_journal_rejections': 1,
                'old_exact_retry_recovered': True, 'precreated_birth_preserved': True,
                'admitted_after_previous_drain': True, 'final_effects': 2, 'final_holds': 0}
    finally:
        owners.close()


async def workflow_binding(directory):
    owners = DirectOwners(directory)
    active = await FactoredSession.begin(owners, directory / 'active.sqlite', CYCLE, 'same-label')
    previous = await leave_pending(active, owners)
    active.disconnect()
    try:
        changed = deepcopy(previous)
        changed['workflow'] = deepcopy(REVERSED_CYCLE)
        require(FactoredSession._requirements(changed) == FactoredSession._requirements(previous),
                'workflow control does not preserve the local obligation shapes')
        await rejected_begin(owners, directory / 'different-workflow.sqlite', 'same-label', REVERSED_CYCLE)
        corruptions = (
            ('workflow', deepcopy(REVERSED_CYCLE)),
            ('manifest', 'different-readable-label'),
            ('birth_token', '0' * 32),
            ('birth_token', 'invalid-token'),
        )
        before = owners.snapshot()
        for index, (field, value) in enumerate(corruptions):
            target = directory / ('changed-' + str(index) + '.sqlite')
            shutil.copy2(directory / 'active.sqlite', target)
            altered = deepcopy(previous)
            altered[field] = value
            with sqlite3.connect(target) as db:
                db.execute('UPDATE state SET payload=? WHERE id=1', (canonical(altered),))
            try:
                unexpected = FactoredSession(owners, target)
            except FactoredExecutionError:
                pass
            else:
                unexpected.disconnect()
                raise ValueError('changed immutable session binding was accepted')
            require(owners.snapshot() == before, 'changed journal touched owner state')
        await recover_pending(owners, directory / 'active.sqlite', previous, CYCLE)
        return {'different_workflow_same_obligations': 'rejected',
                'altered_journal_controls_rejected': len(corruptions),
                'old_exact_retry_recovered': True, 'final_effects': 3, 'final_holds': 0}
    finally:
        owners.close()


async def cancel_at_commit(task, owners):
    await asyncio.wait_for(owners.entered.wait(), 5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    raise ValueError('task did not propagate cancellation')


async def acquisition_cancellation(directory):
    owners = DirectOwners(directory)
    session = new_idle(owners, directory / 'session.sqlite', 'acquisition-cut')
    birth = session.state['birth_token']
    owners.pause_operation = 'prepare'
    task = asyncio.create_task(session.acquire())
    await cancel_at_commit(task, owners)
    require(session.state['stage'] == 'acquiring' and owners.holds() == 1, 'partial acquisition differs')
    with sqlite3.connect(directory / 'session.sqlite') as db:
        saved = json.loads(db.execute('SELECT payload FROM state').fetchone()[0])
    require(saved['birth_token'] == birth, 'birth was not durable before owner prepare')
    session.disconnect()
    try:
        session = FactoredSession(owners, directory / 'session.sqlite')
        try:
            require(session.state['birth_token'] == birth and await session.acquire(), 'partial admission did not resume')
            require(session.state['certificates']['a']['sequences']['0'] == 2, 'interrupted sequence was reused')
            require(owners.holds() == 2, 'resumed admission lacks both holds')
            output = await session.request('retained-request', VALUE)
            require(output['records']['sink'] == VALUE, 'resumed session output differs')
            require(await session.close() and owners.holds() == 0, 'resumed acquisition did not drain')
        finally:
            session.disconnect()
        return {'birth_durable_before_prepare': True, 'holds_at_cut': 1,
                'same_birth_on_reopen': True, 'recovered_owner_a_sequence': 2,
                'final_effects': 2, 'final_holds': 0}
    finally:
        owners.close()


async def request_cancellation(directory):
    owners = DirectOwners(directory)
    session = await FactoredSession.begin(owners, directory / 'session.sqlite', FLOW, 'request-cut')
    owners.pause_operation = 'schema'
    task = asyncio.create_task(session.request('retained-request', VALUE))
    await cancel_at_commit(task, owners)
    require(session._active == 0 and owners.effects() == 1 and owners.holds() == 2, 'cancelled request state differs')
    require(not await session.close(), 'cancelled pending request lost authority')
    previous = session.state
    session.disconnect()
    try:
        await recover_pending(owners, directory / 'session.sqlite', previous)
        return {'effects_at_cut': 1, 'pending_holds_preserved': 2,
                'active_tasks_after_cancellation': 0, 'exact_retry_recovered': True,
                'final_effects': 2, 'final_holds': 0}
    finally:
        owners.close()


async def retirement_cancellation(directory):
    owners = DirectOwners(directory)
    session = await FactoredSession.begin(owners, directory / 'session.sqlite', FLOW, 'retirement-cut')
    birth = session.state['birth_token']
    owners.pause_operation = 'close'
    task = asyncio.create_task(session.close())
    await cancel_at_commit(task, owners)
    require(session.state['stage'] == 'closing' and owners.holds() == 1, 'partial retirement differs')
    session.disconnect()
    try:
        session = FactoredSession(owners, directory / 'session.sqlite')
        try:
            require(session.state['birth_token'] == birth, 'retirement recovery changed birth')
            require(await session.close() and owners.holds() == 0, 'retirement did not resume')
        finally:
            session.disconnect()
        return {'holds_at_cut': 1, 'same_birth_on_reopen': True,
                'final_effects': 0, 'final_holds': 0}
    finally:
        owners.close()


async def run(directory):
    controls = {}
    for name, operation in (
        ('fresh_and_repeated_journal', fresh_and_repeated_journal),
        ('precreated_journal', precreated_journal),
        ('workflow_binding', workflow_binding),
        ('acquisition_cancellation', acquisition_cancellation),
        ('request_cancellation', request_cancellation),
        ('retirement_cancellation', retirement_cancellation),
    ):
        path = directory / name
        path.mkdir()
        controls[name] = await operation(path)
    return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New directory for records, owner databases and captured sources.')
    args = parser.parse_args()
    sources = {name: (ROOT / name).read_bytes() for name in SOURCE_NAMES}
    args.out.mkdir(parents=True, exist_ok=False)
    controls = asyncio.run(run(args.out))
    require(sources == {name: (ROOT / name).read_bytes() for name in SOURCE_NAMES}, 'executed source changed during controls')
    for name, data in sources.items():
        target = args.out / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    result = {'status': 'pass', 'scope': 'actual in-process Endpoint, SQLite and ProtoJSON; task/response cuts after committed operations',
              'controls': controls, 'control_groups': len(controls),
              'runtime': {'python': sys.version, 'optimized': sys.flags.optimize,
                          'protobuf': protobuf_version, 'platform': platform.platform()},
              'source_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}}
    (args.out / 'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': 'pass', 'control_groups': len(controls), 'output': str(args.out), 'optimized': sys.flags.optimize}))


if __name__ == '__main__':
    main()
