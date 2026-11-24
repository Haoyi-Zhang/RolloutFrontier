"""Certified difference-bound acceleration with the complete frontier fallback.

No version names or owner roles are trusted. Each local transition graph must
be one directed chain. The constructor derives ranks from those edges, computes
the tight difference-bound hull of the manifest's finite compatible relation,
and checks that the hull contains no additional catalog placement. Recognized
relations have a monotone, componentwise greatest phase endpoint. Iterating that
endpoint solves the same phase-first objective without enumerating frontiers.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import product
from math import prod

from .envelope import antichain, verify_box
from .goal_planner import GoalPlanner


class CertifiedGoalPlanner:
    """Recognize an exact chain/zone structure, otherwise use ``GoalPlanner``.

    Recognition examines the complete physical catalog within the existing
    placement budget. The returned plans are accepted by RolloutCoordinator.
    ``recognition()`` exposes the finite equivalence certificate; its profile
    order is determined by permitted transitions, not textual atom names.
    """

    def __init__(self, branches, candidates, transitions=None, **budgets):
        self.fallback = GoalPlanner(branches, candidates, transitions, **budgets)
        self.nodes = self.fallback.nodes
        self.orders, self.ranks = {}, {}
        self._queries = 0
        self._structured = 0
        self._fallback_queries = 0
        self._iterations = 0
        self._guard_corners = 0
        self._certificate = self._recognize()

    def _recognize(self):
        certificate = {"recognized": False, "catalog_placements":
                       self.fallback.placement_count, "checked_placements": 0}
        for node in self.nodes:
            graph = self.fallback.adjacency[node]
            incoming = [0] * len(graph)
            for neighbors in graph:
                for target in neighbors:
                    incoming[target] += 1
            roots = [index for index, degree in enumerate(incoming) if degree == 0]
            if (len(roots) != 1 or any(degree > 1 for degree in incoming)
                    or any(len(neighbors) > 1 for neighbors in graph)):
                return dict(certificate, reason="local graph is not a directed chain", owner=node)
            order, seen, current = [], set(), roots[0]
            while current not in seen:
                order.append(current)
                seen.add(current)
                if not graph[current]:
                    break
                current = graph[current][0]
            if len(order) != len(graph) or graph[order[-1]]:
                return dict(certificate, reason="local graph is not a directed chain", owner=node)
            self.orders[node] = tuple(order)
            self.ranks[node] = {index: rank for rank, index in enumerate(order)}
        shape = [len(self.orders[node]) for node in self.nodes]
        # A profile's mask records exactly which manifest alternatives it meets.
        masks = {node: [sum(1 << branch for branch, requirements in
                           enumerate(self.fallback.branches)
                           if set(requirements[node]) <=
                           set(self.fallback.domains[node][index]))
                       for index in self.orders[node]] for node in self.nodes}
        compatible = []
        for state in product(*(range(size) for size in shape)):
            mask = (1 << len(self.fallback.branches)) - 1
            for node, rank in zip(self.nodes, state):
                mask &= masks[node][rank]
            if mask:
                compatible.append(state)
        certificate["compatible_placements"] = len(compatible)
        certificate["checked_placements"] = prod(shape)
        if not compatible:
            return dict(certificate, reason="empty compatible relation")
        lower = [min(state[i] for state in compatible) for i in range(len(shape))]
        upper = [max(state[i] for state in compatible) for i in range(len(shape))]
        bounds = [[max(state[i] - state[j] for state in compatible)
                   for j in range(len(shape))] for i in range(len(shape))]
        allowed = set(compatible)
        for state in product(*(range(size) for size in shape)):
            inside = (all(low <= value <= high for low, value, high in zip(lower, state, upper))
                      and all(state[i] - state[j] <= bounds[i][j]
                              for i in range(len(shape)) for j in range(len(shape)) if i != j))
            if inside != (state in allowed):
                # The tight hull always contains the relation. Retaining an
                # explicit additional cell makes rejection independently checkable.
                return dict(certificate, reason="difference hull adds an incompatible placement",
                            hull_counterexample=list(state))
        return dict(certificate, recognized=True, nodes=list(self.nodes),
                    ordered_profiles={node: [list(self.fallback.domains[node][index])
                                             for index in self.orders[node]] for node in self.nodes},
                    lower=lower, upper=upper, difference_bounds=bounds)

    def recognition(self):
        return deepcopy(self._certificate)

    def statistics(self):
        return {"queries": self._queries, "structured_queries": self._structured,
                "fallback_queries": self._fallback_queries,
                "greedy_iterations": self._iterations,
                "guard_corners": self._guard_corners,
                "recognition_placements": self._certificate["checked_placements"]}

    def _rank_state(self, state):
        physical = self.fallback._state(state)
        return tuple(self.ranks[node][index] for node, index in zip(self.nodes, physical))

    def _external(self, state):
        return {node: list(self.fallback.domains[node][self.orders[node][rank]])
                for node, rank in zip(self.nodes, state)}

    def _phase(self, source, target):
        paths, box, steps = {}, {}, []
        for owner, node in enumerate(self.nodes):
            paths[node] = [list(self.fallback.domains[node][self.orders[node][rank]])
                           for rank in range(source[owner], target[owner] + 1)]
            relevant = set().union(*(set(branch[node]) for branch in self.fallback.branches))
            box[node] = antichain([sorted(set(profile) & relevant) for profile in paths[node]])
            steps.extend({"node": node, "support": profile} for profile in paths[node][1:])
        check = verify_box(self.fallback.branches, box)
        if not check["safe"]:
            raise RuntimeError("recognized structured phase failed original guard safety")
        self._guard_corners += check["corners"]
        return {"source": self._external(source), "target": self._external(target),
                "box": box, "local_paths": paths, "steps": steps}

    def plan(self, current, target):
        self._queries += 1
        if not self._certificate["recognized"]:
            self._fallback_queries += 1
            answer = self.fallback.plan(current, target)
            answer["strategy"] = "complete-frontier"
            answer["structure"] = self.recognition()
            return answer
        self._structured += 1
        source, destination = self._rank_state(current), self._rank_state(target)
        physical_source = self.fallback._state(current)
        if not self.fallback._safe(physical_source):
            raise ValueError("goal initial placement incompatible")
        before = self.statistics()
        base = {"schema": "rollout-goal-plan-v1", "branches": deepcopy(self.fallback.branches),
                "initial": self._external(source), "target": self._external(destination),
                "catalog": deepcopy(self.fallback.catalog), "transitions": deepcopy(self.fallback.transitions),
                "objective": ["fewest guard phases", "fewest installations"],
                "strategy": "certified-difference-bounds", "structure": self.recognition(),
                "scope": "finite manifest exactly recognized in directed-chain ranks",
                "budgets": {"placements": self.fallback.max_placements,
                            "phase_candidates": self.fallback.max_phase_edges,
                            "frontier_states_per_expansion": self.fallback.max_frontier_states}}
        trace, phases = [list(source)], []

        def finish(status, reason=None):
            result = dict(base, status=status, phases=deepcopy(phases) if status == "planned" else [],
                          cost={"phases": len(phases), "installations": sum(b - a for a, b in zip(source, destination)),
                                "handoffs": max(len(phases) - 1, 0)} if status == "planned" else None,
                          search={"rank_iterates": deepcopy(trace), "before": before,
                                  "after": self.statistics()})
            if reason is not None:
                result["reason"] = reason
            return result

        if not self.fallback._safe(self.fallback._state(target)):
            return finish("unreachable", "target incompatible")
        if any(goal < start for start, goal in zip(source, destination)):
            return finish("unreachable", "target precedes source on a directed chain")
        state = source
        bounds, upper = self._certificate["difference_bounds"], self._certificate["upper"]
        while state != destination:
            following = tuple(min([destination[i], upper[i]] +
                                  [state[j] + bounds[i][j] for j in range(len(self.nodes)) if i != j])
                              for i in range(len(self.nodes)))
            self._iterations += 1
            trace.append(list(following))
            if any(after < before for before, after in zip(state, following)):
                raise RuntimeError("recognized structured successor regressed")
            if following == state:
                return finish("unreachable", "greatest safe endpoint is a fixed point before target")
            phases.append(self._phase(state, following))
            state = following
        return finish("planned")


def plan_certified_goal(branches, current, candidates, target, transitions=None, **budgets):
    """One-shot exact planning with automatic, checked structural acceleration."""
    return CertifiedGoalPlanner(branches, candidates, transitions, **budgets).plan(current, target)
