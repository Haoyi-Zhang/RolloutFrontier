"""Post-development synthetic holdout for relation shape and schedule generalization.

This suite was added after the controller and exact solver were frozen.  It uses
seed range 1000--1239 and relation generators not used by ``tests.campaign``.
It is still generated evidence, not an external or representative workload.
"""
from __future__ import annotations

import csv
import json
import random
import resource
import sys
import time
from itertools import combinations
from pathlib import Path

from src.envelope import frontier_synthesize, synthesize
from src.checker import frontier_certificate, safe_envelope

PROFILES = tuple(range(4))
FAMILIES = ("diagonal", "cycle", "staircase", "planted", "sparse", "capped-random")
SEEDS = tuple(range(1000, 1240))
STEPS = 48


def relation_for(family: str, seed: int) -> set[tuple[int, int]]:
    rng = random.Random((seed << 8) ^ sum(map(ord, family)))
    if family == "diagonal":
        return {(i, i) for i in PROFILES}
    if family == "cycle":
        return {(i, i) for i in PROFILES} | {(i, (i + 1) % 4) for i in PROFILES}
    if family == "staircase":
        return {(0, 0), (0, 1), (1, 1), (1, 2), (2, 2), (2, 3), (3, 3)}
    if family == "planted":
        rows = set(rng.sample(PROFILES, 2))
        cols = set(rng.sample(PROFILES, 2))
        result = {(a, b) for a in rows for b in cols}
        remaining = sorted(set((a, b) for a in PROFILES for b in PROFILES) - result)
        result.update(rng.sample(remaining, 4))
        return result
    count = 5 if family == "sparse" else 8
    return set(rng.sample([(a, b) for a in PROFILES for b in PROFILES], count))


def branches(relation: set[tuple[int, int]]) -> list[dict[str, list[str]]]:
    return [{"0": [f"left.{a}"], "1": [f"right.{b}"]} for a, b in sorted(relation)]


def candidate_profiles() -> dict[str, list[list[str]]]:
    return {
        "0": [[f"left.{a}"] for a in PROFILES],
        "1": [[f"right.{b}"] for b in PROFILES],
    }


def accepted_sets(plan: dict) -> tuple[frozenset[int], frozenset[int]]:
    left = frozenset(int(p[0].split(".")[1]) for p in plan["accepted_profiles"]["0"])
    right = frozenset(int(p[0].split(".")[1]) for p in plan["accepted_profiles"]["1"])
    return left, right


def direct_frontier(relation: set[tuple[int, int]], seed: tuple[int, int]):
    """Enumerate all seeded nonempty rectangles independently of the solver."""
    left_sets = []
    right_sets = []
    for size in range(1, 5):
        left_sets.extend(frozenset(x) for x in combinations(PROFILES, size) if seed[0] in x)
        right_sets.extend(frozenset(x) for x in combinations(PROFILES, size) if seed[1] in x)
    safe = [(a, b) for a in left_sets for b in right_sets
            if all((x, y) in relation for x in a for y in b)]
    frontier = [(a, b) for a, b in safe if not any(
        (c != a or d != b) and c.issuperset(a) and d.issuperset(b)
        for c, d in safe)]
    frontier.sort(key=lambda x: (-len(x[0]) * len(x[1]), len(x[0]) + len(x[1]),
                                 tuple(sorted(x[0])), tuple(sorted(x[1]))))
    return frontier


def replay(schedule: list[tuple[int, int]], relation: set[tuple[int, int]],
           seed: tuple[int, int], allowed: tuple[frozenset[int], frozenset[int]] | None):
    state = list(seed)
    installed = blocked = unchanged = violations = 0
    for node, target in schedule:
        if target == state[node]:
            unchanged += 1
            continue
        trial = list(state)
        trial[node] = target
        permit = ((tuple(trial) in relation) if allowed is None else target in allowed[node])
        if permit:
            state = trial
            installed += 1
        else:
            blocked += 1
        if tuple(state) not in relation:
            violations += 1
    return dict(installed=installed, blocked=blocked, unchanged=unchanged,
                violations=violations, final=list(state))


def one(family: str, seed_value: int) -> dict:
    relation = relation_for(family, seed_value)
    edges = sorted(relation)
    seed = edges[random.Random(seed_value ^ 0x5A17).randrange(len(edges))]
    current = {"0": [f"left.{seed[0]}"], "1": [f"right.{seed[1]}"]}
    candidates = candidate_profiles()
    manifest = branches(relation)

    exact = frontier_synthesize(manifest, current, candidates)
    greedy = synthesize(manifest, current, candidates)
    assert frontier_certificate(manifest, current, candidates, exact)
    assert safe_envelope(manifest, greedy["box"])

    oracle = direct_frontier(relation, seed)
    exact_sets = accepted_sets(exact)
    oracle_vectors = {(a, b) for a, b in oracle}
    assert exact_sets in oracle_vectors
    assert exact["product_mass"] == max(len(a) * len(b) for a, b in oracle)
    exact_front = {
        (frozenset(int(p[0].split(".")[1]) for p in item["accepted_profiles"]["0"]),
         frozenset(int(p[0].split(".")[1]) for p in item["accepted_profiles"]["1"]))
        for item in exact["frontier"]
    }
    assert exact_front == oracle_vectors

    greedy_sets = accepted_sets({
        "accepted_profiles": {
            n: [[f"{('left' if n == '0' else 'right')}.{v}"] for v in PROFILES
                if any(set(option).issubset({f"{('left' if n == '0' else 'right')}.{v}"})
                       for option in greedy["box"][n])]
            for n in ("0", "1")
        }
    })
    fixed = (frozenset({seed[0]}), frozenset({seed[1]}))

    rng = random.Random(seed_value * 7919 + len(family))
    schedule = [(step % 2, rng.randrange(4)) for step in range(STEPS)]
    outcomes = {
        "fixed": replay(schedule, relation, seed, fixed),
        "greedy": replay(schedule, relation, seed, greedy_sets),
        "exact": replay(schedule, relation, seed, exact_sets),
        "central": replay(schedule, relation, seed, None),
    }
    assert all(outcomes[name]["violations"] == 0 for name in outcomes)
    return dict(
        family=family, seed=seed_value, edges=len(relation), start_left=seed[0], start_right=seed[1],
        oracle_frontier=len(oracle), exact_frontier=exact["frontier_size"],
        exact_product_mass=exact["product_mass"], greedy_product_mass=len(greedy_sets[0]) * len(greedy_sets[1]),
        exact_states=exact["search"]["states"], exact_terms=exact["guard_terms"],
        fixed_installed=outcomes["fixed"]["installed"],
        greedy_installed=outcomes["greedy"]["installed"],
        exact_installed=outcomes["exact"]["installed"],
        central_installed=outcomes["central"]["installed"],
        fixed_blocked=outcomes["fixed"]["blocked"],
        greedy_blocked=outcomes["greedy"]["blocked"],
        exact_blocked=outcomes["exact"]["blocked"],
        central_blocked=outcomes["central"]["blocked"],
        exact_central_gap=outcomes["central"]["installed"] - outcomes["exact"]["installed"],
        exact_minus_greedy=outcomes["exact"]["installed"] - outcomes["greedy"]["installed"],
    )


def run(out: Path) -> dict:
    begin = time.perf_counter()
    cpu = time.process_time()
    rows = [one(family, seed) for family in FAMILIES for seed in SEEDS]
    out.mkdir(parents=True, exist_ok=True)
    with (out / "generalization.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    by_family = {}
    for family in FAMILIES:
        subset = [r for r in rows if r["family"] == family]
        by_family[family] = {
            "cases": len(subset),
            "exact_product_mass": sum(r["exact_product_mass"] for r in subset),
            "greedy_product_mass": sum(r["greedy_product_mass"] for r in subset),
            "exact_installed": sum(r["exact_installed"] for r in subset),
            "greedy_installed": sum(r["greedy_installed"] for r in subset),
            "fixed_installed": sum(r["fixed_installed"] for r in subset),
            "central_installed": sum(r["central_installed"] for r in subset),
            "exact_better_schedule_cases": sum(r["exact_minus_greedy"] > 0 for r in subset),
            "greedy_better_schedule_cases": sum(r["exact_minus_greedy"] < 0 for r in subset),
            "equal_schedule_cases": sum(r["exact_minus_greedy"] == 0 for r in subset),
        }
    answer = {
        "scope": "post-development generated holdout; not an external or representative workload",
        "freeze": "core solver/checker unchanged after first holdout execution",
        "seed_range": [min(SEEDS), max(SEEDS)],
        "families": list(FAMILIES),
        "cases": len(rows),
        "proposals": len(rows) * STEPS,
        "oracle_frontier_mismatches": 0,
        "safety_violations": 0,
        "exact_product_mass": sum(r["exact_product_mass"] for r in rows),
        "greedy_product_mass": sum(r["greedy_product_mass"] for r in rows),
        "exact_installed": sum(r["exact_installed"] for r in rows),
        "greedy_installed": sum(r["greedy_installed"] for r in rows),
        "fixed_installed": sum(r["fixed_installed"] for r in rows),
        "central_installed": sum(r["central_installed"] for r in rows),
        "exact_better_schedule_cases": sum(r["exact_minus_greedy"] > 0 for r in rows),
        "greedy_better_schedule_cases": sum(r["exact_minus_greedy"] < 0 for r in rows),
        "equal_schedule_cases": sum(r["exact_minus_greedy"] == 0 for r in rows),
        "positive_central_gap_cases": sum(r["exact_central_gap"] > 0 for r in rows),
        "max_central_gap": max(r["exact_central_gap"] for r in rows),
        "by_family": by_family,
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - begin,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    return answer


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m tests.generalization OUTPUT_DIR")
    result = run(Path(sys.argv[1]))
    (Path(sys.argv[1]) / "generalization.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
