"""Complete small-relation study for locally certified factored planning."""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path
import platform

from src.factored_planner import FactoredChainPlanner, FactoredPlanningRefusal
from tests.goal_planner_oracle import relation_inputs, support_transitions


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ['src/factored_planner.py', 'src/controller.py', 'src/envelope.py',
           'tests/factored_planning_study.py', 'tests/factored_planning_oracle.py',
           'tests/check_factored_planning.py', 'tests/factored_planning_regression.py',
           'tests/goal_planner_oracle.py']


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def relation(shape, mask):
    return {s for i, s in enumerate(product(*(range(q) for q in shape))) if mask >> i & 1}


def simple_context(family, shape, mask):
    branches, catalog = relation_inputs(shape, relation(shape, mask))
    transitions = support_transitions(catalog, [{(i, i + 1) for i in range(q - 1)} for q in shape])
    return {'name': f'{family}-{mask}', 'family': family, 'shape': list(shape), 'masks': [mask],
            'factors': [{'id': 'compatibility', 'branches': branches}],
            'catalog': catalog, 'transitions': transitions}


def overlapping_context(left, right):
    catalog = {str(i): [[f'physical:{i}:{r}'] for r in range(2)] for i in range(3)}
    factors = []
    for identity, scope, mask in [('left', ('0', '1'), left), ('right', ('1', '2'), right)]:
        branches, local = relation_inputs((2, 2), relation((2, 2), mask))
        factors.append({'id': identity, 'branches': [
            {n: [identity + ':' + a for a in branch[str(i)]] for i, n in enumerate(scope)}
            for branch in branches]})
        for i, n in enumerate(scope):
            for rank in range(2):
                catalog[n][rank].extend(identity + ':' + a for a in local[str(i)][rank])
    catalog = {n: [sorted(p) for p in profiles] for n, profiles in catalog.items()}
    transitions = {n: [{'source': p[0], 'target': p[1]}] for n, p in catalog.items()}
    return {'name': f'overlapping-binary-pairs-{left}-{right}', 'family': 'overlapping-binary-pairs',
            'shape': [2, 2, 2], 'masks': [left, right], 'factors': factors,
            'catalog': catalog, 'transitions': transitions}


def contexts():
    for family, shape in [('ternary-pair', (3, 3)), ('binary-triple', (2, 2, 2))]:
        for mask in range(1, 1 << (len(list(product(*(range(q) for q in shape)))))):
            yield simple_context(family, shape, mask)
    for left, right in product(range(1, 16), repeat=2):
        yield overlapping_context(left, right)


def external(context, state):
    return {str(i): context['catalog'][str(i)][r] for i, r in enumerate(state)}


def compatible(context, ranks):
    supports = {n: set(p) for n, p in external(context, ranks).items()}
    return all(any(all(set(req) <= supports[n] for n, req in branch.items())
                   for branch in f['branches']) for f in context['factors'])


def summarize(context_rows, outcomes):
    groups = defaultdict(lambda: {'contexts': 0, 'recognized': 0, 'refused': 0, 'queries': 0,
                                  'planned_nontrivial': 0, 'noops': 0, 'unreachable': 0,
                                  'phases': 0, 'installations': 0})
    family = {c['name']: c['family'] for c in context_rows}
    for context in context_rows:
        group = groups[context['family']]
        group['contexts'] += 1
        group['recognized' if 'recognition' in context else 'refused'] += 1
    for name, result in outcomes:
        group = groups[family[name]]
        group['queries'] += 1
        if result['status'] == 'unreachable':
            group['unreachable'] += 1
        elif result['cost']['installations'] == 0:
            group['noops'] += 1
        else:
            group['planned_nontrivial'] += 1
            group['phases'] += result['cost']['phases']
            group['installations'] += result['cost']['installations']
    return {'status': 'pass', 'contexts': len(context_rows), 'groups': dict(groups),
            'recognized': sum(g['recognized'] for g in groups.values()),
            'refused': sum(g['refused'] for g in groups.values()), 'queries': len(outcomes)}


def produce(output):
    if output.exists():
        raise ValueError('Use a new study directory')
    output.mkdir(parents=True)
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}
    for name in sources:
        p = output / 'sources' / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((ROOT / name).read_bytes())
    context_rows, outcomes = [], []
    with gzip.open(output / 'plans.jsonl.gz', 'wt', encoding='utf-8') as handle:
        for context in contexts():
            try:
                planner = FactoredChainPlanner(context['factors'], context['catalog'], context['transitions'])
            except FactoredPlanningRefusal as exc:
                context['refusal'] = {'reason': exc.reason, 'witness': exc.witness}
                context_rows.append(context)
                continue
            context['recognition'] = planner.recognition()
            context_rows.append(context)
            allowed = [s for s in product(*(range(q) for q in context['shape'])) if compatible(context, s)]
            for source, target in product(allowed, repeat=2):
                plan = planner.plan(external(context, source), external(context, target))
                result = {name: deepcopy(plan[name]) for name in
                          ('initial', 'target', 'status', 'cost', 'phases', 'search')}
                if 'reason' in plan:
                    result['reason'] = plan['reason']
                row = {'context': context['name'], 'source': list(source), 'target': list(target),
                       'result': result}
                handle.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
                outcomes.append((context['name'], {'status': result['status'], 'cost': result['cost']}))
    with gzip.open(output / 'contexts.json.gz', 'wt', encoding='utf-8') as handle:
        json.dump(context_rows, handle, sort_keys=True, separators=(',', ':'))
    for name, expected in sources.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Source changed during campaign: ' + name)
    summary = summarize(context_rows, outcomes)
    write(output / 'summary.json', summary)
    write(output / 'environment.json', {'python': platform.python_version(),
        'platform': platform.platform(), 'sources': sources,
        'scope': 'complete finite relation and overlapping-factor oracle campaign; no execution latency measurement',
        'inventory': {'ternary-pair': 511, 'binary-triple': 255, 'overlapping-binary-pairs': 225}})
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    produce(parser.parse_args().out)
