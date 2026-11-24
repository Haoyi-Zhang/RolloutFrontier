"""Focused real-process semantic, recovery, and transport identity controls."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from src.controller import canonical
from src.factored_runtime import FactoredCoordinator, FactoredExecutionError
from src.factored_planner import FactoredChainPlanner
from src.factored_session import FactoredSession, SchemaRequestPending
from tests.factored_cases import graph_case
from tests.factored_network import PhysicalNetwork, RegisteredTransport


class PhysicalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='factored-runtime-control-')
        self.path = Path(self.temp.name)
        self.case = graph_case(count=3)
        self.net = PhysicalNetwork(self.path,self.case['registry'])
        self.net.start()
        self.resources = []

    async def asyncTearDown(self):
        for value in reversed(self.resources): value.disconnect()
        self.net.close()
        self.temp.cleanup()

    def coordinator(self, **kwargs):
        value = FactoredCoordinator(self.net,self.path/'rollout.sqlite',**kwargs)
        self.resources.append(value)
        return value

    async def snapshots(self):
        return {owner:(await self.net.rpc(owner,{'op':'inspect'}))['state'] for owner in self.case['owners']}

    async def worker(self, event, *, phase=0, owner='owner-000'):
        plan = self.path/'plan.json'; plan.write_text(canonical(self.case['plan'])+'\n')
        args = [sys.executable,'-B','-m','tests.factored_coordinator_worker',
                '--directory',str(self.path),'--registry',str(self.path/'registry.json'),
                '--routes',str(self.path/'relay-routes.json'),'--journal',str(self.path/'rollout.sqlite'),
                '--plan',str(plan),'--manifest','worker-job','--cut-event',event,
                '--cut-phase',str(phase),'--cut-owner',owner]
        process = await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,start_new_session=True)
        output,error = await asyncio.wait_for(process.communicate(),20)
        self.assertEqual(process.returncode,-signal.SIGKILL,error.decode()+output.decode())
        return json.loads((self.path/'coordinator-cuts.jsonl').read_text().splitlines()[-1])

    async def test_manifest_limit_and_actual_cycle(self):
        coordinator = self.coordinator(plan=self.case['plan'],manifest='m'*128)
        result = await coordinator.run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual((result['acknowledged_installs'],result['reconciled_steps']),(9,0))
        self.assertEqual(result['target_observation']['first'],result['target_observation']['second'])
        self.assertTrue(all(not v['slots'] for v in (await self.snapshots()).values()))

    async def test_actual_coordinator_kill_after_partial_acquisition(self):
        cut = await self.worker('acquire-returned')
        self.assertEqual(cut['cut']['response']['status'],'admitted')
        before = await self.snapshots()
        self.assertEqual(sum(len(s['slots']) for s in before.values()),1)
        self.assertTrue(all(s['generation'] == 0 for s in before.values()))
        result = await self.coordinator().run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['acknowledged_installs']+result['reconciled_steps'],9)

    async def test_actual_coordinator_kill_after_partial_old_retirement(self):
        cut = await self.worker('retire-returned',phase=1)
        self.assertTrue(cut['cut']['retired'])
        before = await self.snapshots()
        counts = {owner:len(v['slots']) for owner,v in before.items()}
        self.assertEqual(counts,{'owner-000':1,'owner-001':2,'owner-002':2})
        self.assertTrue(all(any(h['origin'] == 1 for h in s['slots'].values()) for s in before.values()))
        result = await self.coordinator().run()
        self.assertEqual(result['status'],'complete')
        self.assertTrue(all(not v['slots'] for v in (await self.snapshots()).values()))

    async def test_install_reply_lost_then_reconciled_once(self):
        coordinator = self.coordinator(plan=self.case['plan'],manifest='lost-install')
        await coordinator.advance()
        owner = self.case['plan']['phases'][0]['steps'][0]['node']
        await self.net.control('drop-reply',owner,operation='install_if_current')
        result = await coordinator.advance()
        self.assertEqual(result['reason'],'installation-outcome-unknown')
        self.assertEqual(coordinator.state['step_index'],0)
        self.assertEqual((await self.snapshots())[owner]['generation'],1)
        coordinator.disconnect()
        recovered = self.coordinator()
        result = await recovered.run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual((result['acknowledged_installs'],result['reconciled_steps']),(8,1))
        events = [json.loads(line) for line in (self.path/'relay-events.jsonl').read_text().splitlines()]
        drops = [e for e in events if e['event'] == 'reply-discarded-after-owner']
        self.assertEqual(len(drops),1)
        self.assertEqual(drops[0]['response']['response']['status'],'installed')

    async def test_actual_coordinator_kill_after_install_receipt(self):
        await self.worker('install-returned')
        result = await self.coordinator().run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual((result['acknowledged_installs'],result['reconciled_steps']),(8,1))

    async def test_old_retirement_reply_lost_keeps_new_global_phase(self):
        await self.worker('retire-returned',phase=1)
        coordinator = self.coordinator()
        await self.net.control('drop-reply','owner-001',operation='close')
        answer = await coordinator.advance()
        self.assertEqual(answer['reason'],'old-phase-release-pending')
        owners = await self.snapshots()
        self.assertTrue(all(any(h.get('origin') == 1 for h in state['slots'].values()) for state in owners.values()))
        coordinator.disconnect()
        recovered = self.coordinator()
        self.assertEqual((await recovered.run())['status'],'complete')
        self.assertTrue(all(not s['slots'] for s in (await self.snapshots()).values()))

    async def test_registry_catalog_and_wrong_owner_rejected(self):
        coordinator = self.coordinator(plan=self.case['plan'],manifest='bound')
        await coordinator.advance()
        coordinator.disconnect()
        altered = deepcopy(self.net.registry)
        altered['owners']['owner-000']['catalog'][0].append('foreign')
        transport = RegisteredTransport(self.path,altered,self.net.ports,trace_name='altered.jsonl')
        self.resources.append(transport)
        with self.assertRaises(FactoredExecutionError):
            FactoredCoordinator(transport,self.path/'rollout.sqlite')
        port = self.net.ports['owner-000']
        self.net.ports['owner-000'] = self.net.ports['owner-001']
        try:
            for request in ({'op':'read'}, {'op':'prepare','origin':4,'sequence':1,'manifest':'wrong',
                                          'requires':[]}):
                with self.assertRaises(FactoredExecutionError): await self.net.rpc('owner-000',request)
        finally: self.net.ports['owner-000'] = port
        self.assertEqual((await self.coordinator().run())['status'],'complete')

    async def test_global_certificate_substitution_rejected(self):
        coordinator = self.coordinator(plan=self.case['plan'],manifest='pointer')
        await coordinator.advance(); coordinator.disconnect()
        with sqlite3.connect(self.path/'rollout.sqlite') as db:
            state = json.loads(db.execute('SELECT payload FROM state').fetchone()[0])
            cert = state['certificates']['0']['owner-000']
            cert['sequences']['0'] += 1; cert['receipts'][0]['sequence'] += 1
            db.execute('UPDATE state SET payload=?',(canonical(state),))
        with self.assertRaises(FactoredExecutionError): self.coordinator()

    async def test_actual_tcp_cut_preserves_live_owner_and_recovers(self):
        coordinator = self.coordinator(plan=self.case['plan'],manifest='tcp-cut')
        await coordinator.advance()
        before = await self.snapshots()
        owner = self.case['plan']['phases'][0]['steps'][0]['node']
        pid = self.net.processes[owner].pid
        await self.net.control('cut',owner)
        result = await coordinator.advance()
        self.assertEqual(result['reason'],'owner-unreachable')
        self.assertIsNone(self.net.processes[owner].poll())
        self.assertEqual(self.net.processes[owner].pid,pid)
        await self.net.control('restore',owner)
        self.assertEqual(await self.snapshots(),before)
        self.assertEqual((await coordinator.run())['status'],'complete')
        events = [json.loads(line) for line in (self.path/'relay-events.jsonl').read_text().splitlines()]
        self.assertTrue(any(e['event'] == 'cut-closed-request' for e in events))
        self.assertTrue(any(e['event'] == 'link-restored' for e in events))

    async def test_pending_dataflow_retains_all_guards_across_owner_death(self):
        session = await FactoredSession.begin(self.net,self.path/'session.sqlite',self.case['workflow'],'flow')
        self.resources.append(session)
        killed = 'owner-001'
        await self.net.restart_owner(killed,kill_after_request='pending:h0001')
        with self.assertRaises(SchemaRequestPending):
            await session.request('pending',{'key':'κλειδί','value':7,'status':1})
        self.assertFalse(await session.close())
        with self.assertRaises(ValueError):
            await session.request('new-id',{'key':'κλειδί','value':7,'status':1})
        self.net.processes[killed].wait(timeout=5)
        self.assertEqual(self.net.processes[killed].returncode,-signal.SIGKILL)
        session.disconnect()
        await self.net.restart_owner(killed,kill=False)
        restored = FactoredSession(self.net,self.path/'session.sqlite'); self.resources.append(restored)
        output = await restored.request('pending',{'key':'κλειδί','value':7,'status':1})
        self.assertTrue(output['steps']['h0001']['duplicate'])
        self.assertTrue(await restored.close())
        with sqlite3.connect(self.net.database(killed)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM schema_results').fetchone()[0],1)
        self.assertTrue(all(not s['slots'] for s in (await self.snapshots()).values()))

    async def test_request_input_snapshot_and_sequential_session_sequences(self):
        session = await FactoredSession.begin(self.net,self.path/'first.sqlite',self.case['workflow'],'first')
        self.resources.append(session)
        reached,release = asyncio.Event(),asyncio.Event()
        async def pause(step,response):
            if step['id'] == 'h0000': reached.set(); await release.wait()
        value = {'key':'original','value':23,'status':1}
        task = asyncio.create_task(session.request('snapshot',value,after_step=pause))
        await asyncio.wait_for(reached.wait(),5)
        value['key']='changed'; value['value']=-99
        release.set()
        result = await task
        self.assertEqual(result['records']['h0003'],{'key':'original','value':23,'status':1})
        self.assertTrue(await session.close()); session.disconnect()
        later = await FactoredSession.begin(self.net,self.path/'second.sqlite',self.case['workflow'],'second')
        self.resources.append(later)
        self.assertEqual(later.state['stage'],'open')
        self.assertTrue(all(cert['sequences']['0'] == 2 for cert in later.state['certificates'].values()))
        result = await later.request('snapshot',{'key':'later','value':1,'status':1})
        self.assertEqual(result['records']['h0003'],{'key':'later','value':1,'status':1})
        self.assertTrue(all(not r['duplicate'] for r in result['steps'].values()))
        self.assertTrue(await later.close())
        with sqlite3.connect(self.net.database('owner-001')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM schema_results WHERE request_id=?',('snapshot:h0001',)).fetchone()[0],2)
        later.disconnect()
        reused = await FactoredSession.begin(self.net,self.path/'third.sqlite',self.case['workflow'],'first')
        self.resources.append(reused)
        result = await reused.request('snapshot',{'key':'reused-manifest','value':4,'status':1})
        self.assertEqual(result['records']['h0003'],{'key':'reused-manifest','value':4,'status':1})
        self.assertTrue(all(not r['duplicate'] for r in result['steps'].values()))
        self.assertEqual(reused.state['admission_certificates']['owner-001']['sequences']['0'],3)
        self.assertTrue(await reused.close())
        with sqlite3.connect(self.net.database('owner-001')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM schema_results WHERE request_id=?',('snapshot:h0001',)).fetchone()[0],3)

    async def test_actual_field_addition_join_normalizes_declared_metadata(self):
        case = graph_case('field-addition',5,'fanout-join',deployment='metadata-control')
        net = PhysicalNetwork(self.path/'metadata',case['registry']); net.start()
        session = None
        try:
            profiles = case['registry']['owners']['owner-000']['catalog']
            # Prepare the receiving join and all branch parsers before changing
            # two branch serializers. Every edge stays parser-compatible.
            for owner,rank in [('owner-004',1),('owner-001',1),('owner-002',1),
                               ('owner-003',1),('owner-001',2),('owner-003',2)]:
                self.assertEqual((await net.rpc(owner,{'op':'install','support':profiles[rank]}))['status'],'installed')
            session = await FactoredSession.begin(net,self.path/'metadata'/'session.sqlite',case['workflow'],'mixed-tags')
            result = await session.request('mixed-join',{'key':'join','value':42,'tag':''})
            self.assertEqual(result['records']['h004'],{'key':'join','value':42,'tag':''})
            self.assertEqual([result['steps'][name]['output']['record']['tag'] for name in ['h001','h002','h003']],
                             ['migrated-δ','','migrated-δ'])
            self.assertTrue(await session.close())
        finally:
            if session: session.disconnect()
            net.close()

    async def test_concurrent_exact_retries_share_first_complete_result(self):
        session = await FactoredSession.begin(self.net,self.path/'concurrent.sqlite',self.case['workflow'],'concurrent')
        self.resources.append(session)
        reached,release = asyncio.Event(),asyncio.Event()
        async def pause(step,response):
            if step['id'] == 'h0000': reached.set(); await release.wait()
        value = {'key':'same','value':17,'status':1}
        early = asyncio.create_task(session.request('same-id',value,after_step=pause))
        await asyncio.wait_for(reached.wait(),5)
        winner = await session.request('same-id',value)
        release.set()
        self.assertEqual(await early,winner)
        self.assertEqual(await session.request('same-id',value),winner)
        self.assertTrue(await session.close())
        for owner in self.case['owners']:
            with sqlite3.connect(self.net.database(owner)) as db:
                expected = 2 if owner == 'owner-000' else 1
                self.assertEqual(db.execute('SELECT count(*) FROM schema_results').fetchone()[0],expected)

    async def test_integer_domain_rejected_before_pending_binding(self):
        case = graph_case('integer-widening',3,'cycle',deployment='integer-domain-control')
        net = PhysicalNetwork(self.path/'integer',case['registry']); net.start()
        session = None
        try:
            session = await FactoredSession.begin(net,self.path/'integer'/'session.sqlite',case['workflow'],'narrow')
            with self.assertRaises(ValueError):
                await session.request('outside-domain',{'key':'wide','value':1<<40})
            self.assertEqual(session.db.execute('SELECT count(*) FROM requests').fetchone()[0],0)
            self.assertTrue(await session.close())
        finally:
            if session: session.disconnect()
            net.close()

    async def test_successive_rollouts_reuse_bootstrap_registry_and_allocators(self):
        base = self.case['plan']
        planner = FactoredChainPlanner(base['factors'],base['catalog'],base['transitions'])
        middle = {owner:base['catalog'][owner][1] for owner in self.case['owners']}
        first_plan = planner.plan(base['initial'],middle)
        first = self.coordinator(plan=first_plan,manifest='successive')
        self.assertEqual((await first.run())['status'],'complete')
        first.disconnect()
        second_plan = planner.plan(middle,base['target'])
        second = FactoredCoordinator(self.net,self.path/'later-rollout.sqlite',plan=second_plan,manifest='successive')
        self.resources.append(second)
        self.assertEqual((await second.run())['status'],'complete')
        self.assertEqual(second.state['acknowledged_installs'],6)
        self.assertEqual(self.net.registry['owners']['owner-000']['initial'],base['initial']['owner-000'])
        second.disconnect()
        stale = FactoredCoordinator(self.net,self.path/'stale-rollout.sqlite',plan=second_plan,manifest='stale')
        self.resources.append(stale)
        before = await self.snapshots()
        answer = await stale.advance()
        self.assertEqual(answer['status'],'deviation')
        self.assertEqual(answer['reason'],'phase-source-differs')
        self.assertEqual(await self.snapshots(),before)

    async def test_active_phase_authority_is_bound_to_its_complete_plan(self):
        base = self.case['plan']
        planner = FactoredChainPlanner(base['factors'],base['catalog'],base['transitions'])
        middle = {owner:base['catalog'][owner][1] for owner in self.case['owners']}
        first_plan = planner.plan(base['initial'],middle)
        first = self.coordinator(plan=first_plan,manifest='same-label')
        self.assertEqual((await first.advance())['status'],'progress')
        first.disconnect()
        before = await self.snapshots()
        with self.assertRaises(FactoredExecutionError):
            FactoredCoordinator(self.net,self.path/'different-plan.sqlite',plan=base,manifest='same-label')
        self.assertEqual(await self.snapshots(),before)
        self.assertEqual((await self.coordinator().run())['status'],'complete')


if __name__ == '__main__': unittest.main()
