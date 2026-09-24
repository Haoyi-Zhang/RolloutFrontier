"""Offline audit of a curated Android class-introduction slice.

The CSV contains factual class-presence metadata transcribed from official Android
reference pages.  This test never contacts Android services or the network.  It
checks the retained transformation, generated assembly-time lower-bound fixtures,
and one explicitly synthetic mapping into the finite frontier model.  It does not
establish behavioral compatibility or workload prevalence.
"""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import random
import resource
import time

from src.checker import frontier_certificate
from src.envelope import frontier_synthesize

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "android-class-introductions.csv"
SEED = 20260912


def read_rows() -> list[dict]:
    with DATA.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 24
    assert set(rows[0]) == {
        "contract", "class", "first_public_api_level", "official_reference", "checked_on"
    }
    contracts = [row["contract"] for row in rows]
    classes = [row["class"] for row in rows]
    assert len(set(contracts)) == len(contracts)
    assert len(set(classes)) == len(classes)
    for row in rows:
        level = int(row["first_public_api_level"])
        assert 1 <= level <= 34
        assert row["contract"].startswith("api.")
        assert row["class"].startswith("android.")
        assert row["official_reference"] == (
            "https://developer.android.com/reference/" + row["class"].replace(".", "/")
        )
        assert row["checked_on"] == "2026-09-12"
    return rows


def support(rows: list[dict], level: int) -> list[str]:
    return sorted(row["contract"] for row in rows
                  if int(row["first_public_api_level"]) <= level)


def lower_bound(rows_by_contract: dict[str, dict], references: list[str]) -> int:
    if not references:
        raise ValueError("nonempty reference set required")
    return max(int(rows_by_contract[name]["first_public_api_level"])
               for name in references)


def run() -> dict:
    started, cpu = time.perf_counter(), time.process_time()
    rows = read_rows()
    by_contract = {row["contract"]: row for row in rows}

    # Every retained introduction fact has a two-sided boundary check in the
    # derived presence model: absent immediately before, present at introduction.
    boundary_checks = 0
    for row in rows:
        level = int(row["first_public_api_level"])
        name = row["contract"]
        assert name not in support(rows, level - 1)
        assert name in support(rows, level)
        boundary_checks += 2

    levels = [8, 9, 11, 14, 16, 17, 18, 19, 21, 22, 23, 25, 26, 28, 29, 31, 33, 34]
    counts = [len(support(rows, level)) for level in levels]
    assert counts == sorted(counts) and counts[-1] == len(rows)

    # Generated reference sets illustrate MoonlightBox-style lower bounds only.
    # They are not applications or sampled workloads.  Each has one valid and one
    # deliberately impossible declared assembly level.
    rng = random.Random(SEED)
    contracts = sorted(by_contract)
    lower_bound_checks = 0
    observed_bounds: dict[int, int] = {}
    for case in range(96):
        size = 1 + case % 6
        references = sorted(rng.sample(contracts, size))
        bound = lower_bound(by_contract, references)
        assert all(int(by_contract[name]["first_public_api_level"]) <= bound
                   for name in references)
        assert any(int(by_contract[name]["first_public_api_level"]) > bound - 1
                   for name in references)
        lower_bound_checks += 2
        observed_bounds[bound] = observed_bounds.get(bound, 0) + 1

    # Explicitly synthetic five-owner mapping.  Candidate profiles are cumulative
    # API-level support sets; the two workload alternatives are manually declared.
    current_levels = [18, 21, 26, 29, 34]
    current = {str(i): support(rows, level) for i, level in enumerate(current_levels)}
    candidate_levels = [[17, 18, 19], [19, 21, 22], [25, 26, 28],
                        [28, 29, 31], [31, 33, 34]]
    candidates = {str(i): [support(rows, level) for level in levels_i]
                  for i, levels_i in enumerate(candidate_levels)}
    branches = [
        {"0": ["api.bluetooth-manager"], "1": ["api.job-scheduler"],
         "2": ["api.shortcut-manager"], "3": [], "4": []},
        {"0": [], "1": [], "2": ["api.vibration-effect"],
         "3": ["api.role-manager"], "4": ["api.credential-manager"]},
    ]
    plan = frontier_synthesize(branches, current, candidates)
    assert frontier_certificate(branches, current, candidates, plan)
    assert plan["frontier_size"] >= 1
    assert plan["product_mass"] >= 1

    digest = hashlib.sha256(DATA.read_bytes()).hexdigest()
    return dict(
        source_file="data/android-class-introductions.csv",
        source_sha256=digest,
        declaration_facts=len(rows),
        api_level_span=[min(int(r["first_public_api_level"]) for r in rows),
                        max(int(r["first_public_api_level"]) for r in rows)],
        distinct_introduction_levels=len({int(r["first_public_api_level"]) for r in rows}),
        boundary_presence_checks=boundary_checks,
        support_levels=levels,
        support_counts=counts,
        generated_reference_sets=96,
        lower_bound_checks=lower_bound_checks,
        generated_lower_bound_distribution={str(k): observed_bounds[k]
                                            for k in sorted(observed_bounds)},
        synthetic_frontier=dict(
            endpoint_levels=current_levels,
            candidate_levels=candidate_levels,
            alternatives=len(branches),
            frontier_size=plan["frontier_size"],
            product_mass=plan["product_mass"],
            search=plan["search"],
        ),
        seed=SEED,
        scope=("curated official class-introduction metadata and generated reference sets; "
               "not an SDK corpus, real application sample, Android execution, behavioral "
               "equivalence, or production workload"),
        cpu_seconds=time.process_time() - cpu,
        wall_seconds=time.perf_counter() - started,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
