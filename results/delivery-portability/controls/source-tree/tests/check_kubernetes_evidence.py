"""Data-only arithmetic and event validation of the Kubernetes policy fixture."""
from pathlib import Path
import argparse
import hashlib
import itertools
import json

ROOT = Path(__file__).resolve().parents[1]


def require(value, message):
    if not value:
        raise ValueError(message)


def allowed(role, a, b, c):
    if abs(a - b) > 1:
        return False
    if role == "kubelet":
        return c >= 25 and max(a, b) - 3 <= c <= min(a, b)
    if role == "controller":
        return max(a, b) - 1 <= c <= min(a, b)
    if role == "kubectl":
        return max(a, b) - 1 <= c <= min(a, b) + 1
    raise ValueError("unknown policy role")


def profile(role, node, version, clients):
    if node == 2:
        return {f"client.{version}"}
    return {f"allows.{c}" for c in clients if allowed(role, version, version, c)}


def accepts(box, role, node, version, clients):
    atoms = profile(role, node, version, clients)
    return any(set(term) <= atoms for term in box[str(node)])


def subsets(catalog, seed):
    return [tuple(v for bit, v in enumerate(catalog) if mask & (1 << bit))
            for mask in range(1, 1 << len(catalog))
            if mask & (1 << catalog.index(seed))]


def check(path=ROOT / "results/kubernetes-skew/results.json"):
    d = json.loads(Path(path).read_text())
    facts = json.loads((ROOT / "data/kubernetes-version-skew.json").read_text())
    require(d["source"] == facts, "policy source facts differ")
    for name, digest in d["source_sha256"].items():
        file = (ROOT / name).resolve()
        require(file.is_relative_to(ROOT.resolve()) and file.is_file(), "invalid policy source path")
        require(hashlib.sha256(file.read_bytes()).hexdigest() == digest, "policy source differs: " + name)
    require(len(d["exhaustive"]) == len(d["lifecycles"]) == len(facts["cases"]) == 3,
            "policy cohort count")
    totals = dict(vectors=0, compatible_vectors=0, frontier_members_across_seeds=0, lifecycle_proposals=0)
    for case, saved, run in zip(facts["cases"], d["exhaustive"], d["lifecycles"]):
        role, clients = case["role"], case["client_minor_catalog"]
        require(saved["role"] == run["role"] == role, "role identity differs")
        domains = [facts["server_minor_catalog"], facts["server_minor_catalog"], clients]
        vectors = list(itertools.product(*domains))
        require([tuple(r["versions"]) for r in saved["rows"]] == vectors, "missing/reordered policy vector")
        safe_count = members = 0
        for vector, row in zip(vectors, saved["rows"]):
            safe = allowed(role, *vector)
            require(type(row["compatible"]) is bool and row["compatible"] == safe, "incorrect policy cell")
            if not safe:
                continue
            safe_count += 1
            boxes = [b for b in itertools.product(*(subsets(dom, seed) for dom, seed in zip(domains, vector)))
                     if all(allowed(role, *v) for v in itertools.product(*b))]
            frontier = sorted(b for b in boxes if not any(
                b != other and all(set(x) <= set(y) for x, y in zip(b, other)) for other in boxes))
            require(row["frontier"] == [list(map(list, b)) for b in frontier], "incorrect literal policy frontier")
            accepted = tuple(tuple(v for v in dom if accepts(row["selected"], role, i, v, clients))
                             for i, dom in enumerate(domains))
            require(accepted in frontier, "selected guard does not have a frontier vector")
            mass = 1
            for vs in accepted:
                mass *= len(vs)
            require(type(row["product_mass"]) is int and row["product_mass"] == mass
                    and mass == max(len(b[0]) * len(b[1]) * len(b[2]) for b in frontier),
                    "selected policy mass differs")
            members += len(frontier)
        require(saved["vectors"] == len(vectors) and saved["compatible_vectors"] == safe_count
                and saved["frontier_members_across_seeds"] == members, "policy row totals differ")
        totals["vectors"] += len(vectors)
        totals["compatible_vectors"] += safe_count
        totals["frontier_members_across_seeds"] += members
        require(run["current"] == case["current"], "lifecycle starting vector differs")
        state = list(run["current"])
        proposals = [(i, v) for i, domain in enumerate(domains) for v in domain]
        require(len(run["trace"]) == len(proposals), "lifecycle proposal denominator differs")
        seed_row = next(row for row in saved["rows"] if row["versions"] == run["current"])
        require(run["box"] == seed_row["selected"] and run["product_mass"] == seed_row["product_mass"],
                "lifecycle guard does not match initial plan")
        require(run["frontier_size"] == len(seed_row["frontier"]), "initial frontier count differs")
        for (owner, value), event in zip(proposals, run["trace"]):
            require(event["owner"] == owner and event["proposed_minor"] == value, "lifecycle proposal differs")
            old = profile(role, owner, state[owner], clients)
            target = profile(role, owner, value, clients)
            status = "unchanged" if old == target else "installed" if accepts(run["box"], role, owner, value, clients) else "blocked"
            require(event["status"] == status, "lifecycle event status differs")
            if status != "blocked":
                state[owner] = value
            require(event["versions_after"] == state and event["policy_safe"] is True
                    and allowed(role, *state), "unsafe/inconsistent policy event")
        require(run["owner_and_origin_reopen"] == "authorized" and run["retirement"] == "closed"
                and run["delayed_prepare"] == "closed", "policy recovery outcome differs")
        totals["lifecycle_proposals"] += len(proposals)
    require(d["totals"] == totals, "cached policy totals differ from raw rows")
    return {"status": "PASS", **totals}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "results/kubernetes-skew/results.json")
    print(json.dumps(check(parser.parse_args().data), sort_keys=True))
