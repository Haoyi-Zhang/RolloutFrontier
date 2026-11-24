"""Independent finite checks for catalog-covered static-batch optimality.

The reference enumerates local antichains and *all* abstract support vectors;
it neither calls the production corner test nor removes dominated products
before computing the batch optimum.  Installed changes compare complete
support values, not only their manifest projections.  This is an untimed
logical study, not a performance or deployment experiment.

Run from the artifact root:
    python -B -m tests.static_batch_optimality --out /new/output/directory

The optional destination must be absent or empty.  With no destination, the
same JSON result is printed.  Checks use explicit exceptions and remain active
under Python -O.
"""
from __future__ import annotations

import argparse
import hashlib
from itertools import combinations, product
import json
from math import prod
from pathlib import Path
import platform
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "src/batch.py", "src/envelope.py", "src/checker.py", "src/controller.py",
    "tests/static_batch_optimality.py",
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in SOURCE_FILES}


def subsets(values, empty=True):
    return [tuple(c) for size in range(0 if empty else 1, len(values) + 1)
            for c in combinations(values, size)]


def holds(guard, support):
    return any(all(atom in support for atom in term) for term in guard)


def truth(branches, state):
    return any(all(all(atom in state[node] for atom in required)
                   for node, required in branch.items()) for branch in branches)


def box_key(box):
    return tuple((node, tuple(tuple(t) for t in box[node])) for node in sorted(box))


def direct_products(branches, current, candidates, universes):
    """Return every legal product before acceptance-mask canonicalization.

    The test domain uses unit weights per supplied candidate.  Projected
    duplicates are retained in its mass calculation and combined only for
    the candidate-acceptance sets.  A zero-weight current anchor is included.
    """
    nodes = sorted(current)
    local, catalogs = {}, {}
    raw_projected = {}
    for node in nodes:
        relevant = {atom for branch in branches for atom in branch[node]}
        anchor = tuple(sorted(set(current[node]) & relevant))
        raw = [tuple(sorted(set(c) & relevant)) for c in candidates[node]]
        raw_projected[node] = raw
        catalogs[node] = sorted({anchor, *raw})
        library = sorted({anchor, *raw,
                          *(tuple(sorted(branch[node])) for branch in branches)})
        require(len(library) <= 10, "reference input exceeds local library")
        choices = []
        for guard in subsets(library, empty=False):
            if len(guard) > 8:
                continue
            if any(set(a) < set(b) for a in guard for b in guard):
                continue
            if not holds(guard, anchor):
                continue
            accepted = frozenset(p for p in catalogs[node] if holds(guard, p))
            runtime = [s for s in subsets(universes[node]) if holds(guard, s)]
            mass = sum(holds(guard, p) for p in raw)
            choices.append((guard, accepted, runtime, mass))
        local[node] = choices

    safe = []
    for selected in product(*(local[node] for node in nodes)):
        if prod(len(choice[0]) for choice in selected) > 4096:
            continue
        if not all(truth(branches, dict(zip(nodes, state)))
                   for state in product(*(choice[2] for choice in selected))):
            continue
        box = {node: [list(term) for term in choice[0]]
               for node, choice in zip(nodes, selected)}
        safe.append(dict(box=box,
                         acceptance=tuple(choice[1] for choice in selected),
                         masses=tuple(choice[3] for choice in selected),
                         terms=sum(len(choice[0]) for choice in selected)))
    require(bool(safe), "compatible anchor must have a legal product")
    representatives = {}
    for entry in safe:
        label = entry["acceptance"]
        old = representatives.get(label)
        if old is None or (entry["terms"], box_key(entry["box"])) < (
                old["terms"], box_key(old["box"])):
            representatives[label] = entry
    frontier = [entry for label, entry in representatives.items()
                if not any(other != label and all(a >= b for a, b in zip(other, label))
                           for other in representatives)]
    return safe, frontier, catalogs


def literal_replay(box, current, proposals):
    state = {node: tuple(sorted(set(support))) for node, support in current.items()}
    counts = dict(proposals=len(proposals), installed=0, blocked=0, unchanged=0)
    for proposal in proposals:
        node = proposal["node"]
        support = tuple(sorted(set(proposal["support"])))
        if support == state[node]:
            counts["unchanged"] += 1
        elif holds(box[node], support):
            counts["installed"] += 1
            state[node] = support
        else:
            counts["blocked"] += 1
    counts["final"] = {node: list(support) for node, support in state.items()}
    return counts


def acceptance_program(box, supports):
    return tuple(sum((1 << index) for index, support in enumerate(supports[node])
                     if holds(box[node], support)) for node in sorted(box))


def count_program(program, start, schedule):
    """Literal local transitions over four *full* supports per owner."""
    state = list(start)
    installed = 0
    for node, support_index in schedule:
        if state[node] != support_index and program[node] & (1 << support_index):
            state[node] = support_index
            installed += 1
    return installed


def finite_monotonicity():
    """All nested acceptance sets on four values and schedules of length <= 5."""
    schedules = [schedule for length in range(6)
                 for schedule in product(range(4), repeat=length)]
    checks = 0
    strict_gains = 0
    triples = 0
    for small in range(1, 16):
        for large in range(1, 16):
            if small | large != large:
                continue
            for initial in range(4):
                if not small & (1 << initial):
                    continue
                triples += 1
                for schedule in schedules:
                    a = count_program((small,), (initial,), [(0, s) for s in schedule])
                    b = count_program((large,), (initial,), [(0, s) for s in schedule])
                    require(a <= b, "acceptance expansion reduced installed changes")
                    strict_gains += a < b
                    checks += 1
    return dict(support_values=4, nested_set_seed_triples=triples,
                schedules_per_triple=len(schedules), maximum_schedule_length=5,
                comparisons=checks, strict_gains=strict_gains, mismatches=0)


def positive_catalog_campaign(frontier_synthesize, frontier_certificate, choose_batch_box):
    """Complete two-atom one/two-alternative contexts, then all length <= 3 batches."""
    universes = {"0": ("a", "b"), "1": ("c", "d")}
    supports = {node: subsets(atoms) for node, atoms in universes.items()}
    candidates = {node: [list(s) for s in values] for node, values in supports.items()}
    alternatives = [{"0": list(a), "1": list(b)}
                    for a, b in product(supports["0"], supports["1"])]
    actions = tuple(product(range(2), range(4)))
    schedules = [schedule for length in range(4)
                 for schedule in product(actions, repeat=length)]
    counts = dict(manifests=0, compatible_seed_contexts=0,
                  legal_products_before_quotient=0, canonical_frontier_members=0,
                  all_product_vs_frontier_batches=0, chooser_calls=0,
                  maximum_exhaustive_batch_length=3, mismatches=0)
    for branch_count in (1, 2):
        for branches_tuple in combinations(alternatives, branch_count):
            branches = list(branches_tuple)
            counts["manifests"] += 1
            for start in product(range(4), repeat=2):
                current = {node: list(supports[node][start[int(node)]]) for node in universes}
                if not truth(branches, current):
                    continue
                legal, direct_front, _ = direct_products(branches, current, candidates, universes)
                plan = frontier_synthesize(branches, current, candidates)
                require(frontier_certificate(branches, current, candidates, plan),
                        "production frontier certificate rejected")
                require({box_key(entry["box"]) for entry in direct_front} ==
                        {box_key(entry["box"]) for entry in plan["frontier"]},
                        "literal full-support frontier mismatch")
                all_programs = {acceptance_program(entry["box"], supports) for entry in legal}
                frontier_programs = {acceptance_program(entry["box"], supports)
                                     for entry in plan["frontier"]}
                for schedule in schedules:
                    all_best = max(count_program(p, start, schedule) for p in all_programs)
                    frontier_best = max(count_program(p, start, schedule) for p in frontier_programs)
                    require(all_best == frontier_best, "frontier omitted a static-batch optimum")
                    counts["all_product_vs_frontier_batches"] += 1
                # Exercise the real selector once per context on a longer batch;
                # the independent optimum still ranges over *all* legal products.
                proposals = [dict(node=str(node), support=list(supports[str(node)][index]))
                             for node, index in (*actions, *reversed(actions))]
                chosen = choose_batch_box(branches, current, candidates, proposals)
                observed = literal_replay(chosen["box"], current, proposals)
                optimum = max(literal_replay(entry["box"], current, proposals)["installed"]
                              for entry in legal)
                require(chosen["forecast"] == observed, "selector forecast/replay disagreement")
                require(observed["installed"] == optimum, "selector missed covered-batch optimum")
                counts["chooser_calls"] += 1
                counts["compatible_seed_contexts"] += 1
                counts["legal_products_before_quotient"] += len(legal)
                counts["canonical_frontier_members"] += len(direct_front)
    counts["schedules_per_context"] = len(schedules)
    counts["integrated_chooser_batch_length"] = 2 * len(actions)
    return counts


def projected_coverage_controls(choose_batch_box):
    """Sparse catalogs, zero-weight anchors, irrelevant changes and off-catalog failure."""
    branches = [{"0": ["a"]}, {"0": ["b"]}]
    current = {"0": ["a", "b", "old"]}
    catalog = {"0": [["a", "b"]]}
    proposals = [dict(node="0", support=support) for support in (
        ["a", "b", "new"], ["a", "b", "new"], ["a", "b"],
        ["a", "b", "old"], ["a", "b", "old"])]
    legal, _, _ = direct_products(branches, current, catalog, {"0": ("a", "b", "old", "new")})
    selected = choose_batch_box(branches, current, catalog, proposals)
    scores = [literal_replay(entry["box"], current, proposals)["installed"] for entry in legal]
    require(set(scores) == {3}, "projection changed full-support change counts")
    require(selected["forecast"]["installed"] == 3, "irrelevant-only changes were discarded")
    require(selected["forecast"]["unchanged"] == 2, "full-support no-op count mismatch")

    # The current anchor is part of D_i even when candidates are empty.
    anchored = choose_batch_box(branches, current, {"0": []}, proposals)
    require(anchored["forecast"] == selected["forecast"], "zero-weight anchor coverage mismatch")
    require(anchored["frontier_plan"]["product_mass"] == 0, "anchor gained candidate weight")

    # A different, equally accepting safe guard helps a proposal not covered by
    # the catalog.  This is a deliberate boundary witness, not an implementation bug.
    outside = [dict(node="0", support=["b"])]
    missed = choose_batch_box(branches, current, catalog, outside)
    alternate = {"0": [["b"]]}
    require(missed["box"] == {"0": [["a"]]}, "unexpected canonical representative")
    require(missed["forecast"]["installed"] == 0, "off-catalog control no longer discriminates")
    require(literal_replay(alternate, current, outside)["installed"] == 1,
            "alternative guard did not realize the off-catalog witness")
    covered = choose_batch_box(branches, current, {"0": [["a", "b"], ["b"]]}, outside)
    require(covered["forecast"]["installed"] == 1,
            "including the proposed projection did not restore the static optimum")
    return dict(covered_irrelevant_change_proposals=len(proposals),
                covered_irrelevant_changes=3, covered_full_support_noops=2,
                equal_catalog_legal_products=len(legal), empty_catalog_anchor_controls=1,
                off_catalog_selected_installs=0, off_catalog_alternate_installs=1,
                augmented_catalog_selected_installs=1,
                scope="coverage uses relevant projections; installations use complete supports")


def run():
    before = hashes()
    # Capture source identities before production modules are imported.
    from src.batch import choose_batch_box
    from src.checker import frontier_certificate
    from src.envelope import frontier_synthesize

    result = dict(
        schema="rolloutfrontier-static-batch-optimality-v1",
        monotonicity=finite_monotonicity(),
        positive_catalog=positive_catalog_campaign(frontier_synthesize,
                                                   frontier_certificate, choose_batch_box),
        projection_and_boundary=projected_coverage_controls(choose_batch_box),
        source_sha256=before,
        environment=dict(python=sys.version, platform=platform.platform()),
        scope=("finite logical checks of isolated static predicate guards with catalog-covered "
               "proposal projections and sufficient generation headroom; no timing, network, "
               "failure, deployment, or unseen-schedule claim"),
    )
    require(hashes() == before, "source changed during the study; rerun from stable files")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out is not None:
        destination = args.out.resolve()
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            parser.error("output directory must be absent or empty")
    result = run()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "summary.json").write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
