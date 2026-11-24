"""Discoverable standard-library smoke tests for the published core API."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from src.checker import frontier_certificate, safe_envelope
from src.envelope import frontier_synthesize, synthesize
from src.network import Client, Network


class CoreSmokeTests(unittest.TestCase):
    def setUp(self):
        self.branches = [
            {"0": ["a.old"], "1": ["b.old"]},
            {"0": ["a.new"], "1": ["b.new"]},
        ]
        self.current = {"0": ["a.old"], "1": ["b.old"]}
        self.candidates = {
            "0": [["a.old"], ["a.new"]],
            "1": [["b.old"], ["b.new"]],
        }

    def test_exact_frontier_is_checkable(self):
        plan = frontier_synthesize(self.branches, self.current, self.candidates)
        self.assertTrue(frontier_certificate(self.branches, self.current, self.candidates, plan))
        self.assertTrue(safe_envelope(self.branches, plan["box"]))

    def test_marginal_cross_product_is_rejected(self):
        box = {"0": [["a.old"], ["a.new"]], "1": [["b.old"], ["b.new"]]}
        self.assertFalse(safe_envelope(self.branches, box))

    def test_greedy_result_is_safe(self):
        plan = synthesize(self.branches, self.current, self.candidates)
        self.assertTrue(plan["certificate"]["safe"])
        self.assertTrue(safe_envelope(self.branches, plan["box"]))

    def test_search_bound_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "search-state bound"):
            frontier_synthesize(self.branches, self.current, self.candidates, max_states=1)

    def test_delayed_prepare_cannot_resurrect(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as tmp:
                net = Network(Path(tmp), [["a.old"], ["b.old"]], policy="predicate", seed=7)
                await net.start()
                client = Client(net)
                result = await client.acquire("m", self.branches)
                self.assertEqual(result["status"], "admitted")
                cert = result["certificate"]
                self.assertTrue(await client.retire(cert))
                reply = await net.rpc(0, 0, {"op": "prepare", "origin": 0,
                    "sequence": cert["sequences"]["0"], "manifest": "m", "requires": ["a.old"]})
                self.assertEqual(reply["status"], "closed")
                client.disconnect()
                await net.stop()
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
