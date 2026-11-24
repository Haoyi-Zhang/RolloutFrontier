"""Bounded synthesis scaling and explicit failure-closed boundary checks."""
from __future__ import annotations

import csv
import json
import random
import resource
import sys
import time
from pathlib import Path

from src.envelope import frontier_synthesize
from src.checker import frontier_certificate


def relation_edges(profiles: int, edge_count: int, seed: int):
    rng = random.Random(seed)
    universe = [(a, b) for a in range(profiles) for b in range(profiles)]
    return sorted(rng.sample(universe, min(edge_count, len(universe))))


def run_case(profiles: int, edge_count: int, seed: int) -> dict:
    edges = relation_edges(profiles, edge_count, seed)
    current_pair = edges[seed % len(edges)]
    branches = [{"0": [f"a.{a}"], "1": [f"b.{b}"]} for a, b in edges]
    current = {"0": [f"a.{current_pair[0]}"], "1": [f"b.{current_pair[1]}"]}
    candidates = {
        "0": [[f"a.{a}"] for a in range(profiles)],
        "1": [[f"b.{b}"] for b in range(profiles)],
    }
    start = time.perf_counter_ns()
    plan = frontier_synthesize(branches, current, candidates)
    elapsed = time.perf_counter_ns() - start
    assert frontier_certificate(branches, current, candidates, plan)
    return {
        "dimension": 2,
        "profiles_per_owner": profiles,
        "edges": len(edges),
        "seed": seed,
        "search_states": plan["search"]["states"],
        "safe_complete": plan["search"]["safe_complete"],
        "unsafe_pruned": plan["search"]["unsafe_pruned"],
        "frontier_size": plan["frontier_size"],
        "product_mass": plan["product_mass"],
        "guard_terms": plan["guard_terms"],
        "solver_wall_ns": elapsed,
    }


def ternary_case(seed: int) -> dict:
    rng = random.Random(seed)
    tuples = sorted(rng.sample([(a, b, c) for a in range(3) for b in range(3) for c in range(3)], 8))
    cur = tuples[seed % len(tuples)]
    branches = [{"0": [f"a.{a}"], "1": [f"b.{b}"], "2": [f"c.{c}"]} for a, b, c in tuples]
    current = {"0": [f"a.{cur[0]}"], "1": [f"b.{cur[1]}"], "2": [f"c.{cur[2]}"]}
    candidates = {"0": [[f"a.{x}"] for x in range(3)],
                  "1": [[f"b.{x}"] for x in range(3)],
                  "2": [[f"c.{x}"] for x in range(3)]}
    start = time.perf_counter_ns()
    plan = frontier_synthesize(branches, current, candidates)
    elapsed = time.perf_counter_ns() - start
    assert frontier_certificate(branches, current, candidates, plan)
    return {
        "dimension": 3,
        "profiles_per_owner": 3,
        "edges": 8,
        "seed": seed,
        "search_states": plan["search"]["states"],
        "safe_complete": plan["search"]["safe_complete"],
        "unsafe_pruned": plan["search"]["unsafe_pruned"],
        "frontier_size": plan["frontier_size"],
        "product_mass": plan["product_mass"],
        "guard_terms": plan["guard_terms"],
        "solver_wall_ns": elapsed,
    }


def failure_closed_checks() -> dict:
    search_failed = False
    try:
        branches = [{"0": ["a.0"], "1": ["b.0"]}, {"0": ["a.1"], "1": ["b.1"]}]
        current = {"0": ["a.0"], "1": ["b.0"]}
        candidates = {"0": [["a.0"], ["a.1"]], "1": [["b.0"], ["b.1"]]}
        frontier_synthesize(branches, current, candidates, max_states=1)
    except ValueError as exc:
        search_failed = str(exc) == "exact frontier search-state bound"

    library_failed = False
    try:
        atoms = [f"x.{i}" for i in range(8)]
        branches = [{"0": [atom]} for atom in atoms]
        current = {"0": [atoms[0]]}
        candidates = {"0": [[atoms[0]] + atoms[1:i + 1] for i in range(8)]}
        frontier_synthesize(branches, current, candidates)
    except ValueError as exc:
        library_failed = str(exc) == "exact frontier local-library bound"
    assert search_failed and library_failed
    return {"search_state_bound_rejected": search_failed, "local_library_bound_rejected": library_failed}


def run(out: Path) -> dict:
    begin = time.perf_counter()
    cpu = time.process_time()
    rows = []
    for profiles in range(3, 9):
        for edge_count in sorted({profiles, min(8, 2 * profiles)}):
            for seed in range(2000, 2010):
                rows.append(run_case(profiles, edge_count, seed + profiles * 101 + edge_count * 17))
    for seed in range(2100, 2120):
        rows.append(ternary_case(seed))
    out.mkdir(parents=True, exist_ok=True)
    with (out / "scaling.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    failures = failure_closed_checks()
    result = {
        "scope": "bounded synthetic solver stress; timings are local component measurements",
        "cases": len(rows),
        "dimensions": sorted(set(r["dimension"] for r in rows)),
        "profiles_per_owner": [min(r["profiles_per_owner"] for r in rows), max(r["profiles_per_owner"] for r in rows)],
        "max_search_states": max(r["search_states"] for r in rows),
        "median_search_states": sorted(r["search_states"] for r in rows)[len(rows) // 2],
        "max_frontier_size": max(r["frontier_size"] for r in rows),
        "max_product_mass": max(r["product_mass"] for r in rows),
        "bound_checks": failures,
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - begin,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m tests.scaling OUTPUT_DIR")
    result = run(Path(sys.argv[1]))
    (Path(sys.argv[1]) / "scaling.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
