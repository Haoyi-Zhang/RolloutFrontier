"""Official-policy compatibility slices, direct arithmetic oracle and durable replay.

Run from artifact/: python -B -m tests.kubernetes_skew_study --out /new/path
No Kubernetes process or installation is invoked. Every retained policy vector,
guard corner and RPC outcome is checked against a separate arithmetic predicate.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
from pathlib import Path
import platform
import tempfile

from src.checker import frontier_certificate
from src.envelope import frontier_synthesize, compatible
from src.network import Client, Network

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data/kubernetes-version-skew.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def policy(role, versions):
    """Direct integer policy; never inspects atoms, manifests or certificates."""
    a, b, c = versions
    if abs(a - b) > 1:
        return False
    if role == "kubelet":
        return c >= 25 and all(0 <= server - c <= 3 for server in (a, b))
    if role == "controller":
        return all(0 <= server - c <= 1 for server in (a, b))
    if role == "kubectl":
        return all(abs(server - c) <= 1 for server in (a, b))
    raise ValueError("unknown component role")


def inputs(case):
    # The fixed server catalog satisfies the HA skew bound. The listed allowed
    # client sets encode the independently transcribed role-specific policy.
    role = case["role"]
    servers = (36, 37)
    client_versions = case["client_minor_catalog"]
    if role == "kubelet":
        allowed = {36: (33, 34, 35, 36), 37: (34, 35, 36, 37)}
    elif role == "controller":
        allowed = {36: (35, 36), 37: (36, 37)}
    elif role == "kubectl":
        allowed = {36: (35, 36, 37), 37: (36, 37, 38)}
    else:
        raise ValueError("unknown role")
    profiles = {
        "0": {v: sorted(f"allows.{c}" for c in allowed[v] if c in client_versions) for v in servers},
        "1": {v: sorted(f"allows.{c}" for c in allowed[v] if c in client_versions) for v in servers},
        "2": {c: [f"client.{c}"] for c in client_versions},
    }
    branches = [{"0": [f"allows.{c}"], "1": [f"allows.{c}"], "2": [f"client.{c}"]}
                for c in client_versions]
    candidates = {n: list(profiles[n].values()) for n in profiles}
    current = {str(i): profiles[str(i)][v] for i, v in enumerate(case["current"])}
    return profiles, branches, candidates, current


def direct_frontier(catalogs, seed, role):
    """Exhaustive subsets of version values; no producer representation reused."""
    choices = []
    for catalog, anchor in zip(catalogs, seed):
        choices.append([tuple(v for i, v in enumerate(catalog) if mask & (1 << i))
                        for mask in range(1, 1 << len(catalog))
                        if any(v == anchor and mask & (1 << i) for i, v in enumerate(catalog))])
    safe = [rectangle for rectangle in itertools.product(*choices)
            if all(policy(role, vector) for vector in itertools.product(*rectangle))]
    return sorted(rect for rect in safe if not any(
        all(set(a) <= set(b) for a, b in zip(rect, other)) and rect != other for other in safe))


def accepted_versions(plan, profiles):
    result = []
    for member in plan["frontier"]:
        box = member["box"]
        result.append(tuple(tuple(v for v, atoms in profiles[n].items()
                                  if any(set(term) <= set(atoms) for term in box[n]))
                            for n in ("0", "1", "2")))
    return sorted(result)


def exhaustive(case):
    profiles, branches, candidates, _ = inputs(case)
    catalogs = [tuple(profiles[n]) for n in ("0", "1", "2")]
    rows = []
    frontier_members = 0
    for versions in itertools.product(*catalogs):
        current = {str(i): profiles[str(i)][v] for i, v in enumerate(versions)}
        observed = compatible(branches, {n: set(a) for n, a in current.items()})
        expected = policy(case["role"], versions)
        require(observed == expected, "manifest does not encode official numerical policy")
        row = {"versions": list(versions), "compatible": expected}
        if expected:
            plan = frontier_synthesize(branches, current, candidates)
            require(frontier_certificate(branches, current, candidates, plan), "certificate rejected")
            actual = accepted_versions(plan, profiles)
            direct = direct_frontier(catalogs, versions, case["role"])
            require(actual == direct, "policy frontier differs from literal version-subset oracle")
            frontier_members += len(direct)
            row.update(frontier=[list(map(list, rect)) for rect in direct],
                       selected=plan["box"], product_mass=plan["product_mass"])
        rows.append(row)
    return {"role": case["role"], "vectors": len(rows),
            "compatible_vectors": sum(row["compatible"] for row in rows),
            "frontier_members_across_seeds": frontier_members, "rows": rows}


async def lifecycle(case, root):
    profiles, branches, candidates, current = inputs(case)
    plan = frontier_synthesize(branches, current, candidates)
    require(frontier_certificate(branches, current, candidates, plan), "checker rejected plan")
    root.mkdir()
    net = Network(root, [current[str(i)] for i in range(3)])
    await net.start()
    client = Client(net)
    trace = []
    versions = list(case["current"])
    try:
        admission = await client.acquire_box("kubernetes-" + case["role"], branches, plan["box"])
        require(admission["status"] == "admitted", "initial acquisition failed")
        cert = admission["certificate"]
        for owner, values in enumerate((profiles["0"], profiles["1"], profiles["2"])):
            for value in values:
                proposed = profiles[str(owner)][value]
                allowed = any(set(term) <= set(proposed) for term in plan["box"][str(owner)])
                expected = "unchanged" if value == versions[owner] else "installed" if allowed else "blocked"
                # Actual endpoint's support can alias two versions after projection.
                same_support = net.nodes[owner].state["support"] == proposed
                if same_support:
                    expected = "unchanged"
                reply = await net.rpc(0, owner, {"op": "install", "support": proposed})
                require(reply is not None and reply["status"] == expected,
                        f"policy installation mismatch: {case['role']}, {owner}, {value}, {expected}, {reply}")
                if reply["status"] in ("installed", "unchanged"):
                    versions[owner] = value
                require(policy(case["role"], versions), "guard allowed incompatible official-policy vector")
                trace.append({"owner": owner, "proposed_minor": value, "status": reply["status"],
                              "versions_after": list(versions), "policy_safe": True})
        await net.crash(1)
        client.disconnect()
        client = Client(net)
        use = await client.use(cert)
        require(all(r is not None and r["status"] == "used" for r in use), "reopen lost authorization")
        require(await client.retire(cert), "retirement did not finish")
        late = await net.rpc(0, 1, {"op": "prepare", "origin": 0,
            "sequence": cert["sequences"]["1"], "manifest": cert["manifest"],
            "requires": [], "options": plan["box"]["1"]})
        require(late is not None and late["status"] == "closed", "delayed prepare resurrected")
        return {"role": case["role"], "current": case["current"], "box": plan["box"],
                "product_mass": plan["product_mass"], "frontier_size": plan["frontier_size"],
                "trace": trace, "owner_and_origin_reopen": "authorized", "retirement": "closed",
                "delayed_prepare": late["status"]}
    finally:
        client.disconnect()
        await net.stop()


async def main(out):
    require(not out.exists() or not any(out.iterdir()), "output must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    facts = json.loads(FACTS.read_text())
    require(facts["server_minor_catalog"] == [36, 37], "unexpected policy catalog")
    identities = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [FACTS, Path(__file__), *sorted((ROOT / "src").glob("*.py"))]}
    with tempfile.TemporaryDirectory() as temp:
        rows = [exhaustive(case) for case in facts["cases"]]
        runs = [await lifecycle(case, Path(temp) / case["role"]) for case in facts["cases"]]
    result = {"design": "all 36 policy-catalog vectors and every compatible seed; three owned TCP/SQLite lifecycles",
              "source": facts, "environment": {"python": platform.python_version(), "platform": platform.platform()},
              "source_sha256": identities, "exhaustive": rows, "lifecycles": runs,
              "totals": {"vectors": sum(r["vectors"] for r in rows),
                         "compatible_vectors": sum(r["compatible_vectors"] for r in rows),
                         "frontier_members_across_seeds": sum(r["frontier_members_across_seeds"] for r in rows),
                         "lifecycle_proposals": sum(len(r["trace"]) for r in runs)},
              "scope": "Documented three-component version constraints executed as abstract support declarations, not Kubernetes binaries, cluster benchmarks or incident prevalence."}
    require(all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
                for name, digest in identities.items()), "source changed during study")
    (out / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["totals"], sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    asyncio.run(main(parser.parse_args().out.resolve()))
