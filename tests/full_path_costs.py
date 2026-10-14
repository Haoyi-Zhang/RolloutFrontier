"""Complete durable lifecycle benchmark on five owned local owner processes.

Four static choices share one manifest, candidate domain, ordered proposals and
Client lifecycle. Batch choice sees a training batch, never the reverse test batch.
All counts/refusals/no-ops are retained. Timings include FULL/DELETE SQLite and TCP,
not a memory-only install. Byte counts are application frames, not TCP wire bytes.
"""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
from itertools import product
import json
import os
from pathlib import Path
import platform
import queue
import socket
from statistics import median
import subprocess
import sys
import tempfile
import threading
import time
from src import batch, checker, envelope
from src.controller import canonical
from src.network import Client

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 1024 * 1024
POLICIES = ("fixed", "greedy", "mass", "batch")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


class OwnedNetwork:
    def __init__(self, directory, supports):
        self.directory, self.supports = directory, deepcopy(supports)
        self.window, self.policy = 8, "predicate"
        self.processes, self.ports = {}, {}
        self.calls, self.bytes, self.rpc_ns = 0, 0, []
        self.management_calls, self.management_bytes = 0, 0

    def start_node(self, node):
        # Initial support lives in a candidate-local file, avoiding Windows argv
        # limits at 12,000 atoms. Worker reads only this owned JSON input.
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "tests.cost_endpoint", str(node),
             str(self.directory / f"owner-{node}.sqlite"), str(self.directory / f"support-{node}.json")],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.processes[node] = process
        ready_lines = queue.Queue()
        threading.Thread(target=lambda: ready_lines.put(process.stdout.readline()), daemon=True).start()
        try:
            line = ready_lines.get(timeout=10)
        except queue.Empty:
            raise TimeoutError("owned endpoint readiness")
        if not line:
            raise RuntimeError("owned endpoint startup failed: "+process.stderr.read())
        ready = json.loads(line)
        if ready.get("status") != "ready" or ready.get("node") != node or type(ready.get("port")) is not int:
            raise ValueError("invalid owned readiness")
        self.ports[node] = ready["port"]

    def start(self):
        for node in range(len(self.supports)):
            self.start_node(node)

    def stop_node(self, node):
        process = self.processes.pop(node)
        if process.poll() is None:
            if node in self.ports:
                with socket.create_connection(("127.0.0.1", self.ports[node]), timeout=5) as channel:
                    request = b'{"op":"benchmark-stop"}\n'
                    channel.sendall(request)
                    with channel.makefile("rb") as stream:
                        reply = stream.readline()
                        require(json.loads(reply) == {"status": "stopped"}, "shutdown acknowledgment mismatch")
                    self.management_calls += 1
                    self.management_bytes += len(request)+len(reply)
                # These management frames are outside Client RPC totals but
                # included in measured reopen/shutdown wall time.
            else:
                process.terminate()  # Startup-error cleanup of this owned child.
            process.wait(timeout=10)
        for stream in (process.stdout, process.stderr):
            stream.close()
        self.ports.pop(node, None)

    def stop(self):
        for node in list(self.processes):
            self.stop_node(node)

    async def rpc(self, source, target, request):
        encoded = (canonical(request)+"\n").encode()
        if len(encoded) > LIMIT:
            raise ValueError("frame bound")
        begin = time.perf_counter_ns()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", self.ports[target], limit=LIMIT+1), 5)
        try:
            writer.write(encoded)
            await writer.drain()
            answer = await asyncio.wait_for(reader.readline(), 5)
            if not answer or len(answer) > LIMIT:
                raise ValueError("response frame bound")
            result = json.loads(answer)
        finally:
            writer.close()
            await writer.wait_closed()
        self.calls += 1
        self.bytes += len(encoded)+len(answer)
        self.rpc_ns.append(time.perf_counter_ns()-begin)
        return result


def fixture(padding, mismatch):
    extra = [f"unused{i:05d}" for i in range(padding)]
    cells = ((0, 0), (0, 1), (0, 2), (1, 0))
    branches = [{"0": [f"a{i}"], "1": [f"b{j}"], "2": [], "3": [], "4": []}
                for i, j in cells]
    current = {"0": sorted(extra+["a0"]), "1": sorted(extra+["b0"]),
               **{str(i): extra[:] for i in range(2, 5)}}
    candidates = {"0": [["a0"], ["a1"]], "1": [["b0"], ["b1"], ["b2"]],
                  "2": [[]], "3": [[]], "4": [[]]}
    training = [dict(node="0", support=sorted(extra+[f"a{i}"])) for _ in range(12) for i in (1, 0)]
    proposals = ([dict(node="1", support=sorted(extra+[f"b{i}"])) for _ in range(12) for i in (1, 0)]
                 if mismatch else deepcopy(training))
    return branches, current, candidates, training, proposals


async def trial(directory, policy, padding, mismatch, repeat):
    branches, current, candidates, training, proposals = fixture(padding, mismatch)
    timings = {}
    full_start = time.perf_counter_ns()
    begin = time.perf_counter_ns()
    if policy == "batch":
        choice = batch.choose_batch_box(branches, current, candidates, training)
        box = choice["box"]
    elif policy == "mass":
        choice = envelope.frontier_synthesize(branches, current, candidates)
        box = choice["box"]
    elif policy == "greedy":
        choice = envelope.synthesize(branches, current, candidates)
        box = choice["box"]
    else:
        box = {node: [requirements] for node, requirements in branches[0].items()}
    timings["planning_ns"] = time.perf_counter_ns()-begin
    begin = time.perf_counter_ns()
    require(checker.safe_envelope(branches, box), "unsafe planned envelope")
    if policy == "mass":
        require(checker.frontier_certificate(branches, current, candidates, choice), "invalid planning certificate")
    timings["external_check_ns"] = time.perf_counter_ns()-begin
    # Literal per-target reference; runtime results below must match every status.
    state = deepcopy(current)
    expected = []
    for proposal in proposals:
        node, target = proposal["node"], proposal["support"]
        status = ("unchanged" if state[node] == target else "installed"
                  if any(all(atom in target for atom in term) for term in box[node]) else "blocked")
        expected.append(status)
        if status == "installed":
            state[node] = target[:]
    net = OwnedNetwork(directory, [current[str(i)] for i in range(5)])
    client = None
    measurements = []
    try:
        begin = time.perf_counter_ns(); net.start()
        client = Client(net)
        timings["startup_ns"] = time.perf_counter_ns()-begin
        begin = time.perf_counter_ns()
        admitted = await client.acquire_box("cost", branches, box)
        timings["acquisition_ns"] = time.perf_counter_ns()-begin
        require(admitted["status"] == "admitted", "admission did not complete")
        cert = admitted["certificate"]
        require(checker.certificate(cert, branches), "invalid admission certificate")
        begin = time.perf_counter_ns(); client.disconnect(); client = Client(net)
        timings["origin_reopen_ns"] = time.perf_counter_ns()-begin
        counts = dict(installed=0, blocked=0, unchanged=0)
        live = deepcopy(current)
        begin = time.perf_counter_ns()
        for proposal, status in zip(proposals, expected):
            reply = await net.rpc(0, int(proposal["node"]), dict(op="install", support=proposal["support"]))
            require(reply["status"] == status, "proposal differs from literal reference")
            counts[status] += 1
            if status == "installed":
                live[proposal["node"]] = proposal["support"][:]
            require(any(all(all(atom in live[node] for atom in req) for node, req in branch.items())
                        for branch in branches), "incompatible placement")
        timings["updates_ns"] = time.perf_counter_ns()-begin
        require(sum(counts.values()) == len(proposals) == 24, "incomplete proposal accounting")
        before = (await net.rpc(0, 2, {"op": "inspect"}))["state"]
        measurements.append(await net.rpc(0, 2, {"op": "benchmark-stats"}))
        begin = time.perf_counter_ns(); net.stop_node(2); net.start_node(2)
        timings["owner_reopen_ns"] = time.perf_counter_ns()-begin
        require((await net.rpc(0, 2, {"op": "inspect"}))["state"] == before, "reopen changed held state")
        begin = time.perf_counter_ns()
        require(all(reply["status"] == "used" for reply in await client.use(cert)), "held use rejected")
        timings["use_ns"] = time.perf_counter_ns()-begin
        begin = time.perf_counter_ns()
        require(await client.retire(cert), "retirement did not complete")
        timings["retirement_ns"] = time.perf_counter_ns()-begin
        require(not client.state["attempts"], "origin retains an unresolved attempt")
        require((await client.use(cert))[0]["status"] == "not-authorized", "retired admission authorized use")
        for node in range(5):
            actual = (await net.rpc(0, node, {"op": "inspect"}))["state"]
            require(actual["support"] == state[str(node)] and checker.endpoint_invariant(actual), "owner state/reference mismatch")
            require(actual["slots"] == {} and actual["floor"][0] == 1, "retirement left a held slot or wrong floor")
            measurements.append(await net.rpc(0, node, {"op": "benchmark-stats"}))
        require((await net.rpc(0, 0, dict(op="prepare", origin=0, sequence=1, manifest="cost",
                                       requires=[], options=box["0"])))["status"] == "closed", "delayed prepare resurrected a hold")
        require(all(row["synchronous"] == 2 and row["journal_mode"] == "delete" for row in measurements), "durability mode mismatch")
        database_bytes = sum(path.stat().st_size for path in directory.glob("*.sqlite"))
        return_value = dict(policy=policy, padding_atoms=padding, mismatch=mismatch, repeat=repeat,
                            proposals=24, **counts, safety_violations=0, refused_admissions=0,
                            owner_processes=5, owner_reopens=1, origin_reopens=1,
                            sqlite_files=6, sqlite_bytes=database_bytes,
                            rpc_count=net.calls, tcp_connections=net.calls,
                            application_frame_bytes=net.bytes, rpc_samples_ns=net.rpc_ns,
                            owner_persist_calls=sum(row["persist_calls"] for row in measurements),
                            owner_persist_ns=sum(row["persist_ns"] for row in measurements),
                            owner_persist_payload_bytes=sum(row["payload_bytes"] for row in measurements),
                            timings_ns=timings)
    finally:
        begin = time.perf_counter_ns()
        if client is not None:
            client.disconnect()
        net.stop()
        timings["shutdown_ns"] = time.perf_counter_ns()-begin
    return_value["full_lifecycle_ns"] = time.perf_counter_ns()-full_start
    return_value.update(management_connections=net.management_calls,
                        management_frame_bytes=net.management_bytes,
                        total_tcp_connections=net.calls+net.management_calls,
                        total_application_frame_bytes=net.bytes+net.management_bytes)
    return return_value


def run(out, repeats):
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("1..5 repeats")
    rows = []
    for padding, mismatch, repeat in product((0, 11999), (False, True), range(repeats)):
        # Rotate complete policy paths to reduce fixed order effects; no tuning.
        policies = POLICIES[repeat % 4:]+POLICIES[:repeat % 4]
        for policy in policies:
            with tempfile.TemporaryDirectory(prefix="cost-owned-", dir=out.parent) as tmp:
                directory = Path(tmp)
                _, current, _, _, _ = fixture(padding, mismatch)
                for node, support in current.items():
                    (directory / f"support-{node}.json").write_text(canonical(support), encoding="utf-8")
                rows.append(asyncio.run(trial(directory, policy, padding, mismatch, repeat)))
                out.write_text(json.dumps(dict(status="running", rows=rows), indent=2,
                                          sort_keys=True)+"\n", encoding="utf-8")
            print(f"cost case {len(rows)}/{16*repeats}: {policy} padding={padding} mismatch={mismatch}",
                  file=sys.stderr, flush=True)
    return summarize(rows, repeats)


def summarize(rows, repeats):
    if type(repeats) is not int or not 1 <= repeats <= 5 or len(rows) != 16*repeats:
        raise ValueError("incomplete trial rows")
    groups = []
    for padding, mismatch, policy in product((0, 11999), (False, True), POLICIES):
        selected = [row for row in rows if (row["padding_atoms"], row["mismatch"], row["policy"]) == (padding, mismatch, policy)]
        require(len(selected) == repeats, "incomplete policy/payload/schedule group")
        require(all((row["installed"], row["blocked"], row["unchanged"], row["rpc_count"],
                     row["owner_persist_calls"]) ==
                    tuple(selected[0][key] for key in ("installed", "blocked", "unchanged", "rpc_count",
                                                       "owner_persist_calls")) for row in selected),
                "semantic disagreement across repetitions")
        groups.append(dict(policy=policy, padding_atoms=padding, mismatch=mismatch,
                           installed=selected[0]["installed"], blocked=selected[0]["blocked"], unchanged=selected[0]["unchanged"],
                           full_lifecycle_median_ms=median(row["full_lifecycle_ns"] for row in selected)/1e6,
                           stage_medians_ms={key: median(row["timings_ns"][key] for row in selected)/1e6
                                             for key in selected[0]["timings_ns"]}))
    # Stats response sizes include measured durations, so their decimal lengths
    # and application byte totals need not be equal across semantic repetitions.
    return dict(status="completed", python=sys.version, platform=platform.platform(), trials=len(rows), repeats=repeats,
                proposals_total=sum(row["proposals"] for row in rows), groups=groups, rows=rows,
                scope="same host; measured FULL/DELETE SQLite + TCP lifecycle incl setup/checks/reopen/retirement; no WAN/power-loss claim",
                measurement_boundary="cold DB each trial; one TCP connection/RPC; stats instrumentation overhead included; application bytes not wire bytes; owner persist timers exclude stats sizing; origin persistence included in lifecycle stages, not owner totals; no fault injection")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--finalize-from", type=Path,
                        help="summarize retained complete rows after an aggregation-only failure; no experiments")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("result already exists; do not overwrite evidence")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.finalize_from:
        raw = json.loads(args.finalize_from.read_text(encoding="utf-8"))
        answer = summarize(raw["rows"], args.repeats)
        answer["raw_rows_source"] = args.finalize_from.name
        # Pre-counter runs still acknowledged these exact management messages.
        # Preserve the measured rows; distinguish derived accounting explicitly.
        missing = [row for row in answer["rows"] if "management_connections" not in row]
        if missing:
            answer["derived_management_accounting"] = dict(
                connections_per_trial=6,
                application_bytes_per_trial=6*(len(b'{"op":"benchmark-stop"}\n')+len(b'{"status":"stopped"}\n')),
                basis="one owner reopen plus five final shutdowns; exact acknowledged frames in reviewed run path; derived after run, not TCP wire measurements")
    else:
        answer = run(args.out, args.repeats)
    args.out.write_text(json.dumps(answer, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in answer.items() if key not in ("rows", "groups")}, indent=2))
