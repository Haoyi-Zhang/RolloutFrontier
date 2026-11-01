"""Owned SQLite effects are drained and fenced before protocol retirement."""
from __future__ import annotations
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from src.controller import Endpoint
from src.effect_ledger import EffectLedger,DrainingClient,lease_id
from src.network import Network,Client

class LedgerTests(unittest.TestCase):
    def test_fence_blocks_new_work_but_drains_registered_payload(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=EffectLedger(Path(d)/'effects.sqlite');token='a'*64
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
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'effects.sqlite';ledger=EffectLedger(path)
            ledger.register('a'*64);ledger.register('b'*64);op=ledger.begin('a'*64,'key','value')
            with self.assertRaises(ValueError):ledger.finish('b'*64,op)
            with self.assertRaises(ValueError):ledger.finish('a'*64,True)
            self.assertEqual(ledger.finish('a'*64,op,cancel=True),'cancelled');ledger.disconnect()
            ledger=EffectLedger(path)
            self.assertTrue(ledger.fence_if_drained('a'*64));self.assertIsNone(ledger.read('key'))
            ledger.disconnect()

    def test_non_primary_schema_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bad.sqlite';db=sqlite3.connect(path)
            db.execute('CREATE TABLE leases(token TEXT,phase TEXT NOT NULL)');db.close()
            with self.assertRaises(ValueError):EffectLedger(path)

class CoupledTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_effect_cannot_outlive_guard(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);net=Network(root/'net',[['a','b'],['a','b']]);await net.start()
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
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);net=Network(root/'net',[['a'],['a']]);await net.start()
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
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);net=Network(root/'net',[['a','b'],['a','b']]);await net.start()
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

if __name__=='__main__':unittest.main()
