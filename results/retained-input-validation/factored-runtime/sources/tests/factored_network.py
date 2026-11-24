"""Actual owner processes and identity-checked transport for factored execution."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

from src.controller import canonical
from src.factored_runtime import FactoredExecutionError
from src.schema_runtime import LIMIT, identity_for


class RegisteredTransport:
    """Every response, including reads and retries, checks full physical identity."""
    def __init__(self, directory, registry, ports, *, window=8, trace_name='transport.jsonl'):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.registry, self.ports = deepcopy(registry), dict(ports)
        self.window, self.policy = window, 'predicate'
        self.trace = []
        self.issued = 0
        self._trace_file = open(self.directory/trace_name, 'a', encoding='utf-8', buffering=1)

    def record(self, event, **details):
        value = {'event':event, 'time_ns':time.perf_counter_ns(), 'pid':os.getpid(), **deepcopy(details)}
        self.trace.append(value)
        self._trace_file.write(canonical(value)+'\n')
        self._trace_file.flush()
        os.fsync(self._trace_file.fileno())

    async def rpc(self, owner, request, source=0, drop=False):
        if owner not in self.registry['owners']: raise ValueError('unknown physical owner')
        if drop: raise ValueError('use an actual relay cut for transport fault evidence')
        self.issued += 1
        serial, start = self.issued, time.perf_counter_ns()
        expected = identity_for(self.registry, owner, self.window, self.policy)
        raw = (canonical({'identity':expected, 'request':request})+'\n').encode()
        if len(raw) > LIMIT: raise ValueError('request frame bound')
        self.record('rpc-issued', call=serial, owner=owner, source=source, request=request)
        writer = None
        response, order, received = None, None, 0
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', self.ports[owner], limit=LIMIT+1), 5)
            writer.write(raw)
            await writer.drain()
            answer = await asyncio.wait_for(reader.readline(), 5)
            if not answer: raise ConnectionError('transport ended before reply')
            if len(answer) > LIMIT: raise FactoredExecutionError('response frame bound')
            value = json.loads(answer)
            if (not isinstance(value, dict) or set(value) != {'identity','response','owner_order'} or
                    canonical(value['identity']) != canonical(expected) or
                    not isinstance(value['response'], dict)):
                self.record('identity-rejected', call=serial, owner=owner, received=value)
                raise FactoredExecutionError('physical response identity differs from registry')
            response, order, received = value['response'], value['owner_order'], len(answer)
            if response.get('status') == 'wrong-physical-owner':
                raise FactoredExecutionError('physical request identity rejected')
        except (OSError, ConnectionError, asyncio.TimeoutError):
            pass
        finally:
            if writer is not None:
                writer.close()
                try: await writer.wait_closed()
                except (ConnectionError, OSError): pass
        self.record('rpc-result', call=serial, owner=owner, source=source, request=request,
                    response=response, owner_order=order, bytes=len(raw)+received,
                    elapsed_ns=time.perf_counter_ns()-start)
        return response

    def disconnect(self):
        self._trace_file.close()


class PhysicalNetwork(RegisteredTransport):
    def __init__(self, directory, registry, *, window=8):
        super().__init__(directory, registry, {}, window=window)
        self.processes, self.direct_ports, self.identity_paths = {}, {}, {}
        self.relay, self.control_port = None, None
        self.owner_indices = {owner:i for i,owner in enumerate(sorted(registry['owners']))}
        (self.directory/'registry.json').write_text(canonical(registry)+'\n')

    @staticmethod
    def _ready(process, timeout=15):
        if process.stdout is None or not select.select([process.stdout], [], [], timeout)[0]:
            raise TimeoutError('process readiness')
        line = process.stdout.readline()
        if not line:
            error = process.stderr.read() if process.stderr else ''
            raise RuntimeError('process exited before readiness: '+error)
        return json.loads(line)

    def database(self, owner):
        return self.directory/f'owner-{self.owner_indices[owner]:04d}.sqlite'

    def start_owner(self, owner, *, kill_after_request=None):
        identity = identity_for(self.registry, owner, self.window, self.policy)
        path = self.directory/f'identity-{self.owner_indices[owner]:04d}.json'
        path.write_text(canonical(identity)+'\n')
        self.identity_paths[owner] = path
        args = [sys.executable, '-B', '-m', 'src.schema_runtime', '--identity', str(path),
                '--database', str(self.database(owner))]
        if kill_after_request is not None: args += ['--kill-after-request', kill_after_request]
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
        try:
            ready = self._ready(process)
            if (set(ready) != {'status','owner','port','pid'} or ready['status'] != 'ready' or
                    ready['owner'] != owner or ready['pid'] != process.pid):
                raise ValueError('physical owner readiness identity')
        except BaseException:
            if process.poll() is None: os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            raise
        self.processes[owner], self.direct_ports[owner] = process, ready['port']
        self.record('owner-start', owner=owner, pid=process.pid, port=ready['port'], command=args)

    def start(self):
        try:
            for owner in sorted(self.registry['owners']): self.start_owner(owner)
            targets = self.directory/'relay-targets.json'
            targets.write_text(canonical(self.direct_ports)+'\n')
            args = [sys.executable,'-B','-m','tests.factored_tcp_relay','--targets',str(targets),
                    '--events',str(self.directory/'relay-events.jsonl')]
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
            self.relay = process
            ready = self._ready(process)
            if (ready.get('status') != 'ready' or ready.get('pid') != process.pid or
                    set(ready.get('ports', {})) != set(self.registry['owners'])):
                raise ValueError('relay readiness')
            self.ports, self.control_port = ready['ports'], ready['control_port']
            (self.directory/'relay-routes.json').write_text(canonical(self.ports)+'\n')
            self.record('relay-start', pid=process.pid, ports=self.ports, control_port=self.control_port)
        except BaseException:
            self.stop()
            raise

    async def control(self, op, owner=None, **details):
        value = {'op':op, **details}
        if owner is not None: value['owner'] = owner
        reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', self.control_port), 5)
        try:
            writer.write((canonical(value)+'\n').encode())
            await writer.drain()
            reply = json.loads(await asyncio.wait_for(reader.readline(), 5))
            if reply.get('status') != 'controlled': raise ValueError('relay control failed')
            self.record('relay-control', control=value, response=reply,
                        owner_liveness={n:p.poll() is None for n,p in self.processes.items()})
            return reply
        finally:
            writer.close()
            await writer.wait_closed()

    def stop_owner(self, owner, *, kill=False):
        process = self.processes.pop(owner)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL if kill else signal.SIGTERM)
            process.wait(timeout=5)
        self.record('owner-stop', owner=owner, pid=process.pid, signal_requested='KILL' if kill else 'TERM',
                    returncode=process.returncode)
        for stream in (process.stdout, process.stderr):
            if stream is not None: stream.close()

    async def restart_owner(self, owner, *, kill=True, kill_after_request=None):
        self.stop_owner(owner, kill=kill)
        self.start_owner(owner, kill_after_request=kill_after_request)
        await self.control('target', owner, port=self.direct_ports[owner])

    def stop(self):
        for owner in list(self.processes): self.stop_owner(owner)
        if self.relay is not None:
            if self.relay.poll() is None:
                os.killpg(self.relay.pid, signal.SIGTERM)
                self.relay.wait(timeout=5)
            self.record('relay-stop', pid=self.relay.pid, returncode=self.relay.returncode)
            for stream in (self.relay.stdout,self.relay.stderr):
                if stream is not None: stream.close()
            self.relay = None

    def close(self):
        self.stop()
        self.disconnect()
