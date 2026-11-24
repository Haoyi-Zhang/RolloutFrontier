"""Durable finite dataflow sessions across named physical schema owners.

Each session fixes the wire class on every physical emitter, then retains the
union of all codec obligations at that owner using origin two. Fan-out tasks run
concurrently; joins parse every incoming wire and require equal semantic values.
The durable closing gate rejects new request IDs while exact retries of pending
IDs retain all guards until their complete outputs have been recorded.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .checker import envelope_certificate
from .controller import canonical, initialize_state_table, load_singleton_state, MAX_SEQ
from .factored_runtime import OwnerView, _profile, FactoredExecutionError
from .network import Client
from .schema_contracts import FAMILIES, validate_payload


class SchemaRequestPending(RuntimeError):
    pass


class FactoredSession:
    """One active writer per journal; origin two is reserved to this session.

The former writer must stop before reopening. Owners retain durable request
bindings and effect results, so a process that exits after an effect commits can
be retried without executing that effect a second time.
"""
    def __init__(self, network, path, *, workflow=None, manifest=None, codecs=None):
        self.net, self.path = network, Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock, self._active = asyncio.Lock(), 0
        self._failed = self._closed = False
        self.clients = {}
        initialized = self._journal_initialized(self.path)
        self.db = sqlite3.connect(str(self.path))
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA journal_mode=DELETE')
            initialize_state_table(self.db)
            self.db.execute('''CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY, input TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','complete')), output TEXT)''')
            self.db.commit()
            state = load_singleton_state(self.db)
            if state is None:
                if initialized or self.db.execute('SELECT 1 FROM requests LIMIT 1').fetchone() is not None:
                    raise FactoredExecutionError('session journal lost its durable state')
                families = {v['family'] for v in network.registry['owners'].values()}
                if len(families) != 1: raise ValueError('a dataflow uses one registered schema family')
                state = {'schema':'factored-schema-session','manifest':manifest,
                         'birth_token':uuid4().hex,
                         'registry':deepcopy(network.registry), 'window':network.window,
                         'workflow':deepcopy(workflow),'family':next(iter(families)),
                         'codecs':deepcopy(codecs),'stage':'acquiring',
                         'certificates':{},'admission_certificates':{},'journal_sequence':0}
                self._validate(state)
                self._write(state)
            else:
                self._validate(state)
                for field,value in (('workflow',workflow),('manifest',manifest),('codecs',codecs)):
                    if value is not None and canonical(state[field]) != canonical(value):
                        raise FactoredExecutionError('reopened session binding differs: '+field)
            self._state = state
            self.owners = sorted(network.registry['owners'])
            self.required = self._requirements(state)
            for index,owner in enumerate(self.owners):
                # A later session reuses this origin's sequence allocator after
                # the previous session has durably drained and retired.
                directory = Path(network.directory)/'application-origins'/f'owner-{index:04d}'
                self.clients[owner] = Client(OwnerView(network,owner,directory), 2)
            self._check_origins()
            shape = [(r[1],str(r[2]).upper(),r[3],r[5]) for r in self.db.execute('PRAGMA table_info(requests)')]
            if shape != [('request_id','TEXT',0,1),('input','TEXT',1,0),('status','TEXT',1,0),('output','TEXT',0,0)]:
                raise ValueError('session request database schema')
            for rid,raw,status,output in self.db.execute('SELECT * FROM requests'):
                self._validate_request_id(rid)
                value = json.loads(raw)
                self._seed(value)
                if status == 'complete': self._validate_output(json.loads(output),value)
                elif status != 'pending' or output is not None or state['stage'] in {'acquiring','retired'}:
                    raise ValueError('invalid durable request state')
        except BaseException:
            for client in self.clients.values(): client.disconnect()
            self.db.close()
            self._closed = True
            raise

    @classmethod
    async def begin(cls, network, path, workflow, manifest):
        path = Path(path)
        if cls._journal_initialized(path):
            session = cls(network,path,workflow=workflow,manifest=manifest)
        else:
            codecs = {}
            for owner,registered in sorted(network.registry['owners'].items()):
                value = _profile(owner,await network.rpc(owner,{'op':'read'},source=2))
                if value is None: raise SchemaRequestPending('owner unavailable during codec selection')
                try: rank = registered['catalog'].index(value['support'])
                except ValueError as error: raise FactoredExecutionError('unknown observed program') from error
                spec = FAMILIES[registered['family']]
                codecs[owner] = spec['classes'][spec['emits'][rank]]
            session = cls(network,path,workflow=workflow,manifest=manifest,codecs=codecs)
        await session.acquire()
        return session

    @staticmethod
    def _journal_initialized(path):
        """Distinguish an unused journal from retained or damaged session state.

        Failed validation can leave the two empty tables. They may be retried
        with corrected inputs, but request rows, missing tables, and malformed
        singleton state must never be reinterpreted as a new session.
        """
        if not path.exists():
            return False
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            objects = set(db.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','view','trigger')"))
            if not objects:
                return False
            if objects != {('table','state'),('table','requests')}:
                raise FactoredExecutionError('incomplete or unknown session journal schema')
            expected = {
                'state': [('id','INTEGER',0,1),('payload','TEXT',1,0)],
                'requests': [('request_id','TEXT',0,1),('input','TEXT',1,0),
                             ('status','TEXT',1,0),('output','TEXT',0,0)]}
            for table, shape in expected.items():
                actual = [(r[1],str(r[2]).upper(),r[3],r[5])
                          for r in db.execute('PRAGMA table_info(' + table + ')')]
                if actual != shape:
                    raise FactoredExecutionError('invalid session journal table schema')
            if db.execute('SELECT 1 FROM state LIMIT 1').fetchone() is None:
                if db.execute('SELECT 1 FROM requests LIMIT 1').fetchone() is not None:
                    raise FactoredExecutionError('session requests have no durable session state')
                return False
            if load_singleton_state(db) is None:
                raise FactoredExecutionError('invalid durable session payload')
            return True

    @staticmethod
    def _admission_manifest(state):
        """Bind owner authority to this journal's immutable session identity.

        A readable label may be reused, but an independently created journal
        must not adopt admissions whose pending requests it does not retain.
        The birth token is committed with the session before any owner prepare.
        """
        fields = ('birth_token','manifest','registry','window','workflow','family','codecs')
        binding = {name:state[name] for name in fields}
        return state['manifest'] + ':session:' + hashlib.sha256(canonical(binding).encode()).hexdigest()

    @staticmethod
    def _requirements(state):
        result = {owner:{'emit:'+cls} for owner,cls in state['codecs'].items()}
        steps = {s['id']:s for s in state['workflow']}
        for step in state['workflow']:
            for parent in step['parents']:
                result[step['owner']].add('accept:'+state['codecs'][steps[parent]['owner']])
        return {owner:sorted(req) for owner,req in result.items()}

    def _validate(self, state):
        fields = {'schema','manifest','birth_token','registry','window','workflow','family','codecs','stage',
                  'certificates','admission_certificates','journal_sequence'}
        if (not isinstance(state,dict) or set(state) != fields or state['schema'] != 'factored-schema-session' or
                not isinstance(state['manifest'],str) or not 1 <= len(state['manifest']) <= 128 or
                not isinstance(state['birth_token'],str) or
                not re.fullmatch(r'[0-9a-f]{32}',state['birth_token']) or
                canonical(state['registry']) != canonical(self.net.registry) or state['window'] != self.net.window or
                state['family'] not in FAMILIES or state['stage'] not in {'acquiring','open','closing','retired'} or
                type(state['journal_sequence']) is not int or not 0 <= state['journal_sequence'] <= MAX_SEQ):
            raise FactoredExecutionError('invalid session journal binding')
        try:
            str.encode(state['manifest'], 'utf-8')
        except UnicodeEncodeError as error:
            raise FactoredExecutionError('session manifest must be valid UTF-8') from error
        owners = set(self.net.registry['owners'])
        if (not isinstance(state['codecs'],dict) or set(state['codecs']) != owners or
                any(cls not in FAMILIES[state['family']]['classes'] for cls in state['codecs'].values()) or
                any(v['family'] != state['family'] for v in self.net.registry['owners'].values())):
            raise FactoredExecutionError('invalid physical codec placement')
        seen, covered = set(), set()
        if not isinstance(state['workflow'],list) or not 1 <= len(state['workflow']) <= 2048:
            raise FactoredExecutionError('dataflow size')
        for step in state['workflow']:
            if (not isinstance(step,dict) or set(step) != {'id','owner','parents'} or
                    not isinstance(step['id'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,31}',step['id']) or
                    step['id'] in seen or step['owner'] not in owners or not isinstance(step['parents'],list) or
                    len(step['parents']) > 64 or len(set(step['parents'])) != len(step['parents']) or
                    not set(step['parents']) <= seen):
                raise FactoredExecutionError('invalid ordered dataflow')
            seen.add(step['id']); covered.add(step['owner'])
        if covered != owners: raise FactoredExecutionError('dataflow must cover its physical registry')
        certs = state['certificates']
        if not isinstance(certs,dict) or not set(certs) <= owners:
            raise FactoredExecutionError('session certificate placement')
        if state['stage'] == 'open' and set(certs) != owners:
            raise FactoredExecutionError('open session lacks all-owner authority')
        if state['stage'] in {'acquiring','retired'} and certs:
            raise FactoredExecutionError('unexpected published session authority')
        admitted = state['admission_certificates']
        if not isinstance(admitted,dict) or set(admitted) not in (set(),owners):
            raise FactoredExecutionError('incomplete historical session admission')
        if state['stage'] == 'acquiring' and admitted:
            raise FactoredExecutionError('acquisition already has published admission')
        if certs and canonical(certs) != canonical(admitted):
            raise FactoredExecutionError('active and historical session admission differ')
        required = self._requirements(state)
        for owner,cert in admitted.items():
            if (cert.get('origin') != 2 or cert.get('manifest') != self._admission_manifest(state) or
                    cert.get('box') != {'0':[required[owner]]} or
                    not envelope_certificate(cert,[{'0':required[owner]}])):
                raise FactoredExecutionError('session certificate differs from codec obligations')

    def _healthy(self):
        if self._failed or self._closed: raise sqlite3.DatabaseError('session must be reopened')

    def _mutate(self, function):
        self._healthy()
        try:
            with self.db: return function()
        except sqlite3.DatabaseError:
            self._failed = True
            raise

    def _write(self, state):
        self._mutate(lambda:self.db.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(canonical(state),)))

    def _commit(self, **changes):
        state = deepcopy(self._state)
        state.update(deepcopy(changes))
        state['journal_sequence'] += 1
        self._validate(state)
        self._write(state)
        self._state = state

    @property
    def state(self): return deepcopy(self._state)

    def _check_origins(self):
        state = self._state
        admission_manifest = self._admission_manifest(state)
        for owner,client in self.clients.items():
            for record in client.state['attempts'].values():
                if record['manifest'] != admission_manifest or state['stage'] == 'retired':
                    raise FactoredExecutionError('application origin contains foreign authority')
                if 'certificate' in record:
                    cert = record['certificate']
                    if cert.get('box') != {'0':[self.required[owner]]}:
                        raise FactoredExecutionError('durable codec hold differs')
                    published = state['certificates'].get(owner)
                    if published is not None and canonical(published) != canonical(cert):
                        raise FactoredExecutionError('global and local session certificates differ')
                    if published is None and state['stage'] not in {'acquiring','closing'}:
                        raise FactoredExecutionError('unpublished application authority')
            if state['stage'] == 'open':
                key = client._record(state['certificates'][owner])
                if key is None or client.state['attempts'][key]['status'] != 'committed':
                    raise FactoredExecutionError('open session authority is not committed')

    async def acquire(self):
        async with self._lock:
            self._healthy(); self._check_origins()
            if self._state['stage'] != 'acquiring': return self._state['stage'] == 'open'
            certs = {}
            for owner in self.owners:
                answer = await self.clients[owner].acquire_box(self._admission_manifest(self._state),
                    [{'0':self.required[owner]}], {'0':[self.required[owner]]})
                if answer['status'] != 'admitted': return False
                certs[owner] = answer['certificate']
            self._commit(stage='open',certificates=certs,admission_certificates=certs)
            return True

    @staticmethod
    def _validate_request_id(value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',value):
            raise ValueError('dataflow request identity')

    def _seed(self, value):
        # The dataflow preserves numeric values through every emitter. Its
        # request domain is therefore the intersection of retained producer
        # domains, even when a middle parser accepts a wider input class.
        family = self._state['family']
        rank = len(FAMILIES[family]['programs'])-1
        if family == 'integer-widening' and 'narrow' in self._state['codecs'].values():
            rank = 0
        if family == 'field-addition':
            if not isinstance(value,dict) or value.get('tag') not in {'','migrated-δ'}:
                raise ValueError('declared field-addition metadata')
            value = deepcopy(value)
            value['tag'] = 'migrated-δ'
        validate_payload(family,rank,value)

    def _validate_output(self, output, value):
        steps = self._state['workflow']
        if not isinstance(output,dict) or set(output) != {'records','steps'} or set(output['steps']) != {s['id'] for s in steps}:
            raise FactoredExecutionError('invalid complete dataflow result')
        parents = {p for s in steps for p in s['parents']}
        sinks = {s['id'] for s in steps if s['id'] not in parents}
        if set(output['records']) != sinks: raise FactoredExecutionError('dataflow sink outputs differ')
        for step in steps:
            response = output['steps'][step['id']]
            if response.get('status') != 'applied': raise FactoredExecutionError('incomplete dataflow effect')
            expected = deepcopy(value)
            if self._state['family'] == 'field-addition':
                expected['tag'] = 'migrated-δ' if self._state['codecs'][step['owner']] == 'extended' else ''
            if response['output']['record'] != expected:
                raise FactoredExecutionError('dataflow changed semantic content')
            if step['id'] in sinks and output['records'][step['id']] != expected:
                raise FactoredExecutionError('dataflow result disagrees with sink')

    async def request(self, request_id, value, *, after_step=None):
        value = deepcopy(value)
        self._validate_request_id(request_id); self._seed(value)
        if after_step is not None and not callable(after_step): raise ValueError('step observer')
        raw = canonical(value)
        async with self._lock:
            self._healthy(); self._check_origins()
            def bind():
                row = self.db.execute('SELECT input,status,output FROM requests WHERE request_id=?',(request_id,)).fetchone()
                if row is not None:
                    if row[0] != raw: raise ValueError('request ID is already bound to another input')
                    if row[1] == 'complete': return json.loads(row[2])
                    if self._state['stage'] not in {'open','closing'}:
                        raise FactoredExecutionError('pending request has no session authority')
                else:
                    if self._state['stage'] != 'open': raise ValueError('session is not open for new request IDs')
                    self.db.execute('INSERT INTO requests VALUES(?,?,?,NULL)',(request_id,raw,'pending'))
                return None
            result = self._mutate(bind)
            if result is not None: return result
            self._active += 1
        try:
            tasks, definitions = {}, {s['id']:s for s in self._state['workflow']}
            async def run_step(step):
                prior = [await tasks[parent] for parent in step['parents']]
                owner = step['owner']
                cert = self._state['certificates'][owner]
                response = await self.net.rpc(owner,{
                    'op':'schema','origin':2,'sequence':cert['sequences']['0'],'manifest':cert['manifest'],
                    'request_id':request_id+':'+step['id'],
                    'input_classes':[self._state['codecs'][definitions[p]['owner']] for p in step['parents']],
                    'emit_class':self._state['codecs'][owner],
                    'inputs':[r['output']['wire'] for r in prior],
                    'seed':None if prior else deepcopy(value)},source=2)
                if response is None or response.get('status') != 'applied':
                    raise SchemaRequestPending('physical schema effect unconfirmed at '+owner)
                if after_step is not None: await after_step(deepcopy(step),deepcopy(response))
                return response
            for step in self._state['workflow']: tasks[step['id']] = asyncio.create_task(run_step(step))
            replies = await asyncio.gather(*tasks.values(),return_exceptions=True)
            errors = [r for r in replies if isinstance(r,BaseException)]
            if errors: raise SchemaRequestPending(str(errors[0])) from errors[0]
            results = dict(zip(tasks,replies))
            parent_ids = {p for s in self._state['workflow'] for p in s['parents']}
            output = {'records':{s['id']:deepcopy(results[s['id']]['output']['record'])
                                  for s in self._state['workflow'] if s['id'] not in parent_ids},
                      'steps':results}
            self._validate_output(output,value)
            def complete():
                row = self.db.execute('SELECT input,status,output FROM requests WHERE request_id=?',
                                      (request_id,)).fetchone()
                if row is None or row[0] != raw:
                    raise FactoredExecutionError('pending request binding changed before completion')
                if row[1] == 'complete':
                    # Concurrent exact retries share one durable returned result,
                    # including receipt metadata, regardless of which finishes first.
                    return json.loads(row[2])
                self.db.execute('UPDATE requests SET status=?,output=? WHERE request_id=?',
                                ('complete',canonical(output),request_id))
                return deepcopy(output)
            return self._mutate(complete)
        finally:
            async with self._lock: self._active -= 1

    async def close(self):
        async with self._lock:
            self._healthy(); self._check_origins()
            if self._state['stage'] == 'retired': return True
            if self._state['stage'] != 'closing': self._commit(stage='closing')
            pending = self.db.execute("SELECT count(*) FROM requests WHERE status='pending'").fetchone()[0]
            if self._active or pending: return False
            for owner,client in self.clients.items():
                await client.recover()
                for record in list(client.state['attempts'].values()):
                    if record['status'] != 'committed' or not await client.retire(record['certificate']):
                        return False
                if client.state['attempts']: return False
            self._commit(stage='retired',certificates={})
            return True

    def disconnect(self):
        if not self._closed:
            self._closed = True
            for client in self.clients.values(): client.disconnect()
            self.db.close()
