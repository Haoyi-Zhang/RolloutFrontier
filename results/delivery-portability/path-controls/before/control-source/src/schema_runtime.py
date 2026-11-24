"""Registered physical owners with actual ProtoJSON handlers and durable effects.

Each process has one Endpoint state and one SQLite serialization point. Every
factor incident to its physical owner is therefore checked against that same
support and all its holds. The outer transport identity binds local node zero to
an immutable named deployment, owner, application family, and physical catalog.
The loopback test transport assumes trusted peers and fail-stop processes.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import sqlite3

from google.protobuf import json_format
from .controller import Endpoint, canonical
from .schema_contracts import FAMILIES, actual_probes, encode_wire, decode_wire, validate_payload

LIMIT = 2 * 1024 * 1024


def identity_for(registry, owner, window=8, policy='predicate'):
    registered = registry['owners'][owner]
    return {'deployment': registry['deployment'], 'owner': owner,
            'family': registered['family'], 'initial': deepcopy(registered['initial']),
            'catalog': deepcopy(registered['catalog']), 'window': window, 'policy': policy}


def program_rank(family, catalog, support):
    try:
        return catalog.index(support)
    except ValueError as error:
        raise ValueError('support is outside the registered physical catalog') from error


def check_wire_class(family, cls, wire):
    """Check the declared wire domain before invoking the actual schema parser."""
    if cls not in FAMILIES[family]['classes'] or not isinstance(wire, str) or len(wire) > 16384:
        raise ValueError('wire class')
    raw = json.loads(wire)
    if not isinstance(raw, dict):
        raise ValueError('wire object')
    if family == 'enum-alias':
        if raw.get('status') != {'old-name': 'ACTIVE', 'new-name': 'ENABLED'}[cls]:
            raise ValueError('wire enum class differs')
    elif family == 'field-key':
        expected = 'count' if cls == 'old-key' else 'quantity'
        alternate = 'quantity' if cls == 'old-key' else 'count'
        if expected not in raw or alternate in raw:
            raise ValueError('wire key class differs')
    elif family == 'field-addition':
        if ('tag' in raw) != (cls == 'extended') or (cls == 'extended' and raw['tag'] != 'migrated-δ'):
            raise ValueError('wire field class differs')
    elif family == 'integer-widening':
        value = raw.get('value')
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError('wire integer class')
        number = int(value)
        bound = 31 if cls == 'narrow' else 63
        if not -(1 << bound) <= number < (1 << bound):
            raise ValueError('wire integer domain differs')


def request_requirements(request):
    if (not isinstance(request['input_classes'], list) or
            len(request['input_classes']) > 64 or
            any(not isinstance(v, str) for v in request['input_classes']) or
            not isinstance(request['emit_class'], str)):
        raise ValueError('schema contract fields')
    return sorted({'emit:' + request['emit_class'],
                   *('accept:' + cls for cls in request['input_classes'])})


class SchemaEndpoint(Endpoint):
    def __init__(self, identity, path, *, after_commit=None):
        expected = {'deployment', 'owner', 'family', 'initial', 'catalog', 'window', 'policy'}
        if (not isinstance(identity, dict) or set(identity) != expected or
                not isinstance(identity['deployment'], str) or not 1 <= len(identity['deployment']) <= 128 or
                not isinstance(identity['owner'], str) or not 1 <= len(identity['owner']) <= 128 or
                identity['policy'] != 'predicate'):
            raise ValueError('physical identity schema')
        family = identity['family']
        probe = next((r for r in actual_probes() if r['family'] == family), None)
        if probe is None or identity['catalog'] != probe['profiles'] or identity['initial'] not in probe['profiles']:
            raise ValueError('registered catalog differs from executable schema programs')
        self.identity, self.family = deepcopy(identity), family
        self.after_commit, self.last_audit = after_commit, None
        super().__init__(0, identity['initial'], path, window=identity['window'], policy=identity['policy'])
        try:
            program_rank(family, identity['catalog'], self.state['support'])
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS physical_identity (
                id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS schema_results (
                origin INTEGER NOT NULL, sequence INTEGER NOT NULL,
                manifest TEXT NOT NULL, request_id TEXT NOT NULL,
                input TEXT NOT NULL, output TEXT NOT NULL,
                generation INTEGER NOT NULL, rank INTEGER NOT NULL,
                PRIMARY KEY(origin,sequence,manifest,request_id));
              CREATE TABLE IF NOT EXISTS schema_audit (
                ordinal INTEGER PRIMARY KEY, request TEXT NOT NULL, response TEXT NOT NULL,
                profile TEXT NOT NULL);
            ''')
            shapes = {
                'physical_identity': [('id','INTEGER',0,1), ('identity','TEXT',1,0)],
                'schema_results': [('origin','INTEGER',1,1), ('sequence','INTEGER',1,2),
                    ('manifest','TEXT',1,3), ('request_id','TEXT',1,4), ('input','TEXT',1,0),
                    ('output','TEXT',1,0), ('generation','INTEGER',1,0), ('rank','INTEGER',1,0)],
                'schema_audit': [('ordinal','INTEGER',0,1), ('request','TEXT',1,0),
                    ('response','TEXT',1,0), ('profile','TEXT',1,0)]}
            for table, shape in shapes.items():
                actual = [(r[1],str(r[2]).upper(),r[3],r[5]) for r in self.db.execute('PRAGMA table_info('+table+')')]
                if actual != shape: raise ValueError('physical owner database schema')
            rows = self.db.execute('SELECT id,identity FROM physical_identity').fetchall()
            if not rows:
                with self.db:
                    self.db.execute('INSERT INTO physical_identity VALUES(1,?)', (canonical(identity),))
            elif rows != [(1, canonical(identity))]:
                raise ValueError('physical owner identity changed')
            for origin, sequence, manifest, request_id, raw_input, raw_output, generation, rank in self.db.execute('SELECT * FROM schema_results'):
                if (type(origin) is not int or not 0 <= origin < 6 or
                        type(sequence) is not int or not 1 <= sequence < 2**63 or
                        not isinstance(manifest,str) or not 1 <= len(manifest) <= 256 or
                        not isinstance(request_id, str) or not 1 <= len(request_id) <= 256 or
                        type(generation) is not int or not 0 <= generation <= self.state['generation'] or
                        type(rank) is not int or not 0 <= rank < len(identity['catalog'])):
                    raise ValueError('invalid retained schema effect')
                if canonical(self.compute(rank, json.loads(raw_input))) != raw_output:
                    raise ValueError('retained schema effect differs from its registered handler')
        except BaseException:
            self.disconnect()
            raise

    def install(self, support):
        program_rank(self.family, self.identity['catalog'], sorted(set(support)))
        return super().install(support)

    def compute(self, rank, value):
        if set(value) != {'input_classes', 'emit_class', 'inputs', 'seed'}:
            raise ValueError('handler input schema')
        spec = FAMILIES[self.family]
        if value['emit_class'] != spec['classes'][spec['emits'][rank]]:
            raise ValueError('active serializer differs from retained wire class')
        inputs, classes = value['inputs'], value['input_classes']
        if not isinstance(inputs, list) or len(inputs) != len(classes) or len(inputs) > 64:
            raise ValueError('handler inputs')
        if inputs:
            if value['seed'] is not None: raise ValueError('non-source has a seed')
            records = []
            for wire, cls in zip(inputs, classes):
                check_wire_class(self.family, cls, wire)
                records.append(decode_wire(self.family, rank, wire))
            semantic = records[0]
            comparable = (lambda record: {k:v for k,v in record.items() if k != 'tag'}) if self.family == 'field-addition' else (lambda record:record)
            if any(comparable(record) != comparable(semantic) for record in records):
                raise ValueError('join inputs disagree')
        else:
            semantic = deepcopy(value['seed'])
        # Addition changes an explicit metadata field; key/value remain intact.
        # The other families preserve the complete semantic record.
        if self.family == 'field-addition' and isinstance(semantic, dict):
            semantic['tag'] = 'migrated-δ' if rank == 2 else ''
        validate_payload(self.family, rank, semantic)
        wire = encode_wire(self.family, rank, semantic)
        check_wire_class(self.family, value['emit_class'], wire)
        return {'wire': wire, 'record': semantic}

    def application(self, request):
        fields = {'op', 'origin', 'sequence', 'manifest', 'request_id',
                  'input_classes', 'emit_class', 'inputs', 'seed'}
        if not isinstance(request, dict) or set(request) != fields:
            raise ValueError('schema request fields')
        request_id = request['request_id']
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 256:
            raise ValueError('schema request identity')
        required = set(request_requirements(request))
        key, error = self._key(request['origin'], request['sequence'])
        hold = self.state['slots'].get(key, {})
        if error or hold.get('status') != 'held' or hold.get('manifest') != request['manifest']:
            return {'status': 'not-authorized'}
        terms = hold.get('options', [hold.get('requires', [])])
        if not terms or any(not required <= set(term) for term in terms):
            return {'status': 'codec-not-retained'}
        if not required <= set(self.state['support']):
            return {'status': 'unsupported-codec'}
        value = {k: deepcopy(request[k]) for k in ('input_classes', 'emit_class', 'inputs', 'seed')}
        raw_input = canonical(value)
        effect_identity = (request['origin'],request['sequence'],request['manifest'],request_id)
        old = self.db.execute('SELECT input,output,generation,rank FROM schema_results '
                              'WHERE origin=? AND sequence=? AND manifest=? AND request_id=?',
                              effect_identity).fetchone()
        if old is not None:
            if old[0] != raw_input: return {'status': 'request-conflict'}
            return {'status': 'applied', 'duplicate': True, 'output': json.loads(old[1]),
                    'applied_generation': old[2], 'applied_rank': old[3]}
        rank = program_rank(self.family, self.identity['catalog'], self.state['support'])
        output = self.compute(rank, value)
        generation = self.state['generation']
        try:
            with self.db:
                self.db.execute('INSERT INTO schema_results VALUES(?,?,?,?,?,?,?,?)',
                    (*effect_identity, raw_input, canonical(output), generation, rank))
        except sqlite3.DatabaseError:
            self._persistence_failed = True
            raise
        if self.after_commit is not None: self.after_commit(request)
        return {'status': 'applied', 'duplicate': False, 'output': output,
                'applied_generation': generation, 'applied_rank': rank}

    def handle(self, request):
        self._require_healthy()
        try:
            response = (self.application(request) if isinstance(request, dict) and request.get('op') == 'schema'
                        else super().handle(request))
        except (ValueError, TypeError, KeyError, json_format.ParseError) as error:
            response = {'status': 'invalid', 'reason': type(error).__name__}
        try:
            with self.db:
                cursor = self.db.execute('INSERT INTO schema_audit(request,response,profile) VALUES(?,?,?)',
                    (canonical(request), canonical(response), canonical(self.profile())))
                self.last_audit = cursor.lastrowid
        except sqlite3.DatabaseError:
            self._persistence_failed = True
            raise
        return response


async def serve(identity, database, kill_after_request=None):
    def after_commit(request):
        if request['request_id'] == kill_after_request:
            os.kill(os.getpid(), signal.SIGKILL)
    endpoint = SchemaEndpoint(identity, database, after_commit=after_commit)

    async def connection(reader, writer):
        try:
            raw = await asyncio.wait_for(reader.readline(), 5)
            if not raw or len(raw) > LIMIT: return
            request = json.loads(raw)
            if (not isinstance(request, dict) or set(request) != {'identity','request'} or
                    canonical(request['identity']) != canonical(endpoint.identity)):
                response = {'status': 'wrong-physical-owner'}
                order = None
            else:
                response = endpoint.handle(request['request'])
                order = endpoint.last_audit
            envelope = {'identity': endpoint.identity, 'response': response, 'owner_order': order}
            encoded = (canonical(envelope)+'\n').encode()
            if len(encoded) > LIMIT: raise ValueError('response frame bound')
            writer.write(encoded)
            await writer.drain()
        except (ValueError, KeyError, TypeError, sqlite3.DatabaseError, ConnectionError,
                OSError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            try: await writer.wait_closed()
            except (ConnectionError, OSError): pass

    server = await asyncio.start_server(connection, '127.0.0.1', 0, limit=LIMIT+1)
    print(canonical({'status': 'ready', 'owner': identity['owner'],
                     'port': server.sockets[0].getsockname()[1], 'pid': os.getpid()}), flush=True)
    try:
        async with server: await server.serve_forever()
    finally:
        endpoint.disconnect()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--kill-after-request')
    args = parser.parse_args()
    asyncio.run(serve(json.loads(args.identity.read_text()), args.database, args.kill_after_request))


if __name__ == '__main__': main()
