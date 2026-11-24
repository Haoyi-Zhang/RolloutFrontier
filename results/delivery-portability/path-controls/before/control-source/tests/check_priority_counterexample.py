"""Produce or independently check one declared algebraic path counterexample.

The check route imports only standard-library code and independent finite
oracles. It reconstructs the relation, every safe interval phase, both priority
orders under two path rules, and the optimal partition of each resulting path.
The producer consults the unchanged production planner only after that result.
This is an existence witness, not workload-frequency or timing evidence.
"""
from __future__ import annotations

import argparse
from collections import deque
from copy import deepcopy
import hashlib
from itertools import permutations, product
import json
from pathlib import Path
import platform
import sys

from tests.factored_planning_oracle import Oracle, require
from tests.goal_planner_oracle import relation_inputs, support_state, support_transitions

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    'src/controller.py', 'src/envelope.py', 'src/factored_planner.py',
    'tests/goal_planner_oracle.py', 'tests/factored_planning_oracle.py',
    'tests/check_priority_counterexample.py',
)
SCOPE = 'Declared algebraic counterexample; no workload-frequency or timing claim'
SHAPE = (5, 7)
SOURCE = (0, 0)
TARGET = (4, 6)
# Each row means: rank[if_owner] >= if_rank implies rank[then_owner] >= then_rank.
THRESHOLDS = (
    (0, 3, 1, 1),
    (0, 4, 1, 4),
    (1, 5, 0, 1),
    (1, 6, 0, 2),
)


def specification():
    return {'shape': list(SHAPE), 'source': list(SOURCE), 'target': list(TARGET),
            'thresholds': [{'if_owner': i, 'if_rank': a, 'then_owner': j, 'then_rank': b}
                           for i, a, j, b in THRESHOLDS],
            'local_edges': [[[r, r + 1] for r in range(q - 1)] for q in SHAPE]}


def relation_for(spec):
    return {point for point in product(*(range(q) for q in spec['shape']))
            if all(point[c['if_owner']] < c['if_rank'] or
                   point[c['then_owner']] >= c['then_rank'] for c in spec['thresholds'])}


def rectangle(relation, source, target):
    return (all(a <= b for a, b in zip(source, target)) and
            all(point in relation for point in product(*(range(a, b + 1)
                                                         for a, b in zip(source, target)))))


def priority_path(relation, priority, stage_aware):
    current, points = SOURCE, [SOURCE]
    while current != TARGET:
        ready = []
        for owner in priority:
            if current[owner] < TARGET[owner]:
                following = tuple(value + (i == owner) for i, value in enumerate(current))
                if following in relation:
                    ready.append((owner, following))
        require(ready, 'priority path unexpectedly deadlocked')
        if stage_aware:
            ready.sort(key=lambda item: (current[item[0]], priority.index(item[0])))
        current = ready[0][1]
        points.append(current)
    return points


def partition(relation, points):
    distance = [0] + [len(points)] * (len(points) - 1)
    cuts = [[] for _ in points]
    for right in range(1, len(points)):
        for left in range(right):
            if rectangle(relation, points[left], points[right]) and distance[left] + 1 < distance[right]:
                distance[right] = distance[left] + 1
                cuts[right] = cuts[left] + [right]
    require(distance[-1] < len(points), 'safe physical path has no phase partition')
    return {'phases': distance[-1], 'cut_indices': cuts[-1],
            'endpoints': [list(points[0])] + [list(points[i]) for i in cuts[-1]]}


def literal_observation(spec):
    require(spec == specification(), 'declared threshold specification changed')
    relation = relation_for(spec)
    for first, second in product(relation, repeat=2):
        require(tuple(map(max, first, second)) in relation, 'relation is not maximum closed')
    graph = {source: [target for target in sorted(relation)
                      if target != source and rectangle(relation, source, target)]
             for source in sorted(relation)}
    distances, queue = {SOURCE: 0}, deque([SOURCE])
    while queue:
        current = queue.popleft()
        for following in graph[current]:
            if following not in distances:
                distances[following] = distances[current] + 1
                queue.append(following)
    handoffs = [list(point) for point in sorted(relation)
                if rectangle(relation, SOURCE, point) and rectangle(relation, point, TARGET)]
    paths = []
    for stage_aware in (False, True):
        for priority in permutations(range(len(SHAPE))):
            points = priority_path(relation, priority, stage_aware)
            require(len(points) - 1 == sum(TARGET), 'priority path installation count differs')
            paths.append({'strategy': 'stage-priority' if stage_aware else 'fixed-priority',
                          'priority': list(priority), 'path': [list(p) for p in points],
                          **partition(relation, points)})
    require(distances[TARGET] == 2 and handoffs == [[2, 4]], 'literal optimum or unique handoff differs')
    require(len(paths) == 4 and all(p['phases'] == 3 for p in paths), 'portfolio phase cost differs')
    return {'specification': deepcopy(spec), 'relation': [list(p) for p in sorted(relation)],
            'relation_cells': len(relation), 'max_closed': True,
            'phase_graph': [{'source': list(source), 'targets': [list(t) for t in targets]}
                            for source, targets in graph.items()],
            'reachable_phase_distances': [{'state': list(s), 'phases': distances[s]}
                                          for s in sorted(distances)],
            'exact_phase_count': distances[TARGET], 'two_phase_handoffs': handoffs,
            'paths': paths}


def physical_model(relation):
    branches, catalog = relation_inputs(SHAPE, relation)
    transitions = support_transitions(catalog, [{(r, r + 1) for r in range(q - 1)} for q in SHAPE])
    return {'factors': [{'id': 'threshold-dependencies', 'branches': branches}],
            'catalog': catalog, 'transitions': transitions,
            'initial': support_state(catalog, SOURCE), 'target': support_state(catalog, TARGET)}


def semantic_check(observation, model, plan):
    expected = literal_observation(observation['specification'])
    require(observation == expected, 'retained literal phase or priority-path observation changed')
    relation = {tuple(p) for p in expected['relation']}
    require(model == physical_model(relation), 'positive physical encoding differs from threshold relation')
    require(all(plan[field] == model[field] for field in model), 'production plan model changed')
    oracle = Oracle(model['factors'], model['catalog'], model['transitions'])
    require(oracle.local_relations['threshold-dependencies'] == relation,
            'physical model changed the algebraic relation')
    oracle.check_recognition(plan['recognition'])
    oracle.check_plan(plan, SOURCE, TARGET)
    require(plan['search']['rank_iterates'] == [[0, 0], [2, 4], [4, 6]], 'production handoff differs')
    return {'status': 'PASS', 'scope': SCOPE, 'shape': list(SHAPE),
            'source': list(SOURCE), 'target': list(TARGET),
            'relation_cells': len(relation), 'max_closed': True,
            'safe_phase_edges': sum(len(row['targets']) for row in expected['phase_graph']),
            'exact_phase_count': expected['exact_phase_count'],
            'unique_two_phase_handoff': expected['two_phase_handoffs'][0],
            'portfolio_paths': len(expected['paths']),
            'portfolio_phase_counts': [row['phases'] for row in expected['paths']],
            'installations_per_path': sum(TARGET),
            'production_cost': deepcopy(plan['cost']),
            'production_rank_trace': deepcopy(plan['search']['rank_iterates'])}


def negative_controls(observation, model, plan):
    results = []

    def rejects(name, changed_observation, changed_plan):
        try:
            semantic_check(changed_observation, model, changed_plan)
        except (ValueError, KeyError, TypeError, IndexError):
            results.append({'name': name, 'rejected': True})
        else:
            raise ValueError('failed semantic corruption control: ' + name)

    changed = deepcopy(plan)
    changed['cost']['phases'] = 3
    rejects('changed production phase cost', observation, changed)
    changed = deepcopy(observation)
    changed['two_phase_handoffs'] = [[2, 3]]
    rejects('changed unique two-phase handoff', changed, plan)
    changed = deepcopy(observation)
    changed['paths'][0]['path'][3] = [3, 0]
    rejects('unsafe priority-path state', changed, plan)
    changed = deepcopy(observation)
    changed['specification']['thresholds'][0]['then_rank'] = 2
    rejects('changed declared threshold', changed, plan)
    return results


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def check(directory, corruption_controls=False):
    environment = read(directory / 'environment.json')
    require(set(environment['sources']) == set(SOURCE_NAMES), 'executed source inventory differs')
    for name, expected in environment['sources'].items():
        require(digest(ROOT / name) == expected, 'current source differs: ' + name)
        require(digest(directory / 'sources' / name) == expected, 'captured source differs: ' + name)
    observation = read(directory / 'observation.json')
    model = read(directory / 'model.json')
    plan = read(directory / 'production-plan.json')
    result = semantic_check(observation, model, plan)
    require(result == read(directory / 'summary.json'), 'retained summary differs from reconstruction')
    require(set(environment['data_files']) == {'observation.json', 'model.json', 'production-plan.json',
                                               'summary.json', 'checker-controls.json'}, 'data binding inventory differs')
    for name, expected in environment['data_files'].items():
        require(digest(directory / name) == expected, 'retained data bytes differ: ' + name)
    if corruption_controls:
        controls = negative_controls(observation, model, plan)
        require(controls == read(directory / 'checker-controls.json'), 'corruption-control inventory differs')
        result['corruption_controls'] = controls
    result['source_files'] = len(SOURCE_NAMES)
    return result


def produce(directory):
    sources = {name: (ROOT / name).read_bytes() for name in SOURCE_NAMES}
    observation = literal_observation(specification())
    model = physical_model({tuple(p) for p in observation['relation']})
    # No production module is imported until the independent phase/path result exists.
    from src.factored_planner import FactoredChainPlanner
    plan = FactoredChainPlanner(model['factors'], model['catalog'], model['transitions']).plan(
        model['initial'], model['target'])
    result = semantic_check(observation, model, plan)
    controls = negative_controls(observation, model, plan)
    require(sources == {name: (ROOT / name).read_bytes() for name in SOURCE_NAMES}, 'executed source changed')
    directory.mkdir(parents=True, exist_ok=False)
    data = {'observation.json': observation, 'model.json': model, 'production-plan.json': plan,
            'summary.json': result, 'checker-controls.json': controls}
    for name, value in data.items():
        (directory / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    for name, content in sources.items():
        target = directory / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    environment = {'scope': SCOPE, 'python': sys.version, 'optimized': sys.flags.optimize,
                   'implementation': platform.python_implementation(),
                   'sources': {name: hashlib.sha256(content).hexdigest() for name, content in sources.items()},
                   'data_files': {name: digest(directory / name) for name in data}}
    (directory / 'environment.json').write_text(json.dumps(environment, indent=2, sort_keys=True) + '\n')
    (directory / 'README.md').write_text('''# Declared priority-path counterexample

This finite algebraic example establishes that combining the two fixed owner
priorities with the two minimum-current-rank priority paths does not solve
every max-closed chain instance. It is an existence witness, with no workload
frequency or timing claim.

The domains are ranks 0 through 4 and 0 through 6. Four implications define
compatibility: a >= 3 implies b >= 1; a >= 4 implies b >= 4; b >= 5 implies
a >= 1; b >= 6 implies a >= 2. Of 35 rank pairs, 27 are compatible. Independent
enumeration of every safe interval phase gives a two-phase optimum from (0,0)
to (4,6), with the unique intermediate endpoint (2,4). Each of the four declared
priority paths needs three phases even after exact optimal path partitioning.
Every compared path uses ten one-rank installations.

`observation.json` retains the complete relation, phase graph, phase distances,
all four paths and their optimal partitions. `model.json` retains the positive
manifest encoding and complete physical catalogs and edges. The unchanged
production planner's full witness is in `production-plan.json`. The checker
reconstructs these observations and validates that witness without importing
the production planner, controller, runtime or positive guard checker.

Run from the artifact directory:

```bash
python -B -m tests.check_priority_counterexample --check results/priority-counterexample --corruption-controls
python -O -B -m tests.check_priority_counterexample --check results/priority-counterexample --corruption-controls
python -B -m tests.check_priority_counterexample --out results/priority-counterexample-reproduction
```

Four semantic corruption controls alter the production cost, intermediate
endpoint, priority path and declared threshold. Captured sources and consumed
data are bound in `environment.json`; the checker checks both retained and
current source bytes. Fresh production requires a new output directory.
''')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--out', type=Path)
    operation.add_argument('--check', type=Path)
    parser.add_argument('--corruption-controls', action='store_true',
                        help='Run the four semantic evidence-corruption controls while checking.')
    args = parser.parse_args()
    if args.out is not None:
        result = produce(args.out)
    else:
        require(not any(name == 'src' or name.startswith('src.') for name in sys.modules),
                'check route imported a production module')
        result = check(args.check, args.corruption_controls)
        require(not any(name == 'src' or name.startswith('src.') for name in sys.modules),
                'check route imported a production module')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
