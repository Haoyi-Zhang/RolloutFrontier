"""Actual ProtoJSON contract probes and complete three-owner topology census.

The topology corpus is all nonempty directed simple graphs on three labelled
owners. These are registered graph instances derived from measured library
contracts, not a sample of production deployments. Both ties and phase gaps
against every fixed owner-priority path are retained.
"""
from __future__ import annotations
import argparse
from collections import deque
from copy import deepcopy
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = ['src/schema_contracts.py', 'src/factored_planner.py',
                'src/envelope.py', 'src/controller.py', 'src/checker.py', 'src/goal_planner.py',
                'tests/schema_contract_study.py']


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def context(family, graph_mask):
    edges = [edge for bit, edge in enumerate(itertools.permutations(range(3), 2)) if graph_mask >> bit & 1]
    profiles = family['profiles']
    candidates = {str(i): deepcopy(profiles) for i in range(3)}
    transitions = {str(i): [{'source': deepcopy(a), 'target': deepcopy(b)} for a, b in zip(profiles, profiles[1:])]
                   for i in range(3)}
    factors = [{'id': 'link-' + str(u) + '-' + str(v),
                'branches': [{str(u): ['emit:' + cls], str(v): ['accept:' + cls]}
                             for cls in family['classes']]} for u, v in edges]
    used = {i for edge in edges for i in edge}
    factors.extend({'id': 'isolated-' + str(i), 'branches': [{str(i): []}]}
                   for i in range(3) if i not in used)
    return {'id': family['family'] + '-graph-' + str(graph_mask), 'family': family['family'],
            'graph_mask': graph_mask, 'edges': [list(e) for e in edges],
            'candidates': candidates, 'transitions': transitions, 'factors': factors}


def valid_states(relation, edges):
    return [state for state in itertools.product(range(len(relation)), repeat=3)
            if all(relation[state[u]][state[v]] for u, v in edges)]


def priority_paths(start, allowed, order):
    todo = deque([start]); paths = {start: [start]}
    while todo:
        current = todo.popleft()
        for owner in order:
            endpoint = tuple(value + (i == owner) for i, value in enumerate(current))
            if endpoint in allowed and endpoint not in paths:
                paths[endpoint] = paths[current] + [endpoint]
                todo.append(endpoint)
    return paths


def box_safe(source, target, relation, edges):
    return all(relation[a][b] for u, v in edges
               for a in range(source[u], target[u] + 1)
               for b in range(source[v], target[v] + 1))


def partition_path(path, relation, edges):
    cost = [0] + [len(path) + 1] * (len(path) - 1)
    cuts = [None] * len(path)
    for end in range(1, len(path)):
        for begin in range(end):
            if box_safe(path[begin], path[end], relation, edges):
                if cost[begin] + 1 < cost[end]:
                    cost[end] = cost[begin] + 1; cuts[end] = begin
    indices = [len(path) - 1]
    while indices[-1]: indices.append(cuts[indices[-1]])
    return cost[-1], list(reversed(indices))


def compact_plan(answer):
    # The shared context stores immutable catalogs, factors and edge inputs
    # once. Query-specific returned witnesses, diagnostics and costs are kept.
    return {key: deepcopy(value) for key, value in answer.items()
            if key not in {'catalog', 'candidates', 'transitions', 'factors', 'structure', 'recognition'}}


def produce(output):
    from google.protobuf import __version__ as protobuf_version
    from src.schema_contracts import actual_probes
    from src.factored_planner import FactoredChainPlanner
    if output.exists() and any(output.iterdir()):
        raise ValueError('use an empty result directory')
    output.mkdir(parents=True, exist_ok=True)
    families = actual_probes()
    write(output / 'probes.json', families)
    contexts = [context(family, mask) for family in families for mask in range(1, 64)]
    write(output / 'contexts.json', contexts)
    environment = {'python': sys.version, 'platform': platform.platform(),
                   'protobuf': protobuf_version, 'owners': 3,
                   'graph_inventory': 'all 63 nonempty directed simple graphs on three labelled owners',
                   'query_inventory': 'all ordered compatible physical configurations in every context',
                   'counts_are': 'registered contract/topology instances; not sampled production deployments',
                   'source_sha256': {name: digest(ROOT / name) for name in SOURCE_NAMES}}
    for name in SOURCE_NAMES:
        destination = output / 'sources' / name; destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    write(output / 'environment.json', environment)
    # The directed three-cycle is also within the old eight-alternative global
    # DNF language. Retain its production frontier plan as an independent route.
    from src.goal_planner import GoalPlanner
    old_controls = []
    for family in families:
        if len(family['profiles']) != 4:
            continue
        ctx = context(family, 25)  # 0->1, 1->2, 2->0 in the fixed edge inventory.
        branches = []
        for local in itertools.product(*(factor['branches'] for factor in ctx['factors'])):
            branches.append({str(i): sorted({atom for branch in local
                                            for atom in branch.get(str(i), [])}) for i in range(3)})
        planner = GoalPlanner(branches, ctx['candidates'], ctx['transitions'])
        answer = planner.plan({str(i): family['profiles'][0] for i in range(3)},
                              {str(i): family['profiles'][-1] for i in range(3)})
        old_controls.append({'context': ctx['id'], 'answer': answer})
    write(output / 'frontier-cycle-controls.json', old_controls)
    total = 0
    orders = list(itertools.permutations(range(3)))
    for family in families:
        size = len(family['profiles']); relation = family['relation']
        family_count = 0
        with gzip.open(output / (family['family'] + '.jsonl.gz'), 'wt', encoding='utf-8') as stream:
            for ctx in [c for c in contexts if c['family'] == family['family']]:
                planner = FactoredChainPlanner(ctx['factors'], ctx['candidates'], ctx['transitions'])
                recognition = planner.recognition()
                if not recognition.get('recognized', False):
                    raise RuntimeError('measured factor was not recognized: ' + ctx['id'])
                write(output / 'recognition' / (ctx['id'] + '.json'), recognition)
                allowed = set(valid_states(relation, ctx['edges']))
                for source in sorted(allowed):
                    paths = {order: priority_paths(source, allowed, order) for order in orders}
                    for target in sorted(allowed):
                        answer = planner.plan({str(i): family['profiles'][source[i]] for i in range(3)},
                                              {str(i): family['profiles'][target[i]] for i in range(3)})
                        routes = []
                        for order in orders:
                            path = paths[order].get(target)
                            if path is None: phases, cuts = None, None
                            else: phases, cuts = partition_path(path, relation, ctx['edges'])
                            routes.append({'order': list(order), 'path': path, 'phases': phases, 'cuts': cuts})
                        stream.write(json.dumps({'context': ctx['id'], 'source': source, 'target': target,
                                                 'answer': compact_plan(answer), 'routes': routes},
                                                sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n')
                        family_count += 1
                print(json.dumps({'family': family['family'], 'graph': ctx['graph_mask'],
                                  'completed_family_queries': family_count}), flush=True)
        total += family_count
    write(output / 'inventory.json', {'families': len(families), 'contexts': len(contexts),
                                      'queries': total, 'priority_orders': [list(x) for x in orders]})
    print(json.dumps({'status': 'COLLECTED', 'queries': total, 'output': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); produce(args.out.resolve())
