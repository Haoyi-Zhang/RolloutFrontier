"""TCP/SQLite controls for durable session completion and input boundaries.

Custom string objects exercise the public Python entry point. Socket requests
contain ordinary JSON strings; Python subclasses are never sent over the wire.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
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

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    'src/controller.py', 'src/network.py', 'src/checker.py', 'src/envelope.py',
    'src/factored_planner.py', 'src/factored_runtime.py', 'src/factored_session.py',
    'src/schema_runtime.py', 'src/schema_contracts.py', 'src/application.py',
    'tests/factored_network.py', 'tests/factored_tcp_relay.py',
    'tests/application_network.py', 'tests/multiprocess.py',
    'tests/session_repair_regression.py', 'tests/check_session_repairs.py',
)
BAD_TEXT = ('\ud800', '\udfff', 'left\ud800right', '\ud800\udc00')
GOOD_TEXT = ('plain', 'identity-🧪-中文', '\x00identity', '🧪' * 128)
FLOW = [{'id': 'source', 'owner': 'only', 'parents': []}]
VALUE = {'key': 'record-κ', 'value': 7, 'status': 1}


class CustomString(str):
    def encode(self, *args, **kwargs):
        return b'not-the-contents-of-this-string'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    path.write_text(canonical(value) + '\n')


def rows(path, sql):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        return db.execute(sql).fetchall()


def backup(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def registry():
    probe = next(p for p in actual_probes() if p['family'] == 'enum-alias')
    return {'deployment': 'session-repair-controls', 'owners': {'only': {
        'family': 'enum-alias', 'initial': deepcopy(probe['profiles'][0]),
        'catalog': deepcopy(probe['profiles'])}}}


def owner_state(path):
    return json.loads(rows(path, 'SELECT payload FROM state WHERE id=1')[0][0])


def holds(path):
    return sum(h['status'] == 'held' for h in owner_state(path)['slots'].values())


async def pipeline_completion(directory):
    directory.mkdir()
    net = ApplicationNetwork(directory / 'network', [PROFILES['accepting'] for _ in range(3)])
    client = task = None
    result = {'kind': 'pipeline-completion', 'input': {'key': 'concurrent', 'amount': 17}}
    try:
        net.start()
        client = Client(net, 2)
        codec = ['ACTIVE', 'ACTIVE']
        certificate = (await client.acquire('completion', [pipeline_branch(codec)]))['certificate']
        session = PipelineSession(client, certificate, codec)
        entered, release = asyncio.Event(), asyncio.Event()

        async def pause():
            entered.set()
            await release.wait()

        task = asyncio.create_task(session.request('same-request', result['input'], after_encode=pause))
        await asyncio.wait_for(entered.wait(), 10)
        result['first_completion'] = await session.request('same-request', result['input'])
        backup(net.directory / 'origin-2.sqlite', directory / 'first-completion.sqlite')
        release.set()
        result['later_completion'] = await task
        task = None
        require(result['first_completion'] == result['later_completion'], 'later completion replaced durable output')
        require([r['duplicate'] for r in result['first_completion']['owner_replies']] == [True, False, False],
                'concurrent control did not exercise different owner receipts')
        backup(net.directory / 'origin-2.sqlite', directory / 'later-completion.sqlite')
        result['active_after_completions'] = session._active
        client.disconnect()
        client = None
        net.crash(0)
        client = Client(net, 2)
        session = PipelineSession(client, certificate, codec)
        before = net.issued
        result['reopened_retry'] = await session.request('same-request', result['input'])
        result['cached_retry_rpc_count'] = net.issued - before
        require(result['reopened_retry'] == result['first_completion'] and not result['cached_retry_rpc_count'],
                'reopened exact retry changed or invoked owners')
        result['retired'] = await session.retire()
        result['effects'] = [rows(net.directory / f'process-node-{node}.sqlite',
                                  'SELECT count(*) FROM application_results')[0][0] for node in range(3)]
        result['final_holds'] = [holds(net.directory / f'process-node-{node}.sqlite') for node in range(3)]
        require(result['retired'] and result['effects'] == [1, 1, 1] and result['final_holds'] == [0, 0, 0],
                'completion control did not drain exactly one effect per owner')
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if client is not None:
            client.disconnect()
        net.stop()
        save(directory / 'transport.json', net.trace)
    save(directory / 'observations.json', result)
    return result['kind']


async def pipeline_strings(directory):
    directory.mkdir()
    net = ApplicationNetwork(directory / 'network', [PROFILES['legacy'] for _ in range(3)])
    client = None
    result = {'kind': 'pipeline-strings', 'rejections': [], 'good_requests': [],
              'bad_manifests': [], 'admission_rejections': []}
    codec = ['ACTIVE', 'ACTIVE']
    try:
        net.start()
        client = Client(net, 2)
        certificate = (await client.acquire('valid-🧪-\x00', [pipeline_branch(codec)]))['certificate']
        session = PipelineSession(client, certificate, codec)
        rejected = [('request_id', value, {'key': 'valid', 'amount': 3}, 'builtin-str') for value in BAD_TEXT]
        rejected += [('request_id', CustomString(BAD_TEXT[0]), {'key': 'valid', 'amount': 3}, 'str-subclass'),
                     ('key', 'custom-key', {'key': CustomString(BAD_TEXT[0]), 'amount': 3}, 'str-subclass')]
        for field, request_id, value, kind in rejected:
            before = net.issued
            try:
                await session.request(request_id, value)
            except ValueError as error:
                result['rejections'].append({'field': field, 'input_kind': kind,
                    'codepoints': [ord(c) for c in (request_id if field == 'request_id' else value['key'])],
                    'exception': type(error).__name__, 'message': str(error),
                    'rpc_before': before, 'rpc_after': net.issued})
                require(type(error) is ValueError and before == net.issued, 'text rejected after physical work')
            else:
                raise ValueError('invalid pipeline text acquired a request binding')
        require(client.db.execute('SELECT count(*) FROM application_requests').fetchone() == (0,),
                'invalid pipeline text left a pending row')
        backup(net.directory / 'origin-2.sqlite', directory / 'after-rejections.sqlite')
        for index, request_id in enumerate(GOOD_TEXT):
            value = {'key': 'key-' + str(index), 'amount': index}
            output = await session.request(request_id, value)
            result['good_requests'].append({'request_id': request_id, 'input': value, 'output': output})
        require(await session.retire(), 'legitimate pipeline text did not drain')
        for index, manifest in enumerate((*BAD_TEXT, CustomString(BAD_TEXT[0]))):
            admission = await client.acquire(manifest, [pipeline_branch(codec)])
            if admission['status'] != 'admitted':
                # JSON decoders combine a surrogate pair into one scalar. The
                # lower admission layer therefore rejects the changed binding;
                # no PipelineSession exists for this particular input.
                require(index == 3 and admission == {'status': 'not-justified', 'reasons': []}
                        and not client.state['attempts'], 'unexpected admission rejection')
                result['admission_rejections'].append({'codepoints': [ord(c) for c in manifest],
                    'outcome': admission, 'final_holds': [holds(net.directory /
                        f'process-node-{node}.sqlite') for node in range(3)]})
                continue
            cert = admission['certificate']
            before = client.db.execute('SELECT count(*) FROM application_sessions').fetchone()[0]
            try:
                PipelineSession(client, cert, codec)
            except ValueError as error:
                require(type(error) is ValueError, 'manifest error did not identify invalid input')
                result['bad_manifests'].append({'input_kind': 'str-subclass' if index == 4 else 'builtin-str',
                    'codepoints': [ord(c) for c in manifest], 'exception': type(error).__name__,
                    'session_rows_before': before,
                    'session_rows_after': client.db.execute('SELECT count(*) FROM application_sessions').fetchone()[0],
                    'retired': await client.retire(cert)})
            else:
                raise ValueError('unencodable manifest registered a pipeline session')
        result['effects'] = [rows(net.directory / f'process-node-{node}.sqlite',
                                  'SELECT count(*) FROM application_results')[0][0] for node in range(3)]
        result['final_holds'] = [holds(net.directory / f'process-node-{node}.sqlite') for node in range(3)]
        require(result['effects'] == [4, 4, 4] and result['final_holds'] == [0, 0, 0],
                'string controls changed effect count or left guards')
    finally:
        if client is not None:
            client.disconnect()
        net.stop()
        save(directory / 'transport.json', net.trace)
    save(directory / 'observations.json', result)
    return result['kind']


async def factored_strings(directory):
    directory.mkdir()
    net = PhysicalNetwork(directory / 'network', registry())
    session = None
    result = {'kind': 'factored-strings', 'bad_manifests': [], 'good_manifests': []}
    try:
        net.start()
        for index, manifest in enumerate((*BAD_TEXT, CustomString(BAD_TEXT[0]))):
            journal = directory / ('invalid-' + str(index) + '.sqlite')
            try:
                unexpected = await FactoredSession.begin(net, journal, FLOW, manifest)
            except ValueError as error:
                state_count = rows(journal, 'SELECT count(*) FROM state')[0][0]
                request_count = rows(journal, 'SELECT count(*) FROM requests')[0][0]
                require(not state_count and not request_count and not holds(net.database('only')),
                        'invalid manifest left a durable binding or authority')
                result['bad_manifests'].append({'path': journal.name,
                    'input_kind': 'str-subclass' if index == 4 else 'builtin-str',
                    'codepoints': [ord(c) for c in manifest], 'exception': type(error).__name__,
                    'message': str(error), 'state_count': state_count, 'request_count': request_count,
                    'owner_holds': holds(net.database('only'))})
            else:
                unexpected.disconnect()
                raise ValueError('unencodable factored manifest was admitted')
        for index, manifest in enumerate(GOOD_TEXT):
            journal = directory / ('valid-' + str(index) + '.sqlite')
            session = await FactoredSession.begin(net, journal, FLOW, manifest)
            if index == 0:
                before = net.issued
                try:
                    await session.request('custom-key', dict(VALUE, key=CustomString(BAD_TEXT[0])))
                except ValueError as error:
                    result['custom_key_rejection'] = {'exception': type(error).__name__,
                        'input_kind': 'str-subclass', 'codepoints': [ord(c) for c in BAD_TEXT[0]],
                        'rpc_before': before, 'rpc_after': net.issued,
                        'request_count': session.db.execute('SELECT count(*) FROM requests').fetchone()[0]}
                    require(type(error) is ValueError and before == net.issued and
                            not result['custom_key_rejection']['request_count'], 'subclass bypassed key validation')
                    backup(journal, directory / 'after-custom-key-rejection.sqlite')
                else:
                    raise ValueError('invalid custom key acquired a durable binding')
            output = await session.request('valid-request', VALUE)
            require(output['records'] == {'source': VALUE}, 'valid manifest changed output')
            result['good_manifests'].append({'path': journal.name, 'manifest': manifest,
                                             'output': output, 'retired': await session.close()})
            require(result['good_manifests'][-1]['retired'], 'valid factored text failed to drain')
            session.disconnect()
            session = None
        result['owner_effects'] = rows(net.database('only'), 'SELECT count(*) FROM schema_results')[0][0]
        result['final_holds'] = holds(net.database('only'))
        require(result['owner_effects'] == 4 and not result['final_holds'], 'factored text effect/guard mismatch')
    finally:
        if session is not None:
            session.disconnect()
        net.close()
    save(directory / 'observations.json', result)
    return result['kind']


async def journal_recovery(directory):
    directory.mkdir()
    net = PhysicalNetwork(directory / 'network', registry())
    session = None
    journal = directory / 'session #corrected.sqlite'
    result = {'kind': 'journal-recovery', 'journal': journal.name, 'rejected_journals': []}
    try:
        net.start()
        try:
            await FactoredSession.begin(net, journal, [], 'corrected')
        except ValueError as error:
            result['invalid_workflow'] = {'exception': type(error).__name__, 'message': str(error)}
        else:
            raise ValueError('empty dataflow admitted')
        require(rows(journal, 'SELECT count(*) FROM state') == [(0,)] and
                rows(journal, 'SELECT count(*) FROM requests') == [(0,)], 'failed initial input bound journal')
        backup(journal, directory / 'empty-initialization.sqlite')
        session = await FactoredSession.begin(net, journal, FLOW, 'corrected')
        result['birth_token'] = session.state['birth_token']
        result['first_output'] = await session.request('corrected', VALUE)
        session.disconnect()
        session = None
        net.stop_owner('only', kill=True)
        before = net.issued
        session = await FactoredSession.begin(net, journal, FLOW, 'corrected')
        result['open_reopen_output'] = await session.request('corrected', VALUE)
        result['open_reopen_rpc_count'] = net.issued - before
        require(session.state['birth_token'] == result['birth_token'] and
                result['open_reopen_output'] == result['first_output'] and not result['open_reopen_rpc_count'],
                'normal reopen depended on owner codec selection')
        net.start_owner('only')
        await net.control('target', 'only', port=net.direct_ports['only'])
        result['retired'] = await session.close()
        session.disconnect()
        session = None
        net.stop_owner('only', kill=True)
        before = net.issued
        session = await FactoredSession.begin(net, journal, FLOW, 'corrected')
        result['retired_reopen_output'] = await session.request('corrected', VALUE)
        result['retired_reopen_rpc_count'] = net.issued - before
        require(session.state['stage'] == 'retired' and session.state['birth_token'] == result['birth_token'] and
                result['retired_reopen_output'] == result['first_output'] and
                not result['retired_reopen_rpc_count'] and await session.close(), 'retired offline reopen failed')
        session.disconnect()
        session = None
        net.start_owner('only')
        await net.control('target', 'only', port=net.direct_ports['only'])
        pending_path = directory / 'pending.sqlite'
        session = await FactoredSession.begin(net, pending_path, FLOW, 'preserved')

        async def interrupt_after_effect(step, response):
            raise RuntimeError('caller interrupted after a recorded owner effect')

        try:
            await session.request('pending', VALUE, after_step=interrupt_after_effect)
        except SchemaRequestPending:
            pass
        else:
            raise ValueError('control did not leave the actual committed effect pending')
        require(session.db.execute("SELECT count(*) FROM requests WHERE status='pending'").fetchone() == (1,),
                'control lacks pending durable input')
        pending_birth = session.state['birth_token']
        session.disconnect()
        session = None
        mutations = {
            'lost-state': ['DELETE FROM state'],
            'missing-requests': ['DROP TABLE requests'],
            'null-payload': ["UPDATE state SET payload='null'"],
            'wrong-singleton': ['UPDATE state SET id=2'],
            'extra-state': ['INSERT INTO state SELECT 2,payload FROM state WHERE id=1'],
            'unknown-table': ['CREATE TABLE unrelated(value TEXT)'],
            'wrong-schema': ['ALTER TABLE state ADD COLUMN shadow TEXT'],
        }
        for name, statements in mutations.items():
            target = directory / 'rejected' / (name + '.sqlite')
            backup(pending_path, target)
            with sqlite3.connect(target) as db:
                for statement in statements:
                    db.execute(statement)
            original = directory / 'before-rejection' / target.name
            original.parent.mkdir(exist_ok=True)
            shutil.copyfile(target, original)
            before = net.issued
            state_before = owner_state(net.database('only'))
            try:
                unexpected = await FactoredSession.begin(net, target, FLOW, 'preserved')
            except (ValueError, sqlite3.DatabaseError) as error:
                require(before == net.issued and target.read_bytes() == original.read_bytes() and
                        owner_state(net.database('only')) == state_before, 'damaged journal changed durable authority')
                result['rejected_journals'].append({'name': name, 'exception': type(error).__name__,
                    'message': str(error), 'rpc_before': before, 'rpc_after': net.issued})
            else:
                unexpected.disconnect()
                raise ValueError('damaged journal was reinitialized: ' + name)
        session = FactoredSession(net, pending_path)
        result['pending_recovered'] = await session.request('pending', VALUE)
        require(session.state['birth_token'] == pending_birth and
                result['pending_recovered']['steps']['source']['duplicate'] is True,
                'recovery repeated the retained effect or changed birth')
        result['pending_retired'] = await session.close()
        result['final_holds'] = holds(net.database('only'))
        result['owner_effects'] = rows(net.database('only'), 'SELECT count(*) FROM schema_results')[0][0]
        require(result['retired'] and result['pending_retired'] and not result['final_holds'] and
                result['owner_effects'] == 2, 'journal controls did not drain original effects')
    finally:
        if session is not None:
            session.disconnect()
        net.close()
    save(directory / 'observations.json', result)
    return result['kind']


async def run(directory):
    require(not directory.exists() or not any(directory.iterdir()), 'new evidence directory required')
    directory.mkdir(parents=True, exist_ok=True)
    require(sys.flags.optimize in (0, 1), 'normal and optimized controls only')
    os.environ['PYTHONOPTIMIZE'] = str(sys.flags.optimize)
    source_bytes = {name: (ROOT / name).read_bytes() for name in SOURCE_NAMES}
    for name, content in source_bytes.items():
        destination = directory / 'sources' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    groups = []
    for name, function in (('pipeline-completion', pipeline_completion), ('pipeline-strings', pipeline_strings),
                           ('factored-strings', factored_strings), ('journal-recovery', journal_recovery)):
        groups.append(await function(directory / name))
    require(source_bytes == {name: (ROOT / name).read_bytes() for name in SOURCE_NAMES},
            'executed source changed during session controls')
    summary = {'python': platform.python_version(), 'optimization': sys.flags.optimize,
        'owner_optimization_environment': os.environ['PYTHONOPTIMIZE'],
        'transport': 'separate TCP/SQLite owner processes', 'groups': groups, 'sources': list(SOURCE_NAMES)}
    save(directory / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(canonical(asyncio.run(run(args.output))))
