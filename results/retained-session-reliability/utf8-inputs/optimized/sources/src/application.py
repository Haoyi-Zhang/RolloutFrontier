"""Actual ProtoJSON pipeline with handlers bound to durable rollout profiles.

The four descriptors implement the documented enum-alias migration: add the
new name after the old one, change the serializer preference, then remove the
old name. Owner transitions and synchronous application calls use one SQLite
connection and one event-loop serialization point.
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
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
from .controller import Endpoint, canonical

PROGRAMS = {
    'legacy': ('ACTIVE',),
    'accepting': ('ACTIVE', 'ENABLED'),
    'emitting': ('ENABLED', 'ACTIVE'),
    'current': ('ENABLED',),
}
PROFILES = {name: sorted(['emit:' + names[0], 'program:' + name] +
                        ['parse:' + value for value in names]) for name, names in PROGRAMS.items()}
ROLES = ('encode', 'transform', 'store')
LIMIT = 1024 * 1024
INPUT_MIN = -(((1 << 62) + 7) // 3)
INPUT_MAX = ((1 << 62) - 8) // 3


def profile_name(support):
    for name, profile in PROFILES.items():
        if support == profile:
            return name
    raise ValueError('support does not identify a registered application')


def semantic_record(value):
    if (not isinstance(value, dict) or set(value) != {'key', 'amount'} or
            not isinstance(value['key'], str) or not 1 <= len(value['key']) <= 128 or
            type(value['amount']) is not int or not -(1 << 62) <= value['amount'] < (1 << 62)):
        raise ValueError('invalid semantic record')
    try:
        value['key'].encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError('semantic key must be valid UTF-8') from error
    return deepcopy(value)


def input_record(value):
    value = semantic_record(value)
    if not INPUT_MIN <= value['amount'] <= INPUT_MAX:
        raise ValueError('input exceeds transform domain')
    return value


def message_class(program):
    names = PROGRAMS[program]
    file = descriptor_pb2.FileDescriptorProto(name='application.proto', package='rollout', syntax='proto3')
    enum = file.enum_type.add(name='State')
    enum.value.add(name='STATE_UNSPECIFIED', number=0)
    enum.options.allow_alias = len(names) > 1
    for name in names:
        enum.value.add(name=name, number=1)
    message = file.message_type.add(name='Record')
    message.field.add(name='key', number=1, label=1, type=9)
    message.field.add(name='amount', number=2, label=1, type=18)
    message.field.add(name='state', number=3, label=1, type=14, type_name='.rollout.State')
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName('rollout.Record'))


MESSAGES = {name: message_class(name) for name in PROGRAMS}


def encode(program, value):
    value = semantic_record(value)
    message = MESSAGES[program](key=value['key'], amount=value['amount'], state=1)
    return canonical(json_format.MessageToDict(message, always_print_fields_with_no_presence=True))


def decode(program, wire, expected_name):
    if not isinstance(wire, str) or len(wire) > 4096:
        raise ValueError('invalid wire frame')
    raw = json.loads(wire)
    if not isinstance(raw, dict) or raw.get('state') != expected_name:
        raise ValueError('wire name differs from retained contract')
    message = MESSAGES[program]()
    json_format.Parse(wire, message)
    if message.state != 1:
        raise ValueError('unexpected application state')
    return semantic_record({'key': message.key, 'amount': message.amount})


def requirements(node, codec):
    if (not isinstance(codec, (list, tuple)) or len(codec) != 2 or
            any(name not in ('ACTIVE', 'ENABLED') for name in codec)):
        raise ValueError('invalid pipeline wire contracts')
    if node == 0:
        return ['emit:' + codec[0]]
    if node == 1:
        return sorted(['parse:' + codec[0], 'emit:' + codec[1]])
    if node == 2:
        return ['parse:' + codec[1]]
    raise ValueError('unknown pipeline node')


def pipeline_branch(codec):
    return {str(node): requirements(node, codec) for node in range(3)}


class ApplicationEndpoint(Endpoint):
    """Registered ProtoJSON code, durable idempotent effects, and owner guards."""
    def __init__(self, node, support, path, *, after_commit=None):
        if type(node) is not int or not 0 <= node < len(ROLES):
            raise ValueError('application role')
        profile_name(support)
        self.after_commit = after_commit
        self.last_audit = None
        super().__init__(node, support, path)
        try:
            profile_name(self.state['support'])
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS application_results (
                request_id TEXT PRIMARY KEY, codec TEXT NOT NULL,
                input TEXT NOT NULL, output TEXT NOT NULL,
                generation INTEGER NOT NULL, program TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS application_audit (
                ordinal INTEGER PRIMARY KEY, request TEXT NOT NULL,
                response TEXT NOT NULL, profile TEXT NOT NULL);
            ''')
            expected = {
                'application_results': [('request_id', 'TEXT', 0, 1), ('codec', 'TEXT', 1, 0),
                    ('input', 'TEXT', 1, 0), ('output', 'TEXT', 1, 0),
                    ('generation', 'INTEGER', 1, 0), ('program', 'TEXT', 1, 0)],
                'application_audit': [('ordinal', 'INTEGER', 0, 1), ('request', 'TEXT', 1, 0),
                    ('response', 'TEXT', 1, 0), ('profile', 'TEXT', 1, 0)]}
            for table, shape in expected.items():
                actual = [(r[1], str(r[2]).upper(), r[3], r[5])
                          for r in self.db.execute('PRAGMA table_info(' + table + ')')]
                if actual != shape:
                    raise ValueError('application database schema')
            for request_id, codec, raw_input, raw_output, generation, program in self.db.execute(
                    'SELECT * FROM application_results'):
                codec = json.loads(codec)
                if (not isinstance(request_id, str) or not request_id or len(request_id) > 128 or
                        program not in PROGRAMS or type(generation) is not int or
                        not 0 <= generation <= self.state['generation'] or
                        not set(requirements(self.node, codec)) <= set(PROFILES[program])):
                    raise ValueError('invalid retained application result')
                if self.compute(program, codec, json.loads(raw_input)) != json.loads(raw_output):
                    raise ValueError('retained application result differs from handler')
        except Exception:
            self.disconnect()
            raise

    def install(self, support):
        profile_name(sorted(set(support)))
        return super().install(support)

    def compute(self, program, codec, value):
        if self.node == 0:
            return {'wire': encode(program, input_record(value))}
        record = decode(program, value, codec[self.node - 1])
        if self.node == 1:
            record['amount'] = record['amount'] * 3 + 7
            return {'wire': encode(program, record)}
        return {'record': record}

    def application(self, request):
        fields = {'op', 'origin', 'sequence', 'manifest', 'request_id', 'codec', 'input'}
        if not isinstance(request, dict) or set(request) != fields:
            raise ValueError('application request schema')
        request_id = request['request_id']
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError('application request identity')
        codec = request['codec']
        required = set(requirements(self.node, codec))
        key, error = self._key(request['origin'], request['sequence'])
        hold = self.state['slots'].get(key, {})
        if (error or hold.get('status') != 'held' or hold.get('manifest') != request['manifest']):
            return {'status': 'not-authorized'}
        terms = hold.get('options', [hold.get('requires', [])])
        if not terms or any(not required <= set(term) for term in terms):
            return {'status': 'codec-not-retained'}
        program = profile_name(self.state['support'])
        if not required <= set(self.state['support']):
            return {'status': 'unsupported-codec'}
        raw_input, raw_codec = canonical(request['input']), canonical(codec)
        row = self.db.execute('SELECT codec,input,output,generation,program FROM application_results '
                              'WHERE request_id=?', (request_id,)).fetchone()
        if row is not None:
            if row[:2] != (raw_codec, raw_input):
                return {'status': 'request-conflict'}
            return {'status': 'applied', 'duplicate': True, 'output': json.loads(row[2]),
                    'applied_generation': row[3], 'applied_program': row[4], 'role': ROLES[self.node]}
        output = self.compute(program, codec, request['input'])
        generation = self.state['generation']
        try:
            with self.db:
                self.db.execute('INSERT INTO application_results VALUES(?,?,?,?,?,?)',
                    (request_id, raw_codec, raw_input, canonical(output), generation, program))
        except sqlite3.DatabaseError:
            self._persistence_failed = True
            raise
        if self.after_commit is not None:
            self.after_commit(request)
        return {'status': 'applied', 'duplicate': False, 'output': output,
                'applied_generation': generation, 'applied_program': program, 'role': ROLES[self.node]}

    def handle(self, request):
        self._require_healthy()
        try:
            response = (self.application(request) if isinstance(request, dict) and
                        request.get('op') == 'application' else super().handle(request))
        except (ValueError, TypeError, KeyError, json_format.ParseError) as error:
            response = {'status': 'invalid', 'reason': type(error).__name__}
        try:
            with self.db:
                cursor = self.db.execute('INSERT INTO application_audit(request,response,profile) VALUES(?,?,?)',
                    (canonical(request), canonical(response), canonical(self.profile())))
                self.last_audit = cursor.lastrowid
        except sqlite3.DatabaseError:
            self._persistence_failed = True
            raise
        return response


class PipelineSession:
    """Durable request bindings and a drain gate protect end-to-end retries.

    Request ids are globally unique across sessions and origins at these owners.
    Closing prevents new request ids. A failed request remains pending in the
    origin database and retains all owner guards; an exact retry remains allowed
    while draining. Successful output is durably recorded before retirement.
    """
    def __init__(self, client, certificate, codec):
        branch = pipeline_branch(codec)
        if client._record(certificate) is None:
            raise ValueError('unowned pipeline certificate')
        receipts = certificate['receipts']
        if {str(r['node']): r['requires'] for r in receipts} != branch:
            raise ValueError('pipeline certificate has different wire contracts')
        self.client, self.certificate, self.codec = client, deepcopy(certificate), list(codec)
        self.manifest = certificate['manifest']
        self._condition = asyncio.Condition()
        self._active = 0
        self._retired = False
        client.db.executescript("""
          CREATE TABLE IF NOT EXISTS application_sessions (
            manifest TEXT PRIMARY KEY, codec TEXT NOT NULL,
            closing INTEGER NOT NULL CHECK(closing IN (0,1)));
          CREATE TABLE IF NOT EXISTS application_requests (
            manifest TEXT NOT NULL, request_id TEXT NOT NULL,
            input TEXT NOT NULL, codec TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','complete')),
            output TEXT, PRIMARY KEY(manifest,request_id));
        """)
        def register():
            row = client.db.execute('SELECT codec,closing FROM application_sessions WHERE manifest=?', (self.manifest,)).fetchone()
            if row is None:
                client.db.execute('INSERT INTO application_sessions VALUES(?,?,0)', (self.manifest, canonical(self.codec)))
                return False
            if row[0] != canonical(self.codec) or row[1] not in (0,1):
                raise ValueError('durable application session binding differs')
            return bool(row[1])
        self._closing = self._mutate(register)
        for request_id, raw_input, raw_codec, status, raw_output in client.db.execute(
                'SELECT request_id,input,codec,status,output FROM application_requests WHERE manifest=?', (self.manifest,)):
            original = input_record(json.loads(raw_input))
            if (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128 or
                    raw_codec != canonical(self.codec) or status not in ('pending','complete')):
                raise ValueError('invalid durable application request')
            if status == 'complete':
                result = json.loads(raw_output)
                if result['record'] != {'key': original['key'], 'amount': 3*original['amount'] + 7}:
                    raise ValueError('durable application result differs')
            elif raw_output is not None:
                raise ValueError('pending request has an unacknowledged output')

    def _mutate(self, function):
        self.client._require_healthy()
        try:
            with self.client.db:
                return function()
        except sqlite3.DatabaseError:
            self.client._persistence_failed = True
            raise

    async def request(self, request_id, value, *, after_encode=None):
        value = input_record(value)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError('pipeline request identity')
        raw_input = canonical(value)
        async with self._condition:
            def bind():
                row = self.client.db.execute('SELECT input,codec,status,output FROM application_requests '
                    'WHERE manifest=? AND request_id=?', (self.manifest,request_id)).fetchone()
                if row is not None:
                    if row[:2] != (raw_input,canonical(self.codec)):
                        raise ValueError('pipeline request input binding differs')
                    if row[2] == 'complete':
                        return json.loads(row[3])
                    return None
                gate = self.client.db.execute('SELECT closing FROM application_sessions WHERE manifest=?', (self.manifest,)).fetchone()
                if gate != (0,):
                    self._closing = True
                    raise ValueError('pipeline session is draining')
                self.client.db.execute('INSERT INTO application_requests VALUES(?,?,?,?,?,NULL)',
                    (self.manifest,request_id,raw_input,canonical(self.codec),'pending'))
                return None
            completed = self._mutate(bind)
            if completed is not None:
                return completed
            self._active += 1
        replies = []
        try:
            payload = deepcopy(value)
            for node in range(3):
                response = await self.client.net.rpc(self.client.origin, node, {
                    'op': 'application', 'origin': self.client.origin,
                    'sequence': self.certificate['sequences'][str(node)],
                    'manifest': self.manifest, 'codec': self.codec,
                    'request_id': request_id, 'input': payload})
                if response is None or response.get('status') != 'applied':
                    raise RuntimeError('pipeline call incomplete: ' + str(response))
                replies.append(deepcopy(response))
                if node == 0 and after_encode is not None:
                    await after_encode()
                payload = response['output'].get('wire') if node < 2 else response['output']['record']
            result = {'record': payload, 'owner_replies': replies}
            def complete():
                self.client.db.execute("UPDATE application_requests SET status='complete',output=? WHERE manifest=? AND request_id=?",
                    (canonical(result),self.manifest,request_id))
            self._mutate(complete)
            return result
        finally:
            async with self._condition:
                self._active -= 1
                self._condition.notify_all()

    async def retire(self):
        async with self._condition:
            def close_gate():
                self.client.db.execute('UPDATE application_sessions SET closing=1 WHERE manifest=?', (self.manifest,))
            self._mutate(close_gate)
            self._closing = True
            while self._active:
                await self._condition.wait()
            unresolved = self.client.db.execute("SELECT COUNT(*) FROM application_requests WHERE manifest=? AND status='pending'", (self.manifest,)).fetchone()[0]
            if unresolved:
                return False
            if self._retired:
                return True
            done = await self.client.retire(self.certificate)
            self._retired = done
            return done


async def serve(node, path, initial, kill_request=None):
    def after_commit(request):
        if request['request_id'] == kill_request:
            os.kill(os.getpid(), signal.SIGKILL)
    endpoint = ApplicationEndpoint(node, PROFILES[initial], path, after_commit=after_commit)

    async def service(reader, writer):
        try:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if len(line) > LIMIT:
                    raise ValueError('frame bound')
                response = endpoint.handle(json.loads(line))
                envelope = {'response': response, 'owner_order': endpoint.last_audit}
            except (ValueError, TypeError, KeyError, asyncio.TimeoutError) as error:
                envelope = {'response': {'status': 'invalid', 'reason': type(error).__name__}, 'owner_order': None}
            except sqlite3.DatabaseError:
                # Preserve durable authority and terminate this failed channel.
                # The endpoint remains fail-closed until it is reopened.
                return
            writer.write((canonical(envelope) + '\n').encode())
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    server = await asyncio.start_server(service, '127.0.0.1', 0, limit=LIMIT + 1)
    print(canonical({'status': 'ready', 'node': node, 'port': server.sockets[0].getsockname()[1]}), flush=True)
    try:
        async with server:
            await server.serve_forever()
    finally:
        endpoint.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', type=int, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--initial', choices=tuple(PROFILES), required=True)
    parser.add_argument('--kill-after-request')
    args = parser.parse_args()
    asyncio.run(serve(args.serve, args.database, args.initial, args.kill_after_request))
