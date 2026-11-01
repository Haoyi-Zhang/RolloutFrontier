"""Owned SQLite effects are drained and fenced before protocol retirement."""
from __future__ import annotations
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from src.controller import Endpoint
from src.effect_ledger import EffectLedger,DrainingClient,lease_id
from src.network import Network,Client
from src.checker import certificate
from tests.memory_lifecycle import memory_environment,memory_storage,ObservedGate,queued_call

class LedgerTests(unittest.TestCase):
    @staticmethod
    @contextmanager
    def storage():
        with tempfile.TemporaryDirectory() as d:yield Path(d)

    def test_fence_blocks_new_work_but_drains_registered_payload(self):
        with self.storage() as root:
            ledger=EffectLedger(root/'effects.sqlite');token='a'*64
            ledger.register(token);op=ledger.begin(token,'key','bound-value')
            self.assertFalse(ledger.fence_if_drained(token))
            with self.assertRaises(ValueError):ledger.begin(token,'new','value')
            self.assertEqual(ledger.finish(token,op),'done')
            self.assertTrue(ledger.fence_if_drained(token))
            self.assertEqual(ledger.read('key'),'bound-value')
            self.assertEqual(ledger.finish(token,op),'already-done')
            with self.assertRaises(ValueError):ledger.begin(token,'new','value')
            ledger.disconnect()

    def test_cancel_persists_and_wrong_lease_never_writes(self):
        with self.storage() as root:
            path=root/'effects.sqlite';ledger=EffectLedger(path)
            ledger.register('a'*64);ledger.register('b'*64);op=ledger.begin('a'*64,'key','value')
            with self.assertRaises(ValueError):ledger.finish('b'*64,op)
            with self.assertRaises(ValueError):ledger.finish('a'*64,True)
            self.assertEqual(ledger.finish('a'*64,op,cancel=True),'cancelled');ledger.disconnect()
            ledger=EffectLedger(path)
            self.assertTrue(ledger.fence_if_drained('a'*64));self.assertIsNone(ledger.read('key'))
            ledger.disconnect()

    def test_non_primary_schema_rejected(self):
        with self.storage() as root:
            path=root/'bad.sqlite';db=sqlite3.connect(str(path))
            db.execute('CREATE TABLE leases(token TEXT,phase TEXT NOT NULL)');db.close()
            with self.assertRaises(ValueError):EffectLedger(path)

class CoupledTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    @contextmanager
    def environment(supports):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            yield root,Network(root/'net',supports)

    async def test_actual_effect_cannot_outlive_guard(self):
        with self.environment([['a','b'],['a','b']]) as (root,net):
            await net.start()
            core=Client(net);ledger=EffectLedger(root/'effects.sqlite');owner=DrainingClient(core,ledger)
            try:
                admitted,lease=await owner.acquire('write',[{'0':['a'],'1':['a']}])
                self.assertEqual(admitted['status'],'admitted')
                number=await lease.begin_write('counter','written')
                self.assertEqual(await lease.retire(),'draining')
                self.assertEqual((await net.rpc(0,0,dict(op='install',support=['b'])))['status'],'blocked')
                self.assertEqual(await lease.finish_write(number),'done')
                self.assertEqual(await lease.retire(),'retired')
                self.assertEqual((await net.rpc(0,0,dict(op='install',support=['b'])))['status'],'installed')
                with self.assertRaises(ValueError):await lease.finish_write(number)
                self.assertEqual(ledger.read('counter'),'written')
                self.assertEqual(await lease.retire(),'retired')
            finally:ledger.disconnect();core.disconnect();await net.stop()

    async def test_restart_does_not_erase_inflight_effect(self):
        with self.environment([['a'],['a']]) as (root,net):
            await net.start()
            core=Client(net);path=root/'effects.sqlite';ledger=EffectLedger(path)
            try:
                owner=DrainingClient(core,ledger);admitted,lease=await owner.acquire('write',[{'0':['a']}])
                number=await lease.begin_write('key','value');await lease.retire()
                ledger.disconnect();core.disconnect();core=Client(net);await core.recover();ledger=EffectLedger(path)
                lease=await DrainingClient(core,ledger).resume(admitted['certificate'])
                self.assertEqual(await lease.retire(),'draining')
                await lease.finish_write(number,cancel=True)
                self.assertEqual(await lease.retire(),'retired');self.assertIsNone(ledger.read('key'))
            finally:ledger.disconnect();core.disconnect();await net.stop()

    async def test_envelope_and_failed_release_remain_fenced(self):
        with self.environment([['a','b'],['a','b']]) as (root,net):
            await net.start()
            core=Client(net);ledger=EffectLedger(root/'effects.sqlite')
            try:
                owner=DrainingClient(core,ledger)
                admitted,lease=await owner.acquire('envelope',[{'0':['a'],'1':['a']}],{'0':[['a']],'1':[['a']]})
                self.assertEqual(admitted['status'],'admitted')
                number=await lease.begin_write('key','value');await lease.finish_write(number)
                net.blocked.add((0,1));self.assertEqual(await lease.retire(),'release-pending')
                with self.assertRaises(ValueError):await lease.begin_write('late','not-written')
                net.blocked.clear();self.assertEqual(await lease.retire(),'retired')
            finally:ledger.disconnect();core.disconnect();await net.stop()


class MemoryLedgerTests(LedgerTests):
    storage=staticmethod(memory_storage)


class MemoryCoupledTests(CoupledTests):
    """Reuse all original effect-lifetime assertions without disk or TCP."""
    environment=staticmethod(memory_environment)


class QueuedDrainInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_snapshots_before_outer_and_core_gates(self):
        for envelope in (False,True):
            for outer in (False,True):
                with self.subTest(envelope=envelope,outer=outer):
                    with memory_environment([['a','b'],['a','b']]) as (root,net):
                        await net.start();core=Client(net);ledger=EffectLedger(root/'effects.sqlite')
                        owner=DrainingClient(core,ledger)
                        try:
                            gate=ObservedGate()
                            if outer:owner.lock=gate
                            else:core._lifecycle_gate=gate
                            branches=[{'0':['a'],'1':['a']}];original=deepcopy(branches)
                            box={'0':[['a']],'1':[['a']]};original_box=deepcopy(box)
                            before=deepcopy(core.state)
                            def mutate():
                                self.assertEqual(core.state,before);self.assertEqual(net.requests,[])
                                self.assertEqual(ledger.db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],0)
                                for requires in branches[0].values():requires[:]=['b']
                                for options in box.values():options[0][:]=['b']
                            result,lease=await queued_call(gate,owner.acquire('queued',branches,
                                box=box if envelope else None),mutate)
                            self.assertEqual(result['status'],'admitted')
                            self.assertTrue(certificate(result['certificate'],original))
                            self.assertFalse(certificate(result['certificate'],branches))
                            self.assertEqual(lease._certificate,result['certificate'])
                            self.assertEqual(lease.token,lease_id(result['certificate']))
                            if envelope:self.assertEqual(result['certificate']['box'],original_box)
                            prepares=[req for _,_,req in net.requests if req['op']=='prepare']
                            self.assertEqual(len(prepares),2)
                            self.assertTrue(all(req.get('options',[req['requires']])==[['a']] for req in prepares))
                            self.assertEqual(await lease.retire(),'retired')
                        finally:ledger.disconnect();core.disconnect();await net.stop()

    async def test_resume_snapshots_nested_and_replaced_certificates_before_outer_gate(self):
        for replace in (False,True):
            with self.subTest(replace=replace):
                with memory_environment([['a','b']]) as (root,net):
                    await net.start();core=Client(net);ledger=EffectLedger(root/'effects.sqlite')
                    owner=DrainingClient(core,ledger)
                    try:
                        first,first_lease=await owner.acquire('original',[{'0':['a']}])
                        second,_=await owner.acquire('other',[{'0':['b']}])
                        supplied=deepcopy(first['certificate']);gate=owner.lock=ObservedGate()
                        before=deepcopy(core.state);net.requests.clear()
                        def mutate():
                            self.assertEqual(core.state,before);self.assertEqual(net.requests,[])
                            if replace:
                                supplied.clear();supplied.update(deepcopy(second['certificate']))
                            else:supplied['receipts'][0]['requires'].append('caller-only')
                        resumed=await queued_call(gate,owner.resume(supplied),mutate)
                        self.assertEqual(resumed._certificate,first['certificate'])
                        self.assertEqual(resumed.token,first_lease.token)
                        number=await resumed.begin_write('key','original-value')
                        self.assertEqual(await resumed.finish_write(number),'done')
                        self.assertEqual(ledger.read('key'),'original-value')
                        self.assertTrue(all(req['manifest']=='original' for _,_,req in net.requests))
                        self.assertEqual(await resumed.retire(),'retired')
                        self.assertIsNotNone(core._record(second['certificate']))
                    finally:ledger.disconnect();core.disconnect();await net.stop()

if __name__=='__main__':unittest.main()
