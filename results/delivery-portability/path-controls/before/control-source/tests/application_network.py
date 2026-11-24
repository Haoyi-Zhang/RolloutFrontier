"""Separate application-owner processes and timestamped TCP observations."""
from __future__ import annotations
from copy import deepcopy
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time
from src.application import profile_name, LIMIT
from src.controller import canonical
from tests.multiprocess import ProcessNetwork


class ApplicationNetwork(ProcessNetwork):
    def __init__(self, directory, supports, *, kill_requests=None):
        super().__init__(directory, supports)
        self.kill_requests = dict(kill_requests or {})
        self.issued = 0

    def start_node(self, node):
        args = [sys.executable, '-B']
        if sys.flags.optimize:
            args.append('-O')
        args += ['-m', 'src.application', '--serve', str(node), '--database',
                 str(self.directory / f'process-node-{node}.sqlite'),
                 '--initial', profile_name(self.supports[node])]
        request = self.kill_requests.pop(node, None)
        if request is not None:
            args += ['--kill-after-request', request]
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1,
                                   start_new_session=True)
        ready = self._ready(process)
        if ready != {'node': node, 'port': ready.get('port'), 'status': 'ready'}:
            raise RuntimeError('malformed application readiness')
        self.processes[node] = process
        self.ports[node] = int(ready['port'])
        self.trace.append({'event': 'process-start', 'node': node, 'pid': process.pid,
                           'command': args, 'time_ns': time.perf_counter_ns()})

    async def rpc(self, source, target, req, drop=False):
        self.issued += 1
        serial = self.issued
        before = time.perf_counter_ns()
        request = (canonical(req) + '\n').encode()
        if len(request) > LIMIT:
            raise ValueError('application request exceeds frame bound')
        event = {'event': 'rpc', 'call': serial, 'source': source, 'target': target,
                 'request': deepcopy(req), 'start_ns': before}
        if drop or (source, target) in self.blocked or (target, source) in self.blocked:
            event.update(event='lost', end_ns=time.perf_counter_ns(), response=None)
            self.trace.append(event)
            return None
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', self.ports[target], limit=LIMIT + 1), 5)
            writer.write(request)
            await writer.drain()
            answer = await asyncio.wait_for(reader.readline(), 5)
            if not answer:
                raise ConnectionError('owner exited before reply')
            if len(answer) > LIMIT:
                raise ValueError('application response exceeds frame bound')
            envelope = json.loads(answer)
            response = envelope['response']
            event.update(response=response, owner_order=envelope['owner_order'],
                         bytes=len(request) + len(answer))
        except (ConnectionError, OSError, asyncio.TimeoutError, KeyError):
            response = None
            event.update(event='unreachable', response=None)
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass
        event['end_ns'] = time.perf_counter_ns()
        event['wall_ns'] = event['end_ns'] - before
        self.trace.append(event)
        return response
