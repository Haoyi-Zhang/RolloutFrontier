"""Deterministic benign origin overlaps, not an additional workload campaign."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from src.network import Network,Client
from src.checker import certificate,valid_manifest
from tests.memory_lifecycle import memory_environment,ObservedGate,queued_call


class OriginSerializationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    @contextmanager
    def environment(supports):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            yield root,Network(root,supports)

    async def overlap(self, envelope):
        with self.environment([['a'],['a']]) as (_,net):
            await net.start()
            client=Client(net)
            original=net.rpc;held=asyncio.Event();release=asyncio.Event();closes=[]
            branches=[{'0':['a'],'1':['a']}]
            async def gate(origin,node,request):
                reply=await original(origin,node,request)
                if request['op']=='close':closes.append((node,request['sequence']))
                if request['op']=='prepare' and request['manifest']=='A' and node==1:
                    held.set();await release.wait()
                return reply
            net.rpc=gate
            try:
                first=asyncio.create_task(client.acquire_box('A',branches,{'0':[['a']],'1':[['a']]})
                    if envelope else client.acquire('A',branches))
                await asyncio.wait_for(held.wait(),2)
                recovery=asyncio.create_task(client.recover())
                second=asyncio.create_task(client.acquire('B',branches))
                await asyncio.sleep(0);await asyncio.sleep(0)
                self.assertFalse(recovery.done());self.assertFalse(second.done())
                self.assertEqual(closes,[])
                self.assertEqual(next(iter(client.state['attempts'].values()))['status'],'acquiring')
                release.set()
                admitted=await asyncio.wait_for(first,2)
                self.assertEqual(admitted['status'],'admitted')
                self.assertEqual(closes,[])
                await recovery
                self.assertEqual((await second)['status'],'admitted')
                self.assertTrue(all(r['status']=='committed' for r in client.state['attempts'].values()))
                saved=deepcopy(client.state);client.disconnect();client=Client(net)
                self.assertEqual(client.state,saved)
                self.assertTrue(await client.retire(admitted['certificate']))
                self.assertTrue(all(r['manifest']!='A' for r in client.state['attempts'].values()))
            finally:
                release.set();client.disconnect();await net.stop()

    async def test_fixed_acquisition_serializes_recovery_and_another_acquisition(self):
        await self.overlap(False)
    async def test_box_acquisition_serializes_recovery_and_another_acquisition(self):
        await self.overlap(True)
    async def test_mixed_placements_reject_before_any_rpc_or_sequence(self):
        with self.environment([['a'],['b']]) as (_,net):
            await net.start();client=Client(net)
            branches=[{'0':['a']},{'1':['b']}];calls=[]
            async def forbidden(*args):calls.append(args);raise AssertionError('unexpected RPC')
            net.rpc=forbidden
            try:
                before=deepcopy(client.state)
                with self.assertRaises(ValueError):await client.acquire('bad',branches)
                with self.assertRaises(ValueError):await client.acquire_box('bad',branches,{'0':[['a']]})
                self.assertEqual(client.state,before);self.assertEqual(calls,[])
                self.assertFalse(valid_manifest(branches))
                fake=dict(manifest='bad',origin=0,branch=0,sequences={'0':1},receipts=[])
                self.assertFalse(certificate(fake,branches))
                self.assertFalse(certificate(dict(fake,mode='envelope',box={'0':[['a']]}),branches))
            finally:client.disconnect();await net.stop()


class MemoryOriginSerializationTests(OriginSerializationTests):
    """The original lifecycle assertions with no TCP or filesystem databases."""
    environment=staticmethod(memory_environment)


class QueuedInputTests(unittest.IsolatedAsyncioTestCase):
    async def acquisition_snapshot(self,envelope,keywords):
        with memory_environment([['a','b'],['a','b']]) as (_,net):
            await net.start();client=Client(net)
            try:
                branches=[{'0':['a'],'1':['a']}];original=deepcopy(branches)
                box={'0':[['a']],'1':[['a']]};original_box=deepcopy(box)
                gate=client._lifecycle_gate=ObservedGate()
                before=deepcopy(client.state)
                if envelope:
                    operation=(client.acquire_box(manifest='queued',branches=branches,box=box)
                               if keywords else client.acquire_box('queued',branches,box))
                else:
                    operation=(client.acquire(manifest='queued',branches=branches)
                               if keywords else client.acquire('queued',branches))
                def mutate():
                    self.assertEqual(client.state,before);self.assertEqual(net.requests,[])
                    for requires in branches[0].values():requires[:]=['b']
                    for options in box.values():options[0][:]=['b']
                result=await queued_call(gate,operation,mutate)
                self.assertEqual(result['status'],'admitted')
                saved=result['certificate']
                self.assertTrue(certificate(saved,original))
                self.assertFalse(certificate(saved,branches))
                if envelope:self.assertEqual(saved['box'],original_box)
                prepares=[req for _,_,req in net.requests if req['op']=='prepare']
                self.assertEqual(len(prepares),2)
                for req in prepares:
                    self.assertEqual(req['manifest'],'queued')
                    self.assertEqual(req.get('options',[req['requires']]),[['a']])
                self.assertTrue(await client.retire(saved))
            finally:client.disconnect();await net.stop()

    async def test_fixed_snapshots_before_gate_for_positional_and_keyword_inputs(self):
        for keywords in (False,True):
            with self.subTest(keywords=keywords):await self.acquisition_snapshot(False,keywords)

    async def test_box_snapshots_before_gate_for_positional_and_keyword_inputs(self):
        for keywords in (False,True):
            with self.subTest(keywords=keywords):await self.acquisition_snapshot(True,keywords)

    async def certificate_snapshot(self,action,envelope,replace):
        with memory_environment([['a','b'],['a','b']]) as (_,net):
            await net.start();client=Client(net)
            try:
                async def admit(name,atom):
                    branches=[{'0':[atom],'1':[atom]}]
                    result=(await client.acquire_box(name,branches,{'0':[[atom]],'1':[[atom]]})
                            if envelope else await client.acquire(name,branches))
                    self.assertEqual(result['status'],'admitted')
                    return result['certificate']
                first=await admit('original','a');second=await admit('other','b')
                supplied=deepcopy(first);before=deepcopy(client.state)
                net.requests.clear();gate=client._lifecycle_gate=ObservedGate()
                def mutate():
                    self.assertEqual(client.state,before);self.assertEqual(net.requests,[])
                    if replace:
                        supplied.clear();supplied.update(deepcopy(second))
                    else:
                        supplied['sequences']['0']=second['sequences']['0']
                        supplied['receipts'][0]['requires'].append('caller-only')
                        if envelope:supplied['box']['0'][0].append('caller-only')
                operation=(client.use(c=supplied) if action=='use' else client.retire(supplied))
                result=await queued_call(gate,operation,mutate)
                requests=[req for _,_,req in net.requests]
                self.assertEqual(len(requests),2)
                self.assertTrue(all(req['sequence']==first['sequences'][str(node)]
                                    for _,node,req in net.requests))
                if action=='use':
                    self.assertTrue(all(r['status']=='used' and r['manifest']=='original' for r in result))
                    self.assertEqual(client.state,before)
                else:
                    self.assertTrue(result)
                    self.assertIsNone(client._record(first))
                    self.assertIsNotNone(client._record(second))
                    self.assertTrue(all(r['status']=='used' for r in await client.use(second)))
            finally:client.disconnect();await net.stop()

    async def test_use_snapshots_nested_and_replaced_certificates_before_gate(self):
        for envelope in (False,True):
            for replace in (False,True):
                with self.subTest(envelope=envelope,replace=replace):
                    await self.certificate_snapshot('use',envelope,replace)

    async def test_retire_snapshots_nested_and_replaced_certificates_before_gate(self):
        for envelope in (False,True):
            for replace in (False,True):
                with self.subTest(envelope=envelope,replace=replace):
                    await self.certificate_snapshot('retire',envelope,replace)

    async def test_queued_use_rechecks_current_authority_after_retirement(self):
        with memory_environment([['a']]) as (_,net):
            await net.start();client=Client(net)
            try:
                saved=(await client.acquire('original',[{'0':['a']}]))['certificate']
                gate=client._lifecycle_gate=ObservedGate();net.requests.clear()
                async with gate:
                    retiring=asyncio.create_task(client.retire(saved))
                    await gate.wait_for_waiters(1)
                    using=asyncio.create_task(client.use(saved))
                    await gate.wait_for_waiters(2)
                    self.assertEqual(net.requests,[])
                self.assertTrue(await asyncio.wait_for(retiring,2))
                self.assertEqual(await asyncio.wait_for(using,2),[{'status':'not-authorized'}])
                self.assertEqual([req['op'] for _,_,req in net.requests],['close'])
            finally:client.disconnect();await net.stop()

if __name__=='__main__':unittest.main()
