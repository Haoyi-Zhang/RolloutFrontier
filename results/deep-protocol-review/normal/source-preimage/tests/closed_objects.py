"""Owned close/reopen lifecycle contract; no service on disconnected objects."""
import asyncio
from pathlib import Path
import sqlite3
import tempfile
import unittest
from src.controller import Endpoint
from src.network import Client,Network


class ClosedObjectTests(unittest.TestCase):
    def test_endpoint_cannot_downgrade_a_closed_store_to_volatile_acknowledgment(self):
        for durable in (False,True):
            with self.subTest(durable=durable),tempfile.TemporaryDirectory() as tmp:
                endpoint=Endpoint(0,['a'],Path(tmp)/'owned.sqlite' if durable else None)
                endpoint.disconnect()
                for operation in (endpoint.profile,lambda:endpoint.prepare(0,1,'owned-close',['a']),
                                  lambda:endpoint.handle({'op':'inspect'})):
                    with self.assertRaisesRegex(sqlite3.DatabaseError,'reopen'):
                        operation()

    def test_closed_origin_sends_no_authorized_use_or_recovery_frames(self):
        async def scenario(mode):
            with tempfile.TemporaryDirectory() as tmp:
                net=Network(Path(tmp),[['a']]);await net.start()
                client=Client(net)
                try:
                    branches=[{'0':['a']}]
                    result=(await client.acquire('owned-close',branches) if mode=='fixed' else
                            await client.acquire_box('owned-close',branches,{'0':[['a']]}))
                    self.assertEqual(result['status'],'admitted')
                    client.disconnect()
                    length=len(net.trace)
                    for operation in (lambda:client.use(result['certificate']),client.recover):
                        with self.assertRaisesRegex(sqlite3.DatabaseError,'reopen'):
                            await operation()
                    self.assertEqual(len(net.trace),length)
                finally:
                    client.disconnect();await net.stop()
        for mode in ('fixed','envelope'):
            with self.subTest(mode=mode):asyncio.run(scenario(mode))


if __name__=='__main__':unittest.main(verbosity=2)
