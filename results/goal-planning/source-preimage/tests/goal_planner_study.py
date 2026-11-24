"""Registered finite goal-planning campaign and a saved-witness checker.

Normal/optimized runs use all nonempty relations in the stated domains. The
two-by-two domain uses every directed local transition graph; larger domains
use four declared transition families. Every compatible ordered endpoint pair
is included, including no-ops and unreachable targets.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path

from src.goal_planner import GoalPlanner
from tests.goal_planner_oracle import (centralized_reachable, literal_phase_graph,
    literal_shortest, relation_inputs, support_state, support_transitions, validate_plan)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["src/goal_planner.py", "src/envelope.py", "src/checker.py", "src/controller.py",
           "tests/goal_planner_oracle.py", "tests/goal_planner_study.py"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def graph_families(shape):
    if tuple(shape) == (2, 2):
        possible = [(0, 1), (1, 0)]
        for masks in product(range(4), repeat=2):
            yield "all-directed-" + "-".join(map(str, masks)), [
                {edge for index, edge in enumerate(possible) if mask & (1 << index)}
                for mask in masks]
        return
    complete = [{(a, b) for a in range(size) for b in range(size) if a != b} for size in shape]
    forward = [{(value, value + 1) for value in range(size - 1)} for size in shape]
    reverse = [{(target, source) for source, target in edges} for edges in forward]
    yield "complete", complete
    yield "forward-chain", forward
    yield "reverse-chain", reverse
    if tuple(shape) == (3, 3):
        yield "directed-cycle", [{(value, (value + 1) % size) for value in range(size)} for size in shape]
    else:
        yield "alternating-direction", [forward[i] if i % 2 == 0 else reverse[i] for i in range(len(shape))]


def contexts():
    for shape in [(2, 2), (3, 3), (2, 2, 2)]:
        cells = list(product(*(range(size) for size in shape)))
        for mask in range(1, 1 << len(cells)):
            relation = {point for index, point in enumerate(cells) if mask & (1 << index)}
            for family, graphs in graph_families(shape):
                yield {"id": "x".join(map(str, shape)) + f"-r{mask}-" + family,
                       "shape": shape, "mask": mask, "relation": relation,
                       "family": family, "graphs": graphs}


def init_summary():
    return {"status": "PASS", "contexts": 0, "goal_queries": 0, "reachable": 0,
            "unreachable": 0, "zero_step_queries": 0, "planned_phases": 0,
            "planned_installations": 0, "literal_safe_products_summed": 0,
            "literal_phase_edges_summed": 0, "frontier_calls": 0,
            "centralized_reachability_mismatches": 0, "optimum_mismatches": 0,
            "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES},
            "design": {"2x2": "15 nonempty relations, all 16 directed graph pairs, all compatible ordered endpoints",
                       "3x3": "511 nonempty relations, complete/forward-chain/reverse-chain/directed-cycle, all compatible ordered endpoints",
                       "2x2x2": "255 nonempty relations, complete/forward-chain/reverse-chain/alternating-direction, all compatible ordered endpoints"},
            "scope": "Finite logical planning and full safe-product oracle; no network, failures or timing comparison."}


def record_query(summary, expected, source, target):
    summary["goal_queries"] += 1
    if expected is None:
        summary["unreachable"] += 1
    else:
        summary["reachable"] += 1
        summary["planned_phases"] += expected[0]
        summary["planned_installations"] += expected[1]
        summary["zero_step_queries"] += int(source == target)


def check_answer(plan, expected):
    actual = None if plan["status"] == "unreachable" else (plan["cost"]["phases"], plan["cost"]["installations"])
    require(actual == expected, "goal optimum differs from all-safe-product oracle")
    if expected is None:
        require(plan["status"] == "unreachable" and plan["cost"] is None and plan["phases"] == [],
                "unreachable result carries a plan")
    else:
        require(plan["status"] == "planned", "reachable result is not planned")
        validate_plan(plan)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    summary = init_summary()
    with (output / "queries.jsonl.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as archive:
            for context in contexts():
                relation, graphs = context["relation"], context["graphs"]
                branches, catalog = relation_inputs(context["shape"], relation)
                transitions = support_transitions(catalog, graphs)
                planner = GoalPlanner(branches, catalog, transitions)
                oracle, products_count = literal_phase_graph(context["shape"], relation, graphs)
                summary["contexts"] += 1
                summary["literal_safe_products_summed"] += products_count
                summary["literal_phase_edges_summed"] += sum(len(edges) for edges in oracle.values())
                for source in sorted(relation):
                    centralized = centralized_reachable(relation, graphs, source)
                    for target in sorted(relation):
                        expected = literal_shortest(oracle, source, target)
                        require((expected is not None) == (target in centralized), "phase and centralized reachability differ")
                        plan = planner.plan(support_state(catalog, source), support_state(catalog, target))
                        check_answer(plan, expected)
                        record_query(summary, expected, source, target)
                        row = {"context": context["id"], "source": source, "target": target,
                               "status": plan["status"], "cost": plan["cost"], "phases": plan["phases"]}
                        archive.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
                summary["frontier_calls"] += planner.statistics()["frontier_calls"]
    summary["queries_sha256"] = hashlib.sha256((output / "queries.jsonl.gz").read_bytes()).hexdigest()
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def check(output):
    saved = json.loads((output / "summary.json").read_text())
    summary = init_summary()
    for name, digest in saved["source_sha256"].items():
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, "source binding changed: " + name)
    require(hashlib.sha256((output / "queries.jsonl.gz").read_bytes()).hexdigest() == saved["queries_sha256"],
            "saved query bytes changed")
    with gzip.open(output / "queries.jsonl.gz", "rt") as rows:
        for context in contexts():
            relation, graphs = context["relation"], context["graphs"]
            branches, catalog = relation_inputs(context["shape"], relation)
            transitions = support_transitions(catalog, graphs)
            oracle, products_count = literal_phase_graph(context["shape"], relation, graphs)
            summary["contexts"] += 1
            summary["literal_safe_products_summed"] += products_count
            summary["literal_phase_edges_summed"] += sum(len(edges) for edges in oracle.values())
            for source in sorted(relation):
                centralized = centralized_reachable(relation, graphs, source)
                for target in sorted(relation):
                    text = next(rows, None)
                    require(text is not None, "missing goal query")
                    row = json.loads(text)
                    require(row["context"] == context["id"] and row["source"] == list(source)
                            and row["target"] == list(target), "goal query design/order changed")
                    expected = literal_shortest(oracle, source, target)
                    require((expected is not None) == (target in centralized), "reachability mismatch")
                    plan = {"initial": support_state(catalog, source), "target": support_state(catalog, target),
                            "branches": branches, "catalog": catalog, "transitions": transitions,
                            "status": row["status"], "cost": row["cost"], "phases": row["phases"]}
                    check_answer(plan, expected)
                    record_query(summary, expected, source, target)
        require(next(rows, None) is None, "extra goal query")
    # Invocation counts are operational metadata, not reconstructed logical facts.
    for name, value in summary.items():
        if name != "frontier_calls":
            require(saved.get(name) == value, "goal summary differs: " + name)
    return {"status": "PASS", "contexts": summary["contexts"], "goal_queries": summary["goal_queries"],
            "reachable": summary["reachable"], "unreachable": summary["unreachable"],
            "independent_all_safe_product_optima": True, "all_witnesses_checked": True,
            "centralized_reachability_agrees": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    if (args.out is None) == (args.check is None):
        parser.error("choose exactly one of --out and --check")
    print(json.dumps(run(args.out) if args.out else check(args.check), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
