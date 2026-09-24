"""Owned TCP endpoint process used only by the bounded multiprocess check."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import sys
from src.controller import Endpoint, canonical

LIMIT = 1024 * 1024


async def main() -> None:
    if len(sys.argv) != 6:
        raise SystemExit("node path support-json window policy")
    node = int(sys.argv[1])
    path = Path(sys.argv[2])
    support = json.loads(sys.argv[3])
    window = int(sys.argv[4])
    policy = sys.argv[5]
    endpoint = Endpoint(node, support, path, window, policy)

    async def service(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=2)
            if len(line) > LIMIT:
                raise ValueError("message too large")
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("object request required")
            response = endpoint.handle(req)
        except (ValueError, KeyError, TypeError, asyncio.TimeoutError) as error:
            response = dict(status="invalid", reason=type(error).__name__)
        encoded = (canonical(response) + "\n").encode()
        if len(encoded) > LIMIT:
            encoded = b'{"status":"response-too-large"}\n'
        writer.write(encoded)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(service, "127.0.0.1", 0, limit=LIMIT + 1)
    port = server.sockets[0].getsockname()[1]
    print(canonical(dict(status="ready", node=node, port=port)), flush=True)
    try:
        async with server:
            await server.serve_forever()
    finally:
        endpoint.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
