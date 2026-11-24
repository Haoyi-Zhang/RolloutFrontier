"""Paired complete-solver comparison to the pre-mask membership-cache backend.

Reference code below is the inspected previous _partial_safe, not a weaker greedy
planner. No packages, sockets or remote data. Fresh calls include normalization,
local library construction, search, frontier output and mask setup when enabled.
Certificate reconstruction is timed separately, identically for both backends.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
from itertools import combinations, product
import json
from pathlib import Path
import platform
import random
from statistics import median
import sys
import time
from unittest.mock import patch
from src import checker, envelope


def previous_partial_safe(branch_sets, assigned, term_memberships=None, unused_masks=None):
    if term_memberships is None:
        term_memberships = {term: frozenset(term)
                            for term in {term for _, guard in assigned for term in guard}}
    for local_values in product(*(guard for _, guard in assigned)):
        possible = False
        for branch in branch_sets:
            if all(branch[node].issubset(term_memberships[value])
                   for (node, _), value in zip(assigned, local_values)):
                possible = True
                break
        if not possible:
            return False
    return True


def cases():
    # Full factorial retained dense construction, no post-timing case selection.
    for b, owners, seed, budget in product((3, 4), (2, 3), (3000, 3001, 3002), (400, 2000)):
        names = [f"c.{i}" for i in range(b)]
        nodes = [str(i) for i in range(owners)]
        branches = [{node: [atom] for node in nodes} for atom in names]
        current = {node: names[:] for node in nodes}
        candidates = {}
        for node in nodes:
            pairs = list(combinations(names, 2))
            random.Random(seed * 101 + int(node)).shuffle(pairs)
            candidates[node] = [list(pair) for pair in pairs[:min(4, 9-b)]]
        yield f"dense-b{b}-n{owners}-s{seed}-k{budget}", branches, current, candidates, budget
    # Wider term payload with the same complete finite guard semantics.
    common = [f"shared{i:03d}" for i in range(95)]
    branches = [{"0": ["a"], "1": common + ["left"]},
                {"0": ["b"], "1": common + ["right"]}]
    current = {"0": ["a"], "1": sorted(set(branches[0]["1"] + branches[1]["1"]))}
    yield "97-atom-projected-term", branches, current, {"0": [["a"], ["b"]], "1": [current["1"]]}, 2000


def execute(backend, branches, current, candidates, budget):
    with ExitStack() as stack:
        if backend == "previous":
            stack.enter_context(patch.object(envelope, "_partial_safe", previous_partial_safe))
            # The old backend had no truth-mask setup; exclude it from its path.
            stack.enter_context(patch.object(envelope, "_branch_masks", return_value=None))
        begin = time.perf_counter_ns()
        try:
            plan = envelope.frontier_synthesize(branches, current, candidates, max_states=budget)
        except ValueError as error:
            if str(error) != "exact frontier search-state bound":
                raise
            plan = dict(refusal=str(error))
        elapsed = time.perf_counter_ns() - begin
    return plan, elapsed


def run(repetitions):
    if not 3 <= repetitions <= 15:
        raise ValueError("3..15 paired repetitions")
    rows = []
    for name, branches, current, candidates, budget in cases():
        # One untimed warmup of each complete path. Both must agree before timing.
        reference = execute("previous", branches, current, candidates, budget)[0]
        if execute("mask", branches, current, candidates, budget)[0] != reference:
            raise RuntimeError(f"warmup complete-plan mismatch: {name}")
        samples = {backend: [] for backend in ("previous", "mask")}
        checks = []
        for repeat in range(repetitions):
            for backend in (("previous", "mask") if repeat % 2 == 0 else ("mask", "previous")):
                plan, elapsed = execute(backend, branches, current, candidates, budget)
                if plan != reference:
                    raise RuntimeError(f"complete-plan mismatch: {name} {backend}")
                samples[backend].append(elapsed)
                if "refusal" not in plan:
                    begin = time.perf_counter_ns()
                    if not checker.frontier_certificate(branches, current, candidates, plan,
                                                        combination_bound=budget):
                        raise RuntimeError(f"frontier certificate rejected: {name} {backend}")
                    checks.append(time.perf_counter_ns()-begin)
        rows.append(dict(case=name, budget=budget, completed="refusal" not in reference,
                         search=reference.get("search"), frontier_size=reference.get("frontier_size"),
                         product_mass=reference.get("product_mass"), refusal=reference.get("refusal"),
                         complete_plan_equal=True, samples_ns=samples,
                         previous_median_ns=median(samples["previous"]),
                         mask_median_ns=median(samples["mask"]),
                         checker_median_ns=median(checks) if checks else None,
                         speed_ratio=median(samples["previous"])/median(samples["mask"])))
    return dict(python=sys.version, platform=platform.platform(), repetitions=repetitions,
                paired_order="alternating; one warmup/backend/case; fresh complete calls",
                cases=len(rows), completed=sum(row["completed"] for row in rows),
                refused=sum(not row["completed"] for row in rows), rows=rows,
                sum_previous_case_medians_ns=sum(row["previous_median_ns"] for row in rows),
                sum_mask_case_medians_ns=sum(row["mask_median_ns"] for row in rows),
                scope="local same-semantic complete solver comparison; no throughput, WAN or asymptotic claim")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("result already exists; do not overwrite evidence")
    result = run(args.repetitions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
