"""Finite lifecycle fixtures: real SQLite in RAM, direct owned endpoints, no sockets.

Keeper connections preserve each named in-memory database across object reopen.
This tests logical reopen, not disk durability or transport behavior.
"""
import asyncio
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import sqlite3
from unittest.mock import patch
from urllib.parse import quote
from uuid import uuid4

from src.controller import Endpoint


class MemoryPath:
    def __init__(self, prefix, parts=()):
        self.prefix, self.parts = prefix, parts

    def __truediv__(self, name):
        return MemoryPath(self.prefix, self.parts + (str(name),))

    def __str__(self):
        return self.prefix + quote('/'.join(self.parts), safe='') + '?mode=memory&cache=shared'


@contextmanager
def memory_storage():
    root = MemoryPath('file:rollout-test-' + uuid4().hex + '-')
    connect = sqlite3.connect
    keepers = {}

    def memory_connect(database, *args, **kwargs):
        name = str(database)
        if not name.startswith(root.prefix):
            raise AssertionError('memory lifecycle test attempted a filesystem database')
        if name not in keepers:
            keepers[name] = connect(name, uri=True)
        return connect(name, *args, **dict(kwargs, uri=True))

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(sqlite3, 'connect', memory_connect))
            stack.enter_context(patch.object(asyncio, 'start_server', side_effect=AssertionError('no sockets')))
            stack.enter_context(patch.object(asyncio, 'open_connection', side_effect=AssertionError('no sockets')))
            yield root
    finally:
        for connection in keepers.values():
            connection.close()


class MemoryNetwork:
    def __init__(self, directory, supports, policy='predicate', window=8):
        self.directory, self.supports = directory, deepcopy(supports)
        self.policy, self.window = policy, window
        self.nodes, self.blocked, self.requests = {}, set(), []

    def __deepcopy__(self, memo):
        raise AssertionError('runtime/RPC objects must not be snapshotted')

    async def start(self):
        for node, support in enumerate(self.supports):
            self.nodes[node] = Endpoint(node, support, self.directory / f'node-{node}.sqlite',
                                        self.window, self.policy)

    async def stop(self):
        for endpoint in self.nodes.values():
            endpoint.disconnect()
        self.nodes.clear()

    async def rpc(self, source, target, request):
        request = deepcopy(request)
        self.requests.append((source, target, request))
        if (source, target) in self.blocked or (target, source) in self.blocked:
            return None
        return deepcopy(self.nodes[target].handle(request))


@contextmanager
def memory_environment(supports):
    with memory_storage() as root:
        yield root, MemoryNetwork(root / 'net', supports)


class ObservedGate:
    """Observe an actual contended lock, rather than guessing with sleeps."""
    def __init__(self):
        self.lock = asyncio.Lock()
        self.waiters = 0
        self.changed = asyncio.Event()

    def __deepcopy__(self, memo):
        raise AssertionError('lifecycle locks must not be snapshotted')

    async def __aenter__(self):
        if self.lock.locked():
            self.waiters += 1
            self.changed.set()
        await self.lock.acquire()
        return self

    async def __aexit__(self, *exc):
        self.lock.release()

    async def wait_for_waiters(self, count=1):
        async def observe():
            while self.waiters < count:
                self.changed.clear()
                await self.changed.wait()
        await asyncio.wait_for(observe(), 2)


async def queued_call(gate, operation, change_inputs):
    async with gate:
        task = asyncio.create_task(operation)
        try:
            await gate.wait_for_waiters()
            change_inputs()
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    return await asyncio.wait_for(task, 2)
