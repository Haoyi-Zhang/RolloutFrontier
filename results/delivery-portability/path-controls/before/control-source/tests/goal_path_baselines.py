"""Executable same-target controls for the declared integer version policy.

This module does not call the production planner, frontier compiler, or checker.
Every route emits the rollout-goal-plan-v1 schema consumed by RolloutCoordinator.
The interval route is policy specific; the literal-products route enumerates
physical catalog products and is restricted to a declared finite product bound.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from itertools import product


ROUTES = ('one-step', 'shortest-path-segmented', 'interval-optimal',
          'literal-products-optimal')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def policy_safe(vector, servers):
    low, high = min(vector[:servers]), max(vector[:servers])
    return high - low <= 1 and all(high - 3 <= v <= low for v in vector[servers:])


def interval_safe(source, target, servers):
    """Exact independent-coordinate hull predicate for +1 local transitions."""
    if any(a > b for a, b in zip(source, target)):
        return False
    return (all(target[i] - source[j] <= 1
                for i in range(servers) for j in range(servers) if i != j)
            and all(target[j] <= min(source[:servers])
                    and source[j] >= max(target[:servers]) - 3
                    for j in range(servers, len(source))))


def shortest_segment_partition(path, valid):
    """Dynamic program over every contiguous subpath; first optimum breaks ties."""
    if not path:
        return [], 0
    distance, predecessor, checked = [0] + [len(path)] * (len(path) - 1), {}, 0
    for right in range(1, len(path)):
        for left in range(right):
            checked += 1
            if valid(left, right) and distance[left] + 1 < distance[right]:
                distance[right], predecessor[right] = distance[left] + 1, left
    require(distance[-1] < len(path), 'No valid segmentation of a safe edge path')
    cuts, right = [], len(path) - 1
    while right:
        left = predecessor[right]
        cuts.append((left, right))
        right = left
    return list(reversed(cuts)), checked


class PolicyGoalBaselines:
    """One route per instance: preparation and caches belong to that route."""

    def __init__(self, domain, route='shortest-path-segmented', *, max_products=2000):
        require(route in ROUTES, 'Unknown route')
        self.domain, self.route = deepcopy(domain), route
        spec = domain['specification']
        self.servers = spec['server_owners']
        self.nodes = [str(i) for i in range(spec['server_owners'] + spec['client_owners'])]
        self.values = [tuple(sorted(map(int, domain['profiles'][node]))) for node in self.nodes]
        self.vertices = tuple(v for v in product(*self.values) if policy_safe(v, self.servers))
        require([list(v) for v in self.vertices] == domain['compatible_placements'],
                'Policy and declared finite relation differ')
        self.allowed = set(self.vertices)
        self.work = {'catalog_cells': 1, 'compatible_vertices': len(self.vertices),
                     'safe_edge_candidates': 0, 'safe_edges': 0,
                     'interval_pair_candidates': 0, 'profile_products': 0,
                     'safe_profile_products': 0, 'product_corner_tests': 0,
                     'phase_edge_candidates': 0, 'unique_phase_edges': 0,
                     'queries': 0, 'source_searches': 0, 'search_edge_visits': 0,
                     'segment_candidates': 0}
        for values in self.values:
            self.work['catalog_cells'] *= len(values)
        self.graph = {v: {} for v in self.vertices}
        self.parents = {}
        if route in ('one-step', 'shortest-path-segmented'):
            for source in self.vertices:
                for owner in range(len(self.nodes)):
                    self.work['safe_edge_candidates'] += 1
                    target = source[:owner] + (source[owner] + 1,) + source[owner + 1:]
                    if target in self.allowed:
                        self.graph[source][target] = 1
                        self.work['safe_edges'] += 1
        elif route == 'interval-optimal':
            for source in self.vertices:
                for target in self.vertices:
                    if source == target:
                        continue
                    self.work['interval_pair_candidates'] += 1
                    if interval_safe(source, target, self.servers):
                        self.graph[source][target] = sum(b - a for a, b in zip(source, target))
                        self.work['phase_edge_candidates'] += 1
        else:
            libraries = [[tuple(values[j] for j in range(len(values)) if mask >> j & 1)
                          for mask in range(1, 1 << len(values))] for values in self.values]
            count = 1
            for library in libraries:
                count *= len(library)
            require(count <= max_products, 'Literal physical-product budget')
            for box in product(*libraries):
                self.work['profile_products'] += 1
                safe = True
                for cell in product(*box):
                    self.work['product_corner_tests'] += 1
                    if cell not in self.allowed:
                        safe = False
                        break
                if not safe:
                    continue
                self.work['safe_profile_products'] += 1
                for source in product(*box):
                    reachable = []
                    for start, values in zip(source, box):
                        local, value = [start], start + 1
                        while value in values:
                            local.append(value)
                            value += 1
                        reachable.append(local)
                    for target in product(*reachable):
                        if target == source:
                            continue
                        self.work['phase_edge_candidates'] += 1
                        self.graph[source][target] = sum(b - a for a, b in zip(source, target))
        self.work['unique_phase_edges'] = sum(map(len, self.graph.values()))

    def stats(self):
        return deepcopy(self.work)

    def _path(self, source, target):
        # All directed +1 paths between these endpoints have the same write
        # count; breadth-first phase distance therefore minimizes (k, W).
        if source not in self.parents:
            parents, queue = {source: None}, deque([source])
            while queue:
                current = queue.popleft()
                for following in self.graph[current]:
                    self.work['search_edge_visits'] += 1
                    if following not in parents:
                        parents[following] = current
                        queue.append(following)
            self.parents[source] = parents
            self.work['source_searches'] += 1
        parents = self.parents[source]
        if target not in parents:
            return []
        path, current = [], target
        while current is not None:
            path.append(current)
            current = parents[current]
        return list(reversed(path))

    def _support(self, vector):
        return {node: list(self.domain['profiles'][node][str(vector[i])])
                for i, node in enumerate(self.nodes)}

    def _phase(self, path):
        local = {node: [self._support(path[0])[node]] for node in self.nodes}
        steps = []
        for before, after in zip(path, path[1:]):
            changed = [i for i in range(len(self.nodes)) if before[i] != after[i]]
            require(len(changed) == 1 and after[changed[0]] == before[changed[0]] + 1,
                    'Baseline phase contains an undeclared edge')
            owner = changed[0]
            node = self.nodes[owner]
            profile = list(self.domain['profiles'][node][str(after[owner])])
            local[node].append(profile)
            steps.append({'node': node, 'support': profile})
        box = {}
        for node in self.nodes:
            relevant = set().union(*(set(branch[node]) for branch in self.domain['branches']))
            terms = {tuple(sorted(set(profile) & relevant)) for profile in local[node]}
            box[node] = sorted([list(term) for term in terms
                                if not any(set(other) < set(term) for other in terms)])
        return {'source': self._support(path[0]), 'target': self._support(path[-1]),
                'box': box, 'local_paths': local, 'steps': steps}

    def plan(self, initial_versions, target_versions):
        source, target = tuple(initial_versions), tuple(target_versions)
        require(source in self.allowed and target in self.allowed, 'Task endpoint outside policy')
        self.work['queries'] += 1
        before = self.stats()
        path = self._path(source, target)
        phases, cuts, write_path = [], [], path
        if path and self.route in ('one-step', 'shortest-path-segmented'):
            if self.route == 'one-step':
                cuts = [(i, i + 1) for i in range(len(path) - 1)]
            else:
                cuts, checked = shortest_segment_partition(
                    path, lambda left, right: interval_safe(path[left], path[right], self.servers))
                self.work['segment_candidates'] += checked
            phases = [self._phase(path[left:right + 1]) for left, right in cuts]
        elif path:
            write_path = [source]
            for start, end in zip(path, path[1:]):
                local_path, current = [start], list(start)
                for owner in range(len(current)):
                    while current[owner] < end[owner]:
                        current[owner] += 1
                        local_path.append(tuple(current))
                cuts.append((len(write_path) - 1, len(write_path) + len(local_path) - 2))
                write_path.extend(local_path[1:])
                phases.append(self._phase(local_path))
        exact = self.route in ('interval-optimal', 'literal-products-optimal')
        return {'schema': 'rollout-goal-plan-v1', 'branches': deepcopy(self.domain['branches']),
                'initial': self._support(source), 'target': self._support(target),
                'catalog': deepcopy(self.domain['candidates']),
                'transitions': deepcopy(self.domain['transitions']),
                'objective': ['fewest guard phases', 'fewest installations'] if exact else
                             ['fewest installations', 'fewest phases on the selected path']
                             if self.route == 'shortest-path-segmented' else
                             ['fewest installations', 'one guard phase per installation'],
                'scope': 'declared finite version policy and +1 local transitions',
                'status': 'planned' if path else 'unreachable',
                'cost': {'phases': len(phases), 'installations': len(write_path) - 1,
                         'handoffs': max(len(phases) - 1, 0)} if path else None,
                'phases': phases,
                'baseline': {'route': self.route, 'globally_phase_optimal': exact,
                             'version_path': [list(v) for v in write_path],
                             'phase_cuts': [list(cut) for cut in cuts]},
                'search': {'before': before, 'after': self.stats()}}


def policy_plan(domain, initial_versions, target_versions, route='shortest-path-segmented'):
    return PolicyGoalBaselines(domain, route).plan(initial_versions, target_versions)


def policy_baselines(domain, initial_versions, target_versions):
    routes = ROUTES if domain['name'] == 'boundary-three-owner' else ROUTES[:-1]
    return {route: policy_plan(domain, initial_versions, target_versions, route) for route in routes}
