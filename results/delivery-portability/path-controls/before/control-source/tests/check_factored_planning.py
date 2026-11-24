"""Reconstruct complete factored-planner evidence using an independent oracle."""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path

from tests.factored_planning_oracle import Oracle, require


ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = {'src/factored_planner.py', 'src/controller.py', 'src/envelope.py',
                'tests/factored_planning_study.py', 'tests/factored_planning_oracle.py',
                'tests/check_factored_planning.py', 'tests/factored_planning_regression.py',
                'tests/goal_planner_oracle.py'}


def read(path):
    return json.loads(path.read_text())


def expected_specs():
    specs = {}
    for family, shape, masks in [('ternary-pair', [3, 3], 511), ('binary-triple', [2, 2, 2], 255)]:
        for mask in range(1, masks + 1):
            specs[f'{family}-{mask}'] = (family, shape, [mask])
    for left, right in product(range(1, 16), repeat=2):
        specs[f'overlapping-binary-pairs-{left}-{right}'] = ('overlapping-binary-pairs',
                                                         [2, 2, 2], [left, right])
    return specs


def allowed(shape, mask):
    cells = list(product(*(range(q) for q in shape)))
    return {s for i, s in enumerate(cells) if mask & (1 << i)}


def model(context):
    oracle = Oracle(context['factors'], context['catalog'], context['transitions'])
    require([len(oracle.profiles[n]) for n in oracle.nodes] == context['shape'], "changed physical shape")
    if context['family'] == 'overlapping-binary-pairs':
        require(set(oracle.local_relations) == {'left', 'right'}, "overlap factor inventory")
        require(oracle.shapes['left'][0] == ['0', '1'] and oracle.shapes['right'][0] == ['1', '2'],
                "overlap shares a different physical owner")
        for name, mask in zip(('left', 'right'), context['masks']):
            require(oracle.local_relations[name] == allowed([2, 2], mask), "overlap factor relation changed")
    else:
        require(set(oracle.local_relations) == {'compatibility'}, "finite factor inventory")
        require(oracle.local_relations['compatibility'] == allowed(context['shape'], context['masks'][0]),
                "finite relation differs from registered mask")
    return oracle


def inventory(contexts, rows, oracles):
    expected = set()
    for context in contexts:
        if 'recognition' not in context:
            continue
        oracle = oracles[context['name']]
        states = list(oracle.graph())
        expected.update((context['name'], source, target) for source, target in product(states, repeat=2))
    observed = [(r['context'], tuple(r['source']), tuple(r['target'])) for r in rows]
    require(len(observed) == len(set(observed)), "duplicate query")
    require(set(observed) == expected, "complete query inventory differs")


def semantic_checks(contexts, rows):
    specs = expected_specs()
    require(len(contexts) == len(specs) and {c['name'] for c in contexts} == set(specs),
            "complete context inventory differs")
    groups = defaultdict(lambda: {'contexts': 0, 'recognized': 0, 'refused': 0, 'queries': 0,
                                  'planned_nontrivial': 0, 'noops': 0, 'unreachable': 0,
                                  'phases': 0, 'installations': 0})
    oracles, family = {}, {}
    for context in contexts:
        expected = specs[context['name']]
        require((context['family'], context['shape'], context['masks']) == expected, "context specification differs")
        oracle = model(context)
        oracles[context['name']] = oracle
        family[context['name']] = context['family']
        group = groups[context['family']]
        group['contexts'] += 1
        if oracle.closed():
            require('recognition' in context and 'refusal' not in context, "closed context was refused")
            oracle.check_recognition(context['recognition'])
            group['recognized'] += 1
        else:
            require('refusal' in context and 'recognition' not in context, "nonclosed context was recognized")
            oracle.check_refusal(context['refusal'])
            group['refused'] += 1
    inventory(contexts, rows, oracles)
    for row in rows:
        oracle = oracles[row['context']]
        oracle.check_plan(row['result'], tuple(row['source']), tuple(row['target']))
        result, group = row['result'], groups[family[row['context']]]
        group['queries'] += 1
        if result['status'] == 'unreachable':
            group['unreachable'] += 1
        elif result['cost']['installations'] == 0:
            group['noops'] += 1
        else:
            group['planned_nontrivial'] += 1
            group['phases'] += result['cost']['phases']
            group['installations'] += result['cost']['installations']
    summary = {'status': 'pass', 'contexts': len(contexts), 'groups': dict(groups),
               'recognized': sum(g['recognized'] for g in groups.values()),
               'refused': sum(g['refused'] for g in groups.values()), 'queries': len(rows)}
    return summary, oracles


def controls(contexts, rows, oracles):
    results = []

    def rejects(name, call):
        try:
            call()
        except (ValueError, KeyError, IndexError, TypeError):
            results.append({'name': name, 'rejected': True})
        else:
            raise ValueError('Failed corruption control: ' + name)

    base = next(r for r in rows if r['result']['phases'])
    oracle = oracles[base['context']]
    source, target = tuple(base['source']), tuple(base['target'])
    bad = deepcopy(base['result']); bad['cost']['phases'] += 1
    rejects('changed optimum', lambda: oracle.check_plan(bad, source, target))
    bad = deepcopy(base['result']); bad['phases'][0]['steps'].pop()
    rejects('missing physical installation', lambda: oracle.check_plan(bad, source, target))
    bad = deepcopy(base['result']); bad['phases'][0]['box']['0'] = [[]]
    rejects('unsafe positive guard', lambda: oracle.check_plan(bad, source, target))
    context = next(c for c in contexts if 'recognition' in c)
    bad = deepcopy(context['recognition']); bad['factors'][0]['axis_limits'][0]['upper'][0] = 999
    rejects('changed axis certificate', lambda: oracles[context['name']].check_recognition(bad))
    context = next(c for c in contexts if 'refusal' in c)
    bad = deepcopy(context['refusal']); bad['witness']['maximum'] = bad['witness']['first']
    rejects('false closure counterexample', lambda: oracles[context['name']].check_refusal(bad))
    rejects('missing query', lambda: inventory(contexts, rows[1:], oracles))
    context = deepcopy(next(c for c in contexts if c['family'] == 'overlapping-binary-pairs'))
    context['factors'].pop()
    rejects('missing overlapping factor', lambda: model(context))
    return results


def check(directory, corruption_controls=False):
    environment = read(directory / 'environment.json')
    require(set(environment['sources']) == SOURCE_NAMES, "source inventory differs")
    for name, expected in environment['sources'].items():
        for path in (ROOT / name, directory / 'sources' / name):
            require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "source differs: " + name)
    require(environment['inventory'] == {'ternary-pair': 511, 'binary-triple': 255,
                                          'overlapping-binary-pairs': 225}, "registered family inventory")
    with gzip.open(directory / 'contexts.json.gz', 'rt', encoding='utf-8') as handle:
        contexts = json.load(handle)
    with gzip.open(directory / 'plans.jsonl.gz', 'rt', encoding='utf-8') as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    summary, oracles = semantic_checks(contexts, rows)
    require(summary == read(directory / 'summary.json'), "stored summary differs from reconstruction")
    if corruption_controls:
        summary['corruption_controls'] = controls(contexts, rows, oracles)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--corruption-controls', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check(args.results, args.corruption_controls), sort_keys=True, indent=2))
