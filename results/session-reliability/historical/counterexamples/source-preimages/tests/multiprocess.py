"""Five independent endpoint processes with TCP, SQLite, kill/restart and partition."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import resource
import select
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any
from src.checker import certificate, safe_envelope
from src.controller import canonical
from src.network import Client

LIMIT = 1024 * 1024


class ProcessNetwork:
    """Minimal Client-compatible network whose owners are separate OS processes."""
    def __init__(self, directory: Path, supports: list[list[str]], window: int = 8,
                 policy: str = "predicate") -> None:
        self.directory = directory
        self.supports = supports
        self.window = window
        self.policy = policy
        self.processes: dict[int, subprocess.Popen] = {}
        self.ports: dict[int, int] = {}
        self.blocked: set[tuple[int, int]] = set()
        self.trace: list[dict[str, Any]] = []
        self.tick = 0
        self.bytes = 0
        self.delivered = 0
        self.sigkills = 0
        directory.mkdir(parents=True, exist_ok=True)

    def _ready(self, process: subprocess.Popen, timeout: float = 5) -> dict:
        if process.stdout is None or not select.select([process.stdout], [], [], timeout)[0]:
            raise TimeoutError("endpoint readiness")
        line = process.stdout.readline()
        if not line:
            detail = process.stderr.read() if process.stderr else ""
            raise RuntimeError("endpoint exited before readiness: " + detail)
        return json.loads(line)

    def start_node(self, node: int) -> None:
        args = [sys.executable, "-m", "tests.process_tcp_endpoint", str(node),
                str(self.directory / f"process-node-{node}.sqlite"),
                canonical(self.supports[node]), str(self.window), self.policy]
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1,
                                   start_new_session=True)
        ready = self._ready(process)
        if ready != {"node": node, "port": ready.get("port"), "status": "ready"}:
            raise RuntimeError("malformed endpoint readiness")
        self.processes[node] = process
        self.ports[node] = int(ready["port"])
        self.trace.append(dict(event="process-start", node=node))

    def start(self) -> None:
        for node in range(len(self.supports)):
            self.start_node(node)

    def stop_node(self, node: int, kill: bool = False) -> None:
        process = self.processes.pop(node)
        self.ports.pop(node, None)
        if process.poll() is None:
            if kill:
                os.killpg(process.pid, signal.SIGKILL)
                self.sigkills += 1
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        self.trace.append(dict(event="process-stop", node=node, killed=kill,
                               returncode=process.returncode))

    def crash(self, node: int) -> None:
        self.stop_node(node, kill=True)
        self.start_node(node)
        self.trace.append(dict(event="process-restart", node=node))

    def stop(self) -> None:
        for node in list(self.processes):
            self.stop_node(node)

    async def rpc(self, source: int, target: int, req: dict[str, Any],
                  drop: bool = False) -> dict[str, Any] | None:
        self.tick += 1
        if drop or (source, target) in self.blocked or (target, source) in self.blocked:
            self.trace.append(dict(event="lost", tick=self.tick, source=source,
                                   target=target, request=req))
            return None
        request = (canonical(req) + "\n").encode()
        if len(request) > LIMIT:
            raise ValueError("encoded request exceeds frame bound")
        begin = time.perf_counter_ns()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", self.ports[target], limit=LIMIT + 1), 2)
            writer.write(request); await writer.drain()
            answer = await asyncio.wait_for(reader.readline(), 2)
            writer.close(); await writer.wait_closed()
            if len(answer) > LIMIT:
                raise ValueError("encoded response exceeds frame bound")
            response = json.loads(answer)
        except (ConnectionError, OSError, asyncio.TimeoutError, KeyError):
            self.trace.append(dict(event="unreachable", tick=self.tick, source=source,
                                   target=target, request=req))
            return None
        elapsed = time.perf_counter_ns() - begin
        self.bytes += len(request) + len(answer)
        self.delivered += 1
        self.trace.append(dict(event="rpc", tick=self.tick, source=source, target=target,
                               request=req, response=response, bytes=len(request) + len(answer),
                               wall_ns=elapsed))
        return response

    def peak_rss(self) -> dict[str, int]:
        result = {}
        for node, process in self.processes.items():
            try:
                lines = Path(f"/proc/{process.pid}/status").read_text().splitlines()
                value = next(x for x in lines if x.startswith("VmHWM:"))
                result[str(node)] = int(value.split()[1])
            except (OSError, StopIteration, ValueError):
                result[str(node)] = -1
        return result


async def scenario(directory: Path) -> dict:
    supports = [["old", "new"] for _ in range(5)]
    net = ProcessNetwork(directory, supports)
    net.start()
    client = Client(net)
    origin_reopens = 0
    branches = [
        {str(i): ["old"] for i in range(5)},
        {str(i): ["new"] for i in range(5)},
    ]
    box = {"0": [["old"], ["new"]]}
    box.update({str(i): [["old", "new"]] for i in range(1, 5)})
    assert safe_envelope(branches, box)
    try:
        admitted = await client.acquire_box("five-process-envelope", branches, box)
        assert admitted["status"] == "admitted"
        cert = admitted["certificate"]
        assert certificate(cert, branches)

        # Durable acknowledgements survive independent process loss at two owners.
        net.crash(1); net.crash(3)
        after_restart = await client.use(cert)
        assert all(x and x["status"] == "used" for x in after_restart)

        flexible = await net.rpc(0, 0, dict(op="install", support=["new"]))
        rigid = await net.rpc(0, 2, dict(op="install", support=["new"]))
        assert flexible["status"] == "installed"
        assert rigid["status"] == "blocked"

        # Reopen the durable coordinator record after the former handle is closed.
        client.disconnect(); client = Client(net); origin_reopens += 1
        await client.recover()
        assert all(x and x["status"] == "used" for x in await client.use(cert))

        # Retirement is made durable before release. A partition leaves one
        # conservative remote hold that remains across another process kill.
        net.blocked.add((0, 4))
        retired = await client.retire(cert)
        assert not retired
        assert (await client.use(cert))[0]["status"] == "not-authorized"
        net.crash(4)
        still_blocked = await net.rpc(4, 4, dict(op="install", support=["old"]))
        assert still_blocked["status"] == "blocked"

        net.blocked.clear()
        await client.recover()
        assert not client.state["attempts"]
        released = await net.rpc(4, 4, dict(op="install", support=["old"]))
        assert released["status"] == "installed"
        replay = await net.rpc(0, 4, dict(op="prepare", origin=0,
            sequence=cert["sequences"]["4"], manifest=cert["manifest"],
            requires=[], options=box["4"]))
        assert replay["status"] == "closed"

        # Duplicate, reversed catalog exchange converges without conferring use authority.
        profiles = [(await net.rpc(i, i, dict(op="read")))["observed"] for i in range(5)]
        for profile in reversed(profiles):
            for target in reversed(range(5)):
                for _ in range(2):
                    reply = await net.rpc(profile["node"], target,
                                          dict(op="merge", profile=profile))
                    assert reply["status"] in ("merged", "unchanged", "self-authority-rejected")
        states = [(await net.rpc(i, i, dict(op="inspect")))["state"] for i in range(5)]
        catalogs = [s["catalog"] for s in states]
        assert all(c == catalogs[0] for c in catalogs)
        assert all(not any(slot.get("status") == "held" for slot in s["slots"].values())
                   for s in states)

        rss = net.peak_rss()
        return dict(endpoint_processes=5, separate_sqlite_files=5,
                    origin_reopens=origin_reopens, sigkill_events=net.sigkills,
                    delivered_rpcs=net.delivered, serialized_bytes=net.bytes,
                    use_after_two_restarts=[x["status"] for x in after_restart],
                    flexible_change=flexible["status"], rigid_change=rigid["status"],
                    retirement_during_partition=retired,
                    remote_hold_after_restart=still_blocked["status"],
                    release_after_heal=released["status"], delayed_prepare=replay["status"],
                    catalogs_converged=True, live_holds_after_cleanup=0,
                    endpoint_vm_hwm_kib=rss, trace=net.trace,
                    scope=("five independent owner processes on one host; TCP and durable SQLite, "
                           "not cross-host, power-loss, WAN, or production execution"))
    finally:
        client.disconnect()
        net.stop()


def run() -> dict:
    started, cpu = time.perf_counter(), time.process_time()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with tempfile.TemporaryDirectory(prefix="compat-multiprocess-") as directory:
        result = asyncio.run(scenario(Path(directory)))
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result.update(wall_seconds=time.perf_counter() - started,
                  cpu_seconds=time.process_time() - cpu,
                  child_cpu_seconds=(child_after.ru_utime + child_after.ru_stime -
                                     child_before.ru_utime - child_before.ru_stime),
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
