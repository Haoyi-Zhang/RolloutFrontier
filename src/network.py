"""Five real loopback TCP endpoints, multiplexed by one asyncio worker.

Logical fault scheduling is deterministic; measured wall latency is loopback
control-plane latency, not edge-network latency. Crashes close an endpoint and
reopen its SQLite state. The process and OS remain alive; no power-loss claim.
"""
from __future__ import annotations
import asyncio
import json
import random
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from .controller import (Endpoint, canonical, atoms, initialize_state_table,
                         load_singleton_state, MAX_NODES, MAX_SEQ, MAX_REQUIREMENTS,
                         MAX_CONTRACTS)

LIMIT = 1024 * 1024


class Network:
    def __init__(self, directory: Path, supports: list[list[str]], policy: str = "predicate",
                 window: int = 8, seed: int = 1) -> None:
        if not isinstance(supports, (list, tuple)) or not 1 <= len(supports) <= 6:
            raise ValueError("node bound")
        if type(window) is not int or not 1 <= window <= 64 or policy not in ("predicate", "epoch", "unguarded"):
            raise ValueError("invalid policy/window")
        directory.mkdir(parents=True, exist_ok=True)
        # Freeze caller-owned collections before the first await or restart.
        frozen_supports = [atoms(values, MAX_CONTRACTS) for values in supports]
        self.directory, self.supports = directory, frozen_supports
        self.policy, self.window = policy, window
        self.nodes: dict[int, Endpoint] = {}
        self.servers: dict[int, Any] = {}
        self.ports: dict[int, int] = {}
        # Reuse one serialized TCP channel per target.  Opening a fresh client
        # socket for every bounded RPC can exhaust the host ephemeral-port range
        # after repeated clean reproductions even though each individual run is
        # modest.  Locks preserve request/reply framing if callers overlap.
        self.connections: dict[int, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self.connection_locks: dict[int, asyncio.Lock] = {}
        self.server_writers: dict[int, set[asyncio.StreamWriter]] = {}
        self.blocked: set[tuple[int, int]] = set()
        self.trace: list[dict[str, Any]] = []
        self.rng = random.Random(seed)
        self.tick = 0
        self.queue: list[tuple[int, int, int, int, dict[str, Any]]] = []
        self.order = 0
        self.bytes = 0
        self.delivered = 0
        self.opened_connections = 0

    async def start_node(self, n: int) -> None:
        self.nodes[n] = Endpoint(n, self.supports[n], self.directory / f"node-{n}.sqlite",
                                 self.window, self.policy)
        self.server_writers[n] = set()

        async def service(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            self.server_writers[n].add(writer)
            try:
                while True:
                    try:
                        line = await reader.readline()
                    except (ValueError, asyncio.LimitOverrunError) as error:
                        response = dict(status="invalid", reason=type(error).__name__)
                        encoded = (canonical(response) + "\n").encode()
                        writer.write(encoded); await writer.drain()
                        break
                    if not line:
                        break
                    try:
                        if len(line) > LIMIT:
                            raise ValueError("message too large")
                        req = json.loads(line)
                        if not isinstance(req, dict):
                            raise ValueError("object request required")
                        response = self.nodes[n].handle(req)
                    except (ValueError, KeyError, TypeError) as error:
                        response = dict(status="invalid", reason=type(error).__name__)
                    encoded = (canonical(response) + "\n").encode()
                    if len(encoded) > LIMIT:
                        encoded = b'{"status":"response-too-large"}\n'
                    writer.write(encoded)
                    await writer.drain()
            except (ConnectionError, OSError, asyncio.CancelledError):
                pass
            finally:
                self.server_writers.get(n, set()).discard(writer)
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass

        self.servers[n] = await asyncio.start_server(service, "127.0.0.1", 0, limit=LIMIT + 1)
        self.ports[n] = self.servers[n].sockets[0].getsockname()[1]

    async def _drop_connection(self, n: int) -> None:
        pair = self.connections.pop(n, None)
        if pair is None:
            return
        _, writer = pair
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass

    async def _connect(self, n: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        pair = self.connections.get(n)
        if pair is not None and not pair[1].is_closing():
            return pair
        await self._drop_connection(n)
        pair = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", self.ports[n], limit=LIMIT + 1), 2)
        self.opened_connections += 1
        self.connections[n] = pair
        return pair

    async def start(self) -> None:
        for n in range(len(self.supports)):
            await self.start_node(n)

    async def stop_node(self, n: int) -> None:
        await self._drop_connection(n)
        self.servers[n].close()
        await self.servers[n].wait_closed()
        writers = list(self.server_writers.get(n, ()))
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(*(writer.wait_closed() for writer in writers),
                                 return_exceptions=True)
        await asyncio.sleep(0)
        self.nodes[n].disconnect()
        del self.nodes[n]
        del self.servers[n]
        del self.server_writers[n]

    async def stop(self) -> None:
        for n in list(self.servers):
            await self.stop_node(n)

    async def crash(self, n: int) -> None:
        await self.stop_node(n)
        self.trace.append(dict(event="crash", node=n, tick=self.tick))
        await self.start_node(n)
        self.trace.append(dict(event="recover", node=n, tick=self.tick))

    async def rpc(self, source: int, target: int, req: dict[str, Any],
                  drop: bool = False) -> dict[str, Any] | None:
        # Canonical round-trip detaches the wire image and trace from caller mutation.
        request_obj = json.loads(canonical(req))
        self.tick += 1
        if drop or (source, target) in self.blocked or (target, source) in self.blocked:
            self.trace.append(dict(event="lost", tick=self.tick, source=source, target=target,
                                   request=request_obj))
            return None
        begin = time.perf_counter_ns()
        request = (canonical(request_obj) + "\n").encode()
        if len(request) > LIMIT:
            raise ValueError("encoded request exceeds frame bound")
        lock = self.connection_locks.setdefault(target, asyncio.Lock())
        response = None
        answer = b""
        async with lock:
            for attempt in range(2):
                try:
                    reader, writer = await self._connect(target)
                    writer.write(request)
                    await writer.drain()
                    answer = await asyncio.wait_for(reader.readline(), 2)
                    if not answer:
                        raise ConnectionError("persistent channel closed")
                    if len(answer) > LIMIT:
                        raise ValueError("encoded response exceeds frame bound")
                    response = json.loads(answer)
                    break
                except (ConnectionError, OSError, asyncio.TimeoutError):
                    await self._drop_connection(target)
                    if attempt == 1:
                        self.trace.append(dict(event="unreachable", tick=self.tick,
                                               source=source, target=target, request=request_obj))
                        return None
        elapsed = time.perf_counter_ns() - begin
        self.bytes += len(request) + len(answer)
        self.delivered += 1
        self.trace.append(dict(event="rpc", tick=self.tick, source=source, target=target,
                               request=request_obj, response=response, bytes=len(request) + len(answer),
                               wall_ns=elapsed))
        return response

    def enqueue(self, source: int, target: int, req: dict[str, Any], delay: int = 0) -> None:
        if type(delay) is not int or delay < 0:
            raise ValueError("invalid logical delay")
        self.order += 1
        self.queue.append((self.tick + delay, self.order, source, target,
                           json.loads(canonical(req))))

    async def drain(self) -> None:
        for due, order, source, target, req in sorted(self.queue):
            self.tick = max(self.tick, due)
            await self.rpc(source, target, req)
        self.queue.clear()

    async def gossip(self, duplicates: bool = True) -> None:
        profiles = []
        for n in self.nodes:
            answer = await self.rpc(n, n, {"op": "read"})
            profiles.append(answer["observed"])
        for p in profiles:
            for target in self.nodes:
                req = dict(op="merge", profile=p)
                self.enqueue(p["node"], target, req, self.rng.randrange(8))
                if duplicates:
                    self.enqueue(p["node"], target, req, self.rng.randrange(8))
        await self.drain()


class Client:
    """Single-writer durable coordinator, with bounded unresolved attempts.

    Not leader election or concurrent coordinator failover. Restart is allowed
    only after the former writer has stopped. Admission is durably recorded
    before it is reported. Incomplete acquisitions are conservatively retired.
    """
    def __init__(self, network: Network, origin: int = 0) -> None:
        import sqlite3
        if type(origin) is not int or not 0 <= origin < MAX_NODES:
            raise ValueError("origin bound")
        self.net, self.origin = network, origin
        self.db = sqlite3.connect(str(network.directory / f"origin-{origin}.sqlite"))
        try:
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA journal_mode=DELETE")
            initialize_state_table(self.db)
            loaded = load_singleton_state(self.db)
            self.state = loaded if loaded is not None else dict(
                origin=origin, node_count=len(network.supports), window=network.window,
                policy=network.policy, next=[0] * len(network.supports),
                serial=0, attempts={})
            self._validate_loaded_state()
            self.persist()
        except Exception:
            self.db.close()
            raise

    @staticmethod
    def _canonical_sequence_map(value: Any, node_count: int) -> bool:
        if not isinstance(value, dict) or not value:
            return False
        try:
            return all(isinstance(text, str) and text == str(int(text)) and
                       0 <= int(text) < node_count and type(sequence) is int and
                       1 <= sequence <= MAX_SEQ for text, sequence in value.items())
        except (TypeError, ValueError):
            return False

    def _validate_attempt_certificate(self, record: dict[str, Any]) -> None:
        certificate = record.get("certificate")
        if not isinstance(certificate, dict):
            raise ValueError("invalid durable certificate")
        sequences = record["sequences"]
        if (certificate.get("origin") != self.origin or
                type(certificate.get("origin")) is not int or
                certificate.get("manifest") != record["manifest"] or
                certificate.get("sequences") != sequences):
            raise ValueError("durable certificate binding mismatch")
        envelope = certificate.get("mode") == "envelope"
        if envelope:
            expected = {"mode", "manifest", "origin", "box", "sequences", "receipts"}
            if set(certificate) != expected or certificate["mode"] != "envelope":
                raise ValueError("invalid durable envelope certificate schema")
            box = certificate["box"]
            if not isinstance(box, dict) or set(box) != set(sequences):
                raise ValueError("invalid durable envelope box")
            normalized_box = {}
            for text, options in box.items():
                if not isinstance(options, list) or not 1 <= len(options) <= 8:
                    raise ValueError("invalid durable envelope options")
                normalized = sorted({tuple(atoms(option, MAX_CONTRACTS)) for option in options})
                if any(set(other) < set(option) for option in normalized for other in normalized):
                    raise ValueError("nonminimal durable envelope box")
                normalized_box[text] = [list(option) for option in normalized]
            if box != normalized_box:
                raise ValueError("noncanonical durable envelope box")
        else:
            expected = {"manifest", "origin", "branch", "sequences", "receipts"}
            if set(certificate) != expected or type(certificate["branch"]) is not int or not 0 <= certificate["branch"] < 8:
                raise ValueError("invalid durable fixed certificate schema")
            box = None
        receipts = certificate["receipts"]
        if not isinstance(receipts, list) or len(receipts) != len(sequences):
            raise ValueError("invalid durable receipt count")
        seen = set()
        for receipt in receipts:
            fixed_fields = {"status", "node", "origin", "sequence", "manifest",
                            "requires", "observed_generation"}
            expected_receipt = fixed_fields | ({"options"} if envelope else set())
            if not isinstance(receipt, dict) or set(receipt) != expected_receipt:
                raise ValueError("invalid durable receipt schema")
            node = receipt["node"]
            text = str(node)
            if (type(node) is not int or text in seen or text not in sequences or
                    receipt["status"] != "held" or receipt["origin"] != self.origin or
                    type(receipt["origin"]) is not int or
                    receipt["sequence"] != sequences[text] or type(receipt["sequence"]) is not int or
                    receipt["manifest"] != record["manifest"] or
                    type(receipt["observed_generation"]) is not int or
                    not 0 <= receipt["observed_generation"] <= MAX_SEQ):
                raise ValueError("durable receipt binding mismatch")
            if not isinstance(receipt["requires"], list) or atoms(receipt["requires"], MAX_REQUIREMENTS) != receipt["requires"]:
                raise ValueError("noncanonical durable receipt requirements")
            if envelope:
                if receipt["requires"] or receipt["options"] != box[text]:
                    raise ValueError("durable envelope receipt mismatch")
            seen.add(text)
        if seen != set(sequences):
            raise ValueError("incomplete durable receipts")

    def _validate_loaded_state(self) -> None:
        state = self.state
        if (not isinstance(state, dict) or
                set(state) != {"origin", "node_count", "window", "policy",
                               "next", "serial", "attempts"}):
            raise ValueError("invalid durable origin schema")
        node_count = len(self.net.supports)
        if (type(state["origin"]) is not int or state["origin"] != self.origin or
                type(state["node_count"]) is not int or state["node_count"] != node_count or
                type(state["window"]) is not int or state["window"] != self.net.window or
                state["policy"] != self.net.policy):
            raise ValueError("durable origin/network mismatch")
        if (not isinstance(state["next"], list) or len(state["next"]) != node_count or
                any(type(value) is not int or not 0 <= value <= MAX_SEQ for value in state["next"])):
            raise ValueError("invalid durable next-sequence vector")
        if type(state["serial"]) is not int or not 0 <= state["serial"] <= MAX_SEQ:
            raise ValueError("invalid durable attempt serial")
        attempts = state["attempts"]
        if not isinstance(attempts, dict) or len(attempts) > self.net.window:
            raise ValueError("invalid durable attempt map")
        used: set[tuple[int, int]] = set()
        manifests: set[str] = set()
        for key, record in attempts.items():
            if (not isinstance(key, str) or not key or key != str(int(key)) or
                    not 1 <= int(key) <= state["serial"] or not isinstance(record, dict)):
                raise ValueError("invalid durable attempt key")
            status = record.get("status")
            base = {"status", "manifest", "sequences"}
            allowed_by_status = {
                "acquiring": (base,),
                "committed": (base | {"certificate"},),
                "retiring": (base, base | {"certificate"}),
            }
            if status not in allowed_by_status or set(record) not in allowed_by_status[status]:
                raise ValueError("invalid durable attempt schema")
            if (not isinstance(record["manifest"], str) or not record["manifest"] or
                    len(record["manifest"]) > 256 or record["manifest"] in manifests or
                    not self._canonical_sequence_map(record["sequences"], node_count)):
                raise ValueError("invalid durable attempt binding")
            manifests.add(record["manifest"])
            for text, sequence in record["sequences"].items():
                node = int(text)
                if sequence > state["next"][node] or (node, sequence) in used:
                    raise ValueError("reused or unallocated durable sequence")
                used.add((node, sequence))
            if status == "committed" and "certificate" not in record:
                raise ValueError("committed attempt lacks certificate")
            if "certificate" in record:
                self._validate_attempt_certificate(record)

    def persist(self) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (1,?)", (canonical(self.state),))

    def disconnect(self) -> None:
        self.db.close()

    async def _close(self, key: str) -> bool:
        record = self.state["attempts"][key]
        okay = True
        for text, seq in record["sequences"].items():
            r = await self.net.rpc(self.origin, int(text),
                                  dict(op="close", origin=self.origin, sequence=seq))
            if r is None or r["status"] != "closed":
                okay = False
        if okay:
            del self.state["attempts"][key]
            self.persist()
        return okay

    async def recover(self) -> None:
        # Serial use of this Client is part of the model.
        for key in list(self.state["attempts"]):
            record = self.state["attempts"][key]
            if record["status"] == "committed":
                continue
            record["status"] = "retiring"
            self.persist()
            await self._close(key)

    async def acquire(self, manifest: str, branches: list[dict[str, list[str]]]) -> dict[str, Any]:
        from .checker import certificate
        from .controller import atoms, MAX_REQUIREMENTS, MAX_SEQ
        if not isinstance(manifest, str) or not manifest or len(manifest) > 256:
            raise ValueError("manifest binding")
        if not 1 <= len(branches) <= 8:
            raise ValueError("branch bound")
        normalized_branches = []
        for branch in branches:
            if not isinstance(branch, dict) or not branch or len(branch) > len(self.net.supports):
                raise ValueError("placement bound")
            normalized = {}
            for text, requires in branch.items():
                if not isinstance(text, str) or text != str(int(text)) or not 0 <= int(text) < len(self.net.supports):
                    raise ValueError("noncanonical node")
                normalized[text] = atoms(requires, MAX_REQUIREMENTS)
            normalized_branches.append(normalized)
        branches = normalized_branches
        await self.recover()
        for r in self.state["attempts"].values():
            if r["manifest"] == manifest:
                if r["status"] == "committed" and certificate(r["certificate"], branches):
                    return dict(status="admitted", certificate=deepcopy(r["certificate"]))
                return dict(status="not-justified", reasons=[dict(reason="unresolved-or-conflicting-manifest")])
        reasons = []
        for index, branch in enumerate(branches):
            if len(self.state["attempts"]) >= self.net.window:
                reasons.append(dict(reason="origin-window"))
                break
            if self.state["serial"] == MAX_SEQ or any(self.state["next"][int(n)] == MAX_SEQ for n in branch):
                reasons.append(dict(reason="sequence-exhausted"))
                break
            receipts, sequences = [], {}
            okay = True
            for text in sorted(branch, key=int):
                n = int(text)
                self.state["next"][n] += 1
                sequences[text] = self.state["next"][n]
            self.state["serial"] += 1
            key = str(self.state["serial"])
            self.state["attempts"][key] = dict(status="acquiring", manifest=manifest,
                                               sequences=sequences)
            self.persist()  # Intent and nonreused sequence numbers precede network sends.
            for text in sorted(branch, key=int):
                n = int(text)
                req = dict(op="prepare", origin=self.origin, sequence=sequences[text],
                           manifest=manifest, requires=sorted(set(branch[text])))
                reply = await self.net.rpc(self.origin, n, req)
                if reply is None or reply["status"] != "held":
                    okay = False
                    reasons.append(dict(branch=index, node=n, reply=reply))
                    break
                receipts.append(reply["receipt"])
            c = dict(manifest=manifest, origin=self.origin, branch=index,
                     sequences=sequences, receipts=receipts)
            if okay and certificate(c, branches):
                self.state["attempts"][key].update(status="committed", certificate=c)
                self.persist()  # A restarted origin preserves every reported admission.
                return dict(status="admitted", certificate=deepcopy(c))
            self.state["attempts"][key]["status"] = "retiring"
            self.persist()
            # A failed close leaves a durable unresolved attempt because a
            # prepare that was lost from the origin's point of view may still
            # arrive later at an owner.  Do not fall back to another branch for
            # the same manifest until every close is confirmed: doing so would
            # create two durable records with one manifest and make restart
            # validation fail, while dropping the first record would lose the
            # authority needed to retire a delayed hold.
            if not await self._close(key):
                reasons.append(dict(branch=index, reason="retirement-unconfirmed"))
                return dict(status="not-justified", reasons=reasons)
        return dict(status="not-justified", reasons=reasons)

    def _record(self, c: dict[str, Any]) -> str | None:
        for key, record in self.state["attempts"].items():
            if record.get("certificate") == c:
                return key
        return None

    async def retire(self, c: dict[str, Any]) -> bool:
        key = self._record(deepcopy(c))
        if key is None:
            return False
        self.state["attempts"][key]["status"] = "retiring"
        self.persist()
        return await self._close(key)

    async def use(self, c: dict[str, Any]) -> list[dict[str, Any] | None]:
        key = self._record(deepcopy(c))
        if key is None or self.state["attempts"][key]["status"] != "committed":
            return [dict(status="not-authorized")]
        private = deepcopy(self.state["attempts"][key]["certificate"])
        return [await self.net.rpc(self.origin, int(n), dict(op="use", origin=private["origin"],
                sequence=seq, manifest=private["manifest"])) for n, seq in private["sequences"].items()]


    async def acquire_box(self, manifest: str, branches: list[dict[str, list[str]]],
                          box: dict[str, list[list[str]]]) -> dict[str, Any]:
        from .checker import certificate, safe_envelope
        from .controller import MAX_SEQ
        from .envelope import antichain, normalize
        branches = normalize(branches)
        box = {n: antichain(options) for n, options in box.items()}
        if not safe_envelope(branches, box):
            return dict(status="not-justified", reasons=[dict(reason="unsafe-or-out-of-bound-envelope")])
        if any(not 0 <= int(n) < len(self.net.supports) for n in box):
            raise ValueError("placement outside network")
        if not isinstance(manifest, str) or not manifest or len(manifest) > 256:
            raise ValueError("manifest binding")
        await self.recover()
        for r in self.state["attempts"].values():
            if r["manifest"] == manifest:
                if (r["status"] == "committed" and r["certificate"].get("box") == box
                        and certificate(r["certificate"], branches)):
                    return dict(status="admitted", certificate=deepcopy(r["certificate"]))
                return dict(status="not-justified", reasons=[dict(reason="unresolved-or-conflicting-manifest")])
        if len(self.state["attempts"]) >= self.net.window:
            return dict(status="not-justified", reasons=[dict(reason="origin-window")])
        if self.state["serial"] == MAX_SEQ or any(self.state["next"][int(n)] == MAX_SEQ for n in box):
            return dict(status="not-justified", reasons=[dict(reason="sequence-exhausted")])
        sequences = {}
        for n in sorted(box, key=int):
            self.state["next"][int(n)] += 1
            sequences[n] = self.state["next"][int(n)]
        self.state["serial"] += 1
        key = str(self.state["serial"])
        self.state["attempts"][key] = dict(status="acquiring", manifest=manifest, sequences=sequences)
        self.persist()
        receipts, reason = [], None
        for n in sorted(box, key=int):
            reply = await self.net.rpc(self.origin, int(n), dict(op="prepare", origin=self.origin,
                sequence=sequences[n], manifest=manifest, requires=[], options=box[n]))
            if reply is None or reply["status"] != "held":
                reason = dict(node=int(n), reply=reply)
                break
            receipts.append(reply["receipt"])
        c = dict(mode="envelope", manifest=manifest, origin=self.origin, box=box,
                 sequences=sequences, receipts=receipts)
        if reason is None and certificate(c, branches):
            self.state["attempts"][key].update(status="committed", certificate=c)
            self.persist()
            return dict(status="admitted", certificate=deepcopy(c))
        self.state["attempts"][key]["status"] = "retiring"
        self.persist()
        await self._close(key)
        return dict(status="not-justified", reasons=[reason or dict(reason="certificate-rejected")])
