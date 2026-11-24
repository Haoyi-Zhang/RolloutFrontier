"""Targeted executions against the unmodified delivered implementation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from src.application import PROFILES, PipelineSession, pipeline_branch
from src.controller import canonical
from src.factored_session import FactoredSession, SchemaRequestPending
from src.network import Client
from src.schema_contracts import actual_probes
from tests.application_network import ApplicationNetwork
from tests.factored_network import PhysicalNetwork

ROOT = Path('/workspace/scratch/e34480916f53/completion/project/artifact')
BASE = Path('/workspace/scratch/e34480916f53/finalization/review/runtime/counterexamples')


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n')


def snapshot(database, destination):
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)


def state(database):
    with sqlite3.connect(database) as db:
        return json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])


def registry():
    probe = next(p for p in actual_probes() if p['family'] == 'enum-alias')
    return {'deployment': 'targeted-admission-control', 'owners': {'only': {
        'family': 'enum-alias', 'initial': deepcopy(probe['profiles'][0]),
        'catalog': deepcopy(probe['profiles'])}}}


FLOW = [{'id': 'source', 'owner': 'only', 'parents': []}]
VALUE = {'key': 'well-formed', 'value': 7, 'status': 1}


async def pipeline_concurrent(directory):
    directory.mkdir()
    net = ApplicationNetwork(directory, [PROFILES['accepting'] for _ in range(3)])
    client = None
    task = None
    try:
        net.start()
        client = Client(net, 2)
        answer = await client.acquire('concurrent-result', [pipeline_branch(['ACTIVE', 'ACTIVE'])])
        if answer['status'] != 'admitted':
            raise ValueError('control admission failed')
        session = PipelineSession(client, answer['certificate'], ['ACTIVE', 'ACTIVE'])
        entered, release = asyncio.Event(), asyncio.Event()

        async def pause():
            entered.set()
            await release.wait()

        original = {'key': 'same-logical-request', 'amount': 17}
        task = asyncio.create_task(session.request('request', original, after_encode=pause))
        await asyncio.wait_for(entered.wait(), 10)
        first_completion = await session.request('request', original)
        first_row = json.loads(client.db.execute(
            'SELECT output FROM application_requests WHERE manifest=? AND request_id=?',
            ('concurrent-result', 'request')).fetchone()[0])
        save(directory / 'first-completion.json', first_completion)
        snapshot(directory / 'origin-2.sqlite', directory / 'origin-after-first-completion.sqlite')
        release.set()
        later_completion = await task
        task = None
        later_row = json.loads(client.db.execute(
            'SELECT output FROM application_requests WHERE manifest=? AND request_id=?',
            ('concurrent-result', 'request')).fetchone()[0])
        exact_retry = await session.request('request', original)
        save(directory / 'later-completion.json', later_completion)
        save(directory / 'exact-retry.json', exact_retry)
        snapshot(directory / 'origin-2.sqlite', directory / 'origin-after-later-completion.sqlite')
        retired = await session.retire()
        effects = []
        holds = []
        for node in range(3):
            database = directory / f'process-node-{node}.sqlite'
            with sqlite3.connect(database) as db:
                effects.append(db.execute('SELECT count(*) FROM application_results').fetchone()[0])
            holds.append(sum(h['status'] == 'held' for h in state(database)['slots'].values()))
        result = {
            'actual_tcp_owner_processes': 3,
            'same_input': original,
            'first_completion_was_durable': first_completion == first_row,
            'later_completion_matches_final_row': later_completion == later_row,
            'completed_response_changed': first_completion != later_completion,
            'returned_response_changed_on_exact_retry': first_completion != exact_retry,
            'business_record_preserved': first_completion['record'] == later_completion['record'] == exact_retry['record'],
            'first_duplicate_flags': [r['duplicate'] for r in first_completion['owner_replies']],
            'later_duplicate_flags': [r['duplicate'] for r in later_completion['owner_replies']],
            'effects_per_owner': effects, 'retired': retired, 'final_holds_per_owner': holds,
        }
        if not result['completed_response_changed'] or effects != [1, 1, 1]:
            raise ValueError('expected completion-overwrite counterexample was not observed')
        return result
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if client is not None:
            client.disconnect()
        net.stop()
        save(directory / 'transport.json', net.trace)


async def unencodable_manifest(directory):
    directory.mkdir()
    net = PhysicalNetwork(directory, registry())
    session = None
    try:
        net.start()
        session = await FactoredSession.begin(net, directory / 'session.sqlite', FLOW, 'label-\ud800')
        attempts = []
        for _ in range(2):
            try:
                await session.request('valid-request', VALUE)
            except SchemaRequestPending as error:
                attempts.append({'exception': type(error).__name__, 'message': str(error)})
            else:
                raise ValueError('unencodable manifest unexpectedly executed')
        first_retired = await session.close()
        snapshot(session.path, directory / 'session-before-reopen.sqlite')
        session.disconnect()
        session = FactoredSession(net, directory / 'session.sqlite')
        try:
            await session.request('valid-request', VALUE)
        except SchemaRequestPending as error:
            attempts.append({'exception': type(error).__name__, 'message': str(error)})
        else:
            raise ValueError('reopen unexpectedly repaired the manifest')
        after_retired = await session.close()
        rows = list(session.db.execute('SELECT request_id,input,status,output FROM requests'))
        with sqlite3.connect(net.database('only')) as db:
            effects = db.execute('SELECT count(*) FROM schema_results').fetchone()[0]
            replies = [json.loads(r[0]) for r in db.execute('SELECT response FROM schema_audit')]
        owner_state = state(net.database('only'))
        holds = sum(h['status'] == 'held' for h in owner_state['slots'].values())
        result = {
            'actual_tcp_owner_processes': 1,
            'manifest_code_points': [ord(c) for c in session.state['manifest']],
            'admitted_before_requests': True, 'attempts': attempts,
            'retired_before_reopen': first_retired, 'retired_after_reopen': after_retired,
            'request_rows': rows, 'owner_effects': effects, 'held_guards': holds,
            'invalid_replies': [r for r in replies if r.get('status') == 'invalid'],
        }
        if (first_retired or after_retired or len(rows) != 1 or rows[0][2] != 'pending'
                or effects != 0 or holds != 1):
            raise ValueError('expected manifest pending counterexample was not observed')
        return result
    finally:
        if session is not None:
            session.disconnect()
        net.close()


async def empty_journal_retry(directory):
    directory.mkdir()
    net = PhysicalNetwork(directory, registry())
    session = None
    try:
        net.start()
        journal = directory / 'session.sqlite'
        errors = []
        for flow in ([], FLOW):
            try:
                session = await FactoredSession.begin(net, journal, flow, 'valid-label')
            except Exception as error:
                errors.append({'exception': type(error).__name__, 'message': str(error)})
            else:
                raise ValueError('expected failed begin was not observed')
        with sqlite3.connect(journal) as db:
            empty_state_rows = db.execute('SELECT count(*) FROM state').fetchone()[0]
            requests = db.execute('SELECT count(*) FROM requests').fetchone()[0]
        snapshot(journal, directory / 'empty-journal-after-corrected-begin.sqlite')
        holds_before = sum(h['status'] == 'held' for h in state(net.database('only'))['slots'].values())
        session = FactoredSession(net, journal, workflow=FLOW, manifest='valid-label',
                                  codecs={'only': 'old-name'})
        acquired = await session.acquire()
        output = await session.request('corrected', VALUE)
        retired = await session.close()
        result = {'actual_tcp_owner_processes': 1, 'begin_errors': errors,
                  'state_rows_after_corrected_begin': empty_state_rows,
                  'request_rows_after_corrected_begin': requests,
                  'holds_before_explicit_recovery': holds_before,
                  'explicit_constructor_recovery': acquired and retired and output['records']['source'] == VALUE}
        if empty_state_rows or requests or holds_before or not result['explicit_constructor_recovery']:
            raise ValueError('empty-journal counterexample control differs')
        return result
    finally:
        if session is not None:
            session.disconnect()
        net.close()


async def main():
    BASE.mkdir(parents=True, exist_ok=False)
    names = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'src').glob('*.py'))
    names += ['tests/application_network.py', 'tests/factored_network.py',
              'tests/factored_tcp_relay.py', 'tests/multiprocess.py']
    manifest = {}
    for name in names:
        source = ROOT / name
        target = BASE / 'source-preimages' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copy2(__file__, BASE / 'driver.py')
    save(BASE / 'source-manifest.json', manifest)
    results = {}
    for name, function in (
        ('pipeline-concurrent-completion', pipeline_concurrent),
        ('unencodable-manifest', unencodable_manifest),
        ('empty-journal-retry', empty_journal_retry),
    ):
        results[name] = await function(BASE / name)
        save(BASE / name / 'observations.json', results[name])
    after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    if after != manifest:
        raise ValueError('production source changed during targeted observations')
    save(BASE / 'summary.json', {'status': 'COUNTEREXAMPLES_OBSERVED',
                               'source_unchanged': True, 'cases': results})
    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
