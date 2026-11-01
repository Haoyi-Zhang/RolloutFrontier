"""Deterministic benign origin overlaps, not an additional workload campaign."""
import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from src.network import Network,Client
from src.checker import certificate,valid_manifest


class OriginSerializationTests(unittest.IsolatedAsyncioTestCase):
    async def overlap(self, envelope):
        with tempfile.TemporaryDirectory() as directory:
            net=Network(Path(directory),[['a'],['a']]);await net.start()
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
        with tempfile.TemporaryDirectory() as directory:
            net=Network(Path(directory),[['a'],['b']]);await net.start();client=Client(net)
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

if __name__=='__main__':unittest.main()
