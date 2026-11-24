"""Cancellation must not assign one request's reply to a later RPC.

These deterministic controls use actual loopback TCP and SQLite. A test reader
pauses delivery after the endpoint has persisted a reply, so cancelling the
request cannot accidentally make the endpoint's already-committed transition
vanish. The controls exercise both core acquisition modes and cancellation
while waiting for another caller's channel lock. No network timing is measured.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.network import Client, Network


class PausedRead:
    """Leave a valid reply unread on the real channel until explicitly released."""

    def __init__(self, reader, release):
        self.reader = reader
        self.release = release

    async def readline(self):
        await self.release.wait()
        return await self.reader.readline()


@asynccontextmanager
async def pause_first_reply(network, target, operation):
    actual_connect = network._connect
    endpoint = network.nodes[target]
    actual_handle = endpoint.handle
    received = asyncio.Event()
    release = asyncio.Event()
    armed = True

    def handle(request):
        result = actual_handle(request)
        if request.get('op') == operation:
            received.set()
        return result

    async def connect(node):
        nonlocal armed
        reader, writer = await actual_connect(node)
        if node == target and armed:
            armed = False
            return PausedRead(reader, release), writer
        return reader, writer

    endpoint.handle = handle
    network._connect = connect
    try:
        yield received, release
    finally:
        release.set()
        endpoint.handle = actual_handle
        network._connect = actual_connect


class CancellationLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_read_cannot_become_a_later_install_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            net = Network(Path(directory), [['a']])
            await net.start()
            try:
                async with pause_first_reply(net, 0, 'read') as (received, release):
                    first = asyncio.create_task(net.rpc(0, 0, {'op': 'read'}))
                    await asyncio.wait_for(received.wait(), 2)
                    first.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await first
                    release.set()
                    # Before the repair this consumes the cancelled read's
                    # {status: observed} reply instead of the install result.
                    reply = await net.rpc(0, 0, {'op': 'install', 'support': ['b']})
                    self.assertEqual(reply['status'], 'installed')
                    self.assertEqual(reply['observed']['support'], ['b'])
                    self.assertEqual(net.nodes[0].state['support'], ['b'])
                    self.assertEqual(net.opened_connections, 2)
            finally:
                await net.stop()

    async def cancelled_acquisition(self, envelope):
        with tempfile.TemporaryDirectory() as directory:
            net = Network(Path(directory), [['a'], ['a']])
            await net.start()
            client = Client(net)
            try:
                branches = [{'0': ['a'], '1': ['a']}]
                async with pause_first_reply(net, 0, 'prepare') as (received, release):
                    first = asyncio.create_task(
                        client.acquire_box('cancelled', branches, {'0': [['a']], '1': [['a']]})
                        if envelope else client.acquire('cancelled', branches))
                    await asyncio.wait_for(received.wait(), 2)
                    self.assertEqual(net.nodes[0].state['slots']['0:1']['status'], 'held')
                    first.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await first
                    self.assertEqual(client.state['attempts']['1']['status'], 'acquiring')
                    release.set()
                    await client.recover()
                    self.assertEqual(client.state['attempts'], {})
                    for endpoint in net.nodes.values():
                        self.assertEqual(endpoint.state['slots'], {})
                        self.assertEqual(endpoint.state['floor'][0], 1)
                    late = await net.rpc(0, 0, dict(op='prepare', origin=0, sequence=1,
                                                   manifest='cancelled', requires=['a']))
                    self.assertEqual(late['status'], 'closed')
                    # The next admission and durable reopen must not inherit a
                    # response or a sequence from the cancelled admission.
                    next_result = await client.acquire('next', branches)
                    self.assertEqual(next_result['status'], 'admitted')
                    self.assertTrue(all(r['status'] == 'used'
                                        for r in await client.use(next_result['certificate'])))
                    before = deepcopy(client.state)
                    client.disconnect()
                    client = Client(net)
                    self.assertEqual(client.state, before)
                    self.assertTrue(await client.retire(next_result['certificate']))
            finally:
                client.disconnect()
                await net.stop()

    async def test_fixed_acquisition_recovers_after_cancelled_persisted_prepare(self):
        await self.cancelled_acquisition(False)

    async def test_envelope_acquisition_recovers_after_cancelled_persisted_prepare(self):
        await self.cancelled_acquisition(True)

    async def test_cancelled_channel_waiter_cannot_drop_an_active_callers_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            net = Network(Path(directory), [['a']])
            await net.start()
            try:
                async with pause_first_reply(net, 0, 'read') as (received, release):
                    first = asyncio.create_task(net.rpc(0, 0, {'op': 'read'}))
                    await asyncio.wait_for(received.wait(), 2)
                    active_pair = net.connections[0]
                    waiter = asyncio.create_task(net.rpc(0, 0, {'op': 'install', 'support': ['b']}))
                    # Let the task reach the already-held per-target lock.
                    await asyncio.sleep(0)
                    self.assertFalse(waiter.done())
                    waiter.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await waiter
                    self.assertIs(net.connections[0], active_pair)
                    self.assertFalse(active_pair[1].is_closing())
                    release.set()
                    self.assertEqual((await first)['status'], 'observed')
                    reply = await net.rpc(0, 0, {'op': 'install', 'support': ['b']})
                    self.assertEqual(reply['status'], 'installed')
                    self.assertEqual(net.opened_connections, 1)
            finally:
                await net.stop()


if __name__ == '__main__':
    unittest.main(verbosity=2)
