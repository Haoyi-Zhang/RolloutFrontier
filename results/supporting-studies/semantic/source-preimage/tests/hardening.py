"""Adversarial schema, durable-state, atomicity, and serialization regressions.

These checks exercise owned loopback endpoints and temporary SQLite files only.
They do not model Byzantine peers, concurrent origin writers, power loss, or WANs.
"""
from __future__ import annotations
import asyncio
import copy
import json
from pathlib import Path
import resource
import sqlite3
import tempfile
import time
from typing import Callable

from src.checker import certificate, endpoint_invariant, frontier_certificate
from src.controller import Endpoint, canonical
from src.envelope import frontier_synthesize
from src.network import Client, Network


def reject(name: str, action: Callable[[], object], accepted: list[str]) -> None:
    try:
        action()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, sqlite3.DatabaseError):
        accepted.append(name)
        return
    raise AssertionError(f"malformed state accepted: {name}")


def certificate_schemas() -> dict:
    fixed_branches = [{"0": ["a"]}]
    fixed_endpoint = Endpoint(0, ["a"])
    fixed_reply = fixed_endpoint.prepare(0, 1, "fixed", ["a"])
    fixed = dict(manifest="fixed", origin=0, branch=0, sequences={"0": 1},
                 receipts=[fixed_reply["receipt"]])
    assert certificate(fixed, fixed_branches)

    envelope_branches = [{"0": ["a"]}, {"0": ["b"]}]
    envelope_endpoint = Endpoint(0, ["a"])
    envelope_reply = envelope_endpoint.prepare(0, 1, "envelope", [],
                                                options=[["a"], ["b"]])
    envelope = dict(mode="envelope", manifest="envelope", origin=0,
                    box={"0": [["a"], ["b"]]}, sequences={"0": 1},
                    receipts=[envelope_reply["receipt"]])
    assert certificate(envelope, envelope_branches)

    current = {"0": ["a"], "1": ["x"]}
    candidates = {"0": [["a"], ["b"]], "1": [["x"], ["y"]]}
    frontier_branches = [
        {"0": ["a"], "1": ["x"]},
        {"0": ["a"], "1": ["y"]},
        {"0": ["b"], "1": ["x"]},
    ]
    plan = frontier_synthesize(frontier_branches, current, candidates)
    assert frontier_certificate(frontier_branches, current, candidates, plan)

    # A one-owner result exposes Python's numeric equality aliases most directly:
    # True == 1, False == 0, and 1.0 == 1.  The checker must reject those
    # substitutions even when ordinary dictionary equality would accept them.
    typed_branches = [{"0": ["a"]}, {"0": ["b"]}]
    typed_current = {"0": ["a"]}
    typed_candidates = {"0": [["a"], ["b"]]}
    typed_weights = {"0": [1, 0]}
    typed_plan = frontier_synthesize(
        typed_branches, typed_current, typed_candidates, weights=typed_weights)
    assert typed_plan["frontier_size"] == 1
    assert frontier_certificate(
        typed_branches, typed_current, typed_candidates, typed_plan,
        weights=typed_weights)

    rejected: list[str] = []

    def fixed_mutation(name, mutate):
        value = copy.deepcopy(fixed); mutate(value)
        assert not certificate(value, fixed_branches); rejected.append(name)

    fixed_mutation("fixed-extra-top-level", lambda c: c.__setitem__("ignored", 1))
    fixed_mutation("fixed-extra-receipt", lambda c: c["receipts"][0].__setitem__("ignored", 1))
    fixed_mutation("fixed-spurious-mode", lambda c: c.__setitem__("mode", "fixed"))
    fixed_mutation("fixed-boolean-origin", lambda c: c.__setitem__("origin", True))

    def envelope_mutation(name, mutate):
        value = copy.deepcopy(envelope); mutate(value)
        assert not certificate(value, envelope_branches); rejected.append(name)

    envelope_mutation("envelope-extra-top-level", lambda c: c.__setitem__("ignored", 1))
    envelope_mutation("envelope-extra-receipt", lambda c: c["receipts"][0].__setitem__("ignored", 1))
    envelope_mutation("envelope-duplicate-option", lambda c: c["box"]["0"].append(["a"]))
    envelope_mutation("envelope-redundant-option", lambda c: c["box"]["0"].append(["a", "b"]))

    def frontier_mutation(name, mutate):
        value = copy.deepcopy(plan); mutate(value)
        assert not frontier_certificate(frontier_branches, current, candidates, value)
        rejected.append(name)

    frontier_mutation("frontier-extra-top-level", lambda p: p.__setitem__("ignored", 1))
    frontier_mutation("frontier-extra-member-field", lambda p: p["frontier"][0].__setitem__("ignored", 1))
    frontier_mutation("frontier-extra-certificate-field", lambda p: p["certificate"].__setitem__("ignored", 1))
    frontier_mutation("frontier-extra-objective-field", lambda p: p["objective"].__setitem__("ignored", 1))

    type_rejected: list[str] = []

    def typed_mutation(name, mutate):
        value = copy.deepcopy(typed_plan); mutate(value)
        assert not frontier_certificate(
            typed_branches, typed_current, typed_candidates, value,
            weights=typed_weights)
        type_rejected.append(name)

    typed_mutation("selected-frontier-size-true", lambda p: p.__setitem__("frontier_size", True))
    typed_mutation("selected-product-mass-true", lambda p: p.__setitem__("product_mass", True))
    typed_mutation("selected-product-mass-float", lambda p: p.__setitem__("product_mass", 1.0))
    typed_mutation("selected-local-mass-true", lambda p: p["local_masses"].__setitem__("0", True))
    typed_mutation("selected-count-float", lambda p: p["accepted_unique_profiles"].__setitem__("0", 2.0))
    typed_mutation("selected-guard-terms-float", lambda p: p.__setitem__("guard_terms", 2.0))
    typed_mutation("member-product-mass-true", lambda p: p["frontier"][0].__setitem__("product_mass", True))
    typed_mutation("member-local-mass-float", lambda p: p["frontier"][0]["local_masses"].__setitem__("0", 1.0))
    typed_mutation("member-count-float", lambda p: p["frontier"][0]["accepted_unique_profiles"].__setitem__("0", 2.0))
    typed_mutation("member-guard-terms-float", lambda p: p["frontier"][0].__setitem__("guard_terms", 2.0))
    typed_mutation("search-zero-false", lambda p: p["search"].__setitem__("corner_pruned", False))
    typed_mutation("search-states-float", lambda p: p["search"].__setitem__("states", 3.0))
    typed_mutation("certificate-safe-one", lambda p: p["certificate"].__setitem__("safe", 1))
    typed_mutation("certificate-corners-float", lambda p: p["certificate"].__setitem__("corners", 2.0))
    typed_mutation("exact-one", lambda p: p.__setitem__("exact", 1))
    typed_mutation("selected-frontier-size-zero", lambda p: p.__setitem__("frontier_size", 0))
    typed_mutation("selected-product-mass-negative", lambda p: p.__setitem__("product_mass", -1))
    typed_mutation("selected-count-zero", lambda p: p["accepted_unique_profiles"].__setitem__("0", 0))
    typed_mutation("member-guard-terms-zero", lambda p: p["frontier"][0].__setitem__("guard_terms", 0))
    typed_mutation("search-states-zero", lambda p: p["search"].__setitem__("states", 0))
    typed_mutation("certificate-corners-zero", lambda p: p["certificate"].__setitem__("corners", 0))

    return dict(valid_certificates=4, rejected_mutations=rejected,
                rejected_numeric_type_aliases=type_rejected,
                strict_unknown_fields=True, canonical_envelope_options=True,
                strict_numeric_types=True)


def update_payload(path: Path, mutate: Callable[[dict], None]) -> None:
    with sqlite3.connect(path) as db:
        payload = json.loads(db.execute("SELECT payload FROM state WHERE id=1").fetchone()[0])
        mutate(payload)
        db.execute("UPDATE state SET payload=? WHERE id=1", (canonical(payload),))


def duplicate_state_row(path: Path) -> None:
    with sqlite3.connect(path) as db:
        payload = db.execute("SELECT payload FROM state WHERE id=1").fetchone()[0]
        db.execute("INSERT INTO state(id,payload) VALUES(2,?)", (payload,))


def move_state_row(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("UPDATE state SET id=2 WHERE id=1")


def add_shadow_column(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE state ADD COLUMN shadow TEXT")


def endpoint_state_validation(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    rejected: list[str] = []

    def make(name: str) -> Path:
        path = root / f"endpoint-{name}.sqlite"
        endpoint = Endpoint(0, ["a", "b"], path, window=2, policy="predicate")
        assert endpoint.prepare(0, 1, "held", ["a"])["status"] == "held"
        endpoint.disconnect()
        return path

    path = make("policy")
    reject("endpoint-policy-mismatch", lambda: Endpoint(0, [], path, window=2, policy="epoch"), rejected)
    path = make("window")
    reject("endpoint-window-mismatch", lambda: Endpoint(0, [], path, window=3, policy="predicate"), rejected)

    mutations = {
        "endpoint-extra-state-field": lambda s: s.__setitem__("ignored", 1),
        "endpoint-boolean-floor": lambda s: s["floor"].__setitem__(0, True),
        "endpoint-duplicate-support": lambda s: s["support"].append("a"),
        "endpoint-self-profile-mismatch": lambda s: s["catalog"]["0"].__setitem__("generation", 1),
        "endpoint-extra-hold-field": lambda s: s["slots"]["0:1"].__setitem__("ignored", 1),
        "endpoint-slot-outside-window": lambda s: (
            s["slots"].__setitem__("0:3", s["slots"].pop("0:1")),
            s["slots"]["0:3"].__setitem__("sequence", 3)),
    }
    for name, mutate in mutations.items():
        path = make(name)
        update_payload(path, mutate)
        reject(name, lambda p=path: Endpoint(0, [], p, window=2, policy="predicate"), rejected)

    for name, mutate_db in (
            ("endpoint-extra-state-row", duplicate_state_row),
            ("endpoint-missing-canonical-row", move_state_row),
            ("endpoint-shadow-schema-column", add_shadow_column)):
        path = make(name)
        mutate_db(path)
        reject(name, lambda p=path: Endpoint(0, [], p, window=2, policy="predicate"), rejected)

    valid = make("valid")
    endpoint = Endpoint(0, [], valid, window=2, policy="predicate")
    assert endpoint.state["slots"]["0:1"]["status"] == "held"
    endpoint.disconnect()
    return dict(valid_reopen=True, rejected_states=rejected)


async def _committed_origin(root: Path) -> Path:
    network = Network(root, [["a"], ["a"]], window=2)
    await network.start()
    client = Client(network, origin=0)
    try:
        answer = await client.acquire("saved", [{"0": ["a"], "1": ["a"]}])
        assert answer["status"] == "admitted"
    finally:
        client.disconnect()
        await network.stop()
    return root / "origin-0.sqlite"


def client_state_validation(root: Path) -> dict:
    rejected: list[str] = []

    size_root = root / "node-count"
    network = Network(size_root, [["a"], ["a"]], window=2)
    client = Client(network); client.disconnect()
    wider = Network(size_root, [["a"], ["a"], ["a"]], window=2)
    reject("origin-node-count-mismatch", lambda: Client(wider), rejected)

    window_root = root / "window-mismatch"
    network = Network(window_root, [["a"], ["a"]], window=2)
    client = Client(network); client.disconnect()
    changed_window = Network(window_root, [["a"], ["a"]], window=3)
    reject("origin-window-mismatch", lambda: Client(changed_window), rejected)

    policy_root = root / "policy-mismatch"
    network = Network(policy_root, [["a"], ["a"]], window=2, policy="predicate")
    client = Client(network); client.disconnect()
    changed_policy = Network(policy_root, [["a"], ["a"]], window=2, policy="epoch")
    reject("origin-policy-mismatch", lambda: Client(changed_policy), rejected)

    mutations = {
        "origin-identity-mismatch": lambda s: s.__setitem__("origin", 1),
        "origin-boolean-next": lambda s: s["next"].__setitem__(0, True),
        "origin-extra-state-field": lambda s: s.__setitem__("ignored", 1),
        "origin-boolean-attempt-sequence": lambda s: (
            s.__setitem__("serial", 1), s["next"].__setitem__(0, 1),
            s["attempts"].__setitem__("1", dict(status="acquiring", manifest="m",
                                                  sequences={"0": True}))),
    }
    for name, mutate in mutations.items():
        case = root / name
        network = Network(case, [["a"], ["a"]], window=2)
        client = Client(network); client.disconnect()
        path = case / "origin-0.sqlite"
        update_payload(path, mutate)
        reject(name, lambda n=network: Client(n), rejected)

    for name, mutate_db in (
            ("origin-extra-state-row", duplicate_state_row),
            ("origin-missing-canonical-row", move_state_row),
            ("origin-shadow-schema-column", add_shadow_column)):
        case = root / name
        network = Network(case, [["a"], ["a"]], window=2)
        client = Client(network); client.disconnect()
        path = case / "origin-0.sqlite"
        mutate_db(path)
        reject(name, lambda n=network: Client(n), rejected)

    duplicate_root = root / "duplicate-manifest"
    duplicate_network = Network(duplicate_root, [["a"], ["a"]], window=2)
    duplicate_client = Client(duplicate_network); duplicate_client.disconnect()
    duplicate_path = duplicate_root / "origin-0.sqlite"
    def duplicate_manifest(state):
        state["serial"] = 2
        state["next"][0] = 2
        state["attempts"] = {
            "1": dict(status="acquiring", manifest="duplicate", sequences={"0": 1}),
            "2": dict(status="retiring", manifest="duplicate", sequences={"0": 2}),
        }
    update_payload(duplicate_path, duplicate_manifest)
    reject("origin-duplicate-manifest", lambda: Client(duplicate_network), rejected)

    committed_root = root / "committed"
    path = asyncio.run(_committed_origin(committed_root))
    update_payload(path, lambda s: s["attempts"]["1"]["certificate"].__setitem__("ignored", 1))
    committed_network = Network(committed_root, [["a"], ["a"]], window=2)
    reject("origin-extra-certificate-field", lambda: Client(committed_network), rejected)

    valid_root = root / "valid"
    path = asyncio.run(_committed_origin(valid_root))
    valid_network = Network(valid_root, [["a"], ["a"]], window=2)
    client = Client(valid_network)
    assert client.state["attempts"]["1"]["status"] == "committed"
    client.disconnect()
    return dict(valid_reopen=True, rejected_states=rejected)


def atomic_installation() -> dict:
    endpoint = Endpoint(0, ["a", "b", "c"])
    before = copy.deepcopy(endpoint.state)
    held = endpoint.prepare(0, 1, "atomic", ["a"])
    assert held["status"] == "held"
    guarded = copy.deepcopy(endpoint.state)
    blocked = endpoint.install(["b", "c"])
    assert blocked["status"] == "blocked"
    assert endpoint.state["support"] == guarded["support"]
    assert endpoint.state["generation"] == guarded["generation"]
    assert endpoint.state["catalog"] == guarded["catalog"]
    assert endpoint.close(0, 1)["status"] == "closed"
    installed = endpoint.install(["b", "c"])
    assert installed["status"] == "installed"
    assert endpoint.state["support"] == ["b", "c"] and endpoint.state["generation"] == 1
    assert before["generation"] == 0 and endpoint_invariant(endpoint.state)
    return dict(change_atoms=3, blocked_status=blocked["status"],
                state_unchanged_while_blocked=True, after_retirement=installed["status"],
                final_support=endpoint.state["support"], final_generation=1)


async def fixed_branch_cleanup_recovery(root: Path) -> dict:
    """Regression for uncertain branch cleanup followed by origin restart.

    A lost prepare can still be delivered after the origin has observed failure.
    Therefore a failed close must retain one durable attempt and stop fallback to
    the next branch for the same manifest.  Healing then closes a deliberately
    injected late hold, and the closed floor rejects another delayed prepare.
    """
    branches = [
        {"0": ["a"], "1": ["a"]},
        {"0": ["a"], "1": ["b"]},
    ]
    network = Network(root, [["a"], ["a"]], window=2)
    await network.start()
    client = Client(network, origin=0)
    reopened = None
    try:
        network.blocked.add((0, 1))
        answer = await client.acquire("m", branches)
        assert answer["status"] == "not-justified"
        assert answer["reasons"][-1] == {
            "branch": 0, "reason": "retirement-unconfirmed"}
        assert client.state["serial"] == 1
        assert client.state["next"] == [1, 1]
        assert len(client.state["attempts"]) == 1
        key, record = next(iter(client.state["attempts"].items()))
        assert key == "1" and record == {
            "status": "retiring", "manifest": "m",
            "sequences": {"0": 1, "1": 1}}

        # Reopen must accept the unique unresolved record. Recovery while the
        # partition remains cannot delete it merely because node 0 confirmed.
        client.disconnect()
        client = None
        reopened = Client(network, origin=0)
        assert len(reopened.state["attempts"]) == 1
        await reopened.recover()
        assert len(reopened.state["attempts"]) == 1

        # The originally lost prepare may arrive once communication heals. It
        # becomes a real hold and must be retired using the preserved record.
        network.blocked.clear()
        delayed_request = dict(op="prepare", origin=0, sequence=1,
                               manifest="m", requires=["a"])
        delayed = await network.rpc(0, 1, delayed_request)
        assert delayed["status"] == "held"
        assert network.nodes[1].state["slots"]["0:1"]["status"] == "held"
        await reopened.recover()
        assert reopened.state["attempts"] == {}
        assert network.nodes[1].state["floor"][0] == 1
        assert "0:1" not in network.nodes[1].state["slots"]

        late_again = await network.rpc(0, 1, delayed_request)
        assert late_again["status"] == "closed"
        assert "0:1" not in network.nodes[1].state["slots"]
        return dict(
            branches=len(branches), window=2, blocked_link=[0, 1],
            attempts_after_failed_close=1, fallback_stopped_at_branch=0,
            reopen_succeeded=True, unresolved_retained_during_partition=True,
            delayed_prepare_before_cleanup=delayed["status"],
            delayed_hold_retired_after_healing=True,
            delayed_prepare_after_cleanup=late_again["status"],
            duplicate_manifest_records=0,
        )
    finally:
        if client is not None:
            client.disconnect()
        if reopened is not None:
            reopened.disconnect()
        await network.stop()


async def raw_pair(port: int, first: dict, second: dict) -> tuple[dict, dict]:
    reader_a, writer_a = await asyncio.open_connection("127.0.0.1", port)
    reader_b, writer_b = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer_a.write((canonical(first) + "\n").encode())
        writer_b.write((canonical(second) + "\n").encode())
        await asyncio.gather(writer_a.drain(), writer_b.drain())
        line_a, line_b = await asyncio.gather(reader_a.readline(), reader_b.readline())
        return json.loads(line_a), json.loads(line_b)
    finally:
        writer_a.close(); writer_b.close()
        await asyncio.gather(writer_a.wait_closed(), writer_b.wait_closed(),
                             return_exceptions=True)


async def rpc_and_serialization(root: Path) -> dict:
    caller_supports = [["a"]]
    network = Network(root, caller_supports, window=64)
    caller_supports[0].append("mutated")
    caller_supports.append(["phantom"])
    assert network.supports == [["a"]]
    await network.start()
    try:
        mutable = {"op": "read"}
        assert (await network.rpc(0, 0, mutable))["status"] == "observed"
        mutable["ignored"] = 1
        assert network.trace[-1]["request"] == {"op": "read"}

        queued = {"op": "install", "support": ["queued"]}
        network.enqueue(0, 0, queued, delay=1)
        queued["support"].clear()
        await network.drain()
        assert network.nodes[0].state["support"] == ["queued"]
        assert (await network.rpc(0, 0, {"op": "install", "support": ["a"]}))["status"] == "installed"

        invalid_requests = [
            {"op": "read", "ignored": 1},
            {"op": "inspect", "ignored": 1},
            {"op": "install", "support": ["a"], "ignored": 1},
            {"op": "merge", "profile": {"node": 0, "generation": 0, "support": ["a"]}, "ignored": 1},
            {"op": "close", "origin": 0, "sequence": 1, "ignored": 1},
            {"op": "use", "origin": 0, "sequence": 1, "manifest": "m", "ignored": 1},
            {"op": "prepare", "origin": 0, "sequence": 1, "manifest": "m",
             "requires": ["a"], "ignored": 1},
        ]
        for request in invalid_requests:
            answer = await network.rpc(0, 0, request)
            assert answer["status"] == "invalid"

        races = 64
        for sequence in range(1, races + 1):
            prepare = dict(op="prepare", origin=0, sequence=sequence,
                           manifest=f"race-{sequence}", requires=["a"])
            install = dict(op="install", support=[])
            if sequence % 2:
                left, right = await raw_pair(network.ports[0], prepare, install)
                prepared, changed = left, right
            else:
                left, right = await raw_pair(network.ports[0], install, prepare)
                changed, prepared = left, right
            outcome = (prepared["status"], changed["status"])
            assert outcome in {("held", "blocked"), ("missing", "installed")}
            closed = await network.rpc(0, 0, dict(op="close", origin=0, sequence=sequence))
            assert closed["status"] == "closed"
            reset = await network.rpc(0, 0, dict(op="install", support=["a"]))
            assert reset["status"] in ("installed", "unchanged")
            assert endpoint_invariant(network.nodes[0].state)
        return dict(rejected_unknown_field_requests=len(invalid_requests),
                    concurrent_prepare_install_pairs=races,
                    caller_support_alias_detached=True,
                    rpc_trace_request_snapshot=True,
                    delayed_queue_request_snapshot=True,
                    allowed_outcomes=["held/blocked", "missing/installed"],
                    invariant_violations=0,
                    scope="two TCP clients, one serialized endpoint; not multi-writer origin failover")
    finally:
        await network.stop()


def run() -> dict:
    started, cpu = time.perf_counter(), time.process_time()
    with tempfile.TemporaryDirectory(prefix="compat-hardening-") as directory:
        root = Path(directory)
        result = dict(
            certificate_schemas=certificate_schemas(),
            endpoint_state=endpoint_state_validation(root / "endpoint"),
            origin_state=client_state_validation(root / "origin"),
            atomic_install=atomic_installation(),
            fixed_branch_cleanup=asyncio.run(
                fixed_branch_cleanup_recovery(root / "fixed-branch-cleanup")),
            rpc_serialization=asyncio.run(rpc_and_serialization(root / "rpc")),
        )
    result.update(
        cpu_seconds=time.process_time() - cpu,
        wall_seconds=time.perf_counter() - started,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
