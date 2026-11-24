"""Independent weighted-frontier and covered-batch controls.

The fixed design is documented in docs/ADVERSARIAL-FRONTIER-DESIGN.md. The
reference enumerates full abstract support vectors and all legal antichains;
it does not call production corner, dominance, scoring or forecast helpers.
Checks remain active under Python -O.

Run from the artifact root:
    python -B -m tests.adversarial_frontier --out /new/output/directory

An output directory must be absent or empty. This is a finite logical study,
not a timing, network, unseen-demand or production-deployment experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import random
import sys


ROOT = Path(__file__).resolve().parents[1]
MASTER_SEED = 8317401
CONTEXTS = 240
PROPOSALS_PER_CONTEXT = 31
SOURCE_FILES = (
    "src/envelope.py", "src/checker.py", "src/batch.py", "src/controller.py",
    "tests/adversarial_frontier.py", "docs/ADVERSARIAL-FRONTIER-DESIGN.md",
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def source_bytes():
    return {name: (ROOT / name).read_bytes() for name in SOURCE_FILES}


def source_hashes(contents):
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()}


def powerset(values):
    return [frozenset(choice)
            for size in range(len(values) + 1)
            for choice in itertools.combinations(values, size)]


def allows(guard, support):
    return any(term <= support for term in guard)


def manifest_truth(branches, state):
    return any(all(set(required) <= state[node]
                   for node, required in branch.items()) for branch in branches)


def box_key(box):
    return tuple((node, tuple(tuple(term) for term in box[node]))
                 for node in sorted(box))


def literal_products(branches, current, candidates, weights, universes):
    """Enumerate the entire tested guard language using full-support truth.

    Each raw profile contributes its own supplied weight, including when several
    profiles have the same relevant projection. Only the acceptance labels are
    deduplicated. The current projection is a zero-weight anchor if absent.
    """
    nodes = sorted(current)
    local, catalogs = {}, {}
    for node in nodes:
        relevant = set().union(*(set(branch[node]) for branch in branches))
        anchor = frozenset(current[node]) & relevant
        raw = [frozenset(profile) & relevant for profile in candidates[node]]
        catalog = sorted({anchor, *raw}, key=lambda value: tuple(sorted(value)))
        catalogs[node] = catalog
        library = sorted(
            {anchor, *raw, *(frozenset(branch[node]) for branch in branches)},
            key=lambda value: tuple(sorted(value)),
        )
        require(len(library) <= 10, "reference input exceeds local library")
        choices = []
        for size in range(1, min(8, len(library)) + 1):
            for guard in itertools.combinations(library, size):
                if any(a < b for a in guard for b in guard):
                    continue
                if not allows(guard, anchor):
                    continue
                accepted = frozenset(i for i, support in enumerate(catalog)
                                     if allows(guard, support))
                runtime = tuple(support for support in powerset(universes[node])
                                if allows(guard, support))
                mass = sum(weight for weight, support in zip(weights[node], raw)
                           if allows(guard, support))
                choices.append((guard, accepted, runtime, mass))
        local[node] = choices

    relation = {
        values
        for values in itertools.product(*(powerset(universes[node]) for node in nodes))
        if manifest_truth(branches, dict(zip(nodes, values)))
    }
    legal, checked_products = [], 0
    for choices in itertools.product(*(local[node] for node in nodes)):
        if math.prod(len(choice[0]) for choice in choices) > 4096:
            continue
        checked_products += 1
        if any(state not in relation
               for state in itertools.product(*(choice[2] for choice in choices))):
            continue
        box = {node: [sorted(term) for term in choice[0]]
               for node, choice in zip(nodes, choices)}
        masses = tuple(choice[3] for choice in choices)
        terms = sum(len(choice[0]) for choice in choices)
        legal.append(dict(
            box=box, acceptance=tuple(choice[1] for choice in choices),
            masses=masses, terms=terms,
            score=(math.prod(masses), sum(masses), -terms),
        ))
    require(bool(legal), "compatible initial state must have a safe product")

    representatives = {}
    for entry in legal:
        signature = entry["acceptance"]
        old = representatives.get(signature)
        if old is None or (entry["terms"], box_key(entry["box"])) < (
                old["terms"], box_key(old["box"])):
            representatives[signature] = entry
    frontier = [
        entry for signature, entry in representatives.items()
        if not any(other != signature and all(a >= b for a, b in zip(other, signature))
                   for other in representatives)
    ]
    return legal, frontier, catalogs, checked_products


def literal_replay(box, current, proposals):
    state = {node: frozenset(support) for node, support in current.items()}
    guards = {node: [frozenset(term) for term in terms]
              for node, terms in box.items()}
    statuses = []
    for proposal in proposals:
        node, target = proposal["node"], frozenset(proposal["support"])
        if target == state[node]:
            statuses.append("unchanged")
        elif allows(guards[node], target):
            statuses.append("installed")
            state[node] = target
        else:
            statuses.append("blocked")
    return dict(
        installed=statuses.count("installed"),
        blocked=statuses.count("blocked"),
        unchanged=statuses.count("unchanged"),
        final={node: sorted(support) for node, support in state.items()},
    )


def fixed_campaign(frontier_synthesize, frontier_certificate, choose_batch_box):
    rng = random.Random(MASTER_SEED)
    rows = []
    for case in range(CONTEXTS):
        owner_count = 2 if case < 120 else 3
        nodes = [str(node) for node in range(owner_count)]
        universes = {node: tuple(node + "." + atom for atom in "abc") for node in nodes}
        domains = {node: powerset(universes[node]) for node in nodes}
        branches = [
            {node: sorted(rng.choice(domains[node])) for node in nodes}
            for _ in range(1 + case % 5)
        ]
        safe_states = [
            values for values in itertools.product(*(domains[node] for node in nodes))
            if manifest_truth(branches, dict(zip(nodes, values)))
        ]
        picked = rng.choice(safe_states)
        current = {
            node: sorted(support | ({node + ".irrelevant.current"}
                                    if rng.randrange(2) else set()))
            for node, support in zip(nodes, picked)
        }
        candidates = {
            node: [
                sorted(rng.choice(domains[node]) |
                       ({node + ".irrelevant." + str(index)} if index % 2 else set()))
                for index in range(rng.randrange(9))
            ] for node in nodes
        }
        weights = {
            node: [rng.choice((0, 0, 1, 2, 13, 10**9)) for _ in candidates[node]]
            for node in nodes
        }
        legal, frontier, catalogs, checked = literal_products(
            branches, current, candidates, weights, universes)
        plan = frontier_synthesize(branches, current, candidates, weights)
        prefix = f"context {case}: "
        require(frontier_certificate(branches, current, candidates, plan, weights),
                prefix + "producer/checker disagreement")
        require(sorted(box_key(entry["box"]) for entry in plan["frontier"]) ==
                sorted(box_key(entry["box"]) for entry in frontier),
                prefix + "full-support literal frontier disagreement")
        best_score = max(entry["score"] for entry in frontier)
        best = min((entry for entry in frontier if entry["score"] == best_score),
                   key=lambda entry: box_key(entry["box"]))
        require(box_key(plan["box"]) == box_key(best["box"]),
                prefix + "weighted score/canonical tie disagreement")
        require(plan["product_mass"] == best["score"][0],
                prefix + "weighted mass disagreement")

        proposals = []
        for index in range(PROPOSALS_PER_CONTEXT):
            node = rng.choice(nodes)
            support = set(rng.choice(catalogs[node]))
            if index % 3:
                support.add(node + ".irrelevant." + str(index % 4))
            proposals.append(dict(node=node, support=sorted(support)))
        chosen = choose_batch_box(branches, current, candidates, proposals, weights)
        replay = literal_replay(chosen["box"], current, proposals)
        optimum = max(literal_replay(entry["box"], current, proposals)["installed"]
                      for entry in legal)
        require(replay["installed"] == optimum,
                prefix + "covered weighted batch optimum disagreement")
        require(all(chosen["forecast"][key] == replay[key] for key in replay),
                prefix + "full-support forecast disagreement")

        exact_budget = plan["search"]["states"]
        limited = frontier_synthesize(branches, current, candidates, weights,
                                     max_states=exact_budget)
        require(limited == plan, prefix + "exact visit budget changes output")
        require(frontier_certificate(branches, current, candidates, limited, weights,
                                     combination_bound=exact_budget),
                prefix + "exact checker budget rejects")
        require(exact_budget > 1, prefix + "unexpected empty search")
        try:
            frontier_synthesize(branches, current, candidates, weights,
                                max_states=exact_budget - 1)
        except ValueError as exc:
            require(str(exc) == "exact frontier search-state bound",
                    prefix + "wrong refusal at lower budget")
        else:
            raise AssertionError(prefix + "under-budget synthesis did not refuse")
        require(not frontier_certificate(branches, current, candidates, plan, weights,
                                         combination_bound=exact_budget - 1),
                prefix + "under-budget checker accepted")
        rows.append(dict(
            case=case, owners=owner_count, branch_count=len(branches),
            raw_candidates=sum(map(len, candidates.values())),
            zero_weights=sum(weight == 0 for values in weights.values() for weight in values),
            checked_products=checked, safe_products=len(legal),
            frontier_members=len(frontier), states=exact_budget,
            batch_installed=optimum,
            input=dict(branches=branches, current=current, candidates=candidates,
                       weights=weights, proposals=proposals),
            result=dict(max_mass_box=plan["box"], product_mass=plan["product_mass"],
                        frontier_boxes=[entry["box"] for entry in plan["frontier"]],
                        batch_box=chosen["box"], batch_forecast=chosen["forecast"],
                        exact_budget_accepted=True, one_less_budget_refused=True),
        ))
    return rows


def generation_headroom_control(choose_batch_box, endpoint_type, maximum_generation):
    """Remove only generation headroom; safety remains but the forecast can fail."""
    branches = [
        {"0": ["a0"], "1": ["b0"]},
        {"0": ["a0"], "1": ["b1"]},
        {"0": ["a0"], "1": ["b2"]},
        {"0": ["a1"], "1": ["b0"]},
    ]
    current = {"0": ["a0"], "1": ["b0"]}
    candidates = {"0": [["a0"], ["a1"]], "1": [["b0"], ["b1"], ["b2"]]}
    proposals = ([dict(node="0", support=[atom]) for atom in ["a1", "a0"] * 3] +
                 [dict(node="1", support=[atom]) for atom in ["b1", "b0"] * 2])
    headroom = {"0": 1, "1": 4}
    selected = choose_batch_box(branches, current, candidates, proposals)
    rows = []
    for entry in selected["frontier_plan"]["frontier"]:
        endpoints = {node: endpoint_type(int(node), support)
                     for node, support in current.items()}
        try:
            for node, endpoint in endpoints.items():
                # Seed a valid near-limit initial state before any admission;
                # do not simulate the preceding 2^63 installation history.
                endpoint.state["generation"] = maximum_generation - headroom[node]
                endpoint.state["catalog"][node] = endpoint.profile()
                held = endpoint.prepare(0, 1, "headroom-boundary", [], entry["box"][node])
                require(held["status"] == "held", "headroom control did not acquire")
            statuses = []
            for proposal in proposals:
                reply = endpoints[proposal["node"]].install(proposal["support"])
                statuses.append(reply["status"])
                require(manifest_truth(branches, {
                    node: set(endpoint.state["support"]) for node, endpoint in endpoints.items()
                }), "headroom control violated compatibility")
            rows.append(dict(
                box=entry["box"], selected=entry["box"] == selected["box"],
                forecast_installed=literal_replay(entry["box"], current, proposals)["installed"],
                actual_installed=statuses.count("installed"),
                actual_generation_exhausted=statuses.count("generation-exhausted"),
                statuses=statuses,
            ))
        finally:
            for endpoint in endpoints.values():
                endpoint.disconnect()
    chosen = next(row for row in rows if row["selected"])
    alternative = next(row for row in rows if not row["selected"])
    require((chosen["forecast_installed"], chosen["actual_installed"]) == (6, 1),
            "generation-headroom control no longer distinguishes the forecast")
    require((alternative["forecast_installed"], alternative["actual_installed"]) == (4, 4),
            "generation-headroom control lost its better feasible alternative")
    return dict(
        premise_removed="sufficient generation headroom", headroom=headroom,
        branches=branches, current=current, candidates=candidates, proposals=proposals,
        rows=rows, compatible_after_every_event=True,
        scope="In-memory Endpoint transitions from seeded near-limit initial states; no persistence or process-failure claim.",
    )


def term_count_control(frontier_synthesize):
    branches = [{"0": ["a", "b"]}, {"0": ["z"]}]
    current = {"0": ["a", "b", "z"]}
    candidates = {"0": [["a", "b", "z"]]}
    plan = frontier_synthesize(branches, current, candidates)
    alternative = {"0": [["z"]]}
    require(plan["box"] == {"0": [["a", "b"]]},
            "term-count/lexical control changed")
    require(manifest_truth(branches, {"0": {"z"}}),
            "single-atom alternative is not safe")
    return dict(
        branches=branches, current=current, candidates=candidates,
        selected=plan["box"], also_safe_same_acceptance=alternative,
        selected_terms=1, alternative_terms=1, selected_atoms=2, alternative_atoms=1,
        meaning="The tie rule minimizes term count, then lexical order; it does not minimize atom count or serialized bytes.",
    )


def run():
    before = source_bytes()
    # Record the source inventory before importing the production modules.
    from src.batch import choose_batch_box
    from src.checker import frontier_certificate
    from src.controller import Endpoint, MAX_SEQ
    from src.envelope import frontier_synthesize

    rows = fixed_campaign(frontier_synthesize, frontier_certificate, choose_batch_box)
    result = dict(
        schema="rolloutfrontier-adversarial-frontier-v1", status="PASS",
        design=dict(master_seed=MASTER_SEED, contexts=CONTEXTS,
                    two_owner_contexts=120, three_owner_contexts=120,
                    local_base_atoms=3, alternatives_range=[1, 5],
                    raw_candidates_per_owner_range=[0, 8],
                    weight_draws=[0, 0, 1, 2, 13, 10**9],
                    proposals_per_context=PROPOSALS_PER_CONTEXT),
        totals=dict(
            checked_products=sum(row["checked_products"] for row in rows),
            safe_products=sum(row["safe_products"] for row in rows),
            frontier_members=sum(row["frontier_members"] for row in rows),
            covered_batch_optimum_comparisons=len(rows),
            covered_batch_proposals=len(rows) * PROPOSALS_PER_CONTEXT,
            exact_budget_acceptances=len(rows), one_less_budget_refusals=len(rows),
            zero_weight_entries=sum(row["zero_weights"] for row in rows),
            mismatches=0,
        ),
        contexts=rows,
        generation_headroom=generation_headroom_control(choose_batch_box, Endpoint, MAX_SEQ),
        term_count_tie=term_count_control(frontier_synthesize),
        source_sha256=source_hashes(before),
        environment=dict(python=sys.version, platform=platform.platform()),
        scope=("Fixed-seed weighted finite-domain conformance and explicit premise controls; "
               "not exhaustive over all three-atom manifests, not an unseen-demand study, "
               "and not network, timing, storage-failure or production evidence."),
    )
    require(source_bytes() == before, "source changed during the study; rerun stable files")
    return result, before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    destination = args.out.resolve() if args.out is not None else None
    if destination is not None and destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            parser.error("output directory must be absent or empty")
    result, sources = run()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if destination is None:
        print(encoded, end="")
        return
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "summary.json").write_text(encoded, encoding="utf-8")
    for name, raw in sources.items():
        path = destination / "source-preimage" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    print(json.dumps(dict(status="PASS", output=str(destination),
                          contexts=CONTEXTS, totals=result["totals"]), indent=2))


if __name__ == "__main__":
    main()
