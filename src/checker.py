"""Independent checker: imports no controller, planner, or workload generator."""
from __future__ import annotations
from itertools import combinations
from typing import Any


def certificate(c: dict[str, Any], branches: list[dict[str, list[str]]]) -> bool:
    """Check structural evidence, NOT signatures, current liveness, or physical APIs.

    Receipt authenticity and ongoing holds are assumptions; online use checks
    live state. This checker deliberately does not equate a saved receipt with
    current execution authority after explicit retirement.
    """
    if not isinstance(c, dict):
        return False
    if c.get("mode") == "envelope":
        return envelope_certificate(c, branches)
    try:
        if set(c) != {"manifest", "origin", "branch", "sequences", "receipts"}:
            return False
        if not valid_manifest(branches) or type(c["origin"]) is not int or not 0 <= c["origin"] < 6:
            return False
        if not isinstance(c["manifest"], str) or not 1 <= len(c["manifest"]) <= 256:
            return False
        if type(c["branch"]) is not int or not 0 <= c["branch"] < len(branches):
            return False
        branch = branches[c["branch"]]
        expected = {int(n): sorted(set(req)) for n, req in branch.items()}
        if not isinstance(c["sequences"], dict) or set(c["sequences"]) != set(branch):
            return False
        for n, sequence in c["sequences"].items():
            if (not isinstance(n, str) or n != str(int(n)) or
                    type(sequence) is not int or not 1 <= sequence < 2**63):
                return False
        if not isinstance(c["receipts"], list) or len(c["receipts"]) != len(expected):
            return False
        received = {}
        for r in c["receipts"]:
            if (not isinstance(r, dict) or
                    set(r) != {"status", "node", "origin", "sequence", "manifest",
                               "requires", "observed_generation"}):
                return False
            n = r["node"]
            if type(n) is not int:
                return False
            if n in received or r["status"] != "held" or r["manifest"] != c["manifest"]:
                return False
            if type(r["sequence"]) is not int or not 1 <= r["sequence"] < 2**63:
                return False
            if type(r["origin"]) is not int or r["origin"] != c["origin"]:
                return False
            if (type(c["sequences"][str(n)]) is not int or
                    r["sequence"] != c["sequences"][str(n)]):
                return False
            if r["requires"] != expected.get(n) or "options" in r:
                return False
            if (type(r.get("observed_generation")) is not int or
                    not 0 <= r["observed_generation"] < 2**63):
                return False
            received[n] = r
        return set(received) == set(expected)
    except (KeyError, TypeError, ValueError):
        return False


def obstruction(branches: list[set[tuple[int, str]]], available: set[tuple[int, str]],
                witness: list[tuple[int, str]], exact_small: bool = False) -> bool:
    if not branches or len(witness) != len(set(witness)):
        return False
    relevant = set().union(*branches)
    W = set(witness)
    if not W or not W.issubset(relevant - available):
        return False
    if not all(any(x in b for x in W) for b in branches):
        return False
    if any(all(any(x in b for x in W - {removed}) for b in branches) for removed in W):
        return False
    if exact_small:
        candidates = sorted(relevant - available)
        if len(candidates) > 18:
            raise ValueError("independent exact checker bound: 18 false atoms")
        for k in range(len(W)):
            for choice in combinations(candidates, k):
                if all(any(x in b for x in choice) for b in branches):
                    return False
    return True


def endpoint_invariant(state: dict[str, Any]) -> bool:
    try:
        active = [h for h in state["slots"].values() if h["status"] == "held"]
        if any(not any(all(a in state["support"] for a in option)
                       for option in h.get("options", [h["requires"]])) for h in active):
            return False
        for key in state["slots"]:
            origin, sequence = map(int, key.split(":"))
            if not state["floor"][origin] < sequence <= state["floor"][origin] + state["window"]:
                return False
        return len(state["slots"]) <= len(state["floor"]) * state["window"]
    except (KeyError, TypeError, ValueError):
        return False


def safe_envelope(branches: list[dict[str, list[str]]], box: dict[str, list[list[str]]]) -> bool:
    """Independent recursive corner search, not the producer's product routine."""
    try:
        if not valid_manifest(branches) or not 1 <= len(box) <= 6:
            return False
        nodes = sorted(box)
        if any(sorted(b) != nodes for b in branches):
            return False
        bound = 1
        for node in nodes:
            if node != str(int(node)) or not 0 <= int(node) < 6:
                return False
            if not isinstance(box[node], list) or not 1 <= len(box[node]) <= 8:
                return False
            bound *= len(box[node])
            for option in box[node]:
                if not isinstance(option, list) or len(option) > 96:
                    return False
                if any(not isinstance(a, str) or not a or len(a) > 512 for a in option):
                    return False
        if bound > 4096:
            return False
        # Each depth filters the still-possible global branches. A corner is
        # safe iff at least one branch survives all endpoint assignments.
        def visit(depth: int, possible: list[int]) -> bool:
            if depth == len(nodes):
                return bool(possible)
            n = nodes[depth]
            for local in box[n]:
                remaining = [i for i in possible if all(a in local for a in branches[i][n])]
                if not remaining or not visit(depth + 1, remaining):
                    return False
            return True
        return visit(0, list(range(len(branches))))
    except (TypeError, ValueError, KeyError):
        return False


def envelope_certificate(c: dict[str, Any], branches: list[dict[str, list[str]]]) -> bool:
    try:
        if set(c) != {"mode", "manifest", "origin", "box", "sequences", "receipts"}:
            return False
        if c["mode"] != "envelope":
            return False
        box = c["box"]
        if not isinstance(box, dict):
            return False
        for options in box.values():
            if not isinstance(options, list) or not 1 <= len(options) <= 8:
                return False
            normalized = sorted({tuple(sorted(set(option))) for option in options
                                 if isinstance(option, list)})
            if (len(normalized) != len(options) or
                    options != [list(option) for option in normalized] or
                    any(set(other) < set(option) for option in normalized for other in normalized)):
                return False
        if type(c["origin"]) is not int or not 0 <= c["origin"] < 6:
            return False
        if not isinstance(c["manifest"], str) or not 1 <= len(c["manifest"]) <= 256:
            return False
        if (not isinstance(c["sequences"], dict) or
                not safe_envelope(branches, box) or sorted(c["sequences"]) != sorted(box)):
            return False
        for n, sequence in c["sequences"].items():
            if (not isinstance(n, str) or n != str(int(n)) or
                    type(sequence) is not int or not 1 <= sequence < 2**63):
                return False
        if not isinstance(c["receipts"], list) or len(c["receipts"]) != len(box):
            return False
        received = set()
        for r in c["receipts"]:
            if (not isinstance(r, dict) or
                    set(r) != {"status", "node", "origin", "sequence", "manifest",
                               "requires", "options", "observed_generation"}):
                return False
            n = str(r["node"])
            if n in received or n not in box or type(r["node"]) is not int:
                return False
            if r["status"] != "held" or r["manifest"] != c["manifest"] or r["requires"] != []:
                return False
            if type(r["origin"]) is not int or r["origin"] != c["origin"]:
                return False
            if type(r["sequence"]) is not int or not 1 <= r["sequence"] < 2**63:
                return False
            if (type(c["sequences"][n]) is not int or
                    r["sequence"] != c["sequences"][n] or r["options"] != box[n]):
                return False
            if (type(r.get("observed_generation")) is not int or
                    not 0 <= r["observed_generation"] < 2**63):
                return False
            received.add(n)
        return received == set(box)
    except (TypeError, ValueError, KeyError):
        return False


def valid_manifest(branches: list[dict[str, list[str]]]) -> bool:
    try:
        if not isinstance(branches, list) or not 1 <= len(branches) <= 8:
            return False
        for b in branches:
            if not isinstance(b, dict) or not 1 <= len(b) <= 6:
                return False
            for n, req in b.items():
                if not isinstance(n, str) or n != str(int(n)) or not 0 <= int(n) < 6:
                    return False
                if not isinstance(req, list) or len(req) > 96:
                    return False
                if any(not isinstance(a, str) or not 1 <= len(a) <= 512 for a in req):
                    return False
        return True
    except (ValueError, TypeError):
        return False


def frontier_certificate(branches: list[dict[str, list[str]]], current: dict[str, list[str]],
                         candidates: dict[str, list[list[str]]], plan: dict[str, Any],
                         weights: dict[str, list[int]] | None = None,
                         combination_bound: int = 250_000) -> bool:
    """Independently re-enumerate and fully validate a bounded frontier result.

    ``combination_bound`` is a visited-prefix state bound, not the raw Cartesian
    product of local choices. Unsafe prefixes and boxes above the declared
    4,096-corner language bound are rejected before descent. This matches the
    producer's admissible language while retaining a separately implemented
    enumeration and metadata reconstruction.
    """
    from itertools import product as cartesian
    try:
        if (not valid_manifest(branches) or not isinstance(plan, dict) or
                plan.get("exact") is not True or type(combination_bound) is not int or
                not 1 <= combination_bound <= 250_000):
            return False
        nodes = sorted(branches[0])
        if any(sorted(b) != nodes for b in branches):
            return False
        if sorted(current) != nodes or sorted(candidates) != nodes:
            return False
        if weights is not None and sorted(weights) != nodes:
            return False
        relevant = {n: set().union(*(set(b[n]) for b in branches)) for n in nodes}

        def clean(values, cap):
            if not isinstance(values, list) or len(values) > cap:
                raise ValueError
            if any(not isinstance(x, str) or not x or len(x) > 512 for x in values):
                raise ValueError
            return tuple(sorted(set(values)))

        def minimal(values):
            vals = sorted(set(values))
            return tuple(x for x in vals if not any(set(y) < set(x) for y in vals))

        local: dict[str, list[dict[str, Any]]] = {}
        domains: dict[str, list[tuple[str, ...]]] = {}
        for n in nodes:
            cur = tuple(x for x in clean(current[n], 12000) if x in relevant[n])
            if not isinstance(candidates[n], list) or len(candidates[n]) > 8:
                return False
            raw = [tuple(x for x in clean(p, 12000) if x in relevant[n])
                   for p in candidates[n]]
            if weights is None:
                ws = [1] * len(raw)
            else:
                ws = weights[n]
                if not isinstance(ws, list) or len(ws) != len(raw):
                    return False
                if any(type(w) is not int or not 0 <= w <= 10**9 for w in ws):
                    return False
            profile_weights: dict[tuple[str, ...], int] = {}
            for profile, weight in zip(raw, ws):
                profile_weights[profile] = profile_weights.get(profile, 0) + weight
            profile_weights.setdefault(cur, 0)
            profiles = sorted(profile_weights)
            domains[n] = profiles
            library = sorted(set([cur, *raw, *(clean(b[n], 96) for b in branches)]))
            if len(library) > 10:
                return False
            choices: dict[tuple[tuple[str, ...], ...], dict[str, Any]] = {}
            for bits in range(1, 1 << len(library)):
                guard = minimal([library[i] for i in range(len(library)) if bits & (1 << i)])
                if not 1 <= len(guard) <= 8 or not any(set(g).issubset(cur) for g in guard):
                    continue
                accepted = tuple(p for p in profiles
                                 if any(set(g).issubset(p) for g in guard))
                mass = sum(profile_weights[p] for p in accepted)
                mask = sum(1 << i for i, p in enumerate(profiles) if p in accepted)
                choices[guard] = dict(guard=guard, accepted=accepted,
                                      mass=mass, mask=mask)
            local[n] = list(choices.values())
            if not local[n]:
                return False

        branch_sets = [{n: set(clean(b[n], 96)) for n in nodes} for b in branches]
        order = sorted(nodes, key=lambda n: (len(local[n]), n))
        counters = dict(states=0, complete=0, safe_complete=0,
                        unsafe_pruned=0, corner_pruned=0)
        safe: list[dict[str, Any]] = []

        def prefix_safe(assigned):
            for local_values in cartesian(*(guard for _, guard in assigned)):
                if not any(all(branch[node].issubset(set(value))
                               for (node, _), value in zip(assigned, local_values))
                           for branch in branch_sets):
                    return False
            return True

        def visit(depth, selected, assigned, corner_count):
            counters["states"] += 1
            if counters["states"] > combination_bound:
                raise OverflowError("checker state bound")
            if depth == len(order):
                counters["complete"] += 1
                counters["safe_complete"] += 1
                masks = tuple(selected[n]["mask"] for n in nodes)
                masses = tuple(selected[n]["mass"] for n in nodes)
                key = tuple((n, selected[n]["guard"]) for n in nodes)
                terms = sum(len(selected[n]["guard"]) for n in nodes)
                safe.append(dict(masks=masks, masses=masses, key=key,
                                 terms=terms, selected=dict(selected),
                                 score=(prod_int(masses), sum(masses), -terms)))
                return
            n = order[depth]
            for choice in local[n]:
                next_corners = corner_count * len(choice["guard"])
                if next_corners > 4096:
                    counters["corner_pruned"] += 1
                    continue
                next_assigned = assigned + [(n, choice["guard"])]
                if not prefix_safe(next_assigned):
                    counters["unsafe_pruned"] += 1
                    continue
                selected[n] = choice
                visit(depth + 1, selected, next_assigned, next_corners)
                del selected[n]

        visit(0, {}, [], 1)
        if not safe:
            return False

        def dominates(left, right):
            return all((a | b) == a for a, b in zip(left, right))

        # Equal candidate-acceptance vectors retain the least-metadata lexical guard.
        by_masks: dict[tuple[int, ...], dict[str, Any]] = {}
        for record in safe:
            old = by_masks.get(record["masks"])
            if old is None or (record["terms"], record["key"]) < (old["terms"], old["key"]):
                by_masks[record["masks"]] = record
        nondominated = [record for masks, record in by_masks.items()
                        if not any(other_masks != masks and dominates(other_masks, masks)
                                   for other_masks in by_masks)]
        if not nondominated:
            return False

        def external(record):
            selected = record["selected"]
            box = {n: [list(x) for x in selected[n]["guard"]] for n in nodes}
            return dict(
                box=box,
                product_mass=record["score"][0],
                local_masses={n: selected[n]["mass"] for n in nodes},
                accepted_unique_profiles={n: len(selected[n]["accepted"]) for n in nodes},
                accepted_profiles={n: [list(x) for x in selected[n]["accepted"]] for n in nodes},
                guard_terms=sum(len(box[n]) for n in nodes),
            )

        expected_frontier = sorted(
            (external(x) for x in nondominated),
            key=lambda x: (-x["product_mass"], x["guard_terms"],
                           tuple((n, tuple(tuple(v) for v in x["box"][n])) for n in nodes)))
        best_score = max(record["score"] for record in nondominated)
        best = min((record for record in nondominated if record["score"] == best_score),
                   key=lambda record: record["key"])
        expected_best = external(best)
        expected_domains = {n: [list(x) for x in domains[n]] for n in nodes}
        expected_objective = dict(
            domain="nondominated frontier members",
            primary="candidate-profile product mass",
            secondary="sum of local masses",
            tertiary="fewer guard terms",
            final="lexicographic box",
            weights="uniform per supplied candidate" if weights is None else "supplied integers",
        )
        expected_certificate = dict(
            safe=True,
            corners=prod_int(len(expected_best["box"][n]) for n in nodes),
        )
        expected_plan_fields = {
            "box", "product_mass", "local_masses", "accepted_unique_profiles",
            "accepted_profiles", "guard_terms", "frontier", "frontier_size",
            "search", "objective", "candidate_domains", "certificate", "exact", "scope",
        }
        if set(plan) != expected_plan_fields:
            return False
        for field, value in expected_best.items():
            if plan.get(field) != value:
                return False
        if plan.get("frontier") != expected_frontier:
            return False
        if plan.get("frontier_size") != len(expected_frontier):
            return False
        if plan.get("candidate_domains") != expected_domains:
            return False
        if plan.get("search") != counters:
            return False
        if plan.get("objective") != expected_objective:
            return False
        if plan.get("certificate") != expected_certificate:
            return False
        if plan.get("scope") != "bounded positive guard library; supplied finite candidate profiles":
            return False
        return safe_envelope(branches, expected_best["box"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

def prod_int(values) -> int:
    answer = 1
    for value in values:
        answer *= value
    return answer
