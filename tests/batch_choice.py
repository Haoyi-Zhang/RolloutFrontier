"""Untimed portable tests for an optional explicit-batch static choice.

The tiny oracle literally enumerates rectangles and proposal transitions. It
imports neither planner nor checker helpers for its reference calculations.
Endpoint and Client checks use owned in-memory calls, never sockets or services.
"""
from __future__ import annotations
import asyncio
import copy
from itertools import combinations, product
from math import prod
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import batch, checker, envelope
from src.controller import Endpoint, MAX_CONTRACTS, MAX_SEQ
from src.network import Client


def subsets(values):
    return [part for size in range(1, len(values) + 1) for part in combinations(values, size)]


def literal_frontier(cells, seed, widths=(2, 3)):
    safe = [(left, right) for left in subsets(range(widths[0]))
            for right in subsets(range(widths[1]))
            if seed[0] in left and seed[1] in right
            and all((i, j) in cells for i in left for j in right)]
    front = [(left, right) for left, right in safe
             if not any((left, right) != other and all(i in other[0] for i in left)
                        and all(j in other[1] for j in right) for other in safe)]
    boxes = [{"0": [[f"a{i}"] for i in left], "1": [[f"b{j}"] for j in right]}
             for left, right in front]
    key = lambda box: tuple((node, tuple(map(tuple, box[node]))) for node in sorted(box))
    mass = lambda box: prod(len(options) for options in box.values())
    terms = lambda box: sum(len(options) for options in box.values())
    boxes.sort(key=lambda box: (-mass(box), terms(box), key(box)))
    default = min(boxes, key=lambda box: (-mass(box), -terms(box), terms(box), key(box)))
    return boxes, default


def literal_batch(box, current, proposals):
    state = {node: sorted(set(values)) for node, values in current.items()}
    result = dict(proposals=len(proposals), installed=0, blocked=0, unchanged=0)
    for item in proposals:
        node, support = item["node"], sorted(set(item["support"]))
        if state[node] == support:
            result["unchanged"] += 1
        elif any(all(atom in support for atom in term) for term in box[node]):
            result["installed"] += 1
            state[node] = support
        else:
            result["blocked"] += 1
    return dict(result, final=state)


def relation_fixture(cells, seed):
    return ([{"0": [f"a{i}"], "1": [f"b{j}"]} for i, j in sorted(cells)],
            {"0": [f"a{seed[0]}"], "1": [f"b{seed[1]}"]},
            {"0": [["a0"], ["a1"]], "1": [["b0"], ["b1"], ["b2"]]})


def witness():
    branches, current, candidates = relation_fixture({(0, 0), (0, 1), (0, 2), (1, 0)}, (0, 0))
    proposals = [dict(node="0", support=[f"a{i}"]) for _ in range(100) for i in (1, 0)]
    return branches, current, candidates, proposals


def held_endpoints(branches, current, box):
    endpoints = {node: Endpoint(int(node), support) for node, support in current.items()}
    receipts = []
    for node, endpoint in endpoints.items():
        reply = endpoint.prepare(0, 1, "batch", [], options=box[node])
        if reply["status"] != "held":
            raise AssertionError(reply)
        receipts.append(reply["receipt"])
    cert = dict(mode="envelope", manifest="batch", origin=0, box=box,
                sequences={node: 1 for node in box}, receipts=receipts)
    if not checker.certificate(cert, branches):
        raise AssertionError("invalid actual receipt certificate")
    return endpoints


def endpoint_batch(branches, current, box, proposals):
    endpoints = held_endpoints(branches, current, box)
    result = dict(proposals=len(proposals), installed=0, blocked=0, unchanged=0)
    for item in proposals:
        status = endpoints[item["node"]].install(item["support"])["status"]
        result[status] += 1
        state = {node: endpoint.state["support"] for node, endpoint in endpoints.items()}
        if not any(all(all(atom in state[node] for atom in required)
                       for node, required in branch.items()) for branch in branches):
            raise AssertionError("whole-manifest safety violation")
        if not all(checker.endpoint_invariant(endpoint.state) for endpoint in endpoints.values()):
            raise AssertionError("endpoint invariant violation")
    result["final"] = {node: list(endpoint.state["support"]) for node, endpoint in endpoints.items()}
    return result


class LocalCalls:
    """Only the reviewed local operations needed by the original Client."""
    def __init__(self, directory, supports):
        self.directory = Path(directory)
        self.supports = copy.deepcopy(supports)
        self.window, self.policy = 2, "predicate"
        self.nodes = {i: Endpoint(i, values, window=self.window) for i, values in enumerate(supports)}
        self.blocked_targets = set()

    async def rpc(self, origin, node, request):
        if node in self.blocked_targets:
            return None
        values = copy.deepcopy(request)
        operation = values.pop("op")
        if operation not in {"prepare", "close", "use", "install"}:
            raise AssertionError("unexpected local operation")
        return getattr(self.nodes[node], operation)(**values)


class BatchChoiceTests(unittest.TestCase):
    def test_literal_two_by_three_frontiers_and_complete_counts(self):
        contexts = 0
        for bits in range(1, 64):
            cells = {(i, j) for i, j in product(range(2), range(3)) if bits & (1 << (3 * i + j))}
            for seed in sorted(cells):
                branches, current, candidates = relation_fixture(cells, seed)
                boxes, default = literal_frontier(cells, seed)
                proposals = [dict(node=str(node), support=[f"{'a' if node == 0 else 'b'}{i}"])
                             for node, i in ((0, 1), (1, 2), (0, 0), (1, 1), (1, 0), (0, 1))]
                result = batch.choose_batch_box(branches, current, candidates, proposals)
                self.assertEqual([member["box"] for member in result["frontier_plan"]["frontier"]], boxes)
                self.assertEqual(result["frontier_plan"]["box"], default)
                selected, score = default, literal_batch(default, current, proposals)
                for index, box in enumerate(boxes):
                    expected = literal_batch(box, current, proposals)
                    self.assertEqual(result["batch_scores"][index], dict(member_index=index, **expected))
                    self.assertEqual(sum(expected[key] for key in ("installed", "blocked", "unchanged")), 6)
                    if expected["installed"] > score["installed"]:
                        selected, score = box, expected
                self.assertEqual(result["box"], selected)
                self.assertEqual(result["forecast"], score)
                self.assertEqual(result["max_mass_forecast"], literal_batch(default, current, proposals))
                self.assertEqual(endpoint_batch(branches, current, selected, proposals), score)
                contexts += 1
        self.assertEqual(contexts, 192)

    def test_actual_200_proposal_witness_keeps_original_negative(self):
        branches, current, candidates, proposals = witness()
        original = envelope.frontier_synthesize(branches, current, candidates)
        result = batch.choose_batch_box(branches, current, candidates, proposals)
        self.assertEqual(result["frontier_plan"], original)
        self.assertEqual((original["product_mass"], original["frontier_size"]), (3, 2))
        self.assertTrue(checker.frontier_certificate(branches, current, candidates, original))
        self.assertEqual(result["max_mass_forecast"], endpoint_batch(branches, current, original["box"], proposals))
        self.assertEqual(result["forecast"], endpoint_batch(branches, current, result["box"], proposals))
        self.assertEqual(result["max_mass_forecast"]["installed"], 0)
        self.assertEqual(result["forecast"]["installed"], 200)
        self.assertEqual(result["max_mass_forecast"]["blocked"], 100)
        self.assertEqual(result["max_mass_forecast"]["unchanged"], 100)
        self.assertFalse(result["kept_max_mass"])

    def test_empty_tie_fallback_and_unseen_future_negative(self):
        branches, current, candidates, proposals = witness()
        for queue in ([], [dict(node="0", support=["a0"])] * 4):
            result = batch.choose_batch_box(branches, current, candidates, queue)
            self.assertTrue(result["kept_max_mass"])
            self.assertEqual(result["box"], result["frontier_plan"]["box"])
        selected = batch.choose_batch_box(branches, current, candidates, proposals)
        other = [dict(node="1", support=[f"b{i}"]) for _ in range(100) for i in (1, 0)]
        self.assertEqual(endpoint_batch(branches, current, selected["box"], other)["installed"], 0)
        self.assertEqual(endpoint_batch(branches, current, selected["frontier_plan"]["box"], other)["installed"], 200)
        self.assertTrue(batch.choose_batch_box(branches, current, candidates, other)["kept_max_mass"])

    def test_batch_and_atom_caps_strict_items_and_error_precedence(self):
        branches, current, candidates, _ = witness()
        item = dict(node="0", support=["a0"])
        result = batch.choose_batch_box(branches, current, candidates, [item] * 256)
        self.assertEqual(result["forecast"]["unchanged"], 256)
        for queue, message in (([item] * 257, "proposal batch bound"),
                               ((item,), "proposal batch bound"),
                               ([dict(item, ignored=1)], "proposal batch item"),
                               ([{"node": True, "support": []}], "proposal batch item"),
                               ([{"node": "00", "support": []}], "proposal batch item"),
                               ([{"node": "2", "support": []}], "proposal batch item"),
                               ([{"node": "0"}], "proposal batch item"),
                               ([{"node": "0", "support": "a0"}], "contracts must be an explicit finite collection"),
                               ([{"node": "0", "support": [""]}], "invalid contract atom"),
                               ([{"node": "0", "support": ["x"] * (MAX_CONTRACTS + 1)}], "contract bound exceeded")):
            with self.subTest(message=message), self.assertRaises(ValueError) as caught:
                batch.choose_batch_box(branches, current, candidates, queue)
            self.assertEqual(str(caught.exception), message)
        with self.assertRaisesRegex(ValueError, "^exact frontier search-state bound$"):
            batch.choose_batch_box([], {}, {}, None, max_states=0)

    def test_full_support_changes_weights_projection_and_input_isolation(self):
        branches = [{"0": ["a"]}, {"0": ["b"]}]
        current = {"0": ["a", "old"]}
        candidates = {"0": [["a"], ["a", "extra"], ["b"], ["b"]]}
        weights = {"0": [0, 2, 0, 3]}
        queue = [dict(node="0", support=["new", "a", "a"]),
                 dict(node="0", support=["b"]), dict(node="0", support=[]),
                 dict(node="0", support=["b"])]
        inputs = copy.deepcopy((branches, current, candidates, queue, weights))
        result = batch.choose_batch_box(branches, current, candidates, queue, weights)
        self.assertEqual(result["frontier_plan"], envelope.frontier_synthesize(branches, current, candidates, weights))
        self.assertEqual(result["forecast"], endpoint_batch(branches, current, result["box"], queue))
        self.assertEqual(result["forecast"], dict(proposals=4, installed=2, blocked=1, unchanged=1, final={"0": ["b"]}))
        self.assertEqual((branches, current, candidates, queue, weights), inputs)
        result["box"]["0"][0].append("mutated-output")
        result["forecast"]["final"]["0"].append("mutated-output")
        self.assertEqual((branches, current, candidates, queue, weights), inputs)
        plan = batch.choose_batch_box([{"0": []}], {"0": []}, {"0": [[], ["outside"]]},
                                      [dict(node="0", support=["outside"])], {"0": [0, 0]})
        self.assertEqual(plan["forecast"]["installed"], 1)
        self.assertEqual(plan["frontier_plan"]["product_mass"], 0)

    def test_original_search_result_caps_and_errors_propagate(self):
        branches, current, candidates, queue = witness()
        plan = envelope.frontier_synthesize(branches, current, candidates)
        required = plan["search"]["states"]
        with self.assertRaisesRegex(ValueError, "^exact frontier search-state bound$"):
            batch.choose_batch_box(branches, current, candidates, queue, max_states=required - 1)
        self.assertEqual(batch.choose_batch_box(branches, current, candidates, queue,
                                               max_states=required)["frontier_plan"], plan)
        with patch.object(envelope, "MAX_FRONTIER_PLANS", 1):
            with self.assertRaisesRegex(ValueError, "^exact frontier result bound$"):
                batch.choose_batch_box(branches, current, candidates, queue)
        self.assertEqual(envelope.MAX_FRONTIER_PLANS, 4096)
        with self.assertRaisesRegex(ValueError, "^weights must be bounded nonnegative integers$"):
            batch.choose_batch_box(branches, current, candidates, queue, {"0": [True, 1], "1": [1, 1, 1]})

    def test_independent_rejection_never_silently_returns_a_box(self):
        branches, current, candidates, queue = witness()
        plan = envelope.frontier_synthesize(branches, current, candidates)
        mutants = []
        changed = copy.deepcopy(plan); changed["search"]["states"] += 1; mutants.append(changed)
        changed = copy.deepcopy(plan); changed["frontier_size"] = float(changed["frontier_size"]); mutants.append(changed)
        changed = copy.deepcopy(plan); changed["frontier"].pop(); changed["frontier_size"] -= 1; mutants.append(changed)
        for changed in mutants:
            with patch.object(batch, "frontier_synthesize", return_value=changed):
                with self.assertRaisesRegex(ValueError, "^batch frontier certificate rejected$"):
                    batch.choose_batch_box(branches, current, candidates, queue)

    def test_optional_choice_is_not_a_max_mass_certificate(self):
        branches, current, candidates, queue = witness()
        result = batch.choose_batch_box(branches, current, candidates, queue)
        self.assertTrue(checker.safe_envelope(branches, result["box"]))
        self.assertFalse(checker.frontier_certificate(branches, current, candidates, result))
        forged = copy.deepcopy(result["frontier_plan"])
        alternative = next(member for member in forged["frontier"] if member["box"] == result["box"])
        forged.update(copy.deepcopy(alternative))
        forged["certificate"] = envelope.verify_box(branches, forged["box"])
        self.assertFalse(checker.frontier_certificate(branches, current, candidates, forged))
        self.assertFalse(checker.safe_envelope(branches, {"0": [["a0"], ["a1"]], "1": [["b0"], ["b1"]]}))

    def test_other_holds_and_generation_exhaustion_remain_real_limits(self):
        branches, current, candidates, queue = witness()
        chosen = batch.choose_batch_box(branches, current, candidates, queue)
        endpoints = held_endpoints(branches, current, chosen["box"])
        self.assertEqual(endpoints["0"].prepare(1, 1, "other", ["a0"])["status"], "held")
        guarded = copy.deepcopy(endpoints["0"].state)
        self.assertEqual(endpoints["0"].install(["a1"])["status"], "blocked")
        self.assertEqual(endpoints["0"].state, guarded)
        self.assertEqual(endpoints["0"].close(1, 1)["status"], "closed")
        endpoints["0"].state["generation"] = MAX_SEQ
        endpoints["0"].state["catalog"]["0"] = endpoints["0"].profile()
        endpoints["0"]._validate_loaded_state(endpoints["0"].state, 8, "predicate")
        self.assertEqual(endpoints["0"].install(["a1"])["status"], "generation-exhausted")
        self.assertEqual(endpoints["0"].state["support"], ["a0"])

    def test_admission_receipts_reopen_retire_and_delayed_prepare(self):
        async def scenario():
            branches, current, candidates, queue = witness()
            chosen = batch.choose_batch_box(branches, current, candidates, queue)
            with tempfile.TemporaryDirectory(prefix="batch-choice-", dir=os.environ.get("P011_TEST_TMP")) as tmp:
                calls = LocalCalls(tmp, [current["0"], current["1"]])
                client = Client(calls)
                try:
                    unsafe = {"0": [["a0"], ["a1"]], "1": [["b0"], ["b1"]]}
                    refused = await client.acquire_box("unsafe", branches, unsafe)
                    self.assertEqual(refused["status"], "not-justified")
                    self.assertEqual(client.state["serial"], 0)
                    answer = await client.acquire_box("batch", branches, chosen["box"])
                    self.assertEqual(answer["status"], "admitted")
                    cert = answer["certificate"]
                    self.assertTrue(checker.certificate(cert, branches))
                    client.disconnect(); client = Client(calls)
                    self.assertTrue(all(reply["status"] == "used" for reply in await client.use(cert)))
                    for item in queue:
                        self.assertEqual(calls.nodes[int(item["node"])].install(item["support"])["status"], "installed")
                    self.assertTrue(await client.retire(cert))
                    self.assertEqual((await client.use(cert))[0]["status"], "not-authorized")
                    self.assertEqual(calls.nodes[0].prepare(0, 1, "batch", [],
                                     options=chosen["box"]["0"])["status"], "closed")
                finally:
                    client.disconnect()
        asyncio.run(scenario())

    def test_failed_close_still_stops_fixed_branch_fallback(self):
        async def scenario():
            branches = [{"0": ["a"], "1": ["a"]}, {"0": ["a"], "1": ["b"]}]
            with tempfile.TemporaryDirectory(prefix="batch-fallback-", dir=os.environ.get("P011_TEST_TMP")) as tmp:
                calls = LocalCalls(tmp, [["a"], ["a"]]); calls.blocked_targets.add(1)
                client = Client(calls)
                try:
                    answer = await client.acquire("m", branches)
                    self.assertEqual(answer["reasons"][-1], dict(branch=0, reason="retirement-unconfirmed"))
                    self.assertEqual(client.state["serial"], 1)
                    self.assertEqual(client.state["next"], [1, 1])
                    self.assertEqual(client.state["attempts"], {"1": dict(status="retiring", manifest="m", sequences={"0": 1, "1": 1})})
                    client.disconnect(); client = Client(calls)
                    await client.recover()
                    self.assertEqual(len(client.state["attempts"]), 1)
                    refused = await client.acquire_box("m", branches, {"0": [["a"]], "1": [["a"]]})
                    self.assertEqual(refused["reasons"], [dict(reason="unresolved-or-conflicting-manifest")])
                    self.assertEqual(client.state["serial"], 1)
                    calls.blocked_targets.clear()
                    self.assertEqual(calls.nodes[1].prepare(0, 1, "m", ["a"])["status"], "held")
                    await client.recover()
                    self.assertEqual(client.state["attempts"], {})
                    self.assertEqual(calls.nodes[1].prepare(0, 1, "m", ["a"])["status"], "closed")
                finally:
                    client.disconnect()
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
