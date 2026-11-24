"""Optional static-box choice for an explicitly supplied finite proposal batch.

This does not replace the max-mass planner or predict an unknown future schedule.
Forecasts assume one unchanged admission, no other holds or intervening updates,
and sufficient generation headroom. Runtime admission and installation still use
the original independently checked guards and lifecycle operations.
"""
from __future__ import annotations
from copy import deepcopy

from .checker import frontier_certificate
from .controller import atoms, MAX_CONTRACTS
from .envelope import frontier_synthesize, MAX_FRONTIER_STATES

MAX_BATCH_PROPOSALS = 256


def _forecast(box, current, proposals):
    state = {node: list(support) for node, support in current.items()}
    guards = {node: [frozenset(term) for term in options] for node, options in box.items()}
    counts = dict(proposals=len(proposals), installed=0, blocked=0, unchanged=0)
    for node, target in proposals:
        if target == state[node]:
            counts["unchanged"] += 1
        elif any(term.issubset(target) for term in guards[node]):
            state[node] = list(target)
            counts["installed"] += 1
        else:
            counts["blocked"] += 1
    counts["final"] = state
    return counts


def choose_batch_box(branches, current, candidates, proposals, weights=None,
                     max_states=MAX_FRONTIER_STATES):
    """Choose among the original canonical frontier members for this batch only.

    Each proposal is exactly {"node": canonical_node_string, "support": atoms}.
    All proposals, including no-ops and refusals, remain in the denominator. A
    strict forecast increase is required to replace the original max-mass box;
    an empty batch or a tie keeps it. Alternative ties follow returned frontier
    order. Full frontier/search/cap checking is unchanged and refusals propagate.

    ``frontier_plan`` is the original max-mass result, not a certificate of the
    optional choice's mass optimality. Pass ``box`` to unchanged Client.acquire_box
    before performing updates. Forecasts are not live admission receipts and
    need not match execution with stale state, other holds, exhaustion or faults.
    """
    plan = frontier_synthesize(branches, current, candidates, weights, max_states)
    if not frontier_certificate(branches, current, candidates, plan, weights,
                                combination_bound=max_states):
        raise ValueError("batch frontier certificate rejected")
    if not isinstance(proposals, list) or len(proposals) > MAX_BATCH_PROPOSALS:
        raise ValueError("proposal batch bound")
    batch = []
    for item in proposals:
        if (not isinstance(item, dict) or set(item) != {"node", "support"}
                or type(item["node"]) is not str or item["node"] not in plan["box"]):
            raise ValueError("proposal batch item")
        batch.append((item["node"], atoms(item["support"], MAX_CONTRACTS)))
    initial = {node: atoms(support, MAX_CONTRACTS) for node, support in current.items()}
    default = _forecast(plan["box"], initial, batch)
    selected_box, selected = plan["box"], default
    scores = []
    for index, member in enumerate(plan["frontier"]):
        forecast = _forecast(member["box"], initial, batch)
        scores.append(dict(member_index=index, **forecast))
        if forecast["installed"] > selected["installed"]:
            selected_box, selected = member["box"], forecast
    return dict(box=deepcopy(selected_box), frontier_plan=plan,
                forecast=deepcopy(selected), max_mass_forecast=default,
                batch_scores=scores, kept_max_mass=selected_box == plan["box"],
                scope="supplied batch only; canonical returned frontier; isolated static guard forecast")
