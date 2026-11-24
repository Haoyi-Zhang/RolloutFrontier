"""Owned loopback TCP relay with observable socket cuts and reconnection.

One relay process listens on a distinct TCP port for each physical owner. Cuts
close accepted sockets and all live streams for that owner. The application and
controller still open real TCP connections and send their encoded requests.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from src.controller import canonical
from src.schema_runtime import LIMIT


class Relay:
    def __init__(self, targets, events):
        self.targets = dict(targets)
        self.cut = set()
        self.streams = {owner: set() for owner in targets}
        self.drop_reply = {}
        self.serial = 0
        self.events = open(events, 'a', encoding='utf-8', buffering=1)

    def record(self, event, **details):
        self.events.write(canonical({'event': event, 'pid': os.getpid(),
                                     'time_ns': time.perf_counter_ns(), **details})+'\n')
        self.events.flush()
        os.fsync(self.events.fileno())

    async def forward(self, owner, reader, writer):
        self.serial += 1
        connection = self.serial
        peer = writer.get_extra_info('peername')
        self.streams[owner].add(writer)
        upstream = None
        self.record('socket-accepted', owner=owner, connection=connection, peer=list(peer))
        try:
            raw = await asyncio.wait_for(reader.readline(), 5)
            if not raw or len(raw) > LIMIT: return
            message = json.loads(raw)
            op = message.get('request', {}).get('op')
            if owner in self.cut:
                self.record('cut-closed-request', owner=owner, connection=connection,
                            operation=op, request_bytes=len(raw))
                return
            remote, upstream = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', self.targets[owner], limit=LIMIT+1), 5)
            self.streams[owner].add(upstream)
            upstream.write(raw)
            await upstream.drain()
            self.record('request-forwarded', owner=owner, connection=connection,
                        operation=op, target_port=self.targets[owner], request_bytes=len(raw))
            answer = await asyncio.wait_for(remote.readline(), 5)
            if not answer or len(answer) > LIMIT:
                self.record('upstream-ended', owner=owner, connection=connection, operation=op)
                return
            if self.drop_reply.get(owner) == op:
                del self.drop_reply[owner]
                self.record('reply-discarded-after-owner', owner=owner, connection=connection,
                            operation=op, response=json.loads(answer), response_bytes=len(answer))
                return
            if owner in self.cut:
                self.record('cut-closed-reply', owner=owner, connection=connection, operation=op)
                return
            writer.write(answer)
            await writer.drain()
            self.record('reply-forwarded', owner=owner, connection=connection,
                        operation=op, response_bytes=len(answer))
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as error:
            self.record('socket-error', owner=owner, connection=connection, kind=type(error).__name__)
        finally:
            for stream in (upstream, writer):
                if stream is not None:
                    self.streams[owner].discard(stream)
                    stream.close()
                    try: await stream.wait_closed()
                    except (ConnectionError, OSError): pass
            self.record('socket-closed', owner=owner, connection=connection)

    async def control(self, reader, writer):
        try:
            raw = await asyncio.wait_for(reader.readline(), 5)
            value = json.loads(raw)
            op, owner = value['op'], value.get('owner')
            if op != 'inspect' and owner not in self.targets: raise ValueError('unknown owner')
            if op == 'cut' and set(value) == {'op','owner'}:
                self.cut.add(owner)
                live = len(self.streams[owner])
                for stream in list(self.streams[owner]): stream.close()
                self.record('link-cut', owner=owner, closed_streams=live)
            elif op == 'restore' and set(value) == {'op','owner'}:
                self.cut.discard(owner)
                self.record('link-restored', owner=owner)
            elif op == 'target' and set(value) == {'op','owner','port'}:
                if type(value['port']) is not int or not 1 <= value['port'] <= 65535: raise ValueError('port')
                self.targets[owner] = value['port']
                self.record('upstream-rebound', owner=owner, port=value['port'])
            elif op == 'drop-reply' and set(value) == {'op','owner','operation'}:
                if value['operation'] not in {'prepare','close','install_if_current','schema','read'}:
                    raise ValueError('operation')
                self.drop_reply[owner] = value['operation']
                self.record('reply-cut-armed', owner=owner, operation=value['operation'])
            elif op != 'inspect' or set(value) != {'op'}:
                raise ValueError('control request')
            response = {'status':'controlled', 'cut':sorted(self.cut), 'targets':self.targets,
                        'drop_reply':self.drop_reply, 'pid':os.getpid()}
            writer.write((canonical(response)+'\n').encode())
            await writer.drain()
        except (OSError, ConnectionError, asyncio.TimeoutError, ValueError, KeyError):
            pass
        finally:
            writer.close()
            try: await writer.wait_closed()
            except (ConnectionError, OSError): pass


async def serve(config, events):
    relay = Relay(config, events)
    servers, ports = [], {}
    for owner in sorted(config):
        async def accept(reader, writer, bound_owner=owner):
            await relay.forward(bound_owner, reader, writer)
        server = await asyncio.start_server(accept, '127.0.0.1', 0, limit=LIMIT+1)
        servers.append(server)
        ports[owner] = server.sockets[0].getsockname()[1]
    control = await asyncio.start_server(relay.control, '127.0.0.1', 0, limit=LIMIT+1)
    servers.append(control)
    relay.record('relay-start', ports=ports, control_port=control.sockets[0].getsockname()[1])
    print(canonical({'status':'ready', 'pid':os.getpid(), 'ports':ports,
                     'control_port':control.sockets[0].getsockname()[1]}), flush=True)
    try: await asyncio.gather(*(server.serve_forever() for server in servers))
    finally:
        for server in servers: server.close()
        await asyncio.gather(*(server.wait_closed() for server in servers))
        relay.events.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--targets', type=Path, required=True)
    parser.add_argument('--events', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve(json.loads(args.targets.read_text()), args.events))
