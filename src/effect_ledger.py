"""Durable drain/fence adapter for an owned single-host key/value effect.

The core protocol's ``use`` response is not a lifetime for arbitrary external
work. This adapter makes one concrete application effect share a durable
admission/retirement ledger. It does not fence arbitrary services or detached
callbacks and assumes the existing single-writer/non-Byzantine storage model.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from .controller import canonical
from .network import Client

MAX_LEASES=64
MAX_OPERATIONS=2048

def identifier(value,limit=256):
    if not isinstance(value,str) or not value or len(value)>limit:
        raise ValueError('invalid effect identifier')
    return value

def lease_id(certificate):
    return hashlib.sha256(canonical(certificate).encode('utf-8')).hexdigest()

class EffectLedger:
    """An operation reservation and its actual SQLite mutation share one DB."""
    def __init__(self,path:Path):
        self.db=sqlite3.connect(str(path));self.closed=False;self.failed=False
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS leases (
                token TEXT PRIMARY KEY, phase TEXT NOT NULL CHECK(phase IN ('open','closing','closed')));
              CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY, lease TEXT NOT NULL REFERENCES leases(token),
                key TEXT NOT NULL, value TEXT NOT NULL,
                phase TEXT NOT NULL CHECK(phase IN ('active','done','cancelled')));
              CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            expected={'leases':[('token','TEXT',0,1),('phase','TEXT',1,0)],
                'operations':[('id','INTEGER',0,1),('lease','TEXT',1,0),('key','TEXT',1,0),
                              ('value','TEXT',1,0),('phase','TEXT',1,0)],
                'effects':[('key','TEXT',0,1),('value','TEXT',1,0)]}
            actual={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if actual!=set(expected):raise ValueError('unexpected effect ledger tables')
            for table,columns in expected.items():
                if [(r[1],str(r[2]).upper(),r[3],r[5]) for r in self.db.execute('PRAGMA table_info('+table+')')]!=columns:
                    raise ValueError('invalid effect ledger schema')
            if [(r[2],r[3],r[4]) for r in self.db.execute('PRAGMA foreign_key_list(operations)')]!=[('leases','lease','token')]:
                raise ValueError('invalid effect ledger foreign key')
            if self.db.execute('SELECT COUNT(*) FROM leases').fetchone()[0]>MAX_LEASES:
                raise ValueError('durable lease bound')
            if self.db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('broken effect ledger reference')
            for token,phase in self.db.execute('SELECT token,phase FROM leases'):
                if (not isinstance(token,str) or len(token)!=64 or
                        any(c not in '0123456789abcdef' for c in token) or
                        phase not in ('open','closing','closed')):raise ValueError('invalid durable lease')
            for number,token,key,value,phase in self.db.execute('SELECT * FROM operations'):
                if type(number) is not int or not 1<=number<=MAX_OPERATIONS:
                    raise ValueError('invalid durable operation')
                identifier(key);identifier(value,4096)
                if phase not in ('active','done','cancelled'):raise ValueError('invalid durable operation phase')
                parent=self.db.execute('SELECT phase FROM leases WHERE token=?',(token,)).fetchone()
                if parent is None or parent[0]=='closed' and phase=='active':
                    raise ValueError('active effect after durable fence')
        except Exception:
            self.db.close();self.closed=True;raise

    def healthy(self):
        if self.closed or self.failed:raise RuntimeError('effect ledger must be reopened')

    def mutate(self,function):
        self.healthy()
        try:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                return function()
        except sqlite3.DatabaseError:
            # A commit error has an uncertain durable outcome. Never continue
            # from an in-memory guess, and never release a guard on this path.
            self.failed=True;raise

    def register(self,token):
        identifier(token,64)
        if len(token)!=64 or any(c not in '0123456789abcdef' for c in token):raise ValueError('invalid token')
        def action():
            existing=self.db.execute('SELECT phase FROM leases WHERE token=?',(token,)).fetchone()
            if existing is not None:return existing[0]
            if self.db.execute('SELECT COUNT(*) FROM leases').fetchone()[0]>=MAX_LEASES:
                raise ValueError('effect lease bound')
            self.db.execute("INSERT INTO leases VALUES(?,'open')",(token,));return 'open'
        return self.mutate(action)

    def phase(self,token):
        self.healthy();row=self.db.execute('SELECT phase FROM leases WHERE token=?',(token,)).fetchone()
        if row is None:raise ValueError('unknown effect lease')
        return row[0]

    def begin(self,token,key,value):
        identifier(key);identifier(value,4096)
        def action():
            if self.phase(token)!='open':raise ValueError('effect lease no longer admits writes')
            number=self.db.execute('SELECT COALESCE(MAX(id),0)+1 FROM operations').fetchone()[0]
            if number>MAX_OPERATIONS:raise ValueError('effect operation bound')
            self.db.execute("INSERT INTO operations VALUES(?,?,?,?,'active')",(number,token,key,value))
            return number
        return self.mutate(action)

    def finish(self,token,number,cancel=False):
        if type(number) is not int or not 1<=number<=MAX_OPERATIONS or type(cancel) is not bool:
            raise ValueError('invalid operation handle')
        def action():
            row=self.db.execute('SELECT lease,key,value,phase FROM operations WHERE id=?',(number,)).fetchone()
            if row is None or row[0]!=token:raise ValueError('effect handle bound to another lease')
            if row[3]!='active':return 'already-'+row[3]
            if self.phase(token)=='closed':raise ValueError('effect lease fenced')
            if not cancel:
                self.db.execute('INSERT INTO effects VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',row[1:3])
            phase='cancelled' if cancel else 'done'
            self.db.execute('UPDATE operations SET phase=? WHERE id=?',(phase,number))
            return phase
        return self.mutate(action)

    def fence_if_drained(self,token):
        def action():
            phase=self.phase(token)
            pending=self.db.execute("SELECT COUNT(*) FROM operations WHERE lease=? AND phase='active'",(token,)).fetchone()[0]
            if phase=='closed':
                if pending:raise ValueError('closed lease has pending effects')
                return True
            self.db.execute("UPDATE leases SET phase=? WHERE token=?",('closing' if pending else 'closed',token))
            return not pending
        return self.mutate(action)

    def read(self,key):
        self.healthy();row=self.db.execute('SELECT value FROM effects WHERE key=?',(identifier(key),)).fetchone()
        return None if row is None else row[0]

    def disconnect(self):
        if not self.closed:self.db.close();self.closed=True

class DrainingClient:
    """Serialize core-client actions and gate all owned SQLite writes."""
    def __init__(self,client:Client,ledger:EffectLedger):
        self.client,self.ledger=client,ledger
        self.lock=asyncio.Lock()

    async def acquire(self,manifest,branches,box=None):
        async with self.lock:
            result=(await self.client.acquire(manifest,branches) if box is None else
                    await self.client.acquire_box(manifest,branches,box))
            if result['status']!='admitted':return result,None
            certificate=deepcopy(result['certificate'])
            token=lease_id(certificate)
            # Failure here leaves the protocol's durable guard held. Recovery
            # must not silently presume that application work has drained.
            if self.ledger.register(token)!='open':raise ValueError('effect lease already closed')
            return result,DrainingLease(self,certificate)

    async def resume(self,certificate):
        async with self.lock:
            if self.client._record(deepcopy(certificate)) is None:
                raise ValueError('no matching durable protocol authority')
            self.ledger.phase(lease_id(certificate))
            return DrainingLease(self,deepcopy(certificate))

class DrainingLease:
    def __init__(self,owner:DrainingClient,certificate):
        self.owner=owner;self._certificate=deepcopy(certificate);self.token=lease_id(certificate)

    async def begin_write(self,key,value):
        async with self.owner.lock:
            responses=await self.owner.client.use(self._certificate)
            if not responses or any(r is None or r.get('status')!='used' for r in responses):
                raise ValueError('protocol authority unavailable')
            return self.owner.ledger.begin(self.token,key,value)

    async def finish_write(self,number,cancel=False):
        async with self.owner.lock:
            responses=await self.owner.client.use(self._certificate)
            if not responses or any(r is None or r.get('status')!='used' for r in responses):
                raise ValueError('protocol authority unavailable')
            return self.owner.ledger.finish(self.token,number,cancel=cancel)

    async def retire(self):
        async with self.owner.lock:
            if not self.owner.ledger.fence_if_drained(self.token):return 'draining'
            if self.owner.client._record(deepcopy(self._certificate)) is None:return 'retired'
            return 'retired' if await self.owner.client.retire(self._certificate) else 'release-pending'
