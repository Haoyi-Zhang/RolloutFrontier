"""Exact goal planning over bounded positive guards and allowed local transitions.

A phase holds one safe Cartesian guard product. Each owner follows a shortest
path inside the part of its directed profile graph accepted by that product.
The objective is lexicographic: fewest phases, then fewest actual installations.
All physical catalog profiles are retained, including profiles with the same
projection onto manifest atoms. This module plans; it does not authorize writes.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from heapq import heappop, heappush
from itertools import product
from math import prod

from .checker import frontier_certificate
from .controller import MAX_CONTRACTS, atoms
from .envelope import MAX_FRONTIER_STATES, MAX_OPTIONS, compatible, frontier_synthesize, normalize

MAX_GOAL_PLACEMENTS = 4096
MAX_GOAL_PHASE_EDGES = 250_000
_FRONTIER_REFUSALS = {
    "exact frontier local-library bound", "exact frontier search-state bound",
    "exact frontier result bound",
}


class GoalPlanningRefusal(ValueError):
    """An explicit resource bound prevented an exact planning answer."""


def _budget(value, maximum, name):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(name)
    return value


def _profile(value):
    return tuple(atoms(value, MAX_CONTRACTS))


def _box_key(box, nodes):
    return tuple((node, tuple(tuple(term) for term in box[node])) for node in nodes)


class GoalPlanner:
    """Reusable exact phase graph for a fixed manifest, catalog and transitions.

    ``transitions`` maps each owner to dictionaries with exactly ``source`` and
    ``target`` full-support lists. Omission permits every distinct profile pair.
    Current and target profiles must belong to the supplied catalog. Catalogs
    contain at most eight raw profiles per owner; duplicates are canonicalized.

    The placement bound covers the entire physical Cartesian catalog. The phase
    edge budget counts (expanded state, frontier member, reachable destination)
    candidates, including parallel candidates, cumulatively for this instance.
    Completed expansions are cached across queries. A resource refusal is never
    reported as an unreachable goal or a partially optimal plan.
    """

    def __init__(self, branches, candidates, transitions=None, *,
                 max_placements=MAX_GOAL_PLACEMENTS,
                 max_phase_edges=MAX_GOAL_PHASE_EDGES,
                 max_frontier_states=MAX_FRONTIER_STATES):
        self.branches = normalize(branches)
        self.nodes = sorted(self.branches[0])
        self.max_placements = _budget(max_placements, MAX_GOAL_PLACEMENTS,
                                      "goal placement budget")
        self.max_phase_edges = _budget(max_phase_edges, MAX_GOAL_PHASE_EDGES,
                                       "goal phase-edge budget")
        self.max_frontier_states = _budget(max_frontier_states, MAX_FRONTIER_STATES,
                                           "goal frontier budget")
        if not isinstance(candidates, dict) or sorted(candidates) != self.nodes:
            raise ValueError("goal catalog placement")
        self.domains = {}
        for node in self.nodes:
            raw = candidates[node]
            if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_OPTIONS:
                raise ValueError("goal catalog profile bound")
            self.domains[node] = tuple(sorted({_profile(profile) for profile in raw}))
        self.placement_count = prod(len(self.domains[node]) for node in self.nodes)
        if self.placement_count > self.max_placements:
            raise GoalPlanningRefusal("goal placement bound")
        self.catalog = {node: [list(profile) for profile in self.domains[node]]
                        for node in self.nodes}
        self.indices = {node: {profile: index for index, profile in enumerate(self.domains[node])}
                        for node in self.nodes}
        if transitions is not None and (not isinstance(transitions, dict)
                                        or sorted(transitions) != self.nodes):
            raise ValueError("goal transition placement")
        self.adjacency, self.transitions = {}, {}
        for node in self.nodes:
            count = len(self.domains[node])
            if transitions is None:
                edges = {(a, b) for a in range(count) for b in range(count) if a != b}
            else:
                raw_edges = transitions[node]
                if not isinstance(raw_edges, list) or len(raw_edges) > MAX_OPTIONS ** 2:
                    raise ValueError("goal transition bound")
                edges = set()
                for edge in raw_edges:
                    if not isinstance(edge, dict) or set(edge) != {"source", "target"}:
                        raise ValueError("goal transition schema")
                    source, target = _profile(edge["source"]), _profile(edge["target"])
                    if source not in self.indices[node] or target not in self.indices[node]:
                        raise ValueError("goal transition outside catalog")
                    a, b = self.indices[node][source], self.indices[node][target]
                    if a != b:
                        edges.add((a, b))
            self.adjacency[node] = tuple(tuple(b for a, b in sorted(edges) if a == index)
                                         for index in range(count))
            self.transitions[node] = [{"source": list(self.domains[node][a]),
                                       "target": list(self.domains[node][b])}
                                      for a, b in sorted(edges)]
        self._edges = {}
        self._frontier_calls = 0
        self._frontier_search_states = 0
        self._phase_candidates = 0
        self._edge_budget_exhausted = False

    def _state(self, raw):
        if not isinstance(raw, dict) or sorted(raw) != self.nodes:
            raise ValueError("goal state placement")
        state = []
        for node in self.nodes:
            profile = _profile(raw[node])
            if profile not in self.indices[node]:
                raise ValueError("goal state outside catalog")
            state.append(self.indices[node][profile])
        return tuple(state)

    def _external_state(self, state):
        return {node: list(self.domains[node][state[index]])
                for index, node in enumerate(self.nodes)}

    def _safe(self, state):
        return compatible(self.branches, {node: set(self.domains[node][state[index]])
                                         for index, node in enumerate(self.nodes)})

    def _local_paths(self, node, start, box):
        terms = [set(term) for term in box[node]]
        allowed = {index for index, profile in enumerate(self.domains[node])
                   if any(term <= set(profile) for term in terms)}
        if start not in allowed:
            raise RuntimeError("goal frontier lost its current anchor")
        paths, queue = {start: (start,)}, deque([start])
        while queue:
            source = queue.popleft()
            for target in self.adjacency[node][source]:
                if target in allowed and target not in paths:
                    paths[target] = paths[source] + (target,)
                    queue.append(target)
        return paths

    def _expand(self, source):
        if source in self._edges:
            return self._edges[source], True
        if self._edge_budget_exhausted:
            raise GoalPlanningRefusal("goal phase-edge bound")
        current = self._external_state(source)
        self._frontier_calls += 1
        try:
            frontier = frontier_synthesize(self.branches, current, self.catalog,
                                           max_states=self.max_frontier_states)
        except ValueError as exc:
            if str(exc) in _FRONTIER_REFUSALS:
                raise GoalPlanningRefusal(str(exc)) from exc
            raise
        if not frontier_certificate(self.branches, current, self.catalog, frontier,
                                    combination_bound=self.max_frontier_states):
            raise RuntimeError("goal frontier certificate rejected")
        self._frontier_search_states += frontier["search"]["states"]
        best = {}
        for member in frontier["frontier"]:
            box = member["box"]
            local = [self._local_paths(node, source[index], box)
                     for index, node in enumerate(self.nodes)]
            for target in product(*(sorted(paths) for paths in local)):
                if target == source:
                    continue
                self._phase_candidates += 1
                if self._phase_candidates > self.max_phase_edges:
                    self._edge_budget_exhausted = True
                    raise GoalPlanningRefusal("goal phase-edge bound")
                if not self._safe(target):
                    raise RuntimeError("goal safe product reached an incompatible state")
                paths = tuple(local[index][target[index]] for index in range(len(self.nodes)))
                writes = sum(len(path) - 1 for path in paths)
                tie = (writes, _box_key(box, self.nodes), paths)
                if target in best and best[target][0] <= tie:
                    continue
                local_paths = {node: [list(self.domains[node][index]) for index in paths[pos]]
                               for pos, node in enumerate(self.nodes)}
                steps = [{"node": node, "support": list(self.domains[node][index])}
                         for pos, node in enumerate(self.nodes) for index in paths[pos][1:]]
                phase = {"source": current, "target": self._external_state(target),
                         "box": deepcopy(box), "local_paths": local_paths, "steps": steps}
                best[target] = (tie, phase)
        # No partially enumerated adjacency is cached after a refusal.
        edges = [(target, best[target][1]) for target in sorted(best)]
        self._edges[source] = edges
        return edges, False

    def statistics(self):
        return {"catalog_placements": self.placement_count,
                "cached_state_expansions": len(self._edges),
                "frontier_calls": self._frontier_calls,
                "frontier_search_states": self._frontier_search_states,
                "phase_candidates": self._phase_candidates,
                "phase_edge_budget_exhausted": self._edge_budget_exhausted}

    def plan(self, current, target):
        """Return an exact minimum-phase plan, or an explicit unreachable answer."""
        source, destination = self._state(current), self._state(target)
        if not self._safe(source):
            raise ValueError("goal initial placement incompatible")
        if self._edge_budget_exhausted:
            raise GoalPlanningRefusal("goal phase-edge bound")
        before = self.statistics()
        query = {"settled_states": 0, "new_state_expansions": 0,
                 "cached_state_expansions": 0, "incumbent_pruned_states": 0}
        base = {"schema": "rollout-goal-plan-v1", "branches": deepcopy(self.branches),
                "initial": self._external_state(source), "target": self._external_state(destination),
                "catalog": deepcopy(self.catalog), "transitions": deepcopy(self.transitions),
                "objective": ["fewest guard phases", "fewest installations"],
                "budgets": {"placements": self.max_placements, "phase_candidates": self.max_phase_edges,
                            "frontier_states_per_expansion": self.max_frontier_states},
                "scope": "fixed catalog and directed local transitions; exact bounded guard language; coordinated phase boundaries"}

        def finish(status, cost, phases, reason=None):
            after = self.statistics()
            answer = dict(base, status=status, cost=cost, phases=deepcopy(phases),
                          search={"query": dict(query), "before": before, "after": after})
            if reason is not None:
                answer["reason"] = reason
            return answer

        if not self._safe(destination):
            return finish("unreachable", None, [], "target incompatible")
        distances, previous = {source: (0, 0)}, {}
        queue = [(0, 0, source)]
        while queue:
            phases, writes, state = heappop(queue)
            if distances[state] != (phases, writes):
                continue
            query["settled_states"] += 1
            if state == destination:
                route = []
                while state != source:
                    state, phase = previous[state]
                    route.append(phase)
                route.reverse()
                return finish("planned", {"phases": phases, "installations": writes,
                                          "handoffs": max(phases - 1, 0)}, route)
            # Every remaining nonempty phase costs at least (1, 1). Once this
            # lower bound cannot improve the known target, synthesizing another
            # frontier at this state cannot affect the requested optimum.
            if destination in distances and (phases + 1, writes + 1) >= distances[destination]:
                query["incumbent_pruned_states"] += 1
                continue
            edges, cached = self._expand(state)
            query["cached_state_expansions" if cached else "new_state_expansions"] += 1
            for following, phase in edges:
                value = (phases + 1, writes + len(phase["steps"]))
                if following not in distances or value < distances[following]:
                    distances[following] = value
                    previous[following] = (state, phase)
                    heappush(queue, (*value, following))
        return finish("unreachable", None, [], "no safe permitted phase path")


def plan_goal(branches, current, candidates, target, transitions=None, *,
              max_placements=MAX_GOAL_PLACEMENTS,
              max_phase_edges=MAX_GOAL_PHASE_EDGES,
              max_frontier_states=MAX_FRONTIER_STATES):
    """One-shot wrapper; use ``GoalPlanner`` to reuse a fixed phase graph."""
    planner = GoalPlanner(branches, candidates, transitions,
                          max_placements=max_placements,
                          max_phase_edges=max_phase_edges,
                          max_frontier_states=max_frontier_states)
    return planner.plan(current, target)
