"""Live authority uses the same canonical numeric types as saved certificates."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.checker import certificate
from src.effect_ledger import DrainingClient, EffectLedger
from src.network import Client, Network

RECORDS = []


class LiveCertificateTypeTests(unittest.IsolatedAsyncioTestCase):
    async def aliases(self, envelope):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);net=Network(root/'net',[['a']]);await net.start()
            core=Client(net);ledger=EffectLedger(root/'effects.sqlite')
            adapter=DrainingClient(core,ledger)
            try:
                branches=[{'0':['a']}]
                admitted,lease=await adapter.acquire('types',branches,
                    {'0':[['a']]} if envelope else None)
                good=admitted['certificate']
                paths=[('origin',),('sequences','0'),('receipts',0,'node'),
                       ('receipts',0,'origin'),('receipts',0,'sequence'),
                       ('receipts',0,'observed_generation')]
                if not envelope:paths.append(('branch',))
                observed=[]
                for path in paths:
                    for kind in (bool,float):
                        with self.subTest(path=path,kind=kind.__name__):
                            supplied=deepcopy(good);parent=supplied
                            for key in path[:-1]:parent=parent[key]
                            parent[path[-1]]=kind(parent[path[-1]])
                            self.assertEqual(supplied,good)  # The alias behind the defect.
                            self.assertFalse(certificate(supplied,branches))
                            before=deepcopy(core.state);owner=deepcopy(net.nodes[0].state)
                            length=len(net.trace)
                            self.assertEqual(await core.use(supplied),[{'status':'not-authorized'}])
                            self.assertFalse(await core.retire(supplied))
                            with self.assertRaisesRegex(ValueError,'no matching durable'):
                                await adapter.resume(supplied)
                            self.assertEqual(core.state,before);self.assertEqual(net.nodes[0].state,owner)
                            self.assertEqual(len(net.trace),length)
                            observed.append(dict(path=list(path),replacement_type=kind.__name__,
                                                 offline_rejected=True,live_rejected=True,no_rpc=True))
                self.assertTrue(all(r['status']=='used' for r in await core.use(good)))
                self.assertEqual(await lease.retire(),'retired')
                RECORDS.append(dict(mode='envelope' if envelope else 'fixed',aliases=observed))
            finally:
                ledger.disconnect();core.disconnect();await net.stop()

    async def test_fixed_live_tokens_reject_all_numeric_aliases(self):
        await self.aliases(False)

    async def test_envelope_live_tokens_reject_all_numeric_aliases(self):
        await self.aliases(True)

    async def test_missing_certificate_cannot_select_an_uncommitted_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            net=Network(Path(directory),[['a']]);await net.start();core=Client(net)
            try:
                net.blocked.add((0,0))
                self.assertEqual((await core.acquire('pending',[{'0':['a']}]))['status'],'not-justified')
                self.assertEqual(core.state['attempts']['1']['status'],'retiring')
                self.assertNotIn('certificate',core.state['attempts']['1'])
                net.blocked.clear();before=deepcopy(core.state);length=len(net.trace)
                for malformed in (None,False,0,[],{}, {'sequences':{'0':True}}):
                    with self.subTest(token=malformed):
                        self.assertEqual(await core.use(malformed),[{'status':'not-authorized'}])
                        self.assertFalse(await core.retire(malformed))
                        self.assertEqual(core.state,before);self.assertEqual(len(net.trace),length)
                await core.recover();self.assertEqual(core.state['attempts'],{})
                RECORDS.append(dict(case='uncertified attempt',malformed_inputs=6,
                                    denied_without_rpc=True,explicit_recovery_completed=True))
            finally:
                core.disconnect();await net.stop()


if __name__=='__main__':
    unittest.main(verbosity=2)
