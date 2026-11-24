"""Pinned declaration extraction and owned durable authorization, not Android execution."""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.android_contracts import SIZE, extract, profile
from src.checker import frontier_certificate
from src.envelope import frontier_synthesize, verify_box
from src.controller import Endpoint
from src.network import Client, Network

DATA = Path(__file__).resolve().parents[1] / "data/android-pinned-class-contracts.json"


def declarations():
    return json.loads(DATA.read_text(encoding="utf-8"))


class AdapterTests(unittest.TestCase):
    def test_boundaries_and_no_later_release_extrapolation(self):
        data = declarations()
        for row in data["contracts"]:
            self.assertNotIn(row["atom"], profile(data, row["since"] - 1))
            self.assertIn(row["atom"], profile(data, row["since"]))
        for level in (True, 8.0, 0, 26, 34):
            with self.assertRaises(ValueError):
                profile(data, level)

    def test_provenance_mutation_and_untrusted_bytes_refuse(self):
        with self.assertRaises(ValueError):
            extract(b"not the pinned history")
        with self.assertRaisesRegex(ValueError, "Git blob mismatch"):
            extract(b"0" * SIZE)
        data = declarations()
        data["contracts"][0]["since"] = True
        with self.assertRaises(ValueError):
            profile(data, 21)

    def test_equal_catalog_masks_do_not_cover_all_runtime_predicates(self):
        branches = [{"0": ["a"]}, {"0": ["b"]}]
        current, candidates = {"0": ["a", "b"]}, {"0": [["a", "b"]]}
        plan = frontier_synthesize(branches, current, candidates)
        self.assertTrue(frontier_certificate(branches, current, candidates, plan))
        self.assertEqual(plan["frontier_size"], 1)
        self.assertEqual(plan["box"], {"0": [["a"]]})
        self.assertTrue(verify_box(branches, {"0": [["b"]]})["safe"])
        endpoint = Endpoint(0, current["0"])
        endpoint.prepare(0, 1, "catalog-scope", [], options=plan["box"]["0"])
        self.assertEqual(endpoint.install(["b"])["status"], "blocked")
        self.assertTrue(Endpoint.satisfies({"requires": ["b"]}, ["b"]))


async def durable_bridge():
    data = declarations()
    levels = (8, 9, 11, 21, 25)
    current = {"0": profile(data, 21), "1": profile(data, 21)}
    candidates = {node: [profile(data, level) for level in levels] for node in current}
    # Explicit caller-declared alternatives. Dates/branch choices are not mined
    # application behavior; the only source-derived values are class presence.
    branches = [{"0": ["api.base64"], "1": ["api.download-manager"]},
                {"0": ["api.fragment"], "1": ["api.base64"]}]
    plan = frontier_synthesize(branches, current, candidates)
    if not frontier_certificate(branches, current, candidates, plan):
        raise ValueError("frontier certificate rejected")
    with tempfile.TemporaryDirectory() as directory:
        net = Network(Path(directory), [current["0"], current["1"]])
        await net.start()
        client = Client(net)
        try:
            answer = await client.acquire_box("android-declarations", branches, plan["box"])
            if answer["status"] != "admitted":
                raise ValueError("declaration admission failed")
            cert = answer["certificate"]
            before = copy.deepcopy(net.nodes[1].state)
            blocked = await net.rpc(0, 1, dict(op="install", support=profile(data, 8)))
            if blocked["status"] != "blocked" or net.nodes[1].state != before:
                raise ValueError("rollback bypassed durable guard")
            await net.crash(1)  # Owned endpoint close/reopen, not an OS kill.
            client.disconnect()
            client = Client(net)
            used = await client.use(cert)
            if any(reply is None or reply["status"] != "used" for reply in used):
                raise ValueError("reopen lost held authorization")
            if not await client.retire(cert):
                raise ValueError("retirement incomplete")
            installed = await net.rpc(0, 1, dict(op="install", support=profile(data, 8)))
            late = await net.rpc(0, 1, dict(op="prepare", origin=0,
                sequence=cert["sequences"]["1"], manifest=cert["manifest"],
                requires=[], options=plan["box"]["1"]))
            if installed["status"] != "installed" or late["status"] != "closed":
                raise ValueError("retirement/floor contract failed")
            return dict(source_blob=data["git_blob"], source_api_range=[1, 25],
                        frontier_size=plan["frontier_size"], product_mass=plan["product_mass"],
                        rollback_while_held=blocked["status"], reopen_use=[r["status"] for r in used],
                        rollback_after_retire=installed["status"], delayed_prepare=late["status"],
                        scope="source-derived declaration profiles; caller-authored alternatives; local SQLite/TCP abstract support, no Android execution or behavioral guarantee")
        finally:
            client.disconnect()
            await net.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-base64", type=Path)
    args = parser.parse_args()
    if args.history_base64:
        encoded = args.history_base64.read_bytes()
        if len(encoded) > 5_000_000:
            raise ValueError("history input size bound")
        actual = extract(base64.b64decode(encoded, validate=True))
        if actual != declarations():
            raise ValueError("retained selected facts differ from authenticated original")
    print(json.dumps(asyncio.run(durable_bridge()), sort_keys=True))
