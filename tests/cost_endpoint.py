"""Owned loopback benchmark worker; original guarded Endpoint with timing only.

Persistence and authorization are unchanged. Stats is a benchmark-only operation,
not a production RPC or certificate field. One request/connection as in the reviewed
process_tcp_endpoint. Process stop/reopen is not described as a crash/power failure.
"""
import asyncio
import json
from pathlib import Path
import sys
import time
from src.controller import Endpoint, canonical

LIMIT = 1024 * 1024


class MeasuredEndpoint(Endpoint):
    def __init__(self, *args, **kwargs):
        self.measurements = dict(persist_calls=0, persist_ns=0, payload_bytes=0)
        super().__init__(*args, **kwargs)

    def persist(self):
        size = len(canonical(self.state).encode("utf-8"))
        begin = time.perf_counter_ns()
        super().persist()
        elapsed = time.perf_counter_ns()-begin
        self.measurements["persist_calls"] += 1
        self.measurements["persist_ns"] += elapsed
        self.measurements["payload_bytes"] += size


async def main():
    node, path = int(sys.argv[1]), Path(sys.argv[2])
    support = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    endpoint = MeasuredEndpoint(node, support, path, window=8, policy="predicate")
    stopped = asyncio.Event()

    async def service(reader, writer):
        request = None
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            if not line or len(line) > LIMIT:
                raise ValueError("bounded object frame required")
            request = json.loads(line)
            if request == {"op": "benchmark-stats"}:
                response = dict(status="stats", **endpoint.measurements,
                                synchronous=endpoint.db.execute("PRAGMA synchronous").fetchone()[0],
                                journal_mode=endpoint.db.execute("PRAGMA journal_mode").fetchone()[0])
            elif request == {"op": "benchmark-stop"}:
                endpoint.disconnect()
                response = dict(status="stopped")
            else:
                response = endpoint.handle(request)
        except (ValueError, KeyError, TypeError, asyncio.TimeoutError) as error:
            response = dict(status="invalid", reason=type(error).__name__)
        encoded = (canonical(response)+"\n").encode()
        if len(encoded) > LIMIT:
            encoded = b'{"status":"response-too-large"}\n'
        writer.write(encoded)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        if request == {"op": "benchmark-stop"}:
            stopped.set()

    server = await asyncio.start_server(service, "127.0.0.1", 0, limit=LIMIT+1)
    print(canonical(dict(status="ready", node=node, port=server.sockets[0].getsockname()[1])), flush=True)
    try:
        async with server:
            await stopped.wait()
    finally:
        endpoint.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
