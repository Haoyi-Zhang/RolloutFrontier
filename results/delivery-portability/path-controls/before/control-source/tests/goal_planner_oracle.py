"""Literal finite-product oracle for goal planning, independent of guard search.

The oracle enumerates every nonempty profile subset product and tests membership
in a supplied finite relation. It does not call the production corner test,
frontier routine, local-path routine or phase-graph expansion.
"""
from collections import deque
from heapq import heappop, heappush
from itertools import product


def relation_inputs(shape, relation):
    """Encode each last-coordinate slice as one positive branch."""
    relation = set(relation)
    if not relation:
        raise ValueError("oracle needs a nonempty relation")
    if len(shape) == 2:
        rows = sorted({point[0] for point in relation})
        branches = [{"0": [f"row_{row}"], "1": [f"column_for_{row}"]} for row in rows]
        catalog = {
            "0": [[f"identity_0_{row}", f"row_{row}"] for row in range(shape[0])],
            "1": [[f"identity_1_{column}",
                   *(f"column_for_{row}" for row in rows if (row, column) in relation)]
                  for column in range(shape[1])],
        }
    else:
        prefixes = sorted({point[:-1] for point in relation})
        last = len(shape) - 1
        branches = [{**{str(owner): [f"coordinate_{owner}_{value}"]
                         for owner, value in enumerate(prefix)},
                     str(last): [f"tail_for_{index}"]}
                    for index, prefix in enumerate(prefixes)]
        catalog = {str(owner): [[f"identity_{owner}_{value}", f"coordinate_{owner}_{value}"]
                               for value in range(size)] for owner, size in enumerate(shape[:-1])}
        catalog[str(last)] = [[f"identity_{last}_{value}",
                              *(f"tail_for_{index}" for index, prefix in enumerate(prefixes)
                                if prefix + (value,) in relation)]
                             for value in range(shape[-1])]
    catalog = {node: [sorted(profile) for profile in profiles] for node, profiles in catalog.items()}
    return branches, catalog


def support_state(catalog, state):
    return {str(owner): catalog[str(owner)][value] for owner, value in enumerate(state)}


def support_transitions(catalog, graphs):
    return {str(owner): [{"source": catalog[str(owner)][source],
                          "target": catalog[str(owner)][target]}
                         for source, target in sorted(edges)]
            for owner, edges in enumerate(graphs)}


def all_safe_products(shape, relation):
    choices = [[tuple(index for index in range(size) if mask & (1 << index))
                for mask in range(1, 1 << size)] for size in shape]
    return [box for box in product(*choices)
            if all(point in relation for point in product(*box))]


def literal_phase_graph(shape, relation, graphs):
    safe = all_safe_products(shape, relation)
    result = {state: {} for state in relation}
    for state in sorted(relation):
        for box in safe:
            if any(value not in box[owner] for owner, value in enumerate(state)):
                continue
            distances = []
            for owner, start in enumerate(state):
                lengths, queue = {start: 0}, deque([start])
                while queue:
                    current = queue.popleft()
                    for source, target in sorted(graphs[owner]):
                        if source == current and target in box[owner] and target not in lengths:
                            lengths[target] = lengths[current] + 1
                            queue.append(target)
                distances.append(lengths)
            for target in product(*(sorted(values) for values in distances)):
                if target == state:
                    continue
                writes = sum(distances[owner][value] for owner, value in enumerate(target))
                result[state][target] = min(writes, result[state].get(target, writes))
    return result, len(safe)


def literal_shortest(graph, source, target):
    distances, queue = {source: (0, 0)}, [(0, 0, source)]
    while queue:
        phases, writes, state = heappop(queue)
        if distances[state] != (phases, writes):
            continue
        if state == target:
            return phases, writes
        for following, cost in sorted(graph[state].items()):
            value = phases + 1, writes + cost
            if following not in distances or value < distances[following]:
                distances[following] = value
                heappush(queue, (*value, following))
    return None


def centralized_reachable(relation, graphs, source):
    reached, queue = {source}, deque([source])
    while queue:
        state = queue.popleft()
        for owner, edges in enumerate(graphs):
            for start, target in edges:
                following = state[:owner] + (target,) + state[owner + 1:]
                if start == state[owner] and following in relation and following not in reached:
                    reached.add(following)
                    queue.append(following)
    return reached


def validate_plan(plan):
    """Check an emitted witness literally, without a production guard checker."""
    if plan["status"] != "planned":
        raise ValueError("not a planned witness")
    nodes = sorted(plan["initial"])
    state = {node: list(plan["initial"][node]) for node in nodes}
    allowed_edges = {node: {(tuple(edge["source"]), tuple(edge["target"]))
                           for edge in plan["transitions"][node]} for node in nodes}
    writes = 0
    for phase in plan["phases"]:
        if phase["source"] != state or not phase["steps"]:
            raise ValueError("phase source or progress")
        for corner in product(*(phase["box"][node] for node in nodes)):
            if not any(all(set(branch[node]) <= set(corner[index])
                           for index, node in enumerate(nodes)) for branch in plan["branches"]):
                raise ValueError("unsafe positive corner")
        expected_steps = []
        for node in nodes:
            path = phase["local_paths"][node]
            if path[0] != phase["source"][node] or path[-1] != phase["target"][node]:
                raise ValueError("local endpoint")
            for profile in path:
                if profile not in plan["catalog"][node]:
                    raise ValueError("local profile outside catalog")
                if not any(set(term) <= set(profile) for term in phase["box"][node]):
                    raise ValueError("local profile rejected")
            for source, target in zip(path, path[1:]):
                if source == target or (tuple(source), tuple(target)) not in allowed_edges[node]:
                    raise ValueError("unpermitted installation")
                expected_steps.append({"node": node, "support": target})
        if expected_steps != phase["steps"]:
            raise ValueError("phase step ordering")
        for step in phase["steps"]:
            state[step["node"]] = list(step["support"])
            writes += 1
            if not any(all(set(branch[node]) <= set(state[node]) for node in nodes)
                       for branch in plan["branches"]):
                raise ValueError("incompatible executed state")
        if state != phase["target"]:
            raise ValueError("phase final state")
    if state != plan["target"]:
        raise ValueError("rollout target not reached")
    expected_cost = {"phases": len(plan["phases"]), "installations": writes,
                     "handoffs": max(len(plan["phases"]) - 1, 0)}
    if plan["cost"] != expected_cost:
        raise ValueError("goal cost")
    return True
