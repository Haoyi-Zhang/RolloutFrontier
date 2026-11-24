"""Targeted, pre-repair executions of the remaining SQLite text boundaries."""
from __future__ import annotations
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3

from src.application import PROFILES, PipelineSession, pipeline_branch
from src.controller import canonical
from src.effect_ledger import EffectLedger
from src.factored_session import FactoredSession, SchemaRequestPending
from src.network import Client
from src.schema_contracts import actual_probes
from src.schema_runtime import SchemaEndpoint, identity_for
from tests.application_network import ApplicationNetwork
from tests.factored_network import PhysicalNetwork

BASE = Path('/workspace/scratch/e34480916f53/finalization/review/runtime/string-boundaries')
BAD = '\ud800'
GOOD = 'text-🧪-\x00'

class EncodableSubclass(str):
    def encode(self, *args, **kwargs):
        return b'claimed-to-be-encodable'

def save(path, value):
    path.write_text(canonical(value) + '\n')

def registry(owner='only', deployment='strings'):
    probe = next(p for p in actual_probes() if p['family'] == 'enum-alias')
    return {'deployment': deployment, 'owners': {owner: {
        'family': 'enum-alias', 'initial': deepcopy(probe['profiles'][0]),
        'catalog': deepcopy(probe['profiles'])}}}

def query(path, sql):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return db.execute(sql).fetchall()

async def pipeline(directory):
    directory.mkdir()
    net = ApplicationNetwork(directory, [PROFILES['legacy'] for _ in range(3)])
    client = None
    result = {}
    try:
        net.start()
        client = Client(net, 2)
        codec = ['ACTIVE', 'ACTIVE']
        cert = (await client.acquire('string-fields', [pipeline_branch(codec)]))['certificate']
        session = PipelineSession(client, cert, codec)
        before = net.issued
        try:
            await session.request(BAD, {'key': 'valid', 'amount': 1})
        except ValueError as error:
            result['invalid_request_id'] = {'error': type(error).__name__,
                'rows': list(client.db.execute('SELECT * FROM application_requests')),
                'issued_before': before, 'issued_after': net.issued}
        else:
            raise ValueError('invalid request ID unexpectedly succeeded')
        out = await session.request(GOOD, {'key': 'valid', 'amount': 1})
        result['valid_request_id'] = {'returned': out, 'retired': await session.retire()}
        cert = (await client.acquire('manifest-' + BAD, [pipeline_branch(codec)]))['certificate']
        try:
            PipelineSession(client, cert, codec)
        except ValueError as error:
            result['invalid_pipeline_manifest'] = {'error': type(error).__name__,
                'retired': await client.retire(cert)}
        else:
            raise ValueError('invalid manifest unexpectedly constructed session')
        cert = (await client.acquire('subclass-key', [pipeline_branch(codec)]))['certificate']
        session = PipelineSession(client, cert, codec)
        try:
            await session.request('subclass', {'key': EncodableSubclass(BAD), 'amount': 1})
        except Exception as error:
            result['subclass_key'] = {'error': type(error).__name__, 'message': str(error),
                'rows': list(client.db.execute("SELECT request_id,status FROM application_requests WHERE manifest='subclass-key'")),
                'retired': await session.retire()}
        else:
            raise ValueError('invalid subclass key unexpectedly executed')
        result['final_owner_results'] = [query(directory / f'process-node-{node}.sqlite',
            'SELECT request_id FROM application_results') for node in range(3)]
    finally:
        if client is not None: client.disconnect()
        net.stop()
        save(directory / 'transport.json', net.trace)
    return result

async def factored(directory):
    directory.mkdir()
    net = PhysicalNetwork(directory, registry())
    session = None
    try:
        net.start()
        flow = [{'id': 'source', 'owner': 'only', 'parents': []}]
        session = await FactoredSession.begin(net, directory / 'session.sqlite', flow, 'subclass-key')
        try:
            await session.request('subclass', {'key': EncodableSubclass(BAD), 'value': 1, 'status': 1})
        except Exception as error:
            return {'subclass_key': {'error': type(error).__name__, 'message': str(error),
                'rows': list(session.db.execute('SELECT request_id,status FROM requests')),
                'retired': await session.close()},
                'owner_effects': query(net.database('only'), 'SELECT count(*) FROM schema_results')}
        raise ValueError('invalid subclass key unexpectedly executed')
    finally:
        if session is not None: session.disconnect()
        net.close()

def direct_schema(directory):
    directory.mkdir()
    result = {}
    for index, label in enumerate((BAD, GOOD)):
        reg = registry(owner='owner-' + label, deployment='deployment-' + label)
        identity = identity_for(reg, 'owner-' + label)
        ep = SchemaEndpoint(identity, directory / f'owner-{index}.sqlite')
        try:
            for sequence, manifest in enumerate(('valid', 'manifest-' + BAD), 1):
                prepared = ep.prepare(2, sequence, manifest, ['emit:old-name'])
                if prepared.get('status') != 'held': raise ValueError(prepared)
                for request_id in (BAD, GOOD):
                    response = ep.handle({'op': 'schema', 'origin': 2, 'sequence': sequence,
                        'manifest': manifest, 'request_id': request_id,
                        'input_classes': [], 'emit_class': 'old-name', 'inputs': [],
                        'seed': {'key': 'valid', 'value': 1, 'status': 1}})
                    result[f'{index}-{sequence}-{request_id == GOOD}'] = {
                        'manifest': manifest, 'request_id': request_id, 'response': response,
                        'effects': ep.db.execute('SELECT count(*) FROM schema_results').fetchone()[0]}
                ep.close(2, sequence)
            result[f'identity-{index}'] = {'readable_identity': identity,
                'stored_identity': ep.db.execute('SELECT identity FROM physical_identity').fetchone()[0],
                'final_holds': sum(h['status'] == 'held' for h in ep.state['slots'].values())}
        finally:
            ep.disconnect()
    return result

def ledger(directory):
    directory.mkdir()
    led = EffectLedger(directory / 'effects.sqlite')
    token = '0' * 64
    led.register(token)
    results = []
    try:
        for key, value in ((BAD, 'value'), ('key', BAD), (GOOD, GOOD)):
            try:
                number = led.begin(token, key, value)
            except ValueError as error:
                results.append({'key': key, 'value': value, 'error': type(error).__name__,
                    'operations': led.db.execute('SELECT count(*) FROM operations').fetchone()[0],
                    'effects': led.db.execute('SELECT count(*) FROM effects').fetchone()[0],
                    'failed': led.failed, 'in_transaction': led.db.in_transaction})
            else:
                results.append({'key': key, 'value': value, 'finish': led.finish(token, number),
                                'read': led.read(key)})
        return {'requests': results, 'fenced': led.fence_if_drained(token)}
    finally:
        led.disconnect()

async def main():
    BASE.mkdir(exist_ok=False)
    shutil.copyfile(__file__, BASE / 'driver.py')
    results = {}
    for name, function in (('pipeline', pipeline), ('factored', factored)):
        results[name] = await function(BASE / name)
        save(BASE / name / 'observations.json', results[name])
    for name, function in (('direct-schema', direct_schema), ('effect-ledger', ledger)):
        results[name] = function(BASE / name)
        save(BASE / name / 'observations.json', results[name])
    save(BASE / 'observations.json', results)
    print(canonical(results))

if __name__ == '__main__':
    asyncio.run(main())
