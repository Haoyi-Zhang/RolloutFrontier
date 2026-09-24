"""Directed recovery, encoded bounds, public fact mapping, and kill/restart tests.

No Android invocation, remote service, disk-failure injection, or traffic to
non-loopback addresses. Subprocess death is explicitly separate from endpoint
close/reopen failures in the deterministic network campaign.
"""
from __future__ import annotations
import asyncio
import copy
import csv
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
from src.controller import Endpoint, canonical, minimum_obstruction
from src.network import Network, Client, LIMIT
from src.checker import certificate, obstruction, endpoint_invariant

async def recovery(directory: Path) -> dict:
    net = Network(directory, [["a", "b"]] * 5, window=2)
    await net.start()
    c = Client(net)
    events = []
    try:
        # A partition interrupts acquisition after node 0 persisted its guard.
        net.blocked.add((0, 1))
        failed = await c.acquire("interrupted", [{"0": ["a"], "1": ["a"]}])
        assert failed["status"] == "not-justified"
        assert len(c.state["attempts"]) == 1
        assert not net.nodes[0].state["slots"]
        events.append({"case": "interrupted-acquisition", "outcome": failed["status"],
                       "retained_attempts": len(c.state["attempts"])})
        # Restart does not reinterpret an incomplete attempt as a committed one.
        c.disconnect(); c = Client(net)
        await c.recover()
        assert len(c.state["attempts"]) == 1
        net.blocked.clear(); await c.recover()
        assert not c.state["attempts"]
        assert net.nodes[1].state["floor"][0] == 1
        replay = await net.rpc(0, 1, dict(op="prepare", origin=0, sequence=1,
                                         manifest="interrupted", requires=["a"]))
        assert replay["status"] == "closed"
        # Committed intent survives a coordinator close/reopen and endpoint recovery.
        old = await c.acquire("old", [{"0": ["a"], "1": ["a"]}])
        assert old["status"] == "admitted"
        old_cert = old["certificate"]
        c.disconnect(); c = Client(net)
        await c.recover(); await net.crash(1)
        assert all(x["status"] == "used" for x in await c.use(old_cert))
        assert (await net.rpc(1, 1, dict(op="install", support=["b"])))["status"] == "blocked"
        events.append({"case": "committed-recovery", "outcome": "held-and-usable"})
        # Acquire a replacement placement before releasing the former placement.
        new = await c.acquire("new", [{"2": ["b"], "3": ["b"], "4": ["b"]}])
        assert new["status"] == "admitted"
        assert all(x["status"] == "used" for x in await c.use(new["certificate"]))
        assert (await c.acquire("over-window", [{"2": ["b"]}]))["status"] == "not-justified"
        # Retirement is journalled before remote release. Lost release is retained.
        net.blocked.add((0, 1))
        assert not await c.retire(old_cert)
        assert (await c.use(old_cert))[0]["status"] == "not-authorized"
        assert (await net.rpc(1, 1, dict(op="install", support=["b"])))["status"] == "blocked"
        assert all(x["status"] == "used" for x in await c.use(new["certificate"]))
        c.disconnect(); c = Client(net)
        net.blocked.clear(); await c.recover()
        assert (await net.rpc(1, 1, dict(op="install", support=["b"])))["status"] == "installed"
        assert await c.retire(new["certificate"])
        events.append({"case": "overlap-migration", "outcome": "new-guards-before-old-retirement",
                       "claim": "compatibility overlap only, not application-state transfer"})
        assert all(endpoint_invariant(n.state) for n in net.nodes.values())
        # Saved structural receipts are not ongoing execution authority.
        assert certificate(old_cert, [{"0": ["a"], "1": ["a"]}])
        assert (await c.use(old_cert))[0]["status"] == "not-authorized"
        # Malformed certificate checks fail closed without importing producer logic.
        rejected = []
        for name, mutated in (("none", None), ("list", []), ("empty-object", {}),
                              ("boolean-origin", {**old_cert, "origin": True})):
            assert not certificate(mutated, [{"0": ["a"], "1": ["a"]}])
            rejected.append(name)
        for name, field, value in (("sequence-overflow", "sequence", 2**63),
                                   ("boolean-node", "node", True),
                                   ("empty-requirements", "requires", [])):
            malformed = copy.deepcopy(old_cert)
            malformed["receipts"][0][field] = value
            assert not certificate(malformed, [{"0": ["a"], "1": ["a"]}])
            rejected.append(name)
        malformed = copy.deepcopy(old_cert)
        del malformed["receipts"][0]["observed_generation"]
        assert not certificate(malformed, [{"0": ["a"], "1": ["a"]}])
        rejected.append("missing-observed-generation")
        malformed = copy.deepcopy(old_cert)
        malformed["receipts"][0]["observed_generation"] = True
        assert not certificate(malformed, [{"0": ["a"], "1": ["a"]}])
        rejected.append("boolean-observed-generation")
        malformed = copy.deepcopy(old_cert)
        malformed["sequences"]["0"] = True
        assert not certificate(malformed, [{"0": ["a"], "1": ["a"]}])
        rejected.append("boolean-top-level-sequence")
        events.append({"case": "retired-certificate",
                       "outcome": "structural-only-not-authority",
                       "rejected_mutations": rejected})
        await net.gossip()
        assert all(n.state["catalog"] == net.nodes[0].state["catalog"] for n in net.nodes.values())
        return dict(cases=events, delivered=net.delivered, serialized_bytes=net.bytes,
                    trace=net.trace)
    finally:
        c.disconnect(); await net.stop()

async def multi_origin_isolation(directory: Path) -> dict:
    """Exercise independent sequence floors and overlapping durable holds.

    Two serial origins share one endpoint.  Retiring one origin across a
    partition must neither release nor authorize the other origin's hold.
    This is a directed finite test, not concurrent-writer or Byzantine proof.
    """
    net = Network(directory, [["a", "b"]] * 3, window=3)
    await net.start()
    first, second = Client(net, origin=0), Client(net, origin=1)
    try:
        a = await first.acquire("origin-zero", [{"0": ["a"], "1": ["a"]}])
        b = await second.acquire("origin-one", [{"1": ["a"], "2": ["a"]}])
        assert a["status"] == b["status"] == "admitted"
        assert all(x["status"] == "used" for x in await first.use(a["certificate"]))
        assert all(x["status"] == "used" for x in await second.use(b["certificate"]))

        # The shared endpoint persists both origin-indexed slots across reopen.
        await net.crash(1)
        shared = await net.rpc(2, 1, dict(op="inspect"))
        slots = shared["state"]["slots"]
        assert slots["0:1"]["manifest"] == "origin-zero"
        assert slots["1:1"]["manifest"] == "origin-one"

        # Origin 0 journals retirement, but its release to the shared node is lost.
        net.blocked.add((0, 1))
        assert not await first.retire(a["certificate"])
        assert (await first.use(a["certificate"]))[0]["status"] == "not-authorized"
        assert all(x["status"] == "used" for x in await second.use(b["certificate"]))
        blocked_by_both = await net.rpc(2, 1, dict(op="install", support=["b"]))
        assert blocked_by_both["status"] == "blocked"
        assert set(blocked_by_both["holds"]) == {"0:1", "1:1"}

        # Healing closes only origin 0.  Origin 1 continues to block the change.
        net.blocked.clear()
        await first.recover()
        blocked_by_second = await net.rpc(2, 1, dict(op="install", support=["b"]))
        assert blocked_by_second["status"] == "blocked"
        assert blocked_by_second["holds"] == ["1:1"]
        delayed = await net.rpc(0, 1, dict(op="prepare", origin=0, sequence=1,
                                           manifest="origin-zero", requires=["a"]))
        assert delayed["status"] == "closed"
        assert all(x["status"] == "used" for x in await second.use(b["certificate"]))

        assert await second.retire(b["certificate"])
        installed = await net.rpc(2, 1, dict(op="install", support=["b"]))
        assert installed["status"] == "installed"
        final = (await net.rpc(2, 1, dict(op="inspect")))["state"]
        assert final["floor"][:2] == [1, 1]
        assert not any(key.startswith(("0:", "1:")) for key in final["slots"])
        assert endpoint_invariant(final)
        return dict(origins=2, shared_node=1, persisted_slots=sorted(slots),
                    blocked_before_heal=blocked_by_both["holds"],
                    blocked_after_first_recovery=blocked_by_second["holds"],
                    delayed_prepare=delayed["status"], final_floors=final["floor"][:2],
                    final_install=installed["status"], trace=net.trace,
                    scope="two serial origins on one host; no concurrent-writer or Byzantine claim")
    finally:
        first.disconnect(); second.disconnect(); await net.stop()


async def public_slice(directory: Path) -> dict:
    with open(Path(__file__).resolve().parents[1] / "data/android-history.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4 and len({r["contract"] for r in rows}) == 4
    # Inclusion is fixed in SOURCE-NOTES.md: four named vibration factories.
    def support(level):
        return sorted(r["contract"] for r in rows if int(r["first_public_api_level"]) <= level)
    levels = [25, 26, 28, 29, 30]
    net = Network(directory, [support(level) for level in levels])
    await net.start(); c = Client(net)
    try:
        common = await c.acquire("factories", [{"1": ["haptic.one"], "2": ["haptic.wave"]}])
        assert common["status"] == "admitted"
        no = await c.acquire("new-factory", [{"2": ["haptic.predefined"]}])
        assert no["status"] == "not-justified"
        branches = [{(2, "haptic.predefined")}]
        observed = {(2, x) for x in support(28)}
        witness = minimum_obstruction(branches, observed)
        assert obstruction(branches, observed, witness, exact_small=True)
        assert (await net.rpc(2, 2, dict(op="install", support=support(29))))["status"] == "installed"
        newer = await c.acquire("new-factory", [{"2": ["haptic.predefined"]}])
        assert newer["status"] == "admitted"
        blocked = await net.rpc(2, 2, dict(op="install", support=support(28)))
        assert blocked["status"] == "blocked"
        assert await c.retire(newer["certificate"])
        rollback = await net.rpc(2, 2, dict(op="install", support=support(28)))
        assert rollback["status"] == "installed" and rollback["observed"]["generation"] == 2
        assert await c.retire(common["certificate"])
        return dict(facts=rows, levels=levels, support_sizes=[len(support(l)) for l in levels],
                    old_admission=common["status"], new_before_upgrade=no["status"],
                    obstruction=witness, new_after_upgrade=newer["status"],
                    rollback_while_held=blocked["status"], rollback_after_retirement=rollback["status"],
                    rollback_generation=2, trace=net.trace,
                    scope="declaration-presence facts, not Android execution or behavioral equivalence")
    finally:
        c.disconnect(); await net.stop()

async def encoding(directory: Path) -> dict:
    net = Network(directory, [["a"]] * 5)
    await net.start()
    try:
        r, w = await asyncio.open_connection("127.0.0.1", net.ports[0])
        w.write(b"[]\n"); await w.drain()
        assert json.loads(await r.readline())["status"] == "invalid"
        w.close(); await w.wait_closed()
        try:
            await net.rpc(0, 0, dict(op="read", padding="x" * LIMIT))
            raise AssertionError("oversized request accepted")
        except ValueError:
            pass
        # Count-valid state can exceed the separately enforced wire encoding cap.
        # This local construction is only a frame-bound test, not a network update.
        huge = [(str(i) + ":" + "x" * 500) for i in range(2200)]
        net.nodes[0].install(huge)
        reply = await net.rpc(0, 0, dict(op="read"))
        assert reply["status"] == "response-too-large"
        return dict(frame_bytes=LIMIT, malformed="invalid", oversized_request="ValueError",
                    oversized_response=reply["status"], direct_local_atoms=len(huge))
    finally:
        await net.stop()

def kill_restart(directory: Path) -> dict:
    path = directory / "killed.sqlite"
    kills = 0
    child = None
    def receive(process):
        if not select.select([process.stdout], [], [], 3)[0]:
            raise TimeoutError("bounded child acknowledgement")
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("child exited before acknowledgement")
        return json.loads(line)
    def launch():
        p = subprocess.Popen([sys.executable, "-m", "tests.process_endpoint", str(path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, bufsize=1)
        assert receive(p)["status"] == "ready"
        return p
    def send(process, request):
        process.stdin.write(canonical(request) + "\n"); process.stdin.flush()
        return receive(process)
    request = dict(op="prepare", origin=0, sequence=1, manifest="durable", requires=["a"])
    try:
        child = launch()
        assert send(child, request)["status"] == "held"
        os.kill(child.pid, signal.SIGKILL); assert child.wait(timeout=3) == -signal.SIGKILL; kills += 1
        child.stdin.close(); child.stdout.close(); child.stderr.close()
        child = launch()
        assert send(child, dict(op="install", support=[]))["status"] == "blocked"
        assert send(child, dict(op="use", origin=0, sequence=1, manifest="durable"))["status"] == "used"
        assert send(child, dict(op="close", origin=0, sequence=1))["status"] == "closed"
        os.kill(child.pid, signal.SIGKILL); assert child.wait(timeout=3) == -signal.SIGKILL; kills += 1
        child.stdin.close(); child.stdout.close(); child.stderr.close()
        child = launch()
        assert send(child, request)["status"] == "closed"
        assert send(child, dict(op="install", support=[]))["status"] == "installed"
        child.stdin.close(); assert child.wait(timeout=3) == 0
        child.stdout.close(); child.stderr.close(); child = None
        return dict(sigkill_events=kills, after_prepare="held", after_close="not-resurrected",
                    scope="owned endpoint process loss after ACK; OS and storage remain running")
    finally:
        if child is not None:
            if child.poll() is None: child.kill()
            child.wait(timeout=3)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None and not stream.closed: stream.close()


def envelope_certificate_mutations() -> dict:
    branches = [{"0": ["a"]}, {"0": ["b"]}]
    endpoint = Endpoint(0, ["a"])
    reply = endpoint.prepare(0, 1, "box", [], options=[["a"], ["b"]])
    assert reply["status"] == "held"
    cert = dict(mode="envelope", manifest="box", origin=0,
                box={"0": [["a"], ["b"]]}, sequences={"0": 1},
                receipts=[reply["receipt"]])
    assert certificate(cert, branches)
    rejected = []
    def reject(name, mutate):
        candidate = copy.deepcopy(cert)
        mutate(candidate)
        assert not certificate(candidate, branches)
        rejected.append(name)
    reject("missing-observed-generation",
           lambda c: c["receipts"][0].pop("observed_generation"))
    reject("boolean-observed-generation",
           lambda c: c["receipts"][0].__setitem__("observed_generation", True))
    reject("boolean-sequence", lambda c: c["sequences"].__setitem__("0", True))
    reject("duplicate-receipt", lambda c: c["receipts"].append(copy.deepcopy(c["receipts"][0])))
    return dict(valid_certificate=True, rejected_mutations=rejected)

def main() -> dict:
    start, cpu = time.perf_counter(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    with tempfile.TemporaryDirectory(prefix="compat-integration-") as d:
        root = Path(d)
        recovered = asyncio.run(recovery(root / "recovery"))
        multi_origin = asyncio.run(multi_origin_isolation(root / "multi-origin"))
        public = asyncio.run(public_slice(root / "public"))
        encoded = asyncio.run(encoding(root / "encoding"))
        killed = kill_restart(root)
        certificate_checks = envelope_certificate_mutations()
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(recovery=recovered, multi_origin=multi_origin, public_slice=public,
                encoding=encoded, process_loss=killed, certificate_mutations=certificate_checks,
                wall_seconds=time.perf_counter()-start, cpu_seconds=time.process_time()-cpu,
                child_cpu_seconds=(child_end.ru_utime + child_end.ru_stime - child_start.ru_utime - child_start.ru_stime),
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))
