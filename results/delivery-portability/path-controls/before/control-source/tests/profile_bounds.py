"""Portable regressions for projected-profile guards and their durable encoding.

Run with ``python -B -m unittest tests.profile_bounds -v``. These fixtures use
only declared positive sets, owned SQLite files, and loopback marker operations.
They are separate from the retained five-test smoke-result denominator.
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from src.checker import certificate, frontier_certificate, safe_envelope
from src.controller import Endpoint, MAX_CONTRACTS, MAX_REQUIREMENTS
from src.envelope import antichain, frontier_synthesize, synthesize, verify_box
from src.network import Client, Network


def correlated_union(shared_count=95, branch_width=1):
    shared = [f"shared.{i:03d}" for i in range(shared_count)]
    left = [f"left.{i:03d}" for i in range(branch_width)]
    right = [f"right.{i:03d}" for i in range(branch_width)]
    branches = [{"0": ["a"], "1": sorted(shared + left)},
                {"0": ["b"], "1": sorted(shared + right)}]
    union = sorted(shared + left + right)
    current = {"0": ["a"], "1": union}
    candidates = {"0": [["a"], ["b"]], "1": [union]}
    return branches, current, candidates


class ProjectedProfileTests(unittest.TestCase):
    def test_exact_requires_a_97_atom_guard(self):
        branches, current, candidates = correlated_union()
        plan = frontier_synthesize(branches, current, candidates)
        self.assertEqual(plan["box"], {"0": [["a"], ["b"]], "1": [current["1"]]})
        self.assertEqual(plan["product_mass"], 2)
        self.assertEqual(plan["frontier_size"], 1)
        self.assertTrue(frontier_certificate(branches, current, candidates, plan))
        self.assertTrue(safe_envelope(branches, plan["box"]))

    def test_exact_requires_two_disjoint_96_atom_requirements(self):
        branches, current, candidates = correlated_union(0, 96)
        plan = frontier_synthesize(branches, current, candidates)
        self.assertEqual(len(plan["box"]["1"][0]), 192)
        self.assertEqual(plan["accepted_unique_profiles"], {"0": 2, "1": 1})
        self.assertTrue(frontier_certificate(branches, current, candidates, plan))

    def test_greedy_uses_the_same_guard_encoding(self):
        branches, current, candidates = correlated_union()
        plan = synthesize(branches, current, candidates)
        self.assertFalse(plan["bounded"])
        self.assertEqual(plan["box"], {"0": [["a"], ["b"]], "1": [current["1"]]})
        self.assertTrue(safe_envelope(branches, plan["box"]))

    def test_eight_branch_projection_union_is_encodable(self):
        branches = [{"0": [f"branch.{j}.{i:03d}" for i in range(96)]}
                    for j in range(8)]
        union = sorted({atom for branch in branches for atom in branch["0"]})
        self.assertEqual(len(union), 768)
        box = {"0": [union]}
        self.assertEqual(verify_box(branches, box), {"safe": True, "corners": 1})
        self.assertTrue(safe_envelope(branches, box))

    def test_input_support_projection_keeps_the_12000_atom_domain(self):
        branches = [{"0": ["required"]}]
        full = ["required"] + [f"irrelevant.{i:05d}" for i in range(MAX_CONTRACTS - 1)]
        plan = frontier_synthesize(branches, {"0": full}, {"0": [full]})
        self.assertEqual(plan["box"], {"0": [["required"]]})
        self.assertTrue(frontier_certificate(branches, {"0": full}, {"0": [full]}, plan))

    def test_fixed_requirement_and_support_caps_are_preserved(self):
        endpoint = Endpoint(0, [f"a.{i}" for i in range(MAX_REQUIREMENTS + 1)])
        with self.assertRaises(ValueError):
            endpoint.prepare(0, 1, "fixed", endpoint.profile()["support"])
        oversized = [f"a.{i}" for i in range(MAX_CONTRACTS + 1)]
        with self.assertRaises(ValueError):
            antichain([oversized])
        self.assertFalse(safe_envelope([{"0": ["a.0"]}], {"0": [oversized]}))
        with self.assertRaises(ValueError):
            endpoint.prepare(0, 1, "oversized", [], options=[oversized])

    def test_large_guard_endpoint_reopen_and_retirement(self):
        branches, current, _ = correlated_union()
        options = [current["1"]]
        with tempfile.TemporaryDirectory(prefix="profile-guard-") as tmp:
            path = Path(tmp) / "owner.sqlite"
            endpoint = Endpoint(1, current["1"], path)
            try:
                self.assertEqual(endpoint.prepare(0, 1, "large", [], options=options)["status"], "held")
            finally:
                endpoint.disconnect()
            endpoint = Endpoint(1, [], path)
            try:
                self.assertEqual(endpoint.install(branches[0]["1"])["status"], "blocked")
                self.assertEqual(endpoint.use(0, 1, "large")["status"], "used")
                self.assertEqual(endpoint.close(0, 1)["status"], "closed")
                self.assertEqual(endpoint.install(branches[0]["1"])["status"], "installed")
            finally:
                endpoint.disconnect()

    def test_large_guard_loopback_admission_origin_reopen(self):
        async def scenario():
            branches, current, _ = correlated_union()
            box = {"0": [["a"], ["b"]], "1": [current["1"]]}
            with tempfile.TemporaryDirectory(prefix="profile-network-") as tmp:
                net = Network(Path(tmp), [current["0"], current["1"]])
                await net.start()
                client = Client(net)
                try:
                    result = await client.acquire_box("large", branches, box)
                    self.assertEqual(result["status"], "admitted")
                    cert = result["certificate"]
                    self.assertTrue(certificate(cert, branches))
                    client.disconnect()
                    client = Client(net)
                    await net.crash(1)
                    self.assertTrue(all(reply["status"] == "used" for reply in await client.use(cert)))
                    changed = await net.rpc(0, 0, {"op": "install", "support": ["b"]})
                    self.assertEqual(changed["status"], "installed")
                    blocked = await net.rpc(1, 1, {"op": "install", "support": branches[0]["1"]})
                    self.assertEqual(blocked["status"], "blocked")
                    self.assertTrue(await client.retire(cert))
                    delayed = await net.rpc(0, 1, {"op": "prepare", "origin": 0,
                        "sequence": cert["sequences"]["1"], "manifest": "large",
                        "requires": [], "options": box["1"]})
                    self.assertEqual(delayed["status"], "closed")
                finally:
                    client.disconnect()
                    await net.stop()
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
