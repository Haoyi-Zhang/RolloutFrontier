"""Behavioral and recovery tests for the executable ProtoJSON pipeline."""
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from google.protobuf import json_format
from src.application import ApplicationEndpoint, PROFILES, PROGRAMS, PipelineSession, decode, encode, pipeline_branch, INPUT_MIN, INPUT_MAX
from src.network import Client
from tests.application_network import ApplicationNetwork

class HandlerTests(unittest.TestCase):
    def test_real_protojson_alias_order_and_removal(self):
        for name, aliases in PROGRAMS.items():
            wire = encode(name, {'key': 'α', 'amount': 0})
            self.assertEqual(json.loads(wire)['state'], aliases[0])
            for alias in ('ACTIVE', 'ENABLED'):
                data = json.loads(wire); data['state'] = alias
                if alias in aliases:
                    self.assertEqual(decode(name, json.dumps(data), alias), {'key': 'α', 'amount': 0})
                else:
                    with self.assertRaises(json_format.ParseError): decode(name, json.dumps(data), alias)

    def test_unregistered_program_cannot_change_durable_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'owner.sqlite'
            owner = ApplicationEndpoint(0, PROFILES['legacy'], path)
            response = owner.handle({'op': 'install', 'support': ['emit:ACTIVE']})
            self.assertEqual(response['status'], 'invalid'); self.assertEqual(owner.profile()['generation'], 0)
            owner.disconnect()
            reopened = ApplicationEndpoint(0, PROFILES['legacy'], path)
            self.assertEqual(reopened.profile()['support'], PROFILES['legacy']); reopened.disconnect()

    def test_broad_rollout_authority_does_not_authorize_business_codec(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner = ApplicationEndpoint(0, PROFILES['accepting'], Path(temporary) / 'owner.sqlite')
            owner.prepare(2, 1, 'broad', [], [[]])
            response = owner.handle({'op': 'application', 'origin': 2, 'sequence': 1, 'manifest': 'broad',
                'request_id': 'broad', 'codec': ['ACTIVE', 'ACTIVE'], 'input': {'key': 'x', 'amount': 1}})
            self.assertEqual(response['status'], 'codec-not-retained')
            self.assertEqual(owner.db.execute('SELECT COUNT(*) FROM application_results').fetchone()[0], 0)
            owner.disconnect()

    def test_sqlite_effect_abort_is_fail_closed_and_reopens_without_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'owner.sqlite'
            owner = ApplicationEndpoint(0, PROFILES['legacy'], path); owner.prepare(2, 1, 'effect', ['emit:ACTIVE'])
            owner.db.execute("CREATE TRIGGER abort_effect BEFORE INSERT ON application_results BEGIN SELECT RAISE(ABORT,'effect abort'); END"); owner.db.commit()
            request = {'op': 'application', 'origin': 2, 'sequence': 1, 'manifest': 'effect',
                'request_id': 'transaction', 'codec': ['ACTIVE', 'ACTIVE'], 'input': {'key': 'x', 'amount': 4}}
            with self.assertRaises(sqlite3.DatabaseError): owner.handle(request)
            with self.assertRaises(sqlite3.DatabaseError): owner.profile()
            owner.disconnect(); reopened = ApplicationEndpoint(0, PROFILES['legacy'], path)
            self.assertEqual(reopened.db.execute('SELECT COUNT(*) FROM application_results').fetchone()[0], 0)
            self.assertEqual(reopened.profile()['generation'], 0); reopened.disconnect()

    def test_same_request_id_cannot_change_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner = ApplicationEndpoint(0, PROFILES['legacy'], Path(temporary) / 'owner.sqlite'); owner.prepare(2, 1, 'once', ['emit:ACTIVE'])
            request = {'op': 'application', 'origin': 2, 'sequence': 1, 'manifest': 'once',
                'request_id': 'one', 'codec': ['ACTIVE', 'ACTIVE'], 'input': {'key': 'x', 'amount': 4}}
            first = owner.handle(request); duplicate = owner.handle(request); request['input']['amount'] = 5; conflict = owner.handle(request)
            self.assertFalse(first['duplicate']); self.assertTrue(duplicate['duplicate']); self.assertEqual(conflict['status'], 'request-conflict')
            self.assertEqual(owner.db.execute('SELECT COUNT(*) FROM application_results').fetchone()[0], 1); owner.disconnect()

    def test_reopen_detects_corrupted_application_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'owner.sqlite'; owner = ApplicationEndpoint(0, PROFILES['legacy'], path); owner.prepare(2, 1, 'effect', ['emit:ACTIVE'])
            owner.handle({'op': 'application', 'origin': 2, 'sequence': 1, 'manifest': 'effect',
                'request_id': 'one', 'codec': ['ACTIVE', 'ACTIVE'], 'input': {'key': 'x', 'amount': 4}})
            owner.db.execute("UPDATE application_results SET output='{}'"); owner.db.commit(); owner.disconnect()
            with self.assertRaisesRegex(ValueError, 'retained application result'): ApplicationEndpoint(0, PROFILES['legacy'], path)

    def test_transform_domain_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner = ApplicationEndpoint(0, PROFILES['legacy'], Path(temporary) / 'owner.sqlite')
            for value in (INPUT_MIN,INPUT_MAX):
                output = owner.compute('legacy', ['ACTIVE','ACTIVE'], {'key':'edge','amount':value})
                self.assertEqual(int(json.loads(output['wire'])['amount']),value)
            for value in (INPUT_MIN-1,INPUT_MAX+1):
                with self.assertRaisesRegex(ValueError,'transform domain'):
                    owner.compute('legacy',['ACTIVE','ACTIVE'],{'key':'edge','amount':value})
            owner.disconnect()

class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.net = ApplicationNetwork(Path(self.temporary.name), [PROFILES['accepting'] for _ in range(3)])
        self.net.start(); self.client = Client(self.net, 2)
    async def asyncTearDown(self):
        self.client.disconnect(); self.net.stop(); self.temporary.cleanup()
    async def lease(self, name='lease'):
        response = await self.client.acquire(name, [pipeline_branch(['ACTIVE', 'ACTIVE'])]); self.assertEqual(response['status'], 'admitted')
        return PipelineSession(self.client, response['certificate'], ['ACTIVE', 'ACTIVE'])
    async def test_retirement_drains_inflight_request_before_codec_removal(self):
        lease = await self.lease(); entered, finish = asyncio.Event(), asyncio.Event()
        async def pause(): entered.set(); await finish.wait()
        task = asyncio.create_task(lease.request('active', {'key': 'drain', 'amount': 11}, after_encode=pause)); await entered.wait()
        retiring = asyncio.create_task(lease.retire()); await asyncio.sleep(0)
        blocked = await self.net.rpc(0, 2, {'op': 'install', 'support': PROFILES['current']})
        self.assertEqual(blocked['status'], 'blocked'); self.assertFalse(retiring.done())
        with self.assertRaisesRegex(ValueError, 'draining'): await lease.request('late', {'key': 'late', 'amount': 0})
        finish.set(); result = await task; self.assertEqual(result['record'], {'key': 'drain', 'amount': 40}); self.assertTrue(await retiring)
        installed = await self.net.rpc(0, 2, {'op': 'install', 'support': PROFILES['current']}); self.assertEqual(installed['status'], 'installed')
    async def test_lost_sink_reply_is_recovered_from_actual_committed_effect(self):
        self.net.stop_node(2); self.net.kill_requests[2] = 'uncertain'; self.net.start_node(2); lease = await self.lease()
        with self.assertRaises(RuntimeError): await lease.request('uncertain', {'key': 'once', 'amount': -7})
        self.assertEqual(self.net.processes[2].wait(timeout=5), -9)
        with sqlite3.connect(self.net.directory / 'process-node-2.sqlite') as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM application_results').fetchone()[0], 1)
        self.assertFalse(await lease.retire())
        certificate, codec = lease.certificate, lease.codec
        with self.assertRaisesRegex(ValueError, 'binding differs'): await lease.request('uncertain', {'key': 'once', 'amount': -6})
        self.client.disconnect(); self.client = Client(self.net, 2)
        lease = PipelineSession(self.client, certificate, codec)
        self.net.crash(2); response = await lease.request('uncertain', {'key': 'once', 'amount': -7})
        self.assertEqual(response['record'], {'key': 'once', 'amount': -14}); self.assertTrue(all(row['duplicate'] for row in response['owner_replies'])); self.assertTrue(await lease.retire())
    async def test_owner_sqlite_abort_closes_channel_and_preserves_retry_authority(self):
        lease = await self.lease()
        path = self.net.directory / 'process-node-2.sqlite'
        with sqlite3.connect(path) as db:
            db.execute("CREATE TRIGGER abort_effect BEFORE INSERT ON application_results BEGIN SELECT RAISE(ABORT,'effect abort'); END")
        with self.assertRaises(RuntimeError):
            await lease.request('store-abort', {'key':'retry','amount':5})
        self.assertFalse(await lease.retire())
        unavailable = await self.net.rpc(0,2,{'op':'read'})
        self.assertIsNone(unavailable)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_results').fetchone()[0],0)
            state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            self.assertTrue(any(h.get('origin')==2 and h.get('status')=='held' for h in state['slots'].values()))
            db.execute('DROP TRIGGER abort_effect')
        self.net.crash(2)
        result = await lease.request('store-abort', {'key':'retry','amount':5})
        self.assertEqual(result['record'],{'key':'retry','amount':22})
        self.assertEqual([r['duplicate'] for r in result['owner_replies']],[True,True,False])
        self.assertTrue(await lease.retire())

    async def test_removing_guard_rejects_real_downstream_work(self):
        lease = await self.lease(); certificate = lease.certificate
        await self.net.rpc(2, 1, {'op': 'close', 'origin': 2, 'sequence': certificate['sequences']['1']})
        with self.assertRaises(RuntimeError): await lease.request('unprotected', {'key': 'reject', 'amount': 5})
        with sqlite3.connect(self.net.directory / 'process-node-1.sqlite') as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM application_results').fetchone()[0], 0)
        self.assertFalse(await lease.retire())
    async def test_sixteen_concurrent_requests_have_distinct_durable_results(self):
        lease = await self.lease(); results = await asyncio.gather(*(lease.request('request-' + str(i), {'key': str(i), 'amount': i}) for i in range(16)))
        self.assertEqual([row['record']['amount'] for row in results], [3 * i + 7 for i in range(16)]); self.assertTrue(await lease.retire())
        for node in range(3):
            with sqlite3.connect(self.net.directory / f'process-node-{node}.sqlite') as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM application_results').fetchone()[0], 16)

if __name__ == '__main__': unittest.main(verbosity=2)
