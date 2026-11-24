"""Exact phase planning for locally max-closed factors on directed chains.

Compatibility is a conjunction of small positive-DNF factors. Recognition
enumerates each factor's own physical catalog, never their global product.
For a max-closed relation, safe single-owner prefixes have a greatest joint
endpoint. Iterating those endpoints minimizes phases; directed chains fix the
number of installations. This module leaves the measured general planner and
owner protocol unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations_with_replacement, product
from math import prod
import re

from .controller import MAX_CONTRACTS, atoms
from .envelope import MAX_OPTIONS, antichain, normalize, verify_box


LIMITS = {
    "owners": 1024,
    "factors": 4096,
    "factor_placements": 4096,
    "total_factor_placements": 262144,
    "closure_pairs": 4000000,
    "steps": 8192,
}


class FactoredPlanningRefusal(ValueError):
    """The declared exact structural route cannot certify this input."""

    def __init__(self, reason, **witness):
        super().__init__(reason)
        self.reason = reason
        self.witness = deepcopy(witness)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _identifier(value, name):
    _require(isinstance(value, str) and
             re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value), name)
    return value


def _profile(raw):
    return tuple(atoms(raw, MAX_CONTRACTS))


def _budgets(raw):
    _require(set(raw) <= set(LIMITS), "unknown factored planning budget")
    result = dict(LIMITS)
    for name, value in raw.items():
        _require(type(value) is int and 1 <= value <= LIMITS[name],
                 "invalid factored planning budget: " + name)
        result[name] = value
    return result


class _Model:
    def __init__(self, factors, candidates, transitions, budgets):
        self.budgets = _budgets(budgets)
        _require(isinstance(candidates, dict) and candidates, "empty physical catalog")
        self.nodes = tuple(sorted(_identifier(n, "invalid physical owner") for n in candidates))
        if len(self.nodes) > self.budgets["owners"]:
            raise FactoredPlanningRefusal("factored owner budget", owners=len(self.nodes))
        _require(isinstance(transitions, dict) and set(transitions) == set(self.nodes),
                 "factored transition placement")
        self.domains, self.ranks, self.edges, self.transitions = {}, {}, {}, {}
        for node in self.nodes:
            raw = candidates[node]
            _require(isinstance(raw, list) and 1 <= len(raw) <= MAX_OPTIONS,
                     "factored catalog profile bound")
            profiles = tuple(sorted({_profile(p) for p in raw}))
            indices = {p: i for i, p in enumerate(profiles)}
            raw_edges = transitions[node]
            _require(isinstance(raw_edges, list) and len(raw_edges) <= MAX_OPTIONS ** 2,
                     "factored transition bound")
            edges = set()
            for edge in raw_edges:
                _require(isinstance(edge, dict) and set(edge) == {"source", "target"},
                         "factored transition schema")
                a, b = _profile(edge["source"]), _profile(edge["target"])
                _require(a in indices and b in indices, "transition outside physical catalog")
                if a != b:
                    edges.add((indices[a], indices[b]))
            incoming = [0] * len(profiles)
            outgoing = [[] for _ in profiles]
            for a, b in sorted(edges):
                incoming[b] += 1
                outgoing[a].append(b)
            roots = [i for i, count in enumerate(incoming) if count == 0]
            if (len(roots) != 1 or any(c > 1 for c in incoming)
                    or any(len(v) > 1 for v in outgoing)):
                raise FactoredPlanningRefusal("local graph is not a directed chain", owner=node)
            order, seen, current = [], set(), roots[0]
            while current not in seen:
                order.append(current)
                seen.add(current)
                if not outgoing[current]:
                    break
                current = outgoing[current][0]
            if len(order) != len(profiles) or outgoing[order[-1]]:
                raise FactoredPlanningRefusal("local graph is not a directed chain", owner=node)
            self.domains[node] = tuple(profiles[i] for i in order)
            self.ranks[node] = {p: i for i, p in enumerate(self.domains[node])}
            self.edges[node] = {(profiles[a], profiles[b]) for a, b in edges}
            self.transitions[node] = [
                {"source": list(self.domains[node][i]), "target": list(self.domains[node][i + 1])}
                for i in range(len(self.domains[node]) - 1)]
        _require(isinstance(factors, list) and factors, "nonempty factor list required")
        if len(factors) > self.budgets["factors"]:
            raise FactoredPlanningRefusal("factor count budget", factors=len(factors))
        self.factors, self.local, seen_ids, covered = [], {}, set(), set()
        self.relevant = {n: set() for n in self.nodes}
        self.incident = {n: [] for n in self.nodes}
        total = 0
        for raw in factors:
            _require(isinstance(raw, dict) and set(raw) == {"id", "branches"},
                     "factor schema")
            identity = _identifier(raw["id"], "invalid factor identity")
            _require(identity not in seen_ids, "duplicate factor identity")
            seen_ids.add(identity)
            branches = raw["branches"]
            _require(isinstance(branches, list) and branches and isinstance(branches[0], dict),
                     "factor branches")
            scope = tuple(sorted(branches[0]))
            _require(scope and set(scope) <= set(self.nodes), "factor outside physical catalog")
            _require(all(isinstance(b, dict) and tuple(sorted(b)) == scope for b in branches),
                     "factor placement mismatch")
            # All original logical-language checks operate in the local factor
            # namespace. Global transport identities are never truncated.
            aliases = {n: str(i) for i, n in enumerate(scope)}
            local = normalize([{aliases[n]: b[n] for n in scope} for b in branches])
            canonical = [{n: b[aliases[n]] for n in scope} for b in local]
            count = prod(len(self.domains[n]) for n in scope)
            if count > self.budgets["factor_placements"]:
                raise FactoredPlanningRefusal("local factor placement budget", factor=identity,
                                               placements=count)
            total += count
            if total > self.budgets["total_factor_placements"]:
                raise FactoredPlanningRefusal("total factor placement budget", placements=total)
            self.factors.append({"id": identity, "branches": canonical})
            self.local[identity] = (scope, aliases, local)
            covered.update(scope)
            for n in scope:
                self.incident[n].append(identity)
                self.relevant[n].update(a for b in canonical for a in b[n])
        _require(covered == set(self.nodes),
                 "every owner needs a factor; use an explicit unary true factor for an unconstrained owner")
        self.factors.sort(key=lambda f: f["id"])
        self.catalog = {n: [list(p) for p in self.domains[n]] for n in self.nodes}
        self.factor_placements = total
        self.positions = {n: i for i, n in enumerate(self.nodes)}

    def state(self, raw):
        _require(isinstance(raw, dict) and set(raw) == set(self.nodes), "factored state placement")
        result = []
        for n in self.nodes:
            p = _profile(raw[n])
            _require(p in self.ranks[n], "state outside physical catalog")
            result.append(self.ranks[n][p])
        return tuple(result)

    def external(self, ranks):
        return {n: list(self.domains[n][r]) for n, r in zip(self.nodes, ranks)}

    def factor_state(self, identity, state):
        return tuple(state[self.positions[n]] for n in self.local[identity][0])

    def truth(self, identity, state):
        scope, _, local = self.local[identity]
        return any(all(set(branch[str(i)]) <= set(self.domains[n][state[i]])
                       for i, n in enumerate(scope)) for branch in local)

    def safe(self, state):
        return all(self.truth(f["id"], self.factor_state(f["id"], state)) for f in self.factors)

    def check_box(self, box):
        _require(isinstance(box, dict) and set(box) == set(self.nodes), "factored box placement")
        canonical = {n: antichain(box[n]) for n in self.nodes}
        _require(canonical == box, "noncanonical factored guard")
        checks = []
        for factor in self.factors:
            identity = factor["id"]
            scope, aliases, branches = self.local[identity]
            relevant = {n: set(a for b in factor["branches"] for a in b[n]) for n in scope}
            projected = {aliases[n]: antichain([sorted(set(term) & relevant[n])
                                               for term in box[n]]) for n in scope}
            check = verify_box(branches, projected)
            _require(check["safe"], "unsafe guard for factor: " + identity)
            checks.append({"id": identity, "corners": check["corners"]})
        return checks


class FactoredChainPlanner:
    """Recognize local max-closure and construct an exact global phase plan.

    ``factors`` is a list of ``{'id': string, 'branches': positive_DNF}``.
    Each DNF has at most six owners and eight alternatives, with global owner
    names as dictionary keys. A physical owner's catalog is shared by all its
    factors. Directed edges, rather than textual version labels, define ranks.
    Every owner must appear in a factor; an explicit unary true factor admits
    an unconstrained owner. Only structural/resource refusal raises
    ``FactoredPlanningRefusal``. A certified unreachable goal is returned.
    """

    def __init__(self, factors, candidates, transitions, **budgets):
        _require(all(name.startswith("max_") for name in budgets),
                 "factored planner budgets use the max_ prefix")
        self.model = _Model(factors, candidates, transitions,
                            {name[4:]: value for name, value in budgets.items()})
        self.nodes = self.model.nodes
        self.relations, self.axis_limits = {}, {}
        certificates, pairs = [], 0
        for factor in self.model.factors:
            identity = factor["id"]
            scope = self.model.local[identity][0]
            shape = tuple(len(self.model.domains[n]) for n in scope)
            relation = {state for state in product(*(range(v) for v in shape))
                        if self.model.truth(identity, state)}
            required_pairs = len(relation) * (len(relation) + 1) // 2
            if pairs + required_pairs > self.model.budgets["closure_pairs"]:
                raise FactoredPlanningRefusal("max-closure pair budget", factor=identity,
                                               required=pairs + required_pairs)
            for a, b in combinations_with_replacement(sorted(relation), 2):
                joined = tuple(max(x, y) for x, y in zip(a, b))
                pairs += 1
                if joined not in relation:
                    raise FactoredPlanningRefusal("factor is not closed under componentwise maximum",
                                                   factor=identity, first=list(a), second=list(b),
                                                   maximum=list(joined))
            limits = {}
            for state in sorted(relation):
                row = []
                for i, size in enumerate(shape):
                    last = state[i]
                    for value in range(last + 1, size):
                        trial = state[:i] + (value,) + state[i + 1:]
                        if trial not in relation:
                            break
                        last = value
                    row.append(last)
                limits[state] = tuple(row)
            self.relations[identity], self.axis_limits[identity] = relation, limits
            certificates.append({"id": identity, "owners": list(scope), "shape": list(shape),
                "catalog_placements": prod(shape), "compatible_placements": len(relation),
                "checked_join_pairs": required_pairs,
                "relation": [list(s) for s in sorted(relation)],
                "axis_limits": [{"source": list(s), "upper": list(limits[s])}
                                for s in sorted(relation)]})
        self._recognition = {"recognized": True, "criterion": "factorwise componentwise-maximum closure",
            "owners": len(self.nodes), "factors": certificates,
            "checked_factor_placements": self.model.factor_placements,
            "checked_join_pairs": pairs, "global_catalog_enumerated": False}

    def recognition(self):
        return deepcopy(self._recognition)

    def _phase(self, source, target):
        paths, box, steps = {}, {}, []
        for i, n in enumerate(self.nodes):
            paths[n] = [list(self.model.domains[n][rank])
                        for rank in range(source[i], target[i] + 1)]
            box[n] = antichain([sorted(set(p) & self.model.relevant[n]) for p in paths[n]])
            steps.extend({"node": n, "support": p} for p in paths[n][1:])
        return {"source": self.model.external(source), "target": self.model.external(target),
                "box": box, "local_paths": paths, "steps": steps,
                "factor_checks": self.model.check_box(box)}

    def plan(self, current, target):
        source, destination = self.model.state(current), self.model.state(target)
        _require(self.model.safe(source), "factored initial placement incompatible")
        base = {"schema": "factored-chain-plan", "factors": deepcopy(self.model.factors),
            "catalog": deepcopy(self.model.catalog), "transitions": deepcopy(self.model.transitions),
            "initial": self.model.external(source), "target": self.model.external(destination),
            "objective": ["fewest guard phases", "fewest installations"],
            "recognition": self.recognition(), "budgets": deepcopy(self.model.budgets)}
        phases, trace = [], [list(source)]

        def finish(status, reason=None):
            result = dict(base, status=status, phases=deepcopy(phases) if status == "planned" else [],
                cost={"phases": len(phases), "installations": sum(b - a for a, b in zip(source, destination)),
                      "handoffs": max(0, len(phases) - 1)} if status == "planned" else None,
                search={"rank_iterates": deepcopy(trace)})
            if reason:
                result["reason"] = reason
            return result

        if not self.model.safe(destination):
            return finish("unreachable", "target incompatible")
        if any(b < a for a, b in zip(source, destination)):
            return finish("unreachable", "target precedes source on a directed chain")
        writes = sum(b - a for a, b in zip(source, destination))
        if writes > self.model.budgets["steps"]:
            raise FactoredPlanningRefusal("factored installation budget", installations=writes)
        state = source
        while state != destination:
            following = list(destination)
            for factor in self.model.factors:
                identity = factor["id"]
                local = self.model.factor_state(identity, state)
                for n, upper in zip(self.model.local[identity][0], self.axis_limits[identity][local]):
                    i = self.model.positions[n]
                    following[i] = min(following[i], upper)
            following = tuple(following)
            _require(all(a <= b for a, b in zip(state, following)), "certified endpoint regressed")
            trace.append(list(following))
            if following == state:
                return finish("unreachable", "greatest safe endpoint is a fixed point before target")
            phases.append(self._phase(state, following))
            state = following
        return finish("planned")


def validate_factored_plan(plan):
    """Check a complete safe execution witness before creation or recovery.

    This checks every declared factor, positive guard, full-profile edge, phase
    endpoint and cost. It does not rely on a claimed closure certificate or on
    planner code paths to establish execution safety. Minimum-phase optimality
    is checked separately by the independent finite study oracle.
    """
    _require(isinstance(plan, dict) and plan.get("schema") == "factored-chain-plan",
             "factored plan schema")
    _require(plan.get("status") == "planned", "only a planned witness can execute")
    _require(plan.get("objective") == ["fewest guard phases", "fewest installations"],
             "factored plan objective")
    model = _Model(plan["factors"], plan["catalog"], plan["transitions"], plan.get("budgets", {}))
    source, target = model.state(plan["initial"]), model.state(plan["target"])
    _require(model.safe(source) and model.safe(target), "incompatible plan endpoint")
    phases = plan.get("phases")
    _require(isinstance(phases, list) and len(phases) <= model.budgets["steps"], "factored phase bound")
    previous, writes, corners = model.external(source), 0, 0
    for phase in phases:
        _require(isinstance(phase, dict) and phase.get("source") == previous, "phase continuity")
        begin, end = model.state(phase["source"]), model.state(phase["target"])
        _require(all(a <= b for a, b in zip(begin, end)) and begin != end, "nonproductive or reversed phase")
        checks = model.check_box(phase["box"])
        _require(phase.get("factor_checks") == checks, "factor guard check record differs")
        corners += sum(c["corners"] for c in checks)
        paths = phase.get("local_paths")
        _require(isinstance(paths, dict) and set(paths) == set(model.nodes), "local path placement")
        for i, n in enumerate(model.nodes):
            expected = [list(model.domains[n][r]) for r in range(begin[i], end[i] + 1)]
            _require(paths[n] == expected, "local path differs from directed physical chain")
            _require(all(any(set(term) <= set(p) for term in phase["box"][n]) for p in paths[n]),
                     "guard excludes a local path profile")
        steps = phase.get("steps")
        _require(isinstance(steps, list) and steps, "empty phase installation sequence")
        actual, cursors = deepcopy(previous), {n: 0 for n in model.nodes}
        for step in steps:
            _require(isinstance(step, dict) and set(step) == {"node", "support"}, "installation step schema")
            n = step["node"]
            _require(n in cursors, "installation names an unknown owner")
            next_index = cursors[n] + 1
            _require(next_index < len(paths[n]) and step["support"] == paths[n][next_index],
                     "installation does not follow its physical path")
            _require((_profile(actual[n]), _profile(step["support"])) in model.edges[n],
                     "installation is not a permitted edge")
            actual[n], cursors[n] = deepcopy(step["support"]), next_index
            writes += 1
            _require(writes <= model.budgets["steps"], "factored installation bound")
        _require(actual == phase["target"] and
                 all(cursors[n] == len(paths[n]) - 1 for n in model.nodes), "phase target not reached")
        previous = deepcopy(actual)
    _require(previous == model.external(target), "plan target not reached")
    expected = {"phases": len(phases), "installations": writes, "handoffs": max(0, len(phases) - 1)}
    _require(plan.get("cost") == expected and all(type(v) is int for v in plan["cost"].values()),
             "factored plan cost mismatch")
    return {"safe": True, "owners": len(model.nodes), "factors": len(model.factors),
            "phases": len(phases), "installations": writes, "factor_corner_checks": corners}
